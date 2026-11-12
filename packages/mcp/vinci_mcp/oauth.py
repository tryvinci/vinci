"""Split authorization-code flow for remote MCP servers.

The official SDK's ``OAuthClientProvider`` runs the browser inside one HTTP
request. Studio opens the authorize URL in another tab and the daemon
receives the callback later, so this module does discovery, dynamic client
registration, PKCE, and token exchange itself. Later MCP calls use the SDK
streamable-HTTP client with the stored bearer, and refresh uses the same
token endpoint the SDK would.
"""

from __future__ import annotations

import base64
import hashlib
import html
import http.client
import ipaddress
import json
import secrets
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any

from vinci_core.credentials import CredentialResolver

STATE_TTL_SECONDS = 600
_HTTP_TIMEOUT = 5.0


class OAuthError(ValueError):
    """User-facing OAuth failure. Never includes token material."""


@dataclass
class _Pending:
    provider_id: str
    verifier: str
    redirect_uri: str
    token_endpoint: str
    revocation_endpoint: str | None
    client_id: str
    client_secret: str | None
    resource: str | None
    allow_loopback: bool
    expires_at: float


_PENDING: dict[str, _Pending] = {}
_REFRESH_GUARD = threading.Lock()
_REFRESH_LOCKS: dict[str, threading.Lock] = {}


def oauth_secret_name(provider_id: str) -> str:
    if provider_id == "mcp":
        return "MCP_OAUTH"
    if provider_id.startswith("mcp_"):
        suffix = provider_id[4:].upper()
        if suffix.isidentifier():
            return "MCP_OAUTH_" + suffix
    raise ValueError("oauth secret name requires an mcp provider id")


def pending_export(state: str) -> dict[str, Any] | None:
    """A pending sign-in as a plain dict, for a host that runs more than one process.

    The callback can reach another process than the start (Cloud Run instances): the host keeps
    this dict (sealed) and gives it back with ``pending_import`` (COREPRODUC-614).
    """
    item = _PENDING.get(state)
    return asdict(item) if item else None


def pending_import(state: str, data: dict[str, Any]) -> None:
    """Put back a pending sign-in that ``pending_export`` gave, before ``finish``."""
    _PENDING[state] = _Pending(**data)


def clear_pending() -> None:
    _PENDING.clear()


def _drop_expired_pending() -> None:
    now = time.time()
    expired = [key for key, item in list(_PENDING.items()) if now > item.expires_at]
    for key in expired:
        _PENDING.pop(key, None)


def _provider_lock(provider_id: str) -> threading.Lock:
    with _REFRESH_GUARD:
        lock = _REFRESH_LOCKS.get(provider_id)
        if lock is None:
            lock = threading.Lock()
            _REFRESH_LOCKS[provider_id] = lock
        return lock


def discard_pending(state: str) -> None:
    _PENDING.pop(state, None)


def callback_block_reason(state: str) -> str | None:
    """Why this callback must not be journaled. None means the state is still valid."""
    if not state:
        return "unknown or reused OAuth state"
    pending = _PENDING.get(state)
    if pending is None:
        return "unknown or reused OAuth state"
    if time.time() > pending.expires_at:
        _PENDING.pop(state, None)
        return "OAuth state expired"
    return None


# The sign-in result page in the Studio's dark tokens (apps/studio/app/theme.css: --bg, --panel,
# --line, --ink, --dim, --accent, --danger). No script and no files, so it works on any origin.
_RESULT_CSS = (
    ":root{color-scheme:dark}"
    "body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0c0e12;"
    'color:#f4f4f5;font:15px/1.55 "Inter Tight",Inter,system-ui,sans-serif}'
    "main{box-sizing:border-box;width:min(440px,calc(100vw - 32px));padding:28px 28px 22px;"
    "border-radius:16px;background:#12141a;border:1px solid rgb(255 255 255/.08);"
    "box-shadow:inset 0 1px 0 rgb(255 255 255/.06)}"
    "p{margin:0}"
    ".eyebrow{margin-bottom:6px;font-size:11px;letter-spacing:.16em;text-transform:uppercase;"
    "color:#21dad2}"
    'h1{margin:0 0 10px;font:italic 400 34px/1.1 "Instrument Serif",Georgia,serif}'
    ".dot{display:inline-block;width:8px;height:8px;margin-right:9px;border-radius:50%;"
    "vertical-align:1px;background:#21dad2}"
    ".bad .eyebrow{color:#f07167}.bad .dot{background:#f07167}"
    "small{display:block;margin-top:18px;padding-top:14px;"
    "border-top:1px solid rgb(255 255 255/.08);color:#a1a1aa;font-size:12.5px}"
)


