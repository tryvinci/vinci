from __future__ import annotations

import shutil
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_vinci_wrapper_before_install(tmp_path: Path) -> None:
    # Simulate a fresh clone: the wrapper alone, with no node_modules and no built CLI.
    # (CI runs `make install` before the tests, so the real checkout is already built.)
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    wrapper = scripts / "vinci"
    shutil.copy2(ROOT / "scripts" / "vinci", wrapper)
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)

    result = subprocess.run(
        [str(wrapper), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "Run make install first" in result.stderr
    assert "tsc: not found" not in result.stderr + result.stdout
