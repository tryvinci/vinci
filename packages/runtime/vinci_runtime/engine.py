from __future__ import annotations

import base64
import difflib
import json
import os
import re
import shutil
import time
import urllib.request
import uuid
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
    presets_document,
    resolve_target,
    safe_area_report,
    validate_output_image,
)
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
from vinci_protocol.constants import PROTOCOL_VERSION
from vinci_protocol.enums import AssetKind, AssetSource, Capability, JobState, RoutePreference
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
from vinci_storage.cas import ContentAddressedStore
from vinci_storage.sqlite_store import SqliteStore

from vinci_runtime.comfy import import_comfy

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
        self.cas = ContentAddressedStore(self.config.cas_dir)
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

    def _rebuild_providers(self) -> None:
        cas = self.cas
        resolver = self.resolver
        self.providers = {
            "mock": MockProvider(cas, api_key=resolver.resolve("MOCK_API_KEY")),
            "wavespeed": WavespeedProvider(api_key=resolver.resolve("WAVESPEED_API_KEY")),
            "google": GoogleProvider(api_key=resolver.resolve("GEMINI_API_KEY")),
            "openai": OpenAIProvider(
                api_key=resolver.resolve("OPENAI_API_KEY"),
                cas=cas,
            ),
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
            key = resolver.resolve(mcp_secret_name(name)) or resolver.resolve("MCP_API_KEY")
            self.providers[name] = McpProvider(HttpMcpTransport(url), api_key=key, cas=cas)

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

    def _emit(
        self,
        type_: str,
        *,
        run_id: str | None = None,
        job_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        secrets = self.resolver.known_values(all_secret_names())
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
        secrets = provider_secret_names(name)
        mcp = is_mcp_name(name)
        configured = name == "mock" or bool(
            (mcp and cfg.get("url"))
            or (secrets and all(self.resolver.resolve(secret) for secret in secrets))
        )
        return {
            "enabled": name in self.enabled_provider_ids(),
            "available": self.provider_available(name),
            "configured": configured,
            "secret_name": secrets[0] if secrets else "",
            "extra_secret_names": list(PROVIDER_EXTRA_SECRETS.get(name, ())),
            "display_name": str(cfg.get("label") or PROVIDER_LABELS.get(name) or name),
            "kind": "mcp" if mcp else "http",
            "docs": PROVIDER_DOCS.get(name) or ("https://modelcontextprotocol.io" if mcp else ""),
            "url": cfg.get("url") if mcp else None,
            "authorize_url": cfg.get("authorize_url"),
            "auth": "oauth_or_key" if mcp else "key",
        }

    def doctor(self) -> dict[str, Any]:
        home = self.config.home
        ffmpeg = shutil.which("ffmpeg")
        disk = shutil.disk_usage(home)
        names = list(PROVIDER_DOCS)
        for name in self.config.providers:
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
            resolved_url = url or body.get("url")
            if not resolved_url:
                raise ValueError("mcp provider requires url")
            body["url"] = resolved_url
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

    def oauth_start(self, name: str) -> dict[str, Any]:
        if name not in PROVIDER_SECRETS and not is_mcp_name(name):
            raise KeyError(name)
        if is_mcp_name(name):
            cfg = self.config.providers.get(name) or {}
            authorize = cfg.get("authorize_url") if isinstance(cfg, dict) else None
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
        label = PROVIDER_LABELS.get(name, name)
        return {
            "id": name,
            "mode": "key",
            "authorize_url": None,
            "hint": f"{label} uses a pasted API key, not a browser login.",
        }

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
        }

    def update_settings(
        self,
        *,
        preference: str | None = None,
        monthly_cap_usd: float | None = None,
        require_approval_over: float | None = None,
    ) -> dict[str, Any]:
        if preference is not None:
            self.config.preference = RoutePreference(preference).value
        if monthly_cap_usd is not None:
            self.config.budget.monthly_cap_usd = monthly_cap_usd
        if require_approval_over is not None:
            self.config.budget.require_approval_over = require_approval_over
        write_config(self.config)
        self.config = load_config(self.config.home)
        return self.settings()

    def remove_provider(self, name: str) -> None:
        self.config.providers.pop(name, None)
        write_config(self.config)
        self.config = load_config(self.config.home)
        self._rebuild_providers()

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
        total = sum(float(row["estimate"].amount) for row in rows)
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
        secrets = self.resolver.known_values(all_secret_names())
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
        total = sum(float(row["estimate"].amount) for row in rows)
        plan = {
            "skill": f"{skill_name}@{skill_version}",
            "total": total,
            "currency": "USD",
            "nodes": [
                {
                    "node_id": row["node_id"],
                    "model_id": row["model"].id,
                    "amount": row["estimate"].amount,
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
        run_id = uuid.uuid4().hex
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
        return self._execute_run(run_id)

    def approve_run(self, run_id: str) -> dict[str, Any]:
        run = self.store.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        if run["state"] != JobState.AWAITING_APPROVAL.value:
            raise ValueError(f"run {run_id} is {run['state']}")
        self.store.put_run(run_id, run, JobState.QUEUED.value)
        self._emit("run.approved", run_id=run_id, payload={})
        return self._execute_run(run_id)

    def cancel_run(self, run_id: str) -> dict[str, Any]:
        run = self.store.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        run["cancelled"] = True
        self.store.put_run(run_id, run, JobState.CANCELLED.value)
        self._emit("run.cancelled", run_id=run_id, payload={})
        return self.store.get_run(run_id) or run

    def _execute_run(self, run_id: str) -> dict[str, Any]:
        run = self.store.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        spec = WorkflowSpec.model_validate(run["workflow"])
        inputs = run.get("inputs") or {}
        self.store.put_run(run_id, run, JobState.RUNNING.value)
        self._emit("run.started", run_id=run_id, payload={})
        context: dict[str, Any] = {"inputs": inputs, "nodes": {}}
        job_ids: list[str] = []
        final_outputs: list[str] = []
        node_map: dict[str, Any] = {}
        try:
            for node in _topo(spec):
                params = interpolate(node.params, context)
                if not isinstance(params, dict):
                    params = {"value": params}
                if node.type.value == "generate":
                    job = self._run_generate(run_id, node, params, spec)
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
            run["job_ids"] = job_ids
            run["outputs"] = final_outputs
            run["nodes"] = node_map
            run["asset_uris"] = [f"vinci://assets/{digest}" for digest in final_outputs]
            run["job_uris"] = [f"vinci://jobs/{jid}" for jid in job_ids]
            run["receipt_uris"] = [f"vinci://receipts/{jid}" for jid in job_ids]
            self.store.put_run(run_id, run, JobState.COMPLETED.value)
            self._emit("run.completed", run_id=run_id, payload={"outputs": final_outputs})
        except Exception as exc:  # noqa: BLE001 — normalize into run failure
            run["job_ids"] = job_ids
            run["nodes"] = node_map
            run["error"] = {"code": "unknown", "message": type(exc).__name__}
            self.store.put_run(run_id, run, JobState.FAILED.value)
            self._emit("run.failed", run_id=run_id, payload=run["error"])
            raise
        return self.store.get_run(run_id) or run

    def _run_generate(
        self, run_id: str, node: WorkflowNode, params: dict[str, Any], spec: WorkflowSpec
    ) -> Job:
        secrets = self.resolver.known_values(all_secret_names())
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
        job_id = uuid.uuid4().hex
        created = now_utc()
        if prior is not None and prior.outputs:
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
        ref = provider.submit(req)
        status = self._wait_status(provider, ref)
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
            currency="USD",
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
                digest = self.cas.put(blob)
                fallback = uri_mime or mime
            elif item.startswith("http://") or item.startswith("https://"):
                if not allow_live_spend():
                    raise RuntimeError("live download requires VINCI_ALLOW_LIVE_SPEND=1")
                with urllib.request.urlopen(item, timeout=30) as response:
                    blob = response.read()
                digest = self.cas.put(blob)
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
        self.store.put_job(job, secret_values=secrets)
        if job.receipt is not None:
            self.store.put_receipt(job.receipt, secret_values=secrets)

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
        digest = self.cas.put(data)
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
        return presets_document()

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
            targets, layout=parsed_layout, unit_cost_ai=unit
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
        for index, raw in enumerate(targets):
            width, height, preset_id = resolve_target(raw)
            dest = work / f"adapt-{index}.png"
            if parsed_layout == "fit_pad_crop":
                adapt_image_fit_pad_crop(
                    src_path,
                    dest,
                    width=width,
                    height=height,
                    fit=parsed_fit,
                    preset_id=preset_id,
                )
                mode_label = f"fit_pad_crop:{parsed_fit}"
            elif allow_live_spend() and self.provider_available("openai"):
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
                provider.estimate(req)
                ref = provider.submit(req)
                status = provider.status(ref)
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
                        "safe_area": safe_area_report(preset_id, width, height),
                    }
                )
                continue
            else:
                adapt_image_ai_extend_placeholder(
                    src_path, dest, width=width, height=height, preset_id=preset_id
                )
                mode_label = "ai_extend:mock_pad"
            image_meta = validate_output_image(
                dest, width=width, height=height, preset_id=preset_id
            )
            digest = self._put_path(
                dest,
                kind=AssetKind.IMAGE,
                mime="image/png",
                run_id="",
            )
            digests.append(digest)
            validation = safe_area_report(preset_id, width, height)
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
        digest = self.cas.put(data)
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
        secrets = self.resolver.known_values(all_secret_names())
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
