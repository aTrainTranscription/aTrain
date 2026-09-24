# AGENTS.md

Notes for AI coding agents (Codex, Claude Code, Copilot, ...). Contribution
mechanics are in [CONTRIBUTING.md](CONTRIBUTING.md).

## Ground rules

- State your assumptions. If the task is ambiguous, ask instead of picking silently.
- Make the minimum change that solves the problem. No speculative abstractions, no drive-by refactors, match the existing style, convention and structure.
- Turn the task into checks: a bug fix starts with a failing test, a UI change is clicked through in the running app. If you could not verify something, say so.

## Project invariants

- **Offline by design.** Audio and transcripts never leave the machine. The only outbound traffic is the model download from Hugging Face.
- **uv is the workflow.** `uv sync`, `uv add`, `uv lock`. No `pip install` in setup paths, no bypassing `uv.lock`.
- **Three platforms.** Windows (MSIX) and Linux (Flatpak) ship as packages, macOS runs from source and is CPU-only. Platform-specific code needs a fallback; Linux-only deps are gated with `sys_platform` markers in `pyproject.toml`.

## Layout

- `aTrain/` - NiceGUI desktop app (pages, components, utils). Entry points `aTrain start` and `aTrain init` (downloads the required models).
- `aTrain_core/` - transcription engine (faster-whisper and transformers backends), model loading, headless CLI `aTrain_core transcribe|load|remove`.
- `aTrain_core/data/models.json` - model registry. Every entry carries pinned file hashes (`scripts/refresh_model_hashes.py` generates them) and the licence id the SBOM script checks.
- `packaging/` - platform builds (so far only `msix/`; Flatpak and the PyInstaller specs still live in `flatpak/`, `share/` and the root and are meant to move here). `.github/workflows/release.yml` builds and signs the Windows release on tag push; Flatpak and macOS are follow-ups.
- `tests/unit`, `tests/core`, `tests/ui`, `tests/e2e_browser` - `.github/workflows/ci.yml` shows what runs where.
- `docs/` - user and security documentation.

## Setup and checks

```bash
uv sync --locked --extra gui           # app + engine; CUDA torch on Windows and Linux, CPU on macOS
uv run ruff check . && uv run ruff format .
uv run bandit -r aTrain aTrain_core -c pyproject.toml
uv pip install pytest pytest-asyncio   # pytest is not a project dependency; CI installs it the same way
uv run --no-sync pytest tests/unit     # fast and offline
```

`tests/core` downloads the `tiny` model from Hugging Face and runs real transcriptions on CPU, so it needs network and a few minutes. `tests/ui` and `tests/e2e_browser` need the GUI stack.

- One test: `uv run --no-sync pytest tests/unit -k <name>`.
- Add or update tests for what you change. Pure logic goes to `tests/unit`, engine runs to `tests/core`, NiceGUI pages to `tests/ui` (the `user` fixture), browser flows to `tests/e2e_browser`.
- Before opening a PR: ruff clean and `tests/unit` green; run `tests/core` or `tests/ui` too when you touched the engine or a page.

Run `uv lock` after any dependency change and commit `uv.lock`; CI installs with `--locked`. Details in [CONTRIBUTING.md](CONTRIBUTING.md).

## Conventions

- Branch from `develop`, name it `feature_<topic>` or `bugfixes_<topic>`, open the PR against `develop`. After a release, bugfix PRs target the `bugfixes_for_aTrain_1.x.x` branch when one exists (see CONTRIBUTING.md). Never push to `main`.
- Use the PR template in `.github/pull_request_template.md` for every PR body.
- Local agent state (`.claude/settings.local.json`, `.codex/`, `CLAUDE.local.md`) is gitignored. Files meant for everyone, such as shared skills under `.claude/skills/`, are committed like any other file.

## Gotchas

Known pitfalls in this repo. Add new ones as they come up.

- Models and user data live under `ATRAIN_USER_DIR` (default `~/Documents/aTrain`; Flatpak keeps models in the XDG data dir instead). Tests must point it at a temp dir; the fixtures in `tests/core/test_transcription_e2e.py` show how. Never let a test download into the real folder.
- Adding a model means a `models.json` entry with file hashes and a licence id, and `.github/scripts/build-sbom.py` must accept it. Non-standard licences need a `LicenseRef-...` expression.
- Model download progress works by patching `huggingface_hub` internals in `aTrain_core/load_resources.py`. Check that path when touching downloads or bumping `huggingface_hub`.
- Heavy imports (torch, ctranslate2) must stay out of the app's startup path, or the splash screen never shows.

## Where to look

- Branching, setup, release policy: [CONTRIBUTING.md](CONTRIBUTING.md)
- MSIX and the release build: [packaging/msix/README.md](packaging/msix/README.md) and the header of `.github/workflows/release.yml`
- Signing and verification: [docs/code-signing-policy.md](docs/code-signing-policy.md), [docs/verifying-releases.md](docs/verifying-releases.md)
- Models and the SBOM: the docstring of `.github/scripts/build-sbom.py`
