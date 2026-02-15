#!/usr/bin/env python3
"""
Robot Bridge Server — runs ON the Booster K1 robot.

Exposes a simple HTTP API so the laptop-side orchestrator can:
  - read telemetry / state  (GET  /state,  GET /health)
  - grab camera frames      (GET  /frame)
  - play speech on speaker   (POST /speak)
  - record from microphone   (POST /record)
  - send motion commands     (POST /velocity, POST /stop)  — gated by --allow-motion

Quick start (on robot via SSH):
  # 1) Install deps
  pip3 install fastapi uvicorn python-multipart --user

  # 2) Source ROS2 (REQUIRED for camera — perception service owns /dev/video*)
  source /opt/ros/humble/setup.bash

  # 3) Run
  python3 server.py                         # read-only, motion disabled
  python3 server.py --allow-motion          # enable motion (careful!)

Camera strategy:
  The booster-daemon-perception.service holds exclusive V4L2 access to /dev/video32/33.
  We read frames via ROS2 topic subscription instead (the perception service publishes them).
  Topic: /booster_camera_bridge/StereoNetNode/rectified_image  (YUV NV12 format)

  If ROS2 is not available, falls back to V4L2 (only works if perception service is stopped).
"""

from __future__ import annotations

import argparse
import base64
import logging
import os
import subprocess
import tempfile
import threading
import time
from typing import Any

import cv2
import numpy as np

logger = logging.getLogger("robot_bridge")

# ---------------------------------------------------------------------------
# Booster SDK discovery (best-effort, not required for read-only operation)
# ---------------------------------------------------------------------------
SDK_AVAILABLE = False
_sdk = None
_loco_client = None  # B1LocoClient instance (initialized lazily)
_sdk_initialized = False
try:
    import booster_robotics_sdk_python as _sdk_mod
    _sdk = _sdk_mod
    SDK_AVAILABLE = True
except ImportError:
    pass


def _ensure_sdk_init(network_interface: str = "") -> bool:
    """Initialize ChannelFactory + B1LocoClient once.  Returns True on success."""
    global _loco_client, _sdk_initialized
    if _sdk_initialized:
        return _loco_client is not None
    _sdk_initialized = True
    if not SDK_AVAILABLE or _sdk is None:
        logger.warning("SDK not available — hand/motion commands disabled")
        return False
    try:
        logger.info("Initializing SDK: domain_id=0, network_interface=%r", network_interface)
        _sdk.ChannelFactory.Instance().Init(0, network_interface)
        _loco_client = _sdk.B1LocoClient()
        _loco_client.Init()
        logger.info("Booster SDK initialized (ChannelFactory + B1LocoClient)")
        return True
    except Exception as e:
        import traceback
        logger.error("SDK init failed: %s\n%s", e, traceback.format_exc())
        _loco_client = None
        return False


def _discover_hand_type():
    """Discover available B1HandType enum value from the robot's SDK version."""
    if _sdk is None:
        return None
    # Try known hand type enums — the robot tells us which via the error signature
    for name in ["kInspireHand", "kDexHand", "kGripperHand"]:
        val = getattr(_sdk.B1HandType, name, None)
        if val is not None:
            logger.info("Using hand type: B1HandType.%s", name)
            return val
    # Last resort: try enum value 0
    try:
        val = _sdk.B1HandType(0)
        logger.info("Using hand type: B1HandType(%d) = %s", 0, val)
        return val
    except Exception:
        pass
    logger.error("Could not discover any B1HandType value!")
    return None


_HAND_TYPE = None  # resolved lazily


def _get_hand_type():
    global _HAND_TYPE
    if _HAND_TYPE is None:
        _HAND_TYPE = _discover_hand_type()
    return _HAND_TYPE


