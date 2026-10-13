"""Portable ledger snapshots for mutations that must survive fresh-home replay."""

from __future__ import annotations

import io
import json
import shutil
import tarfile
from typing import Any

from vinci_skills.loader import skill_dirname
from vinci_storage.durable_journal import JournalError

PORTABLE_REQUIRED_KINDS = frozenset(
    {"skill_install", "comfy_import", "gsheet_sync", "catalog_refresh"}
)


def attach_portable_snapshot(
    kind: str,
    engine: Any,
    payload: dict[str, Any],
    response: dict[str, Any],
) -> dict[str, Any]:
    if kind == "skill_install":
        return _attach_skill(engine, payload, response)
    if kind == "comfy_import":
        return _attach_comfy(engine, payload, response)
    if kind == "gsheet_sync":
        return _attach_gsheet(engine, response)
    if kind == "catalog_refresh":
        return _attach_catalog(engine, response)
    return response


def _attach_skill(engine: Any, payload: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    skill_id = str(response.get("id") or "")
    if not skill_id:
        raise JournalError("skill_install missing skill id in response")
    dirname = skill_dirname(skill_id)
    dest = engine.config.home / "skills" / dirname
    if not dest.is_dir():
        raise JournalError(f"skill_install destination missing after install: {dest}")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        tar.add(dest, arcname=dirname)
    digest = engine.cas.put(buf.getvalue())
    out = dict(response)
    out["ledger_portable"] = {
        "kind": "skill_install",
        "skill_id": skill_id,
        "dirname": dirname,
        "cas_digest": digest,
    }
    return out


def _attach_comfy(engine: Any, payload: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    out = dict(response)
    if out.get("id") and out.get("state"):
        state = str(out.get("state") or "")
        if state != "completed":
            raise JournalError(
                "comfy_import with run must reach completed state before journal ack"
            )
        from vinci_daemon.ledger_mcp import _run_tool_bundle

        out["ledger_portable"] = {
            "kind": "comfy_run",
            "run_replay": _run_tool_bundle(engine, out),
        }
        return out
    workflow = out.get("workflow")
    graph = payload.get("graph")
    if workflow is None or graph is None:
        raise JournalError("comfy_import missing workflow/graph for portable replay")
    blob = json.dumps({"workflow": workflow, "graph": graph}, sort_keys=True).encode("utf-8")
    digest = engine.cas.put(blob)
    out["ledger_portable"] = {
        "kind": "comfy_import",
        "cas_digest": digest,
    }
    return out


def _attach_gsheet(engine: Any, response: dict[str, Any]) -> dict[str, Any]:
    from vinci_daemon.ledger_batch import capture_adapt_batch_bundle

    out = dict(response)
    batch_id = out.get("batch_id")
    portable: dict[str, Any] = {"kind": "gsheet_sync", "sync": out}
    if batch_id:
        portable["adapt_batch"] = capture_adapt_batch_bundle(engine, str(batch_id))
    out["ledger_portable"] = portable
    return out


def _attach_catalog(engine: Any, response: dict[str, Any]) -> dict[str, Any]:
    lock = engine.config.catalog_lock_path
    text = lock.read_text(encoding="utf-8") if lock.is_file() else ""
    out = dict(response)
    out["ledger_portable"] = {
        "kind": "catalog_refresh",
        "catalog_lock_text": text,
    }
    return out


def replay_comfy(engine: Any, response: dict[str, Any]) -> None:
    if response.get("id") and response.get("state"):
        portable = response.get("ledger_portable") or {}
        replay = portable.get("run_replay") or {}
        if portable.get("kind") != "comfy_run" or not replay:
            raise RuntimeError("comfy_import run missing portable run_replay bundle")
        from vinci_daemon.ledger_replay import _materialize_run, _materialize_run_output

        run_body = replay.get("run") or response
        _materialize_run(engine, run_body)
        _materialize_run_output(
            engine,
            {**replay, "run_id": run_body.get("id")},
            replay.get("outputs") or [],
        )
        return
    replay_portable(engine, "comfy_import", response)


def replay_portable(engine: Any, kind: str, response: dict[str, Any]) -> None:
    portable = response.get("ledger_portable")
    if portable is None:
        raise RuntimeError(f"{kind} missing ledger_portable snapshot (fail closed)")
    pk = portable.get("kind") or kind
    if pk == "skill_install":
        _replay_skill(engine, portable)
    elif pk == "comfy_import":
        _replay_comfy(engine, portable)
    elif pk == "gsheet_sync":
        _replay_gsheet(engine, portable, response)
    elif pk == "catalog_refresh":
        _replay_catalog(engine, portable)
    else:
        raise RuntimeError(f"unknown ledger_portable kind {pk}")


def _replay_skill(engine: Any, portable: dict[str, Any]) -> None:
    digest = str(portable.get("cas_digest") or "")
    dirname = str(portable.get("dirname") or "")
    if not digest or not dirname:
        raise RuntimeError("skill_install portable incomplete")
    if not engine.cas.exists(digest):
        raise RuntimeError(f"skill_install cas missing {digest}")
    dest_root = engine.config.home / "skills"
    dest_root.mkdir(parents=True, exist_ok=True)
    dest = dest_root / dirname
    if dest.exists():
        shutil.rmtree(dest)
    raw = engine.cas.get(digest)
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
        tar.extractall(path=dest_root)
    if dest_root not in engine.skills.roots:
        engine.skills.roots.append(dest_root)


def _replay_comfy(engine: Any, portable: dict[str, Any]) -> None:
    digest = str(portable.get("cas_digest") or "")
    if not digest or not engine.cas.exists(digest):
        raise RuntimeError("comfy_import portable cas missing")
    payload = json.loads(engine.cas.get(digest).decode("utf-8"))
    workflows_dir = engine.config.home / "workflows" / "comfy"
    workflows_dir.mkdir(parents=True, exist_ok=True)
    name = f"ledger-{digest[:12]}.json"
    path = workflows_dir / name
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _replay_gsheet(engine: Any, portable: dict[str, Any], response: dict[str, Any]) -> None:
    from vinci_daemon.ledger_batch import restore_adapt_batch_bundle

    batch_bundle = portable.get("adapt_batch")
    if isinstance(batch_bundle, dict) and batch_bundle.get("batch_id"):
        restore_adapt_batch_bundle(engine, batch_bundle)
    state_path = engine.config.home / "gsheet-sync-state.json"
    state_path.write_text(json.dumps(response, indent=2), encoding="utf-8")


def _replay_catalog(engine: Any, portable: dict[str, Any]) -> None:
    text = portable.get("catalog_lock_text")
    if text is None:
        raise RuntimeError("catalog_refresh portable missing lockfile text")
    lock = engine.config.catalog_lock_path
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(str(text), encoding="utf-8")
