"""Unit tests for aTrain_core.jobs.JobStore (queue.json persistence)."""

import json

import pytest
from aTrain_core import jobs
from aTrain_core.jobs import JobStatus, JobStore
from tests.unit.test_jobs import make_spec


def ids(store: JobStore) -> list[str]:
    return [spec.id for spec, _ in store.jobs()]


def test_add_and_reload(tmp_path):
    store = JobStore(tmp_path)
    store.add([make_spec(id="a"), make_spec(id="b", speaker_detection=False)])
    store.update("a", status=JobStatus.RUNNING, started_at="2026-09-30 14-06-40")

    reloaded = JobStore(tmp_path)
    assert ids(reloaded) == ["a", "b"]
    assert reloaded.get("a") == store.get("a")
    assert not (tmp_path / "queue.json.tmp").exists()


def test_add_rejects_duplicate_ids(tmp_path):
    store = JobStore(tmp_path)
    store.add([make_spec(id="a")])
    with pytest.raises(ValueError):
        store.add([make_spec(id="a")])


def test_move(tmp_path):
    store = JobStore(tmp_path)
    store.add([make_spec(id=job_id) for job_id in "abc"])
    store.move("c", -1)
    assert ids(store) == ["a", "c", "b"]
    store.move("a", -1)  # already first
    store.move("a", 5)  # clamped to the end
    assert ids(JobStore(tmp_path)) == ["c", "b", "a"]


@pytest.mark.parametrize(
    "content",
    [
        "{not json",
        json.dumps({"schema_version": 99, "jobs": []}),
        json.dumps({"schema_version": 1}),
    ],
)
def test_unreadable_queue_is_moved_aside(tmp_path, content):
    (tmp_path / "queue.json").write_text(content, encoding="utf-8")
    store = JobStore(tmp_path)
    assert store.jobs() == []
    assert [p.name.startswith("queue.json.unreadable-") for p in tmp_path.iterdir()] == [True]


def test_remove_deletes_work_folder_and_staged_upload_only(tmp_path):
    outside = tmp_path / "Interviews" / "interview.mp3"
    outside.parent.mkdir()
    outside.write_text("audio")
    store = JobStore(tmp_path / "queue")
    staged = store.uploads_root / "a" / "upload.mp3"
    staged.parent.mkdir(parents=True)
    staged.write_text("audio")
    store.add([make_spec(id="a", source=staged), make_spec(id="b", source=outside)])
    for job_id in "ab":
        store.work_dir(job_id).mkdir(parents=True)

    store.remove("a")
    store.remove("b")

    assert store.jobs() == []
    assert not staged.parent.exists() and not store.work_dir("a").exists()
    assert not store.work_dir("b").exists()
    assert outside.exists()


def test_clear_finished_keeps_active_jobs(tmp_path):
    store = JobStore(tmp_path)
    store.add([make_spec(id=job_id, speaker_detection=False) for job_id in "abcd"])
    for job_id in "abc":
        store.update(job_id, status=JobStatus.RUNNING)
    store.update("a", status=JobStatus.DONE)
    store.update("b", status=JobStatus.FAILED)

    assert store.clear_finished() == ["a", "b"]
    assert ids(store) == ["c", "d"]


def test_clear_finished_saves_once_and_deletes_work_folders(tmp_path, monkeypatch):
    store = JobStore(tmp_path)
    store.add([make_spec(id=job_id, speaker_detection=False) for job_id in "abc"])
    for job_id in "ab":
        store.update(job_id, status=JobStatus.CANCELLED)
        store.work_dir(job_id).mkdir(parents=True)
    saves = []
    monkeypatch.setattr(store, "_save", lambda jobs: saves.append([spec.id for spec, _ in jobs]))

    store.clear_finished()

    assert saves == [["c"]]
    assert not store.work_dir("a").exists() and not store.work_dir("b").exists()


def test_reload_reads_what_another_store_saved(tmp_path):
    store = JobStore(tmp_path)
    store.add([make_spec(id="a", speaker_detection=False)])
    JobStore(tmp_path).update("a", status=JobStatus.RUNNING)

    store.reload()

    assert store.get("a")[1].status == JobStatus.RUNNING


@pytest.mark.parametrize("operation", ["add", "update", "move", "remove", "clear_finished"])
def test_failed_save_preserves_memory_disk_and_files(tmp_path, monkeypatch, operation):
    store = JobStore(tmp_path / "queue")
    store.add([make_spec(id="a"), make_spec(id="b")])
    store.update("a", status=JobStatus.CANCELLED)
    upload = store.uploads_root / "a" / "audio.mp3"
    upload.parent.mkdir(parents=True)
    upload.write_bytes(b"audio")
    checkpoint = store.work_dir("a") / "checkpoint.json"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_text("checkpoint")
    state = store.get("a")[1]
    before = [(spec.to_json(), state.to_json()) for spec, state in store.jobs()]
    saved = store.path.read_bytes()

    def disk_full(*args):
        raise OSError("disk full")

    monkeypatch.setattr(jobs.os, "replace", disk_full)
    actions = {
        "add": lambda: store.add([make_spec(id="c")]),
        "update": lambda: store.update("a", status=JobStatus.QUEUED, error="changed"),
        "move": lambda: store.move("a", 1),
        "remove": lambda: store.remove("a"),
        "clear_finished": store.clear_finished,
    }
    with pytest.raises(OSError, match="disk full"):
        actions[operation]()

    assert [(spec.to_json(), state.to_json()) for spec, state in store.jobs()] == before
    assert store.get("a")[1] is state
    assert store.path.read_bytes() == saved
    assert upload.read_bytes() == b"audio"
    assert checkpoint.read_text() == "checkpoint"
