import multiprocessing as mp
import os
import platform
from importlib.resources import files
from importlib.util import find_spec
from pathlib import Path
from typing import cast

from platformdirs import user_data_path, user_documents_path

FLATPAK = bool(os.environ.get("FLATPAK_ID"))
# pyannote requires an explicit opt-in/out for telemetry metrics and raises
# ValueError on model load if unset. Default to opt-out for all runtimes
# (Flatpak, MSIX, native pip on Linux/macOS/Windows, Docker); `setdefault`
# respects an explicitly-set env var if an operator wants metrics on.
os.environ.setdefault("PYANNOTE_METRICS_ENABLED", "false")
LINUX = platform.system().lower() == "linux"
# pyannote requires an explicit opt-in/out for telemetry metrics
if FLATPAK:
    os.environ.setdefault("PYANNOTE_METRICS_ENABLED", "false")

# Keep `spawn` for Flatpak x86; avoid forcing it on Flatpak ARM.
if FLATPAK and platform.machine().lower() not in {"aarch64", "arm64"}:
    try:
        mp.set_start_method("spawn", force=True)
    except RuntimeError:
        pass

ATRAIN_DIR = (
    Path(os.environ["ATRAIN_USER_DIR"])
    if os.environ.get("ATRAIN_USER_DIR")
    else (user_documents_path() / "aTrain")
)
MODELS_DIR = (user_data_path() / "models") if FLATPAK else (ATRAIN_DIR / "models")

if FLATPAK:
    flatpak_required_models_dir = Path("/app/share/atrain-required-models")
    REQUIRED_MODELS_DIR = (
        flatpak_required_models_dir if flatpak_required_models_dir.is_dir() else MODELS_DIR
    )
elif find_spec("aTrain"):
    # Same fallback as the Flatpak branch above: only use the in-package dir
    # when it actually ships models. The install location can be read-only
    # (MSIX under C:\Program Files\WindowsApps\), so a missing dir must not
    # be created there at runtime - downloads go to the writable MODELS_DIR.
    packaged_required_models_dir = cast(Path, files("aTrain") / "required_models")
    REQUIRED_MODELS_DIR = (
        packaged_required_models_dir if packaged_required_models_dir.is_dir() else MODELS_DIR
    )
else:
    REQUIRED_MODELS_DIR = MODELS_DIR

REQUIRED_MODELS = ["speaker-detection", "large-v3-turbo"]


def packaged_models_dir() -> Path | None:
    """The read-only dir shipping models, or None when this build bundles none.

    The two dirs above answer different questions: REQUIRED_MODELS_DIR is where
    the *packager* puts models at build time (inside the install location, which
    is read-only for MSIX and Flatpak), MODELS_DIR is where the *app* writes
    downloads at runtime. They collapse into one when nothing is bundled, so the
    inequality - not the mere existence of REQUIRED_MODELS_DIR - is what tells
    the two situations apart.
    """
    return REQUIRED_MODELS_DIR if REQUIRED_MODELS_DIR != MODELS_DIR else None


def is_packaged_model(model: str) -> bool:
    """True when `model` ships inside the install dir, so the user cannot manage it.

    Ask this instead of testing membership in REQUIRED_MODELS: that list names
    models the build *may* bundle, which stopped implying that it *did* once slim
    builds shipped without them.
    """
    packaged = packaged_models_dir()
    return packaged is not None and (packaged / model).is_dir()


TRANSCRIPT_DIR = ATRAIN_DIR / "transcriptions"
METADATA_FILENAME = "metadata.txt"
LOG_FILENAME = "log.txt"
TIMESTAMP_FORMAT = "%Y-%m-%d %H-%M-%S"
SAMPLING_RATE = 16000
DEFAULT_CPU_THREADS = max(1, count - 1) if (count := os.cpu_count()) else 4
MAX_CPU_THREADS = os.cpu_count() or DEFAULT_CPU_THREADS
