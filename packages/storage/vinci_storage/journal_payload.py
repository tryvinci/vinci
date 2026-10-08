"""Canonical payload fingerprints for durable operation idempotency."""

from __future__ import annotations

import hashlib
import json
from typing import Any

DO_JOURNAL_PATH_SUFFIX = "/__vinci/journal"


def normalize_do_journal_base(base: str) -> str:
    """Worker public origin or full journal API prefix → DoJournalClient base URL."""
    raw = base.strip().rstrip("/")
    if not raw:
        return ""
    if raw.endswith(DO_JOURNAL_PATH_SUFFIX):
        return raw
    return f"{raw}{DO_JOURNAL_PATH_SUFFIX}"


def payload_digest(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


_PROVIDER_INFLIGHT_INTENT_KEYS = (
    "run_id",
    "node_id",
    "job_id",
    "model_id",
    "provider",
    "idempotency_key",
)


def provider_submit_intent_fields_match(
    existing_payload: dict[str, Any],
    commit_payload: dict[str, Any],
    *,
    existing_kind: str,
    existing_path: str,
    commit_kind: str,
    commit_path: str,
) -> bool:
    """Intent identity for submit_intent → ref upgrade (only provider_job_ref may change)."""
    if str(existing_kind) != str(commit_kind) or str(existing_path) != str(commit_path):
        return False
    for key in _PROVIDER_INFLIGHT_INTENT_KEYS:
        if str(existing_payload.get(key) or "") != str(commit_payload.get(key) or ""):
            return False
    return True


def allow_provider_submit_ref_upgrade(
    existing_status: str,
    existing_payload: dict[str, Any],
    commit_payload: dict[str, Any],
    *,
    existing_kind: str,
    existing_path: str,
    commit_kind: str,
    commit_path: str,
) -> bool:
    if str(existing_status) != "pending":
        return False
    if not existing_payload.get("submit_intent"):
        return False
    if str(existing_payload.get("provider_job_ref") or ""):
        return False
    if not str(commit_payload.get("provider_job_ref") or ""):
        return False
    return provider_submit_intent_fields_match(
        existing_payload,
        commit_payload,
        existing_kind=existing_kind,
        existing_path=existing_path,
        commit_kind=commit_kind,
        commit_path=commit_path,
    )


def mcp_ledger_payload(message: dict[str, Any]) -> dict[str, Any]:
    """Full MCP RPC body for ledger (includes tool params, not method/id only)."""
    method = message.get("method")
    params = message.get("params")
    if not isinstance(params, dict):
        params = {}
    out: dict[str, Any] = {"method": method, "id": message.get("id")}
    if method == "tools/call":
        out["tool"] = params.get("name")
        out["arguments"] = params.get("arguments") or {}
    else:
        out["params"] = params
    return out


def mcp_operation_id_suffix(message: dict[str, Any]) -> str:
    payload = mcp_ledger_payload(message)
    method = str(payload.get("method") or "rpc")
    if method == "tools/call":
        tool = str(payload.get("tool") or "unknown")
        return f"mcp:tools/call:{tool}"
    return f"mcp:{method}"


def commit_blob_keys(kind: str, blob_keys: list[str], response: dict[str, Any]) -> list[str]:
    """Expand durable blob key list from handler response (outputs, adapt digests, etc.)."""
    keys: list[str] = [str(k) for k in blob_keys if k]
    if kind == "adapt_run":
        keys.extend(str(d) for d in (response.get("digests") or []) if d)
    elif kind == "adapt_batch":
        for item in response.get("items") or []:
            if isinstance(item, dict):
                aid = item.get("asset_id") or item.get("output_asset_id")
                if aid:
                    keys.append(str(aid))
    elif kind in {"run_accept", "run_output"}:
        keys.extend(str(d) for d in (response.get("outputs") or []) if d)
    elif kind == "asset_upload":
        aid = response.get("id")
        if aid:
            keys.append(str(aid))
    elif kind == "mcp_rpc":
        for asset in response.get("assets") or []:
            if isinstance(asset, dict) and asset.get("id"):
                keys.append(str(asset["id"]))
        for digest in response.get("output_digests") or []:
            keys.append(str(digest))
    seen: set[str] = set()
    ordered: list[str] = []
    for key in keys:
        if key not in seen:
            seen.add(key)
            ordered.append(key)
    return ordered
