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
    assert "EmptyState" in (STUDIO / "app" / "ui" / "empty-state.tsx").read_text(encoding="utf-8")
    assert "PromptBar" in (STUDIO / "app" / "ui" / "prompt-bar.tsx").read_text(encoding="utf-8")
