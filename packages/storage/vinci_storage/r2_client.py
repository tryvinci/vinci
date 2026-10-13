"""Minimal S3-compatible client for Cloudflare R2 (and a local directory mock)."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast


@dataclass(frozen=True)
class ObjectHead:
    etag: str
    body: bytes


class R2Client:
    _mock_guard = threading.Lock()

    def __init__(
        self,
        *,
        bucket: str,
        account_id: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        endpoint: str | None = None,
        mock_root: Path | None = None,
    ) -> None:
        self.bucket = bucket
        self.account_id = account_id or ""
        self.access_key_id = access_key_id or ""
        self.secret_access_key = secret_access_key or ""
        self.mock_root = mock_root
        if mock_root is not None:
            mock_root.mkdir(parents=True, exist_ok=True)
            return
        if not (account_id and access_key_id and secret_access_key):
            raise ValueError("R2 credentials required when mock_root is unset")
        host = endpoint or f"https://{account_id}.r2.cloudflarestorage.com"
        self.endpoint = host.rstrip("/")

    @classmethod
    def from_env(cls) -> R2Client | None:
        mock = os.environ.get("VINCI_R2_MOCK_DIR")
        if mock:
            return cls(bucket=os.environ.get("VINCI_R2_BUCKET", "mock"), mock_root=Path(mock))
        bucket = os.environ.get("VINCI_R2_BUCKET")
        account = os.environ.get("VINCI_R2_ACCOUNT_ID") or os.environ.get("CLOUDFLARE_ACCOUNT_ID")
        key_id = os.environ.get("VINCI_R2_ACCESS_KEY_ID")
        secret = os.environ.get("VINCI_R2_SECRET_ACCESS_KEY")
        if not bucket or not account or not key_id or not secret:
            return None
        return cls(
            bucket=bucket,
            account_id=account,
            access_key_id=key_id,
            secret_access_key=secret,
            endpoint=os.environ.get("VINCI_R2_ENDPOINT"),
        )

    def _mock_path(self, key: str) -> Path:
        if self.mock_root is None:
            raise RuntimeError("mock_root required")
        safe = key.lstrip("/").replace("..", "_")
        return self.mock_root / self.bucket / safe

    def _mock_etag_path(self, key: str) -> Path:
        return self._mock_path(key + ".__etag")

    def _mock_etag_for(self, data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def head(self, key: str) -> ObjectHead | None:
        if self.mock_root is not None:
            path = self._mock_path(key)
            if not path.is_file():
                return None
            body = path.read_bytes()
            etag_path = self._mock_etag_path(key)
            if etag_path.is_file():
                etag = etag_path.read_text(encoding="utf-8").strip()
            else:
                etag = self._mock_etag_for(body)
            return ObjectHead(etag=etag, body=body)
        try:
            body, headers = self._request_with_headers("GET", key)
            etag = headers.get("etag", hashlib.sha256(body).hexdigest()).strip('"')
            return ObjectHead(etag=etag, body=body)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise

    def get_bytes(self, key: str) -> bytes | None:
        meta = self.head(key)
        return meta.body if meta is not None else None

    def put_bytes(
        self,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        if self.mock_root is not None:
            path = self._mock_path(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            etag = self._mock_etag_for(data)
            self._mock_etag_path(key).write_text(etag, encoding="utf-8")
            return etag
        self._request("PUT", key, body=data, content_type=content_type)
        return hashlib.sha256(data).hexdigest()

    def put_bytes_if_match(
        self,
        key: str,
        data: bytes,
        *,
        if_match: str | None,
        if_none_match: bool = False,
        content_type: str = "application/octet-stream",
    ) -> bool:
        """Conditional PUT. if_match=None with if_none_match=True means create-only."""
        if self.mock_root is not None:
            with self._mock_guard:
                current = self.head(key)
                if if_none_match and current is not None:
                    return False
                if if_match is not None:
                    if current is None or current.etag != if_match:
                        return False
                self.put_bytes(key, data, content_type=content_type)
                return True
        extra: dict[str, str] = {}
        if if_none_match:
            extra["If-None-Match"] = "*"
        elif if_match is not None:
            extra["If-Match"] = f'"{if_match}"'
        try:
            self._request("PUT", key, body=data, content_type=content_type, extra_headers=extra)
            return True
        except urllib.error.HTTPError as exc:
            if exc.code in {412, 409}:
                return False
            raise

    def delete(self, key: str) -> None:
        self.delete_if_match(key, if_match=None)

    def delete_if_match(self, key: str, *, if_match: str | None) -> bool:
        if self.mock_root is not None:
            with self._mock_guard:
                head = self.head(key)
                if head is None:
                    return True
                if if_match is not None and head.etag != if_match:
                    return False
                path = self._mock_path(key)
                if path.is_file():
                    path.unlink()
                etag_path = self._mock_etag_path(key)
                if etag_path.is_file():
                    etag_path.unlink()
                return True
        extra: dict[str, str] = {}
        if if_match is not None:
            extra["If-Match"] = f'"{if_match}"'
        try:
            self._request("DELETE", key, extra_headers=extra)
            return True
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return True
            if exc.code in {412, 409}:
                return False
            raise

    def _request_with_headers(
        self,
        method: str,
        key: str,
        body: bytes | None = None,
        content_type: str = "application/octet-stream",
        extra_headers: dict[str, str] | None = None,
    ) -> tuple[bytes, dict[str, str]]:
        key = key.lstrip("/")
        url = f"{self.endpoint}/{self.bucket}/{urllib.parse.quote(key, safe='/')}"
        now = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
        headers = {
            "host": urllib.parse.urlparse(self.endpoint).netloc,
            "x-amz-content-sha256": hashlib.sha256(body or b"").hexdigest(),
            "x-amz-date": now,
        }
        if body is not None:
            headers["content-type"] = content_type
        if extra_headers:
            headers.update(extra_headers)
        signed = _sign_s3(
            method=method,
            url=url,
            headers=headers,
            access_key=self.access_key_id,
            secret_key=self.secret_access_key,
            region="auto",
        )
        req = urllib.request.Request(url, data=body, method=method, headers=signed)
        with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310
            hdrs = {k.lower(): v for k, v in resp.headers.items()}
            return cast(bytes, resp.read()), hdrs

    def _request(
        self,
        method: str,
        key: str,
        body: bytes | None = None,
        content_type: str = "application/octet-stream",
        extra_headers: dict[str, str] | None = None,
    ) -> bytes:
        payload, _hdrs = self._request_with_headers(
            method, key, body=body, content_type=content_type, extra_headers=extra_headers
        )
        return payload

    def get_json(self, key: str) -> dict[str, Any] | None:
        raw = self.get_bytes(key)
        if raw is None:
            return None
        return cast(dict[str, Any], json.loads(raw.decode("utf-8")))

    def put_json(self, key: str, payload: dict[str, Any]) -> str:
        return self.put_bytes(
            key, json.dumps(payload, sort_keys=True).encode("utf-8"), "application/json"
        )

    def put_json_if_match(
        self,
        key: str,
        payload: dict[str, Any],
        *,
        if_match: str | None,
        if_none_match: bool = False,
    ) -> bool:
        return self.put_bytes_if_match(
            key,
            json.dumps(payload, sort_keys=True).encode("utf-8"),
            if_match=if_match,
            if_none_match=if_none_match,
            content_type="application/json",
        )


def _sign_s3(
    *,
    method: str,
    url: str,
    headers: dict[str, str],
    access_key: str,
    secret_key: str,
    region: str,
) -> dict[str, str]:
    parsed = urllib.parse.urlparse(url)
    canonical_uri = parsed.path or "/"
    canonical_query = ""
    norm = {k.lower(): v for k, v in headers.items()}
    canonical_headers = "".join(f"{h}:{norm[h]}\n" for h in sorted(norm))
    signed_headers = ";".join(sorted(norm))
    payload_hash = norm["x-amz-content-sha256"]
    canonical_request = "\n".join(
        [method, canonical_uri, canonical_query, canonical_headers, signed_headers, payload_hash]
    )
    scope = f"{norm['x-amz-date'][:8]}/{region}/s3/aws4_request"
    digest = hashlib.sha256(canonical_request.encode()).hexdigest()
    string_to_sign = "\n".join(["AWS4-HMAC-SHA256", norm["x-amz-date"], scope, digest])

    def _hmac(key: bytes, msg: str) -> bytes:
        return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

    k_date = _hmac(("AWS4" + secret_key).encode(), norm["x-amz-date"][:8])
    k_region = _hmac(k_date, region)
    k_service = _hmac(k_region, "s3")
    k_signing = _hmac(k_service, "aws4_request")
    signature = hmac.new(k_signing, string_to_sign.encode(), hashlib.sha256).hexdigest()
    authorization = (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    out = dict(headers)
    out["Authorization"] = authorization
    return out
