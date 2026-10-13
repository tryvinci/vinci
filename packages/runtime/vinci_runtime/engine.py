from __future__ import annotations

import base64
import difflib
import hashlib
import io
import json
import os
import re
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from collections import defaultdict, deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from vinci_core.catalog import (
    Catalog,
    catalog_to_document,
    load_bundled_catalog,
    merge_catalogs,
    reject_sunset_defaults,
)
from vinci_core.config import VinciConfig, load_config, write_config
from vinci_core.cost import (
    estimate_from_spec,
    idempotency_key,
    now_utc,
    plan_workflow,
    resolve_model,
    should_await_approval,
    with_alternative,
)
from vinci_core.credentials import CredentialResolver
from vinci_core.paths import allow_live_spend
from vinci_core.redact import redact_mapping
from vinci_core.templates import list_templates
from vinci_index.store import AssetIndex
from vinci_media.adapt import (
    AdaptLayout,
    FitMode,
    adapt_image_ai_extend_placeholder,
    adapt_image_fit_pad_crop,
    estimate_adapt_targets,
    image_dimensions,
    presets_document,
    resolve_preset,
    resolve_target,
    safe_area_report,
    validate_output_image,
)
from vinci_media.custom_presets import create_custom_preset, delete_custom_preset
from vinci_media.ops import (
    burn_captions,
    concat,
    cut,
    mock_transcribe,
    probe,
    reframe_9x16,
    render_timeline,
    select_windows,
    split_fixed,
)
from vinci_media.partner_presets import check_export_bytes
from vinci_protocol.constants import PROTOCOL_VERSION
from vinci_protocol.enums import (
    AssetKind,
    AssetSource,
    Capability,
    ErrorCode,
    JobState,
    NodeType,
    RoutePreference,
)
from vinci_protocol.models import (
    Asset,
    Estimate,
    Event,
    Job,
    JobRequest,
    JobStatus,
    JobTimings,
    Provenance,
    ProviderJobRef,
    Receipt,
    VinciError,
    WorkflowNode,
    WorkflowSpec,
)
from vinci_provider_cloudflare import CloudflareProvider
from vinci_provider_elevenlabs import ElevenLabsProvider
from vinci_provider_fal import FalProvider
from vinci_provider_google import GoogleProvider
from vinci_provider_higgsfield import HiggsfieldProvider
from vinci_provider_magnific import MagnificProvider
from vinci_provider_openai import OpenAIProvider
from vinci_provider_sdk.mock import MockProvider
from vinci_provider_wavespeed import WavespeedProvider
from vinci_skills.loader import Skill, SkillLoader, install_skill_dir, interpolate
from vinci_storage.backends import make_cas
from vinci_storage.sqlite_store import SqliteStore

from vinci_runtime.comfy import import_comfy
from vinci_runtime.provider_reconciliation import (
    ProviderInflightUncertain,
    load_ledger_provider_inflight,
    provider_inflight_pending_without_ref,
    supports_durable_reconciliation,
)
from vinci_runtime.writer_effect_trace import record_writer_effect

PROVIDER_DOCS = {
    "mock": "https://github.com/tryvinci/vinci",
    "wavespeed": "https://wavespeed.ai/docs",
    "google": "https://aistudio.google.com/apikey",
    "openai": "https://platform.openai.com/api-keys",
    "fal": "https://docs.fal.ai",
    "elevenlabs": "https://elevenlabs.io/app/settings/api-keys",
    "cloudflare": "https://developers.cloudflare.com/workers-ai/models/flux-1-schnell/",
    "higgsfield": "https://docs.higgsfield.ai",
    "magnific": "https://docs.magnific.com/introduction",
    "mcp": "https://modelcontextprotocol.io",
}
PROVIDER_SECRETS = {
    "mock": "MOCK_API_KEY",
    "wavespeed": "WAVESPEED_API_KEY",
    "google": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
    "fal": "FAL_KEY",
    "elevenlabs": "ELEVENLABS_API_KEY",
    "cloudflare": "CLOUDFLARE_API_TOKEN",
    "higgsfield": "HIGGSFIELD_API_KEY",
    "magnific": "MAGNIFIC_API_KEY",
    "mcp": "MCP_API_KEY",
}
PROVIDER_EXTRA_SECRETS = {
    "higgsfield": ("HIGGSFIELD_API_SECRET",),
}
PROVIDER_LABELS = {
    "mock": "Mock",
    "wavespeed": "Wavespeed",
    "google": "Google",
    "fal": "fal",
    "elevenlabs": "ElevenLabs",
    "cloudflare": "Cloudflare",
    "higgsfield": "Higgsfield",
    "magnific": "Magnific / Freepik",
    "mcp": "Custom MCP",
}
BUNDLED_PROVIDER_IDS = (
    "mock",
    "wavespeed",
    "google",
    "openai",
    "fal",
    "elevenlabs",
    "cloudflare",
    "higgsfield",
    "magnific",
)


def is_mcp_name(name: str) -> bool:
    return name == "mcp" or name.startswith("mcp_")


def mcp_secret_name(name: str) -> str:
    if name == "mcp":
        return "MCP_API_KEY"
    return "MCP_API_KEY_" + name[4:].upper()


