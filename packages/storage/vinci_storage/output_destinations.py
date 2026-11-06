"""Persist generated outputs to user-configured destinations with JSON sidecars."""

from __future__ import annotations

import json
import logging
import mimetypes
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from vinci_core.config import OutputDestinationConfig

from vinci_storage.r2_client import R2Client

LOG = logging.getLogger("vinci.output_destinations")

SIDECAR_SCHEMA = "1"
_SAFE_SEGMENT = re.compile(r"[^a-zA-Z0-9._-]+")


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


def _safe_segment(value: str, *, fallback: str = "default") -> str:
    cleaned = _SAFE_SEGMENT.sub("_", value.strip())[:120]
    return cleaned or fallback


def extension_for_mime(mime: str) -> str:
    base = (mime or "application/octet-stream").split(";", 1)[0].strip().lower()
    if base == "image/jpeg":
        return "jpg"
    if base == "image/png":
        return "png"
    if base == "video/mp4":
        return "mp4"
    if base == "audio/mpeg":
        return "mp3"
    if base == "audio/wav":
        return "wav"
    guessed = mimetypes.guess_extension(base) or ".bin"
    return guessed.lstrip(".")


def build_sidecar(
    *,
    asset_id: str,
    run_id: str,
    mime: str,
    prompt: str | None,
    model_id: str | None,
    provider: str | None,
    params: dict[str, Any] | None,
    source_ids: dict[str, Any] | None,
    saved_at: datetime | None = None,
    run_completed_at: datetime | None = None,
    destination_kind: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the sidecar document written next to each exported file."""
    body: dict[str, Any] = {
        "schema_version": SIDECAR_SCHEMA,
        "asset_id": asset_id,
        "run_id": run_id,
        "mime": mime,
        "prompt": prompt or "",
        "model_id": model_id or "",
        "provider": provider or "",
        "params": params or {},
        "timestamps": {
            "saved_at": (saved_at or _utc_now()).isoformat(),
        },
        "source_ids": source_ids or {},
        "destination": {"kind": destination_kind},
    }
    if run_completed_at is not None:
        body["timestamps"]["run_completed_at"] = run_completed_at.isoformat()
    if extra:
        body["destination"].update(extra)
    return body


@dataclass(frozen=True)
class OutputArtifact:
    """One saved blob plus its sidecar metadata file."""

    asset_id: str
    destination_kind: str
    media_path: str
    sidecar_path: str
    photos_album: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    sidecar: dict[str, Any] = field(default_factory=dict)


class OutputDestination(Protocol):
    """Export sink for generated media. Roadmap #2 overlays the sidecar onto Assets."""

    kind: str

    def save(
        self,
        *,
        blob: bytes,
        mime: str,
        asset_id: str,
        sidecar: dict[str, Any],
    ) -> OutputArtifact: ...


class NoneOutputDestination:
    kind = "none"

    def save(
        self,
        *,
        blob: bytes,
        mime: str,
        asset_id: str,
        sidecar: dict[str, Any],
    ) -> OutputArtifact:
        raise RuntimeError("none destination does not persist outputs")


class LocalFolderDestination:
    kind = "local"

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser()
        self.root.mkdir(parents=True, exist_ok=True)

    def save(
        self,
        *,
        blob: bytes,
        mime: str,
        asset_id: str,
        sidecar: dict[str, Any],
    ) -> OutputArtifact:
        stamp = _utc_now().strftime("%Y%m%dT%H%M%SZ")
        ext = extension_for_mime(mime)
        base = f"{stamp}_{asset_id[:12]}.{ext}"
        media_path = self.root / base
        media_path.write_bytes(blob)
        sidecar_path = media_path.with_suffix(media_path.suffix + ".vinci.json")
        sidecar_path.write_text(
            json.dumps(sidecar, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return OutputArtifact(
            asset_id=asset_id,
            destination_kind=self.kind,
            media_path=str(media_path),
            sidecar_path=str(sidecar_path),
        )


class PhotosAlbumDestination:
    """Stage under ~/.vinci/exports/photos for macOS Photos import."""

    kind = "photos"

    def __init__(self, home: Path, album: str) -> None:
        album_dir = _safe_segment(album, fallback="Vinci")
        root = home / "exports" / "photos" / album_dir
        self.album = album.strip() or "Vinci"
        self._local = LocalFolderDestination(root)

    def save(
        self,
        *,
        blob: bytes,
        mime: str,
        asset_id: str,
        sidecar: dict[str, Any],
    ) -> OutputArtifact:
        saved = self._local.save(blob=blob, mime=mime, asset_id=asset_id, sidecar=sidecar)
        return OutputArtifact(
            asset_id=saved.asset_id,
            destination_kind=self.kind,
            media_path=saved.media_path,
            sidecar_path=saved.sidecar_path,
            photos_album=self.album,
            extra={"photos_album": self.album},
        )


class R2OutputDestination:
    kind = "r2"

    def __init__(self, client: R2Client, prefix: str) -> None:
        self.client = client
        self.prefix = prefix.strip("/") + "/" if prefix.strip() else ""

    def save(
        self,
        *,
        blob: bytes,
        mime: str,
        asset_id: str,
        sidecar: dict[str, Any],
    ) -> OutputArtifact:
        stamp = _utc_now().strftime("%Y%m%dT%H%M%SZ")
        ext = extension_for_mime(mime)
        key_base = f"{self.prefix}{stamp}_{asset_id[:12]}"
        media_key = f"{key_base}.{ext}"
        sidecar_key = f"{key_base}.vinci.json"
        self.client.put_bytes(media_key, blob, content_type=mime)
        sidecar_bytes = json.dumps(sidecar, indent=2, sort_keys=True).encode("utf-8") + b"\n"
        self.client.put_bytes(sidecar_key, sidecar_bytes, content_type="application/json")
        return OutputArtifact(
            asset_id=asset_id,
            destination_kind=self.kind,
            media_path=f"s3://{self.client.bucket}/{media_key}",
            sidecar_path=f"s3://{self.client.bucket}/{sidecar_key}",
        )


def build_output_destination(
    config: OutputDestinationConfig, *, home: Path
) -> OutputDestination | None:
    kind = (config.kind or "none").strip().lower()
    if kind in {"", "none"}:
        return None
    if kind == "local":
        root = Path(config.local_dir).expanduser() if config.local_dir.strip() else home / "exports"
        return LocalFolderDestination(root)
    if kind == "photos":
        return PhotosAlbumDestination(home, config.photos_album or "Vinci")
    if kind == "r2":
        client = R2Client.from_env()
        if client is None:
            raise ValueError(
                "R2 output destination requires VINCI_R2_BUCKET, credentials, "
                "or VINCI_R2_MOCK_DIR for local testing"
            )
        return R2OutputDestination(client, config.r2_prefix or "vinci/outputs/")
    raise ValueError(f"unknown output destination kind: {kind}")


def output_destination_public(config: OutputDestinationConfig, *, home: Path) -> dict[str, Any]:
    """Settings-safe view (no secrets)."""
    r2_ready = R2Client.from_env() is not None
    local_default = str((home / "exports").expanduser())
    return {
        "kind": config.kind or "none",
        "local_dir": config.local_dir or local_default,
        "photos_album": config.photos_album or "Vinci",
        "r2_prefix": config.r2_prefix or "vinci/outputs/",
        "r2_configured": r2_ready,
    }


def export_asset(
    destination: OutputDestination,
    *,
    blob: bytes,
    mime: str,
    asset_id: str,
    run_id: str,
    prompt: str | None,
    model_id: str | None,
    provider: str | None,
    params: dict[str, Any] | None,
    source_ids: dict[str, Any] | None,
    run_completed_at: datetime | None = None,
) -> OutputArtifact:
    sidecar = build_sidecar(
        asset_id=asset_id,
        run_id=run_id,
        mime=mime,
        prompt=prompt,
        model_id=model_id,
        provider=provider,
        params=params,
        source_ids=source_ids,
        run_completed_at=run_completed_at,
        destination_kind=destination.kind,
    )
    if destination.kind == "photos" and isinstance(destination, PhotosAlbumDestination):
        sidecar["destination"]["photos_album"] = destination.album
    saved = destination.save(blob=blob, mime=mime, asset_id=asset_id, sidecar=sidecar)
    return OutputArtifact(
        asset_id=saved.asset_id,
        destination_kind=saved.destination_kind,
        media_path=saved.media_path,
        sidecar_path=saved.sidecar_path,
        photos_album=saved.photos_album,
        extra=saved.extra,
        sidecar=sidecar,
    )


def artifact_to_dict(row: OutputArtifact) -> dict[str, Any]:
    out: dict[str, Any] = {
        "asset_id": row.asset_id,
        "destination_kind": row.destination_kind,
        "media_path": row.media_path,
        "sidecar_path": row.sidecar_path,
    }
    if row.photos_album:
        out["photos_album"] = row.photos_album
    out.update(row.extra)
    return out
