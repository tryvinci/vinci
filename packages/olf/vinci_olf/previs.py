"""Previs of an episode: the e-conte sheet and the animatic (SPEC.md, Previs).

Both cost $0, because no model runs. Each shot shows the best picture it has: its chosen video,
else its chosen keyframe, else pills (``vinci_olf.layout``). Pillow draws the sheet (PNG pages
and one PDF, so no new dependency), and the camera move of ``vinci_media`` with ffmpeg makes the
animatic. The files go in ``previs/<episode>/``: derived output, not in the lock file and not
in the Share zip, made again on request, as ``exports/`` is.
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from vinci_olf.cut import dialogue_take, play_order, takes
from vinci_olf.layout import staging
from vinci_olf.project import FRAMES, OlfError, Project, frames
from vinci_olf.resolve import resolve

log = logging.getLogger(__name__)
CUTS = 5  # cuts on one page of the sheet (the e-conte layout)
PAGE = (1240, 1754)  # A4 portrait at 150 dpi
COLUMNS = (("Cut", 140), ("Picture", 460), ("Action", 250), ("Dialogue", 200), ("Time", 70))
SLOTS = {"a": "#1c9fb8", "b": "#e08a00", "c": "#c2255c"}  # the stripe of each cast slot
PAPER, INK, MUTED, LINE, MARK = "#f5f2ea", "#1d232b", "#6b7480", "#d3d5d8", "#d6336c"
WIDTH = 960  # the animatic is a copy to review: half the width of a 1080p frame
Box = tuple[float, float, float, float]  # left, top, width, height


def previs(
    p: Project,
    episode_id: str,
    *,
    sheet: bool = True,
    animatic: bool = True,
    mock: bool = False,
) -> dict[str, Any]:
    """Make the e-conte sheet, the animatic and/or the mock render of an episode in
    ``previs/<episode>/``. The mock render (``write_mock``) has one look for every cut.

    Returns:
        ``{"files": [project-relative paths], "cuts": n, "runtime": seconds}``.

    Raises:
        OlfError: The episode is missing or has no shots, a shot does not resolve, or a
            layout is off the schema (the show has errors).
    """
    shots = play_order(p, episode_id)
    if not shots:
        raise OlfError(f"{episode_id} has no shots yet")
    views = {shot: resolve(p, shot) for shot in shots}
    try:
        plans = staging(p, views)
    except Exception as exc:  # a layout off the schema (`slot: d`): a reason, not HTTP 500
        from vinci_olf.validate import validate

        if not any(i.level == "error" for i in validate(p)):
            raise  # a valid show: an engine bug
        raise OlfError(
            f"previs of {episode_id} stopped: fix the errors that validate lists first ({exc!r})"
        ) from exc
    from vinci_media import MediaError

    out = p.inside(p.root / "previs" / episode_id)
    out.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    try:
        if sheet:
            files += write_sheet(p, episode_id, views, plans, out)
        if animatic:
            files.append(write_animatic(p, views, plans, out / f"{episode_id}-animatic.mp4"))
        if mock:
            files.append(write_mock(p, views, plans, out / f"{episode_id}-mock.mp4"))
    except MediaError as exc:  # no ffmpeg, a shot over the limits: say why
        raise OlfError(f"previs of {episode_id} stopped: {exc}") from exc
    runtime = sum(float(view.get("duration") or 0) for view in views.values())
    log.info("previs %s: %d cuts, %.2f s -> %s", episode_id, len(shots), runtime, files)
    return {"files": [p.rel(f) for f in files], "cuts": len(shots), "runtime": runtime}


def best_take(p: Project, shot_id: str, kind: str) -> Path | None:
    """The file of a shot's chosen take of ``kind`` (``select``), else of its newest take of
    that kind that is not rejected, else None."""
    chosen = (p.docs[shot_id].data.get("select") or {}).get(kind)
    ids = [f"{shot_id}/{chosen}"] if chosen else []
    ids += [
        t for t in reversed(takes(p, shot_id, kind)) if p.docs[t].data.get("status") != "rejected"
    ]
    for take_id in ids:
        take = p.docs.get(take_id)
        output = str((take.data.get("output") if take else None) or "")
        try:
            if output:
                return p.local_file(output)
        except OlfError as exc:  # a missing file: the next take, else pills
            log.warning("previs %s: %s", take_id, exc)
    return None


def _font(size: int) -> Any:
    """The sheet's font at ``size`` px: the font file of ffmpeg's text, else Pillow's own."""
    from vinci_media.ops import _fontfile

    path = _fontfile()
    return ImageFont.truetype(path, size) if path else ImageFont.load_default(size)


