#!/bin/bash
# Start Demo - Launches command center + webapp in one terminal

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "============================================================"
echo "  TREEHACKS DEMO LAUNCHER"
echo "============================================================"
echo ""

# Check if webapp is built
if [ ! -d "../webapp/dist" ] && [ ! -d "../webapp/node_modules" ]; then
    echo "⚠️  Webapp not set up. Run: cd ../webapp && npm install"
    exit 1
fi

# Cleanup function
cleanup() {
    echo ""
    echo "🛑 Shutting down..."
    kill $CC_PID $WEBAPP_PID 2>/dev/null
    wait $CC_PID $WEBAPP_PID 2>/dev/null
    echo "✓ Stopped"
    exit 0
}

trap cleanup SIGINT SIGTERM

# Start command center in background
echo "🚀 Starting command center..."
python scripts/run_command_center.py > /tmp/cc.log 2>&1 &
CC_PID=$!
sleep 2

if ! kill -0 $CC_PID 2>/dev/null; then
    echo "❌ Command center failed to start. Check /tmp/cc.log"
    exit 1
fi

echo "✓ Command center running (PID $CC_PID)"

# Start webapp in background
echo "🌐 Starting webapp..."
cd ../webapp
npm run dev > /tmp/webapp.log 2>&1 &
WEBAPP_PID=$!
cd "$SCRIPT_DIR"
sleep 3

if ! kill -0 $WEBAPP_PID 2>/dev/null; then
    echo "❌ Webapp failed to start. Check /tmp/webapp.log"
    kill $CC_PID 2>/dev/null
    exit 1
fi

echo "✓ Webapp running (PID $WEBAPP_PID)"
echo ""
echo "============================================================"
echo "  ✅ ALL SERVICES RUNNING"
echo "============================================================"
echo ""
echo "📱 Webapp:          http://localhost:5176/"
echo "🖥️  Command Center:  http://localhost:8000/"
echo ""
echo "============================================================"
echo "  NEXT STEPS"
echo "============================================================"
echo ""
echo "1. Copy code to robot:"
echo "   scp code/final_demo.py booster@192.168.10.102:~/Workspace/himpublic/code/"
echo ""
echo "2. In a NEW terminal, SSH to robot and run:"
echo "   ssh booster@192.168.10.102"
echo "   cd ~/Workspace/himpublic/code"
echo "   export PYTHONPATH=../src"
echo "   python3 final_demo.py --cc http://192.168.10.100:8000"
echo ""
echo "============================================================"
echo ""
echo "Press Ctrl+C to stop all services"
echo ""

# Tail logs to show activity
tail -f /tmp/cc.log /tmp/webapp.log &
TAIL_PID=$!

# Wait for interrupt
wait $CC_PID $WEBAPP_PID

# Cleanup tail
kill $TAIL_PID 2>/dev/null
