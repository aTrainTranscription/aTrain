# Linux installation (end users)

This is the end-user install guide for running aTrain on Linux via the command
line. For the recommended install, use the
[Flathub package](https://flathub.org/apps/io.github.juergenfleiss.aTrain). The
manual setup below is for systems where Flatpak is not an option, or for users
who prefer a virtual-environment install.

> Developing aTrain on Linux? See [CONTRIBUTING.md](../CONTRIBUTING.md), which
> covers the uv-based workflow, the native GUI build dependencies, and the
> Docker dev container.

## Installers

- **Flathub (recommended):** https://flathub.org/apps/io.github.juergenfleiss.aTrain
- A `.deb` file for beta 1.2.1 is available on the
  [university download page](https://business-analytics.uni-graz.at/de/forschung/atrain/download/).

## Manual setup on Ubuntu / Debian

### Limitations

- No Snap package is currently provided. Beyond Flathub, installation and start
  are via the command line, but with the aTrain user interface.
- CPU transcription is the reliably supported path on Linux.
- Additional packages are installed via `apt` from the Universe repository.
- Tested on Ubuntu 24.04 LTS.

### Setup

Update package lists:

```bash
sudo apt update
```

Install dependencies:

```bash
sudo apt install ffmpeg python3 python3-pip python3-venv git build-essential \
    libgl1-mesa-dev libcairo2 libcairo2-dev libgirepository1.0-dev \
    libwebkit2gtk-4.1-dev -y
```

Create a virtual environment in your home folder (or any other you prefer) and
activate it:

```bash
cd ~
python3 -m venv atrain_venv
source atrain_venv/bin/activate
```

Install aTrain (with the GUI extras) from the GitHub repository:

```bash
pip install "aTrain[gui] @ git+https://github.com/aTrainTranscription/aTrain.git@develop"
```

On Linux the PyPI PyTorch wheel already bundles CUDA, so no extra package index
is required.

Download the models for transcription and speaker detection. This only has to
be done once:

```bash
aTrain init
```

Start aTrain. This command opens the user interface:

```bash
aTrain start
```

### Start aTrain after installation

If aTrain is already installed, start it with:

```bash
cd ~
source atrain_venv/bin/activate
aTrain start
```

### Python version note

Depending on your Ubuntu version you might need a newer Python than the system
default. Install it from a third-party repository, then run the commands above
with that interpreter:

```bash
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt install python3.12
```
