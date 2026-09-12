"""Integrity checks for downloaded model files.

Models are pinned in models.json by revision *and* by a per-file hash, and this
module compares what is on disk against those hashes. Pinning them in our own
repository rather than fetching them from the Hub at check time is what makes
the check meaningful: a hash served by the same place as the file cannot
disprove that the file was tampered with. It also keeps verification working
without network access.

Only files listed in the manifest are looked at. Anything else in the model
directory is ignored - notably the `.cache/huggingface/` bookkeeping that
`snapshot_download` writes, whose contents differ between downloads and which
broke an earlier attempt at hashing the directory as a whole.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

CHUNK_SIZE = 1024 * 1024


class ModelIntegrityError(Exception):
    """A model does not match the checksums pinned for it in models.json."""


def _file_hash(path: Path, algorithm: str) -> str:
    """Hash a file without reading it into memory - the weights are gigabytes."""
    if algorithm != "sha256":
        raise ValueError(f"unsupported hash algorithm: {algorithm}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def find_missing_files(model_path: Path, manifest: dict[str, str]) -> list[str]:
    """Names of manifest files that are not on disk.

    Cheap enough to run on every load: a download that was interrupted leaves
    files missing rather than truncated, because huggingface_hub downloads to a
    temporary name and moves the file into place once it is complete.
    """
    return sorted(name for name in manifest if not (model_path / name).is_file())


def verify_model(model_path: Path, manifest: dict[str, str]) -> list[str]:
    """Check every manifest file and return all problems found, not just the first.

    Reporting everything at once means a user who has to act on the message
    learns the full extent in one go instead of one file per attempt.
    """
    problems: list[str] = []
    for name, expected in sorted(manifest.items()):
        path = model_path / name
        if not path.is_file():
            problems.append(f"{name}: missing")
            continue
        algorithm, _, expected_hash = expected.partition(":")
        try:
            actual = _file_hash(path, algorithm)
        except ValueError as error:
            problems.append(f"{name}: {error}")
            continue
        if actual != expected_hash:
            problems.append(f"{name}: expected {algorithm} {expected_hash}, got {actual}")
    return problems
