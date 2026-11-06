from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_studio_assets_page_and_feed() -> None:
    assets = (ROOT / "apps/studio/app/assets-page.tsx").read_text(encoding="utf-8")
    feed = (ROOT / "apps/studio/app/asset-feed.tsx").read_text(encoding="utf-8")
    client = (ROOT / "apps/studio/app/studio-client.tsx").read_text(encoding="utf-8")
    shell = (ROOT / "apps/studio/lib/studio-shell.ts").read_text(encoding="utf-8")
    css = (ROOT / "apps/studio/app/globals.css").read_text(encoding="utf-8")

    assert '| "assets"' in shell
    assert '| "history"' not in client and '| "history"' not in shell
    assert 'title: "Assets"' in shell
    assert 'title: "History"' not in client and 'title: "History"' not in shell
    assert "View Assets" in client
    assert "AssetsPage" in client
    # Image and Video mount ImageFeed. AssetFeed stays the library card feed module.
    assert "ImagePage" in client
    assert "AssetFeed" in feed
    assert "HistoryPage" not in client
    assert 'tool=${next}' in client or "tool=" in client

    assert 'data-testid="assets-page"' in assets
    assert 'data-testid="assets-nav"' in assets
    assert "assets-section-${row.id}" in assets
    assert '{ id: "assets", label: "Assets" }' in assets
    assert '{ id: "projects", label: "Projects" }' in assets
    assert '{ id: "favorites", label: "Favorites" }' in assets
    assert '{ id: "elements", label: "Elements" }' in assets
    assert '{ id: "trash", label: "Trash" }' in assets
    assert '{ id: "image", label: "Images" }' in assets
    assert '{ id: "video", label: "Video" }' in assets
    assert '{ id: "enhanced", label: "Enhanced" }' in assets
    assert "assets-type-${row.id || \"all\"}" in assets
    assert 'data-testid="assets-search"' in assets
    assert 'data-testid="assets-date"' in assets
    assert 'data-testid="assets-empty"' in assets
    assert 'data-testid="assets-error"' in assets
    assert 'data-testid="assets-select-all"' in assets
    assert 'data-testid="assets-reveal-finder"' in assets
    assert 'data-testid="assets-save-photos"' in assets
    assert "Restore" in assets
    assert "Reveal in Finder" in assets
    assert "Save to Photos" in assets
    assert "This Studio" in assets

    assert 'data-testid={`${tool}-feed`}' in feed
    assert "Use as reference" in feed
    assert "Animate" in feed

    assert ".assets-page" in css
    assert ".assets-masonry" in css
    assert ".asset-feed" in css
    assert ".history-page" not in css
