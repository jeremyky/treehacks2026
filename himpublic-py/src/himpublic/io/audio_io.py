"""Audio I/O abstraction - TTS + ASR. Local devices now, robot placeholder later."""

from __future__ import annotations

import logging
import subprocess
import sys
from abc import ABC, abstractmethod
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class AudioIO(Protocol):
    """Protocol for TTS + ASR. Implementations: LocalAudioIO, RobotAudioIO."""

    def speak(self, text: str) -> None:
        """Play text as speech."""
        ...

    def listen(self, timeout_s: float) -> str | None:
        """Listen for speech, return transcript or None on timeout."""
        ...


def _listen_microphone(timeout_s: float) -> str | None:
    """Use speech_recognition + PyAudio to listen from default mic. Returns transcript or None.
    Raises ImportError if speech_recognition or mic not available.
    """
    import speech_recognition as sr  # raises ImportError if not installed
    r = sr.Recognizer()
    with sr.Microphone() as source:
        r.adjust_for_ambient_noise(source, duration=0.3)
        logger.debug("Listening from microphone (timeout %.1fs)...", timeout_s)
        try:
            audio = r.listen(source, timeout=timeout_s, phrase_time_limit=min(timeout_s, 10.0))
        except sr.WaitTimeoutError:
            return None
    try:
        text = r.recognize_google(audio)
        return text.strip() or None
    except sr.UnknownValueError:
        return None
    except sr.RequestError as e:
        logger.warning("Speech recognition request failed: %s", e)
        return None


# Slower speech rate (words per minute). Default pyttsx3 is often ~200; ~130 is calmer.
TTS_RATE_WPM = 130


def _speak_system_say(text: str) -> bool:
    """Use macOS 'say' command when pyttsx3 fails. Returns True if spoken. Uses slower rate."""
    if sys.platform != "darwin":
        return False
    try:
        subprocess.run(
            ["say", "-r", str(TTS_RATE_WPM), text],
            check=True,
            timeout=60,
            capture_output=True,
        )
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.CalledProcessError) as e:
        logger.debug("System 'say' failed: %s", e)
        return False


class LocalAudioIO:
    """Local TTS (log/print or pyttsx3) + ASR (stdin or microphone)."""

    def __init__(self, *, use_tts: bool = True, use_mic: bool = True) -> None:
        """use_tts: if True and pyttsx3 available, use it; else print.
        use_mic: if True, try to listen from microphone (speech_recognition); else stdin only.
        """
        self._use_tts = use_tts
        self._use_mic = use_mic

    def speak(self, text: str) -> None:
        """Log and print. Use pyttsx3 at slower rate; on failure use macOS 'say' fallback."""
        logger.info("TTS: %s", text)
        if self._use_tts:
            try:
                import pyttsx3
                engine = pyttsx3.init()
                try:
                    engine.setProperty("rate", TTS_RATE_WPM)
                except Exception:
                    pass
                engine.say(text)
                engine.runAndWait()
                return
            except Exception as e:
                logger.warning("pyttsx3 TTS failed: %s — trying fallback.", e)
                if _speak_system_say(text):
                    return
                print(f"[TTS] (voice unavailable: {e}) {text}", flush=True)
                return
        print(f"[TTS] {text}", flush=True)

    def listen(self, timeout_s: float) -> str | None:
        """
        Listen for response: from microphone (if use_mic and speech_recognition available) or stdin.
        Returns transcript or None on timeout/no speech.
        """
        if self._use_mic:
            try:
                print(f"[Listening] Speak now (mic, timeout {timeout_s:.0f}s)...", flush=True)
                transcript = _listen_microphone(timeout_s)
                if transcript:
                    logger.info("Heard: %s", transcript)
                    print(f"[Heard] {transcript}", flush=True)
                return transcript
            except ImportError:
                logger.warning(
                    "Microphone not available (pip install SpeechRecognition PyAudio). Using keyboard."
                )
                print("[Listening] Mic unavailable — type your response and press Enter.", flush=True)
                self._use_mic = False
            except Exception as e:
                logger.warning("Microphone listen failed: %s. Using keyboard.", e)
                self._use_mic = False
        # Stdin fallback
        logger.info("Listening for response (type and press Enter within %.1fs)", timeout_s)
        print(f"[Listening] Type your response and press Enter (timeout {timeout_s:.0f}s)...", flush=True)
        try:
            import select
            if sys.platform != "win32":
                r, _, _ = select.select([sys.stdin], [], [], timeout_s)
                if r:
                    line = sys.stdin.readline()
                    transcript = line.strip() or None
                    if transcript:
                        logger.info("Heard: %s", transcript)
                        print(f"[Heard] {transcript}", flush=True)
                    return transcript
            return None
        except (ImportError, OSError, ValueError):
            return None


class RobotAudioIO:
    """Placeholder for robot TTS/ASR. Raises NotImplementedError."""

    def speak(self, text: str) -> None:
        logger.debug("RobotAudioIO.speak(%r)", text)
        raise NotImplementedError(
            "RobotAudioIO: robot TTS not yet implemented. Use --io local."
        )

    def listen(self, timeout_s: float) -> str | None:
        logger.debug("RobotAudioIO.listen(timeout_s=%s)", timeout_s)
        raise NotImplementedError(
            "RobotAudioIO: robot ASR not yet implemented. Use --io local."
        )
