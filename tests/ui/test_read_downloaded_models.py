"""Tests for aTrain/utils/models.py::read_downloaded_models and read_transcription_models.

Pure filesystem-scanning behaviour — no NiceGUI page involved, but the
module imports nicegui, so these live with the app-runtime suite rather
than tests/unit. The search dirs are rebound on the models module (which
imports them into its own namespace via `from aTrain_core.globals import`).
"""

from aTrain.utils import models
from aTrain_core.load_resources import load_model_config_file


def _make_model_dir(root, name, skip=()):
    """Create every file the model's manifest in models.json lists, except `skip`."""
    for file in load_model_config_file()[name]["files"]:
        if file not in skip:
            path = root / name / file
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()


def test_finds_complete_model(tmp_path, monkeypatch):
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


def test_finds_model_with_files_in_subfolders(tmp_path, monkeypatch):
    # speaker-detection keeps its weights in embedding/ and segmentation/ (#334).
    _make_model_dir(tmp_path / "models", "speaker-detection")
    monkeypatch.setattr(models, "MODELS_DIR", tmp_path / "models")
    monkeypatch.setattr(models, "REQUIRED_MODELS_DIR", tmp_path / "required")
    assert models.read_downloaded_models() == ["speaker-detection"]


def test_skips_model_with_a_missing_file(tmp_path, monkeypatch):
    # A browser download drops the dot of .gitattributes; get_model() would then
    # try to download the model, so the page must not list it as downloaded.
    _make_model_dir(tmp_path / "models", "large-v3-turbo", skip=(".gitattributes",))
    monkeypatch.setattr(models, "MODELS_DIR", tmp_path / "models")
    monkeypatch.setattr(models, "REQUIRED_MODELS_DIR", tmp_path / "required")
    assert models.read_downloaded_models() == []


def test_speaker_detection_is_listed_but_not_offered_for_transcription(tmp_path, monkeypatch):
    for name in ("large-v3-turbo", "speaker-detection"):
        _make_model_dir(tmp_path / "models", name)
    monkeypatch.setattr(models, "MODELS_DIR", tmp_path / "models")
    monkeypatch.setattr(models, "REQUIRED_MODELS_DIR", tmp_path / "required")
    assert sorted(models.read_downloaded_models()) == ["large-v3-turbo", "speaker-detection"]
    assert models.read_transcription_models() == ["large-v3-turbo"]
