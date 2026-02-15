#!/bin/bash
# Run this script ON THE ROBOT via SSH
# Starts bridge server and runs the final demo

set -e

LAPTOP_IP="${LAPTOP_IP:-192.168.10.1}"

echo "============================================================"
echo "  ROBOT DEMO - Starting Bridge + Final Demo"
echo "============================================================"
echo ""
echo "Laptop Command Center: http://$LAPTOP_IP:8000"
echo ""

# Kill any existing processes
echo "🧹 Cleaning up old processes..."
pkill -f "robot_bridge" 2>/dev/null || true
pkill -f "final_demo.py" 2>/dev/null || true
sleep 1

# Set up environment
cd ~/Workspace/himpublic
export PYTHONPATH="$PWD/src:$PYTHONPATH"

# Verify himpublic module exists
if [ ! -d "src/himpublic" ]; then
    echo "❌ ERROR: src/himpublic not found!"
    echo "   Run ./setup_robot.sh from your laptop first"
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
echo "🤖 Starting final demo..."
echo "============================================================"
echo ""

# Run the demo
python code/final_demo.py --cc http://$LAPTOP_IP:8000

echo ""
echo "============================================================"
echo "  Demo finished!"
echo "  Bridge is still running (PID: $BRIDGE_PID)"
echo "  Kill it with: kill $BRIDGE_PID"
echo "============================================================"
