"""Camera moves over a still (vinci_media.camera): the windows, the frame path, the video."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image
from vinci_media import MediaError, camera_move, probe
from vinci_media.camera import drawing_size, track, upscale, windows
from vinci_media.ops import FFPROBE

DRAWING, FRAME = (1600, 900), (1280, 720)
BASE = (0.0, 0.0, 1600.0, 900.0)


def test_windows_of_each_move() -> None:
    start, end = windows(DRAWING, FRAME, "push_in", amount=0.35, center=(0.5, 0.42))
    assert start == BASE and end[2:] == pytest.approx((1040, 585))  # the end frame is 65%
    assert (end[0] + end[2] / 2, end[1] + end[3] / 2) == pytest.approx((800, 378))  # on the point
    assert windows(DRAWING, FRAME, "pull_out", amount=0.35, center=(0.5, 0.42)) == (end, start)
    # A point near a corner: the end window stays inside the drawing.
    assert windows(DRAWING, FRAME, "push_in", amount=0.5, center=(0, 0))[1] == (0, 0, 800, 450)
    west, east = windows(DRAWING, FRAME, "pan", amount=0.25)
    assert west[0] == 0 and east[0] + east[2] == pytest.approx(1600)
    assert east[0] - west[0] == pytest.approx(0.25 * west[2])  # travel: a quarter frame width
    assert windows(DRAWING, FRAME, "truck", amount=0.25, direction="left") == (east, west)
    low, high = windows(DRAWING, FRAME, "tilt")  # up by default: from the bottom to the top
    assert low[1] > high[1] == 0
    assert windows(DRAWING, FRAME, "tilt", direction="down") == (high, low)
    assert windows(DRAWING, FRAME, "static") == (BASE, BASE)
    inner, same = windows(DRAWING, FRAME, "shake", amount=0.05)
    assert inner == same and inner[2:] == pytest.approx((1440, 810))  # room on each side
    # A drawing of another shape: the base window has the frame's shape, at the centre.
    assert windows((900, 1600), FRAME)[0] == pytest.approx((0, 546.875, 900, 506.25))
    assert upscale(DRAWING, FRAME, "push_in", amount=0.35) == pytest.approx(1280 / 1040)
    with pytest.raises(MediaError, match="a still cannot do a orbit move"):
        windows(DRAWING, FRAME, "orbit")


def test_track_holds_eases_and_shakes() -> None:
    end = (280.0, 85.5, 1040.0, 585.0)
    path = track(BASE, end, 18, hold_start=4, hold_end=6)  # 0+18: an 8-frame move between holds
    assert len(path) == 18 and path[:5] == [BASE] * 5 and path[11:] == [end] * 7
    widths = [w for _, _, w, _ in path[4:12]]
    assert widths == sorted(widths, reverse=True) and len(set(widths)) == 8  # one step a frame
    assert track(BASE, end, 1) == [end] and track(BASE, end, 3, hold_start=3) == [BASE] * 3
    linear, slow_in, slow_out = (track(BASE, end, 9, ease=e)[4][2] for e in ("none", "in", "out"))
    assert slow_out < linear < slow_in  # half way: fairing in is behind, fairing out is ahead
    assert track(BASE, end, 9, ease="in_out")[4][2] == pytest.approx(linear)
    shaken = track(BASE, BASE, 12, hold_start=3, shake=10.0, seed="e02/s03/sh014/v1")
    assert shaken == track(BASE, BASE, 12, hold_start=3, shake=10.0, seed="e02/s03/sh014/v1")
    assert shaken != track(BASE, BASE, 12, hold_start=3, shake=10.0, seed="e02/s03/sh014/v2")
    assert shaken[:3] == [BASE] * 3 and shaken[-1] == BASE  # no shake in a hold; it fades out
    assert all(abs(x) <= 10 and abs(y) <= 10 for x, y, _, _ in shaken) and shaken[3] != BASE
    with pytest.raises(MediaError, match="ease must be one of none, in, out, in_out"):
        track(BASE, end, 9, ease="slow")


def test_camera_move_stops_ffmpeg_when_a_frame_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A frame that fails to draw stops ffmpeg: no process waits for input (PR-Agent, #529)."""
    if not shutil.which("ffmpeg"):
        pytest.skip("camera_move runs ffmpeg")
    still = tmp_path / "keyframe.png"
    Image.new("RGB", DRAWING, "#1b2a3a").save(still)
    started: list[subprocess.Popen[bytes]] = []
    real = subprocess.Popen

    def fail(*args: object, **kwargs: object) -> Image.Image:
        raise MemoryError("a frame that does not fit in memory")

    monkeypatch.setattr(
        subprocess, "Popen", lambda *a, **k: started.append(real(*a, **k)) or started[-1]
    )
    monkeypatch.setattr(Image.Image, "transform", fail)
    with pytest.raises(MemoryError):
        camera_move(still, tmp_path / "move.mp4", width=640, height=360, seconds=0.5, move="pan")
    assert started and all(proc.returncode is not None for proc in started)  # stopped and reaped


