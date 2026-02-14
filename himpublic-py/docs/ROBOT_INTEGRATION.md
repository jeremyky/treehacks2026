# Booster K1 Robot Integration — Runbook & Notes

> Compiled during TreeHacks 2026 (Feb 14-15).  
> Robot: Booster K1 Humanoid, IP `192.168.10.102`, user `booster`, password `123456`.  
> Laptop connects over USB-C Ethernet (`192.168.10.1`).

---

## Architecture Overview

```
┌──────────── Laptop ────────────┐       HTTP        ┌────────── K1 Robot ──────────┐
│                                │  ◄──────────────► │                              │
│  Orchestrator (Python)         │  192.168.10.102   │  Robot Bridge (FastAPI)      │
│    ├─ RobotBridgeClient        │      :9090        │    ├─ ROS2 Camera Subscriber │
│    ├─ BridgeVideoSource        │                   │    ├─ ALSA Mic (arecord)     │
│    ├─ BridgeAudioIO            │                   │    ├─ TTS (espeak → paplay)  │
│    ├─ YOLO perception          │                   │    ├─ Booster SDK (motion)   │
│    └─ LLM policy               │                   │    └─ FastAPI on :9090       │
└────────────────────────────────┘                   └──────────────────────────────┘
```

**Key principle:** The laptop pipeline has ZERO ROS2 dependencies. All robot hardware
is abstracted behind the HTTP bridge running on the robot.

---

## Robot Environment Summary

| Item | Value |
|------|-------|
| OS | Ubuntu 22.04.2 LTS (aarch64) |
| Kernel | 5.15.153-qki-consolidate-android13 |
| Python | 3.10.12 |
| ROS2 | Humble (sourced from `/opt/ros/humble/setup.bash`) |
| SDK | `booster_robotics_sdk_python` (compiled .so, NOT pip-installable) |
| Hostname | `robot` |
| IP | `192.168.10.102` (USB-C Ethernet) |
| Laptop IP | `192.168.10.1` |
| Disk | ~46 GB free on `/data` |

---

## 1. Camera Access

### What works: ROS2 Subscriber

The `booster-daemon-perception.service` holds an **exclusive lock** on all `/dev/video*` devices.
You CANNOT use OpenCV `VideoCapture` or V4L2 directly while it's running.

Instead, subscribe to ROS2 image topics published by the perception service.

**Working topic:** `/StereoNetNode/rectified_image`  
**Format:** YUV NV12, 544×448  
**Conversion:** `cv2.cvtColor(yuv, cv2.COLOR_YUV2BGR_NV12)`

### Available ROS2 Camera Topics

```
/StereoNetNode/origin_left_image
/StereoNetNode/origin_right_image
/StereoNetNode/rectified_image          ← WE USE THIS ONE
/StereoNetNode/rectified_right_image
/StereoNetNode/stereonet_depth
/StereoNetNode/stereonet_depth/camera_info
/StereoNetNode/stereonet_pointcloud2
/StereoNetNode/stereonet_visual
/X5CameraControlReq
/X5CameraControlResp
/image_combine_raw
/image_left_raw
/image_left_raw/camera_info
/image_right_raw
/image_right_raw/camera_info
```

### GOTCHA: Topic prefix

The topics do **NOT** have a `/booster_camera_bridge/` prefix.  
It's `/StereoNetNode/rectified_image`, **not** `/booster_camera_bridge/StereoNetNode/rectified_image`.

### GOTCHA: Must source ROS2 before starting bridge

```bash
source /opt/ros/humble/setup.bash && python3 ~/server.py
```

If you forget `source`, the ROS2 camera manager will fail with "no frame within 5s" and fall back to V4L2 (which will also fail).

### Alternative: Direct V4L2 (requires stopping perception)

If you ever need raw V4L2 access:
```bash
sudo systemctl stop booster-daemon-perception.service
# NOW OpenCV VideoCapture(/dev/video32) will work
# Restart when done:
sudo systemctl start booster-daemon-perception.service
```

Video devices: `/dev/video0`, `/dev/video1`, `/dev/video32`, `/dev/video33`

---