def mcp_slug(label: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", (label or "").lower()).strip("_")
    return "mcp_" + (slug or "custom")


def provider_secret_names(name: str) -> list[str]:
    if is_mcp_name(name):
        return [mcp_secret_name(name)]
    names = [PROVIDER_SECRETS[name]]
    names.extend(PROVIDER_EXTRA_SECRETS.get(name, ()))
    return names


def all_secret_names() -> list[str]:
    names: list[str] = []
    for name in PROVIDER_SECRETS:
        names.extend(provider_secret_names(name))
    return names


def _mcp_token(provider_name: str, lookup: Any) -> Any:
    def token_for() -> str | None:
        token = lookup(provider_name)
        return token if isinstance(token, str) and token else None

    return token_for


def _usd_total(rows: list[dict[str, Any]]) -> float:
    total = 0.0
    for row in rows:
        estimate = row["estimate"]
        if str(estimate.currency).upper() == "USD":
            total += float(estimate.amount)
    return total
CAP_KIND = {
    Capability.T2I: (AssetKind.IMAGE, "image/png"),
    Capability.I2I: (AssetKind.IMAGE, "image/png"),
    Capability.EDIT_MULTI: (AssetKind.IMAGE, "image/png"),
    Capability.T2V: (AssetKind.VIDEO, "video/mp4"),
    Capability.I2V: (AssetKind.VIDEO, "video/mp4"),
    Capability.LIPSYNC: (AssetKind.VIDEO, "video/mp4"),
    Capability.UPSCALE: (AssetKind.VIDEO, "video/mp4"),
    Capability.TTS: (AssetKind.AUDIO, "audio/mpeg"),
    Capability.STS: (AssetKind.AUDIO, "audio/mpeg"),
    Capability.VOICE_CLONE: (AssetKind.AUDIO, "audio/mpeg"),
    Capability.TRANSCRIBE: (AssetKind.TEXT, "application/json"),
    Capability.REFRAME: (AssetKind.VIDEO, "video/mp4"),
    Capability.CAPTION: (AssetKind.VIDEO, "video/mp4"),
}


def _topo(spec: WorkflowSpec) -> list[WorkflowNode]:
    by_id = {node.id: node for node in spec.nodes}
    incoming: dict[str, int] = {node.id: 0 for node in spec.nodes}
    adj: dict[str, list[str]] = defaultdict(list)
    for edge in spec.edges:
        adj[edge.src].append(edge.dst)
        incoming[edge.dst] = incoming.get(edge.dst, 0) + 1
        incoming.setdefault(edge.src, 0)
    queue = deque([node.id for node in spec.nodes if incoming[node.id] == 0])
    ordered: list[WorkflowNode] = []
    while queue:
        node_id = queue.popleft()
        ordered.append(by_id[node_id])
        for dest in adj[node_id]:
            incoming[dest] -= 1
            if incoming[dest] == 0:
                queue.append(dest)
    if len(ordered) != len(spec.nodes):
        raise ValueError("workflow has a cycle")
    return ordered


def _apply_model_id(spec: WorkflowSpec, model_id: str | None) -> WorkflowSpec:
    if not model_id:
        return spec
    return spec.model_copy(
        update={
            "nodes": [
                node.model_copy(update={"model_id": model_id})
                if node.type.value == "generate" and not node.model_id
                else node
                for node in spec.nodes
            ]
        }
    )


def _sniff_mime(blob: bytes, fallback: str) -> str:
    if blob.startswith(b"\x89PNG"):
        return "image/png"
    if blob[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if len(blob) >= 8 and blob[4:8] == b"ftyp":
        return "video/mp4"
    if blob.startswith(b"ID3") or (len(blob) >= 2 and blob[0] == 0xFF and blob[1] & 0xE0 == 0xE0):
        return "audio/mpeg"
    if blob[:4] == b"RIFF" and blob[8:12] == b"WAVE":
        return "audio/wav"
    return fallback


def _decode_data_uri(item: str) -> tuple[bytes, str] | None:
    if not item.startswith("data:") or "," not in item:
        return None
    header, payload = item.split(",", 1)
    if ";base64" not in header.lower():
        return None
    mime = header[5:].split(";", 1)[0] or "application/octet-stream"
    try:
        blob = base64.b64decode(payload)
    except Exception:  # noqa: BLE001 — skip malformed provider payloads
        return None
    if not blob:
        return None
    return blob, mime


class Engine:
    def __init__(self, home: Path | None = None, skills_root: Path | None = None) -> None:
        self.config: VinciConfig = load_config(home)
        self.cas = make_cas(self.config.cas_dir)
        self.store = SqliteStore(self.config.sqlite_path)
        self.index = AssetIndex(self.config.home / "index.sqlite")
        self.resolver = CredentialResolver(self.config)
        roots = [SkillLoader().roots[0]]
        if skills_root:
            roots = [skills_root, *roots]
        installed = self.config.home / "skills"
        if installed.is_dir():
            roots.append(installed)
        self.skills = SkillLoader(roots)
        self.providers: dict[str, Any] = {}
        self._rebuild_providers()

    def _loopback_i2i_enabled(self) -> bool:
        return bool(os.environ.get("VINCI_TEST_LOOPBACK_I2I_URL", "").strip())

    def _rebuild_providers(self) -> None:
        cas = self.cas
        resolver = self.resolver
        from vinci_provider_sdk.loopback_i2i import loopback_i2i_from_env

        loopback_openai = loopback_i2i_from_env(cas=cas)
        openai_provider = (
            loopback_openai
            if loopback_openai is not None
            else OpenAIProvider(
                api_key=resolver.resolve("OPENAI_API_KEY"),
                cas=cas,
            )
        )
        self.providers = {
            "mock": MockProvider(cas, api_key=resolver.resolve("MOCK_API_KEY")),
            "wavespeed": WavespeedProvider(api_key=resolver.resolve("WAVESPEED_API_KEY")),
            "google": GoogleProvider(api_key=resolver.resolve("GEMINI_API_KEY")),
            "openai": openai_provider,
            "fal": FalProvider(api_key=resolver.resolve("FAL_KEY")),
            "elevenlabs": ElevenLabsProvider(api_key=resolver.resolve("ELEVENLABS_API_KEY")),
            "cloudflare": CloudflareProvider(
                api_key=resolver.resolve("CLOUDFLARE_API_TOKEN"),
                cas=cas,
                account_id=self._cloudflare_account_id(),
            ),
            "higgsfield": HiggsfieldProvider(
                api_key=resolver.resolve("HIGGSFIELD_API_KEY"),
                api_secret=resolver.resolve("HIGGSFIELD_API_SECRET"),
            ),
            "magnific": MagnificProvider(api_key=resolver.resolve("MAGNIFIC_API_KEY")),
        }
        from vinci_mcp.adapter import HttpMcpTransport, McpProvider

        for name, cfg in self.config.providers.items():
            if not is_mcp_name(name) or not isinstance(cfg, dict):
                continue
            url = cfg.get("url")
            if not isinstance(url, str) or not url:
                continue
            from vinci_mcp.oauth import access_token

            def bearer(provider_name: str = name) -> str | None:
                token = access_token(resolver, provider_name)
                if token:
                    return token
                return resolver.resolve(mcp_secret_name(provider_name)) or resolver.resolve(
                    "MCP_API_KEY"
                )

            self.providers[name] = McpProvider(
                HttpMcpTransport(url, token_provider=_mcp_token(name, bearer)),
                api_key=bearer(name),
                cas=cas,
                provider_id=name,
            )

    def _mcp_catalog(self, name: str = "mcp") -> Catalog | None:
        provider = self.providers.get(name)
        if provider is None:
            return None
        try:
            models = provider.catalog()
        except Exception:  # noqa: BLE001
            return None
        stamped = [spec.model_copy(update={"provider": name}) for spec in models]
        return Catalog(models=stamped, snapshot_id=name, source=name)

    def _mcp_catalogs(self) -> list[Catalog]:
        rows: list[Catalog] = []
        for name in self.providers:
            if not is_mcp_name(name):
                continue
            extra = self._mcp_catalog(name)
            if extra:
                rows.append(extra)
        return rows

    def enabled_provider_ids(self) -> list[str]:
        extra = [
            name
            for name, body in self.config.providers.items()
            if isinstance(body, dict) and body.get("enabled")
        ]
        if not self.config.demo:
            return extra
        names = ["mock"]
        for name in extra:
            if name not in names:
                names.append(name)
        return names

    def _cloudflare_account_id(self) -> str | None:
        cfg = self.config.providers.get("cloudflare") or {}
        if isinstance(cfg, dict) and cfg.get("account_id"):
            return str(cfg["account_id"])
        value = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
        return value or None

    def provider_available(self, name: str) -> bool:
        if name == "mock":
            return name in self.enabled_provider_ids() or self.config.demo
        if name == "cloudflare":
            return (
                bool(self.resolver.resolve("CLOUDFLARE_API_TOKEN"))
                and bool(self._cloudflare_account_id())
                and name in self.enabled_provider_ids()
            )
        if is_mcp_name(name):
            cfg = self.config.providers.get(name) or {}
            url = cfg.get("url") if isinstance(cfg, dict) else None
            return bool(url) and name in self.enabled_provider_ids()
        secret = PROVIDER_SECRETS.get(name)
        extra = PROVIDER_EXTRA_SECRETS.get(name, ())
        if not secret:
            return False
        return (
            bool(self.resolver.resolve(secret))
            and all(self.resolver.resolve(item) for item in extra)
            and name in self.enabled_provider_ids()
        )

    def routing_providers(self) -> set[str]:
        return {name for name in self.enabled_provider_ids() if self.provider_available(name)}

    def catalog(self) -> Catalog:
        names = self.enabled_provider_ids()
        if not names:
            names = ["mock"] if self.config.demo else []
        catalogs: list[Catalog] = []
        for name in names:
            if is_mcp_name(name):
                extra = self._mcp_catalog(name)
                if extra:
                    catalogs.append(extra)
                continue
            catalogs.append(load_bundled_catalog(name))
        return merge_catalogs(catalogs)

    def full_catalog(self) -> Catalog:
        catalogs = [load_bundled_catalog(name) for name in BUNDLED_PROVIDER_IDS]
        catalogs.extend(self._mcp_catalogs())
        return merge_catalogs(catalogs)

    def _secret_values(self) -> list[str]:
        from vinci_mcp.oauth import oauth_secret_name, secret_material

        names = list(all_secret_names())
        for name in self.config.providers:
            if not is_mcp_name(name):
                continue
            names.append(mcp_secret_name(name))
            try:
                names.append(oauth_secret_name(name))
            except ValueError:
                continue
        values = self.resolver.known_values(names)
        extra: list[str] = []
        for value in values:
            extra.extend(secret_material(value))
        return values + extra

    def _emit(
        self,
        type_: str,
        *,
        run_id: str | None = None,
        job_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        secrets = self._secret_values()
        event = Event(
            type=type_,
            run_id=run_id,
            job_id=job_id,
            created_at=now_utc(),
            payload=redact_mapping(payload or {}, extra_values=secrets),
        )
        self.store.append_event(event, secret_values=secrets)

    def init_home(self, *, demo: bool = False) -> dict[str, Any]:
        self.config.demo = demo
        if demo:
            self.config.providers["mock"] = {"enabled": True}
        write_config(self.config)
        self.config = load_config(self.config.home)
        self._rebuild_providers()
        self.catalog_refresh()
        return {"home": str(self.config.home), "demo": demo, "protocol_version": PROTOCOL_VERSION}

    def _provider_row(self, name: str) -> dict[str, Any]:
        raw = self.config.providers.get(name)
        cfg = raw if isinstance(raw, dict) else {}
        from vinci_mcp.connectors import connector_for
        from vinci_mcp.oauth import auth_state

        secrets = provider_secret_names(name)
        mcp = is_mcp_name(name)
        preset = connector_for(name)
        stored_url = cfg.get("url") if mcp else None
        configured = name == "mock" or bool(
            (mcp and stored_url)
            or (secrets and all(self.resolver.resolve(secret) for secret in secrets))
        )
        state = auth_state(self.resolver, name) if mcp else "key"
        if mcp and state == "disconnected" and configured and not preset:
            has_secret = any(self.resolver.resolve(secret) for secret in secrets)
            state = "connected" if has_secret else state
        return {
            "enabled": name in self.enabled_provider_ids(),
            "available": self.provider_available(name),
            "configured": configured,
            "secret_name": secrets[0] if secrets else "",
            "extra_secret_names": list(PROVIDER_EXTRA_SECRETS.get(name, ())),
            "display_name": str(
                cfg.get("label")
                or (preset.label if preset else None)
                or PROVIDER_LABELS.get(name)
                or name
            ),
            "kind": "mcp" if mcp else "http",
            "docs": (
                preset.docs
                if preset
                else PROVIDER_DOCS.get(name) or ("https://modelcontextprotocol.io" if mcp else "")
            ),
            "url": stored_url or (preset.url if preset else None),
            "authorize_url": cfg.get("authorize_url"),
            "auth": "oauth" if preset else ("oauth_or_key" if mcp else "key"),
            "auth_state": state,
        }

    def doctor(self) -> dict[str, Any]:
        home = self.config.home
        ffmpeg = shutil.which("ffmpeg")
        disk = shutil.disk_usage(home)
        from vinci_mcp.connectors import CONNECTORS

        names = list(PROVIDER_DOCS)
        for name in list(self.config.providers) + list(CONNECTORS):
            if name not in names:
                names.append(name)
        checks = {
            "home": home.is_dir(),
            "cas": self.config.cas_dir.is_dir(),
            "sqlite": self.config.sqlite_path.parent.is_dir(),
            "ffmpeg": ffmpeg is not None,
            "disk_free_bytes": disk.free,
            "demo": self.config.demo,
            "live_spend": allow_live_spend(),
            "providers": {
                name: self._provider_row(name)
                for name in names
                if name in PROVIDER_SECRETS or is_mcp_name(name)
            },
        }
        checks["preference"] = self.config.preference
        checks["budget"] = {
            "monthly_cap_usd": self.config.budget.monthly_cap_usd,
            "require_approval_over": self.config.budget.require_approval_over,
        }
        checks["ok"] = bool(
            checks["home"] and checks["cas"] and checks["sqlite"] and checks["ffmpeg"]
        )
        return checks

    def recover_interrupted_jobs(self) -> int:
        """Mark in-flight jobs/runs failed after unclean restart when journaling is off.

        Not used when a durable journal is enabled; see `reconcile_pending_outbox` instead.
        """
        active_jobs = {
            JobState.RUNNING,
            JobState.QUEUED,
            JobState.CREATED,
        }
        recovered = 0
        for job in self.store.list_jobs():
            if job.state not in active_jobs:
                continue
            job.state = JobState.FAILED
            job.error = VinciError(code=ErrorCode.UNKNOWN, message="recovered after restart")
            self.store.put_job(job)
            recovered += 1
        active_runs = {"running", "queued", "processing"}
        for run in self.store.list_runs():
            state = str(run.get("state") or "")
            if state not in active_runs:
                continue
            run_id = str(run["id"])
            body = dict(run)
            body.pop("id", None)
            body.pop("state", None)
            body["error"] = "interrupted restart"
            self.store.put_run(run_id, body, JobState.FAILED.value)
            recovered += 1
        return recovered

    def templates(self) -> list[dict[str, Any]]:
        return list_templates()

    def models(
        self, *, capability: str | None = None, max_price: float | None = None
    ) -> list[dict[str, Any]]:
        catalog = self.full_catalog()
        rows: list[dict[str, Any]] = []
        for spec in catalog.models:
            reject_sunset_defaults(spec.id)
            if capability and capability not in [c.value for c in spec.capabilities]:
                continue
            if max_price is not None and spec.pricing.amount > max_price:
                continue
            rows.append(
                {
                    **spec.model_dump(mode="json"),
                    "available": self.provider_available(spec.provider),
                    "enabled": spec.provider in self.enabled_provider_ids(),
                }
            )
        return rows

    def catalog_refresh(self) -> dict[str, Any]:
        catalog = self.full_catalog()
        for spec in catalog.models:
            reject_sunset_defaults(spec.id)
        doc = catalog_to_document(catalog)
        lock = self.config.catalog_lock_path
        previous = lock.read_text(encoding="utf-8") if lock.exists() else None
        text = json.dumps(doc, indent=2, sort_keys=True) + "\n"
        lock.write_text(text, encoding="utf-8")
        diff = "".join(
            difflib.unified_diff(
                (previous or "").splitlines(keepends=True),
                text.splitlines(keepends=True),
                fromfile="catalog.lock.json",
                tofile="catalog.lock.json",
            )
        )
        return {
            "path": str(lock),
            "snapshot_id": catalog.snapshot_id,
            "changed": previous != text,
            "diff": diff,
            "models": len(catalog.models),
            "note": "bundled snapshots copied to the lockfile; in-repo JSON is not mutated",
        }

    def add_provider(
        self,
        name: str,
        *,
        from_env: str | None = None,
        secret: str | None = None,
        extra_secret: str | None = None,
        extra_from_env: str | None = None,
        url: str | None = None,
        account_id: str | None = None,
        label: str | None = None,
        authorize_url: str | None = None,
    ) -> dict[str, Any]:
        if name not in PROVIDER_SECRETS and not is_mcp_name(name):
            raise KeyError(name)
        if is_mcp_name(name) and name != "mcp" and not re.fullmatch(r"mcp_[a-z0-9_]+", name):
            raise ValueError("named MCP id must match mcp_<slug>")
        if secret and from_env:
            raise ValueError("use from_env or a pasted secret, not both")
        if extra_secret and extra_from_env:
            raise ValueError("use extra_from_env or a pasted extra secret, not both")
        secret_name = mcp_secret_name(name) if is_mcp_name(name) else PROVIDER_SECRETS[name]
        existing = self.config.providers.get(name) or {}
        body: dict[str, Any] = {"enabled": True}
        if isinstance(existing, dict):
            if existing.get("label"):
                body["label"] = existing["label"]
            if existing.get("authorize_url"):
                body["authorize_url"] = existing["authorize_url"]
            if existing.get("url"):
                body["url"] = existing["url"]
            if existing.get("account_id"):
                body["account_id"] = existing["account_id"]
        if label:
            body["label"] = label
        if authorize_url:
            body["authorize_url"] = authorize_url
        if is_mcp_name(name):
            from vinci_mcp.connectors import connector_for

            preset = connector_for(name)
            resolved_url = url or body.get("url") or (preset.url if preset else None)
            if not resolved_url:
                raise ValueError("mcp provider requires url")
            body["url"] = resolved_url
            if preset and "label" not in body:
                body["label"] = preset.label
        if name == "cloudflare":
            resolved_account = account_id or body.get("account_id") or os.environ.get(
                "CLOUDFLARE_ACCOUNT_ID"
            )
            if resolved_account:
                body["account_id"] = resolved_account
        self.config.providers[name] = body
        if secret:
            kind = self.resolver.put(secret_name, secret)
            self.config.secrets[secret_name] = (
                f"file:keys/{secret_name}" if kind == "file" else "keychain"
            )
            ref = kind
        elif from_env or not is_mcp_name(name):
            env_name = from_env or secret_name
            self.config.secrets[secret_name] = f"env:{env_name}"
            ref = f"env:{env_name}"
        else:
            ref = None
        extra_names = list(PROVIDER_EXTRA_SECRETS.get(name, ()))
        extra_ref = None
        if extra_names:
            extra_name = extra_names[0]
            if extra_secret:
                extra_kind = self.resolver.put(extra_name, extra_secret)
                self.config.secrets[extra_name] = (
                    f"file:keys/{extra_name}" if extra_kind == "file" else "keychain"
                )
                extra_ref = extra_kind
            else:
                extra_env = extra_from_env or extra_name
                self.config.secrets[extra_name] = f"env:{extra_env}"
                extra_ref = f"env:{extra_env}"
        write_config(self.config)
        self.config = load_config(self.config.home)
        self.resolver = CredentialResolver(self.config)
        self._rebuild_providers()
        available = self.provider_available(name)
        row = self._provider_row(name)
        return {
            "id": name,
            "docs_url": row["docs"],
            "secret_name": secret_name,
            "extra_secret_names": list(PROVIDER_EXTRA_SECRETS.get(name, ())),
            "display_name": row["display_name"],
            "kind": row["kind"],
            "ref": ref,
            "extra_ref": extra_ref,
            "available": available,
            "url": body.get("url"),
            "account_id": body.get("account_id"),
            "authorize_url": body.get("authorize_url"),
            "auth": row["auth"],
            "test": "ok" if available or name == "mock" else "missing key",
        }

    def oauth_start(self, name: str, redirect_uri: str) -> dict[str, Any]:
        from vinci_mcp.connectors import connector_for
        from vinci_mcp.oauth import OAuthError, start

        if name not in PROVIDER_SECRETS and not is_mcp_name(name):
            raise KeyError(name)
        if not is_mcp_name(name):
            label = PROVIDER_LABELS.get(name, name)
            return {
                "id": name,
                "mode": "key",
                "authorize_url": None,
                "hint": f"{label} uses a pasted API key, not a browser login.",
            }
        preset = connector_for(name)
        cfg = self.config.providers.get(name) or {}
        if preset and not (isinstance(cfg, dict) and cfg.get("url")):
            self.add_provider(name, url=preset.url, label=preset.label)
            cfg = self.config.providers.get(name) or {}
        authorize = cfg.get("authorize_url") if isinstance(cfg, dict) else None
        server_url = cfg.get("url") if isinstance(cfg, dict) else None
        if isinstance(server_url, str) and server_url:
            try:
                started = start(self.resolver, name, server_url, redirect_uri)
                self._rebuild_providers()
                return started
            except OAuthError:
                if not authorize:
                    raise
        return {
            "id": name,
            "mode": "token" if authorize else "paste",
            "authorize_url": authorize,
            "hint": (
                "Remote MCP OAuth: open the authorize URL, then paste the token."
                if authorize
                else "This MCP uses a pasted bearer. HTTP plugins still use API keys."
            ),
        }

    def oauth_callback(self, *, code: str, state: str, error: str = "") -> dict[str, Any]:
        from vinci_mcp.oauth import finish

        result = finish(self.resolver, code=code, state=state, error=error)
        self._rebuild_providers()
        return result

    def plan_brief(self, brief: str) -> dict[str, Any]:
        query = (brief or "").lower()
        words = [w for w in re.split(r"[^a-z0-9]+", query) if w]
        scored: list[tuple[int, dict[str, Any]]] = []
        for template in list_templates():
            blob = " ".join(
                str(template.get(key) or "")
                for key in ("id", "title", "blurb", "category", "skill")
            ).lower()
            score = sum(1 for word in words if word in blob)
            scored.append((score, template))
        scored.sort(key=lambda row: (-row[0], str(row[1].get("id") or "")))
        hits = [template for score, template in scored if score > 0][:4]
        if not hits:
            hits = [
                template
                for template in list_templates()
                if template.get("id") == "still-image"
            ]
        steps = []
        for template in hits:
            steps.append(
                {
                    "id": template.get("id"),
                    "title": template.get("title"),
                    "skill": template.get("skill"),
                    "blurb": template.get("blurb"),
                    "note": template.get("category"),
                }
            )
        return {"brief": brief, "steps": steps}

    def _collab_dir(self) -> Path:
        path = self.config.home / "collab"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def collab_create(self, name: str | None = None) -> dict[str, Any]:
        sid = uuid.uuid4().hex[:8]
        body = {
            "id": sid,
            "name": name or "Session",
            "snapshot": {},
            "updated_at": now_utc().isoformat(),
        }
        (self._collab_dir() / f"{sid}.json").write_text(json.dumps(body), encoding="utf-8")
        return body

    def collab_list(self) -> list[dict[str, Any]]:
        rows = []
        for path in sorted(self._collab_dir().glob("*.json")):
            try:
                body = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if isinstance(body, dict):
                rows.append(
                    {
                        "id": body.get("id") or path.stem,
                        "name": body.get("name") or path.stem,
                    }
                )
        return rows

    def collab_get(self, sid: str) -> dict[str, Any]:
        path = self._collab_dir() / f"{sid}.json"
        if not path.is_file():
            raise KeyError(sid)
        body = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(body, dict):
            raise KeyError(sid)
        return body

    def collab_put(
        self, sid: str, snapshot: dict[str, Any], name: str | None = None
    ) -> dict[str, Any]:
        try:
            body = self.collab_get(sid)
        except KeyError:
            body = {"id": sid, "name": name or "Session", "snapshot": {}}
        if name:
            body["name"] = name
        body["snapshot"] = snapshot
        body["updated_at"] = now_utc().isoformat()
        (self._collab_dir() / f"{sid}.json").write_text(json.dumps(body), encoding="utf-8")
        return body

    def settings(self) -> dict[str, Any]:
        return {
            "preference": self.config.preference,
            "budget": {
                "monthly_cap_usd": self.config.budget.monthly_cap_usd,
                "require_approval_over": self.config.budget.require_approval_over,
            },
            "demo": self.config.demo,
            "live_spend": allow_live_spend(),
            "gsheet_id": self.config.gsheet_id,
            "gsheet_tab": self.config.gsheet_tab,
            "gsheet_credentials_path": os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", ""),
        }

    def update_settings(
        self,
        *,
        preference: str | None = None,
        monthly_cap_usd: float | None = None,
        require_approval_over: float | None = None,
        gsheet_id: str | None = None,
        gsheet_tab: str | None = None,
    ) -> dict[str, Any]:
        if preference is not None:
            self.config.preference = RoutePreference(preference).value
        if monthly_cap_usd is not None:
            self.config.budget.monthly_cap_usd = monthly_cap_usd
        if require_approval_over is not None:
            self.config.budget.require_approval_over = require_approval_over
        if gsheet_id is not None:
            self.config.gsheet_id = gsheet_id.strip()
        if gsheet_tab is not None:
            self.config.gsheet_tab = gsheet_tab.strip()
        write_config(self.config)
        self.config = load_config(self.config.home)
        return self.settings()

    def remove_provider(self, name: str) -> None:
        if is_mcp_name(name):
            from vinci_mcp.oauth import disconnect

            disconnect(self.resolver, name)
        self.config.providers.pop(name, None)
        write_config(self.config)
        self.config = load_config(self.config.home)
        self._rebuild_providers()

    def disconnect_oauth(self, name: str) -> dict[str, str]:
        if not is_mcp_name(name):
            raise KeyError(name)
        from vinci_mcp.oauth import disconnect

        disconnect(self.resolver, name)
        self._rebuild_providers()
        return {"id": name, "auth_state": "disconnected"}

    def estimate_skill(
        self,
        skill_ref: str,
        inputs: dict[str, Any],
        *,
        max_cost: float | None = None,
        preference: str | None = None,
        model_id: str | None = None,
    ) -> dict[str, Any]:
        skill = self.skills.get(skill_ref)
        spec = skill.workflow.model_copy(
            update={
                "preference": RoutePreference(
                    preference or self.config.preference or skill.workflow.preference.value
                ),
                "max_cost": max_cost if max_cost is not None else skill.workflow.max_cost,
            }
        )
        spec = _apply_model_id(spec, model_id)
        catalog = self.catalog()
        available = self.routing_providers()
        rows = plan_workflow(catalog, spec, available_providers=available or None)
        total = _usd_total(rows)
        reason = should_await_approval(
            total,
            max_cost=spec.max_cost,
            monthly_spent=self.store.month_spend(),
            monthly_cap=self.config.budget.monthly_cap_usd,
            require_over=self.config.budget.require_approval_over,
        )
        print_rows = []
        for row in rows:
            estimate = row["estimate"]
            print_rows.append(
                {
                    "node_id": row["node_id"],
                    "model_id": row["model"].id,
                    "amount": estimate.amount,
                    "currency": estimate.currency,
                    "alternative": estimate.alternative,
                }
            )
        return {
            "skill": skill.ref,
            "total": total,
            "currency": "USD",
            "nodes": print_rows,
            "awaiting_reason": reason,
            "preference": spec.preference.value,
        }

    def _stable_run_id(self, operation_id: str | None) -> str:
        if operation_id:
            return hashlib.sha256(operation_id.encode()).hexdigest()[:24]
        return uuid.uuid4().hex

    def accept_run(
        self,
        skill_ref: str | None,
        inputs: dict[str, Any],
        *,
        max_cost: float | None = None,
        preference: str | None = None,
        workflow: WorkflowSpec | None = None,
        model_id: str | None = None,
        operation_id: str | None = None,
    ) -> dict[str, Any]:
        """Persist run intent only (no provider execution)."""
        run_id = self._stable_run_id(operation_id)
        existing = self.store.get_run(run_id)
        if existing is not None:
            return existing
        secrets = self._secret_values()
        if workflow is not None:
            spec = workflow
            skill_name = workflow.id
            skill_version = workflow.version
            prepared = self._prepare_inputs(inputs)
        else:
            if not skill_ref:
                raise ValueError("skill or workflow is required")
            skill = self.skills.get(skill_ref)
            spec = skill.workflow
            skill_name = skill.id
            skill_version = skill.version
            prepared = self._prepare_inputs(self._apply_input_defaults(skill, inputs))
        safe_inputs = redact_mapping(prepared, extra_values=secrets)
        pref = RoutePreference(preference or self.config.preference or spec.preference.value)
        spec = spec.model_copy(
            update={
                "preference": pref,
                "max_cost": max_cost if max_cost is not None else spec.max_cost,
            }
        )
        spec = _apply_model_id(spec, model_id)
        catalog = self.catalog()
        available = self.routing_providers()
        if not available:
            raise RuntimeError(
                "no available providers; run vinci init --demo or add a provider key"
            )
        rows = plan_workflow(catalog, spec, available_providers=available)
        total = _usd_total(rows)
        plan = {
            "skill": f"{skill_name}@{skill_version}",
            "total": total,
            "currency": "USD",
            "nodes": [
                {
                    "node_id": row["node_id"],
                    "model_id": row["model"].id,
                    "amount": row["estimate"].amount,
                    "currency": row["estimate"].currency,
                    "alternative": row["estimate"].alternative,
                }
                for row in rows
            ],
            "awaiting_reason": should_await_approval(
                total,
                max_cost=spec.max_cost,
                monthly_spent=self.store.month_spend(),
                monthly_cap=self.config.budget.monthly_cap_usd,
                require_over=self.config.budget.require_approval_over,
            ),
            "preference": spec.preference.value,
        }
        body: dict[str, Any] = {
            "skill": f"{skill_name}@{skill_version}",
            "inputs": safe_inputs,
            "max_cost": spec.max_cost,
            "preference": spec.preference.value,
            "estimate": plan,
            "job_ids": [],
            "outputs": [],
            "workflow": spec.model_dump(mode="json"),
        }
        if plan["awaiting_reason"]:
            body["awaiting_reason"] = plan["awaiting_reason"]
            self.store.put_run(run_id, body, JobState.AWAITING_APPROVAL.value)
            self._emit(
                "run.awaiting_approval",
                run_id=run_id,
                payload={"reason": plan["awaiting_reason"], "total": plan["total"]},
            )
            return self.store.get_run(run_id) or body
        self.store.put_run(run_id, body, JobState.QUEUED.value)
        self._emit(
            "run.created", run_id=run_id, payload={"skill": body["skill"], "total": plan["total"]}
        )
        return self.store.get_run(run_id) or body

    def dispatch_run(
        self,
        run_id: str,
        *,
        operation_id: str | None = None,
        receipt_parent_op_id: str | None = None,
    ) -> dict[str, Any]:
        """Execute a queued run after durable intent is committed."""
        run = self.store.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        state = str(run.get("state") or "")
        if state == JobState.RUNNING.value:
            journal = getattr(self, "_journal", None)
            parent = receipt_parent_op_id or operation_id
            if journal is not None and parent:
                receipt_row = journal.get_operation(f"{parent}:output")
                has_receipt = (
                    receipt_row is not None and receipt_row.get("status") == "committed"
                )
                if not has_receipt:
                    return self._execute_run(
                        run_id, receipt_parent_op_id=receipt_parent_op_id or operation_id
                    )
            return run
        if state in {JobState.COMPLETED.value, JobState.FAILED.value}:
            return run
        if state == JobState.AWAITING_APPROVAL.value:
            return run
        if state != JobState.QUEUED.value:
            return run
        return self._execute_run(
            run_id,
            receipt_parent_op_id=receipt_parent_op_id or operation_id,
        )

    def start_run(
        self,
        skill_ref: str | None,
        inputs: dict[str, Any],
        *,
        max_cost: float | None = None,
        preference: str | None = None,
        workflow: WorkflowSpec | None = None,
        model_id: str | None = None,
    ) -> dict[str, Any]:
        run = self.accept_run(
            skill_ref,
            inputs,
            max_cost=max_cost,
            preference=preference,
            workflow=workflow,
            model_id=model_id,
        )
        if str(run.get("state") or "") == JobState.QUEUED.value:
            return self.dispatch_run(str(run["id"]))
        return run

    def approve_run(self, run_id: str) -> dict[str, Any]:
        run = self.store.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        if run["state"] != JobState.AWAITING_APPROVAL.value:
            raise ValueError(f"run {run_id} is {run['state']}")
        self.store.put_run(run_id, run, JobState.QUEUED.value)
        self._emit("run.approved", run_id=run_id, payload={})
        if getattr(self, "_journal", None) is None:
            return self.dispatch_run(run_id)
        return self.store.get_run(run_id) or run

    def cancel_run(self, run_id: str) -> dict[str, Any]:
        run = self.store.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        run["cancelled"] = True
        self.store.put_run(run_id, run, JobState.CANCELLED.value)
        self._emit("run.cancelled", run_id=run_id, payload={})
        return self.store.get_run(run_id) or run

    def _bump_test_exec_counter(self) -> None:
        record_writer_effect("completion")
        path = os.environ.get("VINCI_TEST_EXEC_COUNTER_PATH")
        if not path:
            return
        counter = Path(path)
        counter.parent.mkdir(parents=True, exist_ok=True)
        n = 0
        if counter.is_file():
            n = int(counter.read_text(encoding="utf-8").strip() or "0")
        counter.write_text(str(n + 1), encoding="utf-8")

    def _bump_test_counter(self, env_key: str) -> None:
        path = os.environ.get(env_key)
        if not path:
            return
        counter = Path(path)
        counter.parent.mkdir(parents=True, exist_ok=True)
        n = int(counter.read_text(encoding="utf-8").strip() or "0") if counter.is_file() else 0
        counter.write_text(str(n + 1), encoding="utf-8")

    def _put_run_state(self, run_id: str, run: dict[str, Any], state: str) -> None:
        self._require_journal_writer_live()
        record_writer_effect(f"run_state_{state}")
        self.store.put_run(run_id, run, state)

    def _require_journal_writer_live(self) -> None:
        journal = getattr(self, "_journal", None)
        if journal is None:
            return
        if getattr(self, "_journal_writer_fenced", False):
            raise RuntimeError("journal writer fenced")
        token = getattr(self, "_journal_token", None)
        if token is None:
            raise RuntimeError("journal writer token missing")
        renew = getattr(self, "_renew_journal_writer", None)
        try:
            if callable(renew):
                renew()
            else:
                self._journal_token = journal.renew_writer(token)
        except Exception:
            self._journal_writer_fenced = True
            self._journal_token = None
            raise

    def _cas_put(self, data: bytes) -> str:
        self._require_journal_writer_live()
        record_writer_effect("cas")
        self._bump_test_counter("VINCI_TEST_CAS_PUT_COUNTER_PATH")
        return self.cas.put(data)

    def _execute_run(
        self, run_id: str, *, receipt_parent_op_id: str | None = None
    ) -> dict[str, Any]:
        run = self.store.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        spec = WorkflowSpec.model_validate(run["workflow"])
        inputs = run.get("inputs") or {}
        try:
            self._require_journal_writer_live()
        except Exception:
            self._journal_writer_fenced = True
            self._journal_token = None
            raise
        if os.environ.get("VINCI_TEST_SLEEP_DURING_EXECUTE_MS"):
            time.sleep(int(os.environ["VINCI_TEST_SLEEP_DURING_EXECUTE_MS"]) / 1000.0)
            self._require_journal_writer_live()
        record_writer_effect("execute_entry")
        self._put_run_state(run_id, run, JobState.RUNNING.value)
        self._emit("run.started", run_id=run_id, payload={})
        context: dict[str, Any] = {"inputs": inputs, "nodes": {}}
        job_ids: list[str] = []
        final_outputs: list[str] = []
        node_map: dict[str, Any] = {}
        try:
            for node_index, node in enumerate(_topo(spec)):
                self._require_journal_writer_live()
                record_writer_effect("node")
                params = interpolate(node.params, context)
                if not isinstance(params, dict):
                    params = {"value": params}
                if node.type.value == "generate":
                    job = self._run_generate(
                        run_id, node, params, spec, receipt_parent_op_id=receipt_parent_op_id
                    )
                elif node.type.value == "media":
                    job = self._run_media(run_id, node, params)
                elif node.type.value == "indexquery":
                    job = self._run_indexquery(run_id, node, params)
                else:
                    continue
                job_ids.append(job.id)
                output = job.outputs[0] if job.outputs else None
                data = self._load_jsonish(output) if output else None
                context["nodes"][node.id] = {
                    "output": output,
                    "outputs": job.outputs,
                    "data": data,
                }
                node_map[node.id] = {
                    "output": output,
                    "outputs": job.outputs,
                    "job_id": job.id,
                    "capability": node.capability.value if node.capability else None,
                }
                final_outputs = job.outputs
                sleep_after = os.environ.get("VINCI_TEST_SLEEP_AFTER_NODE_MS")
                if sleep_after and str(node_index) == os.environ.get(
                    "VINCI_TEST_SLEEP_AFTER_NODE_INDEX", "0"
                ):
                    time.sleep(int(sleep_after) / 1000.0)
                    self._require_journal_writer_live()
            run["job_ids"] = job_ids
            run["outputs"] = final_outputs
            run["nodes"] = node_map
            run["asset_uris"] = [f"vinci://assets/{digest}" for digest in final_outputs]
            run["job_uris"] = [f"vinci://jobs/{jid}" for jid in job_ids]
            run["receipt_uris"] = [f"vinci://receipts/{jid}" for jid in job_ids]
            hook = getattr(self, "_commit_run_receipt_hook", None)
            self._bump_test_exec_counter()
            if hook is not None and receipt_parent_op_id:
                hook(run_id, run, receipt_parent_op_id)
            self._put_run_state(run_id, run, JobState.COMPLETED.value)
            self._emit("run.completed", run_id=run_id, payload={"outputs": final_outputs})
        except Exception as exc:  # noqa: BLE001 — normalize into run failure
            run["job_ids"] = job_ids
            run["nodes"] = node_map
            run["error"] = {"code": "unknown", "message": str(exc) or type(exc).__name__}
            try:
                self._put_run_state(run_id, run, JobState.FAILED.value)
                self._emit("run.failed", run_id=run_id, payload=run["error"])
            except Exception:
                pass
            raise
        return self.store.get_run(run_id) or run

    def _prepare_provider_submit_intent(
        self,
        *,
        parent_op_id: str | None,
        run_id: str,
        node_id: str,
        job_id: str,
        model_id: str,
        provider_name: str,
        idempotency_key_value: str,
    ) -> None:
        journal = getattr(self, "_journal", None)
        if journal is None or not parent_op_id:
            return
        try:
            from vinci_daemon.durable_provider_inflight import (  # type: ignore[import-not-found]
                prepare_provider_submit_intent,
            )

            prepare_provider_submit_intent(
                journal,
                self,
                parent_op_id=parent_op_id,
                run_id=run_id,
                node_id=node_id,
                job_id=job_id,
                model_id=model_id,
                provider_name=provider_name,
                idempotency_key=idempotency_key_value,
            )
        except ImportError:
            return

    def _commit_provider_inflight_ledger(
        self,
        *,
        parent_op_id: str | None,
        run_id: str,
        node_id: str,
        job_id: str,
        model_id: str,
        provider_name: str,
        provider_job_ref: str,
        idempotency_key_value: str,
    ) -> None:
        journal = getattr(self, "_journal", None)
        if journal is None or not parent_op_id:
            return
        try:
            from vinci_daemon.durable_provider_inflight import commit_provider_inflight

            commit_provider_inflight(
                journal,
                self,
                parent_op_id=parent_op_id,
                run_id=run_id,
                node_id=node_id,
                job_id=job_id,
                model_id=model_id,
                provider_name=provider_name,
                provider_job_ref=provider_job_ref,
                idempotency_key=idempotency_key_value,
            )
        except ImportError:
            return

    def _durable_provider_submit(
        self,
        *,
        parent_op_id: str | None,
        run_id: str,
        node_id: str,
        provider: Any,
        model_id: str,
        provider_name: str,
        req: JobRequest,
        idempotency_key_value: str,
        secrets: list[str],
        estimate: Estimate,
        started: datetime,
    ) -> tuple[ProviderJobRef, str]:
        """Submit or resume provider work with durable provider_inflight ledger child."""
        journal = getattr(self, "_journal", None)
        parent_op = parent_op_id
        ledger_row = load_ledger_provider_inflight(journal, parent_op, node_id)
        pending_intent = provider_inflight_pending_without_ref(journal, parent_op, node_id)
        deny_reconcile = os.environ.get("VINCI_TEST_FORCE_NO_PROVIDER_RECONCILIATION") == "1"
        if ledger_row is not None and (
            deny_reconcile or not supports_durable_reconciliation(provider)
        ):
            raise ProviderInflightUncertain(
                f"ledger has provider ref for {provider_name} but vendor cannot reconcile; "
                "fail closed (no blind resubmit)"
            )
        inflight = self._inflight_job_for_node(run_id, node_id)
        if pending_intent is not None:
            if inflight is not None and inflight.provider_job_ref:
                self._commit_provider_inflight_ledger(
                    parent_op_id=parent_op,
                    run_id=run_id,
                    node_id=node_id,
                    job_id=str(pending_intent.get("job_id") or inflight.id),
                    model_id=str(pending_intent.get("model_id") or model_id),
                    provider_name=str(pending_intent.get("provider") or provider_name),
                    provider_job_ref=inflight.provider_job_ref,
                    idempotency_key_value=str(
                        pending_intent.get("idempotency_key") or idempotency_key_value
                    ),
                )
                ledger_row = load_ledger_provider_inflight(journal, parent_op, node_id)
            else:
                raise ProviderInflightUncertain(
                    "provider submit accepted but durable provider_inflight ref was not "
                    "committed; fail closed (no blind resubmit)"
                )
        if inflight is not None and inflight.provider_job_ref:
            job_id = inflight.id
            ref = ProviderJobRef(provider=provider_name, ref=inflight.provider_job_ref)
            record_writer_effect("submit_resume")
        elif ledger_row is not None:
            job_id = str(ledger_row.get("job_id") or uuid.uuid4().hex)
            ref = ProviderJobRef(
                provider=str(ledger_row.get("provider") or provider_name),
                ref=str(ledger_row["provider_job_ref"]),
            )
            if self.store.get_job(job_id) is None:
                pending = Job(
                    id=job_id,
                    workflow_run_id=run_id,
                    node_id=node_id,
                    model_id=str(ledger_row.get("model_id") or model_id),
                    provider_job_ref=ref.ref,
                    state=JobState.RUNNING,
                    inputs=redact_mapping(req.inputs, extra_values=secrets),
                    outputs=[],
                    estimate=estimate,
                    timings=JobTimings(created_at=started, started_at=started),
                    idempotency_key=idempotency_key_value,
                )
                self._persist_job(pending, secrets)
            record_writer_effect("submit_resume_ledger")
        else:
            job_id = uuid.uuid4().hex
            self._require_journal_writer_live()
            self._prepare_provider_submit_intent(
                parent_op_id=parent_op,
                run_id=run_id,
                node_id=node_id,
                job_id=job_id,
                model_id=model_id,
                provider_name=provider_name,
                idempotency_key_value=idempotency_key_value,
            )
            record_writer_effect("submit")
            ref = provider.submit(req)
            record_writer_effect("submit_accepted")
            pending = Job(
                id=job_id,
                workflow_run_id=run_id,
                node_id=node_id,
                model_id=model_id,
                provider_job_ref=ref.ref,
                state=JobState.RUNNING,
                inputs=redact_mapping(req.inputs, extra_values=secrets),
                outputs=[],
                estimate=estimate,
                timings=JobTimings(created_at=started, started_at=started),
                idempotency_key=idempotency_key_value,
            )
            self._persist_job(pending, secrets)
            if os.environ.get("VINCI_TEST_EXIT_AFTER_SUBMIT_ACCEPTED") == "1":
                os._exit(137)  # noqa: SLF001
            self._commit_provider_inflight_ledger(
                parent_op_id=parent_op,
                run_id=run_id,
                node_id=node_id,
                job_id=job_id,
                model_id=model_id,
                provider_name=provider_name,
                provider_job_ref=ref.ref,
                idempotency_key_value=idempotency_key_value,
            )
            if os.environ.get("VINCI_TEST_SLEEP_AFTER_SUBMIT_MS"):
                time.sleep(int(os.environ["VINCI_TEST_SLEEP_AFTER_SUBMIT_MS"]) / 1000.0)
                self._require_journal_writer_live()
            if os.environ.get("VINCI_TEST_EXIT_AFTER_SUBMIT") == "1":
                os._exit(137)  # noqa: SLF001
        return ref, job_id

    def _run_generate(
        self,
        run_id: str,
        node: WorkflowNode,
        params: dict[str, Any],
        spec: WorkflowSpec,
        *,
        receipt_parent_op_id: str | None = None,
    ) -> Job:
        secrets = self._secret_values()
        catalog = self.catalog()
        available = self.routing_providers()
        capability = node.capability
        if capability is None:
            raise ValueError(f"generate node {node.id} missing capability")
        req = JobRequest(
            capability=capability,
            model_id=node.model_id,
            inputs=params if isinstance(params, dict) else {"value": params},
            preference=spec.preference,
        )
        model = resolve_model(catalog, req, available_providers=available or None)
        provider = self.providers[model.provider]
        key = idempotency_key(model.id, req.inputs)
        prior = self.store.find_by_idempotency(key)
        created = now_utc()
        if prior is not None and prior.outputs:
            job_id = uuid.uuid4().hex
            estimate = estimate_from_spec(model, cached=True)
            receipt = Receipt(
                job_id=job_id,
                model_id=model.id,
                provider=model.provider,
                list_price=model.pricing.amount,
                unit_count=1,
                computed_cost=0.0,
                currency="USD",
                pricing_snapshot_at=model.pricing.snapshot_at,
                cached=True,
            )
            job = Job(
                id=job_id,
                workflow_run_id=run_id,
                node_id=node.id,
                model_id=model.id,
                state=JobState.COMPLETED,
                inputs=redact_mapping(req.inputs, extra_values=secrets),
                outputs=list(prior.outputs),
                estimate=estimate,
                receipt=receipt,
                timings=JobTimings(created_at=created, started_at=created, completed_at=now_utc()),
                idempotency_key=key,
            )
            self._persist_job(job, secrets)
            self._emit(
                "job.completed", run_id=run_id, job_id=job.id, payload={"cached": True, "cost": 0}
            )
            return job
        estimate = with_alternative(provider.estimate(req), catalog, capability.value)
        started = now_utc()
        ref, job_id = self._durable_provider_submit(
            parent_op_id=receipt_parent_op_id,
            run_id=run_id,
            node_id=node.id,
            provider=provider,
            model_id=model.id,
            provider_name=model.provider,
            req=req,
            idempotency_key_value=key,
            secrets=secrets,
            estimate=estimate,
            started=started,
        )
        status = self._wait_status(provider, ref)
        self._require_journal_writer_live()
        if status.state in {JobState.FAILED, JobState.CANCELLED}:
            message = status.error.message if status.error else status.state.value
            raise RuntimeError(message)
        kind, mime = CAP_KIND.get(capability, (AssetKind.IMAGE, "application/octet-stream"))
        outputs = self._ingest_status_outputs(
            status,
            kind=kind,
            mime=mime,
            secrets=secrets,
            run_id=run_id,
            model_id=model.id,
            prompt=str(req.inputs.get("prompt") or ""),
        )
        cached = bool(estimate.cached)
        receipt = Receipt(
            job_id=job_id,
            model_id=model.id,
            provider=model.provider,
            list_price=model.pricing.amount,
            unit_count=1,
            computed_cost=0.0 if cached else float(estimate.amount),
            currency=estimate.currency,
            pricing_snapshot_at=estimate.pricing_snapshot_at,
            wall_time=(now_utc() - started).total_seconds(),
            cached=cached,
        )
        job = Job(
            id=job_id,
            workflow_run_id=run_id,
            node_id=node.id,
            model_id=model.id,
            provider_job_ref=ref.ref,
            state=status.state,
            inputs=redact_mapping(req.inputs, extra_values=secrets),
            outputs=outputs,
            estimate=estimate,
            receipt=receipt,
            error=status.error,
            timings=JobTimings(created_at=created, started_at=started, completed_at=now_utc()),
            idempotency_key=key,
        )
        self._persist_job(job, secrets)
        self._emit(
            "job.completed",
            run_id=run_id,
            job_id=job.id,
            payload={"model_id": model.id, "cost": receipt.computed_cost, "cached": cached},
        )
        return job

    def _wait_status(self, provider: Any, ref: ProviderJobRef) -> JobStatus:
        timeout = float(os.environ.get("VINCI_JOB_POLL_TIMEOUT", "120"))
        interval = float(os.environ.get("VINCI_JOB_POLL_INTERVAL", "0.4"))
        deadline = time.monotonic() + timeout
        status = self._coerce_status(provider.status(ref))
        pending = {JobState.QUEUED, JobState.RUNNING, JobState.CREATED}
        while status.state in pending and time.monotonic() < deadline:
            time.sleep(interval)
            self._require_journal_writer_live()
            status = self._coerce_status(provider.status(ref))
        if status.state in pending:
            raise TimeoutError("provider status timed out")
        return status

    def _coerce_status(self, raw: Any) -> JobStatus:
        if isinstance(raw, JobStatus):
            return raw
        raise TypeError("provider.status must return JobStatus")

    def _ingest_status_outputs(
        self,
        status: JobStatus,
        *,
        kind: AssetKind,
        mime: str,
        secrets: list[str],
        run_id: str,
        model_id: str,
        prompt: str,
    ) -> list[str]:
        outputs: list[str] = []
        for item in status.outputs:
            fallback = mime
            decoded = _decode_data_uri(item)
            if decoded is not None:
                blob, uri_mime = decoded
                digest = self._cas_put(blob)
                fallback = uri_mime or mime
            elif item.startswith("http://") or item.startswith("https://"):
                if not allow_live_spend():
                    raise RuntimeError("live download requires VINCI_ALLOW_LIVE_SPEND=1")
                with urllib.request.urlopen(item, timeout=30) as response:
                    blob = response.read()
                digest = self._cas_put(blob)
            else:
                digest = item
                blob = self.cas.get(digest) if self.cas.exists(digest) else b""
            sniffed = _sniff_mime(blob, fallback)
            asset = Asset(
                id=digest,
                kind=kind,
                mime=sniffed,
                bytes=len(blob),
                source=AssetSource.GENERATED,
                created_by=Provenance(
                    skill=(self.store.get_run(run_id) or {}).get("skill"),
                    model_id=model_id,
                ),
                created_at=datetime.now(tz=UTC),
                uri=f"vinci://assets/{digest}",
            )
            self.store.put_asset(asset, secret_values=secrets)
            self._index_asset(asset, extra_text=prompt)
            outputs.append(digest)
        return outputs

    def _persist_job(self, job: Job, secrets: list[str]) -> None:
        self._require_journal_writer_live()
        record_writer_effect("persist_job")
        self.store.put_job(job, secret_values=secrets)
        if job.receipt is not None:
            self.store.put_receipt(job.receipt, secret_values=secrets)

    def _inflight_job_for_node(self, run_id: str, node_id: str) -> Job | None:
        for row in self.store.list_jobs():
            if row.workflow_run_id != run_id or row.node_id != node_id:
                continue
            if row.provider_job_ref and row.state in {
                JobState.RUNNING,
                JobState.QUEUED,
                JobState.CREATED,
            }:
                return row
        return None

    def cost_report(self, by: str = "provider") -> dict[str, Any]:
        jobs = self.store.list_jobs()
        buckets: dict[str, float] = defaultdict(float)
        for job in jobs:
            if job.receipt is None:
                continue
            if by == "provider":
                key = job.receipt.provider
            elif by == "day":
                completed = job.timings.completed_at or job.timings.created_at
                key = completed.strftime("%Y-%m-%d") if completed else "unknown"
            elif by == "skill":
                run = self.store.get_run(job.workflow_run_id) if job.workflow_run_id else None
                key = (run or {}).get("skill") or "unknown"
            else:
                key = by
            buckets[str(key)] += float(job.receipt.computed_cost)
        return {"by": by, "currency": "USD", "totals": dict(buckets), "jobs": len(jobs)}

    def find(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        return self.index.find(query, limit=limit)

    def install_skill(self, path: str | Path) -> dict[str, Any]:
        dest_root = self.config.home / "skills"
        dest_root.mkdir(parents=True, exist_ok=True)
        if dest_root not in self.skills.roots:
            self.skills.roots.append(dest_root)
        skill = install_skill_dir(Path(path), dest_root)
        return self.skills.inspect(skill.id)

    def import_comfy_graph(self, graph: dict[str, Any]) -> WorkflowSpec:
        return import_comfy(graph)

    def ingest_bytes(self, data: bytes, *, mime: str, filename: str | None = None) -> Asset:
        if (not mime or mime == "application/octet-stream") and filename:
            mime = _mime_from_path(Path(filename))
        digest = self._cas_put(data)
        kind = _kind_from_mime(mime)
        asset = Asset(
            id=digest,
            kind=kind,
            mime=mime or "application/octet-stream",
            bytes=len(data),
            source=AssetSource.UPLOADED,
            created_at=datetime.now(tz=UTC),
            uri=f"vinci://assets/{digest}",
            metadata={"filename": filename} if filename else {},
        )
        self.store.put_asset(asset)
        extra = filename or ""
        if kind == AssetKind.TEXT:
            extra = data.decode("utf-8", errors="replace")
        self._index_asset(asset, extra_text=extra)
        return asset

    def adapt_presets(self) -> list[dict[str, Any]]:
        return presets_document(self.config.home)

    def save_custom_preset(self, body: dict[str, Any]) -> dict[str, Any]:
        return create_custom_preset(body, self.config.home)

    def remove_custom_preset(self, preset_id: str) -> None:
        delete_custom_preset(preset_id, self.config.home)

    def _openai_i2i_unit_cost(self) -> float:
        """OpenAI GPT Image 2.5 is token-billed; catalog amounts stay at 0 (no fake USD)."""
        catalog = load_bundled_catalog("openai")
        spec = catalog.cheapest("i2i") or catalog.models[0]
        if spec.pricing.unit == "token" or spec.pricing.amount <= 0:
            return 0.0
        return float(spec.pricing.amount)

    def estimate_adapt(
        self,
        *,
        source_asset: str,
        targets: list[dict[str, Any]],
        layout: str,
        model_id: str | None = None,
    ) -> dict[str, Any]:
        if not self.cas.exists(source_asset):
            raise ValueError("source asset not found")
        parsed_layout: AdaptLayout = (
            "ai_extend" if layout == "ai_extend" else "fit_pad_crop"
        )
        unit = self._openai_i2i_unit_cost() if parsed_layout == "ai_extend" else 0.0
        estimate = estimate_adapt_targets(
            targets, layout=parsed_layout, unit_cost_ai=unit, home=self.config.home
        )
        estimate["source_asset"] = source_asset
        estimate["model_id"] = model_id
        estimate["openai_available"] = self.provider_available("openai")
        estimate["live_spend"] = allow_live_spend()
        return estimate

    def run_adapt(
        self,
        *,
        source_asset: str,
        targets: list[dict[str, Any]],
        layout: str,
        fit_mode: str = "fit",
        model_id: str | None = None,
        max_cost: float | None = None,
        receipt_parent_op_id: str | None = None,
    ) -> dict[str, Any]:
        if not self.cas.exists(source_asset):
            raise ValueError("source asset not found")
        parsed_layout: AdaptLayout = (
            "ai_extend" if layout == "ai_extend" else "fit_pad_crop"
        )
        parsed_fit: FitMode = (
            "fit" if fit_mode not in {"fit", "pad", "crop"} else fit_mode  # type: ignore[assignment]
        )
        estimate = self.estimate_adapt(
            source_asset=source_asset,
            targets=targets,
            layout=layout,
            model_id=model_id,
        )
        total = float(estimate["total"])
        if max_cost is not None and total > max_cost:
            raise ValueError(f"adapt estimate ${total} exceeds max_cost ${max_cost}")
        if parsed_layout == "ai_extend" and total > 0 and not allow_live_spend():
            raise PermissionError(
                "AI extend/re-layout requires VINCI_ALLOW_LIVE_SPEND=1 and OPENAI_API_KEY"
            )
        if parsed_layout == "ai_extend" and not self.provider_available("openai"):
            raise PermissionError("AI extend/re-layout requires enabled OpenAI provider")

        work = self.config.home / "tmp" / uuid.uuid4().hex
        work.mkdir(parents=True, exist_ok=True)
        src_path = work / "source.bin"
        src_path.write_bytes(self.cas.get(source_asset))
        outputs: list[dict[str, Any]] = []
        digests: list[str] = []
        adapt_secrets = self._secret_values()
        for index, raw in enumerate(targets):
            self._require_journal_writer_live()
            width, height, preset_id = resolve_target(raw, self.config.home)
            dest = work / f"adapt-{index}.png"
            if parsed_layout == "fit_pad_crop":
                dest = adapt_image_fit_pad_crop(
                    src_path,
                    dest,
                    width=width,
                    height=height,
                    fit=parsed_fit,
                    preset_id=preset_id,
                    home=self.config.home,
                )
                mode_label = f"fit_pad_crop:{parsed_fit}"
            elif (allow_live_spend() or self._loopback_i2i_enabled()) and self.provider_available(
                "openai"
            ):
                provider = self.providers.get("openai")
                if provider is None:
                    raise RuntimeError("openai provider missing")
                cheapest = load_bundled_catalog("openai").cheapest("i2i")
                if cheapest is None:
                    raise RuntimeError("openai catalog missing i2i model")
                chosen = model_id or cheapest.id
                req = JobRequest(
                    capability=Capability.I2I,
                    model_id=chosen,
                    inputs={
                        "media": source_asset,
                        "prompt": str(raw.get("prompt") or "extend canvas for ad layout"),
                        "size": f"{width}x{height}",
                    },
                )
                estimate_i2i = provider.estimate(req)
                started = now_utc()
                adapt_node_id = f"adapt:{index}"
                adapt_run_id = receipt_parent_op_id or ""
                ref, _adapt_job_id = self._durable_provider_submit(
                    parent_op_id=receipt_parent_op_id,
                    run_id=adapt_run_id,
                    node_id=adapt_node_id,
                    provider=provider,
                    model_id=chosen,
                    provider_name=str(getattr(provider, "provider_id", None) or "openai"),
                    req=req,
                    idempotency_key_value=idempotency_key(chosen, req.inputs),
                    secrets=adapt_secrets,
                    estimate=estimate_i2i,
                    started=started,
                )
                status = self._wait_status(provider, ref)
                self._require_journal_writer_live()
                if status.state != JobState.COMPLETED or not status.outputs:
                    raise RuntimeError("openai adapt did not complete")
                digest = status.outputs[0]
                digests.append(digest)
                outputs.append(
                    {
                        "index": index,
                        "digest": digest,
                        "layout": "ai_extend",
                        "validation": {"width": width, "height": height},
                        "safe_area": safe_area_report(
                            preset_id, width, height, self.config.home
                        ),
                    }
                )
                continue
            else:
                dest = adapt_image_ai_extend_placeholder(
                    src_path,
                    dest,
                    width=width,
                    height=height,
                    preset_id=preset_id,
                    home=self.config.home,
                )
                record_writer_effect("ai_extend")
                mode_label = "ai_extend:mock_pad"
            image_meta = validate_output_image(
                dest, width=width, height=height, preset_id=preset_id, home=self.config.home
            )
            export_mime = (
                "image/jpeg"
                if str(dest).lower().endswith((".jpg", ".jpeg"))
                else "image/png"
            )
            digest = self._put_path(
                dest,
                kind=AssetKind.IMAGE,
                mime=export_mime,
                run_id="",
            )
            digests.append(digest)
            validation = safe_area_report(preset_id, width, height, self.config.home)
            if image_meta.get("export_validation"):
                validation["export_validation"] = image_meta["export_validation"]
            validation["export_bytes"] = image_meta.get("bytes")
            outputs.append(
                {
                    "index": index,
                    "digest": digest,
                    "layout": mode_label,
                    "validation": validation,
                    "safe_area": validation,
                }
            )
        return {
            "source_asset": source_asset,
            "outputs": outputs,
            "digests": digests,
            "estimate": estimate,
        }

    def ingest_url(self, url: str) -> Asset:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("source_url must be http or https")
        request = urllib.request.Request(url, headers={"User-Agent": "vinci-oss"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data = response.read(20 * 1024 * 1024 + 1)
                raw_mime = response.headers.get("Content-Type", "application/octet-stream")
        except urllib.error.URLError as exc:
            raise ValueError(f"could not download source_url: {exc}") from exc
        if len(data) > 20 * 1024 * 1024:
            raise ValueError("source_url exceeds 20MB")
        mime = raw_mime.split(";", 1)[0].strip() or "application/octet-stream"
        filename = Path(parsed.path).name or "source"
        return self.ingest_bytes(data, mime=mime, filename=filename)

    def start_adapt_batch(
        self,
        items: list[dict[str, Any]],
        *,
        fit_mode: str = "pad",
        layout: str = "fit_pad_crop",
        operation_id: str | None = None,
    ) -> dict[str, Any]:
        if not items:
            raise ValueError("batch requires at least one item")
        prepared: list[dict[str, Any]] = []
        for index, raw in enumerate(items):
            if not isinstance(raw, dict):
                raise ValueError("batch item must be an object")
            preset_ids = raw.get("preset_ids")
            if (
                not isinstance(preset_ids, list)
                or not preset_ids
                or not all(isinstance(preset_id, str) and preset_id for preset_id in preset_ids)
            ):
                raise ValueError(f"item {index} needs preset_ids")
            for preset_id in preset_ids:
                if resolve_preset(str(preset_id), self.config.home) is None:
                    raise ValueError(f"unknown adapt preset: {preset_id}")
            source_url = raw.get("source_url") if isinstance(raw.get("source_url"), str) else None
            asset_id = raw.get("asset_id") if isinstance(raw.get("asset_id"), str) else None
            error: str | None = None
            if asset_id:
                if not self.cas.exists(asset_id):
                    error = "source asset not found"
                    asset_id = None
            elif source_url:
                try:
                    asset_id = self.ingest_url(source_url).id
                except ValueError as exc:
                    error = str(exc)
                    asset_id = None
            else:
                raise ValueError(f"item {index} needs asset_id or source_url")
            prepared.append(
                {
                    "index": index,
                    "asset_id": asset_id,
                    "source_url": source_url,
                    "preset_ids": [str(preset_id) for preset_id in preset_ids],
                    "error": error,
                }
            )
        journal_deferred = getattr(self, "_journal", None) is not None and bool(operation_id)
        if journal_deferred:
            op_key = operation_id if operation_id is not None else ""
            batch_id = hashlib.sha256(op_key.encode()).hexdigest()[:32]
        else:
            batch_id = uuid.uuid4().hex
        stored: list[dict[str, Any]] = []
        for item in prepared:
            record: dict[str, Any] = {
                "index": item["index"],
                "asset_id": item["asset_id"],
                "source_url": item["source_url"],
                "preset_ids": item["preset_ids"],
                "run_id": None,
                "error": item["error"],
            }
            if item["error"] or not item["asset_id"]:
                stored.append(record)
                continue
            spec = WorkflowSpec(
                id=f"axis-adapt-{item['index']}",
                version="1",
                nodes=[
                    WorkflowNode(
                        id="adapt",
                        type=NodeType.MEDIA,
                        params={
                            "op": "adapt",
                            "media": item["asset_id"],
                            "preset_ids": item["preset_ids"],
                            "fit_mode": fit_mode,
                            "layout": layout,
                        },
                    )
                ],
            )
            item_op = f"{operation_id}:item:{item['index']}" if journal_deferred else None
            before = {row["id"] for row in self.store.list_runs()}
            try:
                if journal_deferred:
                    run = self.accept_run(
                        None,
                        {"media": item["asset_id"]},
                        workflow=spec,
                        operation_id=item_op,
                    )
                else:
                    run = self.start_run(None, {"media": item["asset_id"]}, workflow=spec)
                record["run_id"] = run.get("id")
                if run.get("state") == JobState.FAILED.value:
                    err = run.get("error") or {}
                    record["error"] = str(err.get("message") or "adapt failed")
            except Exception as exc:  # noqa: BLE001 — item status records the failure
                created = [row for row in self.store.list_runs() if row["id"] not in before]
                if created:
                    record["run_id"] = created[-1]["id"]
                record["error"] = str(exc) or type(exc).__name__
            stored.append(record)
        path = self._batch_path(batch_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"batch_id": batch_id, "items": stored}),
            encoding="utf-8",
        )
        return {"batch_id": batch_id}

    def adapt_batch_status(self, batch_id: str) -> dict[str, Any]:
        path = self._batch_path(batch_id)
        if not path.is_file():
            raise KeyError(batch_id)
        raw = json.loads(path.read_text(encoding="utf-8"))
        items_out: list[dict[str, Any]] = []
        for item in raw.get("items") or []:
            if not isinstance(item, dict):
                continue
            run = self.store.get_run(str(item["run_id"])) if item.get("run_id") else None
            status, error, outputs = self._batch_item_view(item, run)
            items_out.append(
                {
                    "index": item.get("index"),
                    "asset_id": item.get("asset_id"),
                    "source_url": item.get("source_url"),
                    "preset_ids": item.get("preset_ids") or [],
                    "run_id": item.get("run_id"),
                    "status": status,
                    "error": error,
                    "output_asset_ids": [row["asset_id"] for row in outputs],
                    "outputs": outputs,
                }
            )
        return {"batch_id": batch_id, "items": items_out}

    def adapt_batch_bundle(self, batch_id: str) -> bytes:
        status = self.adapt_batch_status(batch_id)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for item in status["items"]:
                if item.get("status") != "done":
                    continue
                for output in item.get("outputs") or []:
                    blob = self.cas.get(str(output["asset_id"]))
                    ext = "jpg" if blob[:2] == b"\xff\xd8" else "png"
                    name = (
                        f"{item['index']}_{output['preset_id']}_"
                        f"{output['width']}x{output['height']}.{ext}"
                    )
                    info = zipfile.ZipInfo(filename=name, date_time=(1980, 1, 1, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    archive.writestr(info, blob)
        return buffer.getvalue()

    def _batch_path(self, batch_id: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{32}", batch_id):
            raise KeyError(batch_id)
        return self.config.home / "batches" / f"{batch_id}.json"

    def _batch_item_view(
        self, item: dict[str, Any], run: dict[str, Any] | None
    ) -> tuple[str, str | None, list[dict[str, Any]]]:
        state = str(run.get("state") or "") if run else ""
        if state == JobState.COMPLETED.value:
            preset_ids = [str(preset_id) for preset_id in item.get("preset_ids") or []]
            digests = [str(digest) for digest in (run or {}).get("outputs") or []]
            return "done", None, self._adapt_output_checks(preset_ids, digests)
        if state == JobState.RUNNING.value:
            return "running", None, []
        if state in {JobState.FAILED.value, JobState.CANCELLED.value}:
            err = (run or {}).get("error") or {}
            message = item.get("error") or err.get("message") or state
            return "failed", str(message), []
        if item.get("error"):
            return "failed", str(item["error"]), []
        queued = {
            JobState.QUEUED.value,
            JobState.AWAITING_APPROVAL.value,
            JobState.CREATED.value,
        }
        if state in queued:
            return "queued", None, []
        return "queued", None, []

    def _adapt_output_checks(
        self, preset_ids: list[str], digests: list[str]
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for preset_id, digest in zip(preset_ids, digests, strict=False):
            preset = resolve_preset(preset_id, self.config.home)
            if preset is None or not self.cas.exists(digest):
                continue
            blob = self.cas.get(digest)
            try:
                actual_w, actual_h = image_dimensions(blob)
            except ValueError:
                actual_w, actual_h = 0, 0
            cap = getattr(preset, "byte_cap", None)
            cap_doc: dict[str, Any] | None = None
            if cap is not None:
                cap_doc = {
                    "max_bytes": cap.max_bytes,
                    "op": cap.op,
                    "actual_bytes": len(blob),
                    "pass": check_export_bytes(len(blob), cap),
                }
            margins = getattr(preset, "safe_rect_margins_px", None)
            if margins is not None:
                safe: dict[str, Any] = {
                    "applied": True,
                    "margins_px": {
                        "left": margins.left,
                        "right": margins.right,
                        "top": margins.top,
                        "bottom": margins.bottom,
                    },
                }
            else:
                safe = {"applied": False, "margins_px": None}
            rows.append(
                {
                    "preset_id": preset_id,
                    "asset_id": digest,
                    "width": preset.width,
                    "height": preset.height,
                    "dimensions": {
                        "width": preset.width,
                        "height": preset.height,
                        "actual_width": actual_w,
                        "actual_height": actual_h,
                        "pass": actual_w == preset.width and actual_h == preset.height,
                    },
                    "byte_cap": cap_doc,
                    "safe_area": safe,
                }
            )
        return rows

    def handshake(self) -> dict[str, str]:
        return {"protocol_version": PROTOCOL_VERSION, "daemon_version": "0.1.0"}

    def _apply_input_defaults(self, skill: Skill, inputs: dict[str, Any]) -> dict[str, Any]:
        out = dict(inputs)
        declared = skill.manifest.get("inputs") or {}
        if not isinstance(declared, dict):
            return out
        for key, meta in declared.items():
            if key in out or not isinstance(meta, dict):
                continue
            if "default" in meta:
                out[key] = meta["default"]
            elif not meta.get("required"):
                out[key] = ""
        return out

    def _prepare_inputs(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return {key: self._ingest_value(value) for key, value in inputs.items()}

    def _ingest_value(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {key: self._ingest_value(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._ingest_value(item) for item in value]
        if isinstance(value, str) and value.startswith("vinci://assets/"):
            return value.removeprefix("vinci://assets/")
        if isinstance(value, str):
            path = Path(value)
            if path.is_file():
                mime = _mime_from_path(path)
                return self.ingest_bytes(path.read_bytes(), mime=mime, filename=path.name).id
        return value

    def _index_asset(self, asset: Asset, extra_text: str = "") -> None:
        transcript = extra_text
        if asset.kind == AssetKind.TEXT and self.cas.exists(asset.id):
            transcript = self.cas.get(asset.id).decode("utf-8", errors="replace")
        self.index.upsert(
            asset.id,
            kind=asset.kind.value,
            transcript=transcript,
            metadata={"mime": asset.mime, **asset.metadata},
        )

    def _materialize(self, value: Any) -> Path:
        text = str(value)
        if text.startswith("vinci://assets/"):
            text = text.removeprefix("vinci://assets/")
        path = Path(text)
        if path.is_file():
            return path
        if self.cas.exists(text):
            dest = self.config.home / "tmp" / text[:2] / text
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists():
                dest.write_bytes(self.cas.get(text))
            return dest
        raise FileNotFoundError(text)

    def _load_jsonish(self, value: Any) -> Any:
        if isinstance(value, dict | list):
            return value
        if not isinstance(value, str):
            return value
        path = Path(value)
        raw: bytes | None = None
        if path.is_file():
            raw = path.read_bytes()
        elif self.cas.exists(value):
            raw = self.cas.get(value)
        else:
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return value

    def _put_path(
        self,
        path: Path,
        *,
        kind: AssetKind,
        mime: str,
        run_id: str,
        source: AssetSource = AssetSource.DERIVED,
        extra_text: str = "",
    ) -> str:
        data = path.read_bytes()
        digest = self._cas_put(data)
        self._require_journal_writer_live()
        asset = Asset(
            id=digest,
            kind=kind,
            mime=mime,
            bytes=len(data),
            source=source,
            created_by=Provenance(skill=(self.store.get_run(run_id) or {}).get("skill")),
            created_at=datetime.now(tz=UTC),
            uri=f"vinci://assets/{digest}",
        )
        self.store.put_asset(asset)
        self._index_asset(asset, extra_text=extra_text)
        return digest

    def _local_job(
        self,
        run_id: str,
        node: WorkflowNode,
        *,
        model_id: str,
        inputs: dict[str, Any],
        outputs: list[str],
        extra: Any = None,
    ) -> Job:
        secrets = self._secret_values()
        job_id = uuid.uuid4().hex
        created = now_utc()
        estimate = Estimate(
            model_id=model_id,
            provider="local",
            amount=0.0,
            currency="USD",
            unit="op",
            unit_count=1,
            pricing_snapshot_at=created,
        )
        receipt = Receipt(
            job_id=job_id,
            model_id=model_id,
            provider="local",
            list_price=0.0,
            unit_count=1,
            computed_cost=0.0,
            currency="USD",
            pricing_snapshot_at=created,
        )
        job = Job(
            id=job_id,
            workflow_run_id=run_id,
            node_id=node.id,
            model_id=model_id,
            state=JobState.COMPLETED,
            inputs=redact_mapping(inputs, extra_values=secrets),
            outputs=outputs,
            estimate=estimate,
            receipt=receipt,
            timings=JobTimings(created_at=created, started_at=created, completed_at=now_utc()),
        )
        self._persist_job(job, secrets)
        self._emit(
            "job.completed",
            run_id=run_id,
            job_id=job.id,
            payload={"model_id": model_id, "cost": 0, "cached": False},
        )
        return job

    def _run_media(self, run_id: str, node: WorkflowNode, params: dict[str, Any]) -> Job:
        self._require_journal_writer_live()
        op = str(params.get("op") or "")
        work = self.config.home / "tmp" / uuid.uuid4().hex
        work.mkdir(parents=True, exist_ok=True)
        extra: Any = None
        outputs: list[str] = []
        if op == "transcribe":
            src = self._materialize(params.get("media"))
            extra = mock_transcribe(src)
            dest = work / "transcript.json"
            dest.write_text(json.dumps(extra), encoding="utf-8")
            outputs = [
                self._put_path(
                    dest,
                    kind=AssetKind.TEXT,
                    mime="application/json",
                    run_id=run_id,
                    extra_text=str(extra.get("text") or ""),
                )
            ]
        elif op == "select_windows":
            transcript = params.get("transcript")
            if not isinstance(transcript, dict):
                transcript = self._load_jsonish(transcript)
            if not isinstance(transcript, dict):
                raise ValueError("select_windows needs a transcript object")
            extra = select_windows(
                transcript,
                query=str(params.get("query") or "pricing"),
                count=int(params.get("count") or 1),
            )
            dest = work / "windows.json"
            dest.write_text(json.dumps(extra), encoding="utf-8")
            outputs = [
                self._put_path(
                    dest,
                    kind=AssetKind.TEXT,
                    mime="application/json",
                    run_id=run_id,
                    extra_text=json.dumps(extra),
                )
            ]
        elif op == "cut":
            src = self._materialize(params.get("media"))
            windows = params.get("windows")
            if windows is None and "start" in params:
                windows = [{"start": float(params["start"]), "end": float(params["end"])}]
            if not isinstance(windows, list):
                loaded = self._load_jsonish(windows)
                windows = loaded if isinstance(loaded, list) else [loaded]
            for i, window in enumerate(windows):
                if not isinstance(window, dict):
                    continue
                dest = work / f"cut-{i}.mp4"
                cut(src, dest, float(window["start"]), float(window["end"]))
                outputs.append(
                    self._put_path(dest, kind=AssetKind.VIDEO, mime="video/mp4", run_id=run_id)
                )
            extra = windows
        elif op == "reframe_9x16":
            src = self._materialize(params.get("media"))
            dest = work / "reframe.mp4"
            reframe_9x16(src, dest)
            outputs = [self._put_path(dest, kind=AssetKind.VIDEO, mime="video/mp4", run_id=run_id)]
        elif op == "burn_captions":
            src = self._materialize(params.get("media"))
            text = params.get("text") or "pricing"
            if not isinstance(text, str):
                text = json.dumps(text)
            dest = work / "captioned.mp4"
            burn_captions(src, dest, str(text))
            outputs = [self._put_path(dest, kind=AssetKind.VIDEO, mime="video/mp4", run_id=run_id)]
        elif op == "concat":
            paths = [self._materialize(item) for item in (params.get("media") or [])]
            dest = work / "concat.mp4"
            concat(paths, dest)
            outputs = [self._put_path(dest, kind=AssetKind.VIDEO, mime="video/mp4", run_id=run_id)]
        elif op == "render_timeline":
            raw = params.get("timeline") if isinstance(params.get("timeline"), dict) else params
            clips = raw.get("clips") if isinstance(raw, dict) else None
            if not isinstance(clips, list) or not clips:
                raise ValueError("render_timeline needs clips")
            parts: list[Path] = []
            for i, clip in enumerate(clips):
                if not isinstance(clip, dict):
                    raise ValueError("timeline clip must be an object")
                src = self._materialize(clip.get("asset_id") or clip.get("media"))
                start = clip.get("start")
                end = clip.get("end")
                if start is not None or end is not None:
                    info = probe(src)
                    dest_clip = work / f"clip-{i}.mp4"
                    cut(
                        src,
                        dest_clip,
                        float(start or 0),
                        float(end if end is not None else info["duration"]),
                    )
                    parts.append(dest_clip)
                else:
                    parts.append(src)
            dest = work / "timeline.mp4"
            render_timeline(parts, dest)
            outputs = [self._put_path(dest, kind=AssetKind.VIDEO, mime="video/mp4", run_id=run_id)]
        elif op == "adapt":
            src = self._materialize(params.get("media"))
            preset_ids = params.get("preset_ids")
            if not isinstance(preset_ids, list) or not preset_ids:
                raise ValueError("adapt needs preset_ids")
            fit_raw = str(params.get("fit_mode") or "pad")
            parsed_fit: FitMode = fit_raw if fit_raw in {"fit", "pad", "crop"} else "pad"  # type: ignore[assignment]
            layout = str(params.get("layout") or "fit_pad_crop")
            for index, preset_id in enumerate(preset_ids):
                if not isinstance(preset_id, str) or not preset_id:
                    raise ValueError("preset_ids must be strings")
                self._require_journal_writer_live()
                width, height, resolved = resolve_target(
                    {"preset_id": preset_id}, self.config.home
                )
                dest = work / f"adapt-{index}.png"
                if layout == "ai_extend":
                    dest = adapt_image_ai_extend_placeholder(
                        src,
                        dest,
                        width=width,
                        height=height,
                        preset_id=resolved,
                        home=self.config.home,
                    )
                    record_writer_effect("ai_extend")
                else:
                    dest = adapt_image_fit_pad_crop(
                        src,
                        dest,
                        width=width,
                        height=height,
                        fit=parsed_fit,
                        preset_id=resolved,
                        home=self.config.home,
                    )
                export_mime = (
                    "image/jpeg"
                    if str(dest).lower().endswith((".jpg", ".jpeg"))
                    else "image/png"
                )
                outputs.append(
                    self._put_path(dest, kind=AssetKind.IMAGE, mime=export_mime, run_id=run_id)
                )
        elif op == "split":
            src = self._materialize(params.get("media"))
            info = probe(src)
            extra = split_fixed(float(info.get("duration") or 3), int(params.get("count") or 3))
            for i, window in enumerate(extra):
                dest = work / f"part-{i}.mp4"
                cut(src, dest, float(window["start"]), float(window["end"]))
                outputs.append(
                    self._put_path(dest, kind=AssetKind.VIDEO, mime="video/mp4", run_id=run_id)
                )
        else:
            raise ValueError(f"unknown media op {op}")
        if not outputs:
            raise ValueError(f"media op {op} produced no outputs")
        job = self._local_job(
            run_id,
            node,
            model_id="local:ffmpeg:v1",
            inputs=params,
            outputs=outputs,
            extra=extra,
        )
        return job

    def _run_indexquery(self, run_id: str, node: WorkflowNode, params: dict[str, Any]) -> Job:
        query = str(params.get("query") or "")
        extra = self.find(query, limit=int(params.get("limit") or 20))
        work = self.config.home / "tmp" / uuid.uuid4().hex
        work.mkdir(parents=True, exist_ok=True)
        dest = work / "hits.json"
        dest.write_text(json.dumps(extra), encoding="utf-8")
        digest = self._put_path(
            dest,
            kind=AssetKind.TEXT,
            mime="application/json",
            run_id=run_id,
            extra_text=query,
        )
        return self._local_job(
            run_id,
            node,
            model_id="local:index:v1",
            inputs=params,
            outputs=[digest],
            extra=extra,
        )


def _kind_from_mime(mime: str) -> AssetKind:
    if mime.startswith("image/"):
        return AssetKind.IMAGE
    if mime.startswith("video/"):
        return AssetKind.VIDEO
    if mime.startswith("audio/"):
        return AssetKind.AUDIO
    if mime.startswith("text/") or mime in {"application/json"}:
        return AssetKind.TEXT
    return AssetKind.TEXT


def _mime_from_path(path: Path) -> str:
    suffix = path.suffix.lower()
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".webm": "video/webm",
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".json": "application/json",
        ".txt": "text/plain",
    }.get(suffix, "application/octet-stream")
