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


def _certificate_error():
    """The shape of the chain requests raises when a proxy re-signs TLS.

    requests.SSLError has MaxRetryError as its context, whose `reason` is a
    urllib3 SSLError that holds the ssl error in `args` instead of chaining
    it. Built from stdlib exceptions, since the unit job installs neither
    requests nor urllib3.
    """
    import ssl

    urllib3_error = OSError(ssl.SSLCertVerificationError(1, "unable to get local issuer"))
    max_retry = OSError("Max retries exceeded")
    max_retry.reason = urllib3_error
    requests_error = OSError(max_retry)
    requests_error.__context__ = max_retry
    return requests_error


def test_certificate_error_points_to_manual_install(tmp_path, monkeypatch):
    original = file_download.http_get

    def fail(**kw):
        raise _certificate_error()

    monkeypatch.setattr(load_resources, "snapshot_download", fail)

    with pytest.raises(load_resources.ModelDownloadError) as caught:
        load_resources.download_model(
            tmp_path / "large-v3-turbo", MODEL_INFO, progress={"current": 0, "total": 0}
        )

    assert "'large-v3-turbo'" in str(caught.value)
    assert load_resources.OFFLINE_INSTALL_DOCS in str(caught.value)
    assert file_download.http_get is original


def test_other_errors_are_not_reported_as_certificate_errors():
    assert not load_resources._is_certificate_error(OSError("connection lost"))
