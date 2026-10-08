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


def _make_qwen_model(root, name):
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    for filename in models.load_model_config_file()[name]["files"]:
        (directory / filename).touch()
    return directory


def test_qwen_selection_requires_complete_asr_and_shared_aligner(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(models, "REQUIRED_MODELS_DIR", tmp_path)
    name = "qwen3-asr-0.6b"
    asr = _make_qwen_model(tmp_path, name)
    assert models.read_transcription_models() == []
    metadata = next(m for m in models.read_model_metadata() if m["model"] == name)
    assert metadata["downloaded"] and metadata["dependencies_missing"]

    aligner = _make_qwen_model(tmp_path, "qwen3-forced-aligner-0.6b")
    assert models.read_transcription_models() == [name]
    assert len(models.read_downloaded_models()) == 2
    assert next(m for m in models.read_model_metadata() if m["model"] == name)["size"] == "3.42 GB"

    (asr / "processor_config.json").unlink()
    assert models.read_transcription_models() == []
    (asr / "processor_config.json").touch()
    (aligner / "model.safetensors").unlink()
    assert models.read_transcription_models() == []


async def test_qwen_is_selectable_with_only_supported_timestamp_languages(
    tmp_path, monkeypatch, user
):
    from nicegui import app

    monkeypatch.setattr(models, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(models, "REQUIRED_MODELS_DIR", tmp_path)
    for name in ["qwen3-asr-0.6b", "qwen3-asr-1.7b", "qwen3-forced-aligner-0.6b"]:
        _make_qwen_model(tmp_path, name)
    await user.open("/")
    await user.should_see("Select Model", retries=100)
    model_select = next(iter(user.find(marker="select_model").elements))
    model_select.set_value("qwen3-asr-0.6b")
    assert app.storage.general["model"] == "qwen3-asr-0.6b"
    language_select = next(iter(user.find(marker="select_language").elements))
    assert len(language_select.options) == 12  # automatic detection plus 11 languages
    assert "en" in language_select.options and "ja" in language_select.options
    assert "ar" not in language_select.options
    assert "qwen3-forced-aligner-0.6b" not in model_select.options
    model_select.set_value("qwen3-asr-1.7b")
    assert app.storage.general["model"] == "qwen3-asr-1.7b"


async def test_models_page_downloads_qwen_with_timestamp_bundle(tmp_path, monkeypatch, user):
    monkeypatch.setattr(models, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(models, "REQUIRED_MODELS_DIR", tmp_path)
    # The page copies this callable during the user fixture's fresh import.
    import aTrain.pages.models as page

    calls = []
    monkeypatch.setattr(page, "download_model", calls.append)
    await user.open("/models")
    await user.should_see("Qwen3-ASR 0.6B", retries=100)
    await user.should_see("Qwen3-ASR 1.7B")
    await user.should_see("3.42 GB")
    await user.should_see("5.93 GB")
    user.find(marker="download_model_qwen3-asr-0.6b").click()
    assert calls == ["qwen3-asr-0.6b"]


async def test_asr_can_be_repaired_or_deleted_after_removing_aligner(tmp_path, monkeypatch, user):
    import aTrain.pages.models as page
    from nicegui import ui

    monkeypatch.setattr(models, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(models, "REQUIRED_MODELS_DIR", tmp_path)
    _make_qwen_model(tmp_path, "qwen3-asr-0.6b")
    downloads, removals = [], []
    monkeypatch.setattr(page, "download_model", downloads.append)
    monkeypatch.setattr(page, "remove_model", removals.append)
    await user.open("/models")
    await user.should_see("Qwen3-ASR 0.6B", retries=100)
    user.find(marker="download_model_qwen3-asr-0.6b").click()
    assert downloads == ["qwen3-asr-0.6b"]
    user.find(kind=ui.button, content="Delete").click()
    assert removals == ["qwen3-asr-0.6b"]
