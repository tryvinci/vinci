"""Settings for every test in the repo (packages and tests)."""

import pytest


@pytest.fixture(autouse=True)
def _no_agent_clis(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Agent CLIs installed on this machine stay out of tests, so no test runs a real Claude Code.

    A test that wants one points ``VINCI_AGENT_CLI_PATH`` at its fake CLIs.
    """
    none = tmp_path_factory.getbasetemp() / "no-agent-clis"
    monkeypatch.setenv("VINCI_AGENT_CLI_PATH", str(none))
