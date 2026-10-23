#!/usr/bin/env bash
# Notarize a signed macOS app bundle or DMG and staple the ticket to it.
#
# Usage: macos-notarize.sh <aTrain.app | file.dmg> <notary-log.json>
#
# Needs APPLE_API_KEY_P8 (the App Store Connect API key, base64), APPLE_API_KEY_ID
# and APPLE_API_ISSUER_ID. Writes Apple's notary log to the second argument,
# also when notarization fails, and exits non-zero unless it was accepted.
set -euo pipefail

target="$1"
log="$2"

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT
printf '%s' "$APPLE_API_KEY_P8" | base64 --decode > "$workdir/AuthKey.p8"
auth=(--key "$workdir/AuthKey.p8" --key-id "$APPLE_API_KEY_ID" --issuer "$APPLE_API_ISSUER_ID")

upload="$target"
if [[ -d "$target" ]]; then
  # notarytool takes a zip, dmg or pkg, not a bundle.
  upload="$workdir/$(basename "$target").zip"
  ditto -c -k --keepParent "$target" "$upload"
fi

# Usually minutes, at times an hour.
xcrun notarytool submit "$upload" "${auth[@]}" --wait --timeout 1h --output-format json \
  > "$workdir/submit.json" || true
cat "$workdir/submit.json"
id="$(jq -r '.id // empty' "$workdir/submit.json" 2>/dev/null || true)"
status="$(jq -r '.status // empty' "$workdir/submit.json" 2>/dev/null || true)"
if [[ -n "$id" ]]; then
  xcrun notarytool log "$id" "${auth[@]}" "$log" || true
fi
if [[ "$status" != "Accepted" ]]; then
  echo "::error::Notarization of $target: ${status:-no result}"
  [[ -f "$log" ]] && cat "$log"
  exit 1
fi

xcrun stapler staple "$target"
xcrun stapler validate "$target"
