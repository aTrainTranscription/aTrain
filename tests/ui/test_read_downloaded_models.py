"""Tests for aTrain/utils/models.py::read_downloaded_models.

Pure filesystem-scanning behaviour — no NiceGUI page involved, but the
module imports nicegui, so these live with the app-runtime suite rather
than tests/unit. The search dirs are rebound on the models module (which
imports them into its own namespace via `from aTrain_core.globals import`).
"""

from aTrain.utils import models


def _make_model_dir(root, name):
    model_dir = root / name
    model_dir.mkdir(parents=True)
    (model_dir / "model.bin").touch()


def test_finds_model_with_bin_file(tmp_path, monkeypatch):
    _make_model_dir(tmp_path / "models", "large-v3-turbo")
    monkeypatch.setattr(models, "MODELS_DIR", tmp_path / "models")
    monkeypatch.setattr(models, "REQUIRED_MODELS_DIR", tmp_path / "required")
    assert models.read_downloaded_models() == ["large-v3-turbo"]


def test_no_duplicates_when_dirs_coincide(tmp_path, monkeypatch):
    # REQUIRED_MODELS_DIR falls back to MODELS_DIR when no models are
    # bundled with the package; the same dir must not be scanned twice.
    _make_model_dir(tmp_path / "models", "large-v3-turbo")
    monkeypatch.setattr(models, "MODELS_DIR", tmp_path / "models")
    monkeypatch.setattr(models, "REQUIRED_MODELS_DIR", tmp_path / "models")
    assert models.read_downloaded_models() == ["large-v3-turbo"]
