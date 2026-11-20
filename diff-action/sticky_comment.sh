#!/usr/bin/env bash
# Upsert one sticky PR comment identified by an HTML marker.
# Usage: sticky_comment.sh <body-file>
#
# Required env:
#   GITHUB_TOKEN (or INPUT_GITHUB_TOKEN)
#   GITHUB_REPOSITORY  (owner/repo)
#   PR_NUMBER
# Optional env:
#   GITHUB_API_URL     (default https://api.github.com)
#   STICKY_MARKER      (default <!-- apiome-diff-action -->)
#   STICKY_SECTION     (GVM-3.4) a section name such as `diff` or `fixes`: the body replaces only
#                      that section of the one sticky comment, between
#                      `<!-- apiome-diff-action:<name> -->` and `<!-- /apiome-diff-action:<name> -->`,
#                      so the diff and the suggested fixes update independently. A new section is
#                      appended; a comment written before sections existed is replaced wholesale.
#                      Unset: the body replaces the whole comment (the CTG-2.2 behaviour).
#   CURL_BIN           (default curl) — override in tests

set -euo pipefail

BODY_FILE="${1:?body file required}"
MARKER="${STICKY_MARKER:-<!-- apiome-diff-action -->}"
API_URL="${GITHUB_API_URL:-https://api.github.com}"
TOKEN="${GITHUB_TOKEN:-${INPUT_GITHUB_TOKEN:-}}"
CURL_BIN="${CURL_BIN:-curl}"

if [[ -z "${TOKEN}" ]]; then
  echo "sticky_comment: missing GITHUB_TOKEN; skipping comment" >&2
  exit 0
fi
if [[ -z "${GITHUB_REPOSITORY:-}" ]]; then
  echo "sticky_comment: missing GITHUB_REPOSITORY; skipping comment" >&2
  exit 0
fi
if [[ -z "${PR_NUMBER:-}" ]]; then
  echo "sticky_comment: missing PR_NUMBER; skipping comment" >&2
  exit 0
fi
if [[ ! -f "${BODY_FILE}" ]]; then
  echo "sticky_comment: body file not found: ${BODY_FILE}" >&2
  exit 1
fi

OWNER="${GITHUB_REPOSITORY%%/*}"
REPO="${GITHUB_REPOSITORY#*/}"
COMMENTS_URL="${API_URL}/repos/${OWNER}/${REPO}/issues/${PR_NUMBER}/comments"

BODY="$(cat "${BODY_FILE}")"
SECTION="${STICKY_SECTION:-}"

EXISTING_ID=""
# Paginate lightly: first 100 comments is enough for sticky upsert.
LIST_JSON="$("${CURL_BIN}" -sS \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  "${COMMENTS_URL}?per_page=100")"

EXISTING_ID="$(printf '%s' "${LIST_JSON}" | jq -r \
  --arg marker "${MARKER}" \
  '[.[] | select(.body | type == "string" and contains($marker)) | .id] | first // empty')"

if [[ -n "${SECTION}" ]]; then
  EXISTING_BODY="$(printf '%s' "${LIST_JSON}" | jq -r \
    --arg marker "${MARKER}" \
    '[.[] | select(.body | type == "string" and contains($marker)) | .body] | first // ""')"
  # Replace this section in place, append it after the others, or start the comment with it.
  BODY="$(jq -rn \
    --arg old "${EXISTING_BODY}" \
    --arg marker "${MARKER}" \
    --arg start "<!-- apiome-diff-action:${SECTION} -->" \
    --arg end "<!-- /apiome-diff-action:${SECTION} -->" \
    --arg content "${BODY}" '
    ($start + "\n" + $content + "\n" + $end) as $block
    | if ($old | contains($start)) and ($old | contains($end)) then
        ($old | split($start)) as $a
        | ($a[1:] | join($start) | split($end)) as $b
        | $a[0] + $block + ($b[1:] | join($end))
      elif ($old | contains("<!-- apiome-diff-action:")) then
        $old + "\n\n" + $block
      else
        $marker + "\n" + $block
      end')"
fi

# Ensure the marker is present so later runs can find this comment.
if [[ "${BODY}" != *"${MARKER}"* ]]; then
  BODY="${MARKER}
${BODY}"
fi

# Build JSON payload without requiring python (jq --rawfile / --arg).
PAYLOAD="$(jq -n --arg body "${BODY}" '{body: $body}')"

http_ok() {
  local code="$1"
  local expect="$2"
  if [[ "${code}" != "${expect}" ]]; then
    echo "sticky_comment: unexpected HTTP ${code} (expected ${expect})" >&2
    return 1
  fi
  return 0
}

if [[ -n "${EXISTING_ID}" ]]; then
  echo "sticky_comment: updating comment ${EXISTING_ID}" >&2
  STATUS="$("${CURL_BIN}" -sS -o /tmp/apiome-sticky-resp.json -w "%{http_code}" \
    -X PATCH \
    -H "Accept: application/vnd.github+json" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    -H "Content-Type: application/json" \
    -d "${PAYLOAD}" \
    "${API_URL}/repos/${OWNER}/${REPO}/issues/comments/${EXISTING_ID}")"
  http_ok "${STATUS}" "200"
  echo "sticky_comment: updated" >&2
else
  echo "sticky_comment: creating comment on PR #${PR_NUMBER}" >&2
  STATUS="$("${CURL_BIN}" -sS -o /tmp/apiome-sticky-resp.json -w "%{http_code}" \
    -X POST \
    -H "Accept: application/vnd.github+json" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    -H "Content-Type: application/json" \
    -d "${PAYLOAD}" \
    "${COMMENTS_URL}")"
  http_ok "${STATUS}" "201"
  echo "sticky_comment: created" >&2
fi
