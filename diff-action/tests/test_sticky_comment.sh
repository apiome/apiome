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

echo "test_sticky_comment: ok"