def _drawing(frame: tuple[int, int], aspect: str) -> tuple[int, int]:
    """The size of a drawing of shape ``aspect`` whose largest frame-shaped window is ``frame``."""
    w, _, h = str(aspect).partition(":")
    shape = int(w) / int(h) if w.isdigit() and h.isdigit() and int(w) and int(h) else 16 / 9
    shape = min(max(shape, 1 / 4), 4.0)  # `canvas: 1:1000` asked for a 2.7 GB picture (#530)
    fw, fh = frame
    return (round(fh * shape), fh) if shape > fw / fh else (fw, round(fw / shape))


def _windows(camera: dict[str, Any], drawing: tuple[int, int], frame: tuple[int, int]) -> Any:
    """The first and the last window of the shot's camera move. A move that a still cannot do
    (a dolly, an orbit) keeps the first window: the model makes that move, not the engine."""
    from vinci_media import MediaError
    from vinci_media.camera import windows

    keys = {k: camera.get(k) for k in ("direction", "amount", "center", "canvas")}
    try:
        return windows(drawing, frame, camera.get("move") or "static", **keys)
    except MediaError:
        return windows(drawing, frame)


def _placed(pills: list[dict[str, Any]], window: Box) -> dict[str, dict[str, Any]]:
    """Pills of a frame (0 to 1) in drawing pixels, when the frame shows ``window``."""
    x, y, w, h = window
    return {
        pill["slot"]: pill
        | {"x": x + pill["x"] * w, "y": y + pill["y"] * h, "size": pill["size"] * h}
        for pill in pills
    }


def _pill(draw: Any, pill: dict[str, Any], x: float, eye: float, head: float, ghost: bool) -> None:
    """Draw one pill: a body 7 heads tall with the stripe of its slot, and a white dot at the
    eye line on the side it looks to (no dot when it looks away). A ghost is the end place."""
    color = str(pill.get("color") or SLOTS.get(str(pill["slot"]), MUTED))
    wide, top = head * 1.6, eye - head * 0.6
    box = (x - wide / 2, top, x + wide / 2, top + head * 7)
    if ghost:
        draw.rounded_rectangle(box, radius=wide / 2, outline=color, width=2)
        return
    draw.rounded_rectangle(
        box, radius=wide / 2, fill="#dfe3e8", outline=color, width=max(2, round(head * 0.06))
    )
    band = top + head * 2.2
    draw.rectangle((box[0] + 1, band, box[2] - 1, band + head * 0.5), fill=color)
    if pill.get("facing") != "away":
        dot = x + {"left": -0.28, "right": 0.28}.get(str(pill.get("facing")), 0.0) * wide
        r = max(2.0, head * 0.12)
        draw.ellipse((dot - r, eye - r, dot + r, eye + r), fill="white", outline=INK)
    if head >= 24 and pill.get("name"):  # the first name, on the forehead: clear of subtitles
        size = max(10, min(28, round(head * 0.3)))
        name = str(pill["name"]).split()[0]
        draw.text((x, eye - head * 0.32), name, font=_font(size), fill=INK, anchor="mm")


def _scene(
    size: tuple[int, int],
    window: Box,
    drawing: tuple[int, int],
    pills: list[dict[str, Any]],
    ghosts: list[dict[str, Any]] | None = None,
) -> Image.Image:
    """Draw the part ``window`` of a pill drawing: a grid on paper (so a camera move shows) and
    the pills, given in drawing pixels. The near pills (the large ones) are drawn last."""
    image = Image.new("RGB", size, PAPER)
    draw = ImageDraw.Draw(image)
    (x0, y0, ww, wh), (dw, dh) = window, drawing
    sx, sy = size[0] / ww, size[1] / wh
    for k in range(1, 16):
        gx = (k * dw / 16 - x0) * sx
        draw.line((gx, 0, gx, size[1]), fill=LINE, width=1)
    for k in range(1, 8):
        gy = (k * dh / 8 - y0) * sy
        draw.line((0, gy, size[0], gy), fill=LINE, width=1)
    horizon = (dh * 0.55 - y0) * sy
    draw.line((0, horizon, size[0], horizon), fill=MUTED, width=2)
    for pill in ghosts or []:
        _pill(draw, pill, (pill["x"] - x0) * sx, (pill["y"] - y0) * sy, pill["size"] * sy, True)
    for pill in sorted(pills, key=lambda pill: float(pill["size"])):
        _pill(draw, pill, (pill["x"] - x0) * sx, (pill["y"] - y0) * sy, pill["size"] * sy, False)
    return image


