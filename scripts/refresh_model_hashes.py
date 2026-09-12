#!/usr/bin/env python3
"""Refresh the per-file hashes in models.json from the Hugging Face Hub.

Maintainer tool, not part of the shipped package and never run in CI. Use it
whenever a model is added to models.json or its `revision` changes; the updated
hashes then show up as a reviewable diff, like a lockfile.

    scripts/refresh_model_hashes.py            # write the hashes into models.json
    scripts/refresh_model_hashes.py --check    # compare only, exit 1 on drift
    scripts/refresh_model_hashes.py tiny base  # limit to specific models

The Hub reports two kinds of hash, and which one applies depends on how the file
is stored, so the algorithm is written into the manifest rather than guessed
from the hash length later:

    LFS files (the weights)   ->  sha256 of the file content
    everything else           ->  git blob SHA-1 over "blob <size>\\0" + content

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


def fetch_file_hashes(repo_id: str, revision: str) -> dict[str, str]:
    """Return {filename: "sha256:<hash>"} for every file of a model repo."""
    info = HfApi().model_info(repo_id, revision=revision, files_metadata=True)
    hashes: dict[str, str] = {}
    for sibling in info.siblings or []:
        lfs = getattr(sibling, "lfs", None)
        sha256 = getattr(lfs, "sha256", None) if lfs else None
        if not sha256:
            # Files below the LFS threshold are plain git objects, for which the
            # Hub only reports a SHA-1. They are small (a few MB per model), so
            # fetch and hash them here and keep the manifest on one algorithm.
            local = hf_hub_download(repo_id, sibling.rfilename, revision=revision)
            sha256 = hashlib.sha256(Path(local).read_bytes()).hexdigest()
        hashes[sibling.rfilename] = f"sha256:{sha256}"
    return dict(sorted(hashes.items()))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("models", nargs="*", help="model names, defaults to all")
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare against the Hub without writing; exit 1 if they differ",
    )
    args = parser.parse_args()

    config = json.loads(MODELS_JSON.read_text())
    names = args.models or list(config)
    unknown = [name for name in names if name not in config]
    if unknown:
        raise SystemExit(f"unknown model(s): {', '.join(unknown)}")

    drifted = []
    for name in names:
        model = config[name]
        fetched = fetch_file_hashes(model["repo_id"], model["revision"])
        if args.check:
            if model.get("files") != fetched:
                drifted.append(name)
                print(f"DRIFT {name}")
                for filename in sorted(set(fetched) | set(model.get("files", {}))):
                    pinned = model.get("files", {}).get(filename)
                    current = fetched.get(filename)
                    if pinned != current:
                        print(f"    {filename}\n      pinned: {pinned}\n      hub:    {current}")
            else:
                print(f"ok    {name} ({len(fetched)} files)")
        else:
            model["files"] = fetched
            print(f"{name}: {len(fetched)} files")

    if args.check:
        return 1 if drifted else 0

    MODELS_JSON.write_text(json.dumps(config, indent=4) + "\n")
    print(f"\nwrote {MODELS_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
