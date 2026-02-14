#!/usr/bin/env python3
"""
Smoke test for Robot Bridge.

Tests (in order):
  1) GET  /health    — connectivity + camera + SDK status
  2) GET  /state     — robot telemetry
  3) GET  /frame x3  — capture 3 JPEG frames and save to disk
  4) POST /speak     — play a TTS phrase through robot speaker
  5) POST /record    — record 5 seconds from robot mic and save WAV

Usage:
    python scripts/smoke_test_robot.py --host 192.168.10.102
    python scripts/smoke_test_robot.py --host 192.168.10.102 --port 9090 --out missions/smoke_001
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("smoke_test")

# Ensure himpublic is importable
_repo = Path(__file__).resolve().parent.parent
_src = _repo / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))


def main() -> int:
    parser = argparse.ArgumentParser(description="Robot Bridge Smoke Test")
    parser.add_argument("--host", default="192.168.10.102", help="Robot bridge host (default: 192.168.10.102)")
    parser.add_argument("--port", type=int, default=9090, help="Robot bridge port (default: 9090)")
    parser.add_argument("--out", default="missions/smoke_001", help="Output directory for artifacts")
    args = parser.parse_args()

    base_url = f"http://{args.host}:{args.port}"
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    from himpublic.io.robot_client import RobotBridgeClient

    client = RobotBridgeClient(base_url=base_url, timeout=10)
    results: dict = {"base_url": base_url, "tests": {}}
    passed = 0
    failed = 0

    # ── 1. Health ───────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("STEP 1: GET /health")
    print("=" * 60)
    health = client.health()
    print(json.dumps(health, indent=2))
    results["tests"]["health"] = health
    if health.get("status") == "ok":
        print("PASS: Bridge is reachable")
        passed += 1
    else:
        print(f"FAIL: Bridge unreachable — {health.get('error', 'unknown')}")
        print(f"  Is the bridge running?  ssh booster@{args.host} 'python3 server.py'")
        failed += 1
        # Can't continue if bridge is down
        results["tests"]["summary"] = {"passed": passed, "failed": failed}
        (out / "results.json").write_text(json.dumps(results, indent=2))
        return 1

    # ── 2. State ────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("STEP 2: GET /state")
    print("=" * 60)
    state = client.get_state()
    print(json.dumps(state, indent=2))
    results["tests"]["state"] = state
    if "error" not in state:
        print("PASS: State retrieved")
        passed += 1
    else:
        print(f"FAIL: State error — {state.get('error')}")
        failed += 1

    # ── 3. Capture 3 frames ─────────────────────────────────────────
    print("\n" + "=" * 60)
    print("STEP 3: GET /frame x3")
    print("=" * 60)
    frames_ok = 0
    for i in range(3):
        jpeg = client.get_frame_jpeg(quality=85)
        if jpeg and len(jpeg) > 100:
            path = out / f"frame_{i:02d}.jpg"
            path.write_bytes(jpeg)
            print(f"  Frame {i}: {len(jpeg):,} bytes → {path}")
            frames_ok += 1
        else:
            print(f"  Frame {i}: FAILED (no data or too small)")
        time.sleep(0.3)

    results["tests"]["frames"] = {"captured": frames_ok, "expected": 3}
    if frames_ok == 3:
        print("PASS: All 3 frames captured")
        passed += 1
    elif frames_ok > 0:
        print(f"PARTIAL: {frames_ok}/3 frames captured")
        passed += 1
    else:
        print("FAIL: No frames captured — camera may be locked by perception service")
        print("  Try on robot: sudo systemctl stop booster-daemon-perception.service")
        failed += 1

    # ── 4. Speak ────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("STEP 4: POST /speak")
    print("=" * 60)
    phrase = "TreeHacks robot bridge online. Smoke test in progress."
    ok = client.speak(phrase)
    results["tests"]["speak"] = {"ok": ok, "text": phrase}
    if ok:
        print(f"PASS: Spoke: {phrase!r}")
        passed += 1
    else:
        print("FAIL: Speak failed — check espeak on robot: sudo apt-get install espeak")
        failed += 1

    # ── 5. Record 5s ────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("STEP 5: POST /record (5 seconds)")
    print("=" * 60)
    print("  Recording from robot mic for 5 seconds...")
    wav = client.record(duration_s=5.0)
    results["tests"]["record"] = {"size_bytes": len(wav)}
    if wav and len(wav) > 100:
        path = out / "recording.wav"
        path.write_bytes(wav)
        print(f"  Recorded: {len(wav):,} bytes → {path}")
        print("PASS: Audio recorded")
        passed += 1
    else:
        print("FAIL: Recording empty — check ALSA devices on robot: arecord -l")
        failed += 1

    # ── Summary ─────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print(f"SMOKE TEST COMPLETE: {passed} passed, {failed} failed")
    print(f"Artifacts saved to: {out}")
    print("=" * 60)

    results["tests"]["summary"] = {"passed": passed, "failed": failed}
    (out / "results.json").write_text(json.dumps(results, indent=2))

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
