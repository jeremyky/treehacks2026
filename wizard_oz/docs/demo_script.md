# Demo Script (60–90 seconds)

## Setup (< 2 minutes)

```bash
cd wizard_oz
pip install -r requirements.txt
```

## Run command

```bash
python -m src.main --show --typed-mic --manual
```

- **--show**: Open webcam window with overlay (phase, last action, toggles).
- **--typed-mic**: Reserved for future typed transcript input.
- **--manual**: After each action, press Enter to simulate the action completing.

## Key order for a clean demo

1. **Start**  
   Window opens; phase is **SEARCH**. You’ll see periodic “Calling out...” actions; press **Enter** each time if using `--manual`.

2. **Trigger “human detected”**  
   Press **`h`**. On the next tick, the phase switches to **APPROACH**.  
   - Action: `navigate_to(...)`. Press **Enter** when “done.”

3. **Approach “done”**  
   Phase moves to **DEBRIS_ASSESS**.  
   - (Optional) Press **`d`** to simulate debris; then action `clear_debris(...)` runs. Press **Enter**.  
   - If you don’t press `d`, the phase still advances after one tick.

4. **Injury scan**  
   Phase moves to **INJURY_SCAN**.  
   - Action: `scan_injuries(...)`. Press **Enter**.  
   - (Optional) Press **`i`** before or during this phase to add injury findings to the report.

5. **Report**  
   Phase moves to **REPORT**.  
   - Action: `send_report(...)`. Report is written to `artifacts/reports/report_<timestamp>.json` and snapshot to `artifacts/reports/snapshot.jpg`. Press **Enter**.  
   - Phase goes to **DONE** and the loop exits.

6. **Shortcut**  
   At any time, press **`n`** to force the next phase (for quick demo).  
   Press **`q`** to quit.

## Summary

| Key | Effect |
|-----|--------|
| **h** | Toggle “human detected” (starts APPROACH from SEARCH) |
| **d** | Toggle “debris detected” (triggers clear_debris in DEBRIS_ASSESS) |
| **i** | Toggle “injury findings” (adds entries to report) |
| **n** | Force next phase |
| **q** | Quit |

## After the demo

- **Action log**: `artifacts/action_calls.jsonl` (one JSON object per action).
- **Report**: `artifacts/reports/report_<timestamp>.json`.
- **Snapshot**: `artifacts/reports/snapshot.jpg`.
