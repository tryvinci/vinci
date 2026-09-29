from __future__ import annotations

import io
import logging

from vinci_core.catalog import reject_sunset_defaults
from vinci_core.cost import idempotency_key
from vinci_protocol.enums import JobState
from vinci_protocol.models import JobRequest, ProviderJobRef

from vinci_provider_sdk.base import Provider


def sample_request(provider: Provider, extra_inputs: dict[str, str] | None = None) -> JobRequest:
    capabilities = provider.capabilities()
    if not capabilities:
        raise AssertionError("capabilities must not be empty")
    cap = sorted(capabilities, key=lambda item: item.value)[0]
    inputs = {"prompt": "conformance"}
    if extra_inputs:
        inputs.update(extra_inputs)
    return JobRequest(capability=cap, inputs=inputs)


def assert_schema_roundtrip(provider: Provider) -> None:
    models = provider.catalog()
    if not models:
        raise AssertionError("catalog must not be empty")
    if not provider.capabilities():
        raise AssertionError("capabilities must not be empty")
    for spec in models:
        spec.model_validate(spec.model_dump())
        reject_sunset_defaults(spec.id)


def assert_estimate_before_submit(provider: Provider) -> None:
    req = sample_request(provider)
    try:
        provider.submit(req)
    except Exception:
        return
    raise AssertionError("submit must refuse work when estimate() was not called")


def assert_error_normalization(provider: Provider) -> None:
    mapped = provider.normalize_error(PermissionError("nope"))
    if mapped.code.value != "auth":
        raise AssertionError(f"PermissionError should map to auth, got {mapped.code}")
    mapped_timeout = provider.normalize_error(TimeoutError("slow"))
    if mapped_timeout.code.value != "timeout":
        raise AssertionError("TimeoutError should map to timeout")


def assert_idempotent_status(provider: Provider) -> None:
    req = sample_request(provider, {"prompt": "status-idempotent"})
    provider.estimate(req)
    ref: ProviderJobRef = provider.submit(req)
    first = provider.status(ref)
    second = provider.status(ref)
    if first.state != second.state or first.outputs != second.outputs:
        raise AssertionError("status polling must be idempotent")
    if first.state != JobState.COMPLETED:
        raise AssertionError("mock job should complete")


def assert_secret_free_logs(provider: Provider, secret: str) -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger = logging.getLogger("vinci.provider")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        req = sample_request(provider, {"note": secret})
        req = req.model_copy(
            update={"idempotency_key": idempotency_key("conformance", req.inputs)}
        )
        provider.estimate(req)
        try:
            provider.submit(req)
        except Exception:
            pass
    finally:
        logger.removeHandler(handler)
    blob = stream.getvalue()
    if secret in blob:
        raise AssertionError("secret leaked into logs")


def run_conformance(
    provider: Provider, secret: str | None = None, *, live_submit: bool = True
) -> None:
    assert_schema_roundtrip(provider)
    assert_estimate_before_submit(provider)
    assert_error_normalization(provider)
    if live_submit:
        assert_idempotent_status(provider)
    if secret:
        assert_secret_free_logs(provider, secret)
