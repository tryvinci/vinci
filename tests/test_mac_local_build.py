from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from mac_local_build_stub import (
    install_mac_stubs,
    layout_oss_tree,
    run_build_local,
    write_conflicting_venv,
)

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "mac" / "build-local.sh"


def test_bash_n_syntax() -> None:
    proc = subprocess.run(
        ["/bin/bash", "-n", str(SCRIPT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr


def test_subprocess_full_success(tmp_path: Path) -> None:
    stub = tmp_path / "bin"
    oss = layout_oss_tree(tmp_path / "work", SCRIPT)
    open_log = tmp_path / "open.log"
    install_mac_stubs(stub, oss)
    proc = run_build_local(oss, stub, {"MAC_STUB_OPEN_LOG": str(open_log)})
    assert proc.returncode == 0, proc.stderr
    assert open_log.is_file()
    assert "open " in open_log.read_text(encoding="utf-8")
    assert "not notarized" in proc.stderr


def test_subprocess_injected_stage_fail_stops_before_open(tmp_path: Path) -> None:
    stub = tmp_path / "bin"
    oss = layout_oss_tree(tmp_path / "work", SCRIPT)
    open_log = tmp_path / "open.log"
    install_mac_stubs(stub, oss)
    proc = run_build_local(
        oss,
        stub,
        {"MAC_STUB_FAIL_TEST": "1", "MAC_STUB_OPEN_LOG": str(open_log)},
    )
    assert proc.returncode != 0
    assert "make_test" in proc.stderr
    assert not open_log.exists()


def test_subprocess_conflicting_venv_without_delete(tmp_path: Path) -> None:
    stub = tmp_path / "bin"
    oss = layout_oss_tree(tmp_path / "work", SCRIPT)
    install_mac_stubs(stub, oss)
    write_conflicting_venv(oss)
    proc = run_build_local(oss, stub, {"MAC_STUB_OPEN_LOG": str(tmp_path / "open.log")})
    assert proc.returncode != 0
    assert "venv" in proc.stderr
    assert "will not delete" in proc.stderr
    assert (oss / ".venv").is_dir()


def test_subprocess_missing_outputs_before_open(tmp_path: Path) -> None:
    stub = tmp_path / "bin"
    oss = layout_oss_tree(tmp_path / "work", SCRIPT)
    open_log = tmp_path / "open.log"
    install_mac_stubs(stub, oss)
    proc = run_build_local(
        oss,
        stub,
        {"MAC_STUB_SKIP_ARTIFACTS": "1", "MAC_STUB_OPEN_LOG": str(open_log)},
    )
    assert proc.returncode != 0
    assert "verify_outputs" in proc.stderr
    assert not open_log.exists()


def test_subprocess_corrupt_sha256sums(tmp_path: Path) -> None:
    stub = tmp_path / "bin"
    oss = layout_oss_tree(tmp_path / "work", SCRIPT)
    open_log = tmp_path / "open.log"
    install_mac_stubs(stub, oss)
    proc = run_build_local(
        oss,
        stub,
        {"MAC_STUB_BAD_SHA": "1", "MAC_STUB_OPEN_LOG": str(open_log)},
    )
    assert proc.returncode != 0
    assert "verify_outputs" in proc.stderr
    assert "SHA256" in proc.stderr
    assert not open_log.exists()


def test_subprocess_gui_id_must_match_console(tmp_path: Path) -> None:
    stub = tmp_path / "bin"
    oss = layout_oss_tree(tmp_path / "work", SCRIPT)
    install_mac_stubs(stub, oss)
    proc = run_build_local(
        oss,
        stub,
        {"MAC_STUB_ID_USER": "alice", "MAC_STUB_CONSOLE_USER": "bob"},
    )
    assert proc.returncode != 0
    assert "gui_session" in proc.stderr
    assert "must match console user" in proc.stderr


def test_subprocess_rejects_mbsetupuser(tmp_path: Path) -> None:
    stub = tmp_path / "bin"
    oss = layout_oss_tree(tmp_path / "work", SCRIPT)
    install_mac_stubs(stub, oss)
    proc = run_build_local(
        oss,
        stub,
        {"MAC_STUB_CONSOLE_USER": "_mbsetupuser", "MAC_STUB_ID_USER": "_mbsetupuser"},
    )
    assert proc.returncode != 0
    assert "gui_session" in proc.stderr


def test_subprocess_rejects_setup_user(tmp_path: Path) -> None:
    stub = tmp_path / "bin"
    oss = layout_oss_tree(tmp_path / "work", SCRIPT)
    install_mac_stubs(stub, oss)
    proc = run_build_local(
        oss,
        stub,
        {"MAC_STUB_CONSOLE_USER": "SetupUser", "MAC_STUB_ID_USER": "SetupUser"},
    )
    assert proc.returncode != 0
    assert "gui_session" in proc.stderr


def test_subprocess_source_path_with_spaces(tmp_path: Path) -> None:
    stub = tmp_path / "bin"
    spaced = tmp_path / "my workspace"
    oss = layout_oss_tree(spaced, SCRIPT)
    open_log = tmp_path / "open.log"
    install_mac_stubs(stub, oss)
    proc = run_build_local(oss, stub, {"MAC_STUB_OPEN_LOG": str(open_log)})
    assert proc.returncode == 0, proc.stderr
    assert (oss / "dist" / "Vinci Studio.app").is_dir()
    assert open_log.is_file()


def test_rejects_non_macos_without_stubs() -> None:
    if sys.platform == "darwin":
        return
    proc = subprocess.run(
        ["/bin/bash", str(SCRIPT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
