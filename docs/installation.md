# Installation (end users)

aTrain is published as a packaged desktop app and can also be installed from
source with pip.

> Setting up aTrain for **development**? See
> [CONTRIBUTING.md](../CONTRIBUTING.md), which uses the
> [uv](https://docs.astral.sh/uv/) workflow. Building a **standalone
> executable** is also covered there.

## Packaged apps (recommended)

- **Windows:** [Microsoft Store](https://apps.microsoft.com/detail/9N15Q44SZNS2?mode=direct)
- **Linux:** [Flathub](https://flathub.org/apps/io.github.juergenfleiss.aTrain)
  (see also the [Linux installation guide](installation-linux.md) for a manual
  command-line setup)

Additional download types are listed on the
[university download page](https://business-analytics.uni-graz.at/de/forschung/atrain/download/).

How release builds are signed: see the [Code signing policy](code-signing-policy.md).

## Install from source with pip

You need **Python ≥ 3.11**.

Set up and activate a virtual environment:

```bash
python -m venv venv
# Windows
.\venv\Scripts\activate
# macOS / Linux
source venv/bin/activate
```

Install aTrain with the GUI extras (needed for `aTrain start`, the desktop /
browser app):

```bash
pip install "aTrain[gui] @ git+https://github.com/aTrainTranscription/aTrain.git"
```

On **Windows**, prepend the PyTorch CUDA index so pip pulls the CUDA torch
wheel:

```bash
pip install "aTrain[gui] @ git+https://github.com/aTrainTranscription/aTrain.git" \
    --extra-index-url https://download.pytorch.org/whl/cu128
```

On **Linux** the PyPI torch wheel already bundles CUDA. **macOS** is CPU-only.
NVIDIA CUDA GPU support currently covers Windows and Debian-based Linux.

Download the models for transcription and speaker detection. This only has to be
done once:

```bash
aTrain init
```

Start aTrain:

```bash
aTrain start
```

## Command-line / headless usage

For headless transcription pipelines, aTrain also exposes a CLI (`aTrain_core
transcribe`). See the "Headless / CLI Usage" section in the
[README](../README.md#headless--cli-usage).
