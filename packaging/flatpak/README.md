# Flatpak releases

aTrain is published on Flathub as
[`io.github.juergenfleiss.aTrain`](https://github.com/flathub/io.github.juergenfleiss.aTrain).
[`flatpak.yml`](../../.github/workflows/flatpak.yml) builds it and prepares the
Flathub update. Flathub builds and publishes the app itself.

## Files

- [`io.github.juergenfleiss.aTrain.yml`](io.github.juergenfleiss.aTrain.yml):
  the manifest template. It covers permissions, bundled models and the app module.
- [`prepare-flatpak.py`](../../.github/scripts/prepare-flatpak.py): writes
  `flatpak-release/`, which contains:
  - `io.github.juergenfleiss.aTrain.yml`: the template, pinned to the current
    commit and tag. This is the file submitted to Flathub.
  - `local.yml`: the same manifest, built from the checkout.
  - `atrain_python_dependencies.json`: the offline pip sources. The script runs
    `uv export --format pylock.toml`, and `packaging`'s PEP 751 selector picks
    one wheel per package for each CPU architecture of the GNOME 50 runtime
    (CPython 3.13, glibc 2.42). A package without a matching wheel fails
    generation, unless it is on the reviewed sdist allowlist.

  The script also checks that the tag, `aTrain/version.py` and the newest
  AppStream release all agree. RC tags such as `v1.5.0-rc1` only need to match
  the base version, and are never submitted to Flathub.

  The script's own tools (`packaging`, `ruamel.yaml`) are pinned in the `flatpak`
  dependency group in `pyproject.toml` and locked in `uv.lock`.

## Workflow

The workflow runs on `v*` tags, on manual runs, and on PRs that change packaging
inputs.

1. **prepare** generates `flatpak-release/`.
2. **build** runs natively on GitHub's `ubuntu-24.04` (x86_64) and
   `ubuntu-24.04-arm` (aarch64) runners. It uses Flathub's `gnome-50` container
   and the Flatpak project's
   [`flatpak-builder` action](https://github.com/flatpak/flatpak-github-actions).
   Each build:
   - lints the Flathub manifest before building and the repository afterwards,
     the two checks Flathub runs;
   - builds the submitted manifest on tags and `local.yml` otherwise;
   - imports the main Python packages inside the Flatpak as a smoke test;
   - on tags and manual runs, uploads a `.flatpak` bundle for testing, kept 14
     days.
3. **submit** runs for stable tags once both builds pass. It opens or updates a
   PR against the Flathub repository. Test the Flathub PR build, then merge it to
   publish.

### One-time setup

Fork the Flathub repository. Then add these to `aTrainTranscription/aTrain`:

- Variable `FLATHUB_FORK`: the fork's `owner/repo`. Submission is skipped while
  this is unset.
- Secret `FLATHUB_TOKEN`: a classic PAT with `public_repo` scope. It must be
  able to push to the fork and open PRs on Flathub
  ([details](https://github.com/peter-evans/create-pull-request/blob/main/docs/concepts-guidelines.md#push-pull-request-branches-to-a-fork)).

### Releasing

1. Bump `aTrain/version.py`.
2. Add a `<release>` to the AppStream metadata, ideally with release notes.
3. Push the `vVERSION` tag.

To resubmit, re-run the failed jobs of the tag's workflow run.

## Local build

This needs the `org.flatpak.Builder` app from Flathub and about 40 GB of free
space. The CUDA wheels take most of it.

```bash
uv run --isolated --only-group flatpak python .github/scripts/prepare-flatpak.py
flatpak run org.flatpak.Builder --user --install --install-deps-from=flathub \
  --force-clean flatpak_app flatpak-release/local.yml
flatpak run io.github.juergenfleiss.aTrain
```

`local.yml` copies the working tree, including uncommitted changes, but skips
git-ignored paths such as `.venv` and bundles.

The tests in `tests/unit/test_prepare_flatpak.py` generate sources from the real
`uv.lock`. A dependency update without a matching Linux wheel therefore fails the
fast unit tests.

## Maintenance notes

- **Runtime:** to move to a newer GNOME runtime, update `runtime-version`, the
  container tag in the workflow, and `PYTHON`/`GLIBC_MINOR` in the script
  together. Every native wheel then has to be regenerated and tested.
- **aarch64 wheels:** on Linux aarch64, `torch` and `torchcodec` come from the
  PyTorch `cu128` index (see `[tool.uv.sources]`). The x86_64 wheels come from
  PyPI.
- **Models:** the bundled models are pinned to Hugging Face commits. Update the
  URL and `sha256` together.
