# MSIX packaging

Files that drive the Windows MSIX build in `.github/workflows/release.yml`.

## `AppxManifest.xml.template`

Template for the package manifest. The release workflow substitutes
`{{VERSION}}` (from the tag, e.g. `1.5.0`) and `{{PUBLISHER}}` (from the
`SIGNPATH_PUBLISHER` repository variable) and writes the concrete
`AppxManifest.xml` into the PyInstaller output directory before packing
with `makeappx.exe`.

- `Publisher` has to match the signing certificate's subject exactly, or
  signing fails (#211). Builds that skip signing get the placeholder
  `CN=aTrain unsigned build`; an unsigned MSIX does not install by
  double-click on Windows.
- MSIX is packed with `makeappx.exe pack /d dist/aTrain /p aTrain-<version>.msix`.
- If distributing via MS Store, the identity (`Name`, `Publisher`) must
  match what's registered in Microsoft Partner Center.

## Assets

`makeappx.exe` requires the PNG assets referenced by the manifest
(`StoreLogo.png`, `Square150x150Logo.png`, `Square44x44Logo.png`,
`Wide310x150Logo.png`). `packaging/msix/Assets/` holds the aTrain brand
assets, including the scale and targetsize variants that makeappx picks
up by name. The folder is copied into the PyInstaller output during
packaging.
