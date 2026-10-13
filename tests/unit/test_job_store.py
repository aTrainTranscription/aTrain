"""Unit tests for aTrain_core.jobs.JobStore (queue.json persistence)."""

import pytest
from aTrain_core import jobs
from aTrain_core.jobs import JobStatus, JobStore
from tests.unit.test_jobs import make_spec


def ids(store: JobStore) -> list[str]:
    return [spec.id for spec, _ in store.jobs()]


def test_add_and_reload(tmp_path):
    store = JobStore(tmp_path, tmp_path / "transcriptions")
    store.add([make_spec(id="a"), make_spec(id="b", speaker_detection=False)])
    store.update("a", status=JobStatus.RUNNING, started_at="2026-09-30 14-06-40")

    reloaded = JobStore(tmp_path, tmp_path / "transcriptions")
    assert ids(reloaded) == ["a", "b"]
    assert reloaded.get("a") == store.get("a")
    assert not (tmp_path / "queue.json.tmp").exists()


def test_work_files_live_in_the_reserved_output_folder(tmp_path):
    store = JobStore(tmp_path / "queue", tmp_path / "transcriptions")
    source = store.uploads_root / "a" / "audio.mp3"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"audio")
    store.add([make_spec(id="a", source=source), make_spec(id="b")])

    first = store.work_dir("a")
    second = store.work_dir("b")
    assert first.name == ".pending"
    assert first.is_dir()
    assert store.get("a")[0].source == first / "input" / source.name
    assert store.get("a")[0].source.read_bytes() == b"audio"
    assert not source.exists()
    assert first.parent.parent == tmp_path / "transcriptions"
    assert first.parent.name == store.get("a")[1].file_id
    assert first.parent != second.parent
    assert JobStore(store.root, store.transcript_root).work_dir("a") == first


def test_removing_a_finished_job_preserves_its_outputs(tmp_path):
    store = JobStore(tmp_path / "queue", tmp_path / "transcriptions")
    store.add([make_spec(id="a")])
    pending = store.work_dir("a")
    pending.mkdir(parents=True, exist_ok=True)
    output = pending.parent / "transcription.txt"
    output.write_text("Finished transcript")
    store.update("a", status=JobStatus.DONE)

    store.remove("a")

    assert not pending.exists()
    assert output.read_text() == "Finished transcript"


def test_failed_add_restores_uploads_and_removes_claimed_folders(tmp_path, monkeypatch):
    store = JobStore(tmp_path / "queue", tmp_path / "transcriptions")
    source = store.uploads_root / "a" / "audio.mp3"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"audio")

    def disk_full(*args):
        raise OSError("disk full")

    monkeypatch.setattr(store, "_save", disk_full)
    with pytest.raises(OSError, match="disk full"):
        store.add([make_spec(id="a", source=source), make_spec(id="b")])

    assert store.jobs() == []
    assert source.read_bytes() == b"audio"
    assert list(store.transcript_root.iterdir()) == [store.uploads_root]


def test_move(tmp_path):
    store = JobStore(tmp_path, tmp_path / "transcriptions")
    store.add([make_spec(id=job_id) for job_id in "abc"])
    store.move("c", -1)
    assert ids(store) == ["a", "c", "b"]
    store.move("a", -1)  # already first
    store.move("a", 5)  # clamped to the end
    assert ids(JobStore(tmp_path, tmp_path / "transcriptions")) == ["c", "b", "a"]


def test_unreadable_queue_is_moved_aside(tmp_path):
    (tmp_path / "queue.json").write_text("{not json", encoding="utf-8")
    store = JobStore(tmp_path, tmp_path / "transcriptions")
    assert store.jobs() == []
    assert [p.name.startswith("queue.json.unreadable-") for p in tmp_path.iterdir()] == [True]


def test_remove_deletes_work_folder_and_staged_upload_only(tmp_path):
    outside = tmp_path / "Interviews" / "interview.mp3"
    outside.parent.mkdir()
    outside.write_text("audio")
    store = JobStore(tmp_path / "queue", tmp_path / "transcriptions")
    staged = store.uploads_root / "a" / "upload.mp3"
    staged.parent.mkdir(parents=True)
    staged.write_text("audio")
    store.add([make_spec(id="a", source=staged), make_spec(id="b", source=outside)])
    pending = [store.work_dir(job_id) for job_id in "ab"]

    store.remove("a")
    store.remove("b")

    assert store.jobs() == []
    assert not staged.parent.exists()
    assert all(not path.parent.exists() for path in pending)
    assert outside.exists()


def test_clear_finished_removes_only_the_given_jobs_that_are_still_finished(tmp_path):
    store = JobStore(tmp_path, tmp_path / "transcriptions")
    store.add([make_spec(id=job_id, speaker_detection=False) for job_id in "abcde"])
    for job_id in "abce":
        store.update(job_id, status=JobStatus.RUNNING)
    store.update("a", status=JobStatus.DONE)
    store.update("b", status=JobStatus.FAILED)
    store.update("e", status=JobStatus.FAILED)  # finished after the list was shown

    store.clear_finished(["a", "b", "c", "d", "gone"])  # c is running again, d queued

    assert ids(store) == ["c", "d", "e"]


@pytest.mark.parametrize("operation", ["update", "remove"])
def test_failed_save_preserves_memory_disk_and_files(tmp_path, monkeypatch, operation):
    store = JobStore(tmp_path / "queue", tmp_path / "transcriptions")
    store.add([make_spec(id="a"), make_spec(id="b")])
    store.update("a", status=JobStatus.CANCELLED)
    upload = store.work_dir("a") / "input" / "audio.mp3"
    upload.parent.mkdir(parents=True)
    upload.write_bytes(b"audio")
    checkpoint = store.work_dir("a") / "checkpoint.json"
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    checkpoint.write_text("checkpoint")
    state = store.get("a")[1]
    before = [(spec.to_json(), state.to_json()) for spec, state in store.jobs()]
    saved = store.path.read_bytes()

    def disk_full(*args):
        raise OSError("disk full")

    monkeypatch.setattr(jobs.os, "replace", disk_full)
    actions = {
        "update": lambda: store.update("a", status=JobStatus.QUEUED, error="changed"),
        "remove": lambda: store.remove("a"),
    }
    with pytest.raises(OSError, match="disk full"):
        actions[operation]()

    assert [(spec.to_json(), state.to_json()) for spec, state in store.jobs()] == before
    assert store.get("a")[1] is state
    assert store.path.read_bytes() == saved
    assert upload.read_bytes() == b"audio"
    assert checkpoint.read_text() == "checkpoint"
