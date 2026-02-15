#!/usr/bin/env python3
"""
Walk demo — run directly ON the robot via SSH.

Sequence:
  1. Walk forward ~5 steps
  2. Turn left 90°
  3. Walk forward ~3 steps
  4. Turn left 90°
  5. Stop

Usage (on robot):
    cd ~/Workspace/himpublic/code
    python3 walk_demo.py

    # With punch at the end:
    python3 walk_demo.py --punch punch.json

    # Adjust speeds:
    python3 walk_demo.py --walk-speed 0.4 --turn-time 4.0
"""
import argparse
import os
import subprocess
import sys
import time

from booster_robotics_sdk_python import (
    B1LocoClient,
    ChannelFactory,
    RobotMode,
)

# ── Tunables ──────────────────────────────────────────────────────
WALK_SPEED      = 0.5   # m/s forward
TURN_SPEED      = 0.4   # rad/s (positive = turn left)
STEP_LENGTH     = 0.50  # meters per "step"
TURN_90_TIME    = 3.9   # seconds to rotate 90° (pi/2 / 0.4)

CFG = {
    "walk_speed": WALK_SPEED,
    "turn_speed": TURN_SPEED,
    "step_length": STEP_LENGTH,
    "turn_90_time": TURN_90_TIME,
}


def steps_to_seconds(n: int) -> float:
    return (n * CFG["step_length"]) / CFG["walk_speed"]


def send_move(client, vx, vy, vz, duration, label=""):
    """Send Move command in a loop at 10Hz so the robot actually executes it."""
    if label:
        print(f">> {label}")
    hz = 10
    steps = int(duration * hz)
    for _ in range(steps):
        client.Move(vx, vy, vz)
        time.sleep(1.0 / hz)
    # Send stop
    client.Move(0.0, 0.0, 0.0)
    time.sleep(0.3)


def walk_forward(client, n_steps: int):
    dur = steps_to_seconds(n_steps)
    send_move(client, CFG["walk_speed"], 0.0, 0.0, dur,
              f"WALK FORWARD {n_steps} steps ({dur:.1f}s at {CFG['walk_speed']} m/s)")


def turn_left(client):
    send_move(client, 0.0, 0.0, CFG["turn_speed"], CFG["turn_90_time"],
              f"TURN LEFT 90° ({CFG['turn_90_time']:.1f}s)")


def stop(client):
    print(">> STOP")
    client.Move(0.0, 0.0, 0.0)


def main():
    parser = argparse.ArgumentParser(description="Walk demo sequence")
    parser.add_argument("--network", default="", help="Network interface (default: empty)")
    parser.add_argument("--walk-speed", type=float, default=WALK_SPEED)
    parser.add_argument("--turn-time", type=float, default=TURN_90_TIME)
    parser.add_argument("--step-length", type=float, default=STEP_LENGTH)
    parser.add_argument("--punch", type=str, default="", help="Punch JSON file to play after walking (e.g. punch.json)")
    parser.add_argument("--dry-run", action="store_true", help="Print steps without moving")
    args = parser.parse_args()

    CFG["walk_speed"] = args.walk_speed
    CFG["turn_90_time"] = args.turn_time
    CFG["step_length"] = args.step_length

    print("=" * 50)
    print("  WALK DEMO SEQUENCE")
    print(f"  Walk speed:  {CFG['walk_speed']} m/s")
    print(f"  Step length: {CFG['step_length']} m")
    print(f"  Turn 90°:    {CFG['turn_90_time']} s")
    print("=" * 50)
    print()

    if args.dry_run:
        print("[DRY RUN — not connecting to robot]")
        print("1. Walk forward 5 steps")
        print("2. Turn left 90°")
        print("3. Walk forward 3 steps")
        print("4. Turn left 90°")
        if args.punch:
            print(f"5. Punch ({args.punch})")
        print("Done.")
        return

    # Connect
    print("Connecting to robot SDK...")
    ChannelFactory.Instance().Init(domain_id=0, network_interface=args.network)
    client = B1LocoClient()
    client.Init()
    print("Connected!\n")

    # Proper mode transition: Prepare first, then Walking
    print(">> PREPARE MODE (stand up)")
    res = client.ChangeMode(RobotMode.kPrepare)
    print(f"   ChangeMode(kPrepare) returned: {res}")
    time.sleep(3)

    print(">> WALKING MODE")
    res = client.ChangeMode(RobotMode.kWalking)
    print(f"   ChangeMode(kWalking) returned: {res}")
    time.sleep(2)
    print("Walking mode active.\n")

    input("Press ENTER to start the sequence (robot will move!)...")
    print()

    try:
        # 1. Walk forward 5 steps
        walk_forward(client, 5)
        time.sleep(1)

        # 2. Turn left
        turn_left(client)
        time.sleep(1)

        # 3. Walk forward 3 steps
        walk_forward(client, 3)
        time.sleep(1)

        # 4. Turn left
        turn_left(client)
        time.sleep(1)

        # 5. Optional punch via replay_capture.py
        if args.punch and os.path.exists(args.punch):
            print(f">> PLAYING PUNCH: {args.punch}")
            # Stop walking first
            stop(client)
            time.sleep(1)
            subprocess.run([
                sys.executable, "replay_capture.py", args.punch
            ], check=False)
            time.sleep(1)

        # Done
        stop(client)
        print("\n✓ Sequence complete!")

    except KeyboardInterrupt:
        print("\n!! Interrupted — stopping robot")
        stop(client)
    except Exception as e:
        print(f"\n!! Error: {e} — stopping robot")
        stop(client)
        raise


if __name__ == "__main__":
    main()
