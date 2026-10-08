from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CI = ROOT / ".github" / "workflows" / "ci.yml"


def test_ci_installs_ffmpeg_and_runs_phase0_exits() -> None:
    text = CI.read_text(encoding="utf-8")
    assert "ffmpeg" in text
    assert "make free-gate" in text
    assert "ci-artifacts/free-gate" in text
    assert "make clone-smoke" in text
    assert "VINCI_ALLOW_LIVE_SPEND=1" not in text
    assert "test -z \"${VINCI_ALLOW_LIVE_SPEND:-}\"" in text
    assert "workflow_dispatch" in text
