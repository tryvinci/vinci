"""Loopback HTTP I2I/T2I provider for free-gate tests (no live spend, no WAN)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

from vinci_core.cost import idempotency_key, resolve_model
from vinci_protocol.enums import JobState
from vinci_protocol.models import JobRequest, JobStatus, ProviderJobRef

from vinci_provider_sdk.catalog_provider import CatalogBackedProvider


class LoopbackI2IProvider(CatalogBackedProvider):
    """Catalog-backed provider that talks to a local loopback HTTP server."""

    durable_job_reconciliation = True
    catalog_name = "openai"
    provider_id = "openai"
    secret_name = "OPENAI_API_KEY"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = "loopback-test",
        cas: object | None = None,
    ) -> None:
        super().__init__(api_key=api_key)
        self._base_url = base_url.rstrip("/")
        self._cas = cas

    def submit(self, req: JobRequest) -> ProviderJobRef:
        spec = resolve_model(self._catalog, req)
        key = req.idempotency_key or idempotency_key(spec.id, req.inputs)
        if key not in self._estimated:
            raise RuntimeError("estimate() must be called before submit()")
        if not self._api_key:
            raise PermissionError(f"missing {self.secret_name}")
        payload = {
            "capability": req.capability.value,
            "model_id": spec.id,
            "inputs": req.inputs,
            "idempotency_key": key,
        }
        url = f"{self._base_url}/v1/submit"
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={"content-type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            parsed = json.loads(response.read().decode("utf-8"))
        ref = str(parsed["ref"])
        self._jobs[ref] = JobStatus(state=JobState.RUNNING, outputs=[], progress=0.0)
        return ProviderJobRef(provider=self.provider_id, ref=ref)

    def _status_live(self, ref: ProviderJobRef) -> JobStatus | None:
        url = f"{self._base_url}/v1/status/{urllib.parse.quote(ref.ref, safe='')}"
        request = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                parsed = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise
        state = JobState(str(parsed.get("state") or "running"))
        outputs = list(parsed.get("outputs") or [])
        progress = float(parsed.get("progress") or 0)
        status = JobStatus(state=state, outputs=outputs, progress=progress)
        self._jobs[ref.ref] = status
        return status


def loopback_i2i_from_env(cas: object | None = None) -> LoopbackI2IProvider | None:
    base = os.environ.get("VINCI_TEST_LOOPBACK_I2I_URL", "").strip()
    if not base:
        return None
    return LoopbackI2IProvider(base_url=base, cas=cas)
