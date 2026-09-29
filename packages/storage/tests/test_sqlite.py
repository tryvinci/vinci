from pathlib import Path

from vinci_protocol.enums import JobState
from vinci_protocol.models import Job
from vinci_storage.sqlite_store import SqliteStore


def test_job_roundtrip_redacts_secret_keys(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "db.sqlite")
    job = Job(
        id="j1",
        model_id="mock:png:v1",
        state=JobState.CREATED,
        inputs={"prompt": "hi", "api_key": "should-not-persist"},
    )
    store.put_job(job, secret_values=["should-not-persist"])
    loaded = store.get_job("j1")
    assert loaded is not None
    assert loaded.inputs["api_key"] == "[redacted]"
    assert "should-not-persist" not in str(loaded.model_dump())
