from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from vinci_protocol.constants import PROTOCOL_VERSION
from vinci_protocol.enums import (
    AssetKind,
    AssetSource,
    Capability,
    ErrorCode,
    JobState,
    ModelStatus,
    NodeType,
    RoutePreference,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Provenance(StrictModel):
    skill: str | None = None
    model_id: str | None = None


class Asset(StrictModel):
    id: str
    kind: AssetKind
    mime: str
    bytes: int = Field(ge=0)
    width: int | None = None
    height: int | None = None
    duration: float | None = None
    source: AssetSource
    parent_ids: list[str] = Field(default_factory=list)
    created_by: Provenance | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    uri: str | None = None

    @field_validator("uri")
    @classmethod
    def uri_scheme(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith("vinci://assets/"):
            raise ValueError("asset uri must use vinci://assets/{id}")
        return value


class Pricing(StrictModel):
    unit: str
    amount: float = Field(ge=0)
    currency: str = "USD"
    snapshot_at: datetime


class ModelConstraints(StrictModel):
    aspect_ratios: list[str] = Field(default_factory=list)
    max_duration: float | None = None
    resolutions: list[str] = Field(default_factory=list)
    max_input_images: int | None = None


class ModelSpec(StrictModel):
    id: str
    display_name: str
    provider: str
    capabilities: list[Capability]
    constraints: ModelConstraints = Field(default_factory=ModelConstraints)
    pricing: Pricing
    quality_tier: str = "fast"
    status: ModelStatus = ModelStatus.ACTIVE
    secret_names: list[str] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def id_shape(cls, value: str) -> str:
        parts = value.split(":")
        if len(parts) < 2:
            raise ValueError("model id must be provider:model[:version]")
        return value

    @field_validator("id")
    @classmethod
    def no_sora_default(cls, value: str) -> str:
        # Catalog entries may exist as sunset later; default allowlists must not add sora.
        return value


class VinciError(StrictModel):
    code: ErrorCode
    message: str
    provider: str | None = None
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)

    @field_validator("details")
    @classmethod
    def no_secret_keys(cls, value: dict[str, Any]) -> dict[str, Any]:
        banned = {"api_key", "secret", "token", "authorization", "password"}
        lowered = {str(k).lower() for k in value}
        if banned & lowered:
            raise ValueError("error details must not include secret field names")
        return value


class Estimate(StrictModel):
    model_id: str
    provider: str
    amount: float = Field(ge=0)
    currency: str = "USD"
    unit: str
    unit_count: float = 1
    pricing_snapshot_at: datetime
    alternative: dict[str, Any] | None = None
    cached: bool = False


class Receipt(StrictModel):
    job_id: str
    model_id: str
    provider: str
    list_price: float = Field(ge=0)
    unit_count: float
    computed_cost: float = Field(ge=0)
    currency: str = "USD"
    pricing_snapshot_at: datetime
    retries_cost: float = 0
    wall_time: float = 0
    cached: bool = False


class JobTimings(StrictModel):
    created_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class Job(StrictModel):
    id: str
    workflow_run_id: str | None = None
    node_id: str | None = None
    model_id: str
    provider_job_ref: str | None = None
    state: JobState
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: list[str] = Field(default_factory=list)
    estimate: Estimate | None = None
    receipt: Receipt | None = None
    error: VinciError | None = None
    timings: JobTimings = Field(default_factory=JobTimings)
    retries: int = 0
    idempotency_key: str | None = None
    protocol_version: str = PROTOCOL_VERSION


class JobRequest(StrictModel):
    capability: Capability
    model_id: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = None
    max_cost: float | None = None
    preference: RoutePreference = RoutePreference.CHEAPEST


class ProviderJobRef(StrictModel):
    provider: str
    ref: str
    extra: dict[str, Any] = Field(default_factory=dict)


class JobStatus(StrictModel):
    state: JobState
    outputs: list[str] = Field(default_factory=list)
    error: VinciError | None = None
    progress: float | None = Field(default=None, ge=0, le=1)


class WorkflowNode(StrictModel):
    id: str
    type: NodeType
    capability: Capability | None = None
    model_id: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    budget_hint: float | None = None


class WorkflowEdge(StrictModel):
    src: str
    dst: str
    input_key: str | None = None


class WorkflowSpec(StrictModel):
    id: str
    version: str
    nodes: list[WorkflowNode]
    edges: list[WorkflowEdge] = Field(default_factory=list)
    preference: RoutePreference = RoutePreference.CHEAPEST
    max_cost: float | None = None


class Event(StrictModel):
    type: str
    job_id: str | None = None
    run_id: str | None = None
    created_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)


class ProviderAuth(StrictModel):
    env_vars: list[str] = Field(default_factory=list)
    docs_url: str | None = None


class ProviderManifest(StrictModel):
    id: str
    display_name: str
    auth: ProviderAuth = Field(default_factory=ProviderAuth)
    docs_url: str | None = None


class Handshake(StrictModel):
    protocol_version: str = PROTOCOL_VERSION
    daemon_version: str | None = None


class TimelineClip(StrictModel):
    asset_id: str
    start: float = Field(default=0, ge=0)
    end: float | None = None
    track: str = "v0"


class Timeline(StrictModel):
    id: str
    clips: list[TimelineClip]
    fps: float | None = None
    width: int | None = None
    height: int | None = None
