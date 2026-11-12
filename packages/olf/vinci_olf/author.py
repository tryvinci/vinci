"""Author an OLF show from the Studio: a new show and its first character, shot fields, new
shots, scenes and episodes, sheets, forms.

Each edit changes only its own lines (``vinci_olf.edit._put``), so a hand-written file keeps its
comments and style, and each edit is parsed again before it is saved. New files are written in
the spec's style. Uploaded images are checked with Pillow and stay inside the show folder.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import logging
import math
import mimetypes
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from vinci_olf.edit import _put, _save, shot_block
from vinci_olf.project import (
    FRAMES,
    LIBRARY,
    OlfError,
    Project,
    frames,
    load,
    read,
    seconds,
    sheets_of,
    write,
)
from vinci_olf.resolve import MOTION
from vinci_olf.validate import SCHEMA, schema_errors

log = logging.getLogger(__name__)
CAMERA = SCHEMA["$defs"]["camera"]["properties"]
CAMERA_KEYS = tuple(CAMERA)  # every camera field of the schema, in its order
SLUG = re.compile(r"^[a-z0-9-]+$")
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
MAX_UPLOAD = 20 * 1024 * 1024  # bytes of one uploaded image
PLAIN = re.compile(r"[A-Za-z0-9][\w.\-+/]*( [\w.\-]+)*")
NOT_TEXT = re.compile(r"[\d.]+|true|false|null|yes|no|on|off|~", re.IGNORECASE)
ASPECTS = {"16:9": "1920x1080", "9:16": "1080x1920", "1:1": "1080x1080"}  # aspect -> resolution


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")


def new_show(root: Path, title: str, *, medium: str = "2D anime", aspect: str = "16:9") -> Project:
    """Create a show folder (design: New show, step 1): ``project.yaml`` with the license the
    engine copies to every asset, ``bible/show.yaml``, ``bible/style.yaml`` and ``episodes/``.

    Raises:
        OlfError: The folder is not empty, or the title or aspect is not allowed.
    """
    from ruamel.yaml.scalarstring import DoubleQuotedScalarString as Quoted

    title = " ".join(str(title or "").split())
    if not title:
        raise OlfError("a show needs a title")
    if aspect not in ASPECTS:
        raise OlfError(f"aspect must be one of {', '.join(ASPECTS)}, not {aspect!r}")
    if root.exists() and any(root.iterdir()):
        raise OlfError(f"{root} is not empty")
    ratio = Quoted(aspect)  # 16:9 unquoted is the number 969 to a YAML 1.1 reader
    files = {
        "project": (
            "project.yaml",
            {
                "spec": "olf/0.1",
                "show": _slug(title) or "show",
                "title": title,
                "defaults": {"aspect": ratio, "fps": 24, "resolution": ASPECTS[aspect]},
                "exports": [ratio],
                "license": {"owner": "@me", "terms": "all-rights-reserved"},
            },
        ),
        "show": ("bible/show.yaml", {"title": title}),
        "style": (
            "bible/style.yaml",
            {
                "id": "style/main",
                "look": {"medium": " ".join(str(medium or "").split()) or "2D anime"},
                "lenses": ["24mm", "35mm", "50mm", "85mm"],
            },
        ),
    }
    for kind, (_, data) in files.items():
        if problems := schema_errors(kind, data):
            raise OlfError(f"{kind}: {problems[0]}")
    for rel, data in files.values():
        write(data, root / rel, compact=True)
    (root / "episodes").mkdir(exist_ok=True)
    log.info("new show %r (%s, %s) in %s", title, medium, aspect, root)
    return load(root)


def add_character(
    p: Project,
    name: str,
    description: str,
    *,
    sheet: str | None = None,
    voice_id: str | None = None,
    voice_name: str = "",
) -> str:
    """Add a character (design: New show, step 2): a name, a description and, when given, the
    whole sheet as ``sheet.png`` and an ElevenLabs voice (``set_voice``). The sheet's lock entry
    gets the license from ``project.yaml``.

    Returns:
        The new character ID: the first name as a slug (``Mira Sol`` -> ``char/mira``).

    Raises:
        OlfError: The name is empty or taken, or the sheet is not an image.
    """
    name = " ".join(str(name or "").split())
    if not name or not _slug(name):
        raise OlfError("a character needs a name with a letter or a digit")
    slug = next(
        s
        for s in (_slug(name.split()[0]), _slug(name))
        + tuple(f"{_slug(name)}-{n}" for n in range(2, 99))
        if f"char/{s}" not in p.docs and not (p.root / "bible" / "characters" / s).exists()
    )
    folder = p.inside(p.root / "bible" / "characters" / slug)
    data: dict[str, Any] = {"id": f"char/{slug}", "name": name}
    data["description"] = " ".join(str(description or "").split()) or f"{name}."
    image = decode_image(sheet) if sheet else None
    data |= {"sheet": "sheet.png"} if image is not None else {}
    if problems := schema_errors("character", data):
        raise OlfError(f"char/{slug}: {problems[0]}")
    if image is not None:
        _save_image(image, folder / "sheet.png")
    write(data, folder / f"{slug}.yaml", compact=True)
    license_ = p.manifest.get("license")
    if image is not None and isinstance(license_, dict):
        from vinci_olf.render import _lock_entry

        digest = p.sha256(folder / "sheet.png")
        rel = p.rel(folder / "sheet.png")
        p.add_to_lock(
            {f"asset/{digest}": _lock_entry(rel, digest, "image/png", "uploaded", license_)}
        )
    log.info("added character char/%s (%s), sheet: %s", slug, name, image is not None)
    if voice_id:
        set_voice(load(p.root, hashes=p.known), f"char/{slug}", voice_id, voice_name)
    return f"char/{slug}"


def _voice_entry(p: Project, char_id: str) -> tuple[str, Path]:
    """The character's voice entry ID and file: its own, else ``bible/voices/<slug>/<slug>.yaml``.

    Raises:
        OlfError: The character is missing.
    """
    doc = p.docs.get(char_id)
    if p.kind(char_id) != "character" or doc is None:
        raise OlfError(f"{char_id}: no such character")
    current = doc.data.get("voice")
    if isinstance(current, str) and current in p.docs:
        return current, p.docs[current].path
    slug = char_id.split("/", 1)[1]
    return f"voice/{slug}", p.inside(p.root / "bible" / "voices" / slug / f"{slug}.yaml")


def set_voice(
    p: Project, char_id: str, voice_id: str, name: str = "", *, sample: str | None = None
) -> str:
    """Give a character an ElevenLabs voice (design: the character's Voice field).

    The character's own voice entry keeps its description and other providers; only
    ``extensions.elevenlabs.voice_id`` (and ``sample``, when given) changes. Without one,
    ``bible/voices/<slug>/<slug>.yaml`` is written and the character points at it (``voice:
    voice/<slug>``). Its dialogue takes go stale: the voice is part of their hash.

    Returns:
        The voice entry ID, for example ``voice/mira``.

    Raises:
        OlfError: The character is missing, or the ID is not one from a voice list.
    """
    from ruamel.yaml import YAML

    entry, path = _voice_entry(p, char_id)
    doc = p.docs[char_id]
    voice_id = str(voice_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", voice_id):
        raise OlfError(f"{voice_id!r} is not a voice ID: pick a voice from the list")
    if entry in p.docs:  # round trip: the file keeps its comments and other fields
        data: Any = YAML().load(path.read_text(encoding="utf-8"))
        data.setdefault("extensions", {}).setdefault("elevenlabs", {})["voice_id"] = voice_id
    else:
        who = doc.data.get("name") or char_id.split("/", 1)[1]
        data = {"id": entry, "description": " ".join(name.split()) or f"The voice of {who}."}
        data["extensions"] = {"elevenlabs": {"voice_id": voice_id}}
    if sample:
        data["sample"] = sample
    current = doc.data.get("voice")
    if problems := schema_errors("voice", json.loads(json.dumps(data))):
        raise OlfError(f"{entry}: {problems[0]}")
    path.parent.mkdir(parents=True, exist_ok=True)
    write(data, path, compact=entry not in p.docs)
    if current != entry:
        lines = _lines(doc.path)
        _put(lines, 0, len(lines), "", "voice", entry)
        _save(doc.path, lines, lambda d: d.get("voice") == entry)
    log.info("%s speaks in ElevenLabs voice %s (%s)", char_id, voice_id, entry)
    return entry


# A recording's first bytes and its file type (an MP3 without a tag starts with a frame sync).
AUDIO = (
    (b"ID3", ".mp3"),
    (b"\xff\xfb", ".mp3"),
    (b"\xff\xf3", ".mp3"),
    (b"RIFF", ".wav"),
    (b"OggS", ".ogg"),
    (b"fLaC", ".flac"),
)
# The sample files clone_voice writes (``sample-<content hash>.<ext>``, earlier ``sample.mp3``).
# Only these are removed when a new clone replaces them: project files can be untrusted.
SAMPLE_FILE = re.compile(r"sample(-[0-9a-f]{12})?\.(mp3|wav|ogg|flac)")


def clone_voice(
    p: Project, char_id: str, name: str, sample: str, clone: Callable[[str, bytes, str], str]
) -> str:
    """Design: Clone from sample. Clone a voice from a recording and give it to the character.

    ``clone(name, data, file)`` makes the clone (ElevenLabs Instant Voice Cloning) and returns
    its voice ID. The person has confirmed the right to the voice and the speaker's consent
    first (the route checks). The clone comes first, so a refused clone writes nothing; then
    the recording is the voice entry's ``sample``, with a lock entry, as a sheet has. Each
    recording gets its own file, and the entry switches to it only once it is saved: a failed
    save leaves the old sample, lock entry and voice entry together. Then the old sample goes.

    Returns:
        The voice entry ID, for example ``voice/mira``.

    Raises:
        OlfError: The character is missing, or the recording is not MP3, WAV, OGG or FLAC
            audio of at most 20 MB (``MAX_UPLOAD``).
    """
    entry, path = _voice_entry(p, char_id)
    raw = str(sample or "").split(",", 1)[-1] if str(sample).startswith("data:") else str(sample)
    try:
        data = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise OlfError("the recording is not base64 data") from exc
    ext = next((kind for head, kind in AUDIO if data.startswith(head)), None)
    if ext is None or len(data) > MAX_UPLOAD:
        raise OlfError(
            f"a voice sample is MP3, WAV, OGG or FLAC audio of at most {MAX_UPLOAD >> 20} MB"
        )
    who = p.docs[char_id].data.get("name") or char_id.split("/", 1)[1]
    name = " ".join(str(name or "").split()) or f"{who}'s voice"
    voice_id = clone(name, data, f"sample{ext}")
    # A new path per recording: never the old sample's bytes, and never a stale cached hash.
    target = path.parent / f"sample-{hashlib.sha256(data).hexdigest()[:12]}{ext}"
    old = p.docs[entry].data.get("sample") if entry in p.docs else None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        license_ = p.manifest.get("license")
        if isinstance(license_, dict):
            from vinci_olf.render import _lock_entry

            digest, rel = p.sha256(target), p.rel(target)
            mime = mimetypes.guess_type(target.name)[0] or "audio/mpeg"
            row = _lock_entry(rel, digest, mime, "uploaded", license_)
            p.add_to_lock({f"asset/{digest}": row})
        log.info("%s: cloned %s from %s (%d bytes)", char_id, voice_id, p.rel(target), len(data))
        voice = set_voice(load(p.root, hashes=p.known), char_id, voice_id, name, sample=target.name)
    except Exception as exc:
        # The clone exists and holds a voice slot: name it, so it is picked, not made again.
        # It is not deleted: the voice entry may already point to it.
        log.error("%s: clone %s was made but not saved: %r", char_id, voice_id, exc)
        raise OlfError(
            f'ElevenLabs made the voice "{name}" ({voice_id}), but the show could not save it: '
            f"{exc}. Reload and pick it in the Voice menu, or delete it in ElevenLabs."
        ) from exc
    if isinstance(old, str) and old != target.name and SAMPLE_FILE.fullmatch(old):
        try:  # the replaced recording goes with its lock entry: the entry points to the new one
            p.drop_from_lock(p.rel(path.parent / old))
            (path.parent / old).unlink(missing_ok=True)
        except OSError as exc:  # the voice is saved: an old file left behind does no harm
            log.warning("%s: could not remove the old sample %s: %s", char_id, old, exc)
    return voice


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines(keepends=True)


def _scalar(value: str) -> str:
    """A value for a flow map: plain when YAML reads it back as the same text, else quoted."""
    return value if PLAIN.fullmatch(value) and not NOT_TEXT.fullmatch(value) else json.dumps(value)


def _flow(value: Any) -> str:
    """A camera value in a flow map: numbers and lists of numbers plain, text as ``_scalar``."""
    if isinstance(value, list):
        return "[" + ", ".join(_flow(x) for x in value) + "]"
    return f"{value:g}" if isinstance(value, int | float) else _scalar(str(value))


def _length(value: Any) -> str:
    """Check a shot length and return it as it is written: seconds+frames stays as typed
    (``3+12``), each other form becomes seconds (``4s``)."""
    typed = str(value).strip()
    if not 0 < seconds(typed) <= 600:
        raise OlfError(f"duration must be seconds such as 4s or 3+12, not {value!r}")
    return typed if "+" in typed else f"{seconds(typed):g}s"


def _block(lines: list[str], key: str) -> tuple[int, int] | None:
    """Return ``(line of key:, end)`` for a top-level key, or None when the file has none."""
    head = re.compile(rf"^{re.escape(key)}:(\s|$)")
    for i, line in enumerate(lines):
        if head.match(line):
            end = next(
                (
                    j
                    for j in range(i + 1, len(lines))
                    if lines[j].strip() and not lines[j].startswith((" ", "- ", "#"))
                ),
                len(lines),
            )
            while end > i + 1 and not lines[end - 1].strip():  # trailing blank lines stay outside
                end -= 1
            return i, end
    return None


def _node(data: dict[str, Any], shot_id: str) -> dict[str, Any]:
    """The shot in a parsed file: the file itself, or an inline shot of a scene."""
    if data.get("id") == shot_id:
        return data
    return next((s for s in data.get("shots") or [] if s.get("id") == shot_id), {})


def set_shot(p: Project, shot_id: str, **fields: Any) -> dict[str, Any]:
    """Change a shot's ``description``, ``duration`` or camera (each camera field of the schema).

    Each field is one line in the spec's style, for example ``camera: { framing: close_up,
    lens: 50mm }``; ``None`` or ``""`` removes a camera field except framing (required). Camera
    fields that the edit does not name stay as they are.

    Returns:
        The fields as written.

    Raises:
        OlfError: The shot is missing, or a value is not allowed (SPEC.md, Shots).
    """
    doc = p.docs.get(shot_id)
    if doc is None or p.kind(shot_id) != "shot":
        raise OlfError(f"{shot_id}: no such shot")
    if unknown := sorted(set(fields) - {"description", "duration", *CAMERA_KEYS}):
        raise OlfError(f"a shot has no field {unknown[0]!r} to change here")
    lines, want = _lines(doc.path), dict[str, Any]()
    if "description" in fields:
        text = str(fields["description"] or "").strip()
        if not text:
            raise OlfError("a shot needs a description (SPEC.md: required)")
        want["description"] = text
    if "duration" in fields:
        want["duration"] = _length(fields["duration"])
    if any(k in fields for k in CAMERA_KEYS):
        merged = {**(_node(read(doc.path), shot_id).get("camera") or {}), **fields}
        camera = {k: merged[k] for k in CAMERA_KEYS if merged.get(k) not in (None, "")}
        for key, value in camera.items():
            if "enum" in CAMERA[key] and value not in CAMERA[key]["enum"]:
                allowed = ", ".join(CAMERA[key]["enum"])
                raise OlfError(f"camera.{key} must be one of {allowed}, not {value!r}")
            if CAMERA[key].get("type") == "number":  # the Studio sends the text a person typed
                try:
                    camera[key] = float(value)
                except (TypeError, ValueError):
                    raise OlfError(f"camera.{key} must be a number, not {value!r}") from None
            elif not isinstance(value, int | float | list):
                camera[key] = str(value)
        if "framing" not in camera:
            raise OlfError("camera.framing is required (SPEC.md)")
        if errors := schema_errors("camera", camera):
            raise OlfError(f"camera.{errors[0]}")
        want["camera"] = camera
    for key, value in want.items():
        first, end, indent = shot_block(lines, shot_id)  # find it again: lines move
        text = (
            json.dumps(value, ensure_ascii=False)
            if key == "description"
            else "{ " + ", ".join(f"{k}: {_flow(v)}" for k, v in value.items()) + " }"
            if key == "camera"
            else value
        )
        _put(lines, first, end, indent, key, text)
    _save(
        doc.path, lines, lambda data: all(_node(data, shot_id).get(k) == v for k, v in want.items())
    )
    doc.data = _node(read(doc.path), shot_id)
    log.info("shot %s: %s", shot_id, want)
    return want


def add_template(p: Project, library_id: str) -> str:
    """Copy a template of the camerawork library into the show's bible.

    The copy is ``bible/camerawork/<slug>/<slug>.yaml`` with the ID ``cam/<slug>``. It records
    where it came from (``source: anime/tu-slow@1``), and the show owns it from then on: a
    newer library version changes nothing until a person takes it. A template the show
    already has from the same library entry stays as it is.

    Returns:
        The template's ID in the show.

    Raises:
        OlfError: The library has no such template, or the show has its own ``cam/<slug>``.
    """
    namespace, _, slug = str(library_id).partition("/")
    path = LIBRARY / namespace / f"{slug}.yaml"
    if not (SLUG.fullmatch(namespace) and SLUG.fullmatch(slug) and path.is_file()):
        raise OlfError(f"the camerawork library has no template {library_id!r}")
    cam_id, version = f"cam/{slug}", read(path).get("version")
    if (have := p.docs.get(cam_id)) is not None:
        if str(have.data.get("source") or "").partition("@")[0] == library_id:
            return cam_id
        raise OlfError(f"the show has its own {cam_id}: it is not a copy of {library_id}")
    text = re.sub(  # the library ID and version become the show ID and the source
        r"(?m)^id: .*\nversion: .*$",
        f"id: {cam_id}\nsource: {library_id}@{version}",
        path.read_text(encoding="utf-8"),
        count=1,
    )
    target = p.inside(p.root / "bible" / "camerawork" / slug / f"{slug}.yaml")
    if target.exists():  # a file that did not load (see the issues): do not write over it
        raise OlfError(f"{p.rel(target)} is in the way: fix or remove it first")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    if errors := schema_errors("camerawork", read(target)):  # a broken library file: our bug
        target.unlink()
        raise OlfError(f"{library_id}: {errors[0]}")
    p.add(None, target)
    log.info("show %s: added %s from %s@%s", p.root.name, cam_id, library_id, version)
    return cam_id


def apply_template(p: Project, shot_id: str, template: str | None) -> dict[str, Any]:
    """Put a camerawork template on a shot, or take it off (``None``).

    A library ID (``anime/tu-slow``) is copied into the show first (``add_template``). The
    shot's own move fields go, so the template's values show; framing, angle and lens stay.
    The shot gets the template's default length (``dialogue``: the length of the chosen
    dialogue take, when there is one). A BG-only template (``slots: []``) sets
    ``characters: []`` on a shot that takes its cast from the scene, and a template with slots
    takes that line off again. A cast that the shot states stays (validate warns).

    Returns:
        ``{"template": the ID in the show, ...the fields as written}``.

    Raises:
        OlfError: The shot or the template is missing.
    """
    doc = p.docs.get(shot_id)
    if doc is None or p.kind(shot_id) != "shot":
        raise OlfError(f"{shot_id}: no such shot")
    if not template:
        return {"template": None} | set_shot(p, shot_id, template=None)
    cam_id = template if template.startswith("cam/") else add_template(p, template)
    if p.kind(cam_id) != "camerawork" or cam_id not in p.docs:
        raise OlfError(f"the show has no camerawork template {cam_id}")
    entry = p.docs[cam_id].data
    fields: dict[str, Any] = dict.fromkeys(MOTION) | {"template": cam_id}
    length = (entry.get("timing") or {}).get("default")
    if length == "dialogue":  # as long as the line the shot speaks, up to the next whole frame
        name = (doc.data.get("select") or {}).get("audio")
        take = p.docs.get(f"{shot_id}/{name}")
        spoken = seconds(take.data.get("duration")) if take else 0.0
        length = frames(math.ceil(spoken * FRAMES - 1e-6) / FRAMES) if spoken else None
    if length:
        fields["duration"] = length
    written = set_shot(p, shot_id, **fields)
    node = _node(read(doc.path), shot_id)
    # BG only: clear a cast that the shot takes from its scene, never one that it states, so a
    # template with slots later gives back what the shot had (PR-Agent review of #529).
    empty = entry.get("slots") == [] and "characters" not in node
    if empty or (entry.get("slots") and node.get("characters") == []):
        lines = _lines(doc.path)
        first, end, indent = shot_block(lines, shot_id)
        _put(lines, first, end, indent, "characters", "[]" if empty else None)
        _save(doc.path, lines, lambda data: ("characters" in _node(data, shot_id)) == empty)
        doc.data = _node(read(doc.path), shot_id)
    log.info("shot %s: camerawork %s", shot_id, cam_id)
    return {"template": cam_id} | written


def add_shot(
    p: Project, scene_id: str, description: str, *, duration: str = "3s", framing: str = "medium"
) -> str:
    """Add a shot at the end of a scene, numbered in steps of 10 (``sh020`` after ``sh016``).

    Returns:
        The new shot ID.

    Raises:
        OlfError: The scene is missing, or a value is not allowed.
    """
    scene = p.docs.get(scene_id)
    if scene is None or p.kind(scene_id) != "scene":
        raise OlfError(f"{scene_id}: no such scene")
    numbers = [int(s.rsplit("sh", 1)[1]) for s in p.of_kind("shot") if s.startswith(f"{scene_id}/")]
    shot_id = f"{scene_id}/sh{(max(numbers, default=0) // 10 + 1) * 10:03d}"
    text = str(description or "").strip()
    if not text:
        raise OlfError("a shot needs a description (SPEC.md: required)")
    if framing not in CAMERA["framing"]["enum"]:
        raise OlfError(f"camera.framing must be one of {', '.join(CAMERA['framing']['enum'])}")
    length = _length(duration)
    lines = _lines(scene.path)
    block = _block(lines, "shots")
    items = (
        [line for line in lines[block[0] : block[1]] if line.lstrip().startswith("- ")]
        if block
        else []
    )
    dash = " " * (len(items[0]) - len(items[0].lstrip())) if items else "  "
    entry = [
        f"{dash}- id: {shot_id}\n",
        f"{dash}  duration: {length}\n",
        f"{dash}  description: {json.dumps(text, ensure_ascii=False)}\n",
        f"{dash}  camera: {{ framing: {framing} }}\n",
    ]
    # No shots yet: no key, `shots: []`, or a key with no items. Else add after the last item.
    if block is None or not items or lines[block[0]].split(":", 1)[1].strip() == "[]":
        start, end = block or (len(lines), len(lines))
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines[start:end] = ["shots:\n", *entry, *(lines[start + 1 : end] if block else [])]
    else:
        lines[block[1] : block[1]] = entry
    _save(
        scene.path, lines, lambda data: any(s.get("id") == shot_id for s in data.get("shots") or [])
    )
    log.info("scene %s: added %s", scene_id, shot_id)
    return shot_id


def _list_value(lines: list[str], key: str, items: list[str]) -> None:
    """Set a top-level list key as one flow line: ``scenes: [e02/s03, e02/s04]``."""
    _put(lines, 0, len(lines), "", key, "[" + ", ".join(items) + "]")


def add_scene(p: Project, episode_id: str, heading: str, *, location: str | None = None) -> str:
    """Add a scene file to an episode (``scenes/sNN.yaml``) and list it in ``episode.yaml``.

    Raises:
        OlfError: The episode or the location is missing, or the heading is empty.
    """
    episode = p.docs.get(episode_id)
    if episode is None or p.kind(episode_id) != "episode":
        raise OlfError(f"{episode_id}: no such episode")
    text = str(heading or "").strip()
    if not text:
        raise OlfError("a scene needs a heading, for example INT. LAMP ROOM - NIGHT")
    if location and (p.kind(location) != "location" or location not in p.docs):
        raise OlfError(f"{location}: no such location in the bible")
    numbers = [
        int(s.rsplit("/s", 1)[1]) for s in p.of_kind("scene") if s.startswith(f"{episode_id}/")
    ]
    scene_id = f"{episode_id}/s{max(numbers, default=0) + 1:02d}"
    path = p.inside(episode.path.parent / "scenes" / f"{scene_id.rsplit('/', 1)[1]}.yaml")
    path.parent.mkdir(parents=True, exist_ok=True)
    body = f"id: {scene_id}\nheading: {json.dumps(text, ensure_ascii=False)}\n"
    path.write_text(
        body + (f"location: {location}\n" if location else "") + "shots: []\n", encoding="utf-8"
    )
    listed = [s for s in episode.data.get("scenes") or [] if isinstance(s, str)]
    lines = _lines(episode.path)
    _list_value(lines, "scenes", [*listed, scene_id])
    _save(episode.path, lines, lambda data: scene_id in (data.get("scenes") or []))
    log.info("episode %s: added scene %s (%s)", episode_id, scene_id, path)
    return scene_id


def add_episode(p: Project, title: str, *, season: str | None = None) -> str:
    """Add an episode folder with ``episode.yaml``, listed in ``season`` when one is given.

    Raises:
        OlfError: The title is empty or the season is missing.
    """
    text = str(title or "").strip()
    if not text:
        raise OlfError("an episode needs a title")
    doc = p.docs.get(season) if season else None
    if season and (doc is None or p.kind(season) != "season"):
        raise OlfError(f"{season}: no such season")
    number = max((int(e[1:]) for e in p.of_kind("episode")), default=0) + 1
    episode_id = f"e{number:02d}"
    path = p.inside(p.root / "episodes" / episode_id / "episode.yaml")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"id: {episode_id}\ntitle: {json.dumps(text, ensure_ascii=False)}\nscenes: []\n",
        encoding="utf-8",
    )
    if doc is not None:
        listed = [e for e in doc.data.get("episodes") or [] if isinstance(e, str)]
        lines = _lines(doc.path)
        _list_value(lines, "episodes", [*listed, episode_id])
        _save(doc.path, lines, lambda data: episode_id in (data.get("episodes") or []))
    log.info("added episode %s (%s) to %s", episode_id, path, season or "no season")
    return episode_id


def decode_image(data: str) -> Any:
    """Return a Pillow image from base64 (a ``data:`` URL is fine), checked to be a real image.

    Raises:
        OlfError: The data is not base64, too large, or not a PNG, JPEG or WebP image.
    """
    from PIL import Image, UnidentifiedImageError

    raw = str(data or "").split(",", 1)[-1] if str(data).startswith("data:") else str(data or "")
    try:
        blob = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise OlfError("the image is not base64 data") from exc
    if not blob or len(blob) > MAX_UPLOAD:
        raise OlfError(f"an image must be 1 byte to {MAX_UPLOAD // (1024 * 1024)} MB")
    try:
        image = Image.open(io.BytesIO(blob))
        image.verify()  # checks the whole file; the image must be opened again after this
        image = Image.open(io.BytesIO(blob))
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise OlfError("the file is not a PNG, JPEG or WebP image") from exc
    if image.format not in ("PNG", "JPEG", "WEBP"):
        raise OlfError(f"the image must be PNG, JPEG or WebP, not {image.format}")
    return image


def _save_image(image: Any, target: Path) -> None:
    """Write an image in the format its file name asks for (``.png``, ``.jpg``, ``.webp``)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fmt = {".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP"}.get(target.suffix.lower(), "PNG")
    (image.convert("RGB") if fmt == "JPEG" else image).save(target, fmt)


