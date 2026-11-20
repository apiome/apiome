#!/usr/bin/env bash
# Unit tests for sticky_comment.sh (mocked curl).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

fake_curl="${TMP}/fake-curl"
log="${TMP}/curl.log"
body="${TMP}/body.md"
export CURL_BIN="${fake_curl}"
export GITHUB_TOKEN="test-token"
export GITHUB_REPOSITORY="apiome/apiome"
export GITHUB_API_URL="https://api.github.com"
export PR_NUMBER="42"
export PATH="${TMP}:${PATH}"

cat >"${body}" <<'EOF'
### Apiome contract gate: failed
some changelog
EOF

# --- create path: empty comment list ---
cat >"${fake_curl}" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
LOG="${FAKE_CURL_LOG:?}"
echo "$@" >>"${LOG}"
# Detect method / URL from args
args="$*"
if [[ "${args}" == *"issues/42/comments?per_page=100"* ]]; then
  echo '[]'
  exit 0
fi
if [[ "${args}" == *"-X POST"* ]] || [[ "${args}" == *" POST "* ]]; then
  # write body response; print status via -w handling: our script uses -w %{http_code}
  # Fake: last invocation that is POST should emit 201 to stdout (because -o redirects body)
  if [[ "${args}" == *"-w %{http_code}"* ]] || [[ "${args}" == *"-w"*"%{http_code}"* ]]; then
    echo "201"
  else
    echo '{"id":99}'
  fi
  exit 0
fi
echo "unexpected curl: ${args}" >&2
exit 1
EOF
chmod +x "${fake_curl}"

export FAKE_CURL_LOG="${log}"
: >"${log}"
bash "${ROOT}/sticky_comment.sh" "${body}"
grep -q -- '-X POST' "${log}"
grep -q 'issues/42/comments' "${log}"
! grep -q -- '-X PATCH' "${log}"

# --- update path: existing sticky comment ---
cat >"${fake_curl}" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
LOG="${FAKE_CURL_LOG:?}"
echo "$@" >>"${LOG}"
args="$*"
if [[ "${args}" == *"issues/42/comments?per_page=100"* ]]; then
  printf '%s\n' '[{"id":777,"body":"<!-- apiome-diff-action -->\nold"}]'
  exit 0
fi
if [[ "${args}" == *"-X PATCH"* ]]; then
  echo "200"
  exit 0
fi
echo "unexpected curl: ${args}" >&2
exit 1
EOF
chmod +x "${fake_curl}"
: >"${log}"
bash "${ROOT}/sticky_comment.sh" "${body}"
grep -q -- '-X PATCH' "${log}"
grep -q 'issues/comments/777' "${log}"
! grep -q -- '-X POST' "${log}"

# --- sections (GVM-3.4): one comment, the diff and the fixes update independently ---
# This fake curl serves LIST_BODY as the one existing comment (or none when empty) and saves the
# JSON payload of each write to PAYLOAD_LOG.
cat >"${fake_curl}" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
echo "$@" >>"${FAKE_CURL_LOG:?}"
args="$*"
if [[ "${args}" == *"issues/42/comments?per_page=100"* ]]; then
  if [[ -n "${LIST_BODY:-}" ]]; then
    jq -n --arg body "${LIST_BODY}" '[{id: 777, body: $body}]'
  else
    echo '[]'
  fi
  exit 0
fi
while [[ $# -gt 0 ]]; do
  if [[ "$1" == "-d" ]]; then printf '%s' "$2" >"${PAYLOAD_LOG:?}"; fi
  shift
done
if [[ "${args}" == *"-X PATCH"* ]]; then echo "200"; exit 0; fi
if [[ "${args}" == *"-X POST"* ]]; then echo "201"; exit 0; fi
exit 1
EOF
chmod +x "${fake_curl}"
export PAYLOAD_LOG="${TMP}/payload.json"
posted_body() { jq -r '.body' "${PAYLOAD_LOG}"; }
expect_body() {
  local expected="$1"
  if [[ "$(posted_body)" != "${expected}" ]]; then
    echo "unexpected body:" >&2
    posted_body >&2
    echo "--- expected:" >&2
    printf '%s\n' "${expected}" >&2
    exit 1
  fi
}
printf 'diff v1' >"${body}"
fixes_body="${TMP}/fixes.md"

# First run, no comment yet: the diff section starts the comment.
: >"${log}"
LIST_BODY="" STICKY_SECTION=diff bash "${ROOT}/sticky_comment.sh" "${body}"
grep -q -- '-X POST' "${log}"
expect_body $'<!-- apiome-diff-action -->\n<!-- apiome-diff-action:diff -->\ndiff v1\n<!-- /apiome-diff-action:diff -->'

# The fixes section is appended to the same comment.
both=$'<!-- apiome-diff-action -->\n<!-- apiome-diff-action:diff -->\ndiff v1\n<!-- /apiome-diff-action:diff -->'
printf 'fixes v1' >"${fixes_body}"
: >"${log}"
LIST_BODY="${both}" STICKY_SECTION=fixes bash "${ROOT}/sticky_comment.sh" "${fixes_body}"
grep -q 'issues/comments/777' "${log}"
if grep -q -- '-X POST' "${log}"; then echo "a second comment was created" >&2; exit 1; fi
both="${both}"$'\n\n<!-- apiome-diff-action:fixes -->\nfixes v1\n<!-- /apiome-diff-action:fixes -->'
expect_body "${both}"

# A new diff replaces only the diff section; the fixes stay as they were.
printf 'diff v2 with ✅' >"${body}"
: >"${log}"
LIST_BODY="${both}" STICKY_SECTION=diff bash "${ROOT}/sticky_comment.sh" "${body}"
if grep -q -- '-X POST' "${log}"; then echo "a second comment was created" >&2; exit 1; fi
expect_body "${both/diff v1/diff v2 with ✅}"

# New fixes replace only the fixes section.
printf 'fixes v2' >"${fixes_body}"
: >"${log}"
LIST_BODY="${both}" STICKY_SECTION=fixes bash "${ROOT}/sticky_comment.sh" "${fixes_body}"
expect_body "${both/fixes v1/fixes v2}"

# A comment from before sections existed is replaced wholesale, still in place.
: >"${log}"
LIST_BODY=$'<!-- apiome-diff-action -->\nold changelog' STICKY_SECTION=diff bash "${ROOT}/sticky_comment.sh" "${body}"
grep -q 'issues/comments/777' "${log}"
expect_body $'<!-- apiome-diff-action -->\n<!-- apiome-diff-action:diff -->\ndiff v2 with ✅\n<!-- /apiome-diff-action:diff -->'

echo "test_sticky_comment: ok"
