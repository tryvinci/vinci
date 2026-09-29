from __future__ import annotations

import os
from pathlib import Path

DEFAULT_HOME_NAME = ".vinci"


def default_home() -> Path:
    override = os.environ.get("VINCI_HOME")
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / DEFAULT_HOME_NAME


def allow_live_spend() -> bool:
    """Live provider HTTP is off unless explicitly enabled. CI must never set this."""
    return os.environ.get("VINCI_ALLOW_LIVE_SPEND", "") == "1"
