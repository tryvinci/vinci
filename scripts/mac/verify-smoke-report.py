#!/usr/bin/env python3
"""Validate JSON from VinciStudio --smoke-report (fail closed)."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

REQUIRED_KEYS = (
    "started_at",
    "finished_at",
    "app_bundle_sha256",
    "git_sha",
    "studio_port",
    "daemon_port",
    "launch_nonce",
    "daemon_pid",
    "steps",
    "studio_readiness_hmac_ok",
    "studio_hydrated_ui_ok",
    "wk_proxy_mock_image_ok",
    "wk_proxy_mock_video_ok",
    "avfoundation_mp4_decode_ok",
    "wk_video_playback_ok",
    "wk_proxy_receipt_ok",
    "wk_proxy_range_206_ok",
    "wk_download_export_ok",
    "app_relaunch_persistence_ok",
    "foreign_daemon_isolated_ok",
    "quit_descendants_clean_ok",
    "proxy_unauth_denied",
    "proxy_cross_origin_denied",
    "proxy_wrong_host_denied",
    "readiness_no_bridge_denied",
    "readiness_wrong_bridge_denied",
    "hijacked_studio_proof_rejected",
    "token_in_logs",
    "screenshot_png",
    "export_file_sha256",
)

MUST_BE_TRUE = (
    "studio_readiness_hmac_ok",
    "studio_hydrated_ui_ok",
    "wk_proxy_mock_image_ok",
    "wk_proxy_mock_video_ok",
    "avfoundation_mp4_decode_ok",
    "wk_video_playback_ok",
    "wk_proxy_receipt_ok",
    "wk_proxy_range_206_ok",
    "wk_download_export_ok",
    "app_relaunch_persistence_ok",
    "foreign_daemon_isolated_ok",
    "quit_descendants_clean_ok",
    "proxy_unauth_denied",
    "proxy_cross_origin_denied",
    "proxy_wrong_host_denied",
    "readiness_no_bridge_denied",
    "readiness_wrong_bridge_denied",
    "hijacked_studio_proof_rejected",
)


def png_not_blank(path: Path) -> bool:
    script = ROOT / "scripts" / "mac" / "png_pixels.py"
    proc = subprocess.run(
        [sys.executable, str(script), str(path)],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


RELAUNCH_MUST_BE_TRUE = (
    "studio_readiness_hmac_ok",
    "app_relaunch_persistence_ok",
    "proxy_unauth_denied",
    "proxy_cross_origin_denied",
    "readiness_no_bridge_denied",
    "readiness_wrong_bridge_denied",
)


def main() -> int:
    argv = [a for a in sys.argv[1:] if a != "--relaunch"]
    relaunch_mode = "--relaunch" in sys.argv
    if len(argv) < 1:
        print(
            "usage: verify-smoke-report.py [--relaunch] <report.json> [screenshot.png] [expected_git_sha] [exe]",
            file=sys.stderr,
        )
        return 2
    path = Path(argv[0])
    must_true = RELAUNCH_MUST_BE_TRUE if relaunch_mode else MUST_BE_TRUE
    if not path.is_file():
        print(f"smoke report missing: {path}", file=sys.stderr)
        return 1
    data = json.loads(path.read_text(encoding="utf-8"))
    missing = [key for key in REQUIRED_KEYS if key not in data]
    if missing:
        print(f"smoke report missing keys: {missing}", file=sys.stderr)
        return 1
    if not isinstance(data["steps"], list) or len(data["steps"]) < 8:
        print("smoke report steps[] too short", file=sys.stderr)
        return 1
    for step in data["steps"]:
        if not step.get("ok"):
            print(f"smoke step failed: {step.get('name')}", file=sys.stderr)
            return 1
    for key in ("started_at", "finished_at", "app_bundle_sha256", "git_sha", "launch_nonce"):
        if not str(data[key]).strip():
            print(f"smoke report empty field: {key}", file=sys.stderr)
            return 1
    for key in must_true:
        if not data[key]:
            print(f"smoke check failed: {key}", file=sys.stderr)
            return 1
    if data["token_in_logs"]:
        print("smoke check failed: token_in_logs", file=sys.stderr)
        return 1
    if int(data["studio_port"]) <= 0 or int(data["daemon_port"]) <= 0:
        print("smoke check failed: invalid ports", file=sys.stderr)
        return 1
    if len(argv) >= 3:
        expected_sha = argv[2].strip()
        if expected_sha and data["git_sha"] != expected_sha:
            print(f"git_sha mismatch: {data['git_sha']} != {expected_sha}", file=sys.stderr)
            return 1
    if len(argv) >= 4:
        exe = Path(argv[3])
        if exe.is_file():
            digest = hashlib.sha256(exe.read_bytes()).hexdigest()
            if data["app_bundle_sha256"] != digest:
                print("app_bundle_sha256 mismatch", file=sys.stderr)
                return 1
    try:
        start = datetime.fromisoformat(str(data["started_at"]).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(data["finished_at"]).replace("Z", "+00:00"))
        if end < start:
            print("finished_at before started_at", file=sys.stderr)
            return 1
    except ValueError:
        print("invalid timestamps", file=sys.stderr)
        return 1
    shot = Path(str(data["screenshot_png"]))
    if len(argv) >= 2:
        shot = Path(argv[1])
    if not relaunch_mode:
        if not shot.is_file() or not png_not_blank(shot):
            print(f"screenshot missing or blank: {shot}", file=sys.stderr)
            return 1
        if not str(data["export_file_sha256"]).strip():
            print("smoke check failed: export_file_sha256 empty", file=sys.stderr)
            return 1
    print(f"smoke report ok: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