def _hand_open_fingers(hand_index) -> int:
    """Open all fingers (paper gesture) on the given hand.  Returns SDK error code.

    Robot SDK signature (from error):
      ControlDexterousHand(finger_params, hand_index, hand_type) -> int
    Each finger: DexterousFingerParameter with seq, angle (1000=open), force, speed.
    """
    if _loco_client is None or _sdk is None:
        return -1
    hand_type = _get_hand_type()
    if hand_type is None:
        logger.error("Cannot control hand: no valid B1HandType found")
        return -1
    finger_params = []
    # finger sequences: 0,1,2,3,3,5  (from SDK b1_loco_example_client.py hand_paper)
    for seq in [0, 1, 2, 3, 3, 5]:
        fp = _sdk.DexterousFingerParameter()
        fp.seq = seq
        fp.angle = 1000  # fully open
        fp.force = 200
        fp.speed = 800
        finger_params.append(fp)
    return _loco_client.ControlDexterousHand(finger_params, hand_index, hand_type)


def _hand_close_fingers(hand_index) -> int:
    """Close all fingers (rock/fist gesture) on the given hand.  Returns SDK error code.

    Robot SDK signature (from error):
      ControlDexterousHand(finger_params, hand_index, hand_type) -> int
    Each finger: DexterousFingerParameter with seq, angle (0=closed), force, speed.
    """
    if _loco_client is None or _sdk is None:
        return -1
    hand_type = _get_hand_type()
    if hand_type is None:
        logger.error("Cannot control hand: no valid B1HandType found")
        return -1
    finger_params = []
    for seq in [0, 1, 2, 3, 3, 5]:
        fp = _sdk.DexterousFingerParameter()
        fp.seq = seq
        fp.angle = 0  # fully closed
        fp.force = 200
        fp.speed = 800
        finger_params.append(fp)
    return _loco_client.ControlDexterousHand(finger_params, hand_index, hand_type)


def do_wave(hand: str = "right", cycles: int = 2) -> dict:
    """Perform a wave gesture: open-close-open the hand.  Safe, no walking."""
    if not _ensure_sdk_init():
        return {"status": "error", "detail": "SDK not initialized"}

    hand_index = _sdk.B1HandIndex.kRightHand if hand == "right" else _sdk.B1HandIndex.kLeftHand
    errors = []
    for i in range(cycles):
        res = _hand_open_fingers(hand_index)
        if res != 0:
            errors.append(f"open_{i}={res}")
        time.sleep(0.4)
        res = _hand_close_fingers(hand_index)
        if res != 0:
            errors.append(f"close_{i}={res}")
        time.sleep(0.4)
    # End with hand open (friendly)
    res = _hand_open_fingers(hand_index)
    if res != 0:
        errors.append(f"final_open={res}")

    if errors:
        return {"status": "partial", "hand": hand, "cycles": cycles, "errors": errors}
    return {"status": "ok", "hand": hand, "cycles": cycles}


# ---------------------------------------------------------------------------
# Camera backend: ROS2 subscriber (preferred)
# ---------------------------------------------------------------------------
ROS2_IMAGE_TOPIC = "/StereoNetNode/rectified_image"
ROS2_DEPTH_TOPIC = "/StereoNetNode/stereonet_depth"

ROS2_AVAILABLE = False
try:
    import rclpy
    from rclpy.node import Node
    from sensor_msgs.msg import Image as RosImage
    ROS2_AVAILABLE = True
except ImportError:
    pass


