# Flatpak releases

[`.github/workflows/flatpak.yml`](../../.github/workflows/flatpak.yml) replaces
the manual two-repository process in `JuergenFleiss/atrain2flatpak`. It packages
both `aTrain` and `aTrain_core` from this repository in one install. The private
notes repository is no longer a build input.

## What runs

On a `v*` tag, a manual dispatch, or a relevant pull request, the workflow:

1. Exports the locked GUI dependencies as one PEP 751 `pylock.toml` file without
   development packages or the local project. PyCairo, PyGObject, and its typing
   stubs are omitted because GNOME Platform already supplies the runtime bindings.
   No full ML environment is installed just to generate sources.
2. Generates an offline dependency manifest using `req2flatpak==0.3.1` for
   CPython 3.13 / GNOME 50. The preparation script evaluates pylock package
   markers separately for `x86_64` and `aarch64`, then passes its locked
   artifacts to req2flatpak's wheel selector and module generator. URLs and
   SHA-256 hashes come directly from the exported lock; generation does not query
   PyPI. Unsupported binary packages fail preparation instead of silently
   attempting a build.
3. Runs Flathub's official `flatpak-builder-lint` manifest check on the generated
   submission files and its AppStream check on the tracked project metadata.
   After each native build, it also checks
   the Flatpak build directory and exported OSTree repository. These checks are
   gating: a linter error stops the workflow before submission.
4. Builds on native `ubuntu-24.04` and `ubuntu-24.04-arm` runners with the GNOME
   50 SDK installed from Flathub. The jobs remove unused hosted-runner
   toolchains, cached tools, and container images before installing the SDK to
   leave space for the ML wheels, models, build state, and bundles. ARM excludes
   x86 NVIDIA and Triton dependencies; x86 retains its CUDA libraries. Models
   stay bundled with the current Flathub archive hashes and revision-pinned
   `.gitattributes` files.
5. For release tags and manual runs, uploads architecture-specific `.flatpak`
   bundles and checksums. Pull requests skip costly bundle compression after
   validating both native builds and their Flathub lints. All runs upload a
   separate `aTrain-flathub-sources` artifact containing the reviewable manifest
   files. Bundles are workflow artifacts; Flathub builds the source manifest
   itself rather than accepting these bundles for publication.
6. For stable release tags, optionally creates or updates a Flathub PR after
   **both** architectures pass. Flathub's test build and maintainer merge remain
   the final publication steps.

Pull request builds use the checked-out source, including fork commits. The
submission artifact always retains the public repository URL and immutable git
commit. A tag must match both `aTrain/version.py` and the newest release in the
tracked AppStream metadata. The metadata is installed directly from the pinned
source checkout; no release-specific XML is generated.

This workflow is independent of the Windows MSIX release and does not replace
the normal application CI checks. It verifies packaging and Flathub policy, but
does not run the installed application; functional and hardware behavior remain
covered by normal CI and testing on the intended hardware.

## One-time GitHub setup

