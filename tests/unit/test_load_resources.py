"""Unit tests for aTrain_core/load_resources.py.

`download_model` patches huggingface_hub's `http_get` so the byte progress of a
download lands in the caller's progress dict. The patch used to stay in place
for the life of the worker process; the next download in that worker, without
a progress dict, then wrote to a proxy that was already gone. These tests pin
the module attribute being restored, with `snapshot_download` stubbed out.
"""

import inspect
from unittest.mock import create_autospec

import pytest
from aTrain_core import load_resources
from huggingface_hub import file_download

MODEL_INFO = {"repo_id": "aTrain-core/test", "revision": "abc", "repo_size": 10}


@pytest.fixture
def stub_download(monkeypatch):
    calls = []
    # Keep the installed Hub's signature: a **kwargs-only stub hides removed
    # arguments such as local_dir_use_symlinks when upgrading the dependency.
    download = create_autospec(
        load_resources.snapshot_download, side_effect=lambda **kw: calls.append(kw)
    )
    monkeypatch.setattr(load_resources, "snapshot_download", download)
    return calls


def test_http_get_is_restored_after_a_download_with_progress(tmp_path, stub_download):
    original = file_download.http_get
    original_xet = file_download.xet_get
    progress = {"current": 0, "total": 999999}

    load_resources.download_model(tmp_path, MODEL_INFO, progress=progress)

    assert file_download.http_get is original
    assert file_download.xet_get is original_xet
    assert progress["total"] == 10
    assert stub_download[0]["local_dir"] == tmp_path


def test_http_get_is_restored_when_the_download_fails(tmp_path, monkeypatch):
    original = file_download.http_get
    original_xet = file_download.xet_get

    def boom(**kw):
        raise OSError("connection lost")

    monkeypatch.setattr(load_resources, "snapshot_download", boom)

    with pytest.raises(OSError):
        load_resources.download_model(
            tmp_path, MODEL_INFO, progress={"current": 0, "total": 999999}
        )

    assert file_download.http_get is original
    assert file_download.xet_get is original_xet


def test_http_get_is_untouched_without_progress(tmp_path, stub_download):
    original = file_download.http_get
    original_xet = file_download.xet_get

    load_resources.download_model(tmp_path, MODEL_INFO)

    assert file_download.http_get is original
    assert file_download.xet_get is original_xet


@pytest.mark.parametrize("name", ["http_get", "xet_get"])
def test_hub_download_functions_accept_the_progress_bar(name):
    # download_model passes `_tqdm_bar` to both; a Hub upgrade that drops it
    # would only fail at download time.
    assert "_tqdm_bar" in inspect.signature(getattr(file_download, name)).parameters
