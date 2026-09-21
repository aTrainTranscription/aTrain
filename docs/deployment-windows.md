# Deploying aTrain in managed Windows environments

For IT departments rolling aTrain out to managed machines. End users looking
for a normal installation should read [Installation](installation.md) instead.

## Requirements

- Windows 10 or Windows 11 (64-bit).
- **Sideloading must not be blocked by policy.** In our tests this was the only
setting that actually prevented installation:
`Computer Configuration > Administrative Templates > Windows Components > App Package Deployment > Allow all trusted apps to install`.
  - When sideloading is disabled, the install blocks with *"a Windows developer license or a sideload-enabled system is required"*.
  - Sideloading has been the default since Windows 10 version 2004, so a block is a deliberate policy.
- Administrator rights, or execution as `SYSTEM`, for machine-wide
provisioning.
- Outbound access to `huggingface.co` for the first model download, unless a
build with bundled models is used. Machines without internet access need the
bundled build.
- Write access to `%USERPROFILE%\Documents\aTrain\` or to the path set via the
`ATRAIN_USER_DIR` environment variable. With folder redirection the models
land on the network share; plan for several GB per user.

aTrain ships as an **MSIX** package, which affects how it is managed:

- **There is no uninstall entry in the registry.** Detection and verification
must use the `Get-AppxPackage` and `Get-AppxProvisionedPackage` cmdlets.
- **Installation is always tied to a user account.** Machine-wide, the package
is *provisioned*; each user receives it at their next sign-in, not
immediately. Plan rollouts accordingly.

## Obtaining the package

The installer is published on Zenodo. The GitHub release carries the checksums and the CycloneDX SBOM. Appendix A shows how to resolve the current version programmatically.

```powershell
Get-FileHash .\aTrain-<version>.msix -Algorithm SHA256
Get-AuthenticodeSignature .\aTrain-<version>.msix | Format-List Status, SignerCertificate
```

The expected hash is listed in `checksums.txt` on the GitHub release; the copy in the Zenodo record is identical. [Verifying a release](verifying-releases.md) covers the signature and the SBOM in more detail.

## Installing

Machine-wide, the path for software distribution:

```powershell
Add-AppxProvisionedPackage -Online -PackagePath .\aTrain-<version>.msix -SkipLicense
```

Or the equivalent DISM call, for tools that prefer an executable with an exit code:

```
DISM /Online /Add-ProvisionedAppxPackage /PackagePath:aTrain-<version>.msix /SkipLicense
```

`-SkipLicense` is required because the package carries no Store license file;
it has nothing to do with software licensing. No reboot is needed.

For a single user, without administrator rights:

```powershell
Add-AppxPackage -Path .\aTrain-<version>.msix
```

After provisioning, users who are already signed in will not see the
application until their next sign-in, when Windows registers the package for
their profile. That first sign-in takes noticeably longer. A newly created
account picks the package up automatically.

## Verifying a deployment

```powershell
# provisioned machine-wide (authoritative right after a rollout):
Get-AppxProvisionedPackage -Online |
  Where-Object DisplayName -eq "aTrainTranscription.aTrain" |
  Select-Object DisplayName, Version

# registered for the signed-in user:
Get-AppxPackage -Name aTrainTranscription.aTrain
```

Use the first query to confirm a rollout. The second reports nothing until the
user signs in again, which makes a successful deployment look like a failure.

Package versions always have **four components**, and suffixes are dropped. Comparing against `"1.5.0"` fails:

```powershell
[version](Get-AppxProvisionedPackage -Online |
  Where-Object DisplayName -eq "aTrainTranscription.aTrain").Version -ge [version]"1.5.0.0"
```

## Replacing an installation from the Microsoft Store

The Store build and the packages published here use different package
identities (`26987BusinessAnalyticsand.aTrain` and
`aTrainTranscription.aTrain`). Windows treats them as two separate
applications: they do not replace one another, and users end up with two Start
menu entries, both named "aTrain". Remove the Store version explicitly:

```powershell
$p = Get-AppxProvisionedPackage -Online |
     Where-Object DisplayName -eq "26987BusinessAnalyticsand.aTrain"
if ($p) { Remove-AppxProvisionedPackage -Online -PackageName $p.PackageName }
Get-AppxPackage -AllUsers -Name 26987BusinessAnalyticsand.aTrain | Remove-AppxPackage -AllUsers
```

User data under `Documents\aTrain`, including existing transcripts, is kept.

Updating within the same identity needs no uninstall: a package with a higher
version installs over the existing one. Equal or lower versions are rejected
with `0x80073CFB`.

Prerelease builds carry the same four-part version as the final release they
precede: `1.5.0-rc3` and `1.5.0` are both `1.5.0.0` to Windows. A machine that has a prerelease installed therefore cannot be updated to the final release in place; remove the prerelease first.

## Common errors

| Message                                                                | Cause                                          | Fix                                                                                   |
| ---------------------------------------------------------------------- | ---------------------------------------------- | ------------------------------------------------------------------------------------- |
| "a Windows developer license or a sideload-enabled system is required" | sideloading disabled by policy                 | see Requirements                                                                      |
| `0x800B0109` root certificate not trusted                              | signing certificate not trusted on the machine | only affects test-signed builds; released packages use a publicly trusted certificate |
| `0x80073CFB` already installed                                         | same version already present                   | use a higher version or remove first                                                  |
| verification reports "not installed" right after a rollout             | registration happens at sign-in                | query `Get-AppxProvisionedPackage`                                                    |

More detail is in the event log under `Applications and Services Logs > Microsoft > Windows > AppXDeployment-Server`.

## Appendix A: resolving the current version

GitHub provides the version number and the checksums, Zenodo the installer.

```powershell
$rel  = Invoke-RestMethod "https://api.github.com/repos/aTrainTranscription/aTrain/releases/latest" -UseBasicParsing
$ver  = $rel.tag_name.TrimStart("v")
Invoke-WebRequest "https://github.com/aTrainTranscription/aTrain/releases/download/v$ver/checksums.txt" -OutFile checksums.txt

$hits = (Invoke-RestMethod "https://zenodo.org/api/records?q=conceptrecid:22018704&all_versions=true&size=50" `
         -UseBasicParsing -Headers @{Accept="application/json"}).hits.hits
$msix = ($hits | Where-Object { $_.metadata.version -eq $ver }).files |
        Where-Object { $_.key -like "*.msix" }

curl.exe -L -C - -o "aTrain-$ver.msix" $msix.links.self
(Get-FileHash "aTrain-$ver.msix" -Algorithm SHA256).Hash
```

- `releases/latest` skips prereleases, which is what a production rollout
wants.
- The `Accept: application/json` header is required for the Zenodo query;
without it the service answers with HTTP 400.
- `22018704` is aTrain's Zenodo concept ID and stays the same across versions.

