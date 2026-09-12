# Local development setup

aTrain uses [uv](https://docs.astral.sh/uv/) for environment and dependency
management. uv is the recommended workflow for local development and is what
CI uses.

```bash
uv sync                 # install runtime dependencies
uv run aTrain init      # download required ML models
uv run aTrain start     # run the app
```

If you do not have uv installed yet, see the
[uv installation guide](https://docs.astral.sh/uv/#installation).

## Linux: native GUI build dependencies

On Linux the runtime includes `pywebview[GTK]`, whose `pygobject`/`pycairo`
dependencies build from source and require the cairo/glib native libraries plus
`pkg-config`. Install them before the first `uv sync` (Debian/Ubuntu):

```bash
sudo apt-get install -y libcairo2-dev libgirepository1.0-dev pkg-config libglib2.0-dev
```

The recommended Linux workflow is the [Docker dev container](#docker-development-environment),
which installs these for you and runs the app in the browser.

> Looking for the **end-user** Linux install (not development)? See
> [docs/installation-linux.md](docs/installation-linux.md).

## Docker development environment

For a reproducible, isolated setup that needs nothing on the host but Docker,
use the bundled dev container. It pins the toolchain and the locked dependency
graph, bind-mounts the source for live editing, and persists downloaded models
and transcription output across rebuilds.

```bash
docker compose up        # builds the image and starts aTrain
```

The app is then served at `http://localhost:8080`.

The container runs aTrain in **browser mode** (`aTrain start --no-native`). It
deliberately does **not** ship the native desktop-window backend: `pywebview`'s
GTK backend has no use in a headless container, and excluding it keeps the image
lean and portable. Development inside the container is therefore browser-based
only; contributors who need to exercise the native window can do so on their
host after installing the GUI build dependencies above.

## Running the CI checks locally

The CI workflow runs `ruff` (lint + format), `bandit` (security scan),
and `pip-audit` (known-CVE scan). To reproduce the same checks locally
before pushing:

```bash
uv sync --group dev                        # install dev tools
uv run ruff check .                        # lint
uv run ruff format --check .               # format check (no rewrites)
uv run ruff format .                       # apply formatter
uv run bandit -r aTrain -c pyproject.toml  # security scan

# known-CVE scan of the locked dependency graph (same as CI):
mkdir -p /tmp/audit && uv export --format pylock.toml -o /tmp/audit/pylock.toml
uv run pip-audit /tmp/audit --locked
```

`uv sync --locked --group dev` is also used by CI to validate that
`uv.lock` is in sync with `pyproject.toml`. Running `uv lock` locally
after any dependency change keeps the lockfile current.

# Building a standalone executable

We use [PyInstaller](https://pyinstaller.org/) to freeze aTrain into a
standalone executable. The repository ships PyInstaller spec files per
platform:

- `freeze.spec` — Windows / Linux
- `macos_freeze.spec` — macOS

To build your own package:

Clone and install aTrain in **editable mode**:

```bash
git clone https://github.com/aTrainTranscription/aTrain.git
cd aTrain
pip install -e ".[gui]" --extra-index-url https://download.pytorch.org/whl/cu128
```

Download ffmpeg and all required models from Whisper and pyannote.audio:

```bash
aTrain init
```

Install PyInstaller and build with the spec file for your platform:

```bash
pip install pyinstaller
pyinstaller freeze.spec          # Windows / Linux
# or
pyinstaller macos_freeze.spec    # macOS
```

The standalone executable is written to `./dist/aTrain`. Open the executable in
that folder to run this build (e.g. `aTrain.exe` on Windows).

To go a step further and create an MSIX installer for aTrain, you can use
[Advanced Installer Express](https://www.advancedinstaller.com/express-edition.html);
see their [documentation](https://www.advancedinstaller.com/user-guide/introduction.html).

# Branching

As the project grows and community contributions become more frequent (thanks all!) we opted to adopt a branching model with the intention to make it easier and clearer for contributors to make pull requests.

We will mainly follow the model proposed at http://nvie.com/posts/a-successful-git-branching-model/ with some exceptions. After release 1.3.0 there will be two permanent branches: `main`and `develop`.

The `main` branch will be only be updated from `develop` for a new release. That is, each commit in `main` corresponds to a new release. In addition, there are temporary branches for bugfixes and features, which will mainly exist on developer’s forks. There may be public feature branches on aTrain in case a major feature is developed in collaboration.

After each release, a new branch `bugfixes_for_aTrain_1.x.x` will be opened. Any pull requests for bug fixes should use this base. The `bugfixes_for_aTrain_1.x.x` branch will be merged into `main` and `develop` for minor releases.

# Contributing the code

Developers create new branches on their own forks/repositories which are either named `feature_xx` for feature branches or `bugfixes_xx` for bugfix branches. Once they finished development, they can submit a pull request in order to merge their branch into `develop`. Before the pull requests, the branch should be rebased to the current state of develop such that the submitted changes are direct descendants from the current state of develop, and no merge conflicts exist.

If you want to contribute to a collaborative feature branch, the same steps apply as for contributing a full feature/bugfix to `develop`, only that the base will be that feature branch rather than `develop`.

aTrain maintainers may:

1. Reject a pull request - The feature may be deemed of no value to other aTrain users and not incorporated into the aTrain distribution. The discussion about this will be documented in the pull request comments. The developer may still provide his version to others, but there will be no support for this feature from aTrain maintainers. Feel of course free to contact us beforehand with any ideas.

2. Request modifications - aTrain maintainers may request changes to the submitted code. If the submitted pull request results in a merge conflict with the current state of `develop`, a common request will be to rebase the submitted branch to latest `develop`.

3. Accept the request - If the pull request is accepted, then the submitted branch will be merged into `develop`.

# Releases policy

Once `develop` reaches a state which justifies a new release, then there will be one additional house-keeping commit on `develop` (update version number, changelog, install and update instructions), and `develop` will be merged into `main`. The commit will be tagged as a release.

Release numbers conform to the following scheme: X.Y.Z with X, Y, Z natural numbers. Bugfixes and minor feature improvements (all of which do not feature any change to the database structure) result in an increase of Z. New features result in an increase of Y and setting Z to zero. Major new versions of aTrain with significant new features or code-rewriting will result in an increase of X and in setting Y and Z to zero. “alpha” and “beta” may be added to versions which are not stable yet but which nevertheless are proposed to the public for testing.

_Adapted for aTrain from [Orsee Development Instructions](https://github.com/orsee/orsee/) by @bgrainer_
