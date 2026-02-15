#!/bin/bash
# Run this script ON THE ROBOT via SSH
# Starts bridge server and runs walk_demo0v2.py

set -e

LAPTOP_IP="${LAPTOP_IP:-192.168.10.1}"

echo "============================================================"
echo "  ROBOT DEMO V2 - Walk Demo with Camera Feed"
echo "============================================================"
echo ""
echo "Laptop Command Center: http://$LAPTOP_IP:8000"
echo ""

# Kill any existing processes
echo "🧹 Cleaning up old processes..."
pkill -f "robot_bridge" 2>/dev/null || true
pkill -f "walk_demo" 2>/dev/null || true
pkill -f "final_demo" 2>/dev/null || true
sleep 1

# Set up environment
cd ~/Workspace/himpublic
export PYTHONPATH="$PWD/src:$PYTHONPATH"

# Verify walk_demo0v2.py exists
if [ ! -f "code/walk_demo0v2.py" ]; then
    echo "❌ ERROR: code/walk_demo0v2.py not found!"
    echo "   Run from laptop: scp code/walk_demo0v2.py booster@192.168.10.102:~/Workspace/himpublic/code/"
    exit 1
fi

# Start the bridge server in background
echo "🌉 Starting robot bridge server..."
nohup python src/robot_bridge/server.py > /tmp/bridge.log 2>&1 &
BRIDGE_PID=$!
echo "  Bridge PID: $BRIDGE_PID"
echo "  Waiting for bridge to initialize..."
sleep 4

# Check if bridge is running
if ps -p $BRIDGE_PID > /dev/null 2>&1; then
    echo "✓ Bridge running on http://127.0.0.1:9090"
else
    echo "⚠ Bridge failed to start"
    echo "  Check: cat /tmp/bridge.log"
    exit 1
fi

echo ""
echo "🤖 Starting walk demo v2..."
echo "============================================================"
echo ""

# Run the demo
cd code
python walk_demo0v2.py --cc http://$LAPTOP_IP:8000

echo ""
echo "============================================================"
echo "  Demo finished!"
echo "  Bridge is still running (PID: $BRIDGE_PID)"
echo "  Kill it with: kill $BRIDGE_PID"
echo "============================================================"
