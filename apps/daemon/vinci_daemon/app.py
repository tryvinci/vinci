from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from vinci_core.templates import get_template, preview_svg
from vinci_mcp.server import handle_rpc
from vinci_protocol.constants import PROTOCOL_VERSION
from vinci_protocol.models import WorkflowSpec
from vinci_runtime.engine import Engine

DAEMON_PORT = 4310
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


def create_app(engine: Engine | None = None, sheets_client: Any | None = None) -> FastAPI:
    eng = engine or Engine()
    app = FastAPI(title="vinci-daemon", version="0.1.0")
    app.state.engine = eng
    app.state.sheets_client = sheets_client
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

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
        return {"status": "ok", **eng.handshake()}

    @app.get("/handshake")
    def handshake() -> dict[str, str]:
        return eng.handshake()

    @app.post("/init")
    def init(body: InitBody) -> dict[str, Any]:
        return eng.init_home(demo=body.demo)

    @app.get("/doctor")
    def doctor() -> dict[str, Any]:
        return eng.doctor()

    @app.get("/settings")
    def get_settings() -> dict[str, Any]:
        return eng.settings()

    @app.patch("/settings")
    def patch_settings(body: SettingsBody) -> dict[str, Any]:
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

    @app.post("/runs")
    def create_run(body: RunBody) -> dict[str, Any]:
        spec = WorkflowSpec.model_validate(body.workflow) if body.workflow else None
        if spec is None and body.workflow_path:
            path = Path(body.workflow_path).expanduser().resolve()
            if not path.is_file():
                raise HTTPException(status_code=400, detail="workflow file not found")
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
            spec = WorkflowSpec.model_validate(loaded)
        try:
            return eng.start_run(
                body.skill,
                body.inputs,
                max_cost=body.max_cost,
                preference=body.preference,
                workflow=spec,
                model_id=body.model_id,
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"{type(exc).__name__}: {exc}") from exc

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
    def approve_run(run_id: str) -> dict[str, Any]:
        try:
            return eng.approve_run(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc

    @app.post("/runs/{run_id}/cancel")
    def cancel_run(run_id: str) -> dict[str, Any]:
        try:
            return eng.cancel_run(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc

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
    async def upload_asset(file: UploadFile) -> dict[str, Any]:
        data = await file.read()
        asset = eng.ingest_bytes(
            data, mime=file.content_type or "application/octet-stream", filename=file.filename
        )
        return asset.model_dump(mode="json")

    @app.get("/assets/{asset_id}")
    def get_asset(asset_id: str) -> dict[str, Any]:
        asset = eng.store.get_asset(asset_id)
        if asset is None:
            raise HTTPException(status_code=404, detail="asset not found")
        return asset.model_dump(mode="json")

    @app.get("/assets/{asset_id}/file")
    def asset_file(asset_id: str) -> Response:
        if not eng.cas.exists(asset_id):
            raise HTTPException(status_code=404, detail="asset not found")
        blob = eng.cas.get(asset_id)
        asset = eng.store.get_asset(asset_id)
        mime = asset.mime if asset else "application/octet-stream"
        return Response(content=blob, media_type=mime)

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
    def install_skill(body: InstallSkillBody) -> dict[str, Any]:
        try:
            return eng.install_skill(body.path)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"{type(exc).__name__}: {exc}") from exc

    @app.post("/workflows/import/comfy")
    def import_comfy(body: ComfyImportBody) -> dict[str, Any]:
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
    def adapt_run(body: AdaptRunBody) -> dict[str, Any]:
        try:
            return eng.run_adapt(
                source_asset=body.source_asset,
                targets=[t.model_dump(exclude_none=True) for t in body.targets],
                layout=body.layout,
                fit_mode=body.fit_mode,
                model_id=body.model_id,
                max_cost=body.max_cost,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc

    @app.get("/presets")
    def list_presets() -> dict[str, Any]:
        return {"presets": eng.adapt_presets()}

    @app.post("/presets")
    def create_preset(body: PresetCreateBody) -> dict[str, Any]:
        try:
            preset = eng.save_custom_preset(body.model_dump(exclude_none=True))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"preset": preset}

    @app.delete("/presets/{preset_id}")
    def delete_preset(preset_id: str) -> dict[str, Any]:
        try:
            eng.remove_custom_preset(preset_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="preset not found") from exc
        return {"deleted": preset_id}

    @app.post("/adapts/batch")
    def create_adapt_batch(body: BatchBody) -> dict[str, Any]:
        try:
            return eng.start_adapt_batch(
                [item.model_dump(exclude_none=True) for item in body.items],
                fit_mode=body.fit_mode,
                layout=body.layout,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc

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

    @app.get("/providers")
    def providers() -> dict[str, Any]:
        return eng.doctor()["providers"]

    @app.post("/providers")
    def add_provider(body: ProviderBody) -> dict[str, Any]:
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

    @app.delete("/providers/{name}")
    def delete_provider(name: str) -> dict[str, str]:
        eng.remove_provider(name)
        return {"removed": name}

    @app.post("/providers/{name}/oauth")
    def oauth_start(name: str) -> dict[str, Any]:
        try:
            return eng.oauth_start(name)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="unknown provider") from exc

    @app.post("/agent/plan")
    def agent_plan(body: AgentPlanBody) -> dict[str, Any]:
        return eng.plan_brief(body.brief)

    @app.get("/collab/sessions")
    def collab_list() -> dict[str, Any]:
        return {"sessions": eng.collab_list()}

    @app.post("/collab/sessions")
    def collab_create(body: CollabBody) -> dict[str, Any]:
        return eng.collab_create(body.name)

    @app.get("/collab/sessions/{sid}")
    def collab_get(sid: str) -> dict[str, Any]:
        try:
            return eng.collab_get(sid)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="session not found") from exc

    @app.put("/collab/sessions/{sid}")
    def collab_put(sid: str, body: CollabBody) -> dict[str, Any]:
        return eng.collab_put(sid, body.snapshot, body.name)

    @app.post("/catalog/refresh")
    def catalog_refresh() -> dict[str, Any]:
        return eng.catalog_refresh()

    @app.get("/jobs")
    def list_jobs() -> dict[str, Any]:
        return {"jobs": [j.model_dump(mode="json") for j in eng.store.list_jobs()]}

    @app.post("/mcp")
    async def mcp(request: Request) -> dict[str, Any]:
        message = await request.json()
        result = handle_rpc(eng, message)
        return result or {}

    @app.get("/mcp")
    def mcp_info() -> dict[str, Any]:
        from vinci_mcp.server import TOOL_NAMES, tool_schemas

        return {"name": "vinci", "tools": list(TOOL_NAMES), "schemas": tool_schemas()}

    return app


def main() -> None:
    parser = argparse.ArgumentParser(prog="vinci-daemon")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("VINCI_DAEMON_PORT", DAEMON_PORT))
    )
    args = parser.parse_args()
    import uvicorn

    uvicorn.run("vinci_daemon.app:create_app", host=args.host, port=args.port, factory=True)


if __name__ == "__main__":
    main()
