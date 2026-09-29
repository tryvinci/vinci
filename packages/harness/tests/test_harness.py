from __future__ import annotations

from pathlib import Path

import pytest
from vinci_harness import __version__
from vinci_harness.__main__ import main, run_demo


def test_harness_version() -> None:
    assert __version__ == "0.1.0"


def test_harness_cli_points_at_local_scripts(capsys: pytest.CaptureFixture[str]) -> None:
    main([])
    captured = capsys.readouterr()
    assert "./scripts/vinci" in captured.out
    assert "vinci_daemon" in captured.out
    assert "vinci_harness demo" in captured.out


def test_harness_demo_image_generate_zero_cost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    payload = run_demo(tmp_path)
    captured = capsys.readouterr()
    assert payload["state"] == "completed"
    assert payload["computed_cost"] == 0
    assert payload["live_usd"] == 0
    assert payload["outputs"]
    assert payload["receipt_uri"].startswith("vinci://receipts/")
    assert payload["asset_uri"].startswith("vinci://assets/")
    assert payload["job_uri"].startswith("vinci://jobs/")
    assert payload["asset_uris"]
    assert payload["job_uris"]
    assert payload["png_ihdr"] == [960, 540]
    assert payload["replay_cached"] is True
    assert payload["replay_cost"] == 0
    assert payload["replay_outputs"] == payload["outputs"]
    assert "\"computed_cost\": 0" in captured.out
    assert "\"replay_cached\": true" in captured.out