def replace_sheet(p: Project, char_id: str, data: str, *, sheet: str | None = None) -> str:
    """Replace one of a character's sheet images in place (the primary when ``sheet`` is None).

    The new image keeps the sheet's file name and format, so the character file does not change.
    Takes that used the old sheet become stale (its asset hash changes).

    Returns:
        The project-relative path of the sheet file.
    """
    doc = p.docs.get(char_id)
    if doc is None or p.kind(char_id) != "character":
        raise OlfError(f"{char_id}: no such character")
    image = decode_image(data)
    if sheet and sheet not in sheets_of(doc.data):
        raise OlfError(f"{char_id} has no sheet {sheet!r}")
    name = sheet or str(doc.data.get("sheet") or "")
    if not name or name.startswith("asset/") or "#" in name:
        name = "sheet.png"  # no file to keep: write one and point the entry at it
        lines = _lines(doc.path)
        _put(lines, 0, len(lines), "", "sheet", name)
        _save(doc.path, lines, lambda d: d.get("sheet") == name)
    target = p.inside(doc.path.parent / name)
    _save_image(image, target)
    p.drop_from_lock(p.rel(target))  # the old image is gone: its lock entry would be an error
    log.info("character %s: new sheet %s (%dx%d)", char_id, target, *image.size)
    return p.rel(target)


