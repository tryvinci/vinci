from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from vinci_media.adapt import adapt_image_fit_pad_crop, validate_output_image
from vinci_media.custom_presets import create_custom_preset
from vinci_media.ops import require_ffmpeg


def _photo_png(path: Path) -> None:
    require_ffmpeg()
    proc = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=1080x1080:rate=1:duration=1",
            "-vf",
            "scale=1080:1080:flags=lanczos,eq=brightness=0.05:saturation=1.3",
            "-frames:v",
            "1",
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "photo fixture render failed")
    assert path.stat().st_size > 50_000, "expected a rich photographic PNG fixture"


@pytest.mark.parametrize("cap_kb", [100, 150, 500, 2048])
def test_photographic_export_meets_byte_caps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cap_kb: int
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("VINCI_HOME", str(home))
    preset_id = f"photo_cap_{cap_kb}"
    create_custom_preset(
        {
            "id": preset_id,
            "label": f"Photo {cap_kb}KB",
            "partner": "test",
            "width": 1080,
            "height": 1080,
            "byte_cap": {"max_bytes": cap_kb * 1024, "op": "lte"},
        },
        home=home,
    )
    src = tmp_path / "source.png"
    _photo_png(src)
    dst = tmp_path / f"out_{cap_kb}.jpg"
    adapt_image_fit_pad_crop(
        src,
        dst,
        width=1080,
        height=1080,
        fit="pad",
        preset_id=preset_id,
        home=home,
    )
    assert dst.is_file()
    assert dst.suffix.lower() in {".jpg", ".jpeg"}
    meta = validate_output_image(dst, width=1080, height=1080, preset_id=preset_id, home=home)
    assert meta["bytes"] <= cap_kb * 1024
    assert meta["export_validation"]["automated"]["byte_cap_ok"] is True
