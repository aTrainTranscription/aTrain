"""Stop button and cancellation handling.

`nicegui.run.tear_down` (what the stop buttons used to call) shuts down the
thread pool as well, and NiceGUI only rebuilds the process pool. `tear_down`
is a no-op under pytest, so a stand-in with the real pool behaviour is used.
"""

import asyncio

import pytest
from aTrain.utils import models, transcription
from aTrain.utils.stop import stop_run
from nicegui import run


@pytest.fixture
def thread_pool():
    original = run.thread_pool
    yield
    run.thread_pool.shutdown(wait=False)
    run.thread_pool = original


async def test_io_bound_works_after_stop(monkeypatch, thread_pool):
    monkeypatch.setattr(run, "tear_down", lambda: run.thread_pool.shutdown(wait=False))
    stop_run()
    assert await run.io_bound(lambda: "ok") == "ok"


async def test_pipeline_cancel_cleans_up_and_propagates(monkeypatch):
    import aTrain_core.transcribe as core_transcribe

    calls = []

    async def cancelled(*args, **kwargs):
        raise asyncio.CancelledError

    async def materialise(self, directory, filename):
        return directory / filename

    monkeypatch.setattr(run, "cpu_bound", cancelled)
    monkeypatch.setattr(transcription, "dialog_process", lambda progress: None)
    monkeypatch.setattr(transcription, "check_inputs_transcribe", lambda *a: None)
    monkeypatch.setattr(transcription, "close_dialog_process", lambda: calls.append("close"))
    monkeypatch.setattr(transcription, "delete_transcription", lambda fid: calls.append(fid))
    monkeypatch.setattr(transcription, "Settings", lambda **kw: None)
    monkeypatch.setattr(transcription.UploadPayload, "materialise", materialise)
    monkeypatch.setattr(
        core_transcribe, "prepare_transcription", lambda path: (path, "file-id", "ts")
    )
    monkeypatch.setattr(transcription, "ComputeType", lambda value: value)

    with pytest.raises(asyncio.CancelledError):
        await transcription.run_pipeline(transcription.UploadPayload(name="a.wav"))
    assert calls == ["file-id", "close"]


async def test_download_cancel_cleans_up_and_propagates(monkeypatch):
    calls = []

    async def cancelled(*args, **kwargs):
        raise asyncio.CancelledError

    monkeypatch.setattr(run, "cpu_bound", cancelled)
    monkeypatch.setattr(models, "dialog_download", lambda progress, model: None)
    monkeypatch.setattr(models, "check_internet", lambda: None)
    monkeypatch.setattr(models, "close_dialog_download", lambda: calls.append("close"))
    monkeypatch.setattr(models, "remove_model", lambda m: calls.append(m))

    with pytest.raises(asyncio.CancelledError):
        await models.download_model("tiny")
    assert calls == ["tiny", "close"]


def test_stop_buttons_use_stop_run():
    from aTrain.components.dialogs import download, process

    assert process.stop_run is stop_run
    assert download.stop_run is stop_run
