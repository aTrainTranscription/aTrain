# Code signing policy

Free code signing provided by [SignPath.io](https://signpath.io), certificate by [SignPath Foundation](https://signpath.org).

## What is signed

- **Windows MSIX from GitHub releases and Zenodo**: Authenticode-signed through
  SignPath.io with a certificate issued to SignPath Foundation, from v1.5.0 on.
  Earlier builds are unsigned.
- **macOS DMG from Zenodo**: the app and the disk image are signed with the
  Apple Developer ID Application certificate
  `Developer ID Application: Juergen Fleiss (ZC3J2Z2Q96)`, with hardened runtime, and
  notarized by Apple; the ticket is stapled to both. Earlier macOS builds are
  not notarized.
- **Microsoft Store**: packages are signed by Microsoft as part of Store
  publishing.
- **Flathub**: Flatpak packages carry no Authenticode signature; integrity is
  handled by Flathub's build and distribution infrastructure.

Signing runs in the release workflow (`.github/workflows/release.yml`) on a
tagged commit. Every Windows signing request is approved manually by an
approver before the certificate is applied. macOS signing runs in the same
workflow without a manual approval. It uses the repository secrets
`MACOS_CERTIFICATE_P12`, `MACOS_CERTIFICATE_PASSWORD` and
`MACOS_SIGNING_IDENTITY` (certificate) and `APPLE_API_KEY_P8`,
`APPLE_API_KEY_ID` and `APPLE_API_ISSUER_ID` (App Store Connect API key, role
Developer, for notarization), which only repository admins can change. The
certificate expires after five years and the API key can be revoked; either
shows up as a failing signing step in the release workflow. If they leak,
revoke both at Apple.

macOS publishing requires successful signing, notarization, and verification
of the DMG. If signing secrets are missing, the workflow still builds an
ad-hoc-signed DMG for testing and keeps it as a workflow artifact, but the
macOS publishing job for a tagged release fails before uploading anything
to GitHub or Zenodo.

How to check a downloaded release against the published checksums and this
signature: [Verifying a release](verifying-releases.md).

## Roles

- **Authors** - trusted to change the source code without additional review:
  [@JuergenFleiss](https://github.com/JuergenFleiss),
  [@ArminHaberl](https://github.com/ArminHaberl)
  ([merge2main team](https://github.com/orgs/aTrainTranscription/teams/merge2main)).
- **Reviewers** - every change proposed by others is reviewed by one of them:
  [@JuergenFleiss](https://github.com/JuergenFleiss),
  [@ArminHaberl](https://github.com/ArminHaberl),
  [@gerardo-navarro](https://github.com/gerardo-navarro),
  [@BW-Projects](https://github.com/BW-Projects)
  ([reviewers team](https://github.com/orgs/aTrainTranscription/teams/reviewers)).
- **Approvers** - approve each signing request:
  [@JuergenFleiss](https://github.com/JuergenFleiss).

## Privacy

aTrain processes recordings and transcripts locally and does not upload them.
The application transfers data to other systems only in these cases:

- Machine-learning models that are not included in your installation package
  are downloaded from [Hugging Face](https://huggingface.co/) when a model is
  first used, or when you download one on the Models page. Hugging Face's
  [privacy policy](https://huggingface.co/privacy) applies to those requests.
- Installations from the Microsoft Store are subject to Microsoft's Store
  telemetry, see the
  [Microsoft privacy statement](https://privacy.microsoft.com/privacystatement).

aTrain itself sends no usage data or telemetry. The full privacy policy
(German) is published by the University of Graz:
<https://business-analytics.uni-graz.at/en/research/atrain/privacy-policy/>
