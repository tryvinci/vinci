"""Studio projects on the local daemon (COREPRODUC-702): the hosted ``/projects`` API on SQLite.

A project groups runs, uploads and show folders, and keeps one canvas board (pages, comments,
viewports) with a revision number: a save from a stale window gets HTTP 409.

Tables in ``vinci.sqlite`` (next to the runtime's own tables, which do not change):

- ``projects``: id, name, is_default, board (JSON), board_rev, archived_at, created_at, updated_at.
- ``project_links``: (kind, item_id) -> project_id, where kind is ``run``, ``asset`` or ``show``.
  A run is linked once, when it starts. An upload can be in several projects: the CAS gives the
  same bytes one asset id. Outputs need no link: they belong to their run's project.

The default project ("My work", id ``default``) is made on first use. Work with no link (saved
before projects) is in it. Shows renders (workflow ``olf:*``) stay out of project feeds: a show
keeps its own takes.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from vinci_daemon.durable_ops import with_journal_ack

log = logging.getLogger("vinci.projects")

DEFAULT_ID = "default"
DEFAULT_NAME = "My work"
MAX_NAME = 120
MAX_BOARD_BYTES = 2 * 1024 * 1024  # a board holds asset ids, never media bytes
SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, is_default INTEGER NOT NULL DEFAULT 0, board TEXT,
  board_rev INTEGER NOT NULL DEFAULT 0, archived_at TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS project_links (
  kind TEXT NOT NULL, item_id TEXT NOT NULL, project_id TEXT NOT NULL,
  PRIMARY KEY (kind, item_id, project_id)
);
"""
# One lock for every read and write: the store shares one SQLite connection between request
# threads. Bug fixed (first occurrence 2026-11-18, the Shows e2e of COREPRODUC-702 PR 2, before
# release): reads ran without it, and a read beside another (`GET /assets` and `GET /runs` at boot)
# found no default project, so `/assets?project=default` answered 404. Reentrant: `all` calls `get`.
_LOCK = threading.RLock()


def _now() -> str:
    return datetime.now(tz=UTC).isoformat()


