"""Camera moves over a held drawing: the "engine move" of the OLF movie engine.

TV anime often makes a shot from one drawing with camera work on top: a track up, a pan, a
shake. ``camera_move`` does the same from one still, with no video model. Pillow draws each
frame, because it places the crop window at parts of a pixel (a slow move needs that), and
ffmpeg encodes the frames.
"""

from __future__ import annotations

import logging
import random
import subprocess
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path
from typing import Any

from vinci_media.encoders import pick_video_encoder
from vinci_media.episode import BITRATE
from vinci_media.ops import FFMPEG, MediaError, require_ffmpeg

log = logging.getLogger(__name__)
MOVES = ("static", "push_in", "pull_out", "pan", "tilt", "truck", "shake")  # moves a still can do
EASES = {  # fairing: progress 0..1 of the move -> progress of the window
    "none": lambda t: t,
    "in": lambda t: t * t,
    "out": lambda t: 1 - (1 - t) ** 2,
    "in_out": lambda t: t * t * (3 - 2 * t),
}
Window = tuple[float, float, float, float]  # left, top, width, height, in drawing pixels
MAX_SIDE, MAX_FPS, MAX_SECONDS = 4096, 60, 120  # a frame is drawn in memory: keep it bounded


def check(width: int, height: int, fps: float, seconds: float) -> None:
    """Refuse a video that this module should not draw: each frame is a full image in memory,
    and the sizes can come from a show file that nobody checked.

    Raises:
        MediaError: A side over 4096 px, an fps over 60, or a length over 120 s (or under 0).
    """
    if not (16 <= width <= MAX_SIDE and 16 <= height <= MAX_SIDE):
        raise MediaError(
            f"a camera move draws frames of 16 to {MAX_SIDE} px a side, not {width}x{height}"
        )
    if not 1 <= fps <= MAX_FPS:
        raise MediaError(f"a camera move draws 1 to {MAX_FPS} frames a second, not {fps:g}")
    if not 0 < seconds <= MAX_SECONDS:
        raise MediaError(f"a camera move lasts up to {MAX_SECONDS} s, not {seconds:g} s")


def windows(
    drawing: tuple[int, int],
    frame: tuple[int, int],
    move: str = "static",
    *,
    direction: str | None = None,
    amount: float | None = None,
    center: Sequence[float] | None = None,
    canvas: str | None = None,
) -> tuple[Window, Window]:
    """Return the windows of the drawing that the first and the last frame show.

    The base window is the largest window of the frame's shape, at the centre of the drawing.

    Args:
        drawing: Width and height of the still.
        frame: Width and height of the video frame.
        move: One of ``MOVES``.
        direction: ``left`` or ``right`` for a pan or a truck (default ``right``), ``up`` or
            ``down`` for a tilt (default ``up``): where the frame goes.
        amount: Push and pull: the part of the frame the move removes (default 0.2). Pan, tilt
            and truck: travel in frame widths or heights. With ``canvas``, a drawing larger
            than the frame on that axis gives the room, and with no amount the window goes
            from one edge to the other. Where the room is too small, and with no ``canvas``
            (default 0.2), the window gets smaller by the travel and stays in the base window.
            Shake: size as a part of the frame height (default 0.02).
        center: The point a push ends on, ``[x, y]`` from 0 to 1 in the base window.
        canvas: The shot's ``camera.canvas`` (``21:9``): the drawing is larger than the frame
            on purpose. With no canvas, a pan over a drawing of another shape (a square
            keyframe in a 16:9 show) keeps the move it had before canvases.

    Raises:
        MediaError: The move is not one a still can do.
    """
    if move not in MOVES:
        raise MediaError(f"a still cannot do a {move} move: use one of {', '.join(MOVES)}")
    (dw, dh), (fw, fh) = drawing, frame
    bw = min(dw, dh * fw / fh)
    bh = bw * fh / fw
    left, top = (dw - bw) / 2, (dh - bh) / 2
    base = (left, top, bw, bh)
    size = float(amount) if amount else (0.02 if move == "shake" else 0.2)
    if move in ("push_in", "pull_out"):
        w, h = bw * (1 - min(size, 0.95)), bh * (1 - min(size, 0.95))
        cx, cy = center or (0.5, 0.5)
        small = (  # the window around the centre point, kept inside the base window
            min(max(left + cx * bw - w / 2, left), left + bw - w),
            min(max(top + cy * bh - h / 2, top), top + bh - h),
            w,
            h,
        )
        return (base, small) if move == "push_in" else (small, base)
    if move == "shake":
        k = 1 - 2 * min(size, 0.2)  # room for the shake on each side
        inner = (left + bw * (1 - k) / 2, top + bh * (1 - k) / 2, bw * k, bh * k)
        return inner, inner
    if move == "static":
        return base, base
    # A pan, a tilt or a truck slides the window along one axis of the drawing.
    tall = move == "tilt"
    room, side = (dh, bh) if tall else (dw, bw)  # the drawing and the base window on that axis
    # The travel a full-size window has, in frame widths or heights. Only a canvas gives room:
    # the same keyframe, camera and engine version must give the same move (PR-Agent, #530).
    spare = room / side - 1 if canvas else 0.0
    travel = float(amount) if amount else (spare if spare > 0.01 else 0.2)
    k = min(1.0, (1 + spare) / (1 + travel))  # too little room: the window gets smaller
    w, h = bw * k, bh * k
    span = (h if tall else w) * (1 + travel)  # the window plus its travel, centred on the drawing
    if tall:
        x, y = (dw - w) / 2, (dh - span) / 2
        high, low = (x, y, w, h), (x, y + span - h, w, h)
        return (high, low) if direction == "down" else (low, high)
    x, y = (dw - span) / 2, (dh - h) / 2
    west, east = (x, y, w, h), (x + span - w, y, w, h)
    return (east, west) if direction == "left" else (west, east)


