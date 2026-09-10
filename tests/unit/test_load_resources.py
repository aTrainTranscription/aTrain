"""Unit tests for aTrain_core/load_resources.py.

`download_model` patches huggingface_hub's `http_get` so the byte progress of a
download lands in the caller's progress dict. The patch used to stay in place
for the life of the worker process; the next download in that worker, without
a progress dict, then wrote to a proxy that was already gone. These tests pin
the module attribute being restored, with `snapshot_download` stubbed out.
"""

import pytest
from aTrain_core import load_resources
from huggingface_hub import file_download

MODEL_INFO = {"repo_id": "aTrain-core/test", "revision": "abc", "repo_size": 10}


@pytest.fixture
def stub_download(monkeypatch):
    calls = []
    monkeypatch.setattr(load_resources, "snapshot_download", lambda **kw: calls.append(kw))
    return calls


def test_http_get_is_restored_after_a_download_with_progress(tmp_path, stub_download):
    original = file_download.http_get
    progress = {"current": 0, "total": 999999}

    load_resources.download_model(tmp_path, MODEL_INFO, progress=progress)

    assert file_download.http_get is original
    assert progress["total"] == 10
    assert stub_download[0]["local_dir"] == tmp_path


def test_http_get_is_restored_when_the_download_fails(tmp_path, monkeypatch):
    original = file_download.http_get

    def boom(**kw):
        raise OSError("connection lost")

    monkeypatch.setattr(load_resources, "snapshot_download", boom)

    with pytest.raises(OSError):
        load_resources.download_model(
            tmp_path, MODEL_INFO, progress={"current": 0, "total": 999999}
        )

    assert file_download.http_get is original


def test_http_get_is_untouched_without_progress(tmp_path, stub_download):
    original = file_download.http_get

    load_resources.download_model(tmp_path, MODEL_INFO)

    assert file_download.http_get is original
