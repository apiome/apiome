#!/usr/bin/env bash
# Unit tests for entrypoint.sh exit-code propagation and sticky wiring.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

bin="${TMP}/bin"
mkdir -p "${bin}"
workspace="${TMP}/workspace"
mkdir -p "${workspace}"
echo "openapi: 3.1.0" >"${workspace}/openapi.yaml"

export PATH="${bin}:${PATH}"
export GITHUB_WORKSPACE="${workspace}"
export GITHUB_OUTPUT="${TMP}/github_output"
export GITHUB_EVENT_PATH="${TMP}/event.json"
export GITHUB_REPOSITORY="apiome/apiome"
export GITHUB_EVENT_NAME="pull_request"
export APIOME_BIN="${bin}/apiome"
export STICKY_BIN="${bin}/sticky_comment.sh"
export INPUT_SPEC="openapi.yaml"
export INPUT_PROJECT="payments@latest"
export INPUT_FAIL_ON="breaking"
export INPUT_API_KEY="test-key"
export INPUT_TENANT="acme-corp"
export INPUT_BASE_URL="https://api.example.com"
export INPUT_GITHUB_TOKEN="gh-token"
export INPUT_COMMENT="true"

cat >"${GITHUB_EVENT_PATH}" <<'EOF'
{"pull_request":{"number":99}}
EOF

# sticky mock: record invocations
cat >"${STICKY_BIN}" <<'EOF'
#!/usr/bin/env bash
echo "sticky:$1" >>"${STICKY_LOG}"
exit 0
EOF
chmod +x "${STICKY_BIN}"

run_case() {
  local code="$1"
  local expect_error="${2:-}"
  : >"${GITHUB_OUTPUT}"
  export STICKY_LOG="${TMP}/sticky-${code}.log"
  : >"${STICKY_LOG}"

  cat >"${APIOME_BIN}" <<EOF
#!/usr/bin/env bash
echo "# changelog for exit ${code}"
echo "stderr noise" >&2
exit ${code}
EOF
  chmod +x "${APIOME_BIN}"

  set +e
  out="$(bash "${ROOT}/entrypoint.sh" 2>&1)"
  actual=$?
  set -e

  if [[ "${actual}" -ne "${code}" ]]; then
    echo "expected exit ${code}, got ${actual}" >&2
    echo "${out}" >&2
    exit 1
  fi
  grep -q "exit-code=${code}" "${GITHUB_OUTPUT}"
  grep -q "changelog-path=" "${GITHUB_OUTPUT}"
  grep -q "sticky:" "${STICKY_LOG}"
  if [[ "${expect_error}" == "error" ]]; then
    echo "${out}" | grep -q '::error::Apiome diff operational error (exit 2)'
  fi
}

run_case 0
run_case 1
run_case 2 error

# comment=false skips sticky
export INPUT_COMMENT="false"
export STICKY_LOG="${TMP}/sticky-skip.log"
: >"${STICKY_LOG}"
: >"${GITHUB_OUTPUT}"
cat >"${APIOME_BIN}" <<'EOF'
#!/usr/bin/env bash
echo ok
exit 0
EOF
chmod +x "${APIOME_BIN}"
set +e
bash "${ROOT}/entrypoint.sh" >/dev/null 2>&1
actual=$?
set -e
[[ "${actual}" -eq 0 ]]
[[ ! -s "${STICKY_LOG}" ]]

echo "test_entrypoint_exit: ok"
