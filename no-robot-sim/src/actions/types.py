"""Action result type. Same for placeholders and real implementations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ActionResult:
    """Result of an action call. Teammates use this for real hardware too."""

    success: bool
    details: str | dict[str, Any] | None = None
    simulated: bool = True  # False when real hardware was used
