"""Unit tests for aTrain_core.globals' REQUIRED_MODELS_DIR resolution.

The constant is computed at import time, so each test re-executes the module
body via importlib.reload with `files("aTrain")` pointed at an isolated temp
dir. Torch- and NiceGUI-free, so they run in the lightweight `unit` CI job.
"""

import importlib
import importlib.resources
from pathlib import Path

import aTrain_core.globals
import pytest


@pytest.fixture
def reload_globals(monkeypatch, tmp_path):
    """Return a function that reloads aTrain_core.globals with `files("aTrain")`
    resolving to the given path. FLATPAK_ID is cleared and ATRAIN_USER_DIR is
    redirected so the reload never touches the real user environment. The
    pristine module is restored on teardown."""

    def _reload(packaged_dir: Path):
        real_files = importlib.resources.files

        def fake_files(package):
            return packaged_dir if package == "aTrain" else real_files(package)

        monkeypatch.delenv("FLATPAK_ID", raising=False)
        monkeypatch.setenv("ATRAIN_USER_DIR", str(tmp_path / "user"))
        monkeypatch.setattr(importlib.resources, "files", fake_files)
        return importlib.reload(aTrain_core.globals)

    yield _reload
    monkeypatch.undo()
    importlib.reload(aTrain_core.globals)


def test_required_models_dir_uses_packaged_dir_when_it_exists(reload_globals, tmp_path):
    packaged = tmp_path / "aTrain" / "required_models"
    packaged.mkdir(parents=True)
    module = reload_globals(tmp_path / "aTrain")
    assert packaged == module.REQUIRED_MODELS_DIR


def test_required_models_dir_falls_back_to_models_dir_when_missing(reload_globals, tmp_path):
    # No required_models dir inside the package location — e.g. an MSIX
    # without pre-populated models, where the install path is read-only and
    # must never be written to.
    module = reload_globals(tmp_path / "aTrain")
    assert module.REQUIRED_MODELS_DIR == module.MODELS_DIR


@pytest.fixture
def dirs(monkeypatch, tmp_path):
    """Point the two model dirs at temp paths.

    `packaged_models_dir` / `is_packaged_model` read these at call time from
    aTrain_core.globals' own namespace, so patching them here reaches every
    caller - unlike the constants themselves, which each consumer rebinds into
    its own namespace via `from aTrain_core.globals import ...` and which
    therefore have to be patched once per importing module.
    """

    def _set(packaged: Path | None):
        models = tmp_path / "models"
        models.mkdir(exist_ok=True)
        monkeypatch.setattr(aTrain_core.globals, "MODELS_DIR", models)
        # A build that bundles nothing collapses the two onto each other; that
        # is what globals.py's fallback does.
        monkeypatch.setattr(
            aTrain_core.globals, "REQUIRED_MODELS_DIR", packaged if packaged else models
        )
        return models

    return _set


def test_packaged_dir_is_none_when_nothing_is_bundled(dirs):
    dirs(packaged=None)
    assert aTrain_core.globals.packaged_models_dir() is None


def test_bundled_model_is_reported_as_packaged(dirs, tmp_path):
    packaged = tmp_path / "packaged"
    (packaged / "large-v3-turbo").mkdir(parents=True)
    dirs(packaged=packaged)

    assert aTrain_core.globals.packaged_models_dir() == packaged  # precondition
    assert aTrain_core.globals.is_packaged_model("large-v3-turbo")
    # Named in REQUIRED_MODELS but absent from the bundle - membership alone
    # must not make it packaged.
    assert not aTrain_core.globals.is_packaged_model("speaker-detection")


def test_slim_build_reports_nothing_as_packaged(dirs):
    models = dirs(packaged=None)
    (models / "large-v3-turbo").mkdir()

    assert aTrain_core.globals.packaged_models_dir() is None  # precondition
    # Regression guard: with the two dirs collapsed, a *downloaded* model sits
    # in REQUIRED_MODELS_DIR too. Testing existence there without comparing the
    # dirs would call it packaged and hide it from the model manager again.
    assert not aTrain_core.globals.is_packaged_model("large-v3-turbo")
