"""The daemon's MCP server as an agent sees it (COREPRODUC-775)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from vinci_daemon.app import create_app
from vinci_mcp.server import TOOL_NAMES
from vinci_runtime.engine import Engine


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    monkeypatch.setenv("VINCI_SKIP_HOME_LOCK", "1")
    monkeypatch.delenv("VINCI_ALLOW_LIVE_SPEND", raising=False)
    engine = Engine(tmp_path)
    engine.init_home(demo=True)
    return TestClient(create_app(engine))


def rpc(client: TestClient, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        body["params"] = params
    res = client.post("/mcp", json=body)
    assert res.status_code == 200
    return dict(res.json())


def tool(client: TestClient, name: str, **arguments: Any) -> dict[str, Any]:
    """The tool result (content, isError); fails on a JSON-RPC error."""
    reply = rpc(client, "tools/call", {"name": name, "arguments": arguments})
    assert "error" not in reply, reply
    return dict(reply["result"])


def data(result: dict[str, Any]) -> dict[str, Any]:
    assert not result.get("isError"), result
    return dict(json.loads(result["content"][0]["text"]))


def test_initialize_negotiates_and_instructs(client: TestClient) -> None:
    init = rpc(client, "initialize", {"protocolVersion": "2025-06-18"})["result"]
    assert init["protocolVersion"] == "2025-06-18"
    assert "vinci.cost_estimate" in init["instructions"]
    assert (
        rpc(client, "initialize", {"protocolVersion": "1999-01-01"})["result"]["protocolVersion"]
        == "2025-11-25"
    )
    assert rpc(client, "ping")["result"] == {}


def test_notification_gets_202_no_body(client: TestClient) -> None:
    res = client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert res.status_code == 202 and res.content == b""


def test_schemas_describe_and_require(client: TestClient) -> None:
    tools = {t["name"]: t["inputSchema"] for t in rpc(client, "tools/list")["result"]["tools"]}
    assert tools["vinci.image_generate"]["required"] == ["prompt"]
    assert tools["vinci.image_generate"]["properties"]["max_cost"]["description"]
    assert tools["vinci.jobs_get"]["properties"]["run_id"]["description"]
    assert tools["vinci.jobs_cancel"]["required"] == ["run_id"]
    for name, schema in tools.items():
        assert "additionalProperties" not in schema, name
        for prop, spec in schema["properties"].items():
            assert spec.get("description"), f"{name}.{prop}"


def test_video_generate_honors_model_id(client: TestClient) -> None:
    result = tool(client, "vinci.video_generate", prompt="a clip", model_id="nope:mp4:v1")
    assert result["isError"] is True  # before: model_id was dropped and the default model ran
    assert "nope:mp4:v1" in result["content"][0]["text"]


def test_top_level_prompt_merges_into_inputs(client: TestClient) -> None:
    run = data(tool(client, "vinci.image_generate", prompt="a red cube", inputs={"seed": 7}))
    assert run["inputs"]["prompt"] == "a red cube" and run["inputs"]["seed"] == 7


def test_jobs_get_reads_a_run(client: TestClient) -> None:
    run = data(tool(client, "vinci.image_generate", prompt="poll me", max_cost=1))
    got = data(tool(client, "vinci.jobs_get", run_id=run["id"]))
    assert got["id"] == run["id"] and got["state"] == "completed" and got["outputs"]
    assert data(tool(client, "vinci.jobs_get", job_id=run["id"]))["id"] == run["id"]
    job = data(tool(client, "vinci.jobs_get", job_id=run["job_ids"][0]))
    assert job["id"] == run["job_ids"][0]  # a job id still reads the job


def test_tool_failure_is_a_result_the_agent_reads(client: TestClient) -> None:
    missing = tool(client, "vinci.jobs_get", run_id="no-such-run")
    assert missing["isError"] is True
    assert "no-such-run" in missing["content"][0]["text"]
    no_arg = tool(client, "vinci.jobs_cancel")
    assert no_arg["isError"] is True and "run_id" in no_arg["content"][0]["text"]
    unknown = rpc(client, "tools/call", {"name": "vinci.nope", "arguments": {}})
    assert unknown["error"]["code"] == -32602  # a protocol error stays a JSON-RPC error
    assert rpc(client, "nope/method")["error"]["code"] == -32601


def test_awaiting_approval_says_the_next_step(client: TestClient) -> None:
    result = tool(client, "vinci.image_generate", prompt="too dear", max_cost=-0.01)
    run = data(result)
    assert run["state"] == "awaiting_approval"
    hint = result["content"][1]["text"]
    assert f"vinci jobs approve {run['id']}" in hint and "max_cost" in hint
    assert f":4311/#cost/{run['id']}" in hint  # the Studio's Approve button (COREPRODUC-786)
    assert not any("approve" in name for name in TOOL_NAMES)  # an agent never approves its spend


def test_cost_estimate_takes_hosted_args(client: TestClient) -> None:
    video = data(
        tool(client, "vinci.cost_estimate", model_id="mock:mp4:v1", inputs={"prompt": "x"})
    )
    assert video["skill"].startswith("@tryvinci/video-generate")
    assert video["nodes"][0]["model_id"] == "mock:mp4:v1"
    image = data(tool(client, "vinci.cost_estimate", prompt="x"))
    assert image["skill"].startswith("@tryvinci/image-generate")
    # The OSS skill argument still works, as on the hosted server (review on #784/#786).
    named = data(tool(client, "vinci.cost_estimate", skill="@tryvinci/video-generate", prompt="x"))
    assert named["skill"].startswith("@tryvinci/video-generate")
