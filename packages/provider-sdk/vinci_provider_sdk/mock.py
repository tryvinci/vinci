from __future__ import annotations

import hashlib
import logging
import os
import shutil
import struct
import subprocess
import tempfile
import uuid
import zlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from vinci_core.catalog import load_catalog
from vinci_core.cost import estimate_from_spec, idempotency_key
from vinci_core.redact import redact_mapping
from vinci_protocol.enums import Capability, ErrorCode, JobState
from vinci_protocol.models import (
    Estimate,
    JobRequest,
    JobStatus,
    ModelSpec,
    ProviderAuth,
    ProviderJobRef,
    ProviderManifest,
    VinciError,
)
from vinci_storage.cas import CasStore, ContentAddressedStore

from vinci_provider_sdk.base import Provider
from vinci_provider_sdk.shot import compose_shot_prompt, mock_duration_seconds

MOCK_PNG_WIDTH = 960
MOCK_PNG_HEIGHT = 540
_ASPECT_WH = {
    "16:9": (960, 540),
    "9:16": (540, 960),
    "1:1": (720, 720),
    "4:3": (960, 720),
    "3:4": (720, 960),
    "3:2": (960, 640),
    "2:3": (640, 960),
    "21:9": (960, 412),
    "4:5": (576, 720),
    "5:4": (720, 576),
}


def mock_dimensions(aspect_ratio: object | None = None) -> tuple[int, int]:
    """Default 16:9 960x540 when aspect is unset. Even sides for yuv420p."""
    raw = str(aspect_ratio or "").strip()
    if not raw:
        return MOCK_PNG_WIDTH, MOCK_PNG_HEIGHT
    if raw in _ASPECT_WH:
        return _ASPECT_WH[raw]
    if ":" not in raw:
        return MOCK_PNG_WIDTH, MOCK_PNG_HEIGHT
    left, right = raw.split(":", 1)
    try:
        a = float(left)
        b = float(right)
    except ValueError:
        return MOCK_PNG_WIDTH, MOCK_PNG_HEIGHT
    if a <= 0 or b <= 0:
        return MOCK_PNG_WIDTH, MOCK_PNG_HEIGHT
    if a >= b:
        width = MOCK_PNG_WIDTH
        height = int(round(width * b / a))
    else:
        height = MOCK_PNG_WIDTH
        width = int(round(height * a / b))
    width -= width % 2
    height -= height % 2
    return max(width, 2), max(height, 2)


def _png_rgba_rows(rows: list[bytes], width: int, height: int) -> bytes:
    raw = b"".join(rows)

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )


