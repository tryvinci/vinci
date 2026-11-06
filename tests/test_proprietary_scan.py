from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "check_no_proprietary", ROOT / "scripts" / "check_no_proprietary.py"
)
assert SPEC is not None and SPEC.loader is not None
_mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(_mod)


def test_skip_dirs_match_inside_the_tree_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A checkout under a dir named like a skip entry is still scanned; the in-tree cache is not."""
    root = tmp_path / ".mac-bundle-cache" / "vinci-oss"
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (root / ".mac-bundle-cache" / "lib").mkdir(parents=True)
    (root / ".mac-bundle-cache" / "lib" / "b.py").write_text("y = 1\n", encoding="utf-8")
    monkeypatch.setattr(_mod, "ROOT", root)
    assert [p.relative_to(root).as_posix() for p in _mod._iter_files()] == ["src/a.py"]
