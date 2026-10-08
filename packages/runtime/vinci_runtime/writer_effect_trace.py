"""Test-only attribution of side effects to stale vs owner writer roles."""

from __future__ import annotations

import json
import os
from pathlib import Path

_EFFECTS_FILE = "effects.jsonl"


def record_writer_effect(phase: str) -> None:
    effects_dir = os.environ.get("VINCI_TEST_WRITER_EFFECTS_DIR")
    if not effects_dir:
        return
    role = os.environ.get("VINCI_TEST_WRITER_ROLE", "unknown")
    path = Path(effects_dir)
    path.mkdir(parents=True, exist_ok=True)
    payload = {"role": role, "phase": phase}
    with (path / _EFFECTS_FILE).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def count_writer_effects(
    effects_dir: Path | str,
    *,
    role: str,
    phase: str | None = None,
) -> int:
    path = Path(effects_dir) / _EFFECTS_FILE
    if not path.is_file():
        return 0
    total = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("role") != role:
            continue
        if phase is not None and row.get("phase") != phase:
            continue
        total += 1
    return total