def png_scene(seed: str, width: int = MOCK_PNG_WIDTH, height: int = MOCK_PNG_HEIGHT) -> bytes:
    """Deterministic still. Default 16:9 960x540. Valid PNG, not scraped pixels."""
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    sky = (digest[0], digest[1], 40 + digest[2] % 80)
    ground = (digest[3] // 3, 40 + digest[4] % 70, digest[5] // 4)
    sun_x = int(width * (0.18 + (digest[6] / 255) * 0.64))
    sun_y = int(height * (0.16 + (digest[7] / 255) * 0.18))
    horizon = int(height * 0.62)
    rows: list[bytes] = []
    for y in range(height):
        line = bytearray(1 + width * 4)
        t = y / max(height - 1, 1)
        for x in range(width):
            dx = x - sun_x
            dy = y - sun_y
            glow = max(0.0, 1.0 - (dx * dx + dy * dy) / (90.0 * 90.0))
            if y < horizon:
                r = int(sky[0] * (1 - t) + glow * 140)
                g = int(sky[1] * (1 - t * 0.4) + glow * 90)
                b = int(sky[2] + (1 - t) * 80 + glow * 40)
            else:
                shade = 0.55 + 0.45 * ((x + y) % 17) / 17
                r = int(ground[0] * shade)
                g = int(ground[1] * shade)
                b = int(ground[2] * shade)
            i = 1 + x * 4
            line[i] = min(255, max(0, r))
            line[i + 1] = min(255, max(0, g))
            line[i + 2] = min(255, max(0, b))
            line[i + 3] = 255
        rows.append(bytes(line))
    return _png_rgba_rows(rows, width, height)


PNG_SWATCH = png_scene("mock")
PNG_1X1 = PNG_SWATCH
MP4_SWATCH = (Path(__file__).resolve().parent / "fixtures" / "mock.mp4").read_bytes()
_MP4_CACHE: dict[str, bytes] = {}

log = logging.getLogger("vinci.provider.mock")


def _iter_boxes(
    data: bytes, start: int = 0, end: int | None = None
) -> Iterator[tuple[bytes, bytes]]:
    if end is None:
        end = len(data)
    off = start
    while off + 8 <= end:
        size = struct.unpack(">I", data[off : off + 4])[0]
        typ = data[off + 4 : off + 8]
        hdr = 8
        if size == 1:
            if off + 16 > end:
                break
            size = struct.unpack(">Q", data[off + 8 : off + 16])[0]
            hdr = 16
        elif size == 0:
            size = end - off
        if size < 8 or off + size > end:
            break
        yield typ, data[off + hdr : off + size]
        off += size


def mp4_dimensions(blob: bytes) -> tuple[int, int] | None:
    """Read the first non-zero tkhd size from an ISO BMFF MP4."""
    for typ, payload in _iter_boxes(blob):
        if typ != b"moov":
            continue
        for trak_type, trak in _iter_boxes(payload):
            if trak_type != b"trak":
                continue
            for box_type, tkhd in _iter_boxes(trak):
                if box_type != b"tkhd" or len(tkhd) < 84:
                    continue
                version = tkhd[0]
                if version == 1 and len(tkhd) >= 96:
                    width = struct.unpack(">I", tkhd[88:92])[0] >> 16
                    height = struct.unpack(">I", tkhd[92:96])[0] >> 16
                else:
                    width = struct.unpack(">I", tkhd[76:80])[0] >> 16
                    height = struct.unpack(">I", tkhd[80:84])[0] >> 16
                if width and height:
                    return width, height
    return None


def mp4_duration_seconds(blob: bytes) -> float | None:
    """Read movie timescale/duration from the first mvhd box."""
    for typ, payload in _iter_boxes(blob):
        if typ != b"moov":
            continue
        for box_type, mvhd in _iter_boxes(payload):
            if box_type != b"mvhd" or len(mvhd) < 20:
                continue
            version = mvhd[0]
            if version == 1 and len(mvhd) >= 32:
                timescale = struct.unpack(">I", mvhd[20:24])[0]
                duration = struct.unpack(">Q", mvhd[24:32])[0]
            else:
                timescale = struct.unpack(">I", mvhd[12:16])[0]
                duration = struct.unpack(">I", mvhd[16:20])[0]
            if timescale:
                return float(duration) / float(timescale)
    return None


def _stamp_mp4(base: bytes, seed: str) -> bytes:
    payload = hashlib.sha256(seed.encode("utf-8")).digest()
    usertype = hashlib.md5(b"vinci.mock." + seed.encode("utf-8"), usedforsecurity=False).digest()
    size = 8 + 16 + len(payload)
    return base + struct.pack(">I", size) + b"uuid" + usertype + payload


def _encode_mp4(
    seed: str, width: int, height: int, duration: float = 1.0
) -> bytes | None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None
    half = max(float(duration) / 2.0, 0.1)
    with tempfile.TemporaryDirectory(prefix="vinci-mock-mp4-") as raw:
        root = Path(raw)
        (root / "a.png").write_bytes(png_scene(seed, width, height))
        (root / "b.png").write_bytes(png_scene(f"{seed}-pan", width, height))
        dest = root / "out.mp4"
        proc = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-loop",
                "1",
                "-framerate",
                "2",
                "-t",
                f"{half:.3f}",
                "-i",
                str(root / "a.png"),
                "-loop",
                "1",
                "-framerate",
                "2",
                "-t",
                f"{half:.3f}",
                "-i",
                str(root / "b.png"),
                "-filter_complex",
                f"[0:v][1:v]concat=n=2:v=1:a=0,fps=2,format=yuv420p,scale={width}:{height}",
                "-an",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(dest),
            ],
            check=False,
            capture_output=True,
        )
        if proc.returncode != 0 or not dest.is_file():
            return None
        blob = dest.read_bytes()
        if len(blob) < 8 or blob[4:8] != b"ftyp":
            return None
        return blob


def mp4_scene(
    seed: str,
    width: int = MOCK_PNG_WIDTH,
    height: int = MOCK_PNG_HEIGHT,
    duration: float = 1.0,
) -> bytes:
    """Deterministic clip. Default 16:9 960x540, ~1s. Valid MP4, not scraped pixels."""
    seconds = mock_duration_seconds(duration)
    key = hashlib.sha256(f"{seed}:{width}x{height}:{seconds:.3f}".encode()).hexdigest()
    cached = _MP4_CACHE.get(key)
    if cached is not None:
        return cached
    if (
        seed == "mock"
        and (width, height) == (MOCK_PNG_WIDTH, MOCK_PNG_HEIGHT)
        and seconds == 1.0
    ):
        blob = MP4_SWATCH
    else:
        blob = _encode_mp4(seed, width, height, seconds) or _stamp_mp4(MP4_SWATCH, seed)
    _MP4_CACHE[key] = blob
    return blob


