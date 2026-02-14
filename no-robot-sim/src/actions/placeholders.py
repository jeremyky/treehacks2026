"""
Placeholder ActionClient: print ACTION[name] args=... reason=..., log to JSONL, return success.
If config.MANUAL_CONFIRM_ACTIONS, wait for Enter before returning.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from .action_client import ActionClient
from .types import ActionResult

# Set by main so placeholders can check without importing config
MANUAL_CONFIRM_ACTIONS: bool = False
_ARTIFACTS_DIR: str = "artifacts"
_JSONL_PATH: str = "artifacts/action_calls.jsonl"


def set_manual_confirm(value: bool) -> None:
    global MANUAL_CONFIRM_ACTIONS
    MANUAL_CONFIRM_ACTIONS = value


_REPORTS_DIR: str = "artifacts/reports"


def set_artifacts_dir(path: str) -> None:
    global _ARTIFACTS_DIR, _JSONL_PATH, _REPORTS_DIR
    _ARTIFACTS_DIR = path
    _JSONL_PATH = os.path.join(path, "action_calls.jsonl")
    _REPORTS_DIR = os.path.join(path, "reports")


def _ensure_artifacts() -> None:
    Path(_ARTIFACTS_DIR).mkdir(parents=True, exist_ok=True)


def _log_action(name: str, args: dict[str, Any], reason: str) -> None:
    _ensure_artifacts()
    line = json.dumps({"action": name, "args": args, "reason": reason}) + "\n"
    with open(_JSONL_PATH, "a", encoding="utf-8") as f:
        f.write(line)


def _print_action(name: str, args: dict[str, Any], reason: str) -> None:
    print(f"ACTION[{name}]({', '.join(f'{k}={v!r}' for k, v in args.items())} reason={reason!r})")
    sys.stdout.flush()


def _wait_enter_if_manual() -> None:
    if MANUAL_CONFIRM_ACTIONS:
        try:
            input("  [Press Enter to simulate action done] ")
        except EOFError:
            pass


class PlaceholderActionClient(ActionClient):
    """WoZ: every action prints, logs to JSONL, returns success; optional wait for Enter."""

    def _run(self, name: str, args: dict[str, Any], reason: str) -> ActionResult:
        _print_action(name, args, reason)
        _log_action(name, args, reason)
        _wait_enter_if_manual()
        return ActionResult(success=True, details={"logged": True}, simulated=True)

    def navigate_to(self, target_pose: dict[str, Any], reason: str = "") -> ActionResult:
        return self._run(
            "navigate_to",
            {"target_pose": target_pose, "x": target_pose.get("x"), "y": target_pose.get("y"), "yaw": target_pose.get("yaw")},
            reason,
        )

    def explore_step(self, reason: str = "") -> ActionResult:
        return self._run("explore_step", {}, reason)

    def stop(self, reason: str = "") -> ActionResult:
        return self._run("stop", {}, reason)

    def speak(self, text: str, reason: str = "") -> ActionResult:
        return self._run("speak", {"text": text}, reason)

    def clear_debris(self, strategy: str, reason: str = "") -> ActionResult:
        return self._run("clear_debris", {"strategy": strategy}, reason)

    def scan_injuries(self, reason: str = "") -> ActionResult:
        return self._run("scan_injuries", {}, reason)

    def send_report(self, report: dict[str, Any], reason: str = "") -> ActionResult:
        Path(_REPORTS_DIR).mkdir(parents=True, exist_ok=True)
        import time as _time
        ts = _time.strftime("%Y%m%d_%H%M%S", _time.localtime())
        report_path = os.path.join(_REPORTS_DIR, f"report_{ts}.json")
        with open(report_path, "w", encoding="utf-8") as f:
            import json as _json
            _json.dump(report, f, indent=2)
        _print_action("send_report", {"report_keys": list(report.keys()), "path": report_path}, reason)
        _log_action("send_report", {"report_keys": list(report.keys()), "path": report_path}, reason)
        _wait_enter_if_manual()
        return ActionResult(success=True, details={"path": report_path}, simulated=True)
