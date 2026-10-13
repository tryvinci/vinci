from __future__ import annotations

import argparse
import asyncio
import html
import json
import os
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from vinci_core.paths import default_home
from vinci_core.templates import get_template, preview_svg
from vinci_mcp.server import handle_rpc
from vinci_protocol.constants import PROTOCOL_VERSION
from vinci_protocol.models import WorkflowSpec
from vinci_runtime.engine import Engine
from vinci_storage.durable_journal import JournalConfigError, JournalError, journal_from_env
from vinci_storage.home_persistence import persistence_from_env

from vinci_daemon.bridge_auth import BridgeAuthMiddleware
from vinci_daemon.durable_ops import client_operation_id, with_journal_ack
from vinci_daemon.durable_receipts import commit_run_receipt_before_complete
from vinci_daemon.journal_heartbeat import JournalWriterHeartbeat, attach_heartbeat
from vinci_daemon.journal_middleware import JournalHealthMiddleware
from vinci_daemon.outbox_dispatch import reconcile_pending_outbox
from vinci_daemon.persistence_middleware import PersistenceHealthMiddleware

DAEMON_PORT = 4310
_OAUTH_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "testserver"}
STUDIO_HTML = Path(__file__).with_name("studio.html")
STUDIO_ICON = Path(__file__).with_name("studio-icon.svg")
STUDIO_MANIFEST = {
    "name": "Vinci Studio",
    "short_name": "Vinci",
    "start_url": "/studio",
    "display": "standalone",
    "background_color": "#09090b",
    "theme_color": "#09090b",
    "icons": [{"src": "/studio/icon.svg", "sizes": "any", "type": "image/svg+xml"}],
}


class RunBody(BaseModel):
    skill: str | None = None
    workflow: dict[str, Any] | None = None
    workflow_path: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    max_cost: float | None = None
    preference: str | None = None
    model_id: str | None = None


class ProviderBody(BaseModel):
    id: str
    from_env: str | None = None
    secret: str | None = None
    extra_secret: str | None = None
    extra_from_env: str | None = None
    url: str | None = None
    account_id: str | None = None
    label: str | None = None
    authorize_url: str | None = None


class CollabBody(BaseModel):
    snapshot: dict[str, Any] = Field(default_factory=dict)
    name: str | None = None


class AgentPlanBody(BaseModel):
    brief: str = ""


class InitBody(BaseModel):
    demo: bool = False


class SettingsBody(BaseModel):
    preference: str | None = None
    monthly_cap_usd: float | None = None
    require_approval_over: float | None = None
    gsheet_id: str | None = None
    gsheet_tab: str | None = None


class InstallSkillBody(BaseModel):
    path: str


class ComfyImportBody(BaseModel):
    graph: dict[str, Any]
    run: bool = False
    inputs: dict[str, Any] = Field(default_factory=dict)
    max_cost: float | None = None


class AdaptTargetBody(BaseModel):
    preset_id: str | None = None
    width: int | None = None
    height: int | None = None
    prompt: str | None = None


class AdaptEstimateBody(BaseModel):
    source_asset: str
    targets: list[AdaptTargetBody]
    layout: str = "fit_pad_crop"
    model_id: str | None = None


class AdaptRunBody(AdaptEstimateBody):
    fit_mode: str = "fit"
    max_cost: float | None = None


class PresetByteCapBody(BaseModel):
    max_bytes: int
    op: str = "lte"


class PresetMarginsBody(BaseModel):
    left: int = 0
    right: int = 0
    top: int = 0
    bottom: int = 0


class PresetCreateBody(BaseModel):
    id: str | None = None
    label: str
    partner: str | None = None
    platform: str | None = None
    width: int
    height: int
    byte_cap: PresetByteCapBody | None = None
    safe_rect_margins_px: PresetMarginsBody | None = None


class BatchItemBody(BaseModel):
    asset_id: str | None = None
    source_url: str | None = None
    preset_ids: list[str]


class BatchBody(BaseModel):
    items: list[BatchItemBody]
    fit_mode: str = "pad"
    layout: str = "fit_pad_crop"


