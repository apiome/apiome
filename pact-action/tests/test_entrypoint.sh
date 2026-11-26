#!/usr/bin/env bash
# Tests for pact-action/entrypoint.sh (PFX-4.3 / #6940): the CLI arguments each command sends,
# exit-code propagation, every refusal, the job summary, and the sticky PR comment.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

BIN="${TMP}/bin"
mkdir -p "${BIN}"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

# Write the stub CLI: it logs its arguments (one per line) and the broker env, prints `stdout`
# to stdout and `stderr` to stderr, and exits with `code`.
#
# Args: $1 — exit code, $2 — stdout text, $3 — stderr text (optional).
install_cli_stub() {
  cat >"${BIN}/apiome" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$@" >"\${ARGS_LOG}"
env | grep -E '^(PACT_BROKER_BASE_URL|PACT_BROKER_TOKEN|APIOME_LOAD_DOTENV)=' | sort >"\${ENV_LOG}"
printf '%s\n' "$2"
[[ -z "${3:-}" ]] || printf '%s\n' "${3:-}" >&2
exit $1
EOF
  chmod +x "${BIN}/apiome"
}

# Write the stub sticky-comment script: it logs its marker, PR number, token and body.
#
# Args: $1 — exit code it returns.
install_sticky_stub() {
  cat >"${BIN}/sticky.sh" <<EOF
#!/usr/bin/env bash
{
  echo "marker=\${STICKY_MARKER}"
  echo "pr=\${PR_NUMBER}"
  echo "token=\${GITHUB_TOKEN}"
  cat "\$1"
} >"\${STICKY_LOG}"
exit $1
EOF
  chmod +x "${BIN}/sticky.sh"
}

# Reset the environment to a pull-request run of `can-i-deploy` with every input valid.
reset_env() {
  local ws="${TMP}/ws"
  rm -rf "${ws}"
  mkdir -p "${ws}/pacts"
  printf '{}\n' >"${ws}/pacts/web-billing.json"
  for var in $(env | grep -oE '^(INPUT_[A-Z_]+|PACT_BROKER_[A-Z_]+)' || true); do unset "${var}"; done
  export GITHUB_WORKSPACE="${ws}"
  export GITHUB_OUTPUT="${TMP}/output"
  export GITHUB_STEP_SUMMARY="${TMP}/summary"
  export GITHUB_EVENT_NAME=pull_request
  export GITHUB_REPOSITORY=acme/web
  export ARGS_LOG="${TMP}/args"
  export ENV_LOG="${TMP}/env"
  export STICKY_LOG="${TMP}/sticky"
  export APIOME_BIN="${BIN}/apiome"
  export STICKY_BIN="${BIN}/sticky.sh"
  export PR_NUMBER=42
  export BUILD_URL=https://github.com/acme/web/actions/runs/7
  export INPUT_COMMAND=can-i-deploy
  export INPUT_BROKER_BASE_URL=https://api.example.com/v1/tenants/acme/pact-broker
  export INPUT_BROKER_TOKEN=secret-key
  export INPUT_PACTS=pacts
  export INPUT_PACTICIPANT="Billing Service"
  export INPUT_VERSION=0123456789abcdef
  export INPUT_BRANCH=feature/x
  export INPUT_ENVIRONMENT=production
  export INPUT_RETRY_WHILE_UNKNOWN=0
  export INPUT_RETRY_INTERVAL=10
  export INPUT_DRY_RUN=false
  export INPUT_COMMENT=true
  export INPUT_GITHUB_TOKEN=gh-token
  rm -f "${ARGS_LOG}" "${ENV_LOG}" "${STICKY_LOG}" "${GITHUB_OUTPUT}" "${GITHUB_STEP_SUMMARY}"
  install_cli_stub 0 '**Computer says yes \o/**'
  install_sticky_stub 0
}

OUT=""
CODE=0
# Run the entrypoint, capturing its combined output in OUT and its exit code in CODE.
run() {
  set +e
  OUT="$(bash "${ROOT}/entrypoint.sh" 2>&1)"
  CODE=$?
  set -e
}