class ROS2CameraManager:
    """Subscribe to K1 ROS2 camera topic in a background thread.

    The Booster perception service publishes frames as YUV NV12.
    We convert to BGR and store the latest frame thread-safely.
    """

    def __init__(self, topic: str = ROS2_IMAGE_TOPIC) -> None:
        self._topic = topic
        self._frame: np.ndarray | None = None
        self._frame_ts: float = 0.0
        self._lock = threading.Lock()
        self._width = 0
        self._height = 0
        self._frame_count = 0
        self._running = False
        self._thread: threading.Thread | None = None
        self._node = None

    def start(self) -> bool:
        """Start ROS2 subscriber in background thread. Returns True if successful."""
        if not ROS2_AVAILABLE:
            logger.warning("rclpy not available — ROS2 camera backend disabled")
            return False
        try:
            if not rclpy.ok():
                rclpy.init()
            self._running = True
            self._thread = threading.Thread(target=self._spin_loop, daemon=True)
            self._thread.start()
            # Wait up to 5s for first frame
            t0 = time.time()
            while self._frame is None and time.time() - t0 < 5.0:
                time.sleep(0.1)
            if self._frame is not None:
                logger.info(
                    "ROS2 camera: first frame received from %s (%dx%d)",
                    self._topic, self._width, self._height,
                )
                return True
            else:
                logger.warning(
                    "ROS2 camera: no frame within 5s on %s — is perception service running?",
                    self._topic,
                )
                return False
        except Exception as e:
            logger.error("ROS2 camera init failed: %s", e)
            return False

    def _spin_loop(self) -> None:
        """Background thread: create node, subscribe, spin."""
        try:
            node = rclpy.create_node("robot_bridge_camera")
            self._node = node
            node.create_subscription(
                RosImage,
                self._topic,
                self._on_image,
                1,  # QoS: keep only latest
            )
            logger.info("ROS2 camera: subscribing to %s", self._topic)
            while self._running and rclpy.ok():
                rclpy.spin_once(node, timeout_sec=0.1)
        except Exception as e:
            logger.error("ROS2 spin loop error: %s", e)
        finally:
            if self._node:
                self._node.destroy_node()

    def _on_image(self, msg: Any) -> None:
        """ROS2 callback: convert incoming image to BGR numpy array."""
        try:
            w, h = msg.width, msg.height
            encoding = msg.encoding.lower() if msg.encoding else ""
            data = bytes(msg.data)

            if "yuv" in encoding or "nv12" in encoding or encoding == "":
                # K1 camera publishes YUV NV12 (height*1.5 rows, width cols)
                expected_size = int(h * 1.5) * w
                if len(data) >= expected_size:
                    yuv = np.frombuffer(data[:expected_size], dtype=np.uint8).reshape(
                        (int(h * 1.5), w)
                    )
                    bgr = cv2.cvtColor(yuv, cv2.COLOR_YUV2BGR_NV12)
                else:
                    # Might be raw BGR or RGB
                    bgr = self._try_decode_raw(data, w, h, encoding)
                    if bgr is None:
                        return
            elif "bgr8" in encoding:
                bgr = np.frombuffer(data, dtype=np.uint8).reshape((h, w, 3))
            elif "rgb8" in encoding:
                rgb = np.frombuffer(data, dtype=np.uint8).reshape((h, w, 3))
                bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            elif "mono8" in encoding:
                gray = np.frombuffer(data, dtype=np.uint8).reshape((h, w))
                bgr = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
            else:
                bgr = self._try_decode_raw(data, w, h, encoding)
                if bgr is None:
                    if self._frame_count == 0:
                        logger.warning(
                            "ROS2 camera: unknown encoding %r (%d bytes, %dx%d) — skipping",
                            encoding, len(data), w, h,
                        )
                    return

            with self._lock:
                self._frame = bgr
                self._frame_ts = time.time()
                self._width = bgr.shape[1]
                self._height = bgr.shape[0]
                self._frame_count += 1

        except Exception as e:
            if self._frame_count < 3:
                logger.error("ROS2 camera decode error: %s", e)

    @staticmethod
    def _try_decode_raw(data: bytes, w: int, h: int, encoding: str) -> np.ndarray | None:
        """Best-effort decode of raw image bytes."""
        # Try BGR 3-channel
        if len(data) == h * w * 3:
            return np.frombuffer(data, dtype=np.uint8).reshape((h, w, 3))
        # Try YUV NV12 anyway
        expected_nv12 = int(h * 1.5) * w
        if len(data) == expected_nv12:
            yuv = np.frombuffer(data, dtype=np.uint8).reshape((int(h * 1.5), w))
            return cv2.cvtColor(yuv, cv2.COLOR_YUV2BGR_NV12)
        return None

    @property
    def ok(self) -> bool:
        return self._frame is not None

    @property
    def resolution(self) -> tuple[int, int]:
        return (self._width, self._height)

    @property
    def source_info(self) -> str:
        return f"ros2:{self._topic}"

    def grab_jpeg(self, quality: int = 80) -> bytes | None:
        with self._lock:
            if self._frame is None:
                return None
            ok, buf = cv2.imencode(
                ".jpg", self._frame, [cv2.IMWRITE_JPEG_QUALITY, quality]
            )
            return buf.tobytes() if ok else None

    def grab_numpy(self) -> np.ndarray | None:
        with self._lock:
            return self._frame.copy() if self._frame is not None else None

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)


