"""A small reader for TOON, the indented text some MCP servers answer instead of JSON.

Magnific answers ``creations_search`` and ``spaces_state`` only in TOON (seen 2026-11-16,
COREPRODUC-658). It reads the parts those answers use:

- ``key: value`` and nested objects by indent (2 spaces);
- ``key[N]:`` with ``- `` items (objects or values);
- ``key[N]: a,b`` (values on one line);
- ``key[N]{a,b}:`` tables, one row per line.

Values: a quoted string is JSON; ``true``, ``false``, ``null`` and numbers are typed; the rest
is text.
"""

from __future__ import annotations

import json
import re
from typing import Any

_KEY = re.compile(
    r'^(?P<key>"(?:[^"\\]|\\.)*"|[^:\[{"]+?)'
    r"(?:\[(?P<n>\d*)(?P<delim>[|\t]?)\](?:\{(?P<fields>[^}]*)\})?)?:(?: (?P<rest>.*))?$"
)
_NUMBER = re.compile(r"^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?$")


def loads(text: str) -> Any:
    """Read a TOON document.

    Args:
        text: The document.

    Returns:
        The object (or list) it holds.

    Raises:
        ValueError: A line is not TOON.
    """
    lines: list[list[Any]] = [
        [len(raw) - len(raw.lstrip(" ")), raw.strip()] for raw in text.splitlines() if raw.strip()
    ]
    if not lines:
        return {}
    value, _ = _object(lines, 0, lines[0][0])
    return value


def _object(lines: list[list[Any]], i: int, indent: int) -> tuple[dict[str, Any], int]:
    out: dict[str, Any] = {}
    while i < len(lines) and lines[i][0] == indent and not lines[i][1].startswith("-"):
        match = _KEY.match(lines[i][1])
        if not match:
            raise ValueError(f"not a TOON line: {lines[i][1][:60]!r}")
        key = _value(match["key"].strip())
        rest = match["rest"]
        deeper = i + 1 < len(lines) and lines[i + 1][0] > indent
        if match["n"] is not None:  # a list
            delim = match["delim"] or ","
            if match["fields"] is not None:
                names = [_value(f.strip()) for f in _split(match["fields"], delim)]
                rows, i = [], i + 1
                while i < len(lines) and lines[i][0] > indent:
                    cells = [_value(v) for v in _split(lines[i][1], delim)]
                    rows.append(dict(zip(names, cells, strict=False)))  # a short row: no value
                    i += 1
                out[key] = rows
            elif rest:
                out[key], i = [_value(v) for v in _split(rest, delim)], i + 1
            elif deeper:
                out[key], i = _list(lines, i + 1, lines[i + 1][0])
            else:
                out[key], i = [], i + 1
        elif rest is not None and rest != "":
            out[key], i = _value(rest), i + 1
        elif deeper:
            out[key], i = _object(lines, i + 1, lines[i + 1][0])
        else:
            out[key], i = {}, i + 1
    return out, i


def _list(lines: list[list[Any]], i: int, indent: int) -> tuple[list[Any], int]:
    out: list[Any] = []
    while i < len(lines) and lines[i][0] == indent and lines[i][1].startswith("-"):
        item = lines[i][1][1:].strip()
        if _KEY.match(item) and not item.startswith('"'):
            lines[i] = [indent + 2, item]  # the item's first key sits with the keys under it
            value, i = _object(lines, i, indent + 2)
            out.append(value)
        else:
            out.append(_value(item))
            i += 1
    return out, i


def _split(row: str, delim: str) -> list[str]:
    """Split one row on the delimiter, outside quoted strings."""
    cells, cur, quoted, escaped = [], [], False, False
    for ch in row:
        if escaped:
            cur.append(ch)
            escaped = False
        elif ch == "\\" and quoted:
            cur.append(ch)
            escaped = True
        elif ch == '"':
            cur.append(ch)
            quoted = not quoted
        elif ch == delim and not quoted:
            cells.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    cells.append("".join(cur))
    return [c.strip() for c in cells]


def _value(raw: str) -> Any:
    if raw.startswith('"') and raw.endswith('"') and len(raw) >= 2:
        return json.loads(raw)
    if raw in ("true", "false"):
        return raw == "true"
    if raw == "null":
        return None
    if _NUMBER.match(raw):
        return float(raw) if any(c in raw for c in ".eE") else int(raw)
    return raw
