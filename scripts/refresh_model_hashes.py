#!/usr/bin/env python3
"""Refresh the per-file hashes and the sizes in models.json from the Hugging Face Hub.

Maintainer tool, not part of the shipped package and never run in CI. Use it
whenever a model is added to models.json or its `revision` changes; the updated
hashes and sizes then show up as a reviewable diff, like a lockfile.

    scripts/refresh_model_hashes.py            # write hashes and sizes into models.json
    scripts/refresh_model_hashes.py --check    # compare only, exit 1 on drift
    scripts/refresh_model_hashes.py tiny base  # limit to specific models

The Hub reports a sha256 only for LFS files (the weights); for everything else
it has just a git blob SHA-1. The script downloads those small files and hashes
them itself, so every entry is "sha256:<hash of the file content>". The
algorithm is written into the entry rather than guessed from the hash length.

`--check` needs network access and is meant to be run by hand: drift means the
Hub no longer serves what we pinned, which is something a human has to judge.
The netless counterpart - "does every model have a complete files block" - lives
in the test suite.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from huggingface_hub import HfApi, hf_hub_download

MODELS_JSON = Path(__file__).resolve().parents[1] / "aTrain_core" / "data" / "models.json"


def human_size(size: int) -> str:
    """Decimal units with two decimals, as the Hub shows file sizes."""
    if size >= 1_000_000_000:
        return f"{size / 1_000_000_000:.2f} GB"
    return f"{size / 1_000_000:.2f} MB"


def fetch_pinned_fields(repo_id: str, revision: str) -> dict:
    """Return the models.json fields that follow from a repo revision:
    the per-file hashes, and the total size the download progress bar and
    the Models page show."""
    info = HfApi().model_info(repo_id, revision=revision, files_metadata=True)
    hashes: dict[str, str] = {}
    size = 0
    for sibling in info.siblings or []:
        size += sibling.size or 0
        lfs = getattr(sibling, "lfs", None)
        sha256 = getattr(lfs, "sha256", None) if lfs else None
        if not sha256:
            # Files below the LFS threshold are plain git objects, for which the
            # Hub only reports a SHA-1. They are small (a few MB per model), so
            # fetch and hash them here and keep the manifest on one algorithm.
            local = hf_hub_download(repo_id, sibling.rfilename, revision=revision)
            sha256 = hashlib.sha256(Path(local).read_bytes()).hexdigest()
        hashes[sibling.rfilename] = f"sha256:{sha256}"
    return {
        "files": dict(sorted(hashes.items())),
        "repo_size": size,
        "repo_size_human": human_size(size),
    }


def print_drift(label: str, pinned: object, hub: object) -> None:
    print(f"    {label}\n      pinned: {pinned}\n      hub:    {hub}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("models", nargs="*", help="model names, defaults to all")
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare against the Hub without writing; exit 1 if they differ",
    )
    args = parser.parse_args()

    config = json.loads(MODELS_JSON.read_text(encoding="utf-8"))
    names = args.models or list(config)
    unknown = [name for name in names if name not in config]
    if unknown:
        raise SystemExit(f"unknown model(s): {', '.join(unknown)}")

    drifted = []
    for name in names:
        model = config[name]
        fetched = fetch_pinned_fields(model["repo_id"], model["revision"])
        hashes = fetched["files"]
        if args.check:
            if any(model.get(field) != value for field, value in fetched.items()):
                drifted.append(name)
                print(f"DRIFT {name}")
                for filename in sorted(set(hashes) | set(model.get("files", {}))):
                    pinned = model.get("files", {}).get(filename)
                    current = hashes.get(filename)
                    if pinned != current:
                        print_drift(filename, pinned, current)
                for field in ("repo_size", "repo_size_human"):
                    if model.get(field) != fetched[field]:
                        print_drift(field, model.get(field), fetched[field])
            else:
                print(f"ok    {name} ({len(hashes)} files)")
        else:
            model.update(fetched)
            print(f"{name}: {len(hashes)} files, {fetched['repo_size_human']}")

    if args.check:
        return 1 if drifted else 0

    MODELS_JSON.write_text(
        json.dumps(config, indent=4, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"\nwrote {MODELS_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
