from __future__ import annotations

import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

NORTH_STAR_FILES = (
    "LICENSE",
    "NAMESPACE.md",
    "Makefile",
    "README.md",
    "legal/AGPL_CLEAN_ROOM.md",
    "docs/VINCI_OSS_RUNTIME.md",
    "docs/VINCI_OSS_E2E_ACHIEVEMENT.md",
    "scripts/vinci",
    "scripts/clone-smoke.sh",
    "scripts/create-github-repo.sh",
    "skills/image-generate/workflow.yaml",
    "skills/video-generate/workflow.yaml",
    "skills/product-reveal-5s/workflow.yaml",
    "skills/cinema-still/workflow.yaml",
    "skills/cinema-sequence/workflow.yaml",
    "skills/first-last-frame/workflow.yaml",
    "skills/soul-character/workflow.yaml",
    "skills/podcast-to-shorts/workflow.yaml",
    "packages/core/vinci_core/catalogs/mock.json",
    "apps/mac/VinciStudio.swift",
    "apps/android/app/src/main/java/ai/tryvinci/studio/MainActivity.kt",
    "apps/android/app/src/main/AndroidManifest.xml",
    ".github/workflows/ci.yml",
)


def test_clone_tree_has_north_star_files() -> None:
    for rel in NORTH_STAR_FILES:
        path = ROOT / rel
        assert path.is_file(), rel
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "MIT" in license_text
    assert "GNU Affero" not in license_text
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "Do not `npx @tryvinci/cli`" in readme
    assert "mcp:png:v1" in readme
    assert "mcp:mp4:v1" in readme
    assert "make github" in readme
    wrapper = ROOT / "scripts" / "vinci"
    assert wrapper.stat().st_mode & stat.S_IXUSR
    smoke = ROOT / "scripts" / "clone-smoke.sh"
    assert smoke.stat().st_mode & stat.S_IXUSR
    smoke_text = smoke.read_text(encoding="utf-8")
    assert "vinci_daemon" in smoke_text
    assert "./scripts/vinci init --demo" in smoke_text
    assert "960x540" in smoke_text
    assert "540x960" in smoke_text
    assert "9:16" in smoke_text
    assert "camera-pills" in smoke_text
    assert "motion-pills" in smoke_text
    assert "Play timeline" in smoke_text
    assert "node-model" in smoke_text
    assert "studio-client.tsx" in smoke_text
    assert "cast-pills" in smoke_text
    assert "first-frame" in smoke_text
    assert "Start generating" in smoke_text
    assert "Skip for now" in smoke_text
    assert "vinci-onboard-v1" in smoke_text
    assert "Instrument Serif" in smoke_text
    assert 'if "iframe" in page' in smoke_text
    assert "Cinema stack" in smoke_text
    assert "aperture-pills" in smoke_text
    assert "lighting-pills" in smoke_text
    assert "palette-pills" in smoke_text
    assert "image_urls" in smoke_text
    assert "add-shot" in smoke_text
    assert "creativity" in smoke_text
    studio_page = (ROOT / "apps/studio/app/page.tsx").read_text(encoding="utf-8")
    assert "iframe" not in studio_page
    assert "StudioClient" in studio_page
    studio_client = (ROOT / "apps/studio/app/studio-client.tsx").read_text(encoding="utf-8")
    assert "/vinci-api" in studio_client
    assert "Play timeline" in studio_client
    assert "Generate this node" in studio_client
    assert "Cinema stack" in studio_client
    assert "cast-pills" in studio_client
    assert "first-frame" in studio_client
    assert "data-port" in studio_client
    assert "vinci://assets/" in studio_client
    assert "Start generating" in studio_client
    assert "New connector" in studio_client
    assert "connector-mark" in studio_client
    assert "connect-select" in studio_client
    assert "Named MCP" in studio_client
    assert "Supercomputer" in studio_client
    assert "Collab" in studio_client
    assert "aperture-pills" in studio_client
    assert "lighting-pills" in studio_client
    assert "palette-pills" in studio_client
    assert "image_urls" in studio_client
    assert "add-shot" in studio_client
    assert "creativity" in studio_client
    assert "optimized-pills" in studio_client
    assert "element-kind-pills" in studio_client
    assert "t.defaults" in studio_client
    assert 't.page || "canvas"' in studio_client
    assert "Speak scenes open Speak" in studio_client
    assert "Skip for now" in studio_client
    assert "vinci-onboard-v1" in studio_client
    assert "Your Brand's Superagency" in studio_client
    assert "ftyp" in smoke_text
    assert "/receipts/" in smoke_text
    assert '"/runs"' in smoke_text or "/runs" in smoke_text
    assert "vinci.image_generate" in smoke_text
    assert "vinci.video_generate" in smoke_text
    assert "@tryvinci/product-reveal-5s" in smoke_text
    assert "@tryvinci/cinema-still" in smoke_text
    assert "@tryvinci/still-to-talk" in smoke_text
    assert "@tryvinci/cinema-sequence" in smoke_text
    assert "@tryvinci/first-last-frame" in smoke_text
    assert "@tryvinci/soul-character" in smoke_text
    assert "--max-cost" in smoke_text
    assert "jobs approve" in smoke_text
    assert "awaiting_approval" in smoke_text
    assert "@tryvinci/podcast-to-shorts" in smoke_text
    assert "skills add" in smoke_text
    assert "@example/stamp-text" in smoke_text
    assert "@example/stamp-video" in smoke_text
    assert "/studio" in smoke_text
    mac = (ROOT / "apps/mac/VinciStudio.swift").read_text(encoding="utf-8")
    android = (
        ROOT / "apps/android/app/src/main/java/ai/tryvinci/studio/MainActivity.kt"
    ).read_text(encoding="utf-8")
    assert "http://127.0.0.1:4311" in mac
    assert "http://10.0.2.2:4311" in android
    assert "Vinci Studio" in smoke_text
    assert "Bring your own keys" in smoke_text
    assert "New connector" in smoke_text
    assert "Higgsfield" in smoke_text
    assert "Custom MCP" in smoke_text
    assert "--no-open" in smoke_text
    assert "find?q=pricing" in smoke_text
    assert "vinci_mcp.mock_server" in smoke_text
    assert "providers add mcp" in smoke_text
    assert "mcp:png:v1" in smoke_text
    assert "mcp:mp4:v1" in smoke_text
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "make clone-smoke" in ci
    assert "Forbid live spend" in ci
    assert "workflow_dispatch" in ci
    assert "loopback MCP provider" in ci
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "create-github-repo.sh" in makefile


def _tracked_relpaths(root: Path) -> set[str]:
    git_root = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
        text=True,
    ).strip()
    prefix = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "--show-prefix"],
        text=True,
    ).strip().rstrip("/")
    listed = subprocess.check_output(
        ["git", "-C", git_root, "ls-files", "-z", "--", prefix or "."],
        text=True,
    ).split("\0")
    files = [item for item in listed if item]
    if not prefix:
        return set(files)
    lead = prefix + "/"
    return {item[len(lead) :] for item in files if item.startswith(lead)}


def test_git_ls_files_includes_north_star_paths() -> None:
    listed = _tracked_relpaths(ROOT)
    missing = [rel for rel in NORTH_STAR_FILES if rel not in listed]
    assert missing == []
    assert "apps/cli/dist/index.js" not in listed
    assert ".venv" not in listed


def test_clone_smoke_archives_oss_subtree_when_nested() -> None:
    smoke = (ROOT / "scripts" / "clone-smoke.sh").read_text(encoding="utf-8")
    assert "rev-parse --show-prefix" in smoke
    assert "HEAD:${PREFIX%/}" in smoke
    assert "apps/vinci-backend" in smoke
