# Action API

All actions are defined on `ActionClient` and return `ActionResult(success: bool, details: str|dict|None, simulated: bool)`.

## navigate_to(target_pose, reason) → ActionResult

- **target_pose**: `dict` with at least `x`, `y`, `yaw` (or equivalent). Meters and radians.
- **reason**: Optional string for logging (e.g. `"approach_target"`).
- **Expected behavior**: Drive the robot (or sim) to the target pose; stop when reached or timeout.
- **Placeholder**: Logs and returns success; with `--manual`, waits for Enter.

## explore_step(reason) → ActionResult

- **reason**: Optional string (e.g. `"search_patrol"`).
- **Expected behavior**: One exploration step (e.g. rotate by fixed angle or move forward a short distance).
- **Placeholder**: Logs and returns success; with `--manual`, waits for Enter.

## stop(reason) → ActionResult

- **reason**: Optional string.
- **Expected behavior**: Stop all motion immediately.
- **Placeholder**: Logs and returns success.

## speak(text, reason) → ActionResult

- **text**: String to speak (TTS or play clip).
- **reason**: Optional string (e.g. `"search_callout"`).
- **Expected behavior**: Output audio to speaker or robot TTS.
- **Placeholder**: Prints and logs; with `--manual`, waits for Enter.

## clear_debris(strategy, reason) → ActionResult

- **strategy**: One of `"push"`, `"lift"`, `"mark_only"` (or extend as needed).
- **reason**: Optional string (e.g. `"debris_near_target"`).
- **Expected behavior**: Attempt to clear debris (e.g. push, lift) or mark location for operator.
- **Placeholder**: Logs and returns success; with `--manual`, waits for Enter.

## scan_injuries(reason) → ActionResult

- **reason**: Optional string (e.g. `"injury_scan"`).
- **Expected behavior**: Perform injury scan (e.g. capture viewpoints, run classifier, store results).
- **Placeholder**: Logs and returns success; with `--manual`, waits for Enter.

## send_report(report, reason) → ActionResult

- **report**: `dict` with at least `timestamp`, `phase_log`, `last_humans`, `last_debris`, `last_injuries`, `snapshot_path`.
- **reason**: Optional string (e.g. `"final_report"`).
- **Expected behavior**: Send report to command center (HTTP) or persist; include snapshot if available.
- **Placeholder**: Writes `report` to `./artifacts/reports/report_<timestamp>.json`, appends to JSONL, returns success; with `--manual`, waits for Enter.