def add_sheet(p: Project, char_id: str, data: str) -> str:
    """Add a character sheet: ``sheet-2.png`` (then ``-3``, ...) next to the character file,
    listed in ``sheets``. A character with no sheet gets it as its ``sheet``.

    Returns:
        The new sheet's image name, as written in the character file.
    """
    doc = p.docs.get(char_id)
    if doc is None or p.kind(char_id) != "character":
        raise OlfError(f"{char_id}: no such character")
    image = decode_image(data)
    taken = set(sheets_of(doc.data))
    if not doc.data.get("sheet"):
        name = "sheet.png" if "sheet.png" not in taken else "sheet-1.png"
        _save_image(image, p.inside(doc.path.parent / name))
        lines = _lines(doc.path)
        _put(lines, 0, len(lines), "", "sheet", name)
        _save(doc.path, lines, lambda d: d.get("sheet") == name)
        return name
    name = next(
        f"sheet-{n}.png"
        for n in range(2, 1000)
        if f"sheet-{n}.png" not in taken and not (doc.path.parent / f"sheet-{n}.png").exists()
    )
    extra = doc.data.get("sheets") or []
    if not (isinstance(extra, list) and all(isinstance(x, str) for x in extra)):
        raise OlfError(f"{char_id}: sheets must list image files; fix the file first")
    _save_image(image, p.inside(doc.path.parent / name))
    lines = _lines(doc.path)
    _list_value(lines, "sheets", [*extra, name])  # one flow line: sheets: [sheet-2.png, ...]
    _save(doc.path, lines, lambda d: d.get("sheets") == [*extra, name])
    log.info("character %s: added sheet %s", char_id, name)
    return name