# ---------------------------------------------------------------------------
# Camera backend: V4L2 / OpenCV (fallback — only works if perception service is stopped)
# ---------------------------------------------------------------------------
class V4L2CameraManager:
    """OpenCV VideoCapture on /dev/videoN.  Only works when perception service is stopped."""

    def __init__(self, device_indices: list[int]) -> None:
        self._cap: cv2.VideoCapture | None = None
        self._lock = threading.Lock()
        self._device: int | None = None
        self._width = 0
        self._height = 0

        for idx in device_indices:
            cap = cv2.VideoCapture(idx)
            if cap.isOpened():
                ret, frame = cap.read()
                if ret and frame is not None:
                    self._cap = cap
                    self._device = idx
                    self._height, self._width = frame.shape[:2]
                    logger.info("V4L2 camera: /dev/video%d  %dx%d", idx, self._width, self._height)
                    return
                cap.release()
            else:
                cap.release()
        logger.warning("V4L2 camera: no device opened from %s", device_indices)

    @property
    def ok(self) -> bool:
        return self._cap is not None and self._cap.isOpened()

    @property
    def resolution(self) -> tuple[int, int]:
        return (self._width, self._height)

    @property
    def source_info(self) -> str:
        return f"v4l2:/dev/video{self._device}" if self._device is not None else "v4l2:none"

    def grab_jpeg(self, quality: int = 80) -> bytes | None:
        with self._lock:
            if not self.ok:
                return None
            ret, frame = self._cap.read()  # type: ignore[union-attr]
            if not ret or frame is None:
                return None
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
            return buf.tobytes() if ok else None

    def grab_numpy(self) -> np.ndarray | None:
        with self._lock:
            if not self.ok:
                return None
            ret, frame = self._cap.read()  # type: ignore[union-attr]
            return frame if ret else None

    def stop(self) -> None:
        with self._lock:
            if self._cap:
                self._cap.release()
                self._cap = None


# ---------------------------------------------------------------------------
# Camera manager: try ROS2 first, fall back to V4L2
# ---------------------------------------------------------------------------
class CameraManager:
    """Unified camera interface. Tries ROS2 subscriber first, then V4L2."""

    def __init__(self, v4l2_indices: list[int], ros2_topic: str = ROS2_IMAGE_TOPIC) -> None:
        self._backend: ROS2CameraManager | V4L2CameraManager | None = None
        self._backend_name = "none"

        # Try ROS2 first (works while perception service is running)
        if ROS2_AVAILABLE:
            logger.info("Trying ROS2 camera on topic %s ...", ros2_topic)
            ros2_cam = ROS2CameraManager(topic=ros2_topic)
            if ros2_cam.start():
                self._backend = ros2_cam
                self._backend_name = "ros2"
                logger.info("Camera backend: ROS2 (%s)", ros2_topic)
                return
            else:
                ros2_cam.stop()
                logger.info("ROS2 camera failed — trying V4L2 fallback")
        else:
            logger.info("rclpy not available — skipping ROS2 camera, trying V4L2")

        # Try V4L2 (only works if perception service is stopped)
        v4l2_cam = V4L2CameraManager(v4l2_indices)
        if v4l2_cam.ok:
            self._backend = v4l2_cam
            self._backend_name = "v4l2"
            logger.info("Camera backend: V4L2 (%s)", v4l2_cam.source_info)
            return

        logger.warning(
            "NO CAMERA AVAILABLE. For ROS2: source /opt/ros/humble/setup.bash before running. "
            "For V4L2: sudo systemctl stop booster-daemon-perception.service"
        )

    @property
    def ok(self) -> bool:
        return self._backend is not None and self._backend.ok

    @property
    def backend_name(self) -> str:
        return self._backend_name

    @property
    def resolution(self) -> tuple[int, int]:
        return self._backend.resolution if self._backend else (0, 0)

    @property
    def source_info(self) -> str:
        return self._backend.source_info if self._backend else "none"

    def grab_jpeg(self, quality: int = 80) -> bytes | None:
        return self._backend.grab_jpeg(quality) if self._backend else None

    def grab_numpy(self) -> np.ndarray | None:
        return self._backend.grab_numpy() if self._backend else None

    def stop(self) -> None:
        if self._backend:
            self._backend.stop()


