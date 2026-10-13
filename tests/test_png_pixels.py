from __future__ import annotations

import importlib.util
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "png_pixels", ROOT / "scripts" / "mac" / "png_pixels.py"
)
_mod = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(_mod)
png_has_nonuniform_pixels = _mod.png_has_nonuniform_pixels


def test_png_pixels_rejects_flat(tmp_path: Path) -> None:
    def chunk(ctype: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(ctype + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + ctype + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0)
    raw = zlib.compress(b"\x00" + b"\x00\x00\x00" * 2 + b"\x00" + b"\x00\x00\x00" * 2)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", raw) + chunk(b"IEND", b"")
    path = tmp_path / "flat.png"
    path.write_bytes(png)
    assert not png_has_nonuniform_pixels(path)