def result_page(provider: str, problem: str = "") -> str:
    """The page the sign-in tab shows after the provider sends the browser back.

    The local daemon and the hosted backend send this same page, so a sign-in ends in the
    Studio's look on both.

    Args:
        provider: The provider's name, such as "Higgsfield". Empty when it is not known.
        problem: Why the sign-in did not finish. Empty when it finished.

    Returns:
        A complete HTML document. Both values are escaped.
    """
    name = html.escape(provider)
    if problem:
        title, line = "Sign-in did not finish", html.escape(problem[:1].upper() + problem[1:])
    else:
        title = f"Signed in to {name}" if name else "Signed in"
        line = f"Your {name + ' ' if name else ''}models are in the studio now."
    tone = "bad" if problem else "ok"
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{title} · Vinci</title><style>{_RESULT_CSS}</style></head>"
        f'<body><main class="{tone}"><p class="eyebrow">Vinci · {name or "Sign-in"}</p>'
        f'<h1>{title}</h1><p><span class="dot"></span>{line}</p>'
        "<small>You can close this tab.</small></main></body></html>"
    )


def secret_material(raw: str) -> list[str]:
    """Token strings inside a stored OAuth record, for log redaction."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, dict):
        return []
    found: list[str] = []
    tokens = data.get("tokens")
    if isinstance(tokens, dict):
        for key in ("access_token", "refresh_token"):
            value = tokens.get(key)
            if isinstance(value, str) and value:
                found.append(value)
    client = data.get("client")
    if isinstance(client, dict):
        secret = client.get("client_secret")
        if isinstance(secret, str) and secret:
            found.append(secret)
    return found


def auth_state(resolver: CredentialResolver, provider_id: str) -> str:
    record = _load(resolver, provider_id)
    if record is None:
        return "disconnected"
    if record.get("needs_reconnect"):
        return "needs_reconnect"
    tokens = record.get("tokens")
    if isinstance(tokens, dict) and tokens.get("access_token"):
        return "connected"
    return "disconnected"


def start(
    resolver: CredentialResolver,
    provider_id: str,
    server_url: str,
    redirect_uri: str,
) -> dict[str, Any]:
    _drop_expired_pending()
    allow_loopback = _server_allows_loopback(server_url)
    metadata = _discover(server_url, allow_loopback=allow_loopback)
    if not metadata.get("registration_endpoint"):
        raise OAuthError("this MCP server does not allow self-registration")
    client = _client(
        resolver, provider_id, metadata, redirect_uri, allow_loopback=allow_loopback
    )
    verifier, challenge = _pkce()
    state = secrets.token_urlsafe(32)
    _PENDING[state] = _Pending(
        provider_id=provider_id,
        verifier=verifier,
        redirect_uri=redirect_uri,
        token_endpoint=str(metadata["token_endpoint"]),
        revocation_endpoint=_optional_str(metadata.get("revocation_endpoint")),
        client_id=str(client["client_id"]),
        client_secret=_optional_str(client.get("client_secret")),
        resource=_optional_str(metadata.get("resource")),
        allow_loopback=allow_loopback,
        expires_at=time.time() + STATE_TTL_SECONDS,
    )
    query = {
        "response_type": "code",
        "client_id": client["client_id"],
        "redirect_uri": redirect_uri,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    scope = _scope(metadata)
    if scope:
        query["scope"] = scope
    if metadata.get("resource"):
        query["resource"] = metadata["resource"]
    authorize = str(metadata["authorization_endpoint"])
    joiner = "&" if "?" in authorize else "?"
    return {
        "id": provider_id,
        "mode": "oauth",
        "authorize_url": authorize + joiner + urllib.parse.urlencode(query),
        "auth_state": auth_state(resolver, provider_id),
        "hint": "Sign in in the browser. Vinci stores the tokens on this machine.",
    }


def finish(
    resolver: CredentialResolver,
    *,
    code: str,
    state: str,
    error: str = "",
) -> dict[str, Any]:
    if error:
        raise OAuthError("authorization was denied")
    pending = _PENDING.pop(state, None)
    if pending is None:
        raise OAuthError("unknown or reused OAuth state")
    if time.time() > pending.expires_at:
        raise OAuthError("OAuth state expired")
    if not code:
        raise OAuthError("authorization code missing")
    body = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": pending.redirect_uri,
        "client_id": pending.client_id,
        "code_verifier": pending.verifier,
    }
    if pending.client_secret:
        body["client_secret"] = pending.client_secret
    if pending.resource:
        body["resource"] = pending.resource
    tokens = _token_request(pending.token_endpoint, body, allow_loopback=pending.allow_loopback)
    record = _load(resolver, pending.provider_id) or {}
    record.update(
        {
            "client": {
                "client_id": pending.client_id,
                "client_secret": pending.client_secret,
                "redirect_uri": pending.redirect_uri,
            },
            "tokens": tokens,
            "token_endpoint": pending.token_endpoint,
            "revocation_endpoint": pending.revocation_endpoint,
            "resource": pending.resource,
            "allow_loopback": pending.allow_loopback,
            "needs_reconnect": False,
            "expires_at": _expires_at(tokens),
        }
    )
    _save(resolver, pending.provider_id, record)
    return {
        "ok": True,
        "id": pending.provider_id,
        "auth_state": "connected",
    }


def access_token(resolver: CredentialResolver, provider_id: str) -> str | None:
    with _provider_lock(provider_id):
        record = _load(resolver, provider_id)
        if record is None or record.get("needs_reconnect"):
            return None
        tokens = record.get("tokens")
        if not isinstance(tokens, dict):
            return None
        current = tokens.get("access_token")
        if not isinstance(current, str) or not current:
            return None
        expires = record.get("expires_at")
        if isinstance(expires, (int, float)) and time.time() >= float(expires) - 30:
            return _refresh(resolver, provider_id)
        return current


def disconnect(resolver: CredentialResolver, provider_id: str) -> None:
    with _provider_lock(provider_id):
        record = _load(resolver, provider_id)
        if record is not None:
            _revoke(record)
        resolver.delete(oauth_secret_name(provider_id))
        stale = [key for key, item in list(_PENDING.items()) if item.provider_id == provider_id]
        for key in stale:
            _PENDING.pop(key, None)


def _refresh(resolver: CredentialResolver, provider_id: str) -> str | None:
    record = _load(resolver, provider_id)
    if record is None:
        return None
    tokens = record.get("tokens")
    refresh = tokens.get("refresh_token") if isinstance(tokens, dict) else None
    endpoint = record.get("token_endpoint")
    raw_client = record.get("client")
    client: dict[str, Any] = raw_client if isinstance(raw_client, dict) else {}
    if not isinstance(refresh, str) or not refresh or not isinstance(endpoint, str):
        _mark_reconnect(resolver, provider_id, record)
        return None
    body = {
        "grant_type": "refresh_token",
        "refresh_token": refresh,
        "client_id": str(client.get("client_id") or ""),
    }
    secret = client.get("client_secret")
    if isinstance(secret, str) and secret:
        body["client_secret"] = secret
    resource = record.get("resource")
    if isinstance(resource, str) and resource:
        body["resource"] = resource
    try:
        fresh = _token_request(
            endpoint, body, allow_loopback=bool(record.get("allow_loopback"))
        )
    except OAuthError:
        _mark_reconnect(resolver, provider_id, record)
        return None
    if "refresh_token" not in fresh:
        fresh["refresh_token"] = refresh
    record["tokens"] = fresh
    record["needs_reconnect"] = False
    record["expires_at"] = _expires_at(fresh)
    _save(resolver, provider_id, record)
    access = fresh.get("access_token")
    return access if isinstance(access, str) and access else None


def _mark_reconnect(
    resolver: CredentialResolver, provider_id: str, record: dict[str, Any]
) -> None:
    record["needs_reconnect"] = True
    tokens = record.get("tokens")
    if isinstance(tokens, dict):
        tokens["access_token"] = ""
    _save(resolver, provider_id, record)


def _revoke(record: dict[str, Any]) -> None:
    endpoint = record.get("revocation_endpoint")
    tokens = record.get("tokens")
    if not isinstance(endpoint, str) or not endpoint or not isinstance(tokens, dict):
        return
    token = tokens.get("refresh_token") or tokens.get("access_token")
    if not isinstance(token, str) or not token:
        return
    raw_client = record.get("client")
    client: dict[str, Any] = raw_client if isinstance(raw_client, dict) else {}
    body = {"token": token, "client_id": str(client.get("client_id") or "")}
    try:
        _form(endpoint, body, allow_loopback=bool(record.get("allow_loopback")))
    except OAuthError:
        return


def _client(
    resolver: CredentialResolver,
    provider_id: str,
    metadata: dict[str, Any],
    redirect_uri: str,
    *,
    allow_loopback: bool,
) -> dict[str, Any]:
    record = _load(resolver, provider_id) or {}
    existing = record.get("client")
    if (
        isinstance(existing, dict)
        and existing.get("client_id")
        and existing.get("redirect_uri") == redirect_uri
    ):
        return existing
    registered = _json_request(
        str(metadata["registration_endpoint"]),
        {
            "client_name": "Vinci",
            "redirect_uris": [redirect_uri],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        },
        allow_loopback=allow_loopback,
    )
    client_id = registered.get("client_id")
    if not isinstance(client_id, str) or not client_id:
        raise OAuthError("registration did not return a client_id")
    client = {
        "client_id": client_id,
        "client_secret": _optional_str(registered.get("client_secret")),
        "redirect_uri": redirect_uri,
    }
    record["client"] = client
    record["token_endpoint"] = metadata.get("token_endpoint")
    record["revocation_endpoint"] = metadata.get("revocation_endpoint")
    record["resource"] = metadata.get("resource")
    record["allow_loopback"] = allow_loopback
    _save(resolver, provider_id, record)
    return client


def _server_allows_loopback(server_url: str) -> bool:
    host = (urllib.parse.urlparse(server_url).hostname or "").lower()
    return _is_loopback_host(host)


def _discover(server_url: str, *, allow_loopback: bool) -> dict[str, Any]:
    parsed = urllib.parse.urlparse(server_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise OAuthError("MCP URL must be http or https")
    origin = f"{parsed.scheme}://{parsed.netloc}"
    path = parsed.path.rstrip("/")
    resource_doc: dict[str, Any] | None = None
    candidates = []
    if path and path != "/":
        candidates.append(f"{origin}/.well-known/oauth-protected-resource{path}")
    candidates.append(f"{origin}/.well-known/oauth-protected-resource")
    for url in candidates:
        resource_doc = _get_json(url, allow_loopback=allow_loopback)
        if resource_doc:
            break
    auth_base = origin
    resource = None
    resource_scopes: list[str] = []
    if resource_doc:
        resource = _optional_str(resource_doc.get("resource"))
        listed = resource_doc.get("scopes_supported")
        if isinstance(listed, list):
            resource_scopes = [item for item in listed if isinstance(item, str) and item]
        servers = resource_doc.get("authorization_servers")
        if isinstance(servers, list) and servers and isinstance(servers[0], str):
            auth_base = servers[0].rstrip("/")
    metadata = _get_json(
        f"{auth_base}/.well-known/oauth-authorization-server", allow_loopback=allow_loopback
    )
    if metadata is None and auth_base != origin:
        metadata = _get_json(
            f"{origin}/.well-known/oauth-authorization-server", allow_loopback=allow_loopback
        )
    if not metadata or not metadata.get("authorization_endpoint") or not metadata.get(
        "token_endpoint"
    ):
        raise OAuthError("MCP server did not publish OAuth discovery")
    metadata["authorization_endpoint"] = _require_oauth_endpoint(
        str(metadata["authorization_endpoint"]), allow_loopback=allow_loopback
    )
    metadata["token_endpoint"] = _require_oauth_endpoint(
        str(metadata["token_endpoint"]), allow_loopback=allow_loopback
    )
    registration = metadata.get("registration_endpoint")
    if isinstance(registration, str) and registration:
        metadata["registration_endpoint"] = _require_oauth_endpoint(
            registration, allow_loopback=allow_loopback
        )
    revocation = metadata.get("revocation_endpoint")
    if isinstance(revocation, str) and revocation:
        metadata["revocation_endpoint"] = _require_oauth_endpoint(
            revocation, allow_loopback=allow_loopback
        )
    if resource:
        metadata["resource"] = resource
    if resource_scopes:
        metadata["resource_scopes"] = resource_scopes
    return metadata


def _require_oauth_endpoint(url: str, *, allow_loopback: bool = False) -> str:
    """Allow public HTTPS. Loopback HTTP is only allowed for a loopback MCP server."""
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not host:
        raise OAuthError("oauth endpoint must be an http(s) URL")
    if _is_loopback_host(host):
        if not allow_loopback:
            raise OAuthError("oauth endpoint host is not public")
        return url
    if parsed.scheme != "https":
        raise OAuthError("oauth endpoint must use https")
    if _is_blocked_host(host):
        raise OAuthError("oauth endpoint host is not public")
    return url


def _is_loopback_host(host: str) -> bool:
    if host in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _is_blocked_host(host: str) -> bool:
    try:
        return _is_blocked_ip(host)
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise OAuthError("oauth endpoint host did not resolve") from exc
    for info in infos:
        address = str(info[4][0])
        if _is_loopback_host(address) or _is_blocked_ip(address):
            return True
    return False


def _connect_pinned(host: str, port: int, *, allow_loopback: bool) -> socket.socket:
    """Open one socket to a checked address and keep it for the HTTP request."""
    if _is_loopback_host(host):
        if not allow_loopback:
            raise OAuthError("oauth endpoint host is not public")
        try:
            raw = socket.create_connection((host, port), _HTTP_TIMEOUT)
        except OSError as exc:
            raise OAuthError("oauth endpoint unreachable") from exc
        peer = str(raw.getpeername()[0])
        if not _is_loopback_host(peer):
            raw.close()
            raise OAuthError("oauth endpoint peer is not public")
        return raw
    last_error: OSError | None = None
    for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM):
        candidate = str(info[4][0])
        if _is_loopback_host(candidate) or _is_blocked_ip(candidate):
            continue
        try:
            raw = socket.create_connection((candidate, port), _HTTP_TIMEOUT)
        except OSError as exc:
            last_error = exc
            continue
        try:
            peer = str(raw.getpeername()[0])
        except OSError as exc:
            raw.close()
            last_error = exc
            continue
        if peer != candidate or _is_loopback_host(peer) or _is_blocked_ip(peer):
            raw.close()
            continue
        return raw
    raise OAuthError("oauth endpoint host is not public") from last_error


def _is_blocked_ip(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return bool(
        ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _scope(metadata: dict[str, Any]) -> str:
    """Scopes of the authorize request.

    The MCP authorization spec asks for the protected resource's ``scopes_supported``
    (Higgsfield: openid email offline_access; Magnific: openid profile email
    mcp:custom-audience). Before, only openid and offline_access went out, so a server could
    refuse the token: no audience for Magnific, no email for Higgsfield (COREPRODUC-610, found by
    discovery on 2026-11-12 before any live sign-in). offline_access is added when the
    authorization server lists it, so the sign-in gets a refresh token.

    Args:
        metadata: Authorization server metadata from ``_discover``, with ``resource_scopes``.

    Returns:
        A space-separated scope, or "" when the servers list none.
    """
    raw = metadata.get("scopes_supported")
    supported = raw if isinstance(raw, list) else []
    wanted = list(metadata.get("resource_scopes") or [])
    if not wanted:
        wanted = [item for item in ("openid",) if item in supported]
    if "offline_access" in supported and "offline_access" not in wanted:
        wanted.append("offline_access")
    return " ".join(wanted)


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:128]
    if len(verifier) < 43:
        verifier = (verifier + secrets.token_urlsafe(48))[:128]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def _load(resolver: CredentialResolver, provider_id: str) -> dict[str, Any] | None:
    raw = resolver.resolve(oauth_secret_name(provider_id))
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _save(resolver: CredentialResolver, provider_id: str, record: dict[str, Any]) -> None:
    resolver.put(oauth_secret_name(provider_id), json.dumps(record, sort_keys=True))


def _expires_at(tokens: dict[str, Any]) -> float | None:
    expires_in = tokens.get("expires_in")
    if isinstance(expires_in, (int, float)) and expires_in > 0:
        return time.time() + float(expires_in)
    return None


def _token_request(
    url: str, body: dict[str, str], *, allow_loopback: bool
) -> dict[str, Any]:
    payload = _form(url, body, allow_loopback=allow_loopback)
    access = payload.get("access_token")
    if not isinstance(access, str) or not access:
        raise OAuthError("token endpoint did not return an access token")
    return payload


def _form(url: str, body: dict[str, str], *, allow_loopback: bool) -> dict[str, Any]:
    _require_oauth_endpoint(url, allow_loopback=allow_loopback)
    data = urllib.parse.urlencode(body).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"content-type": "application/x-www-form-urlencoded", "accept": "application/json"},
        method="POST",
    )
    return _open_json(request, allow_loopback=allow_loopback)


def _json_request(url: str, body: dict[str, Any], *, allow_loopback: bool) -> dict[str, Any]:
    _require_oauth_endpoint(url, allow_loopback=allow_loopback)
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json", "accept": "application/json"},
        method="POST",
    )
    return _open_json(request, allow_loopback=allow_loopback)


def _get_json(url: str, *, allow_loopback: bool) -> dict[str, Any] | None:
    try:
        _require_oauth_endpoint(url, allow_loopback=allow_loopback)
    except OAuthError:
        return None
    request = urllib.request.Request(url, headers={"accept": "application/json"}, method="GET")
    try:
        return _open_json(request, allow_loopback=allow_loopback)
    except OAuthError:
        return None


def _open_json(request: urllib.request.Request, *, allow_loopback: bool) -> dict[str, Any]:
    _require_oauth_endpoint(request.full_url, allow_loopback=allow_loopback)
    parsed = urllib.parse.urlparse(request.full_url)
    host = (parsed.hostname or "").lower()
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    sock: socket.socket | None = None
    try:
        sock = _connect_pinned(host, port, allow_loopback=allow_loopback)
        if parsed.scheme == "https":
            sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
        status, raw = _exchange(sock, request, host, port, parsed)
    except OAuthError:
        raise
    except (OSError, http.client.HTTPException, UnicodeError, TimeoutError) as exc:
        raise OAuthError("oauth endpoint unreachable") from exc
    finally:
        if sock is not None:
            sock.close()
    if 300 <= status < 400:
        raise OAuthError("oauth redirect refused")
    if status >= 400:
        raise OAuthError(f"oauth http {status}")
    try:
        body = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise OAuthError("oauth endpoint returned invalid json") from exc
    if not isinstance(body, dict):
        raise OAuthError("oauth endpoint returned a non-object")
    return body


def _exchange(
    sock: socket.socket,
    request: urllib.request.Request,
    host: str,
    port: int,
    parsed: urllib.parse.ParseResult,
) -> tuple[int, str]:
    """Send on the already-checked socket. Host stays the original name."""
    conn = http.client.HTTPConnection(host, port, timeout=_HTTP_TIMEOUT)
    conn.sock = sock
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    payload = request.data if isinstance(request.data, bytes) else None
    headers = {key: value for key, value in request.header_items()}
    conn.request(request.get_method(), path, body=payload, headers=headers)
    response = conn.getresponse()
    raw = response.read().decode("utf-8")
    return response.status, raw


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
