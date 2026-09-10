import json
import os
import shutil
from functools import partial
from importlib.resources import files
from multiprocessing.managers import DictProxy
from pathlib import Path

from huggingface_hub import file_download, snapshot_download
from tqdm.auto import tqdm

from aTrain_core.globals import MODELS_DIR, REQUIRED_MODELS, REQUIRED_MODELS_DIR
from aTrain_core.integrity import ModelIntegrityError, find_missing_files, verify_model


class custom_tqdm(tqdm):
    def __init__(self, progress: DictProxy, total: float, *args, **kwargs):
        self.progress = progress
        super().__init__(total=total, *args, **kwargs)

    def update(self, n=1):
        current = self.n + n
        self.progress["current"] = current
        super().update(n)


def download_all_models():
    """Downloads all models defined in the model configuration file."""
    models_config = load_model_config_file()
    for model in models_config:
        get_model(model)


def download_model(model_path: Path, model_info: dict, progress: DictProxy | None = None):
    # http_get is patched module-wide so the byte progress of every file lands
    # in one bar. It has to be restored afterwards: the pool worker outlives this
    # call, and the proxy behind the bar dies with the dialog that opened it.
    original_http_get = file_download.http_get
    if progress:
        repo_size = model_info["repo_size"]
        progress["total"] = repo_size
        tqdm_bar = custom_tqdm(total=repo_size, progress=progress)
        file_download.http_get = partial(original_http_get, _tqdm_bar=tqdm_bar)  # ty: ignore

    try:
        snapshot_download(
            repo_id=model_info["repo_id"],
            revision=model_info["revision"],
            local_dir=model_path,
            local_dir_use_symlinks=False,
            max_workers=1,
        )
    finally:
        file_download.http_get = original_http_get


def get_model(model: str, progress: DictProxy | None = None) -> Path:
    """Loads a specific model, downloading and verifying it if necessary."""
    models_config = load_model_config_file()
    model_info = models_config[model]
    models_dir = REQUIRED_MODELS_DIR if model in REQUIRED_MODELS else MODELS_DIR
    model_path = models_dir / model

    manifest = model_info.get("files")
    if not manifest:
        raise ModelIntegrityError(
            f"No checksums are pinned for model '{model}', so it cannot be verified. "
            "Run scripts/refresh_model_hashes.py to add them."
        )

    # A download that was interrupted leaves the directory in place with files
    # missing, and without this check it would never be completed: the previous
    # `model_path.exists()` test would consider the model present from then on.
    if not model_path.exists() or find_missing_files(model_path, manifest):
        download_model(model_path, model_info, progress)
        problems = verify_model(model_path, manifest)
        if problems:
            message = _integrity_message(model, model_path, problems)
            # Discard it here rather than leaving that to the caller: a model
            # that failed verification but stays on disk would pass the missing
            # file check from then on and be used without complaint.
            shutil.rmtree(model_path, ignore_errors=True)
            raise ModelIntegrityError(message)

    return model_path


def _integrity_message(model: str, model_path: Path, problems: list[str]) -> str:
    """Explain what to do, which differs for models that ship inside the package."""
    if not os.access(model_path, os.W_OK):
        # Models shipped inside the package sit in a read-only directory, so
        # removing and re-downloading them is not something the user can do.
        remedy = (
            f"The bundled model '{model}' does not match its checksums. "
            "Its files cannot be replaced from here - please reinstall aTrain."
        )
    else:
        remedy = (
            f"Model '{model}' does not match its checksums and will be removed. "
            "Please download it again; if this keeps happening, report it."
        )
    return remedy + "\n\n" + "\n".join(problems)


def remove_model(model: str, models_dir: Path = MODELS_DIR):
    model_path = models_dir / model
    if model_path.exists():
        shutil.rmtree(model_path)  # This deletes the directory and all its contents


def load_model_config_file() -> dict:
    """Loads the model configuration file."""
    models_config_path = str(files("aTrain_core.data").joinpath("models.json"))
    with open(models_config_path) as models_config_file:
        models_config: dict = json.load(models_config_file)
    return models_config


if __name__ == "__main__":
    ...
