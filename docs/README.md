# aTrain documentation

aTrain is a tool for automatically transcribing speech recordings using
state-of-the-art machine learning models, fully offline and without uploading
any data. This directory holds the user and reference documentation. For the
project overview, badges, and benchmarks, see the [main README](../README.md).

## Installation

- [Installation (end users)](installation.md) — packaged apps (Microsoft Store,
  Flathub) and installing from source with pip.
- [Linux installation](installation-linux.md) — manual command-line setup on
  Ubuntu / Debian.
- [Windows deployment](deployment-windows.md) — MSIX rollout on managed
  machines, for IT departments.
- [Linux service](linux/service.md) — running aTrain as a systemd service,
  experimental.
- [Uninstalling aTrain](uninstall.md) — removing the app and its data for
  the MSIX and Flatpak packages.

## Usage

- [Tutorials](tutorials.md) — importing aTrain output into QDA software (MAXQDA,
  NVivo on Windows and macOS).

## Reference

- [Security](security/) — security assessments, e.g. the
  [OWASP Top 10 for LLM Applications assessment](security/owasp-llm-top10-assessment.md).
- [Code signing policy](code-signing-policy.md) — how release builds are
  signed, who approves signing requests, and what the app transmits.
- [Verifying a release](verifying-releases.md) — checksums, Authenticode
  signature, source tag and SBOM, for packagers and IT departments.

## For contributors

Development setup, the uv workflow, the Docker dev container, building a
standalone executable, and the branching/release model live in
[CONTRIBUTING.md](../CONTRIBUTING.md).
