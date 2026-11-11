"""Agent CLIs as text models (vinci_provider_sdk/agent_cli.py), run on fake CLIs.

Each fake records its arguments, stdin and folder, and answers in its CLI's own output format.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from vinci_daemon.app import create_app
from vinci_olf.project import OlfError
from vinci_olf.render import run_one
from vinci_protocol.enums import Capability
from vinci_provider_sdk.agent_cli import AGENT_CLIS, AgentCliProvider, run_cli
from vinci_provider_sdk.conformance import run_conformance
from vinci_runtime.engine import Engine

FAKE = """#!{python}
import json, os, sys, time
name, args = os.path.basename(sys.argv[0]), sys.argv[1:]
stdin, mode = sys.stdin.read(), os.environ.get("FAKE_CLI_MODE", "ok")
files = {{f: open(f).read() for f in os.listdir(".")}}
row = {{"name": name, "argv": args, "stdin": stdin, "cwd": os.getcwd(), "files": files}}
with open(os.environ["FAKE_CLI_LOG"], "a") as log:
    log.write(json.dumps(row) + "\\n")
if mode == "slow":
    time.sleep(5)
if mode == "fail":
    sys.exit(print("boom: model overloaded", file=sys.stderr) or 3)
answer = "" if mode == "empty" else "EXT. HARBOR - NIGHT\\n\\nAnswer from " + name + "."
if name in ("claude", "cursor-agent"):
    bad = mode == "error"
    text = "Not logged in · Please run /login" if bad else answer
    print(json.dumps({{"type": "result", "is_error": bad, "result": text}}))
    sys.exit(1 if bad else 0)
if name == "agy":
    bad = {{"status": "ERROR", "error": "quota exceeded"}}
    print(json.dumps(bad if mode == "error" else {{"status": "SUCCESS", "response": answer}}))
elif name == "codex":
    open(args[args.index("-o") + 1], "w").write(answer)
elif mode == "error":  # opencode reports a failure as an error event
    print(json.dumps({{"type": "error", "error": {{"message": "Free usage limit reached."}}}}))
    sys.exit(1)
else:  # opencode: events; a first step's text is not the answer
    for event in ({{"type": "step_start"}}, {{"type": "text", "part": {{"text": "Thinking."}}}},
                  {{"type": "step_start"}}, {{"type": "text", "part": {{"text": answer}}}}):
        print(json.dumps(event))
"""


@pytest.fixture
def fake_clis(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Fake CLIs for all five agent CLIs; returns the log they append to."""
    folder = tmp_path / "bin"
    folder.mkdir()
    for cli in AGENT_CLIS.values():
        script = folder / cli.binary
        script.write_text(FAKE.format(python=sys.executable), encoding="utf-8")
        script.chmod(0o755)
    monkeypatch.setenv("VINCI_AGENT_CLI_PATH", str(folder))
    monkeypatch.setenv("FAKE_CLI_LOG", str(tmp_path / "calls.jsonl"))
    monkeypatch.delenv("FAKE_CLI_MODE", raising=False)
    monkeypatch.delenv("VINCI_ALLOW_LIVE_SPEND", raising=False)
    return tmp_path / "calls.jsonl"


def _calls(log: Path) -> dict[str, dict]:
    return {row["name"]: row for row in map(json.loads, log.read_text().splitlines())}