class MockProvider(Provider):
    """Deterministic fake generations + fake pricing. For CI, tests, and demo mode."""

    durable_job_reconciliation = True

    manifest = ProviderManifest(
        id="mock",
        display_name="Mock",
        auth=ProviderAuth(env_vars=["MOCK_API_KEY"]),
        docs_url="https://github.com/tryvinci/vinci",
    )

    def __init__(self, cas: CasStore, api_key: str | None = None) -> None:
        self._cas = cas
        self._api_key = api_key
        self._catalog = load_catalog()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._estimated: set[str] = set()
        self._blobs = {
            "mock:png:v1": PNG_SWATCH,
            "mock:mp4:v1": MP4_SWATCH,
            "mock:txt:v1": b'{"text":"mock transcript"}',
        }

    def catalog(self) -> list[ModelSpec]:
        return list(self._catalog.models)

    def capabilities(self) -> set[Capability]:
        caps: set[Capability] = set()
        for model in self._catalog.models:
            caps.update(model.capabilities)
        return caps

    def estimate(self, req: JobRequest) -> Estimate:
        spec = self._resolve(req)
        key = req.idempotency_key or idempotency_key(spec.id, req.inputs)
        cached = self._cas.exists(self._digest_for(spec.id, req.inputs))
        estimate = estimate_from_spec(spec, cached=cached)
        self._estimated.add(key)
        log.info("estimate model=%s amount=%s cached=%s", spec.id, estimate.amount, cached)
        return estimate

    def submit(self, req: JobRequest) -> ProviderJobRef:
        counter_path = os.environ.get("VINCI_TEST_MOCK_SUBMIT_COUNTER_PATH")
        if counter_path:
            p = Path(counter_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            n = int(p.read_text(encoding="utf-8").strip() or "0") if p.is_file() else 0
            p.write_text(str(n + 1), encoding="utf-8")
        spec = self._resolve(req)
        key = req.idempotency_key or idempotency_key(spec.id, req.inputs)
        if key not in self._estimated:
            raise RuntimeError("estimate() must be called before submit()")
        extra_values = [self._api_key] if self._api_key else []
        safe_inputs = redact_mapping(req.inputs, extra_values=extra_values)
        log.info("submit model=%s inputs=%s", spec.id, safe_inputs)
        digest = self._cas.put(self._blob(spec.id, req.inputs))
        ref = str(uuid.uuid4())
        self._jobs[ref] = {
            "state": JobState.COMPLETED.value,
            "outputs": [digest],
            "model_id": spec.id,
            "key": key,
        }
        return ProviderJobRef(provider="mock", ref=ref)

    def status(self, ref: ProviderJobRef) -> JobStatus:
        job = self._jobs.get(ref.ref)
        if job is None:
            return JobStatus(
                state=JobState.FAILED,
                error=VinciError(code=ErrorCode.UNKNOWN, message="unknown job"),
            )
        state = JobState(job["state"])
        return JobStatus(state=state, outputs=list(job["outputs"]), progress=1.0)

    def cancel(self, ref: ProviderJobRef) -> None:
        job = self._jobs.get(ref.ref)
        if job is not None:
            job["state"] = JobState.CANCELLED.value

    def normalize_error(self, exc: BaseException) -> VinciError:
        if isinstance(exc, PermissionError):
            return VinciError(code=ErrorCode.AUTH, message="auth failed", retryable=False)
        if isinstance(exc, TimeoutError):
            return VinciError(code=ErrorCode.TIMEOUT, message="timeout", retryable=True)
        if isinstance(exc, ValueError):
            return VinciError(code=ErrorCode.INVALID_INPUT, message=str(exc), retryable=False)
        if isinstance(exc, FileNotFoundError):
            return VinciError(code=ErrorCode.PROVIDER_DOWN, message="missing", retryable=True)
        return VinciError(code=ErrorCode.UNKNOWN, message=type(exc).__name__, retryable=False)

    def _resolve(self, req: JobRequest) -> ModelSpec:
        if req.model_id:
            return self._catalog.by_id(req.model_id)
        spec = self._catalog.cheapest(req.capability.value)
        if spec is None:
            raise ValueError(f"no mock model for {req.capability}")
        return spec

    def _blob(self, model_id: str, inputs: dict[str, object]) -> bytes:
        prompt = compose_shot_prompt(inputs) or "mock"
        width, height = mock_dimensions(inputs.get("aspect_ratio"))
        if model_id == "mock:png:v1":
            return png_scene(prompt, width, height)
        if model_id == "mock:mp4:v1":
            return mp4_scene(prompt, width, height, mock_duration_seconds(inputs.get("duration")))
        return self._blobs[model_id] + b"\n" + prompt.encode("utf-8")

    def _digest_for(self, model_id: str, inputs: dict[str, object]) -> str:
        return ContentAddressedStore.digest(self._blob(model_id, inputs))
