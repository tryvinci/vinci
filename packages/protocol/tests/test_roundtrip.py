from __future__ import annotations

from datetime import UTC, datetime

import jsonschema
from vinci_protocol import (
    PROTOCOL_VERSION,
    Asset,
    AssetKind,
    AssetSource,
    Capability,
    ErrorCode,
    Estimate,
    Event,
    Job,
    JobState,
    ModelSpec,
    Receipt,
    Timeline,
    VinciError,
    WorkflowSpec,
    load_schema,
)


def _now() -> datetime:
    return datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


def _validate(name: str, payload: dict[str, object]) -> None:
    schema = load_schema(name)
    jsonschema.validate(instance=payload, schema=schema, format_checker=jsonschema.FormatChecker())


def test_asset_roundtrip() -> None:
    asset = Asset(
        id="ab" * 32,
        kind=AssetKind.IMAGE,
        mime="image/png",
        bytes=68,
        width=1,
        height=1,
        source=AssetSource.GENERATED,
        created_at=_now(),
        uri="vinci://assets/" + "ab" * 32,
        created_by={"skill": "image-generate@0.1.0", "model_id": "mock:png:v1"},
    )
    payload = asset.model_dump(mode="json")
    _validate("asset", payload)
    assert Asset.model_validate(payload).id == asset.id


def test_model_spec_roundtrip() -> None:
    spec = ModelSpec(
        id="mock:png:v1",
        display_name="Mock PNG",
        provider="mock",
        capabilities=[Capability.T2I],
        pricing={
            "unit": "image",
            "amount": 0.0,
            "currency": "USD",
            "snapshot_at": _now(),
        },
        secret_names=["MOCK_API_KEY"],
    )
    payload = spec.model_dump(mode="json")
    _validate("model_spec", payload)
    assert ModelSpec.model_validate(payload).id == "mock:png:v1"


def test_job_receipt_error_workflow_event() -> None:
    estimate = Estimate(
        model_id="mock:png:v1",
        provider="mock",
        amount=0.0,
        currency="USD",
        unit="image",
        unit_count=1,
        pricing_snapshot_at=_now(),
    )
    receipt = Receipt(
        job_id="job_1",
        model_id="mock:png:v1",
        provider="mock",
        list_price=0.0,
        unit_count=1,
        computed_cost=0.0,
        currency="USD",
        pricing_snapshot_at=_now(),
        cached=True,
    )
    job = Job(
        id="job_1",
        model_id="mock:png:v1",
        state=JobState.COMPLETED,
        estimate=estimate,
        receipt=receipt,
        protocol_version=PROTOCOL_VERSION,
    )
    _validate("job", job.model_dump(mode="json"))
    _validate("receipt", receipt.model_dump(mode="json"))
    err = VinciError(code=ErrorCode.AUTH, message="missing key", retryable=False)
    _validate("error", err.model_dump(mode="json"))
    wf = WorkflowSpec(
        id="@tryvinci/image-generate",
        version="0.1.0",
        nodes=[{"id": "gen", "type": "generate", "capability": "t2i"}],
    )
    _validate("workflow", wf.model_dump(mode="json"))
    event = Event(type="job.completed", job_id="job_1", created_at=_now())
    _validate("event", event.model_dump(mode="json"))


def test_timeline_roundtrip() -> None:
    timeline = Timeline(
        id="tl_1",
        clips=[
            {"asset_id": "clip-a", "start": 0, "end": 1.5, "track": "v0"},
            {"asset_id": "clip-b", "start": 0, "end": None, "track": "v0"},
        ],
        fps=24,
        width=720,
        height=1280,
    )
    payload = timeline.model_dump(mode="json")
    _validate("timeline", payload)
    assert Timeline.model_validate(payload).id == "tl_1"


def test_error_rejects_secret_fields() -> None:
    try:
        VinciError(code=ErrorCode.AUTH, message="x", details={"api_key": "secret"})
    except Exception:
        return
    raise AssertionError("expected secret field rejection")
