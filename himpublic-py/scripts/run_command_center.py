#!/usr/bin/env python3
"""Run the command center FastAPI server."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure src is on path
repo_root = Path(__file__).resolve().parent.parent
src = repo_root / "src"
if str(src) not in sys.path:
    sys.path.insert(0, str(src))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "himpublic.comms.command_center_server:app",
        host="0.0.0.0",  # Listen on all interfaces so robot can reach us
        port=8000,
        reload=False,
    )
