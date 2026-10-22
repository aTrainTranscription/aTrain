# Installing models without Hugging Face access

aTrain downloads its models from Hugging Face. Some networks block that
download, or break it with a proxy. This page shows how to put the models in
place by hand, and how to make aTrain work behind a proxy that inspects TLS.

It is written for Windows. The folder layout is the same on Linux and macOS.

## Which models are needed

| Model               | Needed for                                   | Folder name         |
| ------------------- | -------------------------------------------- | ------------------- |
| `large-v3-turbo`    | transcription (the default model)            | `large-v3-turbo`    |
| `speaker-detection` | speaker detection, only when it is turned on | `speaker-detection` |

Any other model from the model list works the same way. Its repository,
revision and file list are in
[`aTrain_core/data/models.json`](../aTrain_core/data/models.json).

## Where the models go

Each model gets its own folder inside the models folder:

- **Windows (MSIX):** `Documents\aTrain\models\`. This is the real Documents
  folder, which may be redirected, for example to OneDrive. If
  `ATRAIN_USER_DIR` is set, it is `%ATRAIN_USER_DIR%\models\`.
- **Linux (Flatpak):** `~/.var/app/io.github.juergenfleiss.aTrain/data/models/`
- **Linux and macOS (from source):** `~/Documents/aTrain/models/`

## Downloading the files

### With PowerShell (recommended)

Run this on a machine that can reach `huggingface.co`. `Invoke-WebRequest`
uses the Windows proxy settings and the Windows certificate store, like the
browser does. It writes every file under its exact name and keeps the
subfolders.

```powershell
$ProgressPreference = 'SilentlyContinue'
$base = if ($env:ATRAIN_USER_DIR) { $env:ATRAIN_USER_DIR } else { Join-Path ([Environment]::GetFolderPath('MyDocuments')) "aTrain" }
$target = Join-Path $base "models"
$models = @{
  "large-v3-turbo" = @{
    repo = "aTrain-core/faster-whisper-large-v3-turbo"
    rev = "df99141c9f5db0615d025664cff8949373a69593"
    files = @(".gitattributes", "README.md", "config.json", "model.bin", "preprocessor_config.json", "tokenizer.json", "vocabulary.json")
  }
  "speaker-detection" = @{
    repo = "aTrain-core/speaker-detection"
    rev = "027e7a80b40a5e3e69cb83ccf901725b59a4063d"
    files = @(".gitattributes", "README.md", "config.yaml", "diarization.gif", "embedding/README.md", "embedding/pytorch_model.bin", "plda/README.md", "plda/plda.npz", "plda/xvec_transform.npz", "segmentation/pytorch_model.bin")
  }
}
foreach ($name in $models.Keys) {
  $m = $models[$name]
  foreach ($file in $m.files) {
    $path = Join-Path $target "$name\$($file -replace '/', '\')"
    New-Item -ItemType Directory -Force -Path (Split-Path $path) | Out-Null
    Write-Host "Downloading $name/$file"
    Invoke-WebRequest -Uri "https://huggingface.co/$($m.repo)/resolve/$($m.rev)/$file" -OutFile $path -ProxyUseDefaultCredentials
  }
}
Write-Host "Done. Models are in $target"
```

The revisions and file lists match `models.json` at the time of writing. If
your aTrain version pins other revisions, take the values from its
`models.json`.

When you download on a different machine, copy the model folders into the
models folder of the target machine afterwards.

### In the browser

Every file can be downloaded from
`https://huggingface.co/<repo>/resolve/<revision>/<file>`, for example
`https://huggingface.co/aTrain-core/faster-whisper-large-v3-turbo/resolve/df99141c9f5db0615d025664cff8949373a69593/model.bin`.
Two pitfalls:

- **The browser drops the leading dot.** `.gitattributes` is saved as
  `gitattributes`. Rename it back. In Explorer, type the name as
  `.gitattributes.` (with a trailing dot), or run
  `Rename-Item gitattributes .gitattributes`.
- **Files with the same name get a suffix.** `speaker-detection` has several
  `README.md` and `pytorch_model.bin` files in different subfolders. The
  browser saves the second one as `pytorch_model (1).bin`. Move each file into
  its subfolder right after downloading it.

## Checking the result

The models folder should look like this:

```
models\
├── large-v3-turbo\
│   ├── .gitattributes
│   ├── README.md
│   ├── config.json
│   ├── model.bin
│   ├── preprocessor_config.json
│   ├── tokenizer.json
│   └── vocabulary.json
└── speaker-detection\
    ├── .gitattributes
    ├── README.md
    ├── config.yaml
    ├── diarization.gif
    ├── embedding\
    │   ├── README.md
    │   └── pytorch_model.bin
    ├── plda\
    │   ├── README.md
    │   ├── plda.npz
    │   └── xvec_transform.npz
    └── segmentation\
        └── pytorch_model.bin
```

List what is there, including hidden files:

```powershell
Get-ChildItem (Join-Path ([Environment]::GetFolderPath('MyDocuments')) "aTrain\models") -Recurse -File -Force |
  Format-Table Length, FullName -AutoSize
```

To compare checksums, run `Get-FileHash` on a file and look up its expected
SHA-256 in `models.json`.

Then restart aTrain. With all files in place, aTrain does not contact Hugging
Face for these models.

## What aTrain does with incomplete folders

aTrain checks every model folder against the file list and checksums in
`models.json` before it uses the model:

- **A file is missing** (for example `gitattributes` without the dot): aTrain
  tries to download the model again. Without access to Hugging Face this fails
  with a network or certificate error.
- **The download is not possible and the folder is checked as it is** (for
  example with `HF_HUB_OFFLINE=1`): aTrain reports
  `Model '...' does not match its checksums and will be removed` and **deletes
  the model folder**. Put the files in place again before the next attempt.

`HF_HUB_OFFLINE` does not help with manually installed models. It only changes
which of the two errors you see.

## Proxies that inspect TLS

Some networks route HTTPS through a proxy that re-signs the traffic with an
internal root CA. Windows trusts that CA, so the browser works. aTrain then
fails with:

```
SSLCertVerificationError(1, '[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate')
```

aTrain versions that verify certificates against the Windows certificate store
need nothing else: once the root CA is in the store, downloads work.

Older versions use their own CA list. There you can point aTrain to a bundle
that contains the public CAs plus the internal root CA:

```powershell
# Public CAs (Mozilla list, the same source as aTrain's own list)
$bundle = Join-Path $env:USERPROFILE "atrain-ca-bundle.pem"
Invoke-WebRequest https://curl.se/ca/cacert.pem -OutFile $bundle

# Append the internal root CA from the Windows store (adjust the subject)
$ca = Get-ChildItem Cert:\LocalMachine\Root | Where-Object Subject -like "*Example Root CA*"
Add-Content $bundle "-----BEGIN CERTIFICATE-----"
Add-Content $bundle ([Convert]::ToBase64String($ca.RawData, 'InsertLineBreaks'))
Add-Content $bundle "-----END CERTIFICATE-----"

[Environment]::SetEnvironmentVariable("REQUESTS_CA_BUNDLE", $bundle, "User")
```

Sign out of Windows and back in, so that aTrain picks up the variable. The
bundle has to contain the public CAs too: the variable replaces aTrain's CA
list instead of adding to it.
