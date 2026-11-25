"""Studio brand contract: real Vinci mark and shared tokens, not a drawn glyph."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STUDIO = ROOT / "apps" / "studio"


def test_studio_uses_real_logo_and_shared_tokens() -> None:
    client = (STUDIO / "app" / "studio-client.tsx").read_text(encoding="utf-8")
    logo = (STUDIO / "app" / "ui" / "logo.tsx").read_text(encoding="utf-8")
    theme = (STUDIO / "app" / "theme.css").read_text(encoding="utf-8")
    layout = (STUDIO / "app" / "layout.tsx").read_text(encoding="utf-8")
    assert "VinciLogo" in client
    assert "#34c6c0" not in client
    assert "/brand/mark.png" in logo
    assert "/brand/lockup-dark.png" in logo
    assert (STUDIO / "public" / "brand" / "mark.png").is_file()
    assert (STUDIO / "public" / "brand" / "lockup-dark.png").is_file()
    assert "#21dad2" in theme
    assert "#f0dec6" in theme
    assert "--bar:" in theme
    assert "--hover:" in theme
    assert 'import "./theme.css"' in layout
    assert 'import "./brand.css"' in layout
    # Self-hosted fonts: next/font/google downloads at build time (COREPRODUC-522).
    assert "next/font/google" not in layout
    assert "next/font/local" in layout
    fonts = STUDIO / "app" / "fonts"
    # One variable face (Inter) since the flat-glass theme (2026-11); display text uses it at a heavier weight.
    assert "./fonts/Inter-latin.woff2" in layout
    assert (fonts / "Inter-latin.woff2").read_bytes()[:4] == b"wOF2"
    assert (fonts / "OFL-Inter.txt").is_file()
    assert "#3cc9c1" in theme and "--money:" in theme
    assert "EmptyState" in (STUDIO / "app" / "ui" / "empty-state.tsx").read_text(encoding="utf-8")
    assert "PromptBar" in (STUDIO / "app" / "ui" / "prompt-bar.tsx").read_text(encoding="utf-8")


def test_media_tiles_exist_and_match_ids() -> None:
    """Every tile listed in lib/tiles.ts ships as a WebP, and each template tile names a real template."""
    import re

    from vinci_core.templates import list_templates

    studio = ROOT / "apps/studio"
    src = (studio / "lib/tiles.ts").read_text(encoding="utf-8")
    sets = dict(re.findall(r"const (TEMPLATE|EFFECT)_TILES = new Set\(\[(.*?)\]\)", src, re.S))
    ids = {k: re.findall(r'"([a-z0-9-]+)"', v) for k, v in sets.items()}
    assert ids["TEMPLATE"] and ids["EFFECT"]
    for kind, folder in (("TEMPLATE", "templates"), ("EFFECT", "effects")):
        for tile_id in ids[kind]:
            path = studio / "public/tiles" / folder / f"{tile_id}.webp"
            assert path.read_bytes()[8:12] == b"WEBP", path
    assert set(ids["TEMPLATE"]) <= {t["id"] for t in list_templates()}


def test_paper_is_default_theme_with_graphite_switch() -> None:
    """Paper (light) is :root; Graphite is html[data-theme=graphite], restored before paint."""
    theme = (ROOT / "apps/studio/app/theme.css").read_text(encoding="utf-8")
    layout = (ROOT / "apps/studio/app/layout.tsx").read_text(encoding="utf-8")
    assert ':root[data-theme="graphite"]' in theme and "--bg: #f4f3f0;" in theme
    assert '"vinci-theme"' in layout and "graphite" in layout
    assert (ROOT / "apps/studio/app/ui/theme-toggle.tsx").is_file()
