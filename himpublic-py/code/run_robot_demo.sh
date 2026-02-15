#!/usr/bin/env bash
# Run the hardcoded demo on the robot (bridge mode).
# Usage:
#   ./code/run_robot_demo.sh                    # bridge at default 192.168.10.102:9090
#   ./code/run_robot_demo.sh 192.168.10.50     # bridge at 192.168.10.50:9090
#   ./code/run_robot_demo.sh 127.0.0.1         # bridge on same machine (e.g. demo run ON robot)
set -e
cd "$(dirname "$0")/.."
ROBOT_IP="${1:-192.168.10.102}"
CC_URL="${HIMPUBLIC_COMMAND_CENTER_URL:-http://127.0.0.1:8000}"
export PYTHONPATH=src
echo "Bridge: http://${ROBOT_IP}:9090  Command center: ${CC_URL}"
exec python3 code/hardcoded_demo.py --mode bridge --bridge-url "http://${ROBOT_IP}:9090" --command-center "${CC_URL}"
