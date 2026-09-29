from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "create-github-repo.sh"


def test_create_github_repo_script_stays_private() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "tryvinci/vinci" in text
    assert "--private" in text
    assert "TRYVINCI_GITHUB_TOKEN" in text
    assert "npm" in text.lower()
    assert "organizations/tryvinci/repositories/new" in text
    assert "Do not add README" in text
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "./scripts/create-github-repo.sh" in makefile
    env = {**os.environ, "PATH": os.environ.get("PATH", "")}
    refused = subprocess.run(
        ["bash", str(SCRIPT), "--public"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert refused.returncode == 2
    assert "refusing --public" in refused.stderr