Create a fork of
[`flathub/io.github.juergenfleiss.aTrain`](https://github.com/flathub/io.github.juergenfleiss.aTrain).
In **aTrainTranscription/aTrain**, configure:

- Repository variable **`FLATHUB_FORK`**: the fork's `owner/repository`, for
  example `JuergenFleiss/io.github.juergenfleiss.aTrain`.
- Repository secret **`FLATHUB_TOKEN`**: a token that can push packaging branches
  to that fork and create/update pull requests against the Flathub repository.
  A classic PAT with `public_repo` scope can cover this public fork workflow.
  An installed GitHub App with appropriate repository access and Contents/
  Pull requests write permissions is another option; fine-grained PATs can be
  limited by the repositories' different owners. Follow the
  [PR action's fork authentication guidance](https://github.com/peter-evans/create-pull-request/blob/main/docs/concepts-guidelines.md#push-pull-request-branches-to-a-fork).

Without these settings, builds still produce artifacts and the workflow reports
that submission was skipped. The normal `GITHUB_TOKEN` cannot push to an
external fork. Cross-repository credentials are used only in the submission
job, never in branch or fork PR builds.

Push a stable `vVERSION` tag after updating the package version and running the
normal checks. The generated branch is `atrain/vVERSION`; repeated runs update
the same PR. Manual runs default to artifacts only. To submit a manual run,
select a stable release tag as its ref and enable **submit**. Pre-release tags
produce artifacts without a Flathub stable submission.

Install and test Flathub's resulting PR build, then merge it when ready. A
successful official Flathub build publishes the update, as described in
[Flathub's update workflow](https://docs.flathub.org/docs/for-app-authors/maintenance#creating-updates).

## Deliberate build exceptions

Unlike the manual `req2flatpak` CLI command, preparation uses its Python API
so it can keep the exact locked artifacts and architecture-specific markers.
It supplies GNOME 50's CPython 3.13 / glibc 2.42 compatibility tags because
req2flatpak 0.3.1's built-in Linux targets stop at glibc 2.35. The generated pip
command disables network access, build isolation, and dependency resolution,
and ignores preinstalled packages so the selected locked artifacts are used.
req2flatpak is a preparation/test tool, not an application dependency.
The published 0.3.1 release requires `packaging<22`, so preparation pins
`packaging==21.3` in its isolated tool environment.

GNOME 50 intentionally keeps Python 3.13 for this release. Although the current
NumPy 2.4.6 pin also supports Python 3.14, moving to GNOME 51 still requires
regenerating and testing every native dependency and the TorchCodec artifacts.
Changing only the runtime number is not sufficient.

The project pins TorchCodec 0.10.0, matching the previously published Flatpak.
The architecture-specific sources in `pyproject.toml` reproduce its artifact
selection: x86 uses the PyPI wheel and Linux ARM64 uses the `+cu128` wheel from
the official PyTorch index. Both variants are recorded in `uv.lock` and emitted
normally by req2flatpak; the manifest has no TorchCodec-specific module.

The SDK provides the compiler and standard Python build tools. Approved
source-only dependencies (`julius`, `proxy-tools`) build with isolation and
dependency resolution disabled. Review the allowlist before adding another
source build.

To update the SDK, change the manifest runtime and workflow SDK install together,
then update the generator's CPython/platform tags. When the TorchCodec version
changes, regenerate `uv.lock` and verify both architecture artifacts. When model
archives change, update and verify their hashes too.

## Local preparation and build

Allow roughly 40 GB of free space for an x86 build, including downloads,
build/cache state, the exported repository, and its bundle, in addition to the
installed SDK. The CUDA libraries dominate this requirement. Their bundle
compression can take over an hour, so CI skips bundling on pull requests after
the native build and Flathub linters pass.

From the repository root:

```bash
uv export --locked --extra gui --no-dev --no-emit-project \
  --no-emit-package pycairo --no-emit-package pygobject \
  --no-emit-package pygobject-stubs \
  --format pylock.toml --output-file pylock.flatpak.toml
uv run --no-project --with req2flatpak==0.3.1 --with packaging==21.3 --with pyyaml==6.0.3 \
  python .github/scripts/prepare-flatpak.py \
    --lock pylock.flatpak.toml \
    --commit "$(git rev-parse HEAD)" \
    --output-dir .flatpak-work --local-source "$PWD"
flatpak-builder --force-clean --disable-rofiles-fuse --repo=repo \
  flatpak_app .flatpak-work/io.github.juergenfleiss.aTrain.yml
flatpak run --command=flatpak-builder-lint org.flatpak.Builder builddir flatpak_app
flatpak run --command=flatpak-builder-lint org.flatpak.Builder repo repo
flatpak build-bundle repo aTrain-local.flatpak io.github.juergenfleiss.aTrain
```

Install the GNOME 50 SDK/runtime and `flatpak-builder` first. A native ARM build
needs an ARM machine; setting `--arch=aarch64` on an x86 machine does not provide
emulation. Omit `--local-source` to generate the source-pinned Flathub copy, and
add `--tag vVERSION` when preparing a tagged release. The committed AppStream
metadata must already contain the release version as its newest entry.

Run the lightweight generator tests with `python -m pytest
tests/unit/test_prepare_flatpak.py`. They need `req2flatpak==0.3.1`, `packaging`,
PyYAML and pytest, without Torch or the desktop libraries.
