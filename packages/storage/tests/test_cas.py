from pathlib import Path

from vinci_storage.cas import ContentAddressedStore


def test_cas_put_get_and_dedupe(tmp_path: Path) -> None:
    cas = ContentAddressedStore(tmp_path / "cas")
    digest = cas.put(b"hello-vinci")
    assert cas.exists(digest)
    assert cas.get(digest) == b"hello-vinci"
    again = cas.put(b"hello-vinci")
    assert again == digest


def test_put_stream_matches_put_and_leaves_no_temp_file(tmp_path: Path) -> None:
    """COREPRODUC-710: an upload streams into the store; the digest is the same as put()."""
    import io

    cas = ContentAddressedStore(tmp_path / "cas")
    data = b"x" * (3 * 1024 * 1024 + 7)  # more than one 1 MB chunk
    digest, size = cas.put_stream(io.BytesIO(data))
    assert (digest, size) == (cas.digest(data), len(data)) and cas.get(digest) == data
    assert cas.put_stream(io.BytesIO(data)) == (digest, size)  # stored once
    assert not list((tmp_path / "cas").glob(".incoming-*"))


def test_put_stream_removes_its_temp_file_on_a_read_error(tmp_path: Path) -> None:
    import pytest

    class Broken:
        def read(self, n: int) -> bytes:
            raise OSError("the upload stopped")

    cas = ContentAddressedStore(tmp_path / "cas")
    with pytest.raises(OSError):
        cas.put_stream(Broken())  # type: ignore[arg-type]
    assert not list((tmp_path / "cas").glob(".incoming-*"))
