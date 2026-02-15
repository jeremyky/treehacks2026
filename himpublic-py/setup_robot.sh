#!/bin/bash
# One-time setup: Copy all dependencies to robot

set -e

ROBOT_IP="${ROBOT_IP:-192.168.10.102}"

echo "============================================================"
echo "  ROBOT INITIAL SETUP (One-time)"
echo "============================================================"
echo ""
echo "Robot IP: $ROBOT_IP"
echo ""
echo "This will copy all code and dependencies to the robot."
echo "You only need to run this once (or when dependencies change)."
echo ""
read -p "Press Enter to continue or Ctrl+C to cancel..."
echo ""

echo "📦 Creating directories on robot..."
ssh booster@$ROBOT_IP "mkdir -p ~/Workspace/himpublic/{code,src,reports}"
echo "✓ Directories created"
echo ""

echo "📦 Copying himpublic source code..."
scp -r src/himpublic booster@$ROBOT_IP:~/Workspace/himpublic/src/
echo "✓ Source code copied"
echo ""

echo "📦 Copying demo scripts..."
scp code/final_demo.py booster@$ROBOT_IP:~/Workspace/himpublic/code/
if [ -f code/replay_capture.py ]; then
    scp code/replay_capture.py booster@$ROBOT_IP:~/Workspace/himpublic/code/
fi
echo "✓ Demo scripts copied"
echo ""

echo "📦 Copying keyframe files..."
for keyframe in code/*.json; do
    if [ -f "$keyframe" ]; then
        echo "  → $(basename $keyframe)"
        scp "$keyframe" booster@$ROBOT_IP:~/Workspace/himpublic/code/
    fi
done
echo "✓ Keyframes copied"
echo ""

echo "============================================================"
echo "  ✅ ROBOT SETUP COMPLETE"
echo "============================================================"
echo ""
echo "Next steps:"
echo "  1. Run ./start_demo.sh in one terminal (laptop)"
echo "  2. Run ./run_robot.sh in another terminal"
echo ""
echo "For subsequent runs, you only need run_robot.sh"
echo "(unless you change src/himpublic code)"
echo ""