def test_each_cli_runs_once_in_an_empty_folder_with_tools_off(fake_clis: Path) -> None:
    for cli in AGENT_CLIS.values():
        assert run_cli_name(cli.binary) == f"EXT. HARBOR - NIGHT\n\nAnswer from {cli.binary}."
    calls, both = _calls(fake_clis), "SYSTEM\n\nPROMPT"  # no system flag: it goes first
    claude = calls["claude"]
    assert claude["argv"] == [
        "-p",
        "--output-format",
        "json",
        "--tools",
        "",  # no tools at all
        "--no-session-persistence",
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--system-prompt",
        "SYSTEM",
    ]
    assert claude["stdin"] == "PROMPT"
    codex = calls["codex"]
    assert codex["argv"][:3] == ["exec", "--sandbox", "read-only"] and codex["stdin"] == both
    assert calls["agy"]["argv"][-2:] == ["-p", both] and calls["agy"]["stdin"] == ""
    cursor = ["-p", "--output-format", "json", "--mode", "ask", "--trust", "--model", "auto", both]
    assert calls["cursor-agent"]["argv"] == cursor
    opencode = calls.pop("opencode")
    assert opencode["argv"] == ["run", "--agent", "vinci-text", "--format", "json", both]
    # OpenCode gets one file: its vinci-text agent denies every tool on every resource.
    agent = json.loads(opencode["files"]["opencode.json"])["agents"]["vinci-text"]
    assert agent["permissions"] == [{"action": "*", "resource": "*", "effect": "deny"}]
    for call in calls.values():  # a new empty folder each time, removed after the run
        assert call["files"] == {} and Path(call["cwd"]).name.startswith("vinci-cli-")
        assert not Path(call["cwd"]).exists()
    assert [n for n, cli in AGENT_CLIS.items() if cli.tools_off] == ["claude_code"]


def run_cli_name(binary: str, **kw: object) -> str:
    name = next(n for n, cli in AGENT_CLIS.items() if cli.binary == binary)
    return run_cli(name, "PROMPT", "SYSTEM", **kw)  # type: ignore[arg-type]


