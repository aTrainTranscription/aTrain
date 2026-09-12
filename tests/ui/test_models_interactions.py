"""Interaction tests for the /models page.

Drives the Download / Delete buttons on the models page through the
NiceGUI in-process `user` fixture, asserting the page calls the right
backend function with the right argument. The page reads from
`read_model_metadata` and clicks invoke `download_model` /
`remove_model`; all three are monkeypatched so the test doesn't hit
HuggingFace, doesn't spawn a CPU-bound worker for an actual download,
and doesn't depend on which models are present on the host.
"""

import pytest
from aTrain.utils import models as models_utils
from nicegui import ui
from nicegui.testing import User


def _fake_metadata():
    """A predictable mix: one downloaded model (large-v1) and one not
    downloaded (tiny). Both are outside REQUIRED_MODELS so the page
    actually renders them as rows."""
    return [
        {"model": "tiny", "size": "75 MB", "downloaded": False},
        {"model": "large-v1", "size": "3 GB", "downloaded": True},
    ]


@pytest.fixture
def mocked_models(monkeypatch):
    """Pin the models the page sees, and record any download/remove calls.

    Patched on the persistent utils module: the page module is re-imported
    fresh per test by tests/ui/main.py and copies these names at import
    time, so this fixture must be listed before `user` in test signatures."""
    download_calls = []
    remove_calls = []

    def _record_download(model):
        # The real download_model is async, but the on_click handler returns
        # whatever the lambda returns and NiceGUI awaits coroutines for us
        # on the live server. In the user fixture the await chain isn't
        # synchronously driven, so we record via a synchronous stub.
        download_calls.append(model)

    def _record_remove(model):
        remove_calls.append(model)

    monkeypatch.setattr(models_utils, "read_model_metadata", _fake_metadata)
    monkeypatch.setattr(models_utils, "download_model", _record_download)
    monkeypatch.setattr(models_utils, "remove_model", _record_remove)
    return download_calls, remove_calls


async def test_models_page_lists_non_required_models(mocked_models, user: User):
    await user.open("/models")
    await user.should_see("Model Manager", retries=100)
    await user.should_see("tiny")
    await user.should_see("large-v1")
    await user.should_see("75 MB")
    await user.should_see("3 GB")


async def test_download_button_invokes_download_model(mocked_models, user: User):
    download_calls, _ = mocked_models
    await user.open("/models")
    await user.should_see("Model Manager", retries=100)
    # Exactly one row is not-downloaded → exactly one "Download" button.
    # kind= keeps the header label "Download Size" out of the match set:
    # nicegui>=3 clicks only the lowest-id match instead of all matches,
    # and a positional string target would ignore `kind` entirely.
    user.find(kind=ui.button, content="Download").click()
    assert download_calls == ["tiny"]


async def test_delete_button_invokes_remove_model(mocked_models, user: User):
    _, remove_calls = mocked_models
    await user.open("/models")
    await user.should_see("Model Manager", retries=100)
    # Exactly one row is downloaded → exactly one "Delete" button.
    user.find("Delete").click()
    assert remove_calls == ["large-v1"]


@pytest.fixture
def model_dirs(monkeypatch, tmp_path):
    """Switch the page between a bundled and a slim build.

    Patched on aTrain_core.globals only: the page calls `is_packaged_model`,
    which resolves the dirs at call time from that module's namespace. The
    constants themselves would need patching once per importing module.
    """
    import aTrain_core.globals as core_globals

    def _set(packaged: bool):
        models = tmp_path / "models"
        models.mkdir(exist_ok=True)
        required = tmp_path / "packaged" if packaged else models
        if packaged:
            (required / "large-v3-turbo").mkdir(parents=True)
        monkeypatch.setattr(core_globals, "MODELS_DIR", models)
        monkeypatch.setattr(core_globals, "REQUIRED_MODELS_DIR", required)
        return core_globals

    return _set


def _metadata_with_turbo():
    return [
        {"model": "large-v3-turbo", "size": "1.6 GB", "downloaded": False},
        {"model": "tiny", "size": "75 MB", "downloaded": False},
    ]


@pytest.fixture
def turbo_metadata(monkeypatch):
    """Pin the model list the page sees.

    A fixture, not an in-test patch: the page binds `read_model_metadata` at
    import time and tests/ui/main.py re-imports it inside the `user` fixture,
    so patching from the test body lands too late. `model_dirs` can patch from
    the body because `is_packaged_model` resolves the dirs on every call.
    """
    monkeypatch.setattr(models_utils, "read_model_metadata", _metadata_with_turbo)


async def test_bundled_model_is_not_offered_for_download(model_dirs, turbo_metadata, user: User):
    """A model shipped inside the read-only install dir cannot be managed."""
    core_globals = model_dirs(packaged=True)
    assert core_globals.packaged_models_dir() is not None  # precondition

    await user.open("/models")
    await user.should_see("Model Manager", retries=100)
    await user.should_see("tiny")
    await user.should_not_see("large-v3-turbo")


async def test_slim_build_offers_the_default_model(model_dirs, turbo_metadata, user: User):
    """Regression: large-v3-turbo is in REQUIRED_MODELS but slim builds do not
    ship it, and the transcribe page lists only downloaded models - so hiding it
    here left the default model unreachable through the UI entirely."""
    core_globals = model_dirs(packaged=False)
    assert core_globals.packaged_models_dir() is None  # precondition

    await user.open("/models")
    await user.should_see("Model Manager", retries=100)
    await user.should_see("large-v3-turbo")
    await user.should_see("1.6 GB")
