from __future__ import annotations

import base64
import json
import uuid
from typing import Any, Protocol

from vinci_protocol.enums import JobState
from vinci_protocol.models import (
    JobRequest,
    JobStatus,
    ModelSpec,
    ProviderAuth,
    ProviderJobRef,
    ProviderManifest,
)
from vinci_provider_sdk.catalog_provider import CatalogBackedProvider


class CasPut(Protocol):
    def put(self, data: bytes) -> str: ...


class CloudflareProvider(CatalogBackedProvider):
    catalog_name = "cloudflare"
    provider_id = "cloudflare"
    secret_name = "CLOUDFLARE_API_TOKEN"
    manifest = ProviderManifest(
        id="cloudflare",
        display_name="Cloudflare Workers AI",
        auth=ProviderAuth(env_vars=["CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"]),
        docs_url="https://developers.cloudflare.com/workers-ai/models/flux-1-schnell/",
    )

    def __init__(
        self,
        api_key: str | None = None,
        *,
        cas: CasPut | None = None,
        account_id: str | None = None,
    ) -> None:
        super().__init__(api_key=api_key)
        self._cas = cas
        self._account_id = account_id

    def _submit_live(self, req: JobRequest, spec: ModelSpec) -> ProviderJobRef:
        if self._cas is None:
            raise RuntimeError("cloudflare live submit needs CAS")
        account = (self._account_id or "").strip()
        if not account:
            raise ValueError("missing CLOUDFLARE_ACCOUNT_ID")
        endpoint = self._catalog.endpoint_for(spec.id) or "@cf/black-forest-labs/flux-1-schnell"
        url = f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{endpoint}"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {"prompt": self.prompt_text(req), "steps": 4}
        body = self._post_json(url, headers, payload)
        image_b64 = _image_b64(body)
        blob = base64.b64decode(image_b64)
        if not blob:
            raise RuntimeError("cloudflare submit returned empty image")
        digest = self._cas.put(blob)
        ref = str(uuid.uuid4())
        self._jobs[ref] = JobStatus(state=JobState.COMPLETED, outputs=[digest], progress=1.0)
        return ProviderJobRef(provider="cloudflare", ref=ref)

    def _post_json(self, url: str, headers: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
        import urllib.error
        import urllib.request

        data = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raise exc
        parsed: dict[str, Any] = json.loads(raw) if raw else {}
        return parsed


def _image_b64(body: dict[str, Any]) -> str:
    result = body.get("result")
    if isinstance(result, dict) and result.get("image"):
        return str(result["image"])
    if body.get("image"):
        return str(body["image"])
    raise RuntimeError("cloudflare submit missing image")
