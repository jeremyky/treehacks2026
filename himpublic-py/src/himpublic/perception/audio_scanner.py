"""Audio-guided direction scanner: spin-to-peak-loudness approach.

In demo mode we sweep virtual angles and measure mic loudness per window.
In robot mode we call robot.turn_in_place() while sampling audio.

Gracefully degrades when sounddevice or webrtcvad are unavailable.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

logger = logging.getLogger(__name__)

# ── Optional imports (graceful degradation) ──────────────────────────
_HAS_SOUNDDEVICE = False
_HAS_WEBRTCVAD = False

try:
    import sounddevice as sd  # type: ignore
    _HAS_SOUNDDEVICE = True
except ImportError:
    sd = None  # type: ignore

try:
    import webrtcvad  # type: ignore
    _HAS_WEBRTCVAD = True
except ImportError:
    webrtcvad = None  # type: ignore


# ── Data types ───────────────────────────────────────────────────────
@dataclass
class AudioSample:
    """One sample taken during audio scan."""
    angle_deg: float
    rms: float
    log_energy: float
    vad_score: float  # 0.0 or 1.0 from webrtcvad, or energy-based fallback
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "angle_deg": round(self.angle_deg, 1),
            "rms": round(self.rms, 6),
            "log_energy": round(self.log_energy, 4),
            "vad_score": round(self.vad_score, 2),
            "timestamp": self.timestamp,
        }


@dataclass
class AudioScanResult:
    """Result of a full 360-degree audio scan."""
    chosen_angle_deg: float
    peak_rms: float
    peak_log_energy: float
    confidence: float  # 0..1 how confident we are in the chosen angle
    samples: list[AudioSample] = field(default_factory=list)
    scan_duration_s: float = 0.0

    def to_dict(self) -> dict:
        return {
            "chosen_angle_deg": round(self.chosen_angle_deg, 1),
            "peak_rms": round(self.peak_rms, 6),
            "peak_log_energy": round(self.peak_log_energy, 4),
            "confidence": round(self.confidence, 3),
            "num_samples": len(self.samples),
            "scan_duration_s": round(self.scan_duration_s, 2),
        }


# ── Audio helpers ────────────────────────────────────────────────────
SAMPLE_RATE = 16000  # 16 kHz (common for VAD)
CHANNELS = 1


def compute_rms(audio: np.ndarray) -> float:
    """Root-mean-square of audio signal."""
    if audio.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))


def compute_log_energy(audio: np.ndarray) -> float:
    """Log energy (dB-like) of audio signal."""
    rms = compute_rms(audio)
    if rms < 1e-10:
        return -100.0
    return float(20.0 * math.log10(rms))


def compute_vad_score(audio_int16: np.ndarray, sample_rate: int = SAMPLE_RATE) -> float:
    """Voice Activity Detection score using webrtcvad.

    Falls back to energy-based threshold if webrtcvad unavailable.
    Returns 0.0 (no voice) or 1.0 (voice detected), or fraction for energy-based.
    """
    if _HAS_WEBRTCVAD and webrtcvad is not None:
        try:
            vad = webrtcvad.Vad(2)  # aggressiveness 0-3
            # webrtcvad needs 10/20/30ms frames of 16-bit PCM at 8/16/32/48kHz
            frame_duration_ms = 30
            frame_size = int(sample_rate * frame_duration_ms / 1000)
            data = audio_int16.tobytes()
            voiced_count = 0
            total_count = 0
            for i in range(0, len(data) - frame_size * 2, frame_size * 2):
                chunk = data[i : i + frame_size * 2]
                if len(chunk) < frame_size * 2:
                    break
                try:
                    if vad.is_speech(chunk, sample_rate):
                        voiced_count += 1
                except Exception:
                    pass
                total_count += 1
            if total_count == 0:
                return 0.0
            return voiced_count / total_count
        except Exception as e:
            logger.debug("webrtcvad failed, falling back to energy: %s", e)

    # Energy-based fallback
    rms = compute_rms(audio_int16.astype(np.float64))
    # Typical speech RMS for int16 is ~500-5000; quiet room is ~50-200
    threshold = 300.0
    if rms > threshold * 3:
        return 1.0
    elif rms > threshold:
        return float(min(1.0, (rms - threshold) / (threshold * 2)))
    return 0.0


def record_audio_window(duration_s: float = 0.3) -> np.ndarray | None:
    """Record a short audio window from the default microphone.

    Returns int16 numpy array, or None if sounddevice unavailable.
    """
    if not _HAS_SOUNDDEVICE or sd is None:
        return None
    try:
        samples = int(SAMPLE_RATE * duration_s)
        audio = sd.rec(samples, samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="int16")
        sd.wait()
        return audio.flatten()
    except Exception as e:
        logger.warning("Failed to record audio: %s", e)
        return None


# ── Audio Scanner ────────────────────────────────────────────────────
class AudioScanner:
    """Performs a 360-degree audio scan to find the direction of the loudest sound.

    In demo mode: sweeps virtual angles with a delay, recording mic audio at each step.
    In robot mode: calls robot turn functions while recording.
    """

    def __init__(
        self,
        *,
        step_degrees: float = 30.0,
        window_duration_s: float = 0.4,
        smoothing_window: int = 3,
        min_confidence_rms: float = 0.001,
        on_sample: Callable[[AudioSample], None] | None = None,
    ) -> None:
        self.step_degrees = step_degrees
        self.window_duration_s = window_duration_s
        self.smoothing_window = smoothing_window
        self.min_confidence_rms = min_confidence_rms
        self._on_sample = on_sample  # callback for logging each sample

    def scan_demo(
        self,
        *,
        delay_between_steps_s: float = 0.5,
        stop_check: Callable[[], bool] | None = None,
    ) -> AudioScanResult:
        """Run audio scan in laptop demo mode.

        Sweeps 0..360 degrees virtually, recording mic audio at each step.
        If mic unavailable, generates synthetic samples for demonstration.
        """
        t0 = time.time()
        samples: list[AudioSample] = []
        n_steps = int(360.0 / self.step_degrees)

        logger.info("Audio scan starting: %d steps of %.0f deg, window=%.1fs",
                     n_steps, self.step_degrees, self.window_duration_s)

        for i in range(n_steps):
            if stop_check and stop_check():
                break

            angle = i * self.step_degrees
            audio = record_audio_window(self.window_duration_s)

            if audio is not None and audio.size > 0:
                rms = compute_rms(audio.astype(np.float64))
                log_e = compute_log_energy(audio.astype(np.float64))
                vad = compute_vad_score(audio)
            else:
                # No mic: generate synthetic quiet baseline so demo still runs
                rms = 0.0001 + np.random.random() * 0.0001
                log_e = compute_log_energy(np.array([rms * 32767], dtype=np.float64))
                vad = 0.0

            sample = AudioSample(
                angle_deg=angle,
                rms=rms,
                log_energy=log_e,
                vad_score=vad,
            )
            samples.append(sample)
            if self._on_sample:
                self._on_sample(sample)
            logger.debug("Audio sample @ %.0f deg: rms=%.6f vad=%.2f", angle, rms, vad)

            time.sleep(delay_between_steps_s)

        return self._pick_best(samples, time.time() - t0)

    def scan_robot(
        self,
        *,
        turn_fn: Callable[[float], None],
        stop_fn: Callable[[], None],
        stop_check: Callable[[], bool] | None = None,
    ) -> AudioScanResult:
        """Run audio scan in robot mode.

        Args:
            turn_fn: Call to turn robot by given degrees (positive = left).
            stop_fn: Call to stop robot motion.
            stop_check: If returns True, abort scan early.
        """
        t0 = time.time()
        samples: list[AudioSample] = []
        n_steps = int(360.0 / self.step_degrees)

        logger.info("Audio scan (robot): %d steps of %.0f deg", n_steps, self.step_degrees)

        for i in range(n_steps):
            if stop_check and stop_check():
                break

            angle = i * self.step_degrees

            # Record audio while stationary
            audio = record_audio_window(self.window_duration_s)
            if audio is not None and audio.size > 0:
                rms = compute_rms(audio.astype(np.float64))
                log_e = compute_log_energy(audio.astype(np.float64))
                vad = compute_vad_score(audio)
            else:
                rms = 0.0
                log_e = -100.0
                vad = 0.0

            sample = AudioSample(angle_deg=angle, rms=rms, log_energy=log_e, vad_score=vad)
            samples.append(sample)
            if self._on_sample:
                self._on_sample(sample)

            # Turn to next angle
            if i < n_steps - 1:
                turn_fn(self.step_degrees)
                time.sleep(0.1)  # brief settle

        stop_fn()
        return self._pick_best(samples, time.time() - t0)

    def _pick_best(self, samples: list[AudioSample], duration_s: float) -> AudioScanResult:
        """Pick the best heading from collected samples using smoothed peak loudness."""
        if not samples:
            return AudioScanResult(
                chosen_angle_deg=0.0, peak_rms=0.0, peak_log_energy=-100.0,
                confidence=0.0, samples=[], scan_duration_s=duration_s,
            )

        # Compute composite score: combine RMS and VAD
        scores = []
        for s in samples:
            # Weighted composite: high RMS with VAD detected scores best
            composite = s.rms * (1.0 + s.vad_score)
            scores.append(composite)

        # Smooth scores with a sliding window
        n = len(scores)
        w = min(self.smoothing_window, n)
        smoothed = []
        for i in range(n):
            # Circular smoothing for 360-degree wrap
            window_vals = []
            for j in range(-(w // 2), w // 2 + 1):
                idx = (i + j) % n
                window_vals.append(scores[idx])
            smoothed.append(sum(window_vals) / len(window_vals))

        best_idx = int(np.argmax(smoothed))
        best_sample = samples[best_idx]

        # Confidence: ratio of best to mean, clamped [0, 1]
        mean_score = sum(scores) / len(scores) if scores else 1e-10
        if mean_score < 1e-10:
            confidence = 0.0
        else:
            ratio = smoothed[best_idx] / mean_score
            # ratio > 1 means louder than average; map to [0, 1]
            confidence = min(1.0, max(0.0, (ratio - 1.0) / 3.0))

        # If the best RMS is below noise floor, confidence is very low
        if best_sample.rms < self.min_confidence_rms:
            confidence = 0.0

        result = AudioScanResult(
            chosen_angle_deg=best_sample.angle_deg,
            peak_rms=best_sample.rms,
            peak_log_energy=best_sample.log_energy,
            confidence=confidence,
            samples=samples,
            scan_duration_s=duration_s,
        )
        logger.info(
            "Audio scan done: chosen_angle=%.0f deg, peak_rms=%.6f, confidence=%.3f (%.1fs)",
            result.chosen_angle_deg, result.peak_rms, result.confidence, duration_s,
        )
        return result
