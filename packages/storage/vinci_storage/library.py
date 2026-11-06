"""Index completed runs (CAS/receipts) and exported sidecars into a local library."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, TypeVar, cast

LOG = logging.getLogger("vinci.library")
_F = TypeVar("_F", bound=Callable[..., Any])


def _db_locked(method: _F) -> _F:
    """Serialize sqlite use. One shared connection is not safe across FastAPI threads.

    Parallel Image/Video/Assets loads hit this on first open (InterfaceError:
    bad parameter or other API misuse). Seen once while loading Studio after
    the library index landed.
    """

    def wrapped(self: Any, *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            return method(self, *args, **kwargs)

    # Keep the method's own signature so mypy checks callers and return types.
    return cast(_F, wrapped)

SIDECAR_SUFFIX = ".vinci.json"
DATE_PRESETS = {"all", "today", "7d", "30d"}
SECTIONS = {"assets", "projects", "favorites", "elements", "trash"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS library_items (
  id TEXT PRIMARY KEY,
  asset_id TEXT NOT NULL,
  run_id TEXT NOT NULL DEFAULT '',
  media_kind TEXT NOT NULL,
  mime TEXT NOT NULL DEFAULT '',
  prompt TEXT NOT NULL DEFAULT '',
  model_id TEXT NOT NULL DEFAULT '',
  provider TEXT NOT NULL DEFAULT '',
  params TEXT NOT NULL DEFAULT '{}',
  source_ids TEXT NOT NULL DEFAULT '{}',
  destination_kind TEXT NOT NULL DEFAULT '',
  media_path TEXT NOT NULL DEFAULT '',
  sidecar_path TEXT NOT NULL DEFAULT '',
  photos_album TEXT,
  saved_at TEXT NOT NULL DEFAULT '',
  run_completed_at TEXT,
  media_missing INTEGER NOT NULL DEFAULT 0,
  favorite INTEGER NOT NULL DEFAULT 0,
  trashed_at TEXT,
  origin TEXT NOT NULL DEFAULT 'sidecar',
  enhanced INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS library_items_saved_at ON library_items(saved_at);
CREATE INDEX IF NOT EXISTS library_items_kind ON library_items(media_kind);
CREATE INDEX IF NOT EXISTS library_items_model ON library_items(model_id);
CREATE INDEX IF NOT EXISTS library_items_provider ON library_items(provider);
CREATE INDEX IF NOT EXISTS library_items_favorite ON library_items(favorite);
CREATE INDEX IF NOT EXISTS library_items_trashed ON library_items(trashed_at);
CREATE INDEX IF NOT EXISTS library_items_enhanced ON library_items(enhanced);
"""

_MIGRATIONS = (
    ("favorite", "INTEGER NOT NULL DEFAULT 0"),
    ("trashed_at", "TEXT"),
    ("origin", "TEXT NOT NULL DEFAULT 'sidecar'"),
    ("enhanced", "INTEGER NOT NULL DEFAULT 0"),
)


def media_kind_from_mime(mime: str) -> str:
    """Map a MIME type to image, video, audio, or other."""
    base = (mime or "").split(";", 1)[0].strip().lower()
    if base.startswith("image/"):
        return "image"
    if base.startswith("video/"):
        return "video"
    if base.startswith("audio/"):
        return "audio"
    return "other"


def item_id_for_asset(asset_id: str) -> str:
    """Stable library id from a CAS asset digest so CAS and sidecar rows merge."""
    return hashlib.sha256(f"asset:{asset_id}".encode()).hexdigest()[:16]


def item_id_for_sidecar(sidecar_path: str) -> str:
    """Stable library id from the sidecar path when no asset_id is present."""
    return hashlib.sha256(sidecar_path.encode("utf-8")).hexdigest()[:16]


def media_path_for_sidecar(sidecar_path: Path) -> Path:
    """Return the media file that sits beside `{file}.vinci.json`."""
    name = sidecar_path.name
    if name.endswith(SIDECAR_SUFFIX):
        return sidecar_path.with_name(name[: -len(SIDECAR_SUFFIX)])
    return sidecar_path.with_suffix("")


def is_remote_path(path: str) -> bool:
    lowered = path.strip().lower()
    return (
        lowered.startswith("s3://")
        or lowered.startswith("https://")
        or lowered.startswith("http://")
    )


