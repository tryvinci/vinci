from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_studio_bundle_is_self_contained() -> None:
    bundle = ROOT / "dist" / "studio-bundle"
    if not (bundle / "server.js").is_file():
        subprocess.run(
            ["/bin/bash", "scripts/mac/prepare-studio-bundle.sh"],
            cwd=ROOT,
            check=True,
            env={**os.environ, "NODE_ENV": "production"},
        )
    assert (bundle / "server.js").is_file()
    iso = Path(tempfile.mkdtemp(prefix="studio-iso-"))
    shutil.copytree(bundle, iso, dirs_exist_ok=True, ignore_dangling_symlinks=True)
    node = shutil.which("node") or "node"
    proc = subprocess.Popen(
        [node, "server.js"],
        cwd=iso,
        env={"PORT": "4395", "HOSTNAME": "127.0.0.1", "NODE_ENV": "production"},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        import time

        import httpx

        for _ in range(40):
            try:
                res = httpx.get("http://127.0.0.1:4395/", timeout=1.0)
                if res.status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.2)
        else:
            err = proc.stderr.read().decode() if proc.stderr else ""
            raise AssertionError(f"studio server failed to start: {err}")
        page = httpx.get("http://127.0.0.1:4395/", timeout=2.0).text
        chunk = ""
        for line in page.splitlines():
            if "/_next/static/" in line and ".js" in line:
                start = line.find("/_next/static/")
                end = line.find('"', start)
                if end > start:
                    chunk = line[start:end]
                    break
        assert chunk, "no static chunk reference in html"
        stat = httpx.get(f"http://127.0.0.1:4395{chunk}", timeout=2.0)
        assert stat.status_code == 200, f"static chunk missing: {chunk}"
    finally:
        proc.terminate()
        proc.wait(timeout=10)
