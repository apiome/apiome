#!/usr/bin/env bash
# apiome/pact-action entrypoint (PFX-4.3 / #6940).
#
# Runs one `apiome pact` command for a GitHub Actions job:
#
#   publish            publish the consumer's pacts for this commit and branch
#   can-i-deploy       gate a pull request or a deploy on the broker's verdict
#   record-deployment  record what was deployed, after the deploy (on merge)
#
# The command's markdown output (`-o markdown`) is written to apiome-pact-<command>.md in the
# workspace, appended to the job summary and — for publish and can-i-deploy on a pull request —
# upserted as one sticky PR comment. The step exits with the CLI's code, as pact-broker does:
# 0 when it worked (or the version is deployable), 1 otherwise. Input problems are refused here
# with the reason, before anything is sent, and also exit 1.
#
# Env (set by action.yml from the inputs):
#   INPUT_COMMAND               publish | can-i-deploy | record-deployment
#   INPUT_BROKER_BASE_URL       broker base URL; empty reads PACT_BROKER_BASE_URL
#   INPUT_BROKER_TOKEN          API key; empty reads PACT_BROKER_TOKEN (or PACT_BROKER_PASSWORD)
#   INPUT_PACTS                 publish: paths, one per line
#   INPUT_PACTICIPANT           can-i-deploy / record-deployment: the application
#   INPUT_VERSION               the application version (action.yml defaults it to the commit)
#   INPUT_BRANCH                publish: the branch (action.yml defaults it to the PR head branch)
#   INPUT_TAGS                  publish: tags, one per line
#   INPUT_ENVIRONMENT           can-i-deploy / record-deployment: the environment's name
#   INPUT_APPLICATION_INSTANCE  record-deployment: optional instance
#   INPUT_RETRY_WHILE_UNKNOWN   can-i-deploy: non-negative integer
#   INPUT_RETRY_INTERVAL        can-i-deploy: non-negative number of seconds
#   INPUT_DRY_RUN               can-i-deploy: true | false
#   INPUT_COMMENT               true | false
#   INPUT_COMMENT_ID            optional sticky-comment key
#   INPUT_GITHUB_TOKEN          token for the sticky comment
#   PR_NUMBER                   the pull request's number (empty outside a pull request)
#   BUILD_URL                   link to this workflow run, recorded with a publish
#   GITHUB_EVENT_NAME, GITHUB_WORKSPACE, GITHUB_OUTPUT, GITHUB_STEP_SUMMARY  set by the runner
#   APIOME_BIN                  CLI binary (default: apiome) — override in tests
#   STICKY_BIN                  sticky-comment script (default: diff-action/sticky_comment.sh)

set -uo pipefail

ACTION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=pact-action/lib.sh
. "${ACTION_DIR}/lib.sh"

APIOME_BIN="${APIOME_BIN:-apiome}"
# The sticky-comment upsert is diff-action's: a repository action is downloaded whole, so the
# sibling folder is always next to this one.
STICKY_BIN="${STICKY_BIN:-${ACTION_DIR}/../diff-action/sticky_comment.sh}"

COMMAND="${INPUT_COMMAND:-}"
WORKSPACE="${GITHUB_WORKSPACE:-$(pwd)}"

# Print a GitHub error annotation and exit 1 (pact-broker's code for every failure).
#
# Args: $* — the reason.
refuse() {
  echo "::error::pact-action: $*"
  set_output exit-code 1
  exit 1
}

# ---------------------------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------------------------

case "${COMMAND}" in
  publish | can-i-deploy | record-deployment) ;;
  "") refuse "input 'command' is required: publish, can-i-deploy or record-deployment" ;;
  *)
    refuse "unsupported command '${COMMAND}': pact-action runs publish, can-i-deploy or" \
      "record-deployment; run any other apiome pact command in a run: step"
    ;;
esac

BROKER_BASE_URL="${INPUT_BROKER_BASE_URL:-${PACT_BROKER_BASE_URL:-}}"
BROKER_TOKEN="${INPUT_BROKER_TOKEN:-${PACT_BROKER_TOKEN:-}}"
[[ -n "${BROKER_BASE_URL}" ]] ||
  refuse "input 'broker-base-url' is required (or set PACT_BROKER_BASE_URL), such as" \
    "https://api.apiome.dev/v1/tenants/<workspace>/pact-broker"
if [[ -z "${BROKER_TOKEN}" && -z "${PACT_BROKER_PASSWORD:-}" ]]; then
  refuse "input 'broker-token' is required (or set PACT_BROKER_TOKEN): an Apiome API key with" \
    "the Pact scopes this command needs — pass it from a repository secret"
fi
case "${BROKER_BASE_URL}" in
  http://* | https://*) ;;
  *) refuse "input 'broker-base-url' must be an http(s) URL (got: ${BROKER_BASE_URL})" ;;
esac

COMMENT="$(bool_input comment "${INPUT_COMMENT:-true}")" || refuse "${COMMENT}"
DRY_RUN="$(bool_input dry-run "${INPUT_DRY_RUN:-false}")" || refuse "${DRY_RUN}"

VERSION="${INPUT_VERSION:-}"
PACTICIPANT="${INPUT_PACTICIPANT:-}"
ENVIRONMENT="${INPUT_ENVIRONMENT:-}"

[[ -n "${VERSION}" ]] || refuse "input 'version' is empty and no commit SHA was found"

# The CLI reads the broker from the environment, so the key never appears on a command line.
export PACT_BROKER_BASE_URL="${BROKER_BASE_URL}"
if [[ -n "${BROKER_TOKEN}" ]]; then
  export PACT_BROKER_TOKEN="${BROKER_TOKEN}"
