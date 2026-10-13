"""Redact launch secrets before writing logs."""

from __future__ import annotations

import os
import re


def bridge_token() -> str:
    return os.environ.get("VINCI_BRIDGE_TOKEN", "").strip()


def redact_text(text: str) -> str:
    token = bridge_token()
    out = text
    if token:
        out = out.replace(token, "[REDACTED_BRIDGE_TOKEN]")
        out = out.replace(f"Bearer {token}", "Bearer [REDACTED_BRIDGE_TOKEN]")
    return re.sub(
        r"(authorization\s*:\s*Bearer\s+)([^\s,]+)",
        r"\1[REDACTED]",
        out,
        flags=re.IGNORECASE,
    )