def local_file(path: str) -> Path | None:
    """Resolve a local filesystem path; return None for remote or empty values."""
    raw = (path or "").strip()
    if not raw or is_remote_path(raw):
        return None
    return Path(raw).expanduser()


def under_roots(path: Path, roots: list[Path]) -> bool:
    """Return True when `path` is inside one of the allowed roots."""
    try:
        resolved = path.expanduser().resolve()
    except OSError:
        return False
    for root in roots:
        try:
            if resolved.is_relative_to(root.expanduser().resolve()):
                return True
        except OSError:
            continue
    return False


def scan_sidecar_paths(roots: list[Path]) -> list[Path]:
    """Find `{file}.vinci.json` files under each existing root."""
    found: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob(f"*{SIDECAR_SUFFIX}"):
            if not path.is_file():
                continue
            key = str(path.resolve())
            if key in seen:
                continue
            seen.add(key)
            found.append(path)
    return found


def date_bounds(
    preset: str | None, date_from: str | None, date_to: str | None
) -> tuple[str | None, str | None]:
    """Resolve a date preset or explicit ISO bounds.

    Args:
        preset: `all`, `today`, `7d`, `30d`, or empty.
        date_from: Inclusive ISO timestamp.
        date_to: Exclusive ISO timestamp.

    Returns:
        Inclusive start and exclusive end, either of which may be None.
    """
    start = (date_from or "").strip() or None
    end = (date_to or "").strip() or None
    kind = (preset or "").strip().lower()
    if kind in {"", "all"} or kind not in DATE_PRESETS:
        return start, end
    now = datetime.now(tz=UTC)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if kind == "today":
        return start or today.isoformat(), end or (today + timedelta(days=1)).isoformat()
    days = 7 if kind == "7d" else 30
    return start or (today - timedelta(days=days)).isoformat(), end


def is_enhanced(*, model_id: str, source_ids: dict[str, Any]) -> bool:
    """True when the run is an upscale / enhance, not a first-pass generate."""
    cap = str(source_ids.get("capability") or "").strip().lower()
    model = (model_id or "").lower()
    return cap == "upscale" or "upscale" in model


def rerun_hints(*, mime: str, model_id: str, source_ids: dict[str, Any]) -> dict[str, str]:
    """Pick the Studio page and skill that re-run this generation."""
    cap = str(source_ids.get("capability") or "").strip().lower()
    kind = media_kind_from_mime(mime)
    model = (model_id or "").lower()
    if cap == "upscale" or "upscale" in model:
        if kind == "video":
            return {"skill": "@tryvinci/video-upscale", "page": "upscale"}
        return {"skill": "@tryvinci/image-upscale", "page": "upscale"}
    if cap in {"t2v", "i2v"} or kind == "video":
        return {"skill": "@tryvinci/video-generate", "page": "video"}
    if cap == "lipsync":
        return {"skill": "@tryvinci/lipsync", "page": "speak"}
    if cap == "voice_clone":
        return {"skill": "@tryvinci/voice-clone", "page": "speak"}
    if cap == "tts" or kind == "audio":
        return {"skill": "@tryvinci/tts", "page": "speak"}
    return {"skill": "@tryvinci/image-generate", "page": "image"}


