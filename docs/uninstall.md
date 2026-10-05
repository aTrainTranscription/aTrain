# Uninstalling aTrain

How to remove aTrain and, separately, the data it has written. Uninstalling
the application never deletes transcripts: they live outside the application
and stay there until you remove them. The last section lists where the
personal data is.

This page covers the two official channels, the MSIX package on Windows and
the Flatpak on Linux. Each section starts with the normal user path and
continues with the commands for administrators.

## Windows (MSIX, Store or downloaded package)

| Location                                            | Contents                                                | Removed by uninstall | Personal data |
| --------------------------------------------------- | ------------------------------------------------------- | -------------------- | ------------- |
| `C:\Program Files\WindowsApps\<PackageFullName>\`   | the application, read-only                              | yes                  | no            |
| `%LOCALAPPDATA%\Packages\<PackageFamilyName>\`      | package-private data Windows keeps for every packaged app, including its temp folder | yes (signed-out users: at their next sign-in) | no |
| Start menu entry "aTrain"                           |                                                         | yes                  |               |
| `%USERPROFILE%\Documents\aTrain\models\`            | downloaded models, several GB                           | no                   | no            |
| `%USERPROFILE%\Documents\aTrain\transcriptions\`    | one folder per transcription: text, `metadata.txt`, `log.txt` | no             | **yes**       |
| `%USERPROFILE%\Documents\aTrain\settings\`          | the options last used in the app                        | no                   | no            |

`Documents\aTrain` moves to the path in the `ATRAIN_USER_DIR` environment
variable when that is set. aTrain writes nothing under `%LOCALAPPDATA%\aTrain`
and keeps no global Hugging Face cache: model downloads go straight into the
model folder, including the download bookkeeping in its `.cache` subfolder.

Two package identities exist: the Microsoft Store
build is `26987BusinessAnalyticsand.aTrain`, the packages published on GitHub
and Zenodo are `aTrainTranscription.aTrain`. Both can be installed side by
side, so check for both.

**As a user:** `Settings > Apps > Installed apps`, find aTrain, `Uninstall`. Or
right-click the Start menu entry and choose Uninstall. Windows removes the
package and its private data; `Documents\aTrain` stays.

**For the signed-in user only**, from PowerShell:

```powershell
$ids = "aTrainTranscription.aTrain", "26987BusinessAnalyticsand.aTrain"
foreach ($id in $ids) { Get-AppxPackage -Name $id | Remove-AppxPackage }
```

**For all users and the machine-wide provisioning** (administrator):

```powershell
$ids = "aTrainTranscription.aTrain", "26987BusinessAnalyticsand.aTrain"
foreach ($id in $ids) {
  Get-AppxProvisionedPackage -Online | Where-Object DisplayName -eq $id |
    ForEach-Object { Remove-AppxProvisionedPackage -Online -PackageName $_.PackageName }
  Get-AppxPackage -AllUsers -Name $id | Remove-AppxPackage -AllUsers
}
```

Without the provisioning step, users get the package back at their next
sign-in. Run it as administrator or as `SYSTEM`.

**Verify** (both commands print nothing when the package is gone):

```powershell
$ids = "aTrainTranscription.aTrain", "26987BusinessAnalyticsand.aTrain"
foreach ($id in $ids) {
  Get-AppxProvisionedPackage -Online | Where-Object DisplayName -eq $id
  Get-AppxPackage -AllUsers -Name $id
}
```

**Remove the user data.** This deletes all transcripts of that profile:

```powershell
Remove-Item -Recurse -Force "$env:USERPROFILE\Documents\aTrain"
```

When decommissioning a shared machine, every profile has its own folder:

```powershell
Get-ChildItem C:\Users -Directory | ForEach-Object {
  $d = Join-Path $_.FullName "Documents\aTrain"
  if (Test-Path $d) { Remove-Item -Recurse -Force $d }
}
```

With folder redirection, `Documents` is on a network share and the folder
lives there.

## Linux (Flatpak)

| Location                                                      | Contents                          | Removed by uninstall | Personal data |
| ------------------------------------------------------------- | --------------------------------- | -------------------- | ------------- |
| `/var/lib/flatpak/app/io.github.juergenfleiss.aTrain/` (or `~/.local/share/flatpak/app/...` for a user install) | the application | yes | no |
| Application menu entry                                        |                                   | yes                  |               |
| `~/.var/app/io.github.juergenfleiss.aTrain/data/models/`      | downloaded models, several GB     | with `--delete-data` | no            |
| `~/.var/app/io.github.juergenfleiss.aTrain/config/aTrain/`    | the options last used in the app  | with `--delete-data` | no            |
| `~/.var/app/io.github.juergenfleiss.aTrain/cache/`            | library caches and temp files; harmless | with `--delete-data` | no      |
| `~/Documents/aTrain/transcriptions/`                          | one folder per transcription: text, `metadata.txt`, `log.txt` | no | **yes** |

The sandbox has access to `~/Documents` only, which is why the transcripts sit
outside `~/.var/app`. Starting the app with `--transcription-dir <path>` moves
the transcriptions to that path; models and settings stay in the sandbox.

**As a user:** remove aTrain in your software center, or:

```bash
flatpak uninstall --delete-data io.github.juergenfleiss.aTrain
flatpak uninstall --unused        # runtimes no other app needs any more
```

Leave out `--delete-data` to keep models and settings for a later reinstall.

**Remove the transcripts.** This deletes all of them:

```bash
rm -rf ~/Documents/aTrain
```

## What the data contains

- **Transcriptions** are personal data: the text of the recording, speaker
  labels, `metadata.txt` with the original file name and the options used, and
  `log.txt`. The recordings themselves are not stored; aTrain reads them from
  where you selected them. Delete the `transcriptions` folder when a machine is
  decommissioned or a user leaves. From inside the app, the **Delete All**
  button in the Archive tab does the same for the current profile; models and
  settings stay.
- **Models** are large but contain no personal data. They can also be removed
  one by one on the Models page of the app.
- **Settings** hold the options last used in the app.

Secure erasure and encryption at rest are matters of the operating system, not
of aTrain.

To keep the data and only remove the application, skip the data commands
above. A later installation finds the folder again.

## Checklist

After a complete removal:

- [ ] No package is registered (`Get-AppxPackage -AllUsers`, `flatpak list`).
- [ ] No provisioning entry on Windows (`Get-AppxProvisionedPackage -Online`).
- [ ] No Start menu or application menu entry.
- [ ] No `Documents\aTrain` (or the `ATRAIN_USER_DIR` path) in any profile.