def test_camera_move_writes_an_exact_video(tmp_path: Path) -> None:
    if not shutil.which("ffmpeg"):
        pytest.skip("camera_move runs ffmpeg")
    still = tmp_path / "keyframe.png"
    Image.new("RGB", DRAWING, "#1b2a3a").save(still)
    out = camera_move(
        still,
        tmp_path / "move.mp4",
        width=640,
        height=360,
        seconds=0.75,  # 0+18
        move="push_in",
        amount=0.3,
        ease="out",
        hold_end=10 / 24,
    )
    count = subprocess.run(
        [FFPROBE, "-v", "error", "-count_frames", "-select_streams", "v:0"]
        + ["-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(out)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    info = probe(out)
    assert (int(count), info["width"], info["height"]) == (18, 640, 360)  # exact to the frame
    with pytest.raises(MediaError, match="a still cannot do a crane move"):
        camera_move(still, tmp_path / "no.mp4", width=640, height=360, seconds=1, move="crane")
    # Sizes can come from a show file that nobody checked: each frame is an image in memory.
    for size, message in (
        ({"width": 10000, "height": 360, "seconds": 1}, "16 to 4096 px a side, not 10000x360"),
        ({"width": 640, "height": 360, "seconds": 1, "fps": 1000}, "1 to 60 frames a second"),
        ({"width": 640, "height": 360, "seconds": 3600}, "lasts up to 120 s, not 3600 s"),
    ):
        with pytest.raises(MediaError, match=message):
            camera_move(still, tmp_path / "no.mp4", **size)
    assert not (tmp_path / "no.mp4").exists()
    # The size of a still, for each format Pillow reads: a model can answer with WebP.
    webp = tmp_path / "keyframe.webp"
    Image.new("RGB", (1200, 675), "#1b2a3a").save(webp)
    assert (drawing_size(still), drawing_size(webp)) == (DRAWING, (1200, 675))
    (tmp_path / "blank.png").write_text("not an image", encoding="utf-8")
    with pytest.raises(OSError, match="cannot identify image file"):
        drawing_size(tmp_path / "blank.png")


def test_windows_over_a_drawing_larger_than_the_frame() -> None:
    """COREPRODUC-565: a pan or a tilt goes across a drawing larger than the frame (canvas)."""
    wide, frame, canvas = (2100, 900), (1600, 900), "21:9"  # a 21:9 drawing, a 16:9 frame
    assert windows(wide, frame, "pan", canvas=canvas) == ((0, 0, 1600, 900), (500, 0, 1600, 900))
    small = windows(wide, frame, "pan", amount=0.1, canvas=canvas)  # a short pan: at the centre
    assert small[0] == pytest.approx((170, 0, 1600, 900)) and small[1][0] == pytest.approx(330)
    west, east = windows(wide, frame, "pan", amount=0.5, canvas=canvas)  # too far: smaller
    assert west == pytest.approx((0, 56.25, 1400, 787.5)) and east[0] == pytest.approx(700)
    tall = (900, 1600)  # a 9:16 drawing: the frame tilts up 2.16 frame heights
    low, high = windows(tall, frame, "tilt", canvas="9:16")
    assert high == pytest.approx((0, 0, 900, 506.25)) and low[1] == pytest.approx(1093.75)
    assert (1600 - 506.25) / 506.25 == pytest.approx(2.16, abs=0.01)
    # No canvas: a square keyframe in a 16:9 show tilts 0.2 frame heights in the centre crop, as
    # before canvases, not 0.78 (PR-Agent review of #530: the same take gave another move).
    low, high = windows((2048, 2048), frame, "tilt")
    assert high == pytest.approx((2048 / 12, 448, 2048 / 1.2, 960)) and low[1] == pytest.approx(640)
    assert windows((2048, 2048), frame, "tilt", canvas="1:1")[1] == pytest.approx(
        (0, 0, 2048, 1152)
    )
