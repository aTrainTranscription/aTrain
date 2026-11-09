"""Tests for aTrain/utils/models.py::read_model_metadata.

Lives with the app-runtime suite because the module imports nicegui.
"""

from aTrain.utils import models


def _config():
    return {
        "tiny": {
            "repo_id": "aTrain-core/faster-whisper-tiny",
            "revision": "67ab6c7e",
            "repo_size_human": "78.21 MB",
        }
    }


def test_metadata_names_hugging_face_as_source(monkeypatch):
    monkeypatch.setattr(models, "load_model_config_file", _config)
    monkeypatch.setattr(models, "read_downloaded_models", lambda: [])
    (tiny,) = models.read_model_metadata()
    assert tiny["source"] == "Hugging Face"
    assert (
        tiny["source_url"] == "https://huggingface.co/aTrain-core/faster-whisper-tiny/tree/67ab6c7e"
    )


def test_every_registered_model_has_a_source_url(monkeypatch):
    # Skip the disk scan: it would create the real models dir.
    monkeypatch.setattr(models, "read_downloaded_models", lambda: [])
    for model in models.read_model_metadata():
        assert model["source_url"].startswith("https://huggingface.co/"), model["model"]
