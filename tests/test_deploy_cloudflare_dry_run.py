from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy/cloudflare/scripts/deploy.sh"
CF_ROOT = ROOT / "deploy/cloudflare"


def test_deploy_script_dry_run() -> None:
    env = {**os.environ, "DRY_RUN": "1", "FIXTURE_MODE": "1", "ROOT": str(CF_ROOT)}
    out = subprocess.run(
        ["bash", str(DEPLOY)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert out.returncode == 0, out.stderr + out.stdout
    assert "dry-run ok" in out.stdout
    assert "fixture ok" in out.stdout


def test_parse_deploy_url_extracts_workers_dev(tmp_path: Path) -> None:
    lib = CF_ROOT / "scripts/lib.sh"
    log = tmp_path / "deploy.log"
    log.write_text(
        "Uploaded vinci-selfhost\n"
        "  https://vinci-oss-selfhost.acme-sub.workers.dev\n"
        "Current Version ID: abc\n",
        encoding="utf-8",
    )
    out = subprocess.run(
        ["bash", "-c", f'source "{lib}"; parse_deploy_url "{log}"'],
        cwd=CF_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert out.returncode == 0, out.stderr + out.stdout
    assert out.stdout.strip() == "https://vinci-oss-selfhost.acme-sub.workers.dev"


def test_deploy_script_bucket_before_r2_probe() -> None:
    text = DEPLOY.read_text(encoding="utf-8")
    assert text.index("ensure_bucket") < text.index("verify_r2_credentials")


def test_subtree_has_selfhost_docs() -> None:
    doc = ROOT / "docs/SELF_HOST_CLOUDFLARE.md"
    assert doc.is_file()
    text = doc.read_text(encoding="utf-8")
    assert "VINCI_INSTANCE_SECRET" in text
    assert "workers.dev" in text
    assert "one-click" not in text.lower()
    assert "production ready" not in text.lower()
    assert "VINCI_DURABLE_JOURNAL" in text
    assert "durable-before-ack" in text.lower()
