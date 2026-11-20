#!/usr/bin/env bash
# Unit tests for the compatibility-mode inputs of entrypoint.sh (XPC-4.5 / #5749): `mode`,
# `transitive` and `category` reach `apiome diff` as --mode / --transitive|--no-transitive /
# --category, nothing is passed when they are empty (the project's policy applies), and an
# invalid `transitive` is refused before the CLI runs.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

bin="${TMP}/bin"
mkdir -p "${bin}"
workspace="${TMP}/workspace"
mkdir -p "${workspace}"
echo '{"type": "record", "name": "User", "fields": []}' >"${workspace}/user.avsc"

export PATH="${bin}:${PATH}"
export GITHUB_WORKSPACE="${workspace}"
export GITHUB_OUTPUT="${TMP}/github_output"
export GITHUB_EVENT_PATH="${TMP}/event.json"
export GITHUB_REPOSITORY="apiome/apiome"
export GITHUB_EVENT_NAME="pull_request"
export APIOME_BIN="${bin}/apiome"
export STICKY_BIN="${bin}/sticky_comment.sh"
export INPUT_SPEC="user.avsc"
export INPUT_PROJECT="orders-events@latest"
export INPUT_FAIL_ON="breaking"
export INPUT_API_KEY="test-key"
export INPUT_TENANT="acme-corp"
export INPUT_GITHUB_TOKEN="gh-token"
export INPUT_COMMENT="false"
export INPUT_BLAST_RADIUS="false"
# Suggested fixes (GVM-3.4) have their own test: test_entrypoint_fix_suggestions.sh.
export INPUT_FIX_SUGGESTIONS="false"
export ARGS_LOG="${TMP}/args.log"

echo '{"pull_request":{"number":7}}' >"${GITHUB_EVENT_PATH}"

cat >"${APIOME_BIN}" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$@" >"${ARGS_LOG}"
echo "_Graded under \`FULL_TRANSITIVE\`._"
exit 0
STUB
chmod +x "${APIOME_BIN}"
printf '#!/usr/bin/env bash\nexit 0\n' >"${STICKY_BIN}"
chmod +x "${STICKY_BIN}"

run() {
  : >"${ARGS_LOG}"
  set +e
  out="$(bash "${ROOT}/entrypoint.sh" 2>&1)"
  code=$?
  set -e
}

# Empty inputs: no mode flags, so the server reads the project's policy.
unset INPUT_MODE INPUT_TRANSITIVE INPUT_CATEGORY
run
[[ "${code}" -eq 0 ]] || { echo "default: expected exit 0, got ${code}: ${out}" >&2; exit 1; }
for flag in --mode --transitive --no-transitive --category; do
  if grep -qx -- "${flag}" "${ARGS_LOG}"; then
    echo "default: ${flag} passed without an input" >&2
    exit 1
  fi
done

# Every input set: each flag is passed with its value.
export INPUT_MODE="full"
export INPUT_TRANSITIVE="true"
export INPUT_CATEGORY="wire"
run
[[ "${code}" -eq 0 ]]
grep -A1 -x -- "--mode" "${ARGS_LOG}" | grep -qx "full" || { echo "--mode full not passed" >&2; exit 1; }
grep -qx -- "--transitive" "${ARGS_LOG}" || { echo "--transitive not passed" >&2; exit 1; }
grep -A1 -x -- "--category" "${ARGS_LOG}" | grep -qx "wire" || { echo "--category wire not passed" >&2; exit 1; }

# transitive=false turns a transitive policy off for this run.
export INPUT_TRANSITIVE="false"
run
grep -qx -- "--no-transitive" "${ARGS_LOG}" || { echo "--no-transitive not passed" >&2; exit 1; }

# Anything else is refused before the CLI runs.
export INPUT_TRANSITIVE="maybe"
run
[[ "${code}" -eq 2 ]] || { echo "invalid: expected exit 2, got ${code}" >&2; exit 1; }
echo "${out}" | grep -q "::error::Input 'transitive' must be 'true', 'false' or empty (got: maybe)"
[[ ! -s "${ARGS_LOG}" ]] || { echo "invalid: the CLI ran" >&2; exit 1; }

echo "compatibility-mode input tests passed"
