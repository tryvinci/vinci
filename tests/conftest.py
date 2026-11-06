# Import helper: mac_local_build_stub lives alongside tests (test-only PATH stubs).
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def npm_notice_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Write the npm graph + notices from a fake Studio bundle, as prepare-studio-bundle.sh does.

    The fake bundle holds each top-level production package in package-lock.json. So the
    tests do not need dist/notices (build output, COREPRODUC-508 part B).

    Returns:
        A directory to use as ``VINCI_MAC_NPM_NOTICE_DIR``.
    """
    out = tmp_path_factory.mktemp("npm-notices")
    nm = out / "bundle/node_modules"
    lock = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))["packages"]
    for key, meta in lock.items():
        name = key.removeprefix("node_modules/")
        if name == key or "node_modules/" in name or meta.get("dev") or meta.get("link") or not meta.get("license"):
            continue
        (nm / name).mkdir(parents=True)
        pkg = {"name": name, "version": meta["version"]}
        (nm / name / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
    env = {**os.environ, "VINCI_MAC_NPM_NOTICE_DIR": str(out)}
    mac = ROOT / "scripts/mac"
    for cmd in (["write-studio-bundle-npm-graph.py", str(nm.parent)], ["collect-npm-notices.py"]):
        subprocess.run([sys.executable, str(mac / cmd[0]), *cmd[1:]], env=env, check=True)
    return out
