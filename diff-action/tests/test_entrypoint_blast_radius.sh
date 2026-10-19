#!/usr/bin/env bash
# Unit tests for the blast-radius input of entrypoint.sh (CDG-3.6 / #5971): the action passes
# `--blast-radius` to `apiome diff` by default, drops it with `blast-radius: false`, refuses any
# other value, and the server's "Blast radius:" line reaches the sticky comment unchanged.
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
export INPUT_GITHUB_TOKEN="gh-token"
export INPUT_COMMENT="true"
export ARGS_LOG="${TMP}/args.log"
export BODY_COPY="${TMP}/body.md"

echo '{"pull_request":{"number":99}}' >"${GITHUB_EVENT_PATH}"

# The CLI stub records its arguments and prints a changelog with the server's blast-radius line.
cat >"${APIOME_BIN}" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$@" >"${ARGS_LOG}"
echo "- **Removed** (\`ctg.path_removed\`) — \`/paths/~1pets~1{id}\`"
echo "  - Blast radius: affects 3 consumers across 2 teams (mobile, payments); 1 verification run invalidated"
exit 1
EOF
chmod +x "${APIOME_BIN}"

# The sticky stub keeps a copy of the comment body.
cat >"${STICKY_BIN}" <<'EOF'
#!/usr/bin/env bash
cp "$1" "${BODY_COPY}"
EOF
chmod +x "${STICKY_BIN}"

run() {
  : >"${ARGS_LOG}"
  set +e
  out="$(bash "${ROOT}/entrypoint.sh" 2>&1)"
  code=$?
  set -e
}

# Default: the flag is passed and the line reaches the comment.
unset INPUT_BLAST_RADIUS
run
[[ "${code}" -eq 1 ]] || { echo "default: expected exit 1, got ${code}: ${out}" >&2; exit 1; }
grep -qx -- "--blast-radius" "${ARGS_LOG}" || { echo "default: --blast-radius not passed" >&2; exit 1; }
grep -qx -- "--format" "${ARGS_LOG}"
grep -q "Blast radius: affects 3 consumers across 2 teams (mobile, payments); 1 verification run invalidated" "${BODY_COPY}" \
  || { echo "the blast-radius line is missing from the comment" >&2; exit 1; }

# Explicit true behaves like the default.
export INPUT_BLAST_RADIUS="true"
run
grep -qx -- "--blast-radius" "${ARGS_LOG}"

# false: the flag is left out.
export INPUT_BLAST_RADIUS="false"
run
[[ "${code}" -eq 1 ]]
if grep -qx -- "--blast-radius" "${ARGS_LOG}"; then
  echo "blast-radius=false still passed --blast-radius" >&2
  exit 1
fi

# Anything else is refused before the CLI runs.
export INPUT_BLAST_RADIUS="yes"
run
[[ "${code}" -eq 2 ]] || { echo "invalid: expected exit 2, got ${code}" >&2; exit 1; }
echo "${out}" | grep -q "::error::Input 'blast-radius' must be 'true' or 'false' (got: yes)"
[[ ! -s "${ARGS_LOG}" ]] || { echo "invalid: the CLI ran" >&2; exit 1; }

echo "blast-radius input tests passed"