def pill_frames(
    plan: dict[str, Any], camera: dict[str, Any], frame: tuple[int, int], count: int
) -> Iterator[Image.Image]:
    """The frames of a pill clip: the pills go from ``start`` to ``end`` while the camera makes
    the shot's move, with its holds and its fairing. With no ``end``, the pills stay where they
    are in the drawing, so the camera move alone changes them in the frame (a push enlarges
    them)."""
    from vinci_media import MediaError
    from vinci_media.camera import progress, track

    drawing = _drawing(frame, plan["aspect"])
    first, last = _windows(camera, drawing, frame)
    timing: dict[str, Any] = {
        "hold_start": round(float(camera.get("hold_start") or 0) * FRAMES),
        "hold_end": round(float(camera.get("hold_end") or 0) * FRAMES),
        "ease": camera.get("ease") or "none",
    }
    try:
        path, done = track(first, last, count, **timing), progress(count, **timing)
    except MediaError:  # an ease that the schema refuses: no fairing
        timing["ease"] = "none"
        path, done = track(first, last, count, **timing), progress(count, **timing)
    begin = _placed(plan["start"], first)
    end = _placed(plan["end"], last) if plan["end"] is not None else begin
    for window, k in zip(path, done, strict=True):
        pills = [
            pill
            | {key: pill[key] + (end[slot][key] - pill[key]) * k for key in ("x", "y", "size")}
            | {"facing": (end[slot] if k >= 0.5 else pill)["facing"]}
            for slot, pill in begin.items()
            if slot in end
        ]
        yield _scene(frame, window, drawing, pills)


def _picture(
    p: Project, shot_id: str, view: dict[str, Any], plan: dict[str, Any], frame: tuple[int, int]
) -> tuple[Image.Image, Box, Box]:
    """The picture of a shot on the sheet: the whole drawing (its keyframe, a frame of its
    video, or its pills), and the first and the last window of its camera move on it."""
    camera = view.get("camera") or {}
    if (image := _still(p, shot_id)) is not None:
        first, last = _windows(camera, image.size, frame)
        return image, first, last
    drawing = _drawing(frame, plan["aspect"])
    first, last = _windows(camera, drawing, frame)
    pills = list(_placed(plan["start"], first).values())
    ghosts = list(_placed(plan["end"], last).values()) if plan["end"] else []
    k = 960 / drawing[0]  # the picture is 960 px wide: drawing pixels times k
    image = _scene((960, round(drawing[1] * k)), (0, 0, *drawing), drawing, pills, ghosts)
    return image, (first[0] * k, first[1] * k, first[2] * k, first[3] * k), (
        last[0] * k, last[1] * k, last[2] * k, last[3] * k
    )  # fmt: skip


def _still(p: Project, shot_id: str) -> Image.Image | None:
    """The shot's keyframe, else the first frame of its video, or None (then pills)."""
    from vinci_media.ops import FFMPEG

    try:
        if (path := best_take(p, shot_id, "keyframe")) is not None:
            with Image.open(path) as opened:
                return opened.convert("RGB")
        if (video := best_take(p, shot_id, "video")) is not None:
            with tempfile.TemporaryDirectory(prefix="olf-previs-") as raw:
                target = Path(raw) / "frame.png"
                cmd = [FFMPEG, "-y", "-v", "error", "-i", str(video), "-frames:v", "1"]
                subprocess.run([*cmd, str(target)], check=True, capture_output=True)
                with Image.open(target) as opened:
                    return opened.convert("RGB")
    except (OSError, subprocess.CalledProcessError) as exc:  # no picture Pillow reads: pills
        log.warning("previs %s: no picture (%s), so pills", shot_id, exc)
    return None


