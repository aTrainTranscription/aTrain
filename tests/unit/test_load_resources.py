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


def _certificate_error():
    """The chain requests raises when a proxy re-signs TLS with an unknown CA."""
    import ssl

    import requests
    from urllib3.exceptions import MaxRetryError
    from urllib3.exceptions import SSLError as Urllib3SSLError

    reason = Urllib3SSLError(ssl.SSLCertVerificationError(1, "unable to get local issuer"))
    return requests.exceptions.SSLError(MaxRetryError(None, "/api/models/x", reason))


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