def _oauth_redirect_uri(request: Request) -> str:
    """Callback URL for provider sign-in.

    A configured public origin wins. Otherwise only loopback (and the test
    client host) may supply the host, so a forged Host header cannot receive
    the authorization code.
    """
    configured = os.environ.get("VINCI_PUBLIC_BASE_URL", "").strip().rstrip("/")
    if configured:
        base = configured
    else:
        host = (request.url.hostname or "").lower()
        if host not in _OAUTH_LOOPBACK_HOSTS:
            raise HTTPException(
                status_code=400,
                detail="set VINCI_PUBLIC_BASE_URL before starting OAuth on a public host",
            )
        base = str(request.base_url).rstrip("/")
    return f"{base}/providers/oauth/callback"


def create_app(engine: Engine | None = None, sheets_client: Any | None = None) -> FastAPI:
    persistence = None
    journal = None
    journal_token = None
    heartbeat: JournalWriterHeartbeat | None = None
    if engine is None:
        journal_token = None
        persistence_lock_held = False
        home_path = Path(os.environ.get("VINCI_HOME", str(default_home()))).expanduser()
        try:
            journal = journal_from_env(home_path)
        except JournalConfigError as exc:
            raise RuntimeError(str(exc)) from exc
        persistence = persistence_from_env(home_path)
        try:
            if persistence is not None and journal is None:
                persistence.acquire_lock()
                persistence_lock_held = True
                persistence.restore_if_present()
            elif persistence is not None and journal is not None:
                # Compaction-only; acknowledged metadata comes from the durable ledger.
                persistence.acquire_lock()
                persistence_lock_held = True
            if journal is not None:
                journal_token = journal.acquire_writer()
            eng = Engine(home=home_path)
            eng._journal = journal  # noqa: SLF001 — outbox output receipts
            eng._journal_token = journal_token  # noqa: SLF001
            if journal is not None and journal_token is not None:

                def _receipt_hook(run_id: str, run_body: dict[str, Any], parent_op_id: str) -> None:
                    commit_run_receipt_before_complete(
                        journal,
                        eng,
                        parent_op_id=parent_op_id,
                        run_id=run_id,
                        run_body=run_body,
                    )

                eng._commit_run_receipt_hook = _receipt_hook  # noqa: SLF001
                if os.environ.get("VINCI_TEST_DISABLE_HEARTBEAT") != "1":
                    heartbeat = JournalWriterHeartbeat(journal, journal_token, eng)
                    attach_heartbeat(eng, heartbeat)
                    heartbeat.start()
                reconcile_pending_outbox(journal, eng)
            elif persistence is not None:
                eng.recover_interrupted_jobs()
        except Exception:
            if heartbeat is not None:
                heartbeat.stop()
            if journal is not None and journal_token is not None:
                try:
                    release_tok = heartbeat.token if heartbeat is not None else journal_token
                    journal.release_writer(release_tok)
                except JournalError:
                    pass
            if persistence_lock_held and persistence is not None:
                try:
                    persistence.release_lock()
                except Exception:  # noqa: BLE001 — best-effort unlock for restart
                    pass
            raise
    else:
        eng = engine
        heartbeat = None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.persistence = persistence
        app.state.journal = journal
        app.state.journal_token = journal_token
        app.state.journal_heartbeat = heartbeat
        snapshot_role = os.environ.get("VINCI_HOME_SNAPSHOT_ROLE", "compact")
        if persistence is not None and snapshot_role == "compact":
            persistence.start_background()
        if os.environ.get("VINCI_EMIT_READY", "") == "1":
            from vinci_daemon.desktop_boot import emit_ready

            port = int(os.environ.get("VINCI_DAEMON_PORT", str(DAEMON_PORT)))
            nonce = os.environ.get("VINCI_READY_NONCE", os.environ.get("VINCI_LAUNCH_NONCE", ""))
            emit_ready(port, nonce)
        yield
        if heartbeat is not None:
            heartbeat.stop()
        if journal is not None and journal_token is not None:
            journal.release_writer(heartbeat.token if heartbeat is not None else journal_token)
        if persistence is not None:
            persistence.stop()

    app = FastAPI(title="vinci-daemon", version="0.1.0", lifespan=lifespan)
    app.state.engine = eng
    app.state.sheets_client = sheets_client
    app.state.persistence = persistence
    app.state.journal = journal
    app.state.journal_token = journal_token
    desktop = os.environ.get("VINCI_DESKTOP", "") == "1"
    selfhost = desktop or os.environ.get("VINCI_SELFHOST", "") == "1" or bool(
        os.environ.get("VINCI_BRIDGE_TOKEN", "").strip()
    )
    if not selfhost:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.add_middleware(JournalHealthMiddleware)
    if journal is None:
        app.add_middleware(PersistenceHealthMiddleware)
    app.add_middleware(BridgeAuthMiddleware)

    @app.get("/")
    def root() -> RedirectResponse:
        return RedirectResponse(url="/studio")

    @app.get("/studio", response_class=HTMLResponse)
    def studio() -> str:
        return STUDIO_HTML.read_text(encoding="utf-8")

    @app.get("/studio/manifest.webmanifest")
    def studio_manifest() -> Response:
        return Response(
            content=json.dumps(STUDIO_MANIFEST),
            media_type="application/manifest+json",
        )

    @app.get("/studio/icon.svg")
    def studio_icon() -> Response:
        return Response(STUDIO_ICON.read_text(encoding="utf-8"), media_type="image/svg+xml")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        journal_state = app.state.journal
        if journal_state is not None and not journal_state.healthy():
            raise HTTPException(status_code=503, detail="journal_unhealthy")
        persistence = app.state.persistence
        if journal_state is None and persistence is not None and not persistence.healthy:
            raise HTTPException(status_code=503, detail="persistence_unhealthy")
        payload: dict[str, str] = {"status": "ok", **eng.handshake()}
        if desktop:
            payload["desktop"] = "1"
            payload["pid"] = str(os.getpid())
            payload["launch_nonce"] = os.environ.get("VINCI_LAUNCH_NONCE", "")
        return payload

    @app.get("/handshake")
    def handshake() -> dict[str, str]:
        return eng.handshake()

    @app.post("/init")
    def init(body: InitBody, request: Request) -> dict[str, Any]:
        return with_journal_ack(
            request,
            method="POST",
            path="/init",
            payload=body.model_dump(),
            blob_keys=[],
            build_response=lambda: eng.init_home(demo=body.demo),
        )

    @app.get("/doctor")
    def doctor() -> dict[str, Any]:
        return eng.doctor()

    @app.get("/settings")
    def get_settings() -> dict[str, Any]:
        return eng.settings()

    @app.patch("/settings")
    def patch_settings(body: SettingsBody, request: Request) -> dict[str, Any]:
        def _apply() -> dict[str, Any]:
            try:
                return eng.update_settings(
                    preference=body.preference,
                    monthly_cap_usd=body.monthly_cap_usd,
                    require_approval_over=body.require_approval_over,
                    gsheet_id=body.gsheet_id,
                    gsheet_tab=body.gsheet_tab,
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

        return with_journal_ack(
            request,
            method="PATCH",
            path="/settings",
            payload=body.model_dump(exclude_none=True),
            blob_keys=[],
            build_response=_apply,
        )

    @app.post("/runs")
    def create_run(body: RunBody, request: Request) -> dict[str, Any]:
        spec = WorkflowSpec.model_validate(body.workflow) if body.workflow else None
        if spec is None and body.workflow_path:
            path = Path(body.workflow_path).expanduser().resolve()
            if not path.is_file():
                raise HTTPException(status_code=400, detail="workflow file not found")
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
            spec = WorkflowSpec.model_validate(loaded)

        op_id = client_operation_id(request)

        def _accept() -> dict[str, Any]:
            try:
                if getattr(eng, "_journal", None) is None:
                    return eng.start_run(
                        body.skill,
                        body.inputs,
                        max_cost=body.max_cost,
                        preference=body.preference,
                        workflow=spec,
                        model_id=body.model_id,
                    )
                return eng.accept_run(
                    body.skill,
                    body.inputs,
                    max_cost=body.max_cost,
                    preference=body.preference,
                    workflow=spec,
                    model_id=body.model_id,
                    operation_id=op_id,
                )
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(status_code=400, detail=f"{type(exc).__name__}: {exc}") from exc

        return with_journal_ack(
            request,
            method="POST",
            path="/runs",
            payload=body.model_dump(exclude_none=True),
            blob_keys=[],
            build_response=_accept,
            operation_id=op_id,
        )

    @app.get("/runs")
    def list_runs() -> dict[str, Any]:
        return {"runs": eng.store.list_runs()}

    @app.get("/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        run = eng.store.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        return run

    @app.post("/runs/{run_id}/approve")
    def approve_run(run_id: str, request: Request) -> dict[str, Any]:
        path = f"/runs/{run_id}/approve"

        def _approve() -> dict[str, Any]:
            try:
                return eng.approve_run(run_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail="run not found") from exc

        return with_journal_ack(
            request,
            method="POST",
            path=path,
            payload={"run_id": run_id},
            blob_keys=[],
            build_response=_approve,
        )

    @app.post("/runs/{run_id}/cancel")
    def cancel_run(run_id: str, request: Request) -> dict[str, Any]:
        path = f"/runs/{run_id}/cancel"

        def _cancel() -> dict[str, Any]:
            try:
                return eng.cancel_run(run_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail="run not found") from exc

        return with_journal_ack(
            request,
            method="POST",
            path=path,
            payload={"run_id": run_id},
            blob_keys=[],
            build_response=_cancel,
        )

    @app.get("/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        job = eng.store.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        return job.model_dump(mode="json")

    @app.get("/events")
    async def events(run_id: str | None = None, sse: bool = Query(default=False)) -> Any:
        if not sse:
            return {"events": eng.store.list_events(run_id)}

        async def gen() -> AsyncIterator[str]:
            last = 0
            idle = 0
            while idle < 50:
                rows = eng.store.list_events(run_id, after_id=last)
                if not rows:
                    idle += 1
                    yield ": keepalive\n\n"
                    await asyncio.sleep(0.05)
                    continue
                idle = 0
                for row in rows:
                    last = int(row["id"])
                    yield f"data: {json.dumps(row, default=str)}\n\n"
                run = eng.store.get_run(run_id) if run_id else None
                if run and run["state"] in {"completed", "failed", "cancelled"}:
                    break

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.get("/find")
    def find(q: str = "", limit: int = 20) -> dict[str, Any]:
        return {"query": q, "hits": eng.find(q, limit=limit)}

    @app.get("/assets")
    def list_assets() -> dict[str, Any]:
        return {"assets": [a.model_dump(mode="json") for a in eng.store.list_assets()]}

    @app.post("/assets")
    async def upload_asset(request: Request, file: UploadFile) -> dict[str, Any]:
        data = await file.read()
        asset = eng.ingest_bytes(
            data, mime=file.content_type or "application/octet-stream", filename=file.filename
        )
        dumped = asset.model_dump(mode="json")
        return with_journal_ack(
            request,
            method="POST",
            path="/assets",
            payload={"filename": file.filename, "bytes": len(data)},
            blob_keys=[str(asset.id)],
            build_response=lambda: dumped,
        )

    @app.get("/assets/{asset_id}")
    def get_asset(asset_id: str) -> dict[str, Any]:
        asset = eng.store.get_asset(asset_id)
        if asset is None:
            raise HTTPException(status_code=404, detail="asset not found")
        return asset.model_dump(mode="json")

    @app.get("/assets/{asset_id}/file")
    def asset_file(asset_id: str, request: Request) -> Response:
        if not eng.cas.exists(asset_id):
            raise HTTPException(status_code=404, detail="asset not found")
        blob = eng.cas.get(asset_id)
        asset = eng.store.get_asset(asset_id)
        mime = asset.mime if asset else "application/octet-stream"
        total = len(blob)
        range_header = request.headers.get("range")
        if range_header and range_header.startswith("bytes="):
            spec = range_header.removeprefix("bytes=").split("-", 1)
            try:
                start = int(spec[0]) if spec[0] else 0
                end = int(spec[1]) if len(spec) > 1 and spec[1] else total - 1
            except ValueError:
                raise HTTPException(status_code=416, detail="invalid range") from None
            end = min(end, total - 1)
            if start > end or start >= total:
                raise HTTPException(status_code=416, detail="range not satisfiable")
            chunk = blob[start : end + 1]
            headers = {
                "Content-Range": f"bytes {start}-{end}/{total}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(len(chunk)),
            }
            return Response(content=chunk, status_code=206, media_type=mime, headers=headers)
        return Response(
            content=blob,
            media_type=mime,
            headers={"Accept-Ranges": "bytes", "Content-Length": str(total)},
        )

    @app.get("/receipts/{job_id}")
    def get_receipt(job_id: str) -> dict[str, Any]:
        receipt = eng.store.get_receipt(job_id)
        if receipt is None:
            raise HTTPException(status_code=404, detail="receipt not found")
        dumped = receipt.model_dump(mode="json")
        return {"uri": f"vinci://receipts/{job_id}", **dumped}

    @app.get("/models")
    def models(
        capability: str | None = None, max_price: float | None = Query(default=None)
    ) -> dict[str, Any]:
        return {
            "protocol_version": PROTOCOL_VERSION,
            "models": eng.models(capability=capability, max_price=max_price),
        }

    @app.get("/skills")
    def skills(q: str | None = None) -> dict[str, Any]:
        hits = eng.skills.search(q or "")
        return {"skills": [eng.skills.inspect(s.id) for s in hits]}

    @app.get("/templates")
    def templates() -> dict[str, Any]:
        return {"templates": eng.templates()}

    @app.get("/templates/{template_id}")
    def get_template_row(template_id: str) -> dict[str, Any]:
        try:
            return get_template(template_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="template not found") from exc

    @app.get("/templates/{template_id}/preview.svg")
    def template_preview(template_id: str) -> Response:
        return Response(preview_svg(template_id), media_type="image/svg+xml")

    @app.post("/skills/install")
    def install_skill(body: InstallSkillBody, request: Request) -> dict[str, Any]:
        def _install() -> dict[str, Any]:
            try:
                return eng.install_skill(body.path)
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(status_code=400, detail=f"{type(exc).__name__}: {exc}") from exc

        return with_journal_ack(
            request,
            method="POST",
            path="/skills/install",
            payload=body.model_dump(),
            blob_keys=[],
            build_response=_install,
        )

    @app.post("/workflows/import/comfy")
    def import_comfy(body: ComfyImportBody, request: Request) -> dict[str, Any]:
        def _import() -> dict[str, Any]:
            try:
                spec = eng.import_comfy_graph(body.graph)
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(status_code=400, detail=f"{type(exc).__name__}: {exc}") from exc
            if not body.run:
                return {"workflow": spec.model_dump(mode="json")}
            try:
                return eng.start_run(
                    None,
                    body.inputs,
                    max_cost=body.max_cost,
                    workflow=spec,
                )
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(status_code=400, detail=f"{type(exc).__name__}: {exc}") from exc

        return with_journal_ack(
            request,
            method="POST",
            path="/workflows/import/comfy",
            payload=body.model_dump(exclude_none=True),
            blob_keys=[],
            build_response=_import,
        )

    @app.get("/cost/report")
    def cost_report(by: str = "provider") -> dict[str, Any]:
        return eng.cost_report(by=by)

    @app.get("/adapt/presets")
    def adapt_presets() -> dict[str, Any]:
        return {"presets": eng.adapt_presets()}

    @app.post("/adapt/estimate")
    def adapt_estimate(body: AdaptEstimateBody) -> dict[str, Any]:
        try:
            return eng.estimate_adapt(
                source_asset=body.source_asset,
                targets=[t.model_dump(exclude_none=True) for t in body.targets],
                layout=body.layout,
                model_id=body.model_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/adapt/run")
    def adapt_run(body: AdaptRunBody, request: Request) -> dict[str, Any]:
        op_id = client_operation_id(request)

        def _run() -> dict[str, Any]:
            try:
                return eng.run_adapt(
                    source_asset=body.source_asset,
                    targets=[t.model_dump(exclude_none=True) for t in body.targets],
                    layout=body.layout,
                    fit_mode=body.fit_mode,
                    model_id=body.model_id,
                    max_cost=body.max_cost,
                    receipt_parent_op_id=op_id,
                )
            except PermissionError as exc:
                raise HTTPException(status_code=403, detail=str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc

        blob_keys = [body.source_asset] if body.source_asset else []
        return with_journal_ack(
            request,
            method="POST",
            path="/adapt/run",
            payload=body.model_dump(exclude_none=True),
            blob_keys=blob_keys,
            build_response=_run,
            operation_id=op_id,
        )

    @app.get("/presets")
    def list_presets() -> dict[str, Any]:
        return {"presets": eng.adapt_presets()}

    @app.post("/presets")
    def create_preset(body: PresetCreateBody, request: Request) -> dict[str, Any]:
        def _create() -> dict[str, Any]:
            try:
                preset = eng.save_custom_preset(body.model_dump(exclude_none=True))
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            return {"preset": preset}

        return with_journal_ack(
            request,
            method="POST",
            path="/presets",
            payload=body.model_dump(exclude_none=True),
            blob_keys=[],
            build_response=_create,
        )

    @app.delete("/presets/{preset_id}")
    def delete_preset(preset_id: str, request: Request) -> dict[str, Any]:
        def _delete() -> dict[str, Any]:
            try:
                eng.remove_custom_preset(preset_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail="preset not found") from exc
            return {"deleted": preset_id}

        return with_journal_ack(
            request,
            method="DELETE",
            path=f"/presets/{preset_id}",
            payload={"preset_id": preset_id},
            blob_keys=[],
            build_response=_delete,
        )

    @app.post("/adapts/batch")
    def create_adapt_batch(body: BatchBody, request: Request) -> dict[str, Any]:
        batch_op_id = client_operation_id(request)

        def _batch() -> dict[str, Any]:
            try:
                return eng.start_adapt_batch(
                    [item.model_dump(exclude_none=True) for item in body.items],
                    fit_mode=body.fit_mode,
                    layout=body.layout,
                    operation_id=batch_op_id,
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc

        asset_ids = [str(i.asset_id) for i in body.items if i.asset_id]
        return with_journal_ack(
            request,
            method="POST",
            path="/adapts/batch",
            payload=body.model_dump(exclude_none=True),
            blob_keys=asset_ids,
            build_response=_batch,
            operation_id=batch_op_id,
        )

    @app.get("/adapts/batch/{batch_id}/bundle.zip")
    def adapt_batch_bundle(batch_id: str) -> Response:
        try:
            data = eng.adapt_batch_bundle(batch_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="batch not found") from exc
        return Response(
            content=data,
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="bundle.zip"'},
        )

    @app.get("/adapts/batch/{batch_id}")
    def adapt_batch_status(batch_id: str) -> dict[str, Any]:
        try:
            return eng.adapt_batch_status(batch_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="batch not found") from exc

    @app.post("/integrations/gsheet/sync")
    def gsheet_sync(request: Request) -> dict[str, Any]:
        path = "/integrations/gsheet/sync"
        from vinci_runtime.sheets import sync_sheet

        from vinci_daemon.gsheet_live import SheetsConfigError, build_live_sheet_client

        settings = eng.settings()
        if not settings.get("gsheet_id") or not settings.get("gsheet_tab"):
            raise HTTPException(
                status_code=501,
                detail=(
                    "Google Sheet sync is not configured: set gsheet_id and gsheet_tab "
                    "via PATCH /settings."
                ),
            )
        client = app.state.sheets_client
        if client is None:
            try:
                client = build_live_sheet_client()
            except SheetsConfigError as exc:
                raise HTTPException(status_code=501, detail=str(exc)) from exc
        def _sync() -> dict[str, Any]:
            try:
                return sync_sheet(
                    eng,
                    client,
                    sheet_id=str(settings["gsheet_id"]),
                    tab=str(settings["gsheet_tab"]),
                    public_base=str(request.base_url).rstrip("/"),
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc

        return with_journal_ack(
            request,
            method="POST",
            path=path,
            payload={"gsheet_id": settings.get("gsheet_id"), "tab": settings.get("gsheet_tab")},
            blob_keys=[],
            build_response=_sync,
        )

    @app.get("/providers")
    def providers() -> dict[str, Any]:
        return eng.doctor()["providers"]

    @app.post("/providers")
    def add_provider(body: ProviderBody, request: Request) -> dict[str, Any]:
        def _add() -> dict[str, Any]:
            try:
                return eng.add_provider(
                    body.id,
                    from_env=body.from_env,
                    secret=body.secret,
                    extra_secret=body.extra_secret,
                    extra_from_env=body.extra_from_env,
                    url=body.url,
                    account_id=body.account_id,
                    label=body.label,
                    authorize_url=body.authorize_url,
                )
            except KeyError as exc:
                raise HTTPException(status_code=404, detail="unknown provider") from exc
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

        return with_journal_ack(
            request,
            method="POST",
            path="/providers",
            payload={"id": body.id},
            blob_keys=[],
            build_response=_add,
        )

    @app.delete("/providers/{name}")
    def delete_provider(name: str, request: Request) -> dict[str, str]:
        def _remove() -> dict[str, str]:
            eng.remove_provider(name)
            return {"removed": name}

        return with_journal_ack(
            request,
            method="DELETE",
            path=f"/providers/{name}",
            payload={"name": name},
            blob_keys=[],
            build_response=_remove,
        )

    @app.post("/providers/{name}/oauth")
    def oauth_start(name: str, request: Request) -> dict[str, Any]:
        def _oauth() -> dict[str, Any]:
            redirect_uri = _oauth_redirect_uri(request)
            try:
                return eng.oauth_start(name, redirect_uri)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail="unknown provider") from exc
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

        return with_journal_ack(
            request,
            method="POST",
            path=f"/providers/{name}/oauth",
            payload={"name": name},
            blob_keys=[],
            build_response=_oauth,
        )

    @app.post("/providers/{name}/disconnect")
    def oauth_disconnect(name: str, request: Request) -> dict[str, Any]:
        def _drop() -> dict[str, str]:
            try:
                return eng.disconnect_oauth(name)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail="unknown provider") from exc

        return with_journal_ack(
            request,
            method="POST",
            path=f"/providers/{name}/disconnect",
            payload={"name": name},
            blob_keys=[],
            build_response=_drop,
        )

    @app.get("/providers/oauth/callback", response_class=HTMLResponse)
    def oauth_callback(
        request: Request,
        code: str = "",
        state: str = "",
        error: str = "",
    ) -> HTMLResponse:
        from vinci_mcp.oauth import callback_block_reason, discard_pending

        blocked = callback_block_reason(state)
        if error:
            discard_pending(state)
            blocked = blocked or "authorization was denied"
        if blocked:
            page = (
                "<!doctype html><meta charset=utf-8><title>Vinci</title>"
                f"<p>{html.escape(blocked)}</p>"
            )
            return HTMLResponse(page, status_code=400)

        def _finish() -> dict[str, Any]:
            try:
                return eng.oauth_callback(code=code, state=state, error=error)
            except ValueError as exc:
                return {"ok": False, "detail": str(exc)}

        body = with_journal_ack(
            request,
            method="GET",
            path="/providers/oauth/callback",
            payload={"has_code": bool(code), "has_state": bool(state)},
            blob_keys=[],
            build_response=_finish,
        )
        if body.get("ok"):
            message = "Connected. You can close this tab."
        else:
            message = str(body.get("detail") or "Sign-in failed.")
        page = (
            "<!doctype html><meta charset=utf-8><title>Vinci</title>"
            f"<p>{html.escape(message)}</p>"
        )
        return HTMLResponse(page)

    @app.post("/agent/plan")
    def agent_plan(body: AgentPlanBody) -> dict[str, Any]:
        return eng.plan_brief(body.brief)

    @app.get("/collab/sessions")
    def collab_list() -> dict[str, Any]:
        return {"sessions": eng.collab_list()}

    @app.post("/collab/sessions")
    def collab_create(body: CollabBody, request: Request) -> dict[str, Any]:
        return with_journal_ack(
            request,
            method="POST",
            path="/collab/sessions",
            payload=body.model_dump(exclude_none=True),
            blob_keys=[],
            build_response=lambda: eng.collab_create(body.name),
        )

    @app.get("/collab/sessions/{sid}")
    def collab_get(sid: str) -> dict[str, Any]:
        try:
            return eng.collab_get(sid)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="session not found") from exc

    @app.put("/collab/sessions/{sid}")
    def collab_put(sid: str, body: CollabBody, request: Request) -> dict[str, Any]:
        return with_journal_ack(
            request,
            method="PUT",
            path=f"/collab/sessions/{sid}",
            payload={"sid": sid, "name": body.name},
            blob_keys=[],
            build_response=lambda: eng.collab_put(sid, body.snapshot, body.name),
        )

    @app.post("/catalog/refresh")
    def catalog_refresh(request: Request) -> dict[str, Any]:
        return with_journal_ack(
            request,
            method="POST",
            path="/catalog/refresh",
            payload={},
            blob_keys=[],
            build_response=lambda: eng.catalog_refresh(),
        )

    @app.get("/jobs")
    def list_jobs() -> dict[str, Any]:
        return {"jobs": [j.model_dump(mode="json") for j in eng.store.list_jobs()]}

    @app.post("/mcp")
    async def mcp(request: Request) -> dict[str, Any]:
        message = await request.json()
        from vinci_storage.journal_payload import mcp_ledger_payload, mcp_operation_id_suffix

        ledger_payload = mcp_ledger_payload(message)
        op_suffix = mcp_operation_id_suffix(message)
        base_op = request.headers.get("x-vinci-operation-id", "").strip()
        mcp_op_id = f"{base_op}:{op_suffix}" if base_op else None

        durable_op = mcp_op_id or base_op or client_operation_id(request)

        def _rpc() -> dict[str, Any]:
            result = handle_rpc(eng, message, operation_id=durable_op)
            return result or {}

        return with_journal_ack(
            request,
            method="POST",
            path="/mcp",
            payload=ledger_payload,
            blob_keys=[],
            build_response=_rpc,
            operation_id=durable_op,
        )

    @app.get("/mcp")
    def mcp_info() -> dict[str, Any]:
        from vinci_mcp.server import TOOL_NAMES, tool_schemas

        return {"name": "vinci", "tools": list(TOOL_NAMES), "schemas": tool_schemas()}

    return app


def main() -> None:
    from vinci_daemon.desktop_boot import configure_desktop
    from vinci_daemon.home_lock import acquire_home_daemon_lock, release_home_daemon_lock

    parser = argparse.ArgumentParser(prog="vinci-daemon")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("VINCI_DAEMON_PORT", DAEMON_PORT)),
        help="TCP port; 0 picks a free loopback port",
    )
    parser.add_argument(
        "--desktop",
        action="store_true",
        help="Desktop bundle mode: scoped CORS, healthz-only auth bypass",
    )
    parser.add_argument("--parent-pid", type=int, default=0, help="Exit when parent process dies")
    parser.add_argument("--launch-nonce", default="", help="Per-launch nonce echoed on /healthz")
    args = parser.parse_args()
    if args.desktop:
        if not os.environ.get("VINCI_BRIDGE_TOKEN", "").strip():
            raise SystemExit("desktop mode requires VINCI_BRIDGE_TOKEN")
        configure_desktop(args.launch_nonce, args.parent_pid)
        os.environ["VINCI_EMIT_READY"] = "1"
        os.environ["VINCI_READY_NONCE"] = args.launch_nonce
    home_path = Path(os.environ.get("VINCI_HOME", str(default_home()))).expanduser()
    acquire_home_daemon_lock(home_path)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    bind_port = args.port if args.port != 0 else 0
    sock.bind((args.host, bind_port))
    port = int(sock.getsockname()[1])
    os.environ["VINCI_DAEMON_PORT"] = str(port)
    import uvicorn

    config = uvicorn.Config(
        "vinci_daemon.app:create_app",
        host=args.host,
        port=port,
        factory=True,
        log_level=os.environ.get("VINCI_LOG_LEVEL", "info"),
    )
    server = uvicorn.Server(config)
    try:
        server.run(sockets=[sock])
    finally:
        release_home_daemon_lock()


if __name__ == "__main__":
    main()