def test_cli_failures_say_why(
    fake_clis: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_CLI_MODE", "fail")
    with pytest.raises(RuntimeError, match="^Codex failed: boom: model overloaded$"):
        run_cli_name("codex")
    monkeypatch.setenv("FAKE_CLI_MODE", "error")  # the CLI's own words win over the exit code
    with pytest.raises(
        RuntimeError, match="^Claude Code failed: Not logged in · Please run /login$"
    ):
        run_cli_name("claude")
    with pytest.raises(RuntimeError, match="^Antigravity failed: quota exceeded$"):
        run_cli_name("agy")
    with pytest.raises(RuntimeError, match="^OpenCode failed: Free usage limit reached.$"):
        run_cli_name("opencode")
    monkeypatch.setenv("FAKE_CLI_MODE", "empty")
    with pytest.raises(RuntimeError, match="^OpenCode failed: it gave no answer$"):
        run_cli_name("opencode")
    monkeypatch.setenv("FAKE_CLI_MODE", "slow")
    with pytest.raises(TimeoutError, match="^Cursor Agent did not answer in 1 s$"):
        run_cli_name("cursor-agent", timeout=1)
    monkeypatch.setenv("VINCI_AGENT_CLI_PATH", str(tmp_path / "nothing-here"))
    with pytest.raises(
        FileNotFoundError, match="^Claude Code is not installed: no claude on PATH$"
    ):
        run_cli_name("claude")


def test_engine_runs_an_agent_cli_only_when_picked(fake_clis: Path, tmp_path: Path) -> None:
    engine = Engine(tmp_path / "home")
    engine.init_home(demo=True)
    assert set(AGENT_CLIS) <= engine.routing_providers()
    spec = engine.catalog().by_id("claude_code:cli")
    assert (spec.pricing.currency, spec.capabilities) == ("PLAN", [Capability.T2T])
    run_conformance(AgentCliProvider("claude_code", engine.cas))
    params = {"prompt": "Write.", "system": "Be brief.", "mock_reply": "mock", "olf_request": "1"}
    # Routing never picks a CLI: it bills the person's own sign-in.
    auto = run_one("t2t", params, yes=True, engine=engine)
    assert auto["plan"][0]["model"] == "mock:llm:v1" and auto["output"] == b"mock"
    picked = {"model": "claude_code:cli", "engine": engine}
    plan = run_one("t2t", params, dry_run=True, **picked)
    assert (plan["total"], plan["unpriced"]) == (0, ["claude_code:cli"])
    with pytest.raises(OlfError, match="no flat price"):  # a picked CLI still asks first
        run_one("t2t", params, **picked)
    out = run_one("t2t", params | {"olf_request": "2"}, yes=True, **picked)
    assert out["output"] == b"EXT. HARBOR - NIGHT\n\nAnswer from claude."
    assert out["provenance"]["provider"] == "claude_code"
    # Live mode with no keys: nothing to route to, but a picked CLI runs.
    engine.init_home(demo=False)
    with pytest.raises(OlfError, match="no connected model can make t2t"):
        run_one("t2t", params | {"olf_request": "3"}, yes=True, engine=engine)
    codex = run_one(
        "t2t", params | {"olf_request": "4"}, model="codex:cli", yes=True, engine=engine
    )
    assert codex["output"] == b"EXT. HARBOR - NIGHT\n\nAnswer from codex."


def test_text_model_menu_and_routes(fake_clis: Path, tmp_path: Path) -> None:
    engine = Engine(tmp_path / "home")
    engine.init_home(demo=True)
    client = TestClient(create_app(engine))
    menu = client.get("/olf/models", params={"capability": "t2t"}).json()
    assert menu["auto"]["model"] == "mock:llm:v1" and menu["choices"][0]["id"] == "mock:llm:v1"
    assert {
        "id": "claude_code:cli",
        "name": "Claude Code",
        "provider": "claude_code",
        "amount": 0.0,
        "currency": "PLAN",
        "unpriced": True,
        "tools": False,  # Claude Code runs with no tools; the others keep some, so the Studio warns
    } in menu["choices"]
    assert {c["id"]: c.get("tools") for c in menu["choices"]}["codex:cli"] is True
    # Draft from idea on Claude Code: the price check, then the step after the person says yes.
    body = {"idea": "A fox keeps a light.", "model": "claude_code:cli"}
    plan = client.post("/olf/draft", json=body | {"dry_run": True}).json()
    assert plan["plan"][0]["model"] == "claude_code:cli" and plan["text"] is None
    assert client.post("/olf/draft", json=body).status_code == 400  # it asks first
    draft = client.post("/olf/draft", json=body | {"yes": True}).json()
    assert draft["text"] == "EXT. HARBOR - NIGHT\n\nAnswer from claude."
    claude = _calls(fake_clis)["claude"]
    assert claude["stdin"] == "A fox keeps a light." and "Fountain" in claude["argv"][-1]
    # Split with a model on Codex: the system text goes before the script; the answer is parsed.
    script = "EXT. CLIFF PATH - DUSK\n\nMira climbs.\n"
    body = {"script": script, "model": "codex:cli", "yes": True}
    split = client.post("/olf/script/model", json=body).json()
    assert split["preview"]["shots"] == 1
    stdin = _calls(fake_clis)["codex"]["stdin"]
    assert stdin.startswith("You turn film scripts into shot lists.") and stdin.endswith(script)


def test_live_mode_with_only_a_cli_explains_a_render(
    fake_clis: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An installed CLI counts as connected, so a render plan with no image model stops in words.

    It gave HTTP 500 before (bug found 2026-11-09 in self-review; docs/OLF_ENGINE.md).
    """
    from vinci_runtime.engine import all_secret_names

    for name in all_secret_names():
        monkeypatch.delenv(name, raising=False)
    engine = Engine(tmp_path / "home")
    engine.init_home(demo=False)
    assert engine.routing_providers() == set(AGENT_CLIS)
    client = TestClient(create_app(engine))
    path = client.post("/olf/sample").json()["path"]
    shot = client.get("/olf/shot", params={"path": path, "shot": "e02/s03/sh014"})
    error = shot.json()["plans"]["keyframe"]["error"]
    assert shot.status_code == 200 and error.startswith("no connected model can render this")
    body = {"path": path, "shot": "e02/s03/sh014", "kind": "keyframe", "dry_run": True}
    assert client.post("/olf/render", json=body).status_code == 400
