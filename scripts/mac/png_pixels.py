#!/usr/bin/env python3
"""Decode PNG pixels and require non-uniform RGBA (fail closed on flat/blank)."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path


def _png_idat_chunks(data: bytes) -> bytes:
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return b""
    pos = 8
    idat = bytearray()
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        pos += 4
        ctype = data[pos : pos + 4]
        pos += 4
        chunk = data[pos : pos + length]
        pos += length + 4
        if ctype == b"IDAT":
            idat.extend(chunk)
        if ctype == b"IEND":
            break
    return bytes(idat)


def png_has_nonuniform_pixels(path: Path, min_unique: int = 12) -> bool:
    raw = path.read_bytes()
    idat = _png_idat_chunks(raw)
    if not idat:
        return False
    try:
        inflated = zlib.decompress(idat)
    except zlib.error:
        return False
    if len(inflated) < 10:
        return False
    # Sample decoded bytes (filter byte per row skipped heuristically).
    sample = inflated[1 : min(len(inflated), 64_000)]
    if len(sample) < 64:
        return False
    unique = len(set(sample))
    if unique < min_unique:
        return False
    # Require spread in luminance-ish channels.
    lows = sample[::4]
    highs = sample[1::4]
    return max(lows) - min(lows) > 2 or max(highs) - min(highs) > 2


if __name__ == "__main__":
    import sys

    ok = png_has_nonuniform_pixels(Path(sys.argv[1]))
    raise SystemExit(0 if ok else 1)
