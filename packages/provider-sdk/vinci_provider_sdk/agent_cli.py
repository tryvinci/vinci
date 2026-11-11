"""Agent CLIs as text models: Claude Code, Codex, Antigravity, Cursor Agent and OpenCode.

A person who has signed in to an agent CLI can run text steps (``t2t``) on it. Each installed CLI
is a provider with one model, ``<provider>:cli``, which uses the CLI's own default model. A job
runs the CLI once in its print (or exec) mode, in a new empty folder, and returns its final
answer. The CLI bills the person's own sign-in (a plan or a key), so the model has no Vinci price:
its currency is ``PLAN``. Automatic routing takes USD models only, so a CLI runs only when a
person picks it, and a text step asks first. The live-spend switch does not apply: Vinci sends
no request of its own.

Tools: a script can carry instructions for the agent (prompt injection), so each CLI runs with
as few tools as it allows. Claude Code has none (``--tools ""``, checked: it cannot read a file or
fetch a page). OpenCode runs a ``vinci-text`` agent that denies every tool (an ``opencode.json``
in the run folder, OpenCode v2 permissions). Cursor Agent runs in ``ask`` mode (checked: it reads
files but cannot fetch), Codex in a ``read-only`` sandbox (no network), and Antigravity has no
switch (its print mode refuses actions that need approval). Every CLI but Claude Code is marked
``tools_off=False``, so the Studio warns before it runs. Flags are from each CLI's docs (checked
2026-11-09); Claude Code, Cursor Agent and OpenCode were also run. Only the Shows text model menu
lists them so far; Connect and the canvas pickers follow in COREPRODUC-557.
"""

from __future__ import annotations

import json
import logging
import os
import shlex
import shutil
import subprocess
import tempfile
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from vinci_core.cost import estimate_from_spec, idempotency_key
from vinci_protocol.enums import Capability, ErrorCode, JobState
from vinci_protocol.models import (
    Estimate,
    JobRequest,
    JobStatus,
    ModelSpec,
    Pricing,
    ProviderJobRef,
    ProviderManifest,
    VinciError,
)
from vinci_storage.cas import CasStore

from vinci_provider_sdk.base import Provider

log = logging.getLogger("vinci.provider")
TIMEOUT = 300.0  # seconds: an agent CLI can take minutes on a long script
# An app opened from the Dock has a short PATH (the Mac app passes only its own bin folder), so
# look in the usual install folders too: ~/.local/bin (Claude Code, Cursor Agent, agy), Homebrew.
INSTALL_DIRS = ("~/.local/bin", "/opt/homebrew/bin", "/usr/local/bin")
SNAPSHOT = datetime(2026, 11, 9, tzinfo=UTC)  # when the flags below were checked


class CliError(RuntimeError):
    """The CLI reported a failure in its own output (for example: not signed in)."""


def _result(out: str, folder: Path) -> str:
    """Claude Code and Cursor Agent: one JSON object; ``result`` is the answer or the error."""
    body = json.loads(out)
    if body.get("is_error"):
        raise CliError(str(body.get("result") or body.get("subtype") or "error"))
    return str(body.get("result") or "")


def _response(out: str, folder: Path) -> str:
    """Antigravity: one JSON object with ``status``, and ``response`` or ``error``."""
    body = json.loads(out)
    if body.get("status") != "SUCCESS":
        raise CliError(str(body.get("error") or body.get("status") or "error"))
    return str(body.get("response") or "")


def _answer_file(out: str, folder: Path) -> str:
    """Codex: ``-o answer.txt`` writes the final message to a file."""
    return (folder / "answer.txt").read_text(encoding="utf-8")


def _events(out: str, folder: Path) -> str:
    """OpenCode: one JSON event per line; the answer is the text of the last step."""
    text: list[str] = []
    for line in out.splitlines():
        event = json.loads(line) if line.startswith("{") else {}
        if event.get("type") == "step_start":
            text = []
        elif event.get("type") == "text":
            text.append(str((event.get("part") or {}).get("text") or ""))
        elif event.get("type") == "error":  # "Free usage limit reached...", "Agent not found..."
            raise CliError(str((event.get("error") or {}).get("message") or "error"))
    return "".join(text)


