"""Robot Bridge client — talks to the K1 Robot Bridge server over HTTP.

This module provides three classes that plug directly into the orchestrator:
  - RobotBridgeClient   : raw HTTP calls (health, state, frame, speak, record, velocity, stop)
  - BridgeVideoSource   : implements BaseVideoSource using the bridge /frame endpoint
  - BridgeAudioIO       : implements AudioIO using the bridge /speak and /record endpoints

Usage:
    from himpublic.io.robot_client import RobotBridgeClient, BridgeVideoSource, BridgeAudioIO

    client = RobotBridgeClient("http://192.168.10.102:9090")
    video  = BridgeVideoSource(client)
    audio  = BridgeAudioIO(client)
"""

from __future__ import annotations

import logging
import os
import tempfile
from typing import Any

import requests

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Low-level HTTP client
# ---------------------------------------------------------------------------
class RobotBridgeClient:
    """HTTP client for the Robot Bridge server running on the K1."""

    def __init__(
        self,
        base_url: str = "http://192.168.10.102:9090",
        timeout: int = 10,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._connected = False
        self._last_health: dict[str, Any] = {}

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def connected(self) -> bool:
        return self._connected

    # ── health / connectivity ───────────────────────────────────────

    def health(self) -> dict[str, Any]:
        """GET /health — lightweight heartbeat."""
        try:
            resp = requests.get(f"{self._base_url}/health", timeout=self._timeout)
            resp.raise_for_status()
            self._connected = True
            self._last_health = resp.json()
            return self._last_health
        except Exception as e:
            self._connected = False
            return {"status": "unreachable", "error": str(e)}

    # ── state / telemetry ───────────────────────────────────────────

    def get_state(self) -> dict[str, Any]:
        """GET /state — robot telemetry."""
        try:
            resp = requests.get(f"{self._base_url}/state", timeout=self._timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.warning("get_state failed: %s", e)
            return {"error": str(e)}

    # ── camera ──────────────────────────────────────────────────────

    def get_frame_jpeg(self, quality: int = 80) -> bytes | None:
        """GET /frame — returns raw JPEG bytes or None."""
        try:
            resp = requests.get(
                f"{self._base_url}/frame",
                params={"quality": quality},
                timeout=self._timeout,
            )
            if resp.status_code == 503:
                return None
            resp.raise_for_status()
            return resp.content
        except Exception as e:
            logger.warning("get_frame_jpeg failed: %s", e)
            return None

    def get_frame_numpy(self, quality: int = 80):
        """GET /frame — returns BGR numpy array or None.  Requires cv2+numpy."""
        import cv2
        import numpy as np

        jpeg = self.get_frame_jpeg(quality=quality)
        if jpeg is None:
            return None
        arr = np.frombuffer(jpeg, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        return frame

    # ── audio: speak ────────────────────────────────────────────────

    def speak(self, text: str) -> bool:
        """POST /speak — robot says text through speaker.  Returns True on success."""
        try:
            resp = requests.post(
                f"{self._base_url}/speak",
                json={"text": text},
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json().get("status") == "ok"
        except Exception as e:
            logger.warning("speak failed: %s", e)
            return False

    def play_audio(self, wav_bytes: bytes) -> bool:
        """POST /play_audio — play raw WAV through speaker.  Returns True on success."""
        try:
            resp = requests.post(
                f"{self._base_url}/play_audio",
                data=wav_bytes,
                headers={"Content-Type": "audio/wav"},
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json().get("status") == "ok"
        except Exception as e:
            logger.warning("play_audio failed: %s", e)
            return False

    # ── audio: record ───────────────────────────────────────────────

    def record(self, duration_s: float = 5.0) -> bytes:
        """POST /record — record from mic, returns WAV bytes (may be empty on failure)."""
        try:
            resp = requests.post(
                f"{self._base_url}/record",
                json={"duration_s": duration_s},
                timeout=duration_s + 15,
            )
            if resp.status_code == 503:
                return b""
            resp.raise_for_status()
            return resp.content
        except Exception as e:
            logger.warning("record failed: %s", e)
            return b""

    # ── motion (gated by bridge server) ─────────────────────────────

    def set_velocity(self, vx: float, wz: float) -> bool:
        """POST /velocity — send motion command.  Returns False if motion is disabled."""
        try:
            resp = requests.post(
                f"{self._base_url}/velocity",
                json={"vx": vx, "wz": wz},
                timeout=self._timeout,
            )
            if resp.status_code == 403:
                logger.warning("Motion is disabled on the bridge server")
                return False
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.warning("set_velocity failed: %s", e)
            return False

    def stop(self) -> bool:
        """POST /stop — emergency stop (always allowed)."""
        try:
            resp = requests.post(f"{self._base_url}/stop", timeout=self._timeout)
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.warning("stop failed: %s", e)
            return False

    def wave(self, hand: str = "right", cycles: int = 2) -> bool:
        """POST /wave — safe hand wave gesture (no walking).  Returns True on success."""
        try:
            resp = requests.post(
                f"{self._base_url}/wave",
                json={"hand": hand, "cycles": cycles},
                timeout=15,
            )
            resp.raise_for_status()
            result = resp.json()
            return result.get("status") in ("ok", "partial")
        except Exception as e:
            logger.warning("wave failed: %s", e)
            return False


# ---------------------------------------------------------------------------
# Pipeline adapters
# ---------------------------------------------------------------------------


def _get_base_video_source():
    """Lazy import to avoid pulling cv2/numpy when only using RobotBridgeClient."""
    from himpublic.io.video_source import BaseVideoSource
    return BaseVideoSource


class BridgeVideoSource:
    """VideoSource that fetches frames from the Robot Bridge /frame endpoint.

    Implements BaseVideoSource protocol (read / release).
    """

    def __init__(self, client: RobotBridgeClient, quality: int = 80) -> None:
        self._client = client
        self._quality = quality
        logger.info("BridgeVideoSource: bridge at %s", client.base_url)

    def read(self):
        """Return next frame as BGR numpy array, or None on error."""
        return self._client.get_frame_numpy(quality=self._quality)

    def release(self) -> None:
        logger.debug("BridgeVideoSource: released (no-op — bridge owns camera)")


class BridgeAudioIO:
    """AudioIO adapter that uses the Robot Bridge for TTS (speaker) and ASR (mic).

    speak()  → POST /speak to bridge  (espeak on robot)
    listen() → POST /record to bridge  (arecord on robot) → local ASR on laptop
    """

    def __init__(self, client: RobotBridgeClient, *, use_local_asr: bool = True) -> None:
        self._client = client
        self._use_local_asr = use_local_asr
        self._last_speak_done: float = 0.0  # monotonic timestamp when last speak() finished
        logger.info("BridgeAudioIO: bridge at %s, local_asr=%s", client.base_url, use_local_asr)

    def speak(self, text: str) -> None:
        """Play text through robot speaker via bridge.  Blocks until TTS playback finishes."""
        import time as _time
        logger.info("BridgeAudioIO.speak: %s", text[:80])
        ok = self._client.speak(text)
        self._last_speak_done = _time.monotonic()
        if not ok:
            logger.warning("Bridge /speak failed — printing to console as fallback")
            print(f"[TTS-BRIDGE-FALLBACK] {text}", flush=True)

    def listen(self, timeout_s: float) -> str | None:
        """Record from robot mic, then run ASR locally.

        Waits for TTS to finish + a 1s buffer before recording, so the robot
        doesn't hear itself speaking.

        Returns transcript or None on timeout / no speech / failure.
        """
        import time as _time

        # Wait until at least 1s after the last speak() completed
        if self._last_speak_done > 0:
            since_speak = _time.monotonic() - self._last_speak_done
            gap = 1.0  # seconds to wait after TTS finishes before recording
            if since_speak < gap:
                wait = gap - since_speak
                logger.debug("Waiting %.1fs for TTS echo to clear before recording", wait)
                _time.sleep(wait)

        logger.debug("BridgeAudioIO.listen(%.1fs) — recording from robot mic", timeout_s)
        print(f"[Listening] Recording from robot mic ({timeout_s:.0f}s)...", flush=True)
        wav_bytes = self._client.record(duration_s=timeout_s)
        if not wav_bytes:
            logger.warning("BridgeAudioIO: recording returned empty")
            return None

        if self._use_local_asr:
            transcript = self._asr_from_wav(wav_bytes)
            if transcript:
                logger.info("Heard (bridge): %s", transcript)
                print(f"[Heard] {transcript}", flush=True)
            return transcript

        # If no local ASR, save WAV and ask user to type
        logger.warning("No ASR available — returning None")
        return None

    @staticmethod
    def _asr_from_wav(wav_bytes: bytes) -> str | None:
        """Run ASR on WAV bytes using speech_recognition (Google)."""
        try:
            import speech_recognition as sr
        except ImportError:
            logger.warning(
                "speech_recognition not installed — pip install SpeechRecognition"
            )
            return None

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(wav_bytes)
                tmp_path = f.name

            recognizer = sr.Recognizer()
            with sr.AudioFile(tmp_path) as source:
                audio = recognizer.record(source)
            text = recognizer.recognize_google(audio)
            return text.strip() or None
        except sr.UnknownValueError:
            return None
        except sr.RequestError as e:
            logger.warning("Google ASR request error: %s", e)
            return None
        except Exception as e:
            logger.warning("ASR failed: %s", e)
            return None
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