# Assert the CLI was called with exactly these arguments.
#
# Args: the expected arguments.
expect_args() {
  local expected
  expected="$(printf '%s\n' "$@")"
  [[ "$(cat "${ARGS_LOG}")" == "${expected}" ]] ||
    fail "CLI arguments:\n--- expected\n${expected}\n--- got\n$(cat "${ARGS_LOG}")"
}

# Assert the run was refused before the CLI ran.
#
# Args: $1 — text the refusal must contain.
expect_refused() {
  [[ "${CODE}" -eq 1 ]] || fail "expected exit 1 for a refusal, got ${CODE}: ${OUT}"
  grep -qF -- "$1" <<<"${OUT}" || fail "expected the reason [$1], got: ${OUT}"
  grep -qF "::error::" <<<"${OUT}" || fail "a refusal must be an error annotation: ${OUT}"
  [[ ! -e "${ARGS_LOG}" ]] || fail "the CLI must not run when the input is refused"
  grep -qxF "exit-code=1" "${GITHUB_OUTPUT}" || fail "a refusal must set exit-code=1"
}

# --- can-i-deploy -----------------------------------------------------------------------------

reset_env
run
[[ "${CODE}" -eq 0 ]] || fail "deployable: expected 0, got ${CODE}: ${OUT}"
expect_args pact can-i-deploy --pacticipant "Billing Service" --version 0123456789abcdef \
  --to-environment production --retry-while-unknown 0 --retry-interval 10 --output markdown
grep -qxF "PACT_BROKER_BASE_URL=https://api.example.com/v1/tenants/acme/pact-broker" "${ENV_LOG}" ||
  fail "broker URL not passed in the environment"
grep -qxF "PACT_BROKER_TOKEN=secret-key" "${ENV_LOG}" || fail "token not passed in the environment"
grep -qxF "APIOME_LOAD_DOTENV=0" "${ENV_LOG}" || fail "dotenv loading not disabled"
if grep -q "secret-key" <<<"${OUT}"; then fail "the token must never be printed"; fi
grep -qxF "exit-code=0" "${GITHUB_OUTPUT}" || fail "exit-code output"
grep -qxF "deployable=true" "${GITHUB_OUTPUT}" || fail "deployable output"
grep -qxF "report-path=${GITHUB_WORKSPACE}/apiome-pact-can-i-deploy.md" "${GITHUB_OUTPUT}" || fail "report-path output"
grep -q "Computer says yes" "${GITHUB_WORKSPACE}/apiome-pact-can-i-deploy.md" || fail "report file"
grep -q 'can `Billing Service` deploy to `production`?' "${GITHUB_STEP_SUMMARY}" || fail "job summary"
grep -qxF "marker=<!-- apiome-pact-action:can-i-deploy:Billing-Service@production -->" "${STICKY_LOG}" ||
  fail "sticky marker: $(cat "${STICKY_LOG}")"
grep -qxF "pr=42" "${STICKY_LOG}" || fail "sticky PR number"
grep -qxF "token=gh-token" "${STICKY_LOG}" || fail "sticky token"
grep -q "Computer says yes" "${STICKY_LOG}" || fail "sticky body"

# Not deployable: exit 1, deployable=false, comment still posted.
reset_env
install_cli_stub 1 '**Computer says no ¯\_(ツ)_/¯**'
run
[[ "${CODE}" -eq 1 ]] || fail "not deployable: expected 1, got ${CODE}"
grep -qxF "deployable=false" "${GITHUB_OUTPUT}" || fail "deployable=false output"
grep -q "it cannot be deployed yet" "${STICKY_LOG}" || fail "sticky says no"
grep -q "::error::pact-action: apiome pact can-i-deploy exited 1" <<<"${OUT}" || fail "failure annotation"

# The CLI fails before a verdict (a refused key): messages reach the comment, deployable is empty.
reset_env
install_cli_stub 1 '' 'Error: the key lacks the pact:read scope'
run
[[ "${CODE}" -eq 1 ]] || fail "refused key: expected 1"
grep -qxF "deployable=" "${GITHUB_OUTPUT}" || fail "deployable must be empty without a verdict"
grep -q "the key lacks the pact:read scope" "${STICKY_LOG}" || fail "stderr not in the comment"
grep -q "the key lacks the pact:read scope" <<<"${OUT}" || fail "stderr not in the log"