@dataclass(frozen=True)
class AgentCli:
    """How to run one agent CLI once and read its final answer.

    Attributes:
        label: The CLI's name for people.
        binary: The command to look for.
        args: Flags for one run with no prompt (print mode, tools off, no saved session).
        parse: Reads the answer from stdout (or from a file in the run folder).
        docs: The CLI's docs for this mode.
        stdin: The prompt goes on stdin; else it is the last argument.
        system: The flag for a system prompt; without one, the system text goes before the prompt.
        files: Files to write into the run folder first (name, text), such as a tool policy.
        tools_off: True when the CLI has no tools at all; else the Studio warns before a run.
    """

    label: str
    binary: str
    args: tuple[str, ...]
    parse: Callable[[str, Path], str]
    docs: str
    stdin: bool = False
    system: str | None = None
    files: tuple[tuple[str, str], ...] = ()
    tools_off: bool = False


# OpenCode v2: a primary agent whose permissions deny every tool on every resource.
OPENCODE_AGENT = {
    "mode": "primary",
    "description": "Vinci text step: every tool denied",
    "permissions": [{"action": "*", "resource": "*", "effect": "deny"}],
}


AGENT_CLIS = {
    "claude_code": AgentCli(
        "Claude Code",
        "claude",
        ("-p", "--output-format", "json", "--tools", "", "--no-session-persistence")
        + ("--strict-mcp-config", "--disable-slash-commands"),
        _result,
        "https://code.claude.com/docs/en/headless",
        stdin=True,
        system="--system-prompt",
        tools_off=True,
    ),
    "codex": AgentCli(
        "Codex",
        "codex",
        ("exec", "--sandbox", "read-only", "--ephemeral", "--skip-git-repo-check")
        + ("-o", "answer.txt", "-"),
        _answer_file,
        "https://developers.openai.com/codex/noninteractive",
        stdin=True,
    ),
    "antigravity": AgentCli(
        "Antigravity",
        "agy",
        ("--output-format", "json", "--print-timeout", f"{TIMEOUT - 20:.0f}s", "-p"),
        _response,
        "https://antigravity.google/docs/cli/headless",
    ),
    "cursor_agent": AgentCli(
        "Cursor Agent",
        "cursor-agent",
        # Auto is the model every Cursor plan has (Free has no other default).
        ("-p", "--output-format", "json", "--mode", "ask", "--trust", "--model", "auto"),
        _result,
        "https://cursor.com/docs/cli/overview",
    ),
    "opencode": AgentCli(
        "OpenCode",
        "opencode",
        ("run", "--agent", "vinci-text", "--format", "json"),
        _events,
        "https://opencode.ai/docs/cli/",
        files=(("opencode.json", json.dumps({"agents": {"vinci-text": OPENCODE_AGENT}})),),
    ),
}


def _dirs() -> str:
    """``PATH`` and the usual install folders (``INSTALL_DIRS``)."""
    extra = [os.path.expanduser(d) for d in INSTALL_DIRS]
    return os.pathsep.join([os.environ.get("PATH", ""), *extra])


def find_cli(name: str) -> str | None:
    """The path of an installed agent CLI, or None.

    The search uses ``VINCI_AGENT_CLI_PATH`` when it is set (tests point it at fake CLIs), else
    ``PATH`` and the usual install folders.
    """
    dirs = os.environ.get("VINCI_AGENT_CLI_PATH")
    return shutil.which(AGENT_CLIS[name].binary, path=_dirs() if dirs is None else dirs)


def cli_spec(name: str) -> ModelSpec:
    """The one model of an agent CLI: ``t2t``, priced by the person's plan (currency ``PLAN``)."""
    return ModelSpec(
        id=f"{name}:cli",
        display_name=AGENT_CLIS[name].label,
        provider=name,
        capabilities=[Capability.T2T],
        pricing=Pricing(unit="plan", amount=0, currency="PLAN", snapshot_at=SNAPSHOT),
        quality_tier="quality",
    )


def _tail(text: str) -> str:
    """The last line the CLI printed, cut to 300 characters."""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return lines[-1][:300] if lines else ""


