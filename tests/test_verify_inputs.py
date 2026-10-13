from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERIFY = ROOT / "scripts/mac/verify-inputs.py"
LOCK = ROOT / "scripts/mac/deps.lock.json"


def test_verify_inputs_rejects_placeholder(tmp_path: Path) -> None:
    data = json.loads(LOCK.read_text(encoding="utf-8"))
    data["node"]["sha256"] = "PLACEHOLDER"
    bad = tmp_path / "deps.lock.json"
    bad.write_text(json.dumps(data), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(VERIFY), "--lock", str(bad)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0


def test_verify_inputs_ok_on_committed_lock() -> None:
    proc = subprocess.run([sys.executable, str(VERIFY)], cwd=ROOT, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
