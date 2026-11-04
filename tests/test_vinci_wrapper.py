from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_vinci_wrapper_before_install() -> None:
    result = subprocess.run(
        [str(ROOT / "scripts" / "vinci"), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "Run make install first" in result.stderr
    assert "tsc: not found" not in result.stderr + result.stdout
