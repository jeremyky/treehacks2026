# 🚀 Pre-Flight Checklist

Use this checklist to ensure everything works before your actual demo.

## ✅ Phase 1: Test Webapp & Command Center

### 1. Start Services
```bash
cd ~/Documents/treehacks2026/himpublic-py
./start_demo.sh
```

**Expected output:**
- ✓ Command center running (PID XXXX)
- ✓ Webapp running (PID XXXX)
- URLs displayed

### 2. Open Webapp
Open browser: `http://localhost:5176/`

**Should see:**
- Comms panel (left) - "Comms connected" message
- Floor plan (center)
- Robots panel (right)
- Camera/Injury Report boxes (bottom)
- "Awaiting medical report..." in Injury Report

### 3. Test Report Generation
```bash
cd ~/Documents/treehacks2026/himpublic-py
python3 test_report.py
```

**Expected output:**
- ✓ Report generated: reports/triage_YYYYMMDD_HHMMSS.md
- ✓ PDF generated: reports/triage_YYYYMMDD_HHMMSS.pdf
- ✓ Report posted successfully!

**Check webapp:**
- [ ] Injury Report box shows: Priority HIGH, right leg, bleeding, pain 8/10
- [ ] Full report appears at bottom with 📄 PDF and 📝 MD buttons
- [ ] Click 📄 PDF - should download the PDF file
- [ ] Click 📝 MD - should download the markdown file

**✅ If all checked, Phase 1 PASSED!**

---

## ✅ Phase 2: Test Robot Connection (No Movement)

### 1. SSH to Robot
```bash
ssh booster@192.168.10.102
```

### 2. Check Files Exist
```bash
cd ~/Workspace/himpublic/code
ls -lh final_demo.py
ls -lh demo4.json head.json
ls -lh ../src/himpublic/
```

**Should see:**
- final_demo.py (~25KB)
- demo4.json and head.json (keyframes)
- src/himpublic/ folder exists

### 3. Test Import (No Running)
```bash
export PYTHONPATH=../src
python3 -c "from himpublic.medical.triage_pipeline import TriagePipeline; print('✓ Imports work')"
```

**Expected:** `✓ Imports work`

**✅ If all checked, Phase 2 PASSED!**

---

## ✅ Phase 3: Full Demo Dry Run

### 1. Clear Old Reports
```bash
# On robot
rm -rf ~/Workspace/himpublic/reports/scan_frames/*
rm -f ~/Workspace/himpublic/reports/evidence/*.jpg
```

### 2. Run Demo with `--start-triage` Flag
*(Skips walking, tests only triage + report)*

```bash
cd ~/Workspace/himpublic/code
export PYTHONPATH=../src
python3 final_demo.py --cc http://192.168.10.100:8000 --start-triage
```

**Expected flow:**
1. "🧹 Cleaning up old reports..."
2. "Connecting to robot SDK..."
3. "Press ENTER to start..."
4. Robot speaks triage questions (10 lines)
5. "CAPTURING SCREENSHOTS..."
6. "DETECTING RED IN SCREENSHOT..."
7. "✓ Medical report: ..."
8. "✓ Report posted to command center"

**Check webapp during run:**
- [ ] Comms/Chat updates as robot speaks
- [ ] Camera feed shows live video
- [ ] Patient responses appear when robot asks next question
- [ ] Injury Report updates when complete
- [ ] Full report with download buttons appears

**✅ If all checked, Phase 3 PASSED!**

---

## ✅ Phase 4: Full Demo with Walking

### 1. Position Robot
- Clear 5+ meters in front
- Place "victim" (person with red band) in target location

### 2. Run Full Demo
```bash
# From laptop
cd ~/Documents/treehacks2026/himpublic-py
./run_robot.sh
```

**Expected sequence:**
1. Cleanup
2. SDK connection
3. Press ENTER
4. **Speech:** "Hello, is anyone there?"
5. **Walking:** Forward 5s → Turn left → Forward 3s → Turn left
6. **Speech:** "I'm clearing debris"
7. **Keyframe:** demo4 (debris removal)
8. **Speech:** Triage questions
9. **Keyframe:** head (scan)
10. **Screenshot capture** at middle of head scan
11. **Red detection** and annotation
12. **Report generation**
13. **Walk back**
14. **Speech:** "Assessment complete"

**Timing checks:**
- [ ] Robot moves consistently (same distance each time)
- [ ] No speech overlap
- [ ] Patient responses appear before next question
- [ ] Camera pauses during walking
- [ ] Screenshot captures the red band
- [ ] Report generates within 10 seconds

**✅ If all checked, Phase 4 PASSED! You're ready! 🎉**

---

## 🐛 Troubleshooting

### "Command center failed to start"
```bash
cat /tmp/cc.log
```
Check for errors. Most common: port 8000 already in use.

### "Webapp failed to start"
```bash
cat /tmp/webapp.log
```
Check for errors. Most common: port 5176 already in use.

### "CC comms failed"
- Check laptop IP: `ifconfig | grep 192.168.10`
- Update in command: `--cc http://YOUR_LAPTOP_IP:8000`

### "No red detected"
- Victim needs bright red band/marker
- Make sure lighting is good
- Check `reports/scan_frames/` for captured images

### "Report doesn't appear in webapp"
- Check command center is running: `curl http://localhost:8000/latest`
- Check robot can reach laptop: `curl http://192.168.10.100:8000/latest` (from robot)

### "Robot movements inconsistent"
- Charge battery (most common cause)
- Ensure flat, non-slippery floor
- Camera feed should pause during walking (check terminal output)

---

## 📋 Quick Reference

**Start everything:**
```bash
./start_demo.sh    # Terminal 1 (laptop)
./run_robot.sh     # Terminal 2 (laptop)
```

**Test report only:**
```bash
python3 test_report.py
```

**Manual robot run:**
```bash
ssh booster@192.168.10.102
cd ~/Workspace/himpublic/code
export PYTHONPATH=../src
python3 final_demo.py --cc http://192.168.10.100:8000
```

**Skip walking:**
```bash
python3 final_demo.py --cc http://192.168.10.100:8000 --start-triage
```

**Silent mode:**
```bash
python3 final_demo.py --cc http://192.168.10.100:8000 --no-speech
```

---

## 🎯 Success Criteria

Your demo is ready when:
- ✅ Test report appears and is clickable in webapp
- ✅ Robot connects and imports work
- ✅ Triage-only demo completes successfully
- ✅ Full demo with walking works consistently
- ✅ Red detection finds and annotates injury
- ✅ Report downloads work (PDF and MD)
- ✅ All timing is smooth (no overlaps, good flow)

**Ready to present! 🚀**
