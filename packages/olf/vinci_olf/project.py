"""Load an OLF project folder: manifest, bible, episodes, scenes, takes and lock file.

Each file keeps its data as written (validation messages point at it) and its
path (a relative asset path resolves against the folder of the file that holds it).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

log = logging.getLogger(__name__)

SPEC = "olf/0.1"
FRAMES = 24  # frames in one second of seconds+frames notation (`3+12` is 3.5 s)
LIBRARY = Path(__file__).resolve().parent / "camerawork"  # the CC0 templates that ship with us
DURATION = re.compile(r"^(?:(\d+(?:\.\d+)?)s?|(\d+)\+(\d{1,2}))$")
EXTS = (".yaml", ".yml", ".json")
BIBLE_KINDS = ("characters", "locations", "props", "voices", "camerawork")
# Object IDs by kind (SPEC.md, IDs). Bible IDs may carry a show prefix (forks).
KINDS = {
    "character": r"([a-z0-9-]+:)?char/[a-z0-9-]+",
    "location": r"([a-z0-9-]+:)?loc/[a-z0-9-]+",
    "prop": r"([a-z0-9-]+:)?prop/[a-z0-9-]+",
    "voice": r"([a-z0-9-]+:)?voice/[a-z0-9-]+",
    "camerawork": r"([a-z0-9-]+:)?cam/[a-z0-9-]+",
    "season": r"season/\d{2,}",
    "episode": r"e\d{2,}",
    "scene": r"e\d{2,}/s\d{2,}",
    "shot": r"e\d{2,}/s\d{2,}/sh\d{3,}",
    "take": r"e\d{2,}/(s\d{2,}/sh\d{3,}/(kf|v|a)|cue/[a-z0-9-]+/a)\d+",
}
# An asset reference: an asset ID or a relative media path. A `#...` ending is matched only so
# that `asset_id` can refuse it: OLF sends whole files and never crops them.
ASSET_REF = re.compile(
    r"^(?P<ref>asset/[0-9a-f]+|[^\s#]+\.(?:png|jpe?g|webp|gif|wav|mp3|m4a|ogg|flac|mp4|mov|webm))"
    r"(?P<crop>#\S*)?$",
    re.IGNORECASE,
)


def sheets_of(data: Any) -> list[str]:
    """A character's sheets: the primary ``sheet`` first, then ``sheets``.

    Each whole sheet is a reference image. Wrong shapes give nothing (the schema reports them).
    """
    if not isinstance(data, dict):
        return []
    extra = data.get("sheets")
    names = [data.get("sheet"), *(extra if isinstance(extra, list) else [])]
    return [s for s in names if isinstance(s, str) and s]


class OlfError(ValueError):
    """A project problem that the user must fix (bad reference, missing file, bad input)."""


def seconds(value: Any, default: float = 0.0) -> float:
    """Read a duration as seconds: ``4s``, ``2.5``, a number, or seconds+frames (``3+12``).

    Seconds+frames is the notation of anime storyboards and timesheets. A frame is always
    1/24 s, also in a 30 fps project, so one value has one meaning. Anything else is ``default``.
    """
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    match = DURATION.match(str(value).strip())
    if match is None or (match[3] and int(match[3]) >= FRAMES):
        return default
    return float(match[1]) if match[1] else int(match[2]) + int(match[3]) / FRAMES


def frames(value: float) -> str:
    """Seconds as seconds+frames, to the nearest frame: ``3.5`` is ``3+12``."""
    total = round(value * FRAMES)
    return f"{total // FRAMES}+{total % FRAMES:02d}"


@dataclass
class Doc:
    """One loaded file: its data as written, and its path."""

    data: dict[str, Any]
    path: Path


def read(path: Path) -> Any:
    """Read one YAML 1.2 or JSON file into plain Python values.

    Args:
        path: File to read.

    Returns:
        The parsed value. Timestamps become ISO strings, so every value is JSON.
    """
    text = path.read_text(encoding="utf-8")
    data = json.loads(text) if path.suffix == ".json" else YAML(typ="safe", pure=True).load(text)
    return _plain(data)


# Values per file. A show file holds hundreds; nested YAML aliases expand without a cap.
MAX_VALUES = 100_000


def _plain(value: Any, count: list[int] | None = None) -> Any:
    count = count if count is not None else [0]
    count[0] += 1
    if count[0] > MAX_VALUES:  # Project.add reports it as "cannot read"
        raise ValueError(f"more than {MAX_VALUES} values (nested YAML aliases?)")
    if isinstance(value, dict):
        return {str(k): _plain(v, count) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v, count) for v in value]
    if isinstance(value, dt.date):  # YAML timestamps; also covers datetime
        return value.isoformat().replace("+00:00", "Z")
    return value


def write(data: Any, target: Path | TextIO, *, compact: bool = False) -> None:
    """Write ``data`` as block-style YAML 1.2 to a file or a stream.

    The round-trip writer keeps the comments of maps that were loaded with it. ``compact``
    writes a new file in the spec's style: a list or map of plain values goes on one line.
    """
    yaml = YAML()
    yaml.default_flow_style = None if compact else False
    if compact and isinstance(data, dict):  # the top level stays one key per line
        data = CommentedMap(data)
        data.fa.set_block_style()
    yaml.width = 4096  # keep prompts and asset IDs on one line
    if not isinstance(target, Path):
        yaml.dump(data, target)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as fh:
        yaml.dump(data, fh)


def _find(stem: Path) -> Path | None:
    return next((stem.with_suffix(ext) for ext in EXTS if stem.with_suffix(ext).is_file()), None)


@dataclass
class Project:
    """An OLF project folder, loaded."""

    root: Path
    docs: dict[str, Doc] = field(default_factory=dict)  # object ID -> file
    lock: dict[str, Any] = field(default_factory=dict)  # asset ID -> lock entry
    problems: list[str] = field(default_factory=list)  # load errors (duplicate IDs, bad files)
    files: dict[str, Path] = field(default_factory=dict)  # asset hash -> local file
    _hashes: dict[Path, str] = field(default_factory=dict)
    known: dict[str, str] = field(default_factory=dict)  # relative path -> SHA-256 from a host

    @property
    def manifest(self) -> dict[str, Any]:
        return self.docs["project"].data

    def rel(self, path: Path) -> str:
        """Return ``path`` relative to the project folder, for messages and lock URIs."""
        try:
            return path.resolve().relative_to(self.root).as_posix()
        except ValueError:
            return str(path)

    def kind(self, key: str) -> str:
        """Return the object kind for an object ID (``character``, ``shot``, ...)."""
        if key in ("project", "show", "style"):
            return key
        return next((k for k, rx in KINDS.items() if re.fullmatch(rx, key)), "unknown")

    def of_kind(self, kind: str) -> dict[str, Doc]:
        return {k: d for k, d in self.docs.items() if self.kind(k) == kind}

    def add(self, key: str | None, path: Path, data: Any = None) -> Doc | None:
        """Register one object. Duplicate or missing IDs become load problems."""
        if data is None:
            try:
                data = read(path)
            except Exception as exc:  # noqa: BLE001 - any parse error is a user problem
                self.problems.append(f"{self.rel(path)}: cannot read: {exc}")
                return None
        if not isinstance(data, dict):
            self.problems.append(f"{self.rel(path)}: expected a mapping")
            return None
        key = key or str(data.get("id") or "")
        if not key:
            self.problems.append(f"{self.rel(path)}: missing id")
        elif key in self.docs:
            self.problems.append(
                f"{self.rel(path)}: duplicate id {key} (also in {self.rel(self.docs[key].path)})"
            )
        else:
            self.docs[key] = Doc(data, path)
            return self.docs[key]
        return None

    def season_of(self, episode_id: str) -> Doc | None:
        """Return the season that lists an episode, or None (an episode in no season)."""
        return next(
            (
                doc
                for key, doc in self.docs.items()
                if self.kind(key) == "season"
                and isinstance(doc.data.get("episodes"), list)  # a malformed season lists nothing
                and episode_id in doc.data["episodes"]
            ),
            None,
        )

    def sha256(self, path: Path) -> str:
        if path not in self._hashes:
            if known := self.known.get(self.rel(path)):  # a hosted show: the bytes live elsewhere
                self._hashes[path] = known
            else:
                with path.open("rb") as handle:  # in chunks: takes can be large videos
                    self._hashes[path] = hashlib.file_digest(handle, "sha256").hexdigest()
        return self._hashes[path]

    def inside(self, path: Path) -> Path:
        """Resolve ``path``; refuse it outside the project folder (projects can be untrusted)."""
        path = path.resolve()
        if not path.is_relative_to(self.root):
            raise OlfError(f"{path} is outside the project folder")
        return path

    def asset_id(self, value: str, base: Path) -> str | None:
        """Return the full asset ID for an asset reference, or None when ``value`` is plain text.

        Args:
            value: A string from an OLF file.
            base: Folder of the file that holds ``value``.

        Raises:
            OlfError: The relative file is missing or outside the project, or ``value`` names a
                crop (``sheet.png#eyes``).
        """
        match = ASSET_REF.match(value)
        if not match:
            return None
        ref = match["ref"]
        if match["crop"]:  # sheet crops were dropped on 2026-11-09: a whole file is the reference
            raise OlfError(
                f"{value}: point to a whole file ({ref} or a separate image), not a crop"
            )
        if ref.startswith("asset/"):
            digest = ref.removeprefix("asset/")
        else:
            path = self.inside(base / ref)
            if not path.is_file():
                raise OlfError(f"missing file {self.rel(path)}")
            digest = self.sha256(path)
            self.files[digest] = path
        return f"asset/{digest}"

    def hashed(self, value: Any, base: Path) -> Any:
        """Copy ``value`` with every asset reference replaced by its full asset ID."""
        if isinstance(value, dict):
            return {k: self.hashed(v, base) for k, v in value.items()}
        if isinstance(value, list):
            return [self.hashed(v, base) for v in value]
        if isinstance(value, str):
            return self.asset_id(value, base) or value
        return value

    def local_file(self, asset: str) -> Path:
        """Return the local file of an asset, and verify its hash (SPEC.md: MUST verify on fetch).

        Raises:
            OlfError: The asset is not in the lock file, is remote, is missing or has a wrong hash.
        """
        digest = asset.removeprefix("asset/")
        if digest in self.files:
            return self.files[digest]
        uri = str((self.lock.get(f"asset/{digest}") or {}).get("uri") or "")
        if not uri:
            raise OlfError(f"asset/{digest} is not in assets/lock.yaml")
        if "://" in uri:
            raise OlfError(f"asset/{digest}: only relative file URIs work for now, not {uri}")
        path = self.inside(self.root / uri)
        if not path.is_file() or self.sha256(path) != digest:
            raise OlfError(f"asset/{digest}: {uri} is missing or its hash does not match")
        self.files[digest] = path
        return path

    def add_to_lock(self, entries: dict[str, dict[str, Any]]) -> None:
        """Add new lock entries. Existing entries (and their comments) stay as they are."""
        path = self.root / "assets" / "lock.yaml"
        doc = YAML().load(path.read_text(encoding="utf-8")) if path.is_file() else None
        doc = doc if doc is not None else {}
        new = {k: v for k, v in entries.items() if k not in doc}
        if new:
            doc.update(new)
            write(doc, path)
            self.lock.update(new)
            log.info("lock: added %s", ", ".join(new))

    def drop_from_lock(self, uri: str) -> None:
        """Remove the lock entries of a project file that was overwritten (a replaced sheet).

        They pin content that is gone, so validation would report them. The next render adds
        the new content.
        """
        path = self.root / "assets" / "lock.yaml"
        old = [k for k, v in self.lock.items() if isinstance(v, dict) and v.get("uri") == uri]
        if not old or not path.is_file():
            return
        doc = YAML().load(path.read_text(encoding="utf-8"))
        for key in old:
            doc.pop(key, None)
            self.lock.pop(key, None)
        write(doc, path)
        log.info("lock: removed %s (%s was replaced)", ", ".join(old), uri)


def load(root: Path | str, *, hashes: dict[str, str] | None = None) -> Project:
    """Load an OLF project folder.

    Args:
        root: The project folder (it holds ``project.yaml``).
        hashes: SHA-256 hex digests by project-relative path, used as given instead of reading
            those files. A host that keeps a show's media in object storage passes them, and its
            working folder holds empty stand-ins. A local folder passes none: every file is read.

    Raises:
        OlfError: There is no manifest.
    """
    project = Project(Path(root).resolve(), known=dict(hashes or {}))
    top = project.root
    manifest = _find(top / "project")
    if manifest is None:
        raise OlfError(f"{top}: no project.yaml, so this is not an OLF project")
    if project.add("project", manifest) is None:  # every later step reads the manifest
        raise OlfError(f"{top}: {project.problems[-1]}")
    for key in ("show", "style"):
        if path := _find(top / "bible" / key):
            project.add(key, path)
    for kind in BIBLE_KINDS:
        for folder in sorted(p for p in (top / "bible" / kind).glob("*") if p.is_dir()):
            if path := _find(folder / folder.name):
                project.add(None, path)
    for path in sorted((top / "seasons").glob("*")):  # optional: seasons group episodes
        if path.suffix in EXTS:
            project.add(None, path)
    for folder in sorted(p for p in (top / "episodes").glob("*") if p.is_dir()):
        if path := _find(folder / "episode"):
            project.add(None, path)
        for path in sorted((folder / "scenes").glob("*")):
            if path.suffix in EXTS and (scene := project.add(None, path)):
                for shot in scene.data.get("shots") or []:  # inline shots (the default)
                    project.add(None, path, shot)
        for path in sorted((folder / "scenes").glob("*/*")):  # one file per shot (allowed)
            if path.suffix in EXTS:
                project.add(None, path)
    for path in sorted((top / "takes").rglob("*")):
        # <take>.inputs.json keeps the hash view of a take (vinci_olf.explain); it is not an object
        if path.suffix in EXTS and not path.name.endswith(".inputs.json"):
            project.add(None, path)
    if lock := _find(top / "assets" / "lock"):
        try:
            data = read(lock)
        except Exception as exc:  # noqa: BLE001 - any parse error is a user problem
            data = None
            project.problems.append(f"{project.rel(lock)}: cannot read: {exc}")
        if isinstance(data, dict):
            project.lock = data
        elif data is not None:  # an empty lock file is fine
            project.problems.append(f"{project.rel(lock)}: expected a mapping")
    log.info("loaded %s: %d objects, %d lock entries", top, len(project.docs), len(project.lock))
    return project
