"""Actions: ActionClient interface + PlaceholderActionClient for Wizard-of-Oz."""

from .action_client import ActionClient
from .placeholders import PlaceholderActionClient, set_manual_confirm, set_artifacts_dir
from .types import ActionResult

__all__ = [
    "ActionClient",
    "PlaceholderActionClient",
    "ActionResult",
    "set_manual_confirm",
    "set_artifacts_dir",
]