# Dry run, retries.
reset_env
export INPUT_DRY_RUN=true INPUT_RETRY_WHILE_UNKNOWN=12 INPUT_RETRY_INTERVAL=2.5
run
expect_args pact can-i-deploy --pacticipant "Billing Service" --version 0123456789abcdef \
  --to-environment production --retry-while-unknown 12 --retry-interval 2.5 --dry-run --output markdown

# A failing comment never changes the result.
reset_env
install_sticky_stub 1
run
[[ "${CODE}" -eq 0 ]] || fail "a failed comment must not fail the step (got ${CODE})"
grep -q "::warning::pact-action: could not update the pull-request comment" <<<"${OUT}" || fail "comment warning"

# Outside a pull request, or with comment=false, nothing is posted.
reset_env
export PR_NUMBER=""
run
[[ ! -e "${STICKY_LOG}" ]] || fail "no comment outside a pull request"
grep -q "not a pull request; no comment posted" <<<"${OUT}" || fail "say why no comment"
reset_env
export INPUT_COMMENT=false
run
[[ ! -e "${STICKY_LOG}" ]] || fail "comment=false must not post"

# comment-id keys the comment.
reset_env
export INPUT_COMMENT_ID=eu
run
grep -qxF "marker=<!-- apiome-pact-action:can-i-deploy:eu -->" "${STICKY_LOG}" || fail "comment-id marker"

# Refusals.
reset_env; export INPUT_PACTICIPANT=""; run; expect_refused "input 'pacticipant' is required for can-i-deploy"
reset_env; export INPUT_ENVIRONMENT=""; run; expect_refused "input 'environment' is required for can-i-deploy"
reset_env; export INPUT_RETRY_WHILE_UNKNOWN=-1; run; expect_refused "input 'retry-while-unknown' must be a whole number"
reset_env; export INPUT_RETRY_INTERVAL=soon; run; expect_refused "input 'retry-interval' must be a number of seconds"
reset_env; export INPUT_DRY_RUN=maybe; run; expect_refused "input 'dry-run' must be true or false (got: maybe)"
reset_env; export INPUT_COMMENT=1; run; expect_refused "input 'comment' must be true or false (got: 1)"

# --- shared inputs ----------------------------------------------------------------------------

reset_env; export INPUT_COMMAND=""; run; expect_refused "input 'command' is required"
reset_env; export INPUT_COMMAND=create-webhook; run
expect_refused "unsupported command 'create-webhook': pact-action runs publish, can-i-deploy or record-deployment"
reset_env; export INPUT_BROKER_BASE_URL=""; run; expect_refused "input 'broker-base-url' is required"
reset_env; export INPUT_BROKER_BASE_URL=api.example.com; run; expect_refused "must be an http(s) URL"
reset_env; export INPUT_BROKER_TOKEN=""; run; expect_refused "input 'broker-token' is required"
reset_env; export INPUT_VERSION=""; run; expect_refused "input 'version' is empty"

# PACT_BROKER_* from the job's env stand in for empty inputs.
reset_env
export INPUT_BROKER_BASE_URL="" INPUT_BROKER_TOKEN=""
export PACT_BROKER_BASE_URL=https://env.example.com/pact-broker PACT_BROKER_TOKEN=env-key
run
[[ "${CODE}" -eq 0 ]] || fail "env fallback: expected 0, got ${CODE}: ${OUT}"
grep -qxF "PACT_BROKER_BASE_URL=https://env.example.com/pact-broker" "${ENV_LOG}" || fail "env URL fallback"
grep -qxF "PACT_BROKER_TOKEN=env-key" "${ENV_LOG}" || fail "env token fallback"

# Basic-auth password alone is accepted (the CLI reads it as the key).
reset_env
export INPUT_BROKER_TOKEN="" PACT_BROKER_PASSWORD=pw-key
run
[[ "${CODE}" -eq 0 ]] || fail "password fallback: expected 0, got ${CODE}: ${OUT}"

