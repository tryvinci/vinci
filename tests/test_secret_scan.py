from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "check_no_secrets", ROOT / "scripts" / "check_no_secrets.py"
)
assert SPEC is not None and SPEC.loader is not None
_mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(_mod)


def test_secret_scan_clean_on_tree() -> None:
    assert _mod.scan(ROOT) == []


def test_secret_scan_flags_live_looking_key() -> None:
    token = "ghp_" + "abcdefghijklmnopqrstuvwxyz0123456789"
    hits = _mod.findings_in_text(f'token = "{token}"')
    assert hits
    allowed = _mod.findings_in_text('SECRET = "sk-conformance-never-log-me"')
    assert allowed == []
