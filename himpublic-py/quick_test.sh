#!/bin/bash
# Quick test to verify changes locally (no robot needed)

echo "Starting test report generation..."
python3 test_report.py

echo ""
echo "Open webapp at: http://localhost:5176"
echo "You should see:"
echo "  ✓ Camera feed always visible (top-right)"
echo "  ✓ Medical Report always visible (bottom-right)"
echo "  ✓ Robot and victim both in courtyard on map"
echo "  ✓ Click Medical Report box to open PDF"