fi
# A checked-out repository may carry a committed .env; the action's inputs must win.
export APIOME_LOAD_DOTENV=0

args=(pact "${COMMAND}")
case "${COMMAND}" in
  publish)
    pact_paths=()
    while IFS= read -r path; do pact_paths+=("${path}"); done < <(input_lines "${INPUT_PACTS:-}")
    [[ ${#pact_paths[@]} -gt 0 ]] || refuse "input 'pacts' is empty: give pact files or folders, one per line"
    for path in "${pact_paths[@]}"; do
      [[ -e "${WORKSPACE}/${path}" || -e "${path}" ]] ||
        refuse "pact path not found: ${path} — run the consumer's Pact tests before this step"
    done
    args+=("${pact_paths[@]}" --consumer-app-version "${VERSION}")
    [[ -z "${INPUT_BRANCH:-}" ]] || args+=(--branch "${INPUT_BRANCH}")
    while IFS= read -r tag; do args+=(--tag "${tag}"); done < <(input_lines "${INPUT_TAGS:-}")
    [[ -z "${BUILD_URL:-}" ]] || args+=(--build-url "${BUILD_URL}")
    ;;
  can-i-deploy)
    [[ -n "${PACTICIPANT}" ]] || refuse "input 'pacticipant' is required for can-i-deploy"
    [[ -n "${ENVIRONMENT}" ]] || refuse "input 'environment' is required for can-i-deploy"
    RETRIES="${INPUT_RETRY_WHILE_UNKNOWN:-0}"
    INTERVAL="${INPUT_RETRY_INTERVAL:-10}"
    [[ "${RETRIES}" =~ ^[0-9]+$ ]] ||
      refuse "input 'retry-while-unknown' must be a whole number of retries (got: ${RETRIES})"
    [[ "${INTERVAL}" =~ ^[0-9]+([.][0-9]+)?$ ]] ||
      refuse "input 'retry-interval' must be a number of seconds (got: ${INTERVAL})"
    args+=(--pacticipant "${PACTICIPANT}" --version "${VERSION}" --to-environment "${ENVIRONMENT}"
      --retry-while-unknown "${RETRIES}" --retry-interval "${INTERVAL}")
    [[ "${DRY_RUN}" != "true" ]] || args+=(--dry-run)
    ;;
  record-deployment)
    [[ -n "${PACTICIPANT}" ]] || refuse "input 'pacticipant' is required for record-deployment"
    [[ -n "${ENVIRONMENT}" ]] || refuse "input 'environment' is required for record-deployment"
    case "${GITHUB_EVENT_NAME:-}" in
      pull_request | pull_request_target)
        refuse "record-deployment runs after a deploy, on merge — this is a ${GITHUB_EVENT_NAME}" \
          "event, and recording it would tell can-i-deploy the pull request's commit is live." \
          "Run the step on push to your main branch"
        ;;
    esac
    args+=(--pacticipant "${PACTICIPANT}" --version "${VERSION}" --environment "${ENVIRONMENT}")
    [[ -z "${INPUT_APPLICATION_INSTANCE:-}" ]] || args+=(--application-instance "${INPUT_APPLICATION_INSTANCE}")
    ;;
esac
args+=(--output markdown)

# ---------------------------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------------------------

REPORT="${WORKSPACE}/apiome-pact-${COMMAND}.md"
ERRORS="$(mktemp)"
trap 'rm -f "${ERRORS}"' EXIT

echo "pact-action: apiome ${args[*]}"
"${APIOME_BIN}" "${args[@]}" >"${REPORT}" 2>"${ERRORS}"
code=$?

cat "${REPORT}"
if [[ -s "${ERRORS}" ]]; then
  cat "${ERRORS}" >&2
fi

set_output exit-code "${code}"
set_output report-path "${REPORT}"
if [[ "${COMMAND}" == "can-i-deploy" ]]; then
  set_output deployable "$(deployable_from_report "${REPORT}")"
fi

BODY="$(mktemp)"
render_comment "${COMMAND}" "${code}" "${REPORT}" "${ERRORS}" "${PACTICIPANT}" "${ENVIRONMENT}" \
  "${VERSION}" "${DRY_RUN}" >"${BODY}"

if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  cat "${BODY}" >>"${GITHUB_STEP_SUMMARY}"
fi

# ---------------------------------------------------------------------------------------------
# Sticky PR comment (publish and can-i-deploy, pull requests only)
# ---------------------------------------------------------------------------------------------

if [[ "${COMMENT}" == "true" && "${COMMAND}" != "record-deployment" ]]; then
  if [[ -z "${PR_NUMBER:-}" ]]; then
    echo "pact-action: not a pull request; no comment posted"
  else
    key="$(comment_key "${COMMAND}" "${INPUT_COMMENT_ID:-}" "${PACTICIPANT}" "${ENVIRONMENT}")"
    # A failed comment is reported but never changes the step's result.
    if ! STICKY_MARKER="<!-- apiome-pact-action:${key} -->" STICKY_SECTION="" \
      GITHUB_TOKEN="${INPUT_GITHUB_TOKEN:-}" PR_NUMBER="${PR_NUMBER}" \
      "${STICKY_BIN}" "${BODY}"; then
      echo "::warning::pact-action: could not update the pull-request comment; the result is in the job summary"
    fi
  fi
fi
rm -f "${BODY}"

if [[ "${code}" -ne 0 ]]; then
  echo "::error::pact-action: apiome pact ${COMMAND} exited ${code}"
fi
exit "${code}"
