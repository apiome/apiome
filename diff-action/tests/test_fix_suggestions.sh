#!/usr/bin/env bash
# Unit tests for fix_suggestions.sh (GVM-3.4 / #5872, mocked curl): a suggestion block is posted
# only when its line range lies inside one hunk of the PR's diff of the spec file, never twice,
# and never when the replacement would break the ``` fence.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

fake_curl="${TMP}/fake-curl"
export CURL_BIN="${fake_curl}"
export GITHUB_TOKEN="test-token"
export GITHUB_REPOSITORY="apiome/apiome"
export GITHUB_API_URL="https://api.github.com"
export PR_NUMBER="42"
export HEAD_SHA="abc123"
export POSTS_DIR="${TMP}/posts"
mkdir -p "${POSTS_DIR}"

# The PR changes lines 1-12 and 30-31 of api/openapi.yaml; fix-old was suggested by an earlier run.
cat >"${fake_curl}" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
args="$*"
if [[ "${args}" == *"pulls/42/files?per_page=100"* ]]; then
  jq -n '[
    {filename: "README.md", patch: "@@ -1 +1,40 @@\n+x"},
    {filename: "api/openapi.yaml", patch: "@@ -1,10 +1,12 @@\n context\n@@ -28,2 +30,2 @@\n-a\n+b"}
  ]'
  exit 0
fi
if [[ "${args}" == *"pulls/42/comments?per_page=100"* ]]; then
  jq -n '[{id: 1, body: "<!-- apiome-fix:fix-old -->\nsuggested before"}, {id: 2, body: "a human"}]'
  exit 0
fi
if [[ "${args}" == *"-X POST"* && "${args}" == *"pulls/42/comments"* ]]; then
  while [[ $# -gt 0 ]]; do
    if [[ "$1" == "-d" ]]; then
      id="$(jq -r '.body | capture("apiome-fix:(?<id>[^ ]+)").id' <<<"$2")"
      printf '%s' "$2" >"${POSTS_DIR:?}/${id}.json"
    fi
    shift
  done
  echo "201"
  exit 0
fi
echo "unexpected curl: ${args}" >&2
exit 1
EOF
chmod +x "${fake_curl}"

suggestion() {
  # suggestion <fixId> <start> <end> <replacement>
  jq -n --arg id "$1" --argjson s "$2" --argjson e "$3" --arg r "$4" \
    '{fixId: $id, ruleId: "structure.empty-required", fixClass: "removal", message: "Empty required.",
      startLine: $s, endLine: $e, replacement: $r}'
}
jq -n \
  --argjson a "$(suggestion fix-old 2 2 '')" \
  --argjson b "$(suggestion fix-one-line 5 5 $'      required: [id]\n')" \
  --argjson c "$(suggestion fix-range 30 31 $'b\nc\n')" \
  --argjson d "$(suggestion fix-outside 20 20 '')" \
  --argjson e "$(suggestion fix-straddles 11 14 '')" \
  --argjson f "$(suggestion fix-fence 3 3 $'x: "```"\n')" \
  '{path: "./api/openapi.yaml", ready: 6, suggestions: [$a, $b, $c, $d, $e, $f]}' >"${TMP}/fixes.json"

count="$(bash "${ROOT}/fix_suggestions.sh" "${TMP}/fixes.json" 2>"${TMP}/stderr")"

# fix-old (already there) + fix-one-line + fix-range are on the PR; the rest stay snippets.
[[ "${count}" == "3" ]] || { echo "expected 3 suggestions, got ${count}" >&2; cat "${TMP}/stderr" >&2; exit 1; }
posted="$(cd "${POSTS_DIR}" && ls | sort | tr '\n' ' ')"
[[ "${posted}" == "fix-one-line.json fix-range.json " ]] || { echo "posted: ${posted}" >&2; exit 1; }

one="${POSTS_DIR}/fix-one-line.json"
[[ "$(jq -r '.path' "${one}")" == "api/openapi.yaml" ]]
[[ "$(jq -r '.commit_id' "${one}")" == "abc123" ]]
[[ "$(jq -r '.side' "${one}")" == "RIGHT" ]]
[[ "$(jq -r '.line' "${one}")" == "5" ]]
[[ "$(jq -r 'has("start_line")' "${one}")" == "false" ]]
jq -r '.body' "${one}" | grep -q '^```suggestion$'
jq -r '.body' "${one}" | grep -qF '      required: [id]'
jq -r '.body' "${one}" | grep -qF '**Apiome lint fix** `structure.empty-required` (removal): Empty required.'

range="${POSTS_DIR}/fix-range.json"
[[ "$(jq -r '.start_line' "${range}")" == "30" ]]
[[ "$(jq -r '.line' "${range}")" == "31" ]]
[[ "$(jq -r '.start_side' "${range}")" == "RIGHT" ]]

# Missing PR context posts nothing and says so.
count="$(HEAD_SHA="" bash "${ROOT}/fix_suggestions.sh" "${TMP}/fixes.json" 2>/dev/null)"
[[ "${count}" == "0" ]]

echo "test_fix_suggestions: ok"