class ProjectStore:
    """The project and link tables. One per engine (``store(engine)``)."""

    def __init__(self, path: Path) -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        now = _now()
        self._conn.execute(
            "INSERT OR IGNORE INTO projects(id, name, is_default, created_at, updated_at) "
            "VALUES (?, ?, 1, ?, ?)",
            (DEFAULT_ID, DEFAULT_NAME, now, now),
        )
        self._conn.commit()

    def _rows(self, sql: str, args: tuple[Any, ...] | list[Any] = ()) -> list[sqlite3.Row]:
        """Run a read under the store's lock."""
        with _LOCK:
            return self._conn.execute(sql, args).fetchall()

    def get(self, project_id: str) -> dict[str, Any]:
        """The project row as the Studio reads it (``board`` too), or HTTP 404."""
        found = self._rows("SELECT * FROM projects WHERE id=?", (project_id,))
        row = found[0] if found else None
        if row is None:
            raise HTTPException(status_code=404, detail="That project is not in your Studio.")
        return {
            "id": row["id"],
            "name": row["name"],
            "default": bool(row["is_default"]),
            "board": json.loads(row["board"]) if row["board"] else None,
            "board_rev": row["board_rev"],
            "archived_at": row["archived_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def all(self) -> list[dict[str, Any]]:
        """Every project without its board, last changed first, in one read (no delete between)."""
        cols = "id, name, is_default, board_rev, archived_at, created_at, updated_at"
        rows = self._rows(f"SELECT {cols} FROM projects ORDER BY updated_at DESC")
        out = []
        for row in rows:
            item = dict(row)
            item["default"] = bool(item.pop("is_default"))
            out.append(item)
        return out

    def set_meta(self, doc: dict[str, Any]) -> None:
        """Change a project's name, archive time and change time only: never its board, and
        never a row deleted meanwhile (CodeRabbit on #682: a full-row write undid a board save)."""
        with _LOCK:
            self._conn.execute(
                "UPDATE projects SET name=?, archived_at=?, updated_at=? WHERE id=?",
                (doc["name"], doc.get("archived_at"), doc["updated_at"], doc["id"]),
            )
            self._conn.commit()

    def put(self, doc: dict[str, Any]) -> None:
        """Insert or replace a project row (create, update, board save, journal replay)."""
        board = json.dumps(doc["board"]) if doc.get("board") is not None else None
        with _LOCK:
            self._conn.execute(
                "INSERT OR REPLACE INTO projects VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    doc["id"],
                    doc["name"],
                    int(bool(doc.get("default"))),
                    board,
                    int(doc.get("board_rev") or 0),
                    doc.get("archived_at"),
                    doc["created_at"],
                    doc["updated_at"],
                ),
            )
            self._conn.commit()

    def save_board(self, project_id: str, board: dict[str, Any], rev: int) -> bool:
        """Save the board when ``rev`` is the saved revision. False: another window saved first."""
        with _LOCK:
            cur = self._conn.execute(
                "UPDATE projects SET board=?, board_rev=?, updated_at=? WHERE id=? AND board_rev=?",
                (json.dumps(board), rev + 1, _now(), project_id, rev),
            )
            self._conn.commit()
        return cur.rowcount == 1

    def delete(self, project_id: str) -> None:
        with _LOCK:
            self._conn.execute("DELETE FROM projects WHERE id=? AND is_default=0", (project_id,))
            self._conn.commit()

    def link(
        self,
        kind: str,
        item_id: str,
        project_id: str | None,
        *,
        only_once: bool = False,
        fresh: bool = False,
    ) -> None:
        """Put an item in a project. ``only_once``: keep an existing link (a run, a show).

        No link means the default project. An upload is the exception: the same bytes can be in a
        named project and in My work (one CAS id), so My work gets an explicit link too.
        ``fresh``: a show folder just made. A deleted show with the same path left its link, which
        would keep the new show in the old project, so it goes first (CodeRabbit on #691).
        """
        with _LOCK:
            if fresh:
                self._conn.execute(
                    "DELETE FROM project_links WHERE kind=? AND item_id=?", (kind, item_id)
                )
                self._conn.commit()
            if not project_id or (project_id == DEFAULT_ID and kind != "asset"):
                return
            if (
                only_once
                and self._conn.execute(
                    "SELECT 1 FROM project_links WHERE kind=? AND item_id=?", (kind, item_id)
                ).fetchone()
            ):
                return
            self._conn.execute(
                "INSERT OR IGNORE INTO project_links VALUES (?, ?, ?)", (kind, item_id, project_id)
            )
            self._conn.commit()

    def linked(self, kind: str, project_id: str | None = None) -> dict[str, set[str]]:
        """``{item_id: {project ids}}`` for one kind (all projects, or one)."""
        sql, args = "SELECT item_id, project_id FROM project_links WHERE kind=?", [kind]
        if project_id:
            sql, args = sql + " AND project_id=?", [kind, project_id]
        out: dict[str, set[str]] = {}
        for row in self._rows(sql, args):
            out.setdefault(row["item_id"], set()).add(row["project_id"])
        return out

    def used(self, project_id: str) -> bool:
        return bool(
            self._rows("SELECT 1 FROM project_links WHERE project_id=? LIMIT 1", (project_id,))
        )


def store(engine: Any) -> ProjectStore:
    """The engine's project store, made on first use in its ``vinci.sqlite``."""
    with _LOCK:
        found = getattr(engine, "_projects", None)
        if found is None:
            found = ProjectStore(Path(engine.store.path))
            engine._projects = found
    return found


def view(doc: dict[str, Any]) -> dict[str, Any]:
    """A project without its board (``GET /projects/{id}/board`` has it)."""
    return {k: v for k, v in doc.items() if k != "board"}


def _name(value: Any) -> str:
    name = " ".join(str(value or "").split())[:MAX_NAME]
    if not name:
        raise HTTPException(status_code=400, detail="Give the project a name.")
    return name


def stamp(engine: Any, project_id: str | None) -> str | None:
    """A checked project id for new work (404 when missing, 409 when archived); None: default."""
    if not project_id:
        return None
    doc = store(engine).get(project_id)
    if doc["archived_at"]:
        raise HTTPException(
            status_code=409, detail="That project is archived. Restore it to add work."
        )
    return str(doc["id"])


def member(engine: Any, kind: str, project_id: str) -> Any:
    """A test ``item_id -> bool`` for one project; an item with no link is in the default project.

    It reads the links once, so a list of any length costs one query.
    """
    owners = store(engine).linked(kind)
    return lambda item_id: (
        project_id in owners[item_id] if item_id in owners else project_id == DEFAULT_ID
    )


def _show_render(run: dict[str, Any]) -> bool:
    return str((run.get("workflow") or {}).get("id") or "").startswith("olf:")


def filter_runs(engine: Any, runs: list[dict[str, Any]], project_id: str) -> list[dict[str, Any]]:
    """``GET /runs?project=``: the project's runs, without Shows renders."""
    store(engine).get(project_id)  # 404 for an unknown project
    inside = member(engine, "run", project_id)
    return [run for run in runs if not _show_render(run) and inside(str(run.get("id")))]


def asset_ids(engine: Any, project_id: str) -> set[str]:
    """``GET /assets`` and ``/library`` with ``?project=``: its uploads and its runs' outputs."""
    runs = engine.store.list_runs()
    ids = {
        str(a) for run in filter_runs(engine, runs, project_id) for a in run.get("outputs") or []
    }
    ids |= set(store(engine).linked("asset", project_id))
    if project_id == DEFAULT_ID:  # plus every asset nothing else claims (saved before projects)
        mine = {id(run) for run in filter_runs(engine, runs, DEFAULT_ID)}
        claimed = set(store(engine).linked("asset"))
        claimed |= {str(a) for run in runs if id(run) not in mine for a in run.get("outputs") or []}
        ids |= {a.id for a in engine.store.list_assets()} - claimed
    return ids


def show_key(path: Any) -> str:
    """A show folder's link id: its resolved path, as ``/olf/shows`` lists it."""
    return str(Path(str(path)).expanduser().resolve())


class ProjectBody(BaseModel):
    name: str | None = None
    archived: bool | None = None


class BoardBody(BaseModel):
    board: Any = None
    board_rev: int = 0  # 0: the first save of a new board


router = APIRouter()


def _ack(
    request: Request, method: str, path: str, payload: dict[str, Any], build: Any
) -> dict[str, Any]:
    return with_journal_ack(
        request, method=method, path=path, payload=payload, blob_keys=[], build_response=build
    )


@router.get("/projects")
def list_projects(request: Request) -> dict[str, Any]:
    return {"projects": store(request.app.state.engine).all()}


@router.post("/projects")
def create_project(body: ProjectBody, request: Request) -> dict[str, Any]:
    eng, now = request.app.state.engine, _now()
    doc = {
        "id": uuid.uuid4().hex,
        "name": _name(body.name),
        "default": False,
        "board": None,
        "board_rev": 0,
        "archived_at": None,
        "created_at": now,
        "updated_at": now,
    }

    def build() -> dict[str, Any]:
        store(eng).put(doc)
        log.info("project created id=%s", doc["id"])
        return view(doc)

    return _ack(request, "POST", "/projects", {"name": doc["name"]}, build)


@router.get("/projects/{project_id}")
def get_project(project_id: str, request: Request) -> dict[str, Any]:
    return view(store(request.app.state.engine).get(project_id))


@router.patch("/projects/{project_id}")
def update_project(project_id: str, body: ProjectBody, request: Request) -> dict[str, Any]:
    eng = request.app.state.engine
    doc = store(eng).get(project_id)
    if body.name is not None:
        doc["name"] = _name(body.name)
    if body.archived is not None:
        if doc["default"] and body.archived:
            raise HTTPException(status_code=400, detail="The default project cannot be archived.")
        doc["archived_at"] = _now() if body.archived else None
    doc["updated_at"] = _now()

    def build() -> dict[str, Any]:
        store(eng).set_meta(doc)
        log.info(
            "project updated id=%s name=%r archived=%s",
            project_id,
            doc["name"],
            bool(doc["archived_at"]),
        )
        return view(doc)

    return _ack(
        request, "PATCH", f"/projects/{project_id}", body.model_dump(exclude_none=True), build
    )


@router.delete("/projects/{project_id}")
def delete_project(project_id: str, request: Request) -> dict[str, Any]:
    eng = request.app.state.engine
    if store(eng).get(project_id)["default"]:
        raise HTTPException(status_code=400, detail="The default project cannot be deleted.")
    if store(eng).used(project_id):
        raise HTTPException(
            status_code=409, detail="This project has work in it. Archive it instead."
        )

    def build() -> dict[str, Any]:
        store(eng).delete(project_id)
        log.info("project deleted id=%s", project_id)
        return {"deleted": True, "id": project_id}

    return _ack(request, "DELETE", f"/projects/{project_id}", {"id": project_id}, build)


@router.get("/projects/{project_id}/board")
def get_board(project_id: str, request: Request) -> dict[str, Any]:
    doc = store(request.app.state.engine).get(project_id)
    return {"board": doc["board"], "board_rev": doc["board_rev"]}


@router.put("/projects/{project_id}/board")
def put_board(project_id: str, body: BoardBody, request: Request) -> dict[str, Any]:
    eng = request.app.state.engine
    saved = store(eng).get(project_id)["board_rev"]
    if not isinstance(body.board, dict):
        raise HTTPException(status_code=400, detail="Send the board as an object.")
    if len(json.dumps(body.board)) > MAX_BOARD_BYTES:
        raise HTTPException(status_code=413, detail="The board is larger than 2 MB.")

    def build() -> dict[str, Any]:
        if not store(eng).save_board(project_id, body.board, body.board_rev):
            log.warning(
                "project board stale id=%s sent_rev=%s saved_rev=%s",
                project_id,
                body.board_rev,
                saved,
            )
            raise HTTPException(
                status_code=409,
                detail="This board changed in another window. Reload it, then try again.",
            )
        log.info("project board saved id=%s board_rev=%s", project_id, body.board_rev + 1)
        return {"board_rev": body.board_rev + 1, "id": project_id}

    return _ack(request, "PUT", f"/projects/{project_id}/board", body.model_dump(), build)


def replay(engine: Any, kind: str, payload: dict[str, Any], response: dict[str, Any]) -> None:
    """Re-apply a committed journal operation (it may run twice, so each step is idempotent).

    Project rows come back from their responses; the board from the payload; the run and upload
    links from the ``project_id`` in the payload of ``run_accept`` and ``asset_upload``.
    """
    s = store(engine)
    if kind == "project_create" and response.get("id"):
        try:
            s.get(response["id"])  # already there: keep its board
        except HTTPException:
            s.put(response | {"board": None, "board_rev": 0})
    elif kind == "project_update" and response.get("id"):
        s.set_meta(response)
    elif kind == "project_delete" and response.get("id"):
        s.delete(str(response["id"]))
    elif kind == "project_board" and response.get("id"):
        doc = s.get(str(response["id"]))
        if int(response.get("board_rev") or 0) > doc["board_rev"]:
            s.put(doc | {"board": payload.get("board"), "board_rev": response["board_rev"]})
    elif kind == "run_accept" and response.get("id"):
        s.link("run", str(response["id"]), payload.get("project_id"), only_once=True)
    elif kind == "asset_upload" and response.get("id"):
        s.link("asset", str(response["id"]), payload.get("project_id"))