def parse_sidecar(path: Path) -> dict[str, Any] | None:
    """Load one sidecar JSON document. Return None when it is unreadable."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        LOG.warning("skip sidecar %s: %s", path, exc)
        return None
    if not isinstance(raw, dict):
        LOG.warning("skip sidecar %s: not an object", path)
        return None
    return raw


class LibraryIndex:
    """SQLite catalog of completed runs. Created on first ingest, not on construct.

    Identity is `hash(asset:{asset_id})` so a CAS ingest and a later sidecar
    export of the same digest share one row. Sidecars without an asset_id keep
    the path hash. A missing `library.sqlite` means no completed run yet.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None
        if path.is_file():
            self._open()

    @_db_locked
    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    @property
    def exists(self) -> bool:
        return self.path.is_file()

    def _open(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA)
        self._migrate(conn)
        conn.commit()
        self._conn = conn
        LOG.info("opened library index at %s", self.path)
        return conn

    def _migrate(self, conn: sqlite3.Connection) -> None:
        cols = {str(row[1]) for row in conn.execute("PRAGMA table_info(library_items)")}
        for name, spec in _MIGRATIONS:
            if name in cols:
                continue
            conn.execute(f"ALTER TABLE library_items ADD COLUMN {name} {spec}")
            LOG.info("migrated library_items: added %s", name)

    def _ensure(self) -> sqlite3.Connection:
        return self._conn if self._conn is not None else self._open()

    def _item_id(self, asset_id: str, sidecar_path: str) -> str:
        if asset_id:
            return item_id_for_asset(asset_id)
        return item_id_for_sidecar(sidecar_path)

    @_db_locked
    def upsert_document(
        self,
        sidecar: dict[str, Any],
        *,
        sidecar_path: str,
        media_path: str,
        photos_album: str | None = None,
        origin: str = "sidecar",
    ) -> dict[str, Any]:
        """Insert or merge one library row from a sidecar or CAS document."""
        dest = sidecar.get("destination")
        timestamps = sidecar.get("timestamps")
        params = sidecar.get("params")
        source_ids = sidecar.get("source_ids")
        dest = dest if isinstance(dest, dict) else {}
        timestamps = timestamps if isinstance(timestamps, dict) else {}
        params = params if isinstance(params, dict) else {}
        source_ids = source_ids if isinstance(source_ids, dict) else {}
        mime = str(sidecar.get("mime") or "")
        album = photos_album or dest.get("photos_album")
        local = local_file(media_path)
        present = local is not None and local.is_file()
        remote = is_remote_path(media_path)
        media_missing = 0 if (remote or origin == "cas") else int(not present)
        asset_id = str(sidecar.get("asset_id") or "")
        item_id = self._item_id(asset_id, sidecar_path)
        model_id = str(sidecar.get("model_id") or "")
        conn = self._ensure()
        existing = conn.execute(
            "SELECT * FROM library_items WHERE id=?", (item_id,)
        ).fetchone()
        media_final = media_path or (str(existing["media_path"]) if existing else "")
        sidecar_final = sidecar_path or (
            str(existing["sidecar_path"]) if existing else ""
        )
        new_dest = str(dest.get("kind") or sidecar.get("destination_kind") or "")
        old_dest = str(existing["destination_kind"]) if existing else ""
        if new_dest in {"", "none"} and old_dest not in {"", "none"}:
            dest_kind = old_dest
        else:
            dest_kind = new_dest or old_dest
        origin_final = "cas" if origin == "cas" or (
            existing and existing["origin"] == "cas"
        ) else (origin or "sidecar")
        saved_at = str(existing["saved_at"] or "") if existing and existing["saved_at"] else str(
            timestamps.get("saved_at") or ""
        )
        run_completed = (
            existing["run_completed_at"]
            if existing and existing["run_completed_at"]
            else timestamps.get("run_completed_at")
        )
        run_completed_at = str(run_completed) if run_completed else None
        enhanced = 1 if is_enhanced(model_id=model_id, source_ids=source_ids) else 0
        if existing and existing["enhanced"]:
            enhanced = 1
        favorite = int(existing["favorite"]) if existing else 0
        trashed_at = str(existing["trashed_at"]) if existing and existing["trashed_at"] else None
        if existing and existing["media_missing"] == 0 and not media_path:
            media_missing = 0
        elif remote or origin_final == "cas":
            media_missing = 0 if (remote or origin_final == "cas") else media_missing
        row = (
            item_id,
            asset_id,
            str(sidecar.get("run_id") or (existing["run_id"] if existing else "")),
            media_kind_from_mime(mime) or (str(existing["media_kind"]) if existing else "other"),
            mime or (str(existing["mime"]) if existing else ""),
            str(sidecar.get("prompt") or (existing["prompt"] if existing else "")),
            model_id or (str(existing["model_id"]) if existing else ""),
            str(sidecar.get("provider") or (existing["provider"] if existing else "")),
            json.dumps(params) if params else (str(existing["params"]) if existing else "{}"),
            json.dumps(source_ids) if source_ids else (
                str(existing["source_ids"]) if existing else "{}"
            ),
            dest_kind,
            media_final,
            sidecar_final,
            str(album) if album else (existing["photos_album"] if existing else None),
            saved_at,
            run_completed_at,
            media_missing,
            favorite,
            trashed_at,
            origin_final,
            enhanced,
        )
        conn.execute(
            """
            INSERT INTO library_items (
              id, asset_id, run_id, media_kind, mime, prompt, model_id, provider,
              params, source_ids, destination_kind, media_path, sidecar_path,
              photos_album, saved_at, run_completed_at, media_missing,
              favorite, trashed_at, origin, enhanced
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              asset_id=excluded.asset_id,
              run_id=excluded.run_id,
              media_kind=excluded.media_kind,
              mime=excluded.mime,
              prompt=excluded.prompt,
              model_id=excluded.model_id,
              provider=excluded.provider,
              params=excluded.params,
              source_ids=excluded.source_ids,
              destination_kind=excluded.destination_kind,
              media_path=excluded.media_path,
              sidecar_path=excluded.sidecar_path,
              photos_album=excluded.photos_album,
              saved_at=excluded.saved_at,
              run_completed_at=excluded.run_completed_at,
              media_missing=excluded.media_missing,
              origin=excluded.origin,
              enhanced=excluded.enhanced
            """,
            row,
        )
        if asset_id and sidecar_path:
            legacy = item_id_for_sidecar(sidecar_path)
            if legacy != item_id:
                conn.execute("DELETE FROM library_items WHERE id=?", (legacy,))
        conn.commit()
        LOG.info(
            "indexed library item %s asset=%s origin=%s model=%s kind=%s",
            item_id,
            asset_id,
            origin_final,
            model_id,
            media_kind_from_mime(mime),
        )
        loaded = self.get(item_id)
        assert loaded is not None
        return loaded

    @_db_locked
    def ingest_run_asset(
        self,
        *,
        asset_id: str,
        run_id: str,
        mime: str,
        prompt: str = "",
        model_id: str = "",
        provider: str = "",
        params: dict[str, Any] | None = None,
        source_ids: dict[str, Any] | None = None,
        destination_kind: str = "none",
        completed_at: str | datetime | None = None,
    ) -> dict[str, Any]:
        """Index one completed-run output from CAS/receipts (no sidecar required)."""
        when = completed_at.isoformat() if isinstance(completed_at, datetime) else (
            str(completed_at) if completed_at else datetime.now(tz=UTC).isoformat()
        )
        return self.upsert_document(
            {
                "asset_id": asset_id,
                "run_id": run_id,
                "mime": mime,
                "prompt": prompt,
                "model_id": model_id,
                "provider": provider,
                "params": params or {},
                "source_ids": source_ids or {},
                "destination": {"kind": destination_kind or "none"},
                "timestamps": {"saved_at": when, "run_completed_at": when},
            },
            sidecar_path="",
            media_path="",
            origin="cas",
        )

    @_db_locked
    def ingest_sidecar(self, path: Path, *, media_path: str | None = None) -> dict[str, Any] | None:
        """Read one sidecar file and upsert it.

        Args:
            path: Path to `{file}.vinci.json`.
            media_path: Override when the media is not beside the sidecar.

        Returns:
            The stored item, or None when the sidecar is missing or invalid.
        """
        if not path.is_file():
            LOG.warning("sidecar missing: %s", path)
            return None
        doc = parse_sidecar(path)
        if doc is None:
            return None
        resolved = str(path.resolve())
        media = media_path or str(media_path_for_sidecar(path))
        return self.upsert_document(doc, sidecar_path=resolved, media_path=media, origin="sidecar")

    @_db_locked
    def scan(self, roots: list[Path]) -> int:
        """Discover sidecars under `roots` and upsert them.

        CAS-origin rows stay even when their sidecar is gone (destination=none).
        Sidecar-only rows whose local sidecar disappeared are pruned.

        Returns:
            Number of sidecar files ingested on this pass.
        """
        paths = scan_sidecar_paths(roots)
        LOG.info("scanning %s sidecar(s) under %s root(s)", len(paths), len(roots))
        ingested = 0
        live: set[str] = set()
        for path in paths:
            item = self.ingest_sidecar(path)
            if item is None:
                continue
            ingested += 1
            live.add(item["id"])
        if self._conn is None:
            return ingested
        existing_roots = [root for root in roots if root.is_dir()]
        rows = self._conn.execute(
            "SELECT id, sidecar_path, origin FROM library_items"
        ).fetchall()
        for row in rows:
            if str(row["origin"] or "") == "cas":
                continue
            sidecar = str(row["sidecar_path"] or "")
            local = local_file(sidecar)
            if local is None:
                continue
            if not under_roots(local, existing_roots):
                continue
            if not local.is_file() and row["id"] not in live:
                LOG.info("pruning missing sidecar %s", sidecar)
                self._conn.execute("DELETE FROM library_items WHERE id=?", (row["id"],))
        self._conn.commit()
        return ingested

    @_db_locked
    def count(self, *, include_trashed: bool = False) -> int:
        if self._conn is None:
            return 0
        if include_trashed:
            sql = "SELECT COUNT(*) AS n FROM library_items"
            row = self._conn.execute(sql).fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM library_items WHERE trashed_at IS NULL"
            ).fetchone()
        return int(row["n"]) if row else 0

    @_db_locked
    def get(self, item_id: str) -> dict[str, Any] | None:
        if self._conn is None:
            return None
        row = self._conn.execute("SELECT * FROM library_items WHERE id=?", (item_id,)).fetchone()
        return self._to_item(row) if row else None

    @_db_locked
    def query(
        self,
        *,
        kind: str | None = None,
        model: str | None = None,
        provider: str | None = None,
        date: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        q: str | None = None,
        tool: str | None = None,
        section: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Filter library items. Search `q` matches the prompt (case-insensitive)."""
        if self._conn is None:
            return []
        clauses: list[str] = []
        args: list[Any] = []
        section_key = (section or "assets").strip().lower() or "assets"
        if section_key not in SECTIONS:
            section_key = "assets"
        if section_key == "elements":
            return []
        if section_key == "trash":
            clauses.append("trashed_at IS NOT NULL")
        else:
            clauses.append("trashed_at IS NULL")
        if section_key == "favorites":
            clauses.append("favorite = 1")
        tool_key = (tool or "").strip().lower()
        if tool_key == "enhanced":
            clauses.append("enhanced = 1")
        elif tool_key in {"image", "video", "audio"}:
            clauses.append("media_kind = ?")
            args.append(tool_key)
            if tool_key == "image":
                clauses.append("enhanced = 0")
        elif kind and kind != "all":
            clauses.append("media_kind = ?")
            args.append(kind)
        if model:
            clauses.append("model_id = ?")
            args.append(model)
        if provider:
            clauses.append("provider = ?")
            args.append(provider)
        start, end = date_bounds(date, date_from, date_to)
        if start:
            clauses.append("saved_at >= ?")
            args.append(start)
        if end:
            clauses.append("saved_at < ?")
            args.append(end)
        needle = (q or "").strip()
        if needle:
            clauses.append("LOWER(prompt) LIKE ?")
            args.append(f"%{needle.lower()}%")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        capped = max(1, min(int(limit), 500))
        rows = self._conn.execute(
            f"SELECT * FROM library_items {where} ORDER BY saved_at DESC, id DESC LIMIT ?",
            [*args, capped],
        ).fetchall()
        return [self._to_item(row) for row in rows]

    @_db_locked
    def facets(self) -> dict[str, Any]:
        """Distinct kinds, models, and providers for Assets filters."""
        empty: dict[str, Any] = {"kinds": [], "models": [], "providers": []}
        if self._conn is None:
            return empty
        kinds = [
            str(row[0])
            for row in self._conn.execute(
                "SELECT DISTINCT media_kind FROM library_items "
                "WHERE trashed_at IS NULL ORDER BY media_kind"
            )
        ]
        models = [
            {"model_id": str(row[0]), "provider": str(row[1])}
            for row in self._conn.execute(
                "SELECT DISTINCT model_id, provider FROM library_items "
                "WHERE trashed_at IS NULL ORDER BY provider, model_id"
            )
            if row[0]
        ]
        providers = [
            str(row[0])
            for row in self._conn.execute(
                "SELECT DISTINCT provider FROM library_items "
                "WHERE provider != '' AND trashed_at IS NULL ORDER BY provider"
            )
        ]
        return {"kinds": kinds, "models": models, "providers": providers}

    @_db_locked
    def trash(self, item_id: str) -> dict[str, Any]:
        """Soft-delete: keep the row and files so Trash can restore it."""
        item = self.get(item_id)
        if item is None:
            raise KeyError(item_id)
        if item.get("trashed_at"):
            return {"trashed": item_id, "trashed_at": item["trashed_at"]}
        when = datetime.now(tz=UTC).isoformat()
        assert self._conn is not None
        self._conn.execute(
            "UPDATE library_items SET trashed_at=? WHERE id=?", (when, item_id)
        )
        self._conn.commit()
        LOG.info("trashed library item %s", item_id)
        return {"trashed": item_id, "trashed_at": when}

    @_db_locked
    def restore(self, item_id: str) -> dict[str, Any]:
        """Clear trash so the item returns to Assets."""
        item = self.get(item_id)
        if item is None:
            raise KeyError(item_id)
        assert self._conn is not None
        self._conn.execute(
            "UPDATE library_items SET trashed_at=NULL WHERE id=?", (item_id,)
        )
        self._conn.commit()
        LOG.info("restored library item %s", item_id)
        loaded = self.get(item_id)
        assert loaded is not None
        return loaded

    @_db_locked
    def set_favorite(self, item_id: str, favorite: bool) -> dict[str, Any]:
        """Heart or un-heart an item (Higgsfield Favourites)."""
        item = self.get(item_id)
        if item is None:
            raise KeyError(item_id)
        assert self._conn is not None
        self._conn.execute(
            "UPDATE library_items SET favorite=? WHERE id=?", (1 if favorite else 0, item_id)
        )
        self._conn.commit()
        LOG.info("library item %s favorite=%s", item_id, favorite)
        loaded = self.get(item_id)
        assert loaded is not None
        return loaded

    @_db_locked
    def purge(self, item_id: str, *, roots: list[Path]) -> dict[str, Any]:
        """Remove an item from the index and unlink local media + sidecar under `roots`."""
        item = self.get(item_id)
        if item is None:
            raise KeyError(item_id)
        for key in ("media_path", "sidecar_path"):
            local = local_file(str(item.get(key) or ""))
            if local is None or not local.is_file():
                continue
            if not under_roots(local, roots):
                LOG.warning("refusing to unlink %s (outside library roots)", local)
                continue
            try:
                local.unlink()
                LOG.info("deleted library file %s", local)
            except OSError as exc:
                LOG.warning("could not unlink %s: %s", local, exc)
        assert self._conn is not None
        self._conn.execute("DELETE FROM library_items WHERE id=?", (item_id,))
        self._conn.commit()
        LOG.info("purged library item %s", item_id)
        return {"deleted": item_id}

    @_db_locked
    def delete(self, item_id: str, *, roots: list[Path] | None = None) -> dict[str, Any]:
        """Soft-delete (trash). Pass `roots` only when calling `purge`."""
        del roots
        return self.trash(item_id)

    def _to_item(self, row: sqlite3.Row) -> dict[str, Any]:
        params = json.loads(row["params"] or "{}")
        source_ids = json.loads(row["source_ids"] or "{}")
        hints = rerun_hints(
            mime=row["mime"] or "",
            model_id=row["model_id"] or "",
            source_ids=source_ids if isinstance(source_ids, dict) else {},
        )
        media_path = row["media_path"] or ""
        local = local_file(media_path)
        origin = str(row["origin"] or "sidecar")
        missing = bool(row["media_missing"]) or (
            origin != "cas" and local is not None and not local.is_file()
        )
        return {
            "id": row["id"],
            "asset_id": row["asset_id"],
            "run_id": row["run_id"],
            "media_kind": row["media_kind"],
            "mime": row["mime"],
            "prompt": row["prompt"],
            "model_id": row["model_id"],
            "provider": row["provider"],
            "params": params if isinstance(params, dict) else {},
            "source_ids": source_ids if isinstance(source_ids, dict) else {},
            "destination_kind": row["destination_kind"],
            "media_path": media_path,
            "sidecar_path": row["sidecar_path"],
            "photos_album": row["photos_album"],
            "saved_at": row["saved_at"],
            "run_completed_at": row["run_completed_at"],
            "media_missing": missing,
            "local": local is not None,
            "favorite": bool(row["favorite"]),
            "trashed_at": row["trashed_at"],
            "origin": origin,
            "enhanced": bool(row["enhanced"]),
            "rerun_skill": hints["skill"],
            "rerun_page": hints["page"],
        }
