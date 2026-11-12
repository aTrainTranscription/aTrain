#!/usr/bin/env bash
#
# Upload release artifacts to Zenodo as a DRAFT deposition. Never publishes -
# a maintainer reviews and publishes in the Zenodo UI, which also submits the
# record to the community.
#
# Usage:
#   zenodo-upload.sh <version> <file>...
#
# The first invocation per release clears the draft's files before uploading,
# so a second plain invocation for the same version would remove what the
# first one uploaded. Further platforms (macOS) are added to the same draft
# with ZENODO_APPEND=1, which only replaces files of the same name.
#
# Environment:
#   ZENODO_TOKEN        (required) personal access token, scope deposit:write
#   ZENODO_BASE         (required) https://zenodo.org or https://sandbox.zenodo.org
#   GITHUB_REPOSITORY   (required) owner/name, used for the release back-link
#   ZENODO_CONCEPT_ID   (optional) concept id of the published record; when set,
#                       the upload is added as a new version of it, otherwise a
#                       new concept is started
#   ZENODO_METADATA     (optional) metadata file, defaults to .zenodo.json
#   ZENODO_APPEND       (optional) 1 = add the files to the unpublished draft
#                       of <version> instead of starting one; fails if there
#                       is none. Requires ZENODO_DRAFT_ID or ZENODO_CONCEPT_ID
#   ZENODO_DRAFT_ID     (optional) explicit draft id for ZENODO_APPEND=1;
#                       takes precedence over looking up ZENODO_CONCEPT_ID
#   GITHUB_OUTPUT       (optional) receives draft-id after a successful upload
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
  ZENODO_APPEND      (optional) 1 = add the files to the existing draft of
                     <version>, keeping its other files
  ZENODO_DRAFT_ID    (optional) draft id for append; otherwise looks up the
                     draft using ZENODO_CONCEPT_ID
  GITHUB_OUTPUT      (optional) receives draft-id after a successful upload
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
if [[ "${ZENODO_APPEND:-}" == 1 && -z "${ZENODO_DRAFT_ID:-}" && -z "${ZENODO_CONCEPT_ID:-}" ]]; then
  echo "error: ZENODO_APPEND=1 needs ZENODO_DRAFT_ID or ZENODO_CONCEPT_ID to find the draft" >&2
  exit 2
fi
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

pending="${ZENODO_DRAFT_ID:-}"
if [[ -n "${ZENODO_CONCEPT_ID:-}" && ( "${ZENODO_APPEND:-}" != 1 || -z "$pending" ) ]]; then
  # An unpublished draft blocks `newversion`, so reuse it - this release
  # supersedes it anyway. `submitted == false` excludes the edit draft of an
  # already published record, whose files cannot be deleted (403).
  pending="$(api GET "/deposit/depositions?q=conceptrecid:$ZENODO_CONCEPT_ID&status=draft" \
    | jqr '[.[] | select(.submitted == false)][0].id // empty')"
fi
if [[ "${ZENODO_APPEND:-}" == 1 ]]; then
  # Use the first upload's draft, including a new concept's first release.
  # Check its state and version before deleting or uploading any files.
  deposition=""
  [[ -n "$pending" ]] && deposition="$(api GET "/deposit/depositions/$pending")"
  if [[ -z "$deposition" ]] || ! jq -e --arg v "$version" \
      '.submitted == false and .metadata.version == $v' <<<"$deposition" > /dev/null; then
    echo "::error::No unpublished Zenodo draft for $version to append to."
    exit 1
  fi
  echo "appending to Zenodo draft $pending"
elif [[ -n "${ZENODO_CONCEPT_ID:-}" ]]; then
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

# Drafts carry the previous version's files. In append mode only same-named
# files go, so a re-run replaces its own uploads and keeps the other platforms'.
names="$(printf '%s\n' "${files[@]##*/}" | jq -R . | jq -s .)"
for file_id in $(jqr --argjson names "$names" --arg append "${ZENODO_APPEND:-}" \
    '.files[]? | select($append != "1" or (.filename | IN($names[]))) | .id' <<<"$deposition"); do
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

if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  printf 'draft-id=%s\n' "$id" >> "$GITHUB_OUTPUT"
fi
echo "::notice::Zenodo draft ready for review: $ZENODO_BASE/uploads/$id"
if [[ -z "${ZENODO_CONCEPT_ID:-}" && "${ZENODO_APPEND:-}" != 1 ]]; then
  echo "::notice::First record - after publishing it, set the repo variable ZENODO_CONCEPT_ID to its concept id so later releases attach as new versions."
fi
