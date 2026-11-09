# Changelog

Notable changes to aTrain. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow the scheme in [CONTRIBUTING.md](CONTRIBUTING.md#releases-policy).

Older releases are listed on the [GitHub releases page](https://github.com/aTrainTranscription/aTrain/releases).

## [Unreleased]

### Added

- New crisper_whisper transformers backend.
- File upload and download in browser (no-native) mode.
- Downloaded models are checked against pinned per-file hashes.
- Releases ship sha256 checksums and a CycloneDX SBOM; the Windows MSIX is signed via SignPath.
- Local WER evaluation script.
- Docs: uninstall page, adding a model, verifying releases, Windows deployment.
- A server bound to `127.0.0.1` or `localhost` rejects other host names and socket.io connections from other origins. `--allow-any-host` turns this off for a reverse proxy on the same machine.

### Changed

- Improved model manager layout.
- Engine split into reusable steps (groundwork for batch transcription).
- NiceGUI upgraded to 3.x.
- `aTrain start --no-native` binds to `127.0.0.1` by default. Use `--host 0.0.0.0` to serve on the network.

### Fixed

- Missing transcript output caused by the 128-token decoding cap.
- Speaker sentence cues.
- Model download progress on the Xet path.
- large-v3-turbo reachable in slim builds.