def drawing_size(path: Path) -> tuple[int, int]:
    """Return the width and height of a still, for each format Pillow reads (PNG, JPEG, WebP).

    Raises:
        OSError: The file is not an image that Pillow reads.
    """
    # Imported here, as in episode.py: `import vinci_media` must work without Pillow. Bug fixed
    # (first occurrence 2026-11-12, the first CI run after the Actions lock): the Adapts compute
    # image installs vinci_media with no Pillow, and its self-test failed (no module named PIL).
    from PIL import Image

    with Image.open(path) as image:
        return image.size


def upscale(
    drawing: tuple[int, int],
    frame: tuple[int, int],
    move: str = "static",
    *,
    amount: float | None = None,
    center: Sequence[float] | None = None,
    canvas: str | None = None,
) -> float:
    """Return how much the smallest window of a move is enlarged to fill the frame (1.0 = none)."""
    first, last = windows(drawing, frame, move, amount=amount, center=center, canvas=canvas)
    return frame[0] / min(first[2], last[2])


def track(
    start: Window,
    end: Window,
    frames: int,
    *,
    hold_start: int = 0,
    hold_end: int = 0,
    ease: str = "none",
    shake: float = 0.0,
    seed: str = "",
) -> list[Window]:
    """Return the window of each frame: ``start`` in the first hold, then the move, then ``end``.

    Args:
        start: The window of the first frame.
        end: The window of the last frame.
        frames: The number of frames.
        hold_start: Frames with no move at the start.
        hold_end: Frames with no move at the end.
        ease: One of ``EASES`` (fairing).
        shake: The largest shake offset, in drawing pixels. It fades out toward the end of the
            move, and it is the same for the same ``seed``.
        seed: Makes a shake repeatable.

    Raises:
        MediaError: The ease is not known.
    """
    if ease not in EASES:
        raise MediaError(f"ease must be one of {', '.join(EASES)}, not {ease!r}")
    first, last = hold_start, frames - hold_end  # the move runs on frames first..last-1
    rng = random.Random(seed)
    out: list[Window] = []
    for frame in range(frames):
        moving = first <= frame < last
        if frame < first:
            t = 0.0
        elif not moving or last - first < 2:
            t = 1.0
        else:
            t = (frame - first) / (last - first - 1)
        k = EASES[ease](t)
        x, y, w, h = (a + (b - a) * k for a, b in zip(start, end, strict=True))
        if shake and moving:
            x += rng.uniform(-1, 1) * shake * (1 - t)
            y += rng.uniform(-1, 1) * shake * (1 - t)
        out.append((x, y, w, h))
    return out