## 2. Audio Output (TTS / Speaker)

### What works: `espeak --stdout | paplay`

The robot has a **USB Audio Device** (card 0) with a PulseAudio sink.

### GOTCHA: Bare `espeak` hangs forever

`espeak "hello"` will **hang indefinitely** (timeout after 30s). It cannot open
the PulseAudio sink directly. You MUST pipe through `paplay`:

```bash
# THIS HANGS:
espeak "hello"

# THIS WORKS:
espeak --stdout -a 200 "hello" | paplay
```

### GOTCHA: ALSA direct also fails

```bash
# FAILS — "Channels count non available" (device doesn't support mono directly)
espeak --stdout "hello" | aplay -D hw:0,0
```

### Audio output device info

```
Card 0: USB Audio Device
  ALSA name: hw:0,0
  PulseAudio sink: alsa_output.usb-C-Media_Electronics_Inc._USB_Audio_Device-00.analog-stereo
  Format: s16le 2ch 44100Hz
  State: SUSPENDED (wakes on use)
```

---

## 3. Audio Input (Microphone)

### What works: `arecord` via ALSA

```bash
arecord -D default -f S16_LE -r 16000 -c 1 -d 5 /tmp/test.wav
```

This records 5 seconds of 16-bit 16kHz mono WAV. The bridge server uses this
for the `/record` endpoint.

The smoke test confirmed 160KB WAV returned successfully (5s recording).

---

## 4. Booster SDK

### Import

```python
import booster_robotics_sdk_python as sdk
```

This is a **compiled .so** module, not a pip package. `pip show` will fail, but `import` works.

### Location

```
/usr/local/lib/python3.10/dist-packages/booster_robotics_sdk_python.pyi  (type stub)
/usr/local/lib/python3.10/dist-packages/booster_robotics_sdk_python*.so  (binary)
```

### Key classes (from type stub)

| Class | Purpose |
|-------|---------|
| `ChannelFactory` | Initializes SDK comms |
| `B1LocoClient` | Locomotion commands (walk, velocity) |
| `B1LowCmdPublisher` | Low-level motor commands |
| `B1LowStateSubscriber` | Joint state telemetry |
| `B1OdometerStateSubscriber` | Odometry |
| `B1RemoteControllerStateSubscriber` | RC state |
| `B1LowHandDataScriber` | Hand feedback |
| `B1LowHandTouchDataScriber` | Hand touch sensor |

### Enums

| Enum | Values |
|------|--------|
| `RobotMode` | `kDamping`, `kPrepare`, `kWalking`, `kCustom` |
| `B1JointIndex` | `kHeadYaw`(0) through `kCrankDownRight`(22) — 23 joints |
| `B1HandAction` | `kHandOpen`(0), `kHandClose`(1) |
| `B1HandIndex` | `kLeftHand`(0), `kRightHand`(1) |
| `B1HandType` | `kInspireHand`, `kInspireTouchHand`, `kRevoHand`, `kUnknown` |
| `B1LocoApiId` | `kMove`, `kChangeMode`, `kRotateHead` |
| `Frame` | `kBody`, `kHead`, `kLeftFoot`, `kRightFoot`, `kLeftHand`, `kRightHand` |

### Joint Map (B1JointIndex)

```
0  kHeadYaw            11 kLeftHipPitch
1  kHeadPitch           12 kLeftHipRoll
2  kLeftShoulderPitch   13 kLeftHipYaw
3  kLeftShoulderRoll    14 kLeftKneePitch
4  kLeftElbowPitch      15 kCrankUpLeft
5  kLeftElbowYaw        16 kCrankDownLeft
6  kRightShoulderPitch  17 kRightHipPitch
7  kRightShoulderRoll   18 kRightHipRoll
8  kRightElbowPitch     19 kRightHipYaw
9  kRightElbowYaw       20 kRightKneePitch
10 kWaist               21 kCrankUpRight
                        22 kCrankDownRight
```

---

## 5. Running Services on Robot

Key services (from `systemctl`):
- `booster-daemon-perception.service` — camera/stereo vision (holds V4L2 lock)
- `booster-daemon-motion.service` — motor control
- Various other booster-daemon services

