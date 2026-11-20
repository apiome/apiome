#!/usr/bin/env bash
# Post GitHub suggestion blocks for single-region lint fixes (GVM-3.4 / #5872).
# Usage: fix_suggestions.sh <suggestions.json>
#
# <suggestions.json> is `apiome lint suggest <spec> --format json` output. Each entry of its
# `suggestions` array is a ready fix whose change is one region of the spec file
# (startLine..endLine replaced by `replacement`). A suggestion is posted as a pull-request review
# comment — the only place GitHub renders a ```suggestion block the reviewer can accept in one
# click — and ONLY when that line range lies inside one hunk of the pull request's diff of the
# same file; every other fix stays a plain snippet in the sticky comment. Each review comment
# carries a `<!-- apiome-fix:<fixId> -->` marker, so a re-run never posts the same suggestion
# twice. Nothing is ever pushed to the branch.
#
# Prints the number of suggestions now on the pull request (posted by this run or an earlier one).
#
# Required env:
#   GITHUB_TOKEN, GITHUB_REPOSITORY (owner/repo), PR_NUMBER, HEAD_SHA (the PR head commit)
# Optional env:
#   GITHUB_API_URL  (default https://api.github.com)
#   CURL_BIN        (default curl) — override in tests

set -euo pipefail

SUGGESTIONS_FILE="${1:?suggestions file required}"
API_URL="${GITHUB_API_URL:-https://api.github.com}"
TOKEN="${GITHUB_TOKEN:-${INPUT_GITHUB_TOKEN:-}}"
CURL_BIN="${CURL_BIN:-curl}"

for name in TOKEN GITHUB_REPOSITORY PR_NUMBER HEAD_SHA; do
  if [[ -z "${!name:-}" ]]; then
    echo "fix_suggestions: missing ${name}; no suggestion blocks posted" >&2
    echo 0
    exit 0
  fi
done
if [[ ! -f "${SUGGESTIONS_FILE}" ]]; then
  echo "fix_suggestions: suggestions file not found: ${SUGGESTIONS_FILE}" >&2
  exit 1
fi

OWNER="${GITHUB_REPOSITORY%%/*}"
REPO="${GITHUB_REPOSITORY#*/}"
PULL_URL="${API_URL}/repos/${OWNER}/${REPO}/pulls/${PR_NUMBER}"

gh_get() {
  "${CURL_BIN}" -sS \
    -H "Accept: application/vnd.github+json" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    "$1"
}

# The spec path as the pull request names it (no leading ./).
SPEC_PATH="$(jq -r '.path // "" | sub("^\\./"; "")' "${SUGGESTIONS_FILE}")"

# The new-side line ranges of the PR's diff of that file: one [start, end] per hunk.
FILES_JSON="$(gh_get "${PULL_URL}/files?per_page=100")"
RANGES="$(printf '%s' "${FILES_JSON}" | jq -c --arg path "${SPEC_PATH}" '
  [ .[] | select(.filename == $path) | (.patch // "")
    | scan("@@ -[0-9]+(?:,[0-9]+)? \\+([0-9]+)(?:,([0-9]+))? @@")
    | (.[0] | tonumber) as $start
    | ((.[1] // "1") | tonumber) as $count
    | select($count > 0)
    | [$start, $start + $count - 1] ]')"

# Fix ids already suggested on this pull request (by an earlier run).
COMMENTS_JSON="$(gh_get "${PULL_URL}/comments?per_page=100")"
POSTED="$(printf '%s' "${COMMENTS_JSON}" | jq -c '
  [ .[] | (.body // "") | scan("<!-- apiome-fix:([^ ]+) -->") | .[0] ]')"

# The suggestions to post: inside one PR hunk, not posted before, and with a replacement that
# cannot close the ``` fence early.
TODO="$(jq -c --argjson ranges "${RANGES}" --argjson posted "${POSTED}" '
  [ .suggestions[]?
    | . as $s
    | select(any($ranges[]; .[0] <= $s.startLine and $s.endLine <= .[1]))
    | select(($s.replacement | contains("```")) | not) ]' "${SUGGESTIONS_FILE}")"
ALREADY="$(jq -n --argjson todo "${TODO}" --argjson posted "${POSTED}" \
  '[ $todo[] | select(.fixId as $id | any($posted[]; . == $id)) ] | length')"

posted_now=0
while IFS= read -r suggestion; do
  [[ -z "${suggestion}" ]] && continue
  PAYLOAD="$(jq -n --argjson s "${suggestion}" --arg sha "${HEAD_SHA}" --arg path "${SPEC_PATH}" '
    {
      body: ("<!-- apiome-fix:" + $s.fixId + " -->\n"
        + "**Apiome lint fix** `" + $s.ruleId + "` (" + ($s.fixClass // "fix") + "): "
        + ($s.message // "") + "\n\n```suggestion\n" + $s.replacement + "```\n"),
      commit_id: $sha,
      path: $path,
      side: "RIGHT",
      line: $s.endLine
    }
    + (if $s.startLine < $s.endLine then {start_line: $s.startLine, start_side: "RIGHT"} else {} end)')"
  STATUS="$("${CURL_BIN}" -sS -o /dev/null -w "%{http_code}" \
    -X POST \
    -H "Accept: application/vnd.github+json" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    -H "Content-Type: application/json" \
    -d "${PAYLOAD}" \
    "${PULL_URL}/comments")"
  if [[ "${STATUS}" == "201" ]]; then
    posted_now=$((posted_now + 1))
  else
    echo "fix_suggestions: review comment refused (HTTP ${STATUS}); the snippet stays in the sticky comment" >&2
  fi
done < <(jq -c --argjson posted "${POSTED}" '.[] | select(.fixId as $id | any($posted[]; . == $id) | not)' <<<"${TODO}")

echo "fix_suggestions: ${posted_now} posted, ${ALREADY} already on the pull request" >&2
echo $((posted_now + ALREADY))
