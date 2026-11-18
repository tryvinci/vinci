"""The .volf package (SPEC.md, Package; COREPRODUC-699): pack, unpack and the reader's rules."""

from __future__ import annotations

import shutil
import stat
import zipfile
from pathlib import Path

import pytest
from vinci_olf import OlfError, load, validate
from vinci_olf.package import pack, unpack

SAMPLE = Path(__file__).resolve().parents[1] / "conformance" / "tidewatch"


def _zip(path: Path, entries: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return path


def test_pack_then_unpack_gives_the_same_project(tmp_path: Path) -> None:
    show = Path(shutil.copytree(SAMPLE, tmp_path / "tidewatch"))
    (show / "exports" / "e02").mkdir(parents=True)
    (show / "exports" / "e02" / "e02-16x9.mp4").write_bytes(b"derived")
    package = tmp_path / "tidewatch.volf"
    count = pack(load(show), package)
    names = zipfile.ZipFile(package).namelist()
    assert count == len(names) and "tidewatch/project.yaml" in names
    assert all(n.startswith("tidewatch/") for n in names)  # one top folder
    assert not [n for n in names if "/exports/" in n]  # derived files stay out
    root = unpack(package, tmp_path / "copy")
    assert root == (tmp_path / "copy").resolve() and (root / "project.yaml").is_file()
    a, b = load(show), load(root)
    assert a.manifest == b.manifest and sorted(a.docs) == sorted(b.docs) and a.lock == b.lock
    assert [i for i in validate(b) if i.level == "error"] == []


def test_a_root_manifest_and_mac_junk_are_accepted(tmp_path: Path) -> None:
    package = _zip(
        tmp_path / "hand.volf",
        {
            "project.json": b'{"spec": "olf/0.1", "show": "x", "title": "X"}',
            "__MACOSX/._project.json": b"junk",
            ".DS_Store": b"junk",
        },
    )
    root = unpack(package, tmp_path / "x")
    assert sorted(p.name for p in root.iterdir()) == ["project.json"]


@pytest.mark.parametrize(
    "entries, words",
    [
        ({"show/project.yaml": b"spec: olf/0.1", "show/../evil.txt": b"x"}, "unsafe path"),
        ({"/abs/project.yaml": b"spec: olf/0.1"}, "unsafe path"),
        ({"C:/show/project.yaml": b"spec: olf/0.1"}, "unsafe path"),
        ({"show/notes.txt": b"x"}, "no project.yaml"),
        (
            {"a/project.yaml": b"spec: olf/0.1", "b/project.yaml": b"spec: olf/0.1"},
            "no project.yaml",
        ),
    ],
)
def test_unsafe_or_empty_packages_are_refused(
    tmp_path: Path, entries: dict[str, bytes], words: str
) -> None:
    with pytest.raises(OlfError, match=words):
        unpack(_zip(tmp_path / "bad.volf", entries), tmp_path / "out")
    assert not (tmp_path / "out").exists()  # nothing written


def test_links_limits_and_bad_files_are_refused(tmp_path: Path) -> None:
    link = zipfile.ZipInfo("show/sheet.png")
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(tmp_path / "link.volf", "w") as archive:
        archive.writestr("show/project.yaml", "spec: olf/0.1")
        archive.writestr(link, "/etc/passwd")
    with pytest.raises(OlfError, match="link"):
        unpack(tmp_path / "link.volf", tmp_path / "a")
    many = _zip(
        tmp_path / "many.volf",
        {f"show/f{i}.txt": b"x" for i in range(5)} | {"show/project.yaml": b"spec: olf/0.1"},
    )
    with pytest.raises(OlfError, match="the limit is 3"):
        unpack(many, tmp_path / "b", max_files=3)
    with pytest.raises(OlfError, match="unpacks to more than"):
        unpack(many, tmp_path / "c", max_bytes=10)
    (tmp_path / "text.volf").write_text("not a zip")
    with pytest.raises(OlfError, match="not a ZIP"):
        unpack(tmp_path / "text.volf", tmp_path / "d")
    (tmp_path / "e").mkdir()
    with pytest.raises(OlfError, match="exists already"):
        unpack(many, tmp_path / "e")


def test_a_damaged_package_is_refused_and_leaves_nothing(tmp_path: Path) -> None:
    """A ZIP whose data does not match its CRC is refused as damaged, not a server error."""
    package = _zip(
        tmp_path / "x.volf", {"show/project.yaml": b"spec: olf/0.1", "show/a.txt": b"A" * 64}
    )
    data = bytearray(package.read_bytes())
    data[data.index(b"A" * 64)] = ord("B")  # stored entry: flip one byte of its data
    package.write_bytes(bytes(data))
    with pytest.raises(OlfError, match="damaged"):
        unpack(package, tmp_path / "out")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize(
    "entries, words",
    [
        (
            {"show/project.yaml": b"spec: olf/0.1", "show/a.txt": b"1", "show/A.txt": b"2"},
            "same file",
        ),
        (
            {"show/project.yaml": b"spec: olf/0.1", "show/assets": b"x", "show/assets/c.png": b"y"},
            "file and a folder",
        ),
    ],
)
def test_duplicates_and_clashes_are_refused(
    tmp_path: Path, entries: dict[str, bytes], words: str
) -> None:
    with pytest.raises(OlfError, match=words):
        unpack(_zip(tmp_path / "bad.volf", entries), tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_a_password_protected_entry_is_refused(tmp_path: Path) -> None:
    package = _zip(tmp_path / "p.volf", {"show/project.yaml": b"spec: olf/0.1", "show/a.png": b"x"})
    data = bytearray(package.read_bytes())
    for sig in (b"PK\x03\x04", b"PK\x01\x02"):  # set the "encrypted" flag on each header
        at = 0
        while (at := data.find(sig, at)) >= 0:
            flag = at + (6 if sig == b"PK\x03\x04" else 8)
            data[flag] |= 0x1
            at += 4
    package.write_bytes(bytes(data))
    with pytest.raises(OlfError, match="password"):
        unpack(package, tmp_path / "out")


def test_a_root_manifest_wins_over_a_nested_backup(tmp_path: Path) -> None:
    package = _zip(
        tmp_path / "r.volf",
        {
            "project.yaml": b"spec: olf/0.1\nshow: root",
            "backup/project.yaml": b"spec: olf/0.1\nshow: old",
        },
    )
    root = unpack(package, tmp_path / "out")
    assert (root / "project.yaml").read_text().endswith("show: root")
    assert (root / "backup" / "project.yaml").is_file()


def test_a_dangling_link_at_dest_is_not_followed(tmp_path: Path) -> None:
    package = _zip(tmp_path / "x.volf", {"show/project.yaml": b"spec: olf/0.1"})
    (tmp_path / "out").symlink_to(tmp_path / "elsewhere")
    with pytest.raises(OlfError, match="exists already"):
        unpack(package, tmp_path / "out")
    assert not (tmp_path / "elsewhere").exists()


def test_pack_refuses_a_show_that_import_would_refuse(tmp_path: Path) -> None:
    show = Path(shutil.copytree(SAMPLE, tmp_path / "tidewatch"))
    with pytest.raises(OlfError, match="too large for one package"):
        pack(load(show), tmp_path / "t.volf", max_files=3)
    assert not (tmp_path / "t.volf").exists()


def test_pack_refuses_names_that_differ_only_in_case(tmp_path: Path) -> None:
    show = Path(shutil.copytree(SAMPLE, tmp_path / "tidewatch"))
    (show / "Notes.txt").write_text("a")
    if (show / "notes.txt").exists():
        pytest.skip("case-insensitive disk: the two names are one file here")
    (show / "notes.txt").write_text("b")
    with pytest.raises(OlfError, match="differ only in case"):
        pack(load(show), tmp_path / "t.volf")


def test_an_unsupported_compression_is_refused(tmp_path: Path) -> None:
    package = _zip(
        tmp_path / "c.volf", {"show/project.yaml": b"spec: olf/0.1", "show/a.bin": b"x" * 32}
    )
    data = bytearray(package.read_bytes())
    for sig, at_method in ((b"PK\x03\x04", 8), (b"PK\x01\x02", 10)):
        at = 0
        while (at := data.find(sig, at)) >= 0:
            if data[at + (30 if sig == b"PK\x03\x04" else 46) :].startswith(b"show/a.bin"):
                data[at + at_method] = 99  # method 99 (AES): this Python cannot read it
            at += 4
    package.write_bytes(bytes(data))
    with pytest.raises(OlfError, match="not supported"):
        unpack(package, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_pack_refuses_what_unpack_would_move_or_refuse(tmp_path: Path) -> None:
    """A backslash name moves on import, and Notes plus notes/ clash: Export refuses both."""
    show = Path(shutil.copytree(SAMPLE, tmp_path / "tidewatch"))
    try:
        (show / "a\\b.txt").write_text("x")
    except OSError:
        pytest.skip("this disk does not allow a backslash in a file name")
    with pytest.raises(OlfError, match="backslash"):
        pack(load(show), tmp_path / "a.volf")
    (show / "a\\b.txt").unlink()
    (show / "Notes").write_text("x")
    if (show / "notes").exists():
        pytest.skip("case-insensitive disk: Notes and notes are one name here")
    (show / "notes").mkdir()
    (show / "notes" / "cover.png").write_bytes(b"x")
    with pytest.raises(OlfError, match="file and a folder"):
        pack(load(show), tmp_path / "b.volf")


def test_bad_deflate_data_is_a_damaged_package(tmp_path: Path) -> None:
    with zipfile.ZipFile(tmp_path / "d.volf", "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("show/project.yaml", "spec: olf/0.1")
        archive.writestr("show/a.bin", b"\x00" * 4096)
    data = bytearray((tmp_path / "d.volf").read_bytes())
    at = data.find(b"show/a.bin") + len(b"show/a.bin")  # the entry's compressed data follows
    data[at : at + 8] = b"\xff" * 8
    (tmp_path / "d.volf").write_bytes(bytes(data))
    with pytest.raises(OlfError, match="damaged"):
        unpack(tmp_path / "d.volf", tmp_path / "out")
    assert not (tmp_path / "out").exists()