def _dashed(draw: Any, box: Box, color: str, width: int, dash: float = 14) -> None:
    """A dashed rectangle: Pillow draws no dashed lines."""
    x, y, w, h = box
    for a, b in (
        ((x, y), (x + w, y)),
        ((x + w, y), (x + w, y + h)),
        ((x + w, y + h), (x, y + h)),
        ((x, y + h), (x, y)),
    ):
        length = max(abs(b[0] - a[0]), abs(b[1] - a[1]))
        for i in range(0, int(length), int(dash * 2)):
            t0, t1 = i / length, min(i + dash, length) / length
            draw.line(
                (
                    a[0] + (b[0] - a[0]) * t0,
                    a[1] + (b[1] - a[1]) * t0,
                    a[0] + (b[0] - a[0]) * t1,
                    a[1] + (b[1] - a[1]) * t1,
                ),
                fill=color,
                width=width,
            )


def _cell(image: Image.Image, first: Box, last: Box, size: tuple[int, int]) -> Image.Image:
    """Fit a picture into a cell of the sheet, with the frame marks of the move: the first
    window solid, the last window dashed, and an arrow from one to the other."""
    cell = Image.new("RGB", size, "white")
    scale = min(size[0] / image.width, size[1] / image.height)
    shown = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))))
    left, top = (size[0] - shown.width) // 2, (size[1] - shown.height) // 2
    cell.paste(shown, (left, top))
    draw = ImageDraw.Draw(cell)
    a, b = (
        (left + x * scale, top + y * scale, w * scale, h * scale) for x, y, w, h in (first, last)
    )
    whole = (left, top, shown.width, shown.height)
    if any(abs(u - v) > 1 for u, v in zip(a, whole, strict=True)):
        draw.rectangle((a[0], a[1], a[0] + a[2], a[1] + a[3]), outline=MARK, width=3)
    if any(abs(u - v) > 1 for u, v in zip(a, b, strict=True)):
        _dashed(draw, b, MARK, 3)
        start, stop = (a[0] + a[2] / 2, a[1] + a[3] / 2), (b[0] + b[2] / 2, b[1] + b[3] / 2)
        if abs(start[0] - stop[0]) + abs(start[1] - stop[1]) > 8:  # a pan, a tilt or a truck
            draw.line((*start, *stop), fill=MARK, width=4)
            draw.ellipse((stop[0] - 7, stop[1] - 7, stop[0] + 7, stop[1] + 7), fill=MARK)
    return cell


def _wrap(text: str, font: Any, width: float) -> list[str]:
    """Wrap text to a width in pixels."""
    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    lines: list[str] = []
    for paragraph in text.split("\n"):
        line = ""
        for word in paragraph.split():
            trial = f"{line} {word}".strip()
            if line and measure.textlength(trial, font=font) > width:
                lines.append(line)
                line = word
            else:
                line = trial
        lines.append(line)
    return lines


def _runtime(seconds: float) -> str:
    """A runtime as minutes, seconds and frames: ``3:12+08``."""
    minutes, rest = divmod(round(seconds * FRAMES), 60 * FRAMES)
    return f"{minutes}:{rest // FRAMES:02d}+{rest % FRAMES:02d}"


def _action(view: dict[str, Any]) -> str:
    """The Action column: the description, then the camerawork and the move."""
    camera = view.get("camera") or {}
    found = camera.get("template")
    template: dict[str, Any] = found if isinstance(found, dict) else {}
    move = " ".join(str(camera[k]) for k in ("move", "direction") if camera.get(k))
    how = "engine" if camera.get("render") == "engine" else None
    parts = [str(camera.get("framing") or "").replace("_", " "), move.replace("_", " "), how]
    text = str(view.get("description") or "")
    if template.get("id"):
        text += f"\n[{template['id']}]"
    return text + "\n" + " · ".join(x for x in parts if x)


