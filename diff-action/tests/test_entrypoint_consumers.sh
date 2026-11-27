#!/usr/bin/env bash
# Unit tests for the consumers input of entrypoint.sh (PFX-7.4 / #6964): the action passes
# `--consumers` to `apiome diff` by default, drops it with `consumers: false`, refuses any other
# value, and the server's broker-backed consumer line reaches the sticky comment unchanged.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

bin="${TMP}/bin"
mkdir -p "${bin}" "${TMP}/workspace"
echo "openapi: 3.1.0" >"${TMP}/workspace/openapi.yaml"

export PATH="${bin}:${PATH}"
export GITHUB_WORKSPACE="${TMP}/workspace"
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
export INPUT_GITHUB_TOKEN="gh-token"
export INPUT_COMMENT="true"
export INPUT_FIX_SUGGESTIONS="false"
export ARGS_LOG="${TMP}/args.log"
export BODY_COPY="${TMP}/body.md"

echo '{"pull_request":{"number":99}}' >"${GITHUB_EVENT_PATH}"

cat >"${APIOME_BIN}" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$@" >"${ARGS_LOG}"
echo "## Consumer impact"
echo "### \`billing-service\` — breaking"
echo "Pact Broker: pacticipant \`billing-service\` — surface from a published pact (version 1.4.0, a1b2c3d4e5f6)"
exit 1
STUB
chmod +x "${APIOME_BIN}"

cat >"${STICKY_BIN}" <<'STUB'
#!/usr/bin/env bash
cp "$1" "${BODY_COPY}"
STUB
chmod +x "${STICKY_BIN}"

run() {
  : >"${ARGS_LOG}"
  set +e
  out="$(bash "${ROOT}/entrypoint.sh" 2>&1)"
  code=$?
  set -e
}

# Default: the flag is passed and the broker line reaches the comment.
unset INPUT_CONSUMERS
run
[[ "${code}" -eq 1 ]] || { echo "default: expected exit 1, got ${code}: ${out}" >&2; exit 1; }
grep -qx -- "--consumers" "${ARGS_LOG}" || { echo "default: --consumers not passed" >&2; exit 1; }
grep -q "Pact Broker: pacticipant \`billing-service\`" "${BODY_COPY}" \
  || { echo "the broker line is missing from the comment" >&2; exit 1; }

# Explicit true behaves like the default.
export INPUT_CONSUMERS="true"
run
grep -qx -- "--consumers" "${ARGS_LOG}"

# false: the flag is left out.
export INPUT_CONSUMERS="false"
run
[[ "${code}" -eq 1 ]]
if grep -qx -- "--consumers" "${ARGS_LOG}"; then
  echo "consumers=false still passed --consumers" >&2
  exit 1
fi

# Anything else is refused before the CLI runs.
export INPUT_CONSUMERS="yes"
run
[[ "${code}" -eq 2 ]] || { echo "invalid: expected exit 2, got ${code}" >&2; exit 1; }
echo "${out}" | grep -q "::error::Input 'consumers' must be 'true' or 'false' (got: yes)"
[[ ! -s "${ARGS_LOG}" ]] || { echo "invalid: the CLI ran" >&2; exit 1; }

echo "consumers input tests passed"
