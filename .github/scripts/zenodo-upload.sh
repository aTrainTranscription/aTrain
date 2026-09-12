#!/usr/bin/env bash
#
# Upload release artifacts to Zenodo as a DRAFT deposition. Never publishes -
# a maintainer reviews and publishes in the Zenodo UI, which also submits the
# record to the community.
#
# Usage:
#   zenodo-upload.sh <version> <file>...
#
# One invocation per release: it clears the draft's files before uploading,
# so a second invocation for the same version would remove what the first one
# uploaded. Once more artifact types exist (EXE #221, Flatpak), collect them
# in a single publish job and pass them all to one invocation, rather than
# calling this once per build job.
#
# Environment:
#   ZENODO_TOKEN        (required) personal access token, scope deposit:write
#   ZENODO_BASE         (required) https://zenodo.org or https://sandbox.zenodo.org
#   GITHUB_REPOSITORY   (required) owner/name, used for the release back-link
#   ZENODO_CONCEPT_ID   (optional) concept id of the published record; when set,
#                       the upload is added as a new version of it, otherwise a
#                       new concept is started
#   ZENODO_METADATA     (optional) metadata file, defaults to .zenodo.json
#
# Example (rehearse against the sandbox):
#   ZENODO_TOKEN=... ZENODO_BASE=https://sandbox.zenodo.org \
#   GITHUB_REPOSITORY=aTrainTranscription/aTrain \
#     .github/scripts/zenodo-upload.sh 1.5.0 aTrain-1.5.0.msix checksums.txt
#
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: zenodo-upload.sh <version> <file>...

Uploads the files to Zenodo as a draft deposition. Never publishes.

Environment:
  ZENODO_TOKEN       (required) token with scope deposit:write
  ZENODO_BASE        (required) https://zenodo.org | https://sandbox.zenodo.org
  GITHUB_REPOSITORY  (required) owner/name, for the release back-link
  ZENODO_CONCEPT_ID  (optional) concept id; when set, adds a new version to it
  ZENODO_METADATA    (optional) metadata file, default .zenodo.json
USAGE
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then usage; exit 0; fi
if [[ $# -lt 2 ]]; then usage >&2; exit 2; fi

version="$1"; shift
files=("$@")
metadata_file="${ZENODO_METADATA:-.zenodo.json}"

for var in ZENODO_TOKEN ZENODO_BASE GITHUB_REPOSITORY; do
  if [[ -z "${!var:-}" ]]; then
    echo "error: $var is not set - see $0 --help" >&2
    exit 2
  fi
done
[[ -f "$metadata_file" ]] || { echo "error: $metadata_file not found" >&2; exit 2; }
for file in "${files[@]}"; do
  [[ -f "$file" ]] || { echo "error: $file not found" >&2; exit 2; }
done

rendered_metadata="$(mktemp)"
trap 'rm -f "$rendered_metadata"' EXIT

# jq on Windows emits CRLF; the CR survives command substitution when the
# output has several lines, and would end up inside request URLs.
jqr() { jq -r "$@" | tr -d '\r'; }

api() {  # api <method> <path-or-url> [curl args...]
  local method="$1" url="$2"; shift 2
  [[ "$url" == http* ]] || url="$ZENODO_BASE/api$url"
  curl -sS --fail-with-body -X "$method" \
    -H "Authorization: Bearer $ZENODO_TOKEN" "$@" "$url"
}

if [[ -n "${ZENODO_CONCEPT_ID:-}" ]]; then
  # An unpublished draft blocks `newversion`, so reuse it - this release
  # supersedes it anyway. `submitted == false` excludes the edit draft of an
  # already published record, whose files cannot be deleted (403).
  pending="$(api GET "/deposit/depositions?q=conceptrecid:$ZENODO_CONCEPT_ID&status=draft" \
    | jqr '[.[] | select(.submitted == false)][0].id // empty')"
  if [[ -n "$pending" ]]; then
    echo "::warning::Zenodo draft $pending was still unpublished - reusing it for $version."
    deposition="$(api GET "/deposit/depositions/$pending")"
  else
    # `newversion` needs the latest published version's id;
    # /records/<concept> redirects there.
    # `if cmd` rather than a plain assignment: under `set -e` a failing curl
    # would abort before the check below could report anything useful.
    latest=""
    if concept_record="$(curl -sSL --fail-with-body "$ZENODO_BASE/api/records/$ZENODO_CONCEPT_ID" 2>/dev/null)"; then
      latest="$(jqr '.id // empty' <<<"$concept_record")"
    fi
    if [[ -z "$latest" ]]; then
      echo "::error::ZENODO_CONCEPT_ID=$ZENODO_CONCEPT_ID does not resolve to a published record."
      exit 1
    fi
    echo "adding a new version to concept $ZENODO_CONCEPT_ID (latest published: $latest)"
    draft_url="$(api POST "/deposit/depositions/$latest/actions/newversion" | jqr .links.latest_draft)"
    deposition="$(api GET "$draft_url")"
  fi
else
  echo "no ZENODO_CONCEPT_ID set - creating the first record of a new concept"
  deposition="$(api POST /deposit/depositions -H 'Content-Type: application/json' -d '{}')"
fi

id="$(jqr .id <<<"$deposition")"
bucket="$(jqr .links.bucket <<<"$deposition")"

# Drafts carry the previous version's files.
for file_id in $(jqr '.files[]?.id' <<<"$deposition"); do
  api DELETE "/deposit/depositions/$id/files/$file_id" -o /dev/null
done

# Bucket API: 50 GB per file. The legacy files endpoint caps at 100 MB.
for file in "${files[@]}"; do
  echo "uploading $file ($(du -h "$file" | cut -f1))"
  api PUT "$bucket/$(basename "$file")" --upload-file "$file" -o /dev/null \
    -w "  http=%{http_code} in %{time_total}s\n"
done

# Only the per-release bits are added here; the record metadata itself is
# maintained in .zenodo.json, next to CITATION.cff.
jq --arg v "$version" --arg repo "$GITHUB_REPOSITORY" '{metadata: (. + {
  version: $v,
  related_identifiers: (.related_identifiers + [{
    identifier: "https://github.com/\($repo)/releases/tag/v\($v)",
    relation: "isSupplementTo", scheme: "url"}])
})}' "$metadata_file" > "$rendered_metadata"
api PUT "/deposit/depositions/$id" -H 'Content-Type: application/json' \
  -d @"$rendered_metadata" -o /dev/null -w "metadata http=%{http_code}\n"

echo "::notice::Zenodo draft ready for review: $ZENODO_BASE/uploads/$id"
if [[ -z "${ZENODO_CONCEPT_ID:-}" ]]; then
  echo "::notice::First record - after publishing it, set the repo variable ZENODO_CONCEPT_ID to its concept id so later releases attach as new versions."
fi
