from __future__ import annotations

import re
from typing import Any

# Values that look like live keys are stripped from logs/jobs/MCP payloads.
SECRET_PATTERNS = (re.compile(r"(?i)(api[_-]?key|secret|token|authorization|password|bearer)"),)

_REDACTED = "[redacted]"


def redact_text(text: str, extra_values: list[str] | None = None) -> str:
    out = text
    for value in extra_values or []:
        if value and value in out:
            out = out.replace(value, _REDACTED)
    return out


def _is_secret_key(key: str) -> bool:
    return any(p.search(key) for p in SECRET_PATTERNS)


def redact_mapping(data: Any, extra_values: list[str] | None = None) -> Any:
    if isinstance(data, dict):
        out: dict[str, Any] = {}
        for key, value in data.items():
            if _is_secret_key(str(key)):
                out[str(key)] = _REDACTED
            else:
                out[str(key)] = redact_mapping(value, extra_values)
        return out
    if isinstance(data, list):
        return [redact_mapping(item, extra_values) for item in data]
    if isinstance(data, str):
        return redact_text(data, extra_values)
    return data
