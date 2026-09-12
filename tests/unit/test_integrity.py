"""Unit tests for aTrain_core/integrity.py and the pinned manifest.

Network-free and dependency-light: `integrity` imports nothing beyond hashlib
and pathlib, so these run in the lightweight `unit` CI job. Fixtures are built
on the fly with hashes computed the same way the Hub reports them.
"""

import hashlib
import json
import re
from importlib.resources import files

import pytest
from aTrain_core.integrity import find_missing_files, verify_model

MANIFEST_ENTRY = re.compile(r"^sha256:[0-9a-f]{64}$")


def sha256_of(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


@pytest.fixture
def model_dir(tmp_path):
    """A model directory that matches its manifest, plus the noise a real
    download leaves behind: huggingface_hub's `.cache` bookkeeping."""
    path = tmp_path / "some-model"
    path.mkdir()
    weights, config = b"pretend weights" * 100, b'{"model": "test"}'
    (path / "model.bin").write_bytes(weights)
    (path / "config.json").write_bytes(config)
    cache = path / ".cache" / "huggingface" / "download"
    cache.mkdir(parents=True)
    (cache / "model.bin.metadata").write_text("revision\nhash\n1780998538.69")
    manifest = {"model.bin": sha256_of(weights), "config.json": sha256_of(config)}
    return path, manifest


def test_matching_model_has_no_problems(model_dir):
    path, manifest = model_dir
    assert verify_model(path, manifest) == []


def test_cache_directory_is_ignored(model_dir):
    # Hashing the directory as a whole is what broke the earlier attempt: the
    # .cache metadata differs between downloads. Manifest-driven checks skip it.
    path, manifest = model_dir
    (path / ".cache" / "huggingface" / "download" / "model.bin.metadata").write_text("changed")
    (path / "unexpected-extra-file.txt").write_bytes(b"not in the manifest")
    assert verify_model(path, manifest) == []


def test_modified_file_is_reported(model_dir):
    path, manifest = model_dir
    (path / "config.json").write_bytes(b'{"model": "tampered"}')
    problems = verify_model(path, manifest)
    assert len(problems) == 1
    assert problems[0].startswith("config.json: expected sha256")


def test_modified_weights_are_reported(model_dir):
    path, manifest = model_dir
    (path / "model.bin").write_bytes(b"different weights")
    problems = verify_model(path, manifest)
    assert len(problems) == 1
    assert problems[0].startswith("model.bin: expected sha256")


def test_all_problems_are_reported_not_just_the_first(model_dir):
    path, manifest = model_dir
    (path / "model.bin").write_bytes(b"tampered")
    (path / "config.json").unlink()
    assert len(verify_model(path, manifest)) == 2


def test_missing_file_is_reported(model_dir):
    path, manifest = model_dir
    (path / "config.json").unlink()
    assert verify_model(path, manifest) == ["config.json: missing"]


def test_unknown_algorithm_is_reported_not_raised(model_dir):
    path, manifest = model_dir
    manifest["config.json"] = "md5:abc"
    assert any("unsupported hash algorithm" in problem for problem in verify_model(path, manifest))


def test_find_missing_files_is_empty_for_a_complete_model(model_dir):
    path, manifest = model_dir
    assert find_missing_files(path, manifest) == []


def test_find_missing_files_lists_interrupted_downloads(model_dir):
    # huggingface_hub moves files into place only once complete, so an aborted
    # download shows up as missing files rather than truncated ones.
    path, manifest = model_dir
    (path / "model.bin").unlink()
    assert find_missing_files(path, manifest) == ["model.bin"]


def test_find_missing_files_does_not_hash(model_dir):
    path, manifest = model_dir
    (path / "model.bin").write_bytes(b"wrong content, right name")
    assert find_missing_files(path, manifest) == []


# --- the manifest itself -------------------------------------------------


def models_config() -> dict:
    return json.loads(files("aTrain_core.data").joinpath("models.json").read_text())


def test_every_model_pins_file_hashes():
    """Fails in the PR that adds a model without running the refresh script,
    rather than at runtime on a user's machine."""
    without = [name for name, model in models_config().items() if not model.get("files")]
    assert without == [], f"models without pinned hashes: {', '.join(without)}"


@pytest.mark.parametrize("name", list(models_config()))
def test_manifest_entries_are_well_formed(name):
    for filename, entry in models_config()[name]["files"].items():
        assert MANIFEST_ENTRY.match(entry), f"{name}/{filename}: malformed entry {entry!r}"


# --- get_model discards what fails verification --------------------------


def test_failed_verification_removes_the_model(tmp_path, monkeypatch):
    """Without this, the files would stay on disk, pass the missing-file check
    on the next call and be used without ever being verified again."""
    import aTrain_core.load_resources as load_resources

    model_dir = tmp_path / "tiny"

    def fake_download(model_path, model_info, progress=None):
        model_path.mkdir(parents=True)
        (model_path / "model.bin").write_bytes(b"not what was pinned")

    monkeypatch.setattr(load_resources, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(load_resources, "download_model", fake_download)
    monkeypatch.setattr(
        load_resources,
        "load_model_config_file",
        lambda: {
            "tiny": {"repo_id": "x", "revision": "y", "files": {"model.bin": sha256_of(b"pinned")}}
        },
    )

    with pytest.raises(load_resources.ModelIntegrityError):
        load_resources.get_model("tiny")
    assert not model_dir.exists()
