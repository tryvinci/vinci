"""The ``.volf`` package (SPEC.md, Package): a whole OLF project as one ZIP file.

``pack`` writes a project folder into a package (the Studio's Share/Export). ``unpack`` reads a
package into a new folder (Import). A package can come from someone you do not trust, so
``unpack`` refuses unsafe entries before it writes anything, and stops at its size limits.
"""

from __future__ import annotations

import logging
import shutil
import stat
import zipfile
import zlib
from pathlib import Path, PurePosixPath
from typing import IO

from vinci_olf.project import EXTS, OlfError, Project

log = logging.getLogger(__name__)

DERIVED = ("exports", "previs")  # made again on request: never in a package
JUNK = ("__MACOSX", ".DS_Store")  # what a hand-made macOS zip adds: skipped, not refused
MAX_FILES = 20_000
MAX_BYTES = 5 * 10**9  # unpacked bytes (5 GB); a host passes its own quota
MANIFESTS = tuple(f"project{ext}" for ext in EXTS)


def pack(
    project: Project, dest: Path | str, *, max_files: int = MAX_FILES, max_bytes: int = MAX_BYTES
) -> int:
    """Write ``project`` as a ``.volf`` package: one top folder named after the project folder.

    ``exports/`` and ``previs/`` are left out (derived files). A link that leaves the project is
    skipped, so a package never carries a file from outside the folder. A show past the limits
    that ``unpack`` uses is refused before anything is written: an Export always imports again.

    Args:
        project: The loaded project.
        dest: The package file to write.
        max_files: The most files a package may hold (the same as ``unpack``).
        max_bytes: The most bytes it may hold before compression (the same as ``unpack``).

    Returns:
        The number of files written.

    Raises:
        OlfError: The show has more files or bytes than a package may hold.
    """
    files = []
    for file in sorted(project.root.rglob("*")):
        rel = file.relative_to(project.root)
        if not file.is_file() or rel.parts[0] in DERIVED:
            continue
        try:
            project.inside(file)  # resolves links: one that leaves the project is skipped
        except OlfError:
            log.warning("volf: pack skips %s (outside the project)", rel)
            continue
        files.append((file, rel))
    for _, rel in files:
        if "\\" in str(rel):  # unpack reads a backslash as a folder: the file would move
            raise OlfError(f"a file name with a backslash cannot go in a package: {rel}")
    _check_names([PurePosixPath(rel.as_posix()) for _, rel in files])  # what unpack checks
    size = sum(file.stat().st_size for file, _ in files)
    if len(files) > max_files or size > max_bytes:
        raise OlfError(
            f"this show is too large for one package ({len(files)} files, {size / 1e9:.1f} GB);"
            f" a package holds at most {max_files} files and {max_bytes / 1e9:.1f} GB"
        )
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as archive:
        for file, rel in files:
            archive.write(file, Path(project.root.name) / rel)
    log.info("volf: packed %s (%d files, %d bytes) into %s", project.root, len(files), size, dest)
    return len(files)


def _too_big(max_bytes: int) -> str:
    return f"the package unpacks to more than {max_bytes / 1e9:.1f} GB"


def _check_names(paths: list[PurePosixPath]) -> None:
    """Refuse paths that clash once case-folded: the same file twice, or a file that is a folder.

    Both ``pack`` and ``unpack`` call it, so every package that Export writes imports again.
    Case-folded, because two names that differ only in case are one file on macOS and Windows.
    """
    seen: set[str] = set()
    parents: set[str] = set()
    for path in paths:
        key = str(path).casefold()
        if key in seen:
            raise OlfError(
                f"the package has the same file twice (names differ only in case?): {path}"
            )
        seen.add(key)
        parents.update(str(parent).casefold() for parent in path.parents)
    clash = next((path for path in paths if str(path).casefold() in parents), None)
    if clash:
        raise OlfError(f"the package has a file and a folder with the same name: {clash}")


