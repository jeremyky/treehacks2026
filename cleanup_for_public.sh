#!/bin/bash
# Cleanup script to prepare repository for public release
# Run this script from the repository root

set -e

echo "════════════════════════════════════════════════════════════════════════════"
echo "  Repository Cleanup for Public Release"
echo "════════════════════════════════════════════════════════════════════════════"
echo ""
echo "⚠️  WARNING: This script will:"
echo "   1. Remove large model files from git tracking"
echo "   2. Remove generated data, artifacts, and reports"
echo "   3. Stage .env.example files and documentation"
echo ""
echo "   This does NOT rewrite git history. Files remain in history."
echo "   For full history cleanup, see PREPARE_FOR_PUBLIC.md"
echo ""
read -p "Continue? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 1
fi

echo ""
echo "🧹 Step 1: Removing large model files from git tracking..."
git rm --cached himpublic-py/yolov8n.pt 2>/dev/null || echo "  ℹ️  yolov8n.pt not tracked"
git rm --cached himpublic-py/yolov8s-worldv2.pt 2>/dev/null || echo "  ℹ️  yolov8s-worldv2.pt not tracked"
git rm --cached webapp/yolov8s-worldv2.pt 2>/dev/null || echo "  ℹ️  webapp/yolov8s-worldv2.pt not tracked"
echo "✅ Model files removed from tracking"

echo ""
echo "🧹 Step 2: Removing generated data and artifacts..."
git rm -r --cached himpublic-py/data/ 2>/dev/null || echo "  ℹ️  data/ not tracked"
git rm -r --cached himpublic-py/artifacts/ 2>/dev/null || echo "  ℹ️  artifacts/ not tracked"
git rm -r --cached himpublic-py/reports/ 2>/dev/null || echo "  ℹ️  himpublic-py/reports/ not tracked"
git rm -r --cached webapp/reports/ 2>/dev/null || echo "  ℹ️  webapp/reports/ not tracked"
echo "✅ Generated data removed from tracking"

echo ""
echo "🧹 Step 3: Removing log files..."
git rm --cached himpublic-py/logs/*.jsonl 2>/dev/null || echo "  ℹ️  No log files tracked"
echo "✅ Log files removed from tracking"

echo ""
echo "📝 Step 4: Staging configuration files..."
git add .gitignore 2>/dev/null || true
git add .env.example 2>/dev/null || true
git add himpublic-py/.env.example 2>/dev/null || true
git add MODELS_SETUP.md 2>/dev/null || true
git add PREPARE_FOR_PUBLIC.md 2>/dev/null || true
git add cleanup_for_public.sh 2>/dev/null || true
echo "✅ Configuration files staged"

echo ""
echo "════════════════════════════════════════════════════════════════════════════"
echo "  ✅ CLEANUP COMPLETE"
echo "════════════════════════════════════════════════════════════════════════════"
echo ""
echo "📊 Git Status:"
git status --short
echo ""
echo "Next steps:"
echo "  1. Review the changes: git status"
echo "  2. Commit the changes: git commit -m 'chore: prepare for public release'"
echo "  3. Review PREPARE_FOR_PUBLIC.md for additional security checks"
echo "  4. Consider cleaning git history if needed (see PREPARE_FOR_PUBLIC.md)"
echo ""
echo "⚠️  IMPORTANT: Run verification checks before making repository public!"
echo "   See PREPARE_FOR_PUBLIC.md for details."
echo ""
