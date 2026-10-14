import json
import multiprocessing as mp
import os
import platform
from contextlib import suppress
from importlib.resources import files
from importlib.util import find_spec
from pathlib import Path
from typing import Any, cast

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
DURATION_FORMAT = "{:02}:{:02}:{:02}"  # hours, minutes, seconds; hours may exceed 24


def create_file_id(file_path, timestamp):
    """Creates a unique identifier for a file composed of the file path and timestamp."""
    file_base_name = os.path.basename(file_path)
    timestamp = timestamp.replace(" ", "-").replace("-", "")
    timestamp = timestamp[:-2]
    timestamp = timestamp[2:]
    short_base_name = file_base_name[0:7] if len(file_base_name) >= 5 else file_base_name
    return timestamp + "-" + short_base_name


def free_file_id(file_path, timestamp, transcript_root=TRANSCRIPT_DIR) -> str:
    """A file_id no archive folder has yet. Adds -2, -3, ... in the same minute."""
    base_file_id = create_file_id(file_path, timestamp)
    file_id, suffix = base_file_id, 1
    while os.path.exists(os.path.join(transcript_root, file_id)):
        suffix += 1
        file_id = f"{base_file_id}-{suffix}"
    return file_id


def claim_file_id(file_path, timestamp, transcript_root=TRANSCRIPT_DIR) -> str:
    """Create a new archive folder and return its file_id, so two transcriptions never
    share one (also across processes)."""
    os.makedirs(transcript_root, exist_ok=True)
    while True:
        file_id = free_file_id(file_path, timestamp, transcript_root)
        with suppress(FileExistsError):
            os.makedirs(os.path.join(transcript_root, file_id))
            return file_id


def hms(seconds: float) -> str:
    """Seconds as hh:mm:ss (DURATION_FORMAT)."""
    seconds = int(seconds)
    return DURATION_FORMAT.format(seconds // 3600, seconds % 3600 // 60, seconds % 60)


def write_json_atomic(path: Path, data: Any, **dump_options) -> None:
    """Write `data` so a reader sees the old file or the complete new one, also after a crash."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, **dump_options)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


SAMPLING_RATE = 16000
DEFAULT_CPU_THREADS = max(1, count - 1) if (count := os.cpu_count()) else 4
MAX_CPU_THREADS = os.cpu_count() or DEFAULT_CPU_THREADS