# ---------------------------------------------------------------------------
# Audio helpers (ALSA / PulseAudio — discovered from your robot)
# ---------------------------------------------------------------------------
# Card 0: USB Audio Device (C-Media)  → speaker/playback
# Card 1: XFM-DP-V0.0.18 (iFlytek)   → microphone/capture @ 16 kHz mono
ALSA_PLAYBACK_DEVICE = "hw:0,0"
ALSA_CAPTURE_DEVICE = "hw:1,0"
PULSE_SINK = "alsa_output.usb-C-Media_Electronics_Inc._USB_Audio_Device-00.analog-stereo"
CAPTURE_RATE = 16000
CAPTURE_CHANNELS = 1


def speak_espeak(text: str) -> bool:
    """Synthesize speech with espeak and play through PulseAudio (paplay).

    espeak --stdout produces WAV on stdout; piping to paplay avoids the
    PulseAudio hang that occurs when espeak tries to open the sink directly.
    """
    try:
        espeak_proc = subprocess.Popen(
            ["espeak", "--stdout", "-a", "200", "-s", "140", text],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        paplay_proc = subprocess.Popen(
            ["paplay"],
            stdin=espeak_proc.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        espeak_proc.stdout.close()  # allow espeak to receive SIGPIPE if paplay exits
        _, paplay_err = paplay_proc.communicate(timeout=30)
        espeak_proc.wait(timeout=5)
        if paplay_proc.returncode != 0:
            logger.warning("paplay returned %d: %s", paplay_proc.returncode, paplay_err.decode(errors="replace"))
            return False
        return True
    except FileNotFoundError as e:
        logger.warning("espeak or paplay not found: %s — try: sudo apt-get install espeak pulseaudio-utils", e)
        return False
    except Exception as e:
        logger.error("speak_espeak failed: %s", e)
        return False


def play_wav_pulse(wav_bytes: bytes) -> bool:
    """Play WAV bytes through PulseAudio paplay (writes to temp file)."""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(wav_bytes)
        tmp = f.name
    try:
        proc = subprocess.run(["paplay", "--device", PULSE_SINK, tmp], timeout=30, capture_output=True)
        return proc.returncode == 0
    except Exception as e:
        logger.error("paplay failed: %s", e)
        return False
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def play_wav_alsa(wav_bytes: bytes) -> bool:
    """Play WAV bytes through ALSA aplay (piped via stdin)."""
    try:
        proc = subprocess.run(
            ["aplay", "-D", ALSA_PLAYBACK_DEVICE, "-"],
            input=wav_bytes, timeout=30, capture_output=True,
        )
        return proc.returncode == 0
    except Exception as e:
        logger.error("aplay failed: %s", e)
        return False


def record_audio(duration_s: float) -> bytes:
    """Record from ALSA mic, return WAV bytes (S16_LE, 16 kHz, mono)."""
    duration_s = max(0.5, min(30.0, duration_s))
    try:
        proc = subprocess.run(
            [
                "arecord", "-D", ALSA_CAPTURE_DEVICE,
                "-f", "S16_LE", "-r", str(CAPTURE_RATE), "-c", str(CAPTURE_CHANNELS),
                "-d", str(int(duration_s + 0.5)), "-t", "wav", "-q", "-",
            ],
            capture_output=True, timeout=duration_s + 10,
        )
        if proc.returncode != 0:
            stderr = proc.stderr.decode(errors="replace")
            logger.error("arecord failed (rc=%d): %s", proc.returncode, stderr[:200])
            return b""
        return proc.stdout
    except subprocess.TimeoutExpired:
        logger.error("arecord timed out after %.1fs", duration_s + 10)
        return b""
    except Exception as e:
        logger.error("record_audio exception: %s", e)
        return b""


# ---------------------------------------------------------------------------
# FastAPI application factory
# ---------------------------------------------------------------------------
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse


def create_app(camera: CameraManager, allow_motion: bool = False) -> FastAPI:
    app = FastAPI(title="K1 Robot Bridge", version="0.2.0")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    _start_time = time.time()

    # ── health ──────────────────────────────────────────────────────
    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "uptime_s": round(time.time() - _start_time, 1),
            "camera_ok": camera.ok,
            "camera_backend": camera.backend_name,
            "camera_source": camera.source_info,
            "camera_resolution": camera.resolution,
            "allow_motion": allow_motion,
            "sdk_available": SDK_AVAILABLE,
        }

    # ── robot state / telemetry ─────────────────────────────────────
    @app.get("/state")
    async def get_state():
        state: dict[str, Any] = {
            "timestamp": time.time(),
            "camera_ok": camera.ok,
            "camera_backend": camera.backend_name,
            "allow_motion": allow_motion,
            "sdk_available": SDK_AVAILABLE,
        }
        if SDK_AVAILABLE and _sdk is not None:
            try:
                state["sdk_members"] = [m for m in dir(_sdk) if not m.startswith("_")][:30]
                state["sdk_status"] = "available"
            except Exception as e:
                state["sdk_status"] = f"error: {e}"
        return state

    # ── camera frame ────────────────────────────────────────────────
    @app.get("/frame")
    async def get_frame(quality: int = 80, format: str = "jpeg"):
        """Return camera frame.  ?format=jpeg returns raw JPEG, ?format=json returns base64."""
        jpeg = camera.grab_jpeg(quality=max(10, min(100, quality)))
        if jpeg is None:
            return JSONResponse(
                {
                    "error": "camera_unavailable",
                    "camera_backend": camera.backend_name,
                    "detail": "No frame. Ensure: source /opt/ros/humble/setup.bash before running.",
                },
                status_code=503,
            )
        if format == "json":
            return {"jpeg_b64": base64.b64encode(jpeg).decode(), "size_bytes": len(jpeg)}
        return Response(content=jpeg, media_type="image/jpeg")

    # ── speak ───────────────────────────────────────────────────────
    @app.post("/speak")
    async def post_speak(request: Request):
        body = await request.json()
        text = (body.get("text") or "").strip()
        if not text:
            return JSONResponse({"error": "empty text"}, status_code=400)
        ok = speak_espeak(text)
        return {"status": "ok" if ok else "espeak_failed", "engine": "espeak", "text": text}

    # ── play raw audio ──────────────────────────────────────────────
    @app.post("/play_audio")
    async def post_play_audio(request: Request):
        wav_bytes = await request.body()
        if not wav_bytes:
            return JSONResponse({"error": "no audio data"}, status_code=400)
        ok = play_wav_pulse(wav_bytes)
        if not ok:
            ok = play_wav_alsa(wav_bytes)
        return {"status": "ok" if ok else "playback_failed", "size_bytes": len(wav_bytes)}

    # ── record from microphone ──────────────────────────────────────
    @app.post("/record")
    async def post_record(request: Request):
        body = await request.json()
        duration_s = float(body.get("duration_s", 5.0))
        duration_s = max(0.5, min(30.0, duration_s))
        wav_bytes = record_audio(duration_s)
        if not wav_bytes:
            return JSONResponse({"error": "recording_failed"}, status_code=503)
        return Response(
            content=wav_bytes, media_type="audio/wav",
            headers={"X-Duration-S": str(duration_s), "X-Sample-Rate": str(CAPTURE_RATE), "X-Channels": str(CAPTURE_CHANNELS)},
        )

    # ── motion: set velocity (GATED) ────────────────────────────────
    @app.post("/velocity")
    async def post_velocity(request: Request):
        if not allow_motion:
            return JSONResponse(
                {"error": "motion_disabled", "detail": "Start bridge with --allow-motion"},
                status_code=403,
            )
        body = await request.json()
        vx = float(body.get("vx", 0.0))
        wz = float(body.get("wz", 0.0))
        MAX_VX, MAX_WZ = 0.3, 0.5
        vx = max(-MAX_VX, min(MAX_VX, vx))
        wz = max(-MAX_WZ, min(MAX_WZ, wz))
        # TODO: Wire SDK Move RPC here
        logger.info("VELOCITY cmd: vx=%.3f wz=%.3f (stub)", vx, wz)
        return {"status": "ok", "vx": vx, "wz": wz, "note": "SDK motion stub"}

    # ── SDK diagnostics ────────────────────────────────────────────────
    @app.get("/sdk_info")
    async def sdk_info():
        info: dict[str, Any] = {"sdk_available": SDK_AVAILABLE}
        if SDK_AVAILABLE and _sdk is not None:
            # List all B1HandType enum members
            try:
                hand_types = {k: str(getattr(_sdk.B1HandType, k))
                              for k in dir(_sdk.B1HandType)
                              if k.startswith("k")}
                info["B1HandType_members"] = hand_types
            except Exception as e:
                info["B1HandType_error"] = str(e)
            # List B1HandIndex members
            try:
                hand_indices = {k: str(getattr(_sdk.B1HandIndex, k))
                                for k in dir(_sdk.B1HandIndex)
                                if k.startswith("k")}
                info["B1HandIndex_members"] = hand_indices
            except Exception as e:
                info["B1HandIndex_error"] = str(e)
            info["resolved_hand_type"] = str(_get_hand_type())
            info["sdk_init"] = _sdk_initialized
            info["loco_client_ok"] = _loco_client is not None
        return info

    # ── robot mode: get / set ──────────────────────────────────────────
    @app.get("/mode")
    async def get_mode():
        """Get the current robot mode (DAMP, PREP, WALK, CUSTOM, etc.)."""
        if not _ensure_sdk_init():
            return JSONResponse({"error": "SDK not initialized"}, status_code=503)
        try:
            gm = _sdk.GetModeResponse()
            res = _loco_client.GetMode(gm)
            if res == 0:
                # Map mode int to name for readability
                mode_names = {0: "DAMP", 1: "PREP", 2: "WALK", 3: "CUSTOM"}
                mode_val = int(gm.mode) if hasattr(gm.mode, '__int__') else gm.mode
                return {
                    "status": "ok",
                    "mode": str(gm.mode),
                    "mode_value": mode_val,
                    "mode_name": mode_names.get(mode_val, f"UNKNOWN({mode_val})"),
                }
            return JSONResponse({"error": f"GetMode returned {res}"}, status_code=503)
        except Exception as e:
            import traceback
            return JSONResponse({"error": str(e), "traceback": traceback.format_exc()}, status_code=500)

    @app.post("/mode")
    async def set_mode(request: Request):
        """Change robot mode.  Body: {"mode": "prep"|"walk"|"damp"|"custom"}

        SAFETY: Only prep and damp are allowed without --allow-motion.
        Walk and custom require --allow-motion flag.
        """
        if not _ensure_sdk_init():
            return JSONResponse({"error": "SDK not initialized"}, status_code=503)
        body = await request.json()
        target = (body.get("mode") or "").strip().lower()

        mode_map = {
            "damp": _sdk.RobotMode.kDamping,
            "prep": _sdk.RobotMode.kPrepare,
            "walk": _sdk.RobotMode.kWalking,
            "custom": _sdk.RobotMode.kCustom,
        }
        if target not in mode_map:
            return JSONResponse(
                {"error": f"Unknown mode '{target}'. Use: damp, prep, walk, custom"},
                status_code=400,
            )

        # Safety gate: walk and custom can move the robot
        if target in ("walk", "custom") and not allow_motion:
            return JSONResponse(
                {"error": f"Mode '{target}' requires --allow-motion flag on bridge startup"},
                status_code=403,
            )

        try:
            logger.warning("MODE CHANGE requested: -> %s", target.upper())
            res = _loco_client.ChangeMode(mode_map[target])
            if res == 0:
                return {"status": "ok", "mode": target, "detail": f"Changed to {target.upper()}"}
            return JSONResponse(
                {"error": f"ChangeMode returned {res}", "target": target},
                status_code=503,
            )
        except Exception as e:
            import traceback
            return JSONResponse({"error": str(e), "traceback": traceback.format_exc()}, status_code=500)

    # ── hand wave (SAFE — no walking, just fingers) ──────────────────
    @app.post("/wave")
    async def post_wave(request: Request):
        try:
            body = await request.json()
            hand = body.get("hand", "right")
            cycles = int(body.get("cycles", 2))
            cycles = max(1, min(cycles, 5))  # clamp to [1, 5]
            logger.info("WAVE cmd: hand=%s cycles=%d", hand, cycles)
            result = do_wave(hand=hand, cycles=cycles)
            status_code = 200 if result["status"] in ("ok", "partial") else 503
            return JSONResponse(result, status_code=status_code)
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            logger.error("Wave endpoint error: %s\n%s", e, tb)
            return JSONResponse({"error": str(e), "traceback": tb}, status_code=500)

    # ── emergency stop (ALWAYS allowed) ─────────────────────────────
    @app.post("/stop")
    async def post_stop():
        logger.warning("E-STOP requested")
        if _ensure_sdk_init() and _loco_client is not None and _sdk is not None:
            try:
                res = _loco_client.ChangeMode(_sdk.RobotMode.kDamping)
                return {"status": "ok", "action": "stop", "sdk_result": res}
            except Exception as e:
                logger.error("SDK stop failed: %s", e)
                return {"status": "error", "detail": str(e)}
        return {"status": "ok", "action": "stop", "note": "SDK not available — software stop only"}

    return app


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="K1 Robot Bridge Server",
        epilog="IMPORTANT: run  source /opt/ros/humble/setup.bash  before starting!",
    )
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=9090)
    p.add_argument("--camera-indices", default="32,33,0,1",
                   help="V4L2 fallback device indices (default: 32,33,0,1)")
    p.add_argument("--ros2-topic", default=ROS2_IMAGE_TOPIC,
                   help=f"ROS2 image topic (default: {ROS2_IMAGE_TOPIC})")
    p.add_argument("--allow-motion", action="store_true",
                   help="Enable /velocity endpoint (default: DISABLED)")
    p.add_argument("--log-level", default="INFO")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    if not ROS2_AVAILABLE:
        logger.warning(
            "rclpy not importable! Camera will likely fail. "
            "Run:  source /opt/ros/humble/setup.bash  then restart."
        )

    v4l2_indices = [int(x.strip()) for x in args.camera_indices.split(",") if x.strip()]
    camera = CameraManager(v4l2_indices=v4l2_indices, ros2_topic=args.ros2_topic)

    if args.allow_motion:
        logger.warning("MOTION ENABLED — robot WILL move on /velocity commands!")
    else:
        logger.info("Motion DISABLED (safe read-only mode). Use --allow-motion to enable.")

    app = create_app(camera=camera, allow_motion=args.allow_motion)

    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level.lower())


if __name__ == "__main__":
    main()
