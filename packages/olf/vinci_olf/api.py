"""JSON views of an OLF project for a UI (the Vinci Studio Shows page reads these).

Every file path in a view is relative to the project folder, so a server can serve it
with a check that it stays inside the project.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path
from typing import Any

from vinci_olf.layout import staging
from vinci_olf.project import ASSET_REF, LIBRARY, OlfError, Project, read
from vinci_olf.render import prompt, references
from vinci_olf.resolve import awaits_keyframe, inputs_hash, origins, resolve, stale, take_frames
from vinci_olf.validate import validate

log = logging.getLogger(__name__)

BIBLE = ("character", "location", "prop", "voice", "camerawork")
# Take kinds whose hash includes an entry of this kind (SPEC.md, Hash input, step 3).
IMPACT_KINDS = {
    "voice": ("video", "audio"),
    "style": ("keyframe", "video"),
    "camerawork": ("video",),
}


def library() -> list[dict[str, Any]]:
    """The camerawork library: each template as written, with its library ID
    (``anime/tu-to-eyes``) and ``version``. ``vinci_olf.author.add_template`` copies one into
    a show."""
    return [read(path) for path in sorted(LIBRARY.glob("*/*.yaml"))]


def sample_path() -> Path | None:
    """Return the tidewatch conformance sample, when this is a source checkout."""
    path = Path(__file__).resolve().parents[1] / "conformance" / "tidewatch"
    return path if (path / "project.yaml").is_file() else None


def file_of(p: Project, asset: str) -> str | None:
    """Return the project-relative file of an asset ID, or None."""
    digest = asset.removeprefix("asset/")
    if digest in p.files:
        return p.rel(p.files[digest])
    uri = str((p.lock.get(f"asset/{digest}") or {}).get("uri") or "")
    return uri if uri and "://" not in uri else None


def _files(
    p: Project, data: Any, base: Path, hashes: dict[str, str] | None = None
) -> dict[str, str]:
    """Map each asset reference in ``data`` (as written) to its project-relative file.

    ``hashes`` collects a short content hash per file, so a UI can tell when an image that
    keeps its name (a replaced sheet) changed.
    """
    out: dict[str, str] = {}

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, str) and ASSET_REF.match(value):
            try:
                asset = str(p.asset_id(value, base))
                rel = file_of(p, asset)
            except OlfError:
                rel = None
            if rel:
                out[value] = rel
                if hashes is not None:
                    hashes[rel] = asset.removeprefix("asset/")[:12]

    walk(data)
    return out


def _uses(view: dict[str, Any]) -> set[str]:
    """Bible entries a resolved shot uses."""
    used = {c["id"] for c in view.get("characters") or []}
    used |= {
        c["voice"]["id"] for c in view.get("characters") or [] if isinstance(c.get("voice"), dict)
    }
    used |= {prop["id"] for prop in view.get("props") or []}
    if isinstance(view.get("location"), dict):
        used.add(view["location"]["id"])
    if isinstance(template := (view.get("camera") or {}).get("template"), dict):
        used.add(template["id"])
    return used


def _license(p: Project, ref: Any, base: Path) -> Any:
    """The lock-file license of an asset reference, or None before the engine locks it."""
    try:
        asset = p.asset_id(str(ref), base) if ref else None
    except OlfError:
        return None
    return (p.lock.get(str(asset).partition("#")[0]) or {}).get("license") if asset else None


def _map(value: Any) -> dict[str, Any]:
    """``value`` if it is a map, else empty: the schema reports the wrong shape."""
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    """``value`` if it is a list, else empty: the schema reports the wrong shape."""
    return value if isinstance(value, list) else []


def _scene_looks(p: Project, scene: dict[str, Any], episode_id: str) -> dict[str, Any]:
    """Each cast member's form and outfit for a whole scene (season, episode, scene levels)."""
    season, episode = p.season_of(episode_id), p.docs[episode_id]
    looks: dict[str, Any] = {}
    for cid in (c for c in _list(scene.get("characters")) if isinstance(c, str)):
        options = (p.docs[cid].data if cid in p.docs else {}) or {}
        row: dict[str, Any] = {}
        for field, key in (("forms", "form"), ("outfits", "outfit")):
            chosen = {
                **_map(season.data.get(field) if season else None),
                **_map(episode.data.get(field)),
                **_map(scene.get(field)),
            }
            row[key] = chosen.get(cid) or (
                "default" if "default" in _map(options.get(field)) else None
            )
        looks[cid] = row
    return looks