def progress(frames: int, **timing: Any) -> list[float]:
    """How far a move is at each frame, from 0 to 1, with the holds and the fairing of ``track``
    (``hold_start``, ``hold_end``, ``ease``). Pills that move in a previs clip use it."""
    return [x for x, _, _, _ in track((0.0, 0.0, 0.0, 0.0), (1.0, 0.0, 0.0, 0.0), frames, **timing)]


def encode(frames: Iterable[bytes], dst: Path, *, width: int, height: int, fps: float) -> Path:
    """Write raw RGB frames (``width`` x ``height``, 3 bytes a pixel) as a silent MP4. The
    caller checks the size and the length first (``check``).

    Raises:
        MediaError: ffmpeg fails. An error that ``frames`` raises stops ffmpeg first.
    """
    require_ffmpeg()
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [FFMPEG, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24"]
    cmd += ["-s", f"{width}x{height}", "-r", f"{fps:g}", "-i", "-"]
    cmd += ["-c:v", pick_video_encoder(), "-b:v", BITRATE, "-pix_fmt", "yuv420p", str(dst)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdin is not None
    try:
        for data in frames:
            proc.stdin.write(data)
    except BrokenPipeError:
        pass  # ffmpeg stopped: its own words follow
    except BaseException:  # a frame failed to draw: stop ffmpeg, do not leave it waiting
        proc.kill()
        proc.communicate()
        raise
    _, err = proc.communicate()
    if proc.returncode != 0:
        raise MediaError(err.decode(errors="replace").strip()[-600:] or "ffmpeg encode failed")
    return dst


def camera_move(
    src: Path,
    dst: Path,
    *,
    width: int,
    height: int,
    seconds: float,
    fps: float = 24,
    move: str = "static",
    direction: str | None = None,
    amount: float | None = None,
    ease: str = "none",
    hold_start: float = 0.0,
    hold_end: float = 0.0,
    center: Sequence[float] | None = None,
    seed: str = "",
    canvas: str | None = None,
) -> Path:
    """Write a silent video of ``src`` (a still) under a camera move.

    The frame count is exact: ``seconds`` times ``fps``, rounded. The move runs between the two
    holds (``track``).

    Args:
        src: The still (a keyframe).
        dst: The MP4 to write.
        width: Frame width.
        height: Frame height.
        seconds: Length of the video.
        fps: Frames a second (a project can state 23.976).
        move: One of ``MOVES`` (see ``windows`` for ``direction``, ``amount`` and ``center``).
        direction: Where the frame goes.
        amount: How far the move goes.
        ease: One of ``EASES`` (fairing).
        hold_start: Seconds with no move at the start.
        hold_end: Seconds with no move at the end.
        center: The point a push ends on.
        seed: Makes a shake repeatable.
        canvas: The shot's ``camera.canvas``: a pan, a tilt or a truck uses the room of a
            drawing larger than the frame (``windows``).

    Raises:
        MediaError: A wrong move or ease, a size or length over the limits (``check``), or
            ffmpeg fails.
    """
    from PIL import Image  # imported here: see drawing_size

    require_ffmpeg()
    check(width, height, fps, seconds)
    with Image.open(src) as opened:
        image = opened.convert("RGB")
    start, end = windows(
        image.size,
        (width, height),
        move,
        direction=direction,
        amount=amount,
        center=center,
        canvas=canvas,
    )
    size = min(float(amount) if amount else 0.02, 0.2)
    path = track(
        start,
        end,
        max(round(seconds * fps), 1),
        hold_start=round(hold_start * fps),
        hold_end=round(hold_end * fps),
        ease=ease,
        shake=size * start[3] / (1 - 2 * size) if move == "shake" else 0.0,  # drawing pixels
        seed=seed,
    )

    def drawn() -> Iterator[bytes]:
        shown: tuple[Window, bytes] | None = None  # a hold shows one window: draw it one time
        for x, y, w, h in path:
            if shown is None or shown[0] != (x, y, w, h):
                data = image.transform(
                    (width, height),
                    Image.Transform.AFFINE,
                    (w / width, 0, x, 0, h / height, y),
                    Image.Resampling.BICUBIC,
                ).tobytes()
                shown = ((x, y, w, h), data)
            yield shown[1]

    encode(drawn(), dst, width=width, height=height, fps=fps)
    log.info(
        "camera move %s: %d frames %dx%d at %g fps from a %dx%d still -> %s",
        move,
        len(path),
        width,
        height,
        fps,
        *image.size,
        dst.name,
    )
    return dst