def write_sheet(
    p: Project,
    episode_id: str,
    views: dict[str, dict[str, Any]],
    plans: dict[str, dict[str, Any]],
    out: Path,
) -> list[Path]:
    """Draw the e-conte sheet: 5 cuts a page, as PNG pages and one PDF.

    Each row has the cut number (its place in play order: ``C-012``), the picture with the
    frame marks of the move, the action, the dialogue and the time (``3+00``). Each page ends
    with its time and the running total; the last page also has the cut count and the runtime.
    """
    defaults = p.manifest.get("defaults") or {}
    w, _, h = str(defaults.get("resolution") or "1920x1080").partition("x")
    frame = (int(w), int(h)) if w.isdigit() and h.isdigit() and int(w) and int(h) else (1920, 1080)
    small, body, head = _font(20), _font(22), _font(30)
    shots = list(views)
    pages: list[Image.Image] = []
    total = 0.0
    title = str(p.manifest.get("title") or p.manifest.get("show") or p.root.name)
    episode = str(p.docs[episode_id].data.get("title") or "")
    count = -(-len(shots) // CUTS)
    margin, top, row = 60, 200, (PAGE[1] - 200 - 150) // CUTS
    lefts = [margin + sum(width for _, width in COLUMNS[:i]) for i in range(len(COLUMNS))]
    for n in range(count):
        page = Image.new("RGB", PAGE, "white")
        draw = ImageDraw.Draw(page)
        draw.text((margin, 60), f"{title} · {episode_id} {episode}".strip(), font=head, fill=INK)
        draw.text(
            (PAGE[0] - margin, 70),
            f"E-conte · page {n + 1} of {count}",
            font=small,
            fill=MUTED,
            anchor="ra",
        )
        for (name, _), left in zip(COLUMNS, lefts, strict=True):
            draw.text((left + 8, top - 36), name, font=small, fill=MUTED)
        draw.line((margin, top - 6, PAGE[0] - margin, top - 6), fill=INK, width=2)
        start = total
        for i, shot in enumerate(shots[n * CUTS : (n + 1) * CUTS]):
            view, y = views[shot], top + i * row
            length = float(view.get("duration") or 0)
            total += length
            image, first, last = _picture(p, shot, view, plans[shot], frame)
            picture = _cell(image, first, last, (COLUMNS[1][1] - 16, row - 16))
            page.paste(picture, (lefts[1] + 8, y + 8))
            names = {c["id"]: c.get("name") or c["id"] for c in view.get("characters") or []}
            said = [line for line in view.get("dialogue") or [] if isinstance(line, dict)]
            lines = [
                f"{str(names.get(line.get('speaker'), line.get('speaker'))).split()[0].upper()}: "
                f"{line.get('line')}"
                for line in said
            ]
            cells = (
                (f"C-{n * CUTS + i + 1:03d}", 0, head),
                (_action(view), 2, body),
                ("\n".join(lines), 3, body),
                (frames(length), 4, body),
            )
            for text, column, font in cells:
                width = COLUMNS[column][1] - 16
                rows = _wrap(text, font, width)[: (row - 16) // (font.size + 6)]
                at = (lefts[column] + 8, y + 12)
                draw.multiline_text(at, "\n".join(rows), font=font, fill=INK, spacing=6)
            draw.text((margin + 8, y + 56), shot, font=_font(17), fill=MUTED)
            draw.line((margin, y + row, PAGE[0] - margin, y + row), fill=LINE, width=1)
        foot = f"Page {frames(total - start)} · running total {frames(total)}"
        if n == count - 1:
            foot += f" · {len(shots)} cuts · runtime {_runtime(total)}"
        draw.text((PAGE[0] - margin, PAGE[1] - 110), foot, font=body, fill=INK, anchor="ra")
        pages.append(page)
    files = []
    for n, page in enumerate(pages, 1):
        files.append(out / f"{episode_id}-sheet-{n:02d}.png")
        page.save(files[-1])
    pdf = out / f"{episode_id}-sheet.pdf"
    pages[0].save(pdf, save_all=True, append_images=pages[1:], resolution=150)
    return [pdf, *files]


def write_animatic(
    p: Project, views: dict[str, dict[str, Any]], plans: dict[str, dict[str, Any]], dst: Path
) -> Path:
    """Write the animatic: the episode in play order, each shot for its length, from the best
    picture it has (its chosen video, else its keyframe under its camera move, else its pill
    clip), with its chosen dialogue take as the sound."""
    from vinci_media import camera_move, join_clips, normalize_clip
    from vinci_media.camera import MOVES, check, encode

    frame, fps = _review_frame(p)
    with tempfile.TemporaryDirectory(prefix="olf-animatic-") as raw:
        tmp, parts = Path(raw), []
        for i, (shot, view) in enumerate(views.items()):
            camera, length = view.get("camera") or {}, float(view.get("duration") or 0)
            check(*frame, fps, length)
            source, how = best_take(p, shot, "video"), "video"
            if source is None and (still := best_take(p, shot, "keyframe")) is not None:
                move = str(camera["move"]) if camera.get("move") in MOVES else "static"
                keys = ("direction", "amount", "ease", "hold_start", "hold_end", "center", "canvas")
                source, how = tmp / f"move{i}.mp4", "keyframe"
                fields = {k: camera[k] for k in keys if camera.get(k) is not None}
                camera_move(
                    still, source, width=frame[0], height=frame[1], seconds=length, fps=fps,
                    move=move, seed=shot, **fields,
                )  # fmt: skip
            if source is None:
                source, how = tmp / f"pills{i}.mp4", "pills"
                count = max(round(length * fps), 1)
                pictures = (im.tobytes() for im in pill_frames(plans[shot], camera, frame, count))
                encode(pictures, source, width=frame[0], height=frame[1], fps=fps)
            speech = dialogue_take(p, shot)
            sound = p.inside(p.root / speech["file"]) if speech and speech.get("file") else None
            log.info("animatic %s: %s, %.3f s%s", shot, how, length, " + dialogue" * bool(sound))
            parts.append(
                normalize_clip(source, tmp / f"clip{i}.mp4", 0, length, *frame, fps, audio=sound)
            )
        dst.parent.mkdir(parents=True, exist_ok=True)
        join_clips(parts, ["cut"] * len(parts), dst)
    return dst


def _review_frame(p: Project) -> tuple[tuple[int, int], int]:
    """The frame of a review video (960 px wide, the project shape, even sides) and its fps."""
    defaults = p.manifest.get("defaults") or {}
    w, _, h = str(defaults.get("resolution") or "1920x1080").partition("x")
    shape = int(h) / int(w) if w.isdigit() and h.isdigit() and int(w) and int(h) else 9 / 16
    return (WIDTH, round(WIDTH * shape / 2) * 2), int(defaults.get("fps") or 24)


def write_mock(
    p: Project, views: dict[str, dict[str, Any]], plans: dict[str, dict[str, Any]], dst: Path
) -> Path:
    """Write the mock render: the episode in play order, every shot from its pills for its whole
    length (its camera move, holds and fairing), with no sound and each line as a subtitle (the
    speaker's first name, then the line; the lines of a shot share its time).

    Every cut has the same look: no cut mixes a model take, a square clip or a sound of its own
    with the pills of another. A pill keeps its character's color in each cut (``layout``).
    """
    from vinci_media.camera import check, encode
    from vinci_media.episode import burn_cues

    frame, fps = _review_frame(p)
    plan: list[tuple[str, int]] = []  # (shot, frames), from whole-frame boundaries: no drift
    cues: list[tuple[float, float, str]] = []
    at = 0.0
    for shot, view in views.items():
        length = float(view.get("duration") or 0)
        check(*frame, fps, length)
        plan.append((shot, round((at + length) * fps) - round(at * fps)))
        names = {
            c["id"]: str(c.get("name") or c["id"]).split()[0] for c in view.get("characters") or []
        }
        said = [
            line
            for line in view.get("dialogue") or []
            if isinstance(line, dict) and line.get("line")
        ]
        step = length / len(said) if said else 0.0
        cues += [
            (
                at + i * step,
                at + (i + 1) * step,
                f"{names.get(line.get('speaker'), line.get('speaker'))}: {line['line']}",
            )
            for i, line in enumerate(said)
        ]
        log.info("mock %s: pills, %.3f s, %d lines", shot, length, len(said))
        at += length

    def pictures() -> Iterator[bytes]:
        for shot, count in plan:
            camera = views[shot].get("camera") or {}
            yield from (
                image.tobytes() for image in pill_frames(plans[shot], camera, frame, max(count, 1))
            )

    with tempfile.TemporaryDirectory(prefix="olf-mock-") as raw:
        silent = Path(raw) / "pills.mp4"
        encode(pictures(), silent, width=frame[0], height=frame[1], fps=fps)
        dst.parent.mkdir(parents=True, exist_ok=True)
        burn_cues(silent, dst, cues, width=frame[0], height=frame[1])
    return dst