def summary(p: Project) -> dict[str, Any]:
    """Return the whole project as one JSON document: issues, bible, episodes, shots and takes."""
    issues = [{"level": i.level, "where": i.where, "message": i.message} for i in validate(p)]
    # Wrong shapes in an invalid project can break a view in many ways; the issues list names
    # them. In a valid project, the same failure is an engine bug, so it raises.
    invalid = any(i["level"] == "error" for i in issues)
    cache: dict[str, dict[str, Any]] = {}
    usage: dict[str, list[str]] = defaultdict(list)
    shots: dict[str, Any] = {}
    take_ids = sorted(p.of_kind("take"))
    for shot_id in sorted(p.of_kind("shot")):
        try:
            view, error = resolve(p, shot_id), None
            cache[shot_id] = view
            for entry in sorted(_uses(view)):
                usage[entry].append(shot_id)
        except Exception as exc:
            if not (invalid or isinstance(exc, OlfError)):
                raise
            view = p.docs[shot_id].data
            error = str(exc) if isinstance(exc, OlfError) else "fix the errors on the issues page"
        shots[shot_id] = {
            "id": shot_id,
            "scene": shot_id.rsplit("/", 1)[0],
            "error": error,
            "takes": [t for t in take_ids if t.rsplit("/", 1)[0] == shot_id],
            **{k: view.get(k) for k in ("duration", "description", "camera", "select", "control")},
        }
    try:  # pills for a shot with no picture yet
        plans = staging(p, cache)
    except Exception as exc:  # a layout off the schema (`slot: d`) broke GET /olf/project (#530)
        if not invalid:
            raise
        log.warning("summary: no pills, a layout is off the schema: %r", exc)
        plans = {}
    for shot_id, plan in plans.items():
        shots[shot_id]["pills"] = plan
    takes: dict[str, Any] = {}
    for take_id in take_ids:
        data = p.docs[take_id].data
        try:
            is_stale = stale(p, take_id, cache)
        except Exception as exc:
            if not (invalid or isinstance(exc, OlfError)):
                raise
            is_stale = None
        takes[take_id] = data | {
            "stale": is_stale,
            "file": file_of(p, str(data.get("output") or "")),
        }
    forms_usage: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for view in cache.values():
        for char in view.get("characters") or []:
            if isinstance(char.get("form"), dict):
                forms_usage[char["id"]][char["form"]["name"]] += 1

    def impact(kind: str, shot_ids: list[str], data: dict[str, Any]) -> int:
        """Takes that go stale when this entry's render fields change."""
        kinds = IMPACT_KINDS.get(kind, ("keyframe", "video"))
        # A camerawork template changes keyframes too when it has keyframe words, or fills a
        # camera field that a keyframe keeps in its hash.
        still = data.get("keyframe") or {"framing", "angle", "lens"} & set(data.get("camera") or {})
        if kind == "camerawork" and still:
            kinds = ("keyframe", "video")
        return sum(takes[t]["kind"] in kinds for s in shot_ids for t in shots[s]["takes"])

    hashes: dict[str, str] = {}  # bible file -> short content hash (images that keep a name)

    def entry_row(key: str, kind: str, doc: Any, used: list[str]) -> dict[str, Any]:
        """One bible entry as the Studio reads it: its file, data, files and license, the shots
        that use it, and the number of takes that an edit makes stale."""
        data, base = doc.data, doc.path.parent
        main = data.get("sheet") or next(iter(_files(p, data.get("references"), base)), None)
        return {
            "id": key,
            "file": p.rel(doc.path),
            "data": data,
            "files": _files(p, data, base, hashes),
            "used_in": used,
            "impact": impact(kind, used, data),
            "license": _license(p, main, base),
        }

    bible: dict[str, list[dict[str, Any]]] = {kind: [] for kind in BIBLE}
    for key, doc in p.docs.items():
        if p.kind(key) in BIBLE:
            row = entry_row(key, p.kind(key), doc, usage.get(key, []))
            if p.kind(key) == "character":
                row["forms_usage"] = dict(forms_usage.get(key, {}))
            bible[p.kind(key)].append(row)
    style = p.docs.get("style")
    seasons = [
        {
            "id": key,
            "title": doc.data.get("title"),
            "synopsis": doc.data.get("synopsis"),
            "episodes": [e for e in _list(doc.data.get("episodes")) if e in p.docs],
        }
        for key, doc in sorted(p.of_kind("season").items())
    ]
    episodes = []
    for episode_id, doc in sorted(p.of_kind("episode").items()):
        listed = [s for s in _list(doc.data.get("scenes")) if isinstance(s, str) and s in p.docs]
        others = sorted(
            s for s in p.of_kind("scene") if s.startswith(episode_id + "/") and s not in listed
        )
        scenes = []
        for scene_id in listed + others:
            scene = p.docs[scene_id].data
            fields = {
                k: scene.get(k)
                for k in ("heading", "location", "variant", "mood", "characters", "script")
            }
            ids = sorted(s for s in shots if s.rsplit("/", 1)[0] == scene_id)
            looks = _scene_looks(p, scene, episode_id)
            scenes.append({"id": scene_id, **fields, "looks": looks, "shots": ids})
        meta = {k: doc.data.get(k) for k in ("title", "synopsis", "forms", "outfits")}
        meta["file"] = p.rel(doc.path)
        season = p.season_of(episode_id)
        meta["season"] = season.data.get("id") if season else None
        episodes.append({"id": episode_id, **meta, "scenes": scenes})
    return {
        "path": str(p.root),
        "spec": p.manifest.get("spec"),
        "show": p.manifest.get("show"),
        "title": p.manifest.get("title") or p.manifest.get("show"),
        "license": p.manifest.get("license"),
        "issues": issues,
        "style": None if style is None else entry_row("style", "style", style, sorted(cache)),
        "bible": bible,
        "seasons": seasons,
        "episodes": episodes,
        "shots": shots,
        "takes": takes,
        "hashes": hashes,
    }


def shot_detail(p: Project, shot_id: str) -> dict[str, Any]:
    """Return what the engine will send for a shot: resolved view, hashes, prompts, references."""
    view = resolve(p, shot_id)
    picked = (view.get("select") or {}).get("keyframe")
    frames = take_frames(p, {"inputs": {"first_frame": f"{shot_id}/{picked}"}}) if picked else {}
    waits = awaits_keyframe(view, frames)
    refs = [{"asset": ref, "file": file_of(p, ref)} for ref in references(view)]
    return {
        "resolved": view,
        "origins": origins(p, shot_id),
        "hashes": {
            "keyframe": inputs_hash(view, "keyframe"),
            "video": None if waits else inputs_hash(view, "video", frames),
            "audio": inputs_hash(view, "audio"),
        },
        "prompts": {"keyframe": prompt(view, "keyframe"), "video": prompt(view, "video")},
        "references": refs,
    }
