"""Turn a local content-addressed still into a data URI providers can accept."""

from __future__ import annotations

import base64
from typing import Any

_FTYP_IMAGE = {
    b"avif": "image/avif",
    b"avis": "image/avif",
    b"heic": "image/heic",
    b"heix": "image/heic",
    b"hevc": "image/heic",
    b"hevx": "image/heic",
    b"mif1": "image/heif",
    b"msf1": "image/heif",
}
_FTYP_VIDEO = {
    b"isom",
    b"iso2",
    b"iso4",
    b"iso5",
    b"iso6",
    b"mp41",
    b"mp42",
    b"avc1",
    b"dash",
    b"MSNV",
}


def _iso_bmff_mime(blob: bytes) -> str | None:
    if len(blob) < 12 or blob[4:8] != b"ftyp":
        return None
    size = int.from_bytes(blob[:4], "big")
    end = len(blob)
    if 16 <= size <= end:
        end = size
    brands = [blob[8:12]]
    pos = 16
    while pos + 4 <= end:
        brands.append(blob[pos : pos + 4])
        pos += 4
    for brand in brands:
        mime = _FTYP_IMAGE.get(brand)
        if mime:
            return mime
    if any(brand in _FTYP_VIDEO for brand in brands):
        return "video/mp4"
    return None


def sniff_media_mime(blob: bytes) -> str | None:
    if blob.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if blob[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if len(blob) >= 12 and blob[:4] == b"RIFF" and blob[8:12] == b"WEBP":
        return "image/webp"
    if blob[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return _iso_bmff_mime(blob)


def local_media_bytes(value: str | None, cas: Any | None) -> tuple[bytes, str] | None:
    if not isinstance(value, str) or not value:
        return None
    if value.startswith(("http://", "https://", "data:")):
        return None
    if cas is None or not cas.exists(value):
        return None
    blob = cas.get(value)
    mime = sniff_media_mime(blob)
    if mime is None:
        raise ValueError("unsupported local media format")
    return blob, mime


def local_image_bytes(value: str | None, cas: Any | None) -> tuple[bytes, str] | None:
    loaded = local_media_bytes(value, cas)
    if loaded is None:
        return None
    blob, mime = loaded
    if not mime.startswith("image/"):
        raise ValueError("unsupported local image format")
    return blob, mime


def as_data_uri(value: str | None, cas: Any | None) -> str | None:
    loaded = local_media_bytes(value, cas)
    if loaded is None:
        return value
    blob, mime = loaded
    encoded = base64.b64encode(blob).decode("ascii")
    return f"data:{mime};base64,{encoded}"
