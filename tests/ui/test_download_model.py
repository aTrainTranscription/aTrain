"""Tests for aTrain/utils/models.py::download_model - what a failed download may delete (#334).

No page and no download is involved, but the module imports nicegui, so these
live in tests/ui. remove_model is faked because its default directory is the
real models folder.
"""

import shutil
from concurrent.futures.process import BrokenProcessPool

import pytest
from aTrain.utils import models
from nicegui import run, ui
from nicegui.run import SubprocessException


@pytest.fixture
def models_dir(tmp_path, monkeypatch):
    """Point MODELS_DIR at tmp_path and stub what download_model() touches besides
    the folder: the dialogs, the worker pool, the page reload and remove_model."""
    monkeypatch.setattr(models, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(
        models,
        "remove_model",
        lambda model, *_: shutil.rmtree(tmp_path / model, ignore_errors=True),
    )
    for name in ("dialog_download", "close_dialog_download", "dialog_error", "setup_process_pool"):
        monkeypatch.setattr(models, name, lambda *args, **kwargs: None)
    monkeypatch.setattr(ui.navigate, "reload", lambda: None)
    return tmp_path


def _online():
    pass


def _offline():
    raise ConnectionError("We cannot reach Hugging Face")


async def _stopped(func, *args, **kwargs):
    raise BrokenProcessPool()  # the dialog's "stop" button tears the pool down


async def _failed(func, *args, **kwargs):
    raise SubprocessException(OSError, "connection reset", "")


@pytest.mark.parametrize(
    ("check_internet", "cpu_bound"),
    [
        pytest.param(_offline, _failed, id="offline"),  # fails before the worker runs
        pytest.param(_online, _stopped, id="stop"),
        pytest.param(_online, _failed, id="error"),
    ],
)
async def test_failed_download_keeps_a_folder_that_was_there_before(
    models_dir, monkeypatch, check_internet, cpu_bound
):
    weights = models_dir / "speaker-detection" / "embedding" / "pytorch_model.bin"
    weights.parent.mkdir(parents=True)
    weights.touch()
    monkeypatch.setattr(models, "check_internet", check_internet)
    monkeypatch.setattr(run, "cpu_bound", cpu_bound)

    await models.download_model("speaker-detection")

    assert weights.is_file(), "the failed download deleted the existing folder"


@pytest.mark.parametrize(
    "failure", [pytest.param(_stopped, id="stop"), pytest.param(_failed, id="error")]
)
async def test_failed_download_removes_the_folder_it_created(models_dir, monkeypatch, failure):
    async def partial_download(func, *args, model, **kwargs):
        (models_dir / model).mkdir()
        (models_dir / model / "model.bin").touch()
        await failure(func, *args, model=model, **kwargs)

    monkeypatch.setattr(models, "check_internet", _online)
    monkeypatch.setattr(run, "cpu_bound", partial_download)

    await models.download_model("large-v3-turbo")

    assert not (models_dir / "large-v3-turbo").exists(), "the failed download left its folder"
