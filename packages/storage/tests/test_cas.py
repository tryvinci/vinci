from pathlib import Path

from vinci_storage.cas import ContentAddressedStore


def test_cas_put_get_and_dedupe(tmp_path: Path) -> None:
    cas = ContentAddressedStore(tmp_path / "cas")
    digest = cas.put(b"hello-vinci")
    assert cas.exists(digest)
    assert cas.get(digest) == b"hello-vinci"
    again = cas.put(b"hello-vinci")
    assert again == digest