def add_form(
    p: Project,
    char_id: str,
    name: str,
    description: str,
    *,
    palette: list[str] | None = None,
    front: str | None = None,
) -> str:
    """Add a form to a character: description, palette, and a front view image.

    Raises:
        OlfError: The character is missing, the name is taken or not a slug, or a value is bad.
    """
    doc = p.docs.get(char_id)
    if doc is None or p.kind(char_id) != "character":
        raise OlfError(f"{char_id}: no such character")
    if not SLUG.fullmatch(str(name or "")):
        raise OlfError(f"a form name is lowercase letters, digits and dashes, not {name!r}")
    if name in (doc.data.get("forms") or {}):
        raise OlfError(f"{char_id} already has a form named {name!r}")
    text = str(description or "").strip()
    if not text:
        raise OlfError("a form needs a description")
    colors = [c for c in palette or [] if c]
    if bad := [c for c in colors if not HEX.fullmatch(c)]:
        raise OlfError(f"palette colors look like #ff7a1a, not {bad[0]!r}")
    view = None
    if front:
        view = f"forms/{name}/front.png"
        _save_image(decode_image(front), p.inside(doc.path.parent / view))
    lines = _lines(doc.path)
    block = _block(lines, "forms")
    entries = [line for line in lines[block[0] + 1 : block[1]] if line.strip()] if block else []
    indent = " " * (len(entries[0]) - len(entries[0].lstrip())) if entries else "  "
    body = [f"{indent}  description: {json.dumps(text, ensure_ascii=False)}\n"]
    body += [f"{indent}  palette: {json.dumps(colors)}\n"] if colors else []
    body += [f"{indent}  views: {{ front: {view} }}\n"] if view else []
    if block is None:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines += ["forms:\n", f"{indent}{name}:\n", *body]
    else:
        _put(lines, block[0] + 1, block[1], indent, name, body)
    _save(
        doc.path, lines, lambda d: (d.get("forms") or {}).get(name, {}).get("description") == text
    )
    log.info("character %s: added form %s (view %s)", char_id, name, view)
    return name
