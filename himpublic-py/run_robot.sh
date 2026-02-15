#!/bin/bash
# Quick script to copy everything and run on robot

set -e

ROBOT_IP="${ROBOT_IP:-192.168.10.102}"
LAPTOP_IP="${LAPTOP_IP:-192.168.10.1}"

echo "============================================================"
echo "  ROBOT DEMO RUNNER"
echo "============================================================"
echo ""
echo "Robot IP:  $ROBOT_IP"
echo "Laptop IP: $LAPTOP_IP"
echo ""

# Copy all necessary files
echo "📦 Copying files to robot..."

echo "  → final_demo.py"
scp code/final_demo.py booster@$ROBOT_IP:~/Workspace/himpublic/code/

echo "  → robot_run.sh"
scp robot_run.sh booster@$ROBOT_IP:~/Workspace/himpublic/

echo "  → replay_capture.py (if exists)"
if [ -f code/replay_capture.py ]; then
    scp code/replay_capture.py booster@$ROBOT_IP:~/Workspace/himpublic/code/
fi

echo "  → keyframe files"
if [ -f code/demo4.json ]; then
    scp code/demo4.json booster@$ROBOT_IP:~/Workspace/himpublic/code/ 2>/dev/null || echo "    (demo4.json not found, skipping)"
fi
if [ -f code/head.json ]; then
    scp code/head.json booster@$ROBOT_IP:~/Workspace/himpublic/code/ 2>/dev/null || echo "    (head.json not found, skipping)"
fi

echo "✓ Copy complete"
echo ""
echo "💡 Tip: If you get import errors, run ./setup_robot.sh once"
echo ""

# Run on robot
echo "🤖 Connecting to robot and running demo..."
echo "============================================================"
echo ""

ssh -t booster@$ROBOT_IP "cd ~/Workspace/himpublic && LAPTOP_IP=$LAPTOP_IP bash robot_run.sh"