**Do NOT stop these** unless you know what you're doing. The bridge server
works alongside them by using ROS2 topics instead of direct hardware access.

---

## 6. Bridge Server Deployment

### Files

| Location | File | Purpose |
|----------|------|---------|
| Robot: `~/server.py` | `robot_bridge/server.py` | FastAPI bridge server |
| Laptop: `src/robot_bridge/` | Full package | Source of truth |
| Laptop: `src/himpublic/io/robot_client.py` | Client + adapters | Pipeline integration |
| Laptop: `scripts/smoke_test_robot.py` | Smoke test | Verify all 5 subsystems |

### Deploy updated server to robot

```bash
# FROM LAPTOP (not from SSH session!)
scp /Users/jeremyky/Documents/treehacks2026/himpublic-py/src/robot_bridge/server.py booster@192.168.10.102:~/server.py
```

### Start bridge on robot

```bash
# ON ROBOT (SSH session)
source /opt/ros/humble/setup.bash && python3 ~/server.py
```

### Run smoke test from laptop

```bash
# ON LAPTOP
cd /Users/jeremyky/Documents/treehacks2026/himpublic-py
python3 scripts/smoke_test_robot.py --host 192.168.10.102
```

### Bridge endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Uptime, camera status, motion flag, SDK status |
| `/state` | GET | Robot telemetry + SDK members |
| `/frame?quality=80` | GET | JPEG frame from camera |
| `/speak` | POST | TTS via espeak→paplay |
| `/play_audio` | POST | Play raw WAV bytes |
| `/record` | POST | Record from mic (arecord) |
| `/velocity` | POST | Motion command (gated by --allow-motion) |
| `/stop` | POST | Emergency stop (always allowed) |

---

## 7. Smoke Test Results (Feb 15 2026)

```
STEP 1: GET /health         → PASS (bridge reachable, camera OK, SDK available)
STEP 2: GET /state          → PASS (telemetry + 30 SDK members returned)
STEP 3: GET /frame x3       → PASS (3 frames, ~61KB each, 544x448)
STEP 4: POST /speak         → PASS (after fixing espeak→paplay pipe)
STEP 5: POST /record (5s)   → PASS (160KB WAV recorded)
```

---

## 8. Common Pitfalls & Fixes

| Problem | Cause | Fix |
|---------|-------|-----|
| ROS2 camera "no frame within 5s" | Forgot to source ROS2 | `source /opt/ros/humble/setup.bash` before starting server |
| ROS2 camera "no frame within 5s" | Wrong topic name | Use `/StereoNetNode/rectified_image` (no `/booster_camera_bridge/` prefix) |
| V4L2 "can't open camera by index" | Perception service holds lock | Use ROS2 subscriber instead, or `sudo systemctl stop booster-daemon-perception.service` |
| `espeak` hangs for 30s | PulseAudio sink issue | Use `espeak --stdout \| paplay` instead of bare `espeak` |
| ALSA "Channels count non available" | USB device doesn't support mono | Use `paplay` (handles channel conversion) instead of `aplay -D hw:0,0` |
| `scp: No such file or directory` | Running scp from robot SSH | Run `scp` from **laptop** terminal, not from SSH |
| `ModuleNotFoundError: cv2` | cv2 not on laptop | Lazy-imported in robot_client.py; only needed for numpy frame decode |
| `pip show booster_robotics_sdk_python` fails | It's a .so, not pip pkg | Use `import` directly; `pip show` won't find it |
| Smoke test "No such file" | Wrong working directory | `cd himpublic-py` first, then `python3 scripts/smoke_test_robot.py` |

---

## 9. Next Steps

- [ ] Wire SDK `B1LocoClient` for motion commands (walk, turn, head rotation)
- [ ] Wire SDK `B1LowStateSubscriber` for real joint telemetry
- [ ] Add `--allow-motion` flag testing with safety e-stop
- [ ] Integrate depth topic (`/StereoNetNode/stereonet_depth`) for obstacle avoidance
- [ ] Run full orchestrator pipeline with `--io robot --robot-bridge-url http://192.168.10.102:9090`
