# Verifying a release

For anyone who repackages or rolls out aTrain and wants to check that a
downloaded file is what the project published: Flatpak and distribution
maintainers, IT departments, and the Microsoft Store submission. End users
installing from the Store or Flathub do not need any of this; those channels
verify packages themselves.

## What a release consists of

Every release is a git tag `v<version>` and a GitHub release built from it by
[`release.yml`](../.github/workflows/release.yml). It publishes:

| File | Where | Notes |
|------|-------|-------|
| `aTrain-<version>.msix` | [Zenodo](https://doi.org/10.5281/zenodo.22018704) | Windows installer, Authenticode-signed. |
| `checksums.txt` | GitHub release and Zenodo | SHA-256 of every file below, computed after signing. Both copies are identical. |
| `aTrain-<version>-windows.cdx.json` | GitHub release | CycloneDX SBOM of the Windows build. |
| `aTrain-<version>-source.tar.gz` | GitHub (tag archive) | Source at the tag; its hash is in `checksums.txt`. |
| `aTrain-<version>-macos-arm64.dmg` | Zenodo | macOS disk image, Apple silicon, unsigned and not notarized. |
| `checksums-macos.txt` | GitHub release and Zenodo | SHA-256 of the DMG and its SBOM. |
| `aTrain-<version>-macos.cdx.json` | GitHub release and Zenodo | CycloneDX SBOM of the macOS build. |

Windows and macOS upload to the same unpublished Zenodo draft. The Windows
upload passes its draft ID to the macOS job, including on the first release
before `ZENODO_CONCEPT_ID` is configured. The macOS upload checks that the
draft is still unpublished and matches the release version, keeps the Windows
files, and replaces only its own files on retry. Tag runs are serialized, so
two releases never write to the same draft. Publish the draft in Zenodo only
after both platform uploads have succeeded.

The `aTrain-macos-<version>` workflow artifact contains the same three macOS
files.

Under Actions, the `aTrain-msix-<version>` workflow artifact contains the
unsigned build; its installer hash does not match the release's `checksums.txt`.
The `signed-aTrain-<version>` workflow artifact contains the signed installer
and is a temporary alternative download source to Zenodo. The repository's
Actions artifact retention is set to 90 days, so GitHub automatically deletes
the artifact 90 days after upload unless it is manually deleted sooner.
Use Zenodo for long-term downloads. Verify either download against the
checksums published on the GitHub release.

## 1. Compare the checksum

Download `checksums.txt` from the GitHub release, then compare.

Windows:

```powershell
(Get-FileHash .\aTrain-<version>.msix -Algorithm SHA256).Hash
```

PowerShell prints the hash in upper case, `checksums.txt` uses lower case;
compare case-insensitively.

Linux/macOS:

```bash
sha256sum -c checksums.txt --ignore-missing
```

macOS (Apple silicon DMG): compare the hash of the disk image with the
matching line in `checksums-macos.txt` from the GitHub release:

```bash
shasum -a 256 aTrain-<version>-macos-arm64.dmg
```

The macOS build is unsigned for now, so there is no signature to verify, and
Gatekeeper blocks the first launch. Only after the checksum matches, open it
through System Settings → Privacy & Security → Open Anyway.

A mismatch means a corrupted download or a file that is not the released one.
Do not install it; download again, then report if it persists (see below).

## 2. Check the Authenticode signature (Windows installer)

```powershell
Get-AuthenticodeSignature .\aTrain-<version>.msix | Format-List Status, SignerCertificate
```

`Status` must be `Valid` and the signer must be the certificate named in the
[Code signing policy](code-signing-policy.md): issued to SignPath Foundation,
applied through SignPath.io. The policy page also lists who may approve a
signing request.

## 3. Verify the source

For builds from source (Flatpak, distribution packages), work from the tag,
not from a branch:

```bash
git clone --branch v<version> https://github.com/aTrainTranscription/aTrain
```

The tag archive `aTrain-<version>-source.tar.gz` is listed in `checksums.txt`,
so a downloaded tarball can be checked the same way as the installer.

## 4. Read the SBOM

`aTrain-<version>-windows.cdx.json` lists every Python package in the Windows
build with version and licence, plus the bundled ML models and their
Hugging Face revisions. Use it to scan for known vulnerabilities, for example
with `pip-audit`, `grype`, or `trivy sbom`, or to review licences before
redistribution.

## Reporting a mismatch

If a checksum or signature does not match what the release publishes, do not
distribute the file. Report it to the maintainers as described in
[SECURITY.md](../SECURITY.md).