def _entries(
    archive: zipfile.ZipFile, max_files: int, max_bytes: int
) -> list[tuple[zipfile.ZipInfo, PurePosixPath]]:
    """The archive's files with safe relative paths; raise on the first unsafe entry."""
    rows: list[tuple[zipfile.ZipInfo, PurePosixPath]] = []
    for info in archive.infolist():
        name = info.filename.replace("\\", "/")
        path = PurePosixPath(name)
        if info.is_dir() or not path.parts or path.parts[0] in JUNK or path.name in JUNK:
            continue
        if name.startswith("/") or ":" in path.parts[0] or ".." in path.parts:
            raise OlfError(f"the package has an unsafe path: {info.filename}")
        if stat.S_ISLNK(info.external_attr >> 16):
            raise OlfError(f"the package has a link, which a package may not hold: {info.filename}")
        if info.flag_bits & 0x1:
            raise OlfError(f"the package has a password-protected file: {info.filename}")
        rows.append((info, path))
    _check_names([path for _, path in rows])
    if len(rows) > max_files:
        raise OlfError(f"the package has {len(rows)} files; the limit is {max_files}")
    if sum(info.file_size for info, _ in rows) > max_bytes:
        raise OlfError(_too_big(max_bytes))
    return rows


def _top(rows: list[tuple[zipfile.ZipInfo, PurePosixPath]]) -> int:
    """How many leading path parts to drop: 1 (one top folder holds the manifest) or 0 (root)."""
    names = {str(path) for _, path in rows}
    tops = {path.parts[0] for _, path in rows if len(path.parts) > 1}
    if any(m in names for m in MANIFESTS):
        return 0  # a folder zipped from the inside (SPEC.md: readers MAY accept it); it wins
    if len(tops) == 1 and any(f"{next(iter(tops))}/{m}" in names for m in MANIFESTS):
        return 1
    raise OlfError("the package has no project.yaml (or .yml, .json): it is not an OLF project")


def unpack(
    source: Path | str | IO[bytes],
    dest: Path | str,
    *,
    max_files: int = MAX_FILES,
    max_bytes: int = MAX_BYTES,
) -> Path:
    """Unpack a ``.volf`` package into ``dest``, a folder that must not exist yet.

    Every entry is checked before the first file is written: no absolute path, ``..``, drive,
    link, password, duplicate or file-folder clash, at most ``max_files`` files and ``max_bytes``
    unpacked bytes, and a manifest at the root or in one top folder (the root wins). The bytes
    are also counted while they are written, and a damaged entry (CRC) is refused. On any error
    ``dest`` is removed.

    Args:
        source: The package file, or an open binary file.
        dest: The new project folder.
        max_files: The most files the package may hold.
        max_bytes: The most bytes it may unpack to.

    Returns:
        ``dest`` as a resolved path.

    Raises:
        OlfError: The file is not a ZIP, or it breaks a rule above.
    """
    dest = Path(dest)
    try:
        archive = zipfile.ZipFile(source)
    except (zipfile.BadZipFile, OSError) as exc:
        raise OlfError("the file is not a .volf package (not a ZIP file)") from exc
    with archive:
        rows = _entries(archive, max_files, max_bytes)
        drop = _top(rows)
        try:
            dest.mkdir(parents=True)  # claims it; a file or link there (even dangling) fails
        except FileExistsError as exc:
            raise OlfError(f"{dest} exists already") from exc
        root = dest.resolve()
        written = 0
        try:
            for info, path in rows:
                rel = PurePosixPath(*path.parts[drop:])
                if not rel.parts or rel.parts[0] in DERIVED:
                    continue  # writers leave derived files out; a reader need not keep them
                target = (root / rel).resolve()
                if not target.is_relative_to(root):
                    raise OlfError(f"the package has an unsafe path: {info.filename}")
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as src, target.open("wb") as out:
                    while chunk := src.read(1 << 20):
                        written += len(chunk)
                        if written > max_bytes:
                            raise OlfError(_too_big(max_bytes))
                        out.write(chunk)
        except NotImplementedError as exc:  # a compression this Python cannot read
            shutil.rmtree(dest, ignore_errors=True)
            raise OlfError(f"the package uses a compression that is not supported ({exc})") from exc
        except (zipfile.BadZipFile, zlib.error) as exc:  # bad CRC or bad compressed data
            shutil.rmtree(dest, ignore_errors=True)
            raise OlfError(f"the package is damaged ({exc})") from exc
        except BaseException:
            shutil.rmtree(dest, ignore_errors=True)  # a failed unpack leaves nothing behind
            raise
    log.info("volf: unpacked %d files (%d bytes) into %s", len(rows), written, root)
    return root
