from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

from vinci_core.catalog import Catalog, load_bundled_catalog
from vinci_core.cost import estimate_from_spec, idempotency_key, resolve_model
from vinci_core.paths import allow_live_spend
from vinci_core.redact import redact_mapping
from vinci_protocol.enums import Capability, ErrorCode, JobState
from vinci_protocol.models import (
    Estimate,
    JobRequest,
    JobStatus,
    ModelSpec,
    ProviderJobRef,
    VinciError,
)

from vinci_provider_sdk.base import Provider
from vinci_provider_sdk.shot import compose_shot_prompt

log = logging.getLogger("vinci.provider")


class LiveSpendDisabled(RuntimeError):
    """Raised when submit would call a paid API but live spend is off."""


class CatalogBackedProvider(Provider):
    """Estimate from a checked-in catalog snapshot. Live HTTP is opt-in."""

    durable_job_reconciliation: bool = False
    catalog_name: str = ""
    provider_id: str = ""
    secret_name: str = ""

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key
        self._extra_secrets: dict[str, str] = {}
        self._catalog: Catalog = load_bundled_catalog(self.catalog_name)
        self._estimated: set[str] = set()
        self._jobs: dict[str, JobStatus] = {}

    def _secret_values(self) -> list[str]:
        values = [self._api_key] if self._api_key else []
        values.extend(value for value in self._extra_secrets.values() if value)
        return values

    def catalog(self) -> list[ModelSpec]:
        return list(self._catalog.models)

    def capabilities(self) -> set[Capability]:
        caps: set[Capability] = set()
        for model in self._catalog.models:
            caps.update(model.capabilities)
        return caps

    def estimate(self, req: JobRequest) -> Estimate:
        spec = resolve_model(self._catalog, req)
        key = req.idempotency_key or idempotency_key(spec.id, req.inputs)
        self._estimated.add(key)
        estimate = estimate_from_spec(spec)
        log.info(
            "estimate provider=%s model=%s amount=%s", self.provider_id, spec.id, estimate.amount
        )
        return estimate

    def submit(self, req: JobRequest) -> ProviderJobRef:
        spec = resolve_model(self._catalog, req)
        key = req.idempotency_key or idempotency_key(spec.id, req.inputs)
        if key not in self._estimated:
            raise RuntimeError("estimate() must be called before submit()")
        log.info(
            "submit provider=%s model=%s inputs=%s",
            self.provider_id,
            spec.id,
            redact_mapping(req.inputs, extra_values=self._secret_values()),
        )
        if not self._api_key:
            raise PermissionError(f"missing {self.secret_name}")
        if not allow_live_spend():
            raise LiveSpendDisabled(
                "live provider spend is disabled; set VINCI_ALLOW_LIVE_SPEND=1 to enable"
            )
        return self._submit_live(req, spec)

    def status(self, ref: ProviderJobRef) -> JobStatus:
        cached = self._jobs.get(ref.ref)
        if cached is not None and cached.state in {
            JobState.COMPLETED,
            JobState.FAILED,
            JobState.CANCELLED,
        }:
            return cached
        live = self._status_live(ref)
        if live is not None:
            if live.state in {JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED}:
                self._jobs[ref.ref] = live
            return live
        if cached is not None:
            return cached
        return JobStatus(
            state=JobState.FAILED,
            error=VinciError(code=ErrorCode.UNKNOWN, message="unknown job"),
        )

    def cancel(self, ref: ProviderJobRef) -> None:
        current = self._jobs.get(ref.ref)
        if current is not None:
            self._jobs[ref.ref] = JobStatus(state=JobState.CANCELLED)

    def normalize_error(self, exc: BaseException) -> VinciError:
        if isinstance(exc, PermissionError):
            return VinciError(code=ErrorCode.AUTH, message="auth failed", retryable=False)
        if isinstance(exc, TimeoutError):
            return VinciError(code=ErrorCode.TIMEOUT, message="timeout", retryable=True)
        if isinstance(exc, LiveSpendDisabled):
            return VinciError(code=ErrorCode.UNKNOWN, message=str(exc), retryable=False)
        if isinstance(exc, ValueError):
            return VinciError(code=ErrorCode.INVALID_INPUT, message=str(exc), retryable=False)
        if isinstance(exc, urllib.error.HTTPError):
            if exc.code in {401, 403}:
                return VinciError(
                    code=ErrorCode.AUTH, message="provider auth failed", retryable=False
                )
            if exc.code == 429:
                return VinciError(code=ErrorCode.RATE_LIMIT, message="rate limited", retryable=True)
            if exc.code == 400:
                return VinciError(
                    code=ErrorCode.INVALID_INPUT, message="invalid input", retryable=False
                )
            if exc.code >= 500:
                return VinciError(
                    code=ErrorCode.PROVIDER_DOWN, message="provider down", retryable=True
                )
        return VinciError(code=ErrorCode.UNKNOWN, message=type(exc).__name__, retryable=False)

    def prompt_text(self, req: JobRequest) -> str:
        return compose_shot_prompt(req.inputs)

    def _submit_live(self, req: JobRequest, spec: ModelSpec) -> ProviderJobRef:
        raise NotImplementedError

    def _status_live(self, ref: ProviderJobRef) -> JobStatus | None:
        return None

    def _post_json(self, url: str, headers: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        return self._open_json(request)

    def _get_json(self, url: str, headers: dict[str, str]) -> dict[str, Any]:
        request = urllib.request.Request(url, headers=headers, method="GET")
        return self._open_json(request)

    def _post_bytes(self, url: str, headers: dict[str, str], body: dict[str, Any]) -> bytes:
        data = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = response.read()
        except urllib.error.HTTPError as exc:
            raise exc
        if not isinstance(payload, (bytes, bytearray)):
            raise TypeError("provider response was not bytes")
        return bytes(payload)

    def _open_json(self, request: urllib.request.Request) -> dict[str, Any]:
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raise exc
        parsed: dict[str, Any] = json.loads(raw) if raw else {}
        return parsed
