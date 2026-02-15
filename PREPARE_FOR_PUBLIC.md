# Preparing Repository for Public Release

## ✅ Completed Steps

1. **Environment Variables Template Created**
   - ✅ Root `.env.example` created
   - ✅ `himpublic-py/.env.example` created with comprehensive configuration
   - ✅ `webapp/.env.example` already exists

2. **Enhanced .gitignore**
   - ✅ Comprehensive patterns for sensitive files
   - ✅ Excludes logs, reports, data, artifacts
   - ✅ Excludes large model files (.pt, .onnx, etc.)

## 🚨 Required Actions Before Making Public

### 1. Remove Tracked Sensitive Files from Git History

The following files are currently tracked in git but should be removed:

```bash
# Remove large model files (they should be downloaded separately)
git rm --cached himpublic-py/yolov8n.pt
git rm --cached himpublic-py/yolov8s-worldv2.pt
git rm --cached webapp/yolov8s-worldv2.pt

# Remove generated data and artifacts (contains test/demo data)
git rm -r --cached himpublic-py/data/
git rm -r --cached himpublic-py/artifacts/

# Remove logs if any
git rm --cached himpublic-py/artifacts/sessions/sample_session_001/evidence.jsonl 2>/dev/null || true

# Commit the removal
git add .gitignore .env.example himpublic-py/.env.example MODELS_SETUP.md PREPARE_FOR_PUBLIC.md
git commit -m "chore: prepare repository for public release

- Remove model files (add download instructions)
- Remove generated data and artifacts
- Add .env.example templates
- Enhance .gitignore for sensitive data
"
```

### 2. Review and Remove Reports Directory

The `reports/` directories may contain sensitive demo data or test results:

```bash
# Review what's in reports
ls -la himpublic-py/reports/
ls -la webapp/reports/

# If they should be removed from git:
git rm -r --cached himpublic-py/reports/
git rm -r --cached webapp/reports/
```

### 3. Search for Hardcoded Credentials

Run these commands to double-check for any hardcoded secrets:

```bash
# Search for potential API keys
grep -r "sk-[a-zA-Z0-9]\{20,\}" . --exclude-dir=node_modules --exclude-dir=.venv --exclude-dir=.git

# Search for other common secret patterns
grep -ri "password.*=.*['\"]" . --exclude-dir=node_modules --exclude-dir=.venv --exclude-dir=.git | grep -v ".example"

# Search for hardcoded tokens
grep -ri "token.*=.*['\"]" . --exclude-dir=node_modules --exclude-dir=.venv --exclude-dir=.git | grep -v ".example"
```

### 4. Review Specific Files with IP/Network Config

The following files contain local network IPs (192.168.x.x) which are fine for examples, but review them:

- `himpublic-py/setup_robot.sh` - Default robot IP (OK as example)
- `himpublic-py/robot_run.sh` - Laptop IP env var (OK)
- `himpublic-py/src/himpublic/orchestrator/config.py` - Default robot bridge URL (OK)

These are using environment variables with sensible defaults, so they're safe.

### 5. Optional: Clean Git History

If any sensitive data was previously committed, consider using git-filter-repo or BFG Repo-Cleaner:

```bash
# Install git-filter-repo
pip install git-filter-repo

# Remove sensitive files from ALL history (CAREFUL!)
git filter-repo --path himpublic-py/yolov8n.pt --invert-paths
git filter-repo --path himpublic-py/yolov8s-worldv2.pt --invert-paths
git filter-repo --path webapp/yolov8s-worldv2.pt --invert-paths
```

⚠️ **Warning**: This rewrites git history and will break existing clones!

### 6. Create a Public Repository Checklist

Before pushing to a public repository:

- [ ] No `.env` files committed (only `.env.example`)
- [ ] No API keys in code
- [ ] No passwords in code
- [ ] No sensitive demo/test data
- [ ] Large model files removed (with download instructions)
- [ ] `MODELS_SETUP.md` documentation present
- [ ] `README.md` mentions how to set up environment variables
- [ ] All secrets use environment variables
- [ ] `.gitignore` is comprehensive

### 7. Update README Files

Ensure main README.md files mention:

```markdown
## Setup

1. Clone the repository
2. Copy `.env.example` to `.env` and fill in your API keys
3. Download required model files (see MODELS_SETUP.md)
4. Install dependencies
5. Run the application
```

## 📋 Verification Commands

After cleanup, run these to verify:

```bash
# Ensure no .env files are tracked
git ls-files | grep "\.env$"
# Should return nothing (only .env.example should exist)

# Ensure no .pt model files are tracked
git ls-files | grep "\.pt$"
# Should return nothing

# Check repository size
du -sh .git
# Should be reasonable (< 50MB ideally)

# List all tracked files over 1MB
git ls-files | xargs -I {} sh -c 'du -h "{}" 2>/dev/null' | awk '$1 ~ /M$/ {print}'
```

## 🎯 Final Steps

1. Create a new repository on GitHub (or your platform)
2. Set it to **private** initially
3. Push your cleaned repo
4. Do a fresh clone to a new directory
5. Verify everything works without sensitive data
6. Make it **public** only after verification

## 🔒 Security Best Practices

- Never commit API keys, passwords, or tokens
- Always use environment variables for secrets
- Keep `.env` files in `.gitignore`
- Provide `.env.example` templates with placeholder values
- Document where to obtain API keys
- Use services like `git-secrets` to prevent accidental commits