def run_cli(name: str, prompt: str, system: str = "", *, timeout: float = TIMEOUT) -> str:
    """Run an agent CLI once in an empty folder and return its final answer.

    Raises:
        FileNotFoundError: The CLI is not installed.
        TimeoutError: The CLI did not answer in ``timeout`` seconds.
        RuntimeError: The CLI failed or gave no answer (with the CLI's own words).
    """
    cli, path = AGENT_CLIS[name], find_cli(name)
    if path is None:
        raise FileNotFoundError(f"{cli.label} is not installed: no {cli.binary} on PATH")
    text = prompt if cli.system or not system else f"{system}\n\n{prompt}"
    args = [path, *cli.args, *((cli.system, system) if cli.system and system else ())]
    args += [] if cli.stdin else [text]
    command = shlex.join([path, *cli.args])
    used = ", with a system prompt" if cli.system and system else ""
    log.info("agent cli %s: %s (%d characters%s)", name, command, len(text), used)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="vinci-cli-") as folder:
        for file_name, body in cli.files:  # for example OpenCode's tool policy
            (Path(folder) / file_name).write_text(body, encoding="utf-8")
        # The CLI's own folder and the install folders go on its PATH: some CLIs start Node.
        env = {**os.environ, "PATH": os.pathsep.join([os.path.dirname(path), _dirs()])}
        try:
            done = subprocess.run(
                args,
                input=text if cli.stdin else None,
                stdin=None if cli.stdin else subprocess.DEVNULL,  # no CLI waits on our stdin
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=folder,
                env=env,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError(f"{cli.label} did not answer in {timeout:.0f} s") from exc
        error = _tail(done.stderr) or (f"exit {done.returncode}" if done.returncode else "")
        try:
            answer = cli.parse(done.stdout, Path(folder)).strip()
        except CliError as exc:  # the CLI's own words win: "Not logged in", a model error
            answer, error = "", str(exc)
        except (ValueError, OSError):  # not JSON, or no answer file
            answer = ""
    seconds = time.monotonic() - started
    if done.returncode or not answer:
        log.warning("agent cli %s failed in %.1fs: %s", name, seconds, error or "no answer")
        raise RuntimeError(f"{cli.label} failed: {error or 'it gave no answer'}")
    log.info("agent cli %s: %d characters back in %.1fs", name, len(answer), seconds)
    return answer


class AgentCliProvider(Provider):
    """One installed agent CLI as a ``t2t`` provider. ``submit`` runs the CLI and waits for it."""

    durable_job_reconciliation = False

    def __init__(self, name: str, cas: CasStore) -> None:
        self.name, self.spec, self._cas = name, cli_spec(name), cas
        cli = AGENT_CLIS[name]
        self.manifest = ProviderManifest(id=name, display_name=cli.label, docs_url=cli.docs)
        self._estimated: set[str] = set()
        self._jobs: dict[str, JobStatus] = {}

    def catalog(self) -> list[ModelSpec]:
        return [self.spec]

    def capabilities(self) -> set[Capability]:
        return {Capability.T2T}

    def estimate(self, req: JobRequest) -> Estimate:
        self._estimated.add(req.idempotency_key or idempotency_key(self.spec.id, req.inputs))
        return estimate_from_spec(self.spec)

    def submit(self, req: JobRequest) -> ProviderJobRef:
        key = req.idempotency_key or idempotency_key(self.spec.id, req.inputs)
        if key not in self._estimated:
            raise RuntimeError("estimate() must be called before submit()")
        prompt, system = (str(req.inputs.get(k) or "") for k in ("prompt", "system"))
        answer = run_cli(self.name, prompt, system)
        ref = uuid.uuid4().hex
        digest = self._cas.put(answer.encode("utf-8"))
        self._jobs[ref] = JobStatus(state=JobState.COMPLETED, outputs=[digest], progress=1.0)
        return ProviderJobRef(provider=self.name, ref=ref)

    def status(self, ref: ProviderJobRef) -> JobStatus:
        return self._jobs.get(ref.ref) or JobStatus(
            state=JobState.FAILED, error=VinciError(code=ErrorCode.UNKNOWN, message="unknown job")
        )

    def cancel(self, ref: ProviderJobRef) -> None:
        return None  # the CLI ran inside submit: nothing is left to stop

    def normalize_error(self, exc: BaseException) -> VinciError:
        if isinstance(exc, PermissionError):
            return VinciError(code=ErrorCode.AUTH, message=str(exc) or "auth failed")
        if isinstance(exc, TimeoutError):
            return VinciError(code=ErrorCode.TIMEOUT, message=str(exc) or "timeout", retryable=True)
        return VinciError(code=ErrorCode.UNKNOWN, message=str(exc) or type(exc).__name__)
