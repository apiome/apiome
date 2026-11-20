#!/usr/bin/env bash
# Unit tests for the fix-suggestions input of entrypoint.sh (GVM-3.4 / #5872): by default the
# action runs `apiome lint suggest` on the spec, writes the patch and overlay artefact files
# byte-for-byte, upserts a separate "fixes" section of the one sticky comment after the "diff"
# section, posts suggestion blocks, and keeps the diff's exit code whatever happens to the fixes.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

bin="${TMP}/bin"
mkdir -p "${bin}"
workspace="${TMP}/workspace"
mkdir -p "${workspace}/api"
echo "openapi: 3.1.0" >"${workspace}/api/openapi.yaml"

export PATH="${bin}:${PATH}"
export GITHUB_WORKSPACE="${workspace}"
export GITHUB_OUTPUT="${TMP}/github_output"
export GITHUB_EVENT_PATH="${TMP}/event.json"
export GITHUB_REPOSITORY="apiome/apiome"
export GITHUB_EVENT_NAME="pull_request"
export GITHUB_SERVER_URL="https://github.com"
export GITHUB_RUN_ID="777"
export APIOME_BIN="${bin}/apiome"
export STICKY_BIN="${bin}/sticky_comment.sh"
export FIX_SUGGESTIONS_BIN="${bin}/fix_suggestions.sh"
export INPUT_SPEC="./api/openapi.yaml"
export INPUT_PROJECT="payments@latest"
export INPUT_FAIL_ON="breaking"
export INPUT_API_KEY="test-key"
export INPUT_TENANT="acme-corp"
export INPUT_GITHUB_TOKEN="gh-token"
export INPUT_COMMENT="true"
export ARGS_LOG="${TMP}/args.log"
export STICKY_LOG="${TMP}/sticky.log"
export SECTIONS_DIR="${TMP}/sections"
export SUGGEST_LOG="${TMP}/suggest.log"
mkdir -p "${SECTIONS_DIR}"

echo '{"pull_request":{"number":99,"head":{"sha":"headsha"}}}' >"${GITHUB_EVENT_PATH}"

PATCH_BYTES='[{"op":"remove","path":"/tags/1"}]'
export PATCH_BYTES

# CLI stub: `diff` prints a changelog and fails the gate; `lint suggest` writes each --format to -o
# (or fails with SUGGEST_EXIT).
cat >"${APIOME_BIN}" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"${ARGS_LOG}"
if [[ "$1" == "diff" ]]; then
  echo "- **Removed** \`/pets\`"
  exit 1
fi
[[ "${SUGGEST_EXIT:-0}" -eq 0 ]] || exit "${SUGGEST_EXIT}"
fmt=""; out=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --format) fmt="$2"; shift ;;
    -o) out="$2"; shift ;;
  esac
  shift
done
case "${fmt}" in
  json) echo '{"path":"api/openapi.yaml","ready":3,"suggestions":[]}' >"${out}" ;;
  patch) printf '%s' "${PATCH_BYTES}" >"${out}" ;;
  overlay) printf '{"overlay":"1.0.0"}' >"${out}" ;;
  markdown) printf '### Suggested fixes\n\n3 mechanical fixes ready\n' >"${out}" ;;
esac
EOF
chmod +x "${APIOME_BIN}"

# Sticky stub: record the section order and keep each section's body.
cat >"${STICKY_BIN}" <<'EOF'
#!/usr/bin/env bash
echo "${STICKY_SECTION}" >>"${STICKY_LOG}"
cp "$1" "${SECTIONS_DIR}/${STICKY_SECTION}.md"
EOF
chmod +x "${STICKY_BIN}"

# Suggestion stub: record the head sha and say two suggestion blocks are on the PR.
cat >"${FIX_SUGGESTIONS_BIN}" <<'EOF'
#!/usr/bin/env bash
echo "${HEAD_SHA} $1" >>"${SUGGEST_LOG}"
echo "noise" >&2
echo 2
EOF
chmod +x "${FIX_SUGGESTIONS_BIN}"

run() {
  : >"${ARGS_LOG}"; : >"${STICKY_LOG}"; : >"${SUGGEST_LOG}"; : >"${GITHUB_OUTPUT}"
  rm -f "${SECTIONS_DIR}"/*.md "${workspace}"/.apiome-lint-fixes.*
  set +e
  out="$(bash "${ROOT}/entrypoint.sh" 2>&1)"
  code=$?
  set -e
}

# --- default: fixes on ---
run
[[ "${code}" -eq 1 ]] || { echo "the diff's exit code must win (got ${code})" >&2; echo "${out}" >&2; exit 1; }
grep -q -- 'lint suggest ./api/openapi.yaml --path api/openapi.yaml --format json' "${ARGS_LOG}"
grep -q -- '--format markdown --artifact-url https://github.com/apiome/apiome/actions/runs/777#artifacts' "${ARGS_LOG}"
[[ "$(cat "${STICKY_LOG}")" == $'diff\nfixes' ]] || { echo "sections: $(cat "${STICKY_LOG}")" >&2; exit 1; }
grep -q "### Apiome contract gate: failed" "${SECTIONS_DIR}/diff.md"
if grep -q "Suggested fixes" "${SECTIONS_DIR}/diff.md"; then echo "fixes leaked into the diff section" >&2; exit 1; fi
grep -q "3 mechanical fixes ready" "${SECTIONS_DIR}/fixes.md"
grep -q "2 suggestion block(s) on the changed lines" "${SECTIONS_DIR}/fixes.md"
grep -q "^headsha " "${SUGGEST_LOG}"
# The artefact is the CLI's bytes, unchanged.
[[ "$(cat "${workspace}/.apiome-lint-fixes.patch.json")" == "${PATCH_BYTES}" ]]
[[ -s "${workspace}/.apiome-lint-fixes.overlay.json" ]]
grep -q "^fix-count=3$" "${GITHUB_OUTPUT}"
grep -q "^fix-patch-path=.apiome-lint-fixes.patch.json$" "${GITHUB_OUTPUT}"
grep -q "^fix-overlay-path=.apiome-lint-fixes.overlay.json$" "${GITHUB_OUTPUT}"

# --- the suggest call fails: the gate verdict is unchanged and the section says so ---
SUGGEST_EXIT=2 run
[[ "${code}" -eq 1 ]]
grep -q "could not be computed" "${SECTIONS_DIR}/fixes.md"
[[ ! -s "${SUGGEST_LOG}" ]]
echo "${out}" | grep -q "warning: apiome lint suggest failed (exit 2)"

# --- comment=false: artefacts still written, nothing posted ---
INPUT_COMMENT=false run
[[ "${code}" -eq 1 ]]
[[ ! -s "${STICKY_LOG}" && ! -s "${SUGGEST_LOG}" ]]
[[ -s "${workspace}/.apiome-lint-fixes.patch.json" ]]

# --- fix-suggestions=false: no lint suggest call, only the diff section ---
INPUT_FIX_SUGGESTIONS=false run
[[ "${code}" -eq 1 ]]
if grep -q "lint suggest" "${ARGS_LOG}"; then echo "lint suggest ran with fix-suggestions=false" >&2; exit 1; fi
[[ "$(cat "${STICKY_LOG}")" == "diff" ]]

# --- any other value is refused ---
INPUT_FIX_SUGGESTIONS=maybe run
[[ "${code}" -eq 2 ]]
echo "${out}" | grep -q "::error::Input 'fix-suggestions' must be 'true' or 'false' (got: maybe)"

echo "test_entrypoint_fix_suggestions: ok"