# --- publish ----------------------------------------------------------------------------------

reset_env
export INPUT_COMMAND=publish INPUT_TAGS=$'rc\n\n  beta '
install_cli_stub 0 '- Published the pacts of web version 0123456789abcdef'
run
[[ "${CODE}" -eq 0 ]] || fail "publish: expected 0, got ${CODE}: ${OUT}"
expect_args pact publish pacts --consumer-app-version 0123456789abcdef --branch feature/x \
  --tag rc --tag beta --build-url https://github.com/acme/web/actions/runs/7 --output markdown
grep -qxF "marker=<!-- apiome-pact-action:publish -->" "${STICKY_LOG}" || fail "publish marker"
grep -q "Published the pacts of web" "${STICKY_LOG}" || fail "publish comment body"
if grep -q "^deployable=" "${GITHUB_OUTPUT}"; then fail "publish has no deployable output"; fi

# Several paths, one per line, including a path with a space.
reset_env
export INPUT_COMMAND=publish INPUT_PACTS=$'pacts/web-billing.json\nmore pacts'
mkdir -p "${GITHUB_WORKSPACE}/more pacts"
run
expect_args pact publish pacts/web-billing.json "more pacts" --consumer-app-version 0123456789abcdef \
  --branch feature/x --build-url https://github.com/acme/web/actions/runs/7 --output markdown

# A refused publish (exit 1) propagates.
reset_env
export INPUT_COMMAND=publish
install_cli_stub 1 '' 'Error: pacts/web-billing.json is not a pact: no consumer'
run
[[ "${CODE}" -eq 1 ]] || fail "refused publish: expected 1"
grep -q "not published" "${STICKY_LOG}" || fail "refused publish comment"

reset_env; export INPUT_COMMAND=publish INPUT_PACTS=$'\n  \n'; run; expect_refused "input 'pacts' is empty"
reset_env; export INPUT_COMMAND=publish INPUT_PACTS=missing; run; expect_refused "pact path not found: missing"

# No branch: the flag is left out rather than sent empty.
reset_env
export INPUT_COMMAND=publish INPUT_BRANCH="" BUILD_URL=""
run
expect_args pact publish pacts --consumer-app-version 0123456789abcdef --output markdown

# --- record-deployment ------------------------------------------------------------------------

reset_env
export INPUT_COMMAND=record-deployment GITHUB_EVENT_NAME=push INPUT_APPLICATION_INSTANCE=eu-west
install_cli_stub 0 'Recorded deployment of Billing Service version 0123456789abcdef to production environment'
run
[[ "${CODE}" -eq 0 ]] || fail "record-deployment: expected 0, got ${CODE}: ${OUT}"
expect_args pact record-deployment --pacticipant "Billing Service" --version 0123456789abcdef \
  --environment production --application-instance eu-west --output markdown
[[ ! -e "${STICKY_LOG}" ]] || fail "record-deployment never comments"
grep -q "### Pact: recorded deployment" "${GITHUB_STEP_SUMMARY}" || fail "record-deployment summary"

reset_env
export INPUT_COMMAND=record-deployment GITHUB_EVENT_NAME=push
install_cli_stub 1 '' "Error: No environment named 'production' in this workspace."
run
[[ "${CODE}" -eq 1 ]] || fail "record-deployment failure must exit 1"

reset_env; export INPUT_COMMAND=record-deployment; run
expect_refused "record-deployment runs after a deploy, on merge — this is a pull_request event"
reset_env; export INPUT_COMMAND=record-deployment GITHUB_EVENT_NAME=pull_request_target; run
expect_refused "this is a pull_request_target event"
reset_env; export INPUT_COMMAND=record-deployment GITHUB_EVENT_NAME=push INPUT_PACTICIPANT=""; run
expect_refused "input 'pacticipant' is required for record-deployment"
reset_env; export INPUT_COMMAND=record-deployment GITHUB_EVENT_NAME=push INPUT_ENVIRONMENT=""; run
expect_refused "input 'environment' is required for record-deployment"

echo "test_entrypoint: ok"
