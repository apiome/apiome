#!/usr/bin/env bash
# GitHub Action entrypoint for apiome/diff-action (CTG-2.2 / #4472).
# Runs `apiome diff --format md`, upserts a sticky PR comment, then exits with
# the CLI exit code (0 = pass, 1 = gate failed, 2 = operational error).
# GVM-3.4 (#5872): with fix-suggestions (default true) it also runs
# `apiome lint suggest` on the spec, writes the full patch and overlay for a
# workflow artefact, posts GitHub suggestion blocks for single-region fixes inside
# the PR diff, and keeps a second "fixes" section in the same sticky comment.
# Suggested fixes never change the exit code and nothing is pushed to the branch.

set -uo pipefail

APIOME_BIN="${APIOME_BIN:-apiome}"
STICKY_BIN="${STICKY_BIN:-sticky_comment.sh}"
FIX_SUGGESTIONS_BIN="${FIX_SUGGESTIONS_BIN:-fix_suggestions.sh}"
CI_ENTRYPOINT="${CI_ENTRYPOINT:-ci_entrypoint.sh}"

# Dual mode (CTG-2.4 / #4474): the GitHub Action runs this image with no
# arguments and configures everything through INPUT_* env vars. Any argument
# means the image was run as a plain CLI wrapper by a GitLab/Bitbucket recipe or
# `docker run`, so hand off to the pass-through entrypoint.
if [[ $# -gt 0 ]]; then
  exec "${CI_ENTRYPOINT}" "$@"
fi
WORKSPACE="${GITHUB_WORKSPACE:-.}"
CHANGELOG_REL="${APIOME_CHANGELOG_PATH:-.apiome-diff-changelog.md}"
CHANGELOG_PATH="${WORKSPACE%/}/${CHANGELOG_REL#./}"
# GVM-3.4: the artefact files, workspace-relative so an upload-artifact step can find them.
FIX_PATCH_REL="${APIOME_FIX_PATCH_PATH:-.apiome-lint-fixes.patch.json}"
FIX_OVERLAY_REL="${APIOME_FIX_OVERLAY_PATH:-.apiome-lint-fixes.overlay.json}"

SPEC="${INPUT_SPEC:-}"
PROJECT="${INPUT_PROJECT:-}"
FAIL_ON="${INPUT_FAIL_ON:-breaking}"
API_KEY="${INPUT_API_KEY:-}"
TENANT="${INPUT_TENANT:-}"
BASE_URL="${INPUT_BASE_URL:-https://api.apiome.dev}"
COMMENT="${INPUT_COMMENT:-true}"
BLAST_RADIUS="${INPUT_BLAST_RADIUS:-true}"
# XPC-4.5 (#5749): empty means "the project's style-guide policy decides".
MODE="${INPUT_MODE:-}"
TRANSITIVE="${INPUT_TRANSITIVE:-}"
CATEGORY="${INPUT_CATEGORY:-}"
FIX_SUGGESTIONS="${INPUT_FIX_SUGGESTIONS:-true}"
GITHUB_TOKEN="${INPUT_GITHUB_TOKEN:-${GITHUB_TOKEN:-}}"

log() {
  echo "$*" >&2
}

write_output() {
  local name="$1"
  local value="$2"
  if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
    {
      echo "${name}=${value}"
    } >>"${GITHUB_OUTPUT}"
  fi
}

resolve_head_sha() {
  if [[ -n "${HEAD_SHA:-}" ]]; then
    echo "${HEAD_SHA}"
    return 0
  fi
  if [[ -n "${GITHUB_EVENT_PATH:-}" && -f "${GITHUB_EVENT_PATH}" ]]; then
    jq -r '.pull_request.head.sha // empty' "${GITHUB_EVENT_PATH}" 2>/dev/null || true
  fi
}

resolve_pr_number() {
  if [[ -n "${PR_NUMBER:-}" ]]; then
    echo "${PR_NUMBER}"
    return 0
  fi
  if [[ -n "${GITHUB_EVENT_PATH:-}" && -f "${GITHUB_EVENT_PATH}" ]]; then
    jq -r '
      .pull_request.number // .issue.number // empty
    ' "${GITHUB_EVENT_PATH}" 2>/dev/null || true
  fi
}

if [[ -z "${SPEC}" ]]; then
  echo "::error::Input 'spec' is required"
  exit 2
fi
if [[ -z "${PROJECT}" ]]; then
  echo "::error::Input 'project' is required"
  exit 2
fi
if [[ -z "${API_KEY}" ]]; then
  echo "::error::Input 'api-key' is required"
  exit 2
fi
if [[ -z "${TENANT}" ]]; then
  echo "::error::Input 'tenant' is required"
  exit 2
fi

case "${FAIL_ON}" in
  breaking|warn) ;;
  *)
    echo "::error::Input 'fail-on' must be 'breaking' or 'warn' (got: ${FAIL_ON})"
    exit 2
    ;;
esac

case "${BLAST_RADIUS}" in
  true|false) ;;
  *)
    echo "::error::Input 'blast-radius' must be 'true' or 'false' (got: ${BLAST_RADIUS})"
    exit 2
    ;;
esac

case "${FIX_SUGGESTIONS}" in
  true|false) ;;
  *)
    echo "::error::Input 'fix-suggestions' must be 'true' or 'false' (got: ${FIX_SUGGESTIONS})"
    exit 2
    ;;
esac

case "${TRANSITIVE}" in
  ""|true|false) ;;
  *)
    echo "::error::Input 'transitive' must be 'true', 'false' or empty (got: ${TRANSITIVE})"
    exit 2
    ;;
esac

cd "${WORKSPACE}"

SPEC_PATH="${SPEC}"
if [[ ! -f "${SPEC_PATH}" ]]; then
  echo "::error::Spec file not found: ${SPEC_PATH}"
  exit 2
fi

export APIOME_API_KEY="${API_KEY}"
export APIOME_TENANT_ID="${TENANT}"
export APIOME_BASE_URL="${BASE_URL}"
export APIOME_LOAD_DOTENV="${APIOME_LOAD_DOTENV:-0}"

# CDG-3.6 (#5971): the blast-radius line under each breaking change of the changelog.
DIFF_FLAGS=()
if [[ "${BLAST_RADIUS}" == "true" ]]; then
  DIFF_FLAGS+=(--blast-radius)
fi
# XPC-4.5 (#5749): the compatibility mode, passed only when set so the policy applies otherwise.
# The CLI validates the values (exit 2 on an unknown one).
if [[ -n "${MODE}" ]]; then
  DIFF_FLAGS+=(--mode "${MODE}")
fi
if [[ "${TRANSITIVE}" == "true" ]]; then
  DIFF_FLAGS+=(--transitive)
elif [[ "${TRANSITIVE}" == "false" ]]; then
  DIFF_FLAGS+=(--no-transitive)
fi
if [[ -n "${CATEGORY}" ]]; then
  DIFF_FLAGS+=(--category "${CATEGORY}")
fi

log "Running: ${APIOME_BIN} diff ${SPEC_PATH} --against ${PROJECT} --fail-on ${FAIL_ON} --format md ${DIFF_FLAGS[*]:-}"

ERR_PATH="$(mktemp)"
set +e
"${APIOME_BIN}" diff "${SPEC_PATH}" \
  --against "${PROJECT}" \
  --fail-on "${FAIL_ON}" \
  --format md \
  ${DIFF_FLAGS[@]+"${DIFF_FLAGS[@]}"} \
  >"${CHANGELOG_PATH}" 2>"${ERR_PATH}"
DIFF_EXIT=$?
set -e
if [[ -s "${ERR_PATH}" ]]; then
  cat "${ERR_PATH}" >&2
fi
rm -f "${ERR_PATH}"

# Also echo changelog to the job log for reviewers who skip the PR comment.
if [[ -s "${CHANGELOG_PATH}" ]]; then
  log "----- apiome diff changelog (md) -----"
  cat "${CHANGELOG_PATH}" >&2 || true
  log "----- end changelog -----"
fi

write_output "exit-code" "${DIFF_EXIT}"
write_output "changelog-path" "${CHANGELOG_REL}"

HEADER=""
case "${DIFF_EXIT}" in
  0) HEADER="### Apiome contract gate: passed" ;;
  1) HEADER="### Apiome contract gate: failed (threshold: \`${FAIL_ON}\`)" ;;
  2)
    echo "::error::Apiome diff operational error (exit 2)"
    HEADER="### Apiome contract gate: error"
    ;;
  *)
    echo "::error::Apiome diff unexpected exit code ${DIFF_EXIT}"
    HEADER="### Apiome contract gate: unexpected exit \`${DIFF_EXIT}\`"
    ;;
esac

COMMENT_BODY_PATH="$(mktemp)"
{
  echo "${HEADER}"
  echo
  echo "Compared \`${SPEC_PATH}\` against \`${PROJECT}\`."
  echo
  if [[ -s "${CHANGELOG_PATH}" ]]; then
    cat "${CHANGELOG_PATH}"
  else
    echo "_No changelog output._"
  fi
} >"${COMMENT_BODY_PATH}"

should_comment=false
case "$(echo "${COMMENT}" | tr '[:upper:]' '[:lower:]')" in
  true|1|yes) should_comment=true ;;
esac

PR_NUM="$(resolve_pr_number)"
EVENT_NAME="${GITHUB_EVENT_NAME:-}"

# post_section <section> <body-file>: upsert one section of the sticky PR comment.
post_section() {
  local section="$1"
  local body_file="$2"
  local sticky_exit
  set +e
  STICKY_SECTION="${section}" "${STICKY_BIN}" "${body_file}"
  sticky_exit=$?
  set -e
  if [[ "${sticky_exit}" -ne 0 ]]; then
    log "warning: sticky PR comment (${section}) failed (exit ${sticky_exit}); continuing with diff exit ${DIFF_EXIT}"
  fi
}

can_comment=false
if [[ "${should_comment}" == "true" ]]; then
  if [[ -n "${PR_NUM}" ]]; then
    can_comment=true
    export GITHUB_TOKEN
    export PR_NUMBER="${PR_NUM}"
    post_section diff "${COMMENT_BODY_PATH}"
  else
    log "sticky comment skipped (no pull request number; event=${EVENT_NAME:-unknown})"
  fi
else
  log "sticky comment disabled (comment=${COMMENT})"
fi

# GVM-3.4 (#5872): suggested lint fixes for the spec. Failures are logged, never fatal.
if [[ "${FIX_SUGGESTIONS}" == "true" ]]; then
  FIX_DIR="$(mktemp -d)"
  SPEC_REL="${SPEC_PATH#./}"
  ARTIFACT_URL=""
  if [[ -n "${GITHUB_RUN_ID:-}" && -n "${GITHUB_REPOSITORY:-}" ]]; then
    ARTIFACT_URL="${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}#artifacts"
  fi
  SUGGEST_FLAGS=(--path "${SPEC_REL}")
  MARKDOWN_FLAGS=()
  if [[ -n "${ARTIFACT_URL}" ]]; then
    MARKDOWN_FLAGS+=(--artifact-url "${ARTIFACT_URL}")
  fi
  log "Running: ${APIOME_BIN} lint suggest ${SPEC_PATH} --path ${SPEC_REL}"
  set +e
  "${APIOME_BIN}" lint suggest "${SPEC_PATH}" "${SUGGEST_FLAGS[@]}" --format json -o "${FIX_DIR}/fixes.json" \
    && "${APIOME_BIN}" lint suggest "${SPEC_PATH}" "${SUGGEST_FLAGS[@]}" --format patch -o "${FIX_PATCH_REL}" \
    && "${APIOME_BIN}" lint suggest "${SPEC_PATH}" "${SUGGEST_FLAGS[@]}" --format overlay -o "${FIX_OVERLAY_REL}" \
    && "${APIOME_BIN}" lint suggest "${SPEC_PATH}" "${SUGGEST_FLAGS[@]}" --format markdown \
      ${MARKDOWN_FLAGS[@]+"${MARKDOWN_FLAGS[@]}"} -o "${FIX_DIR}/fixes.md"
  SUGGEST_EXIT=$?
  set -e

  if [[ "${SUGGEST_EXIT}" -eq 0 ]]; then
    FIX_COUNT="$(jq -r '.ready // 0' "${FIX_DIR}/fixes.json" 2>/dev/null || echo 0)"
    write_output "fix-count" "${FIX_COUNT}"
    write_output "fix-patch-path" "${FIX_PATCH_REL}"
    write_output "fix-overlay-path" "${FIX_OVERLAY_REL}"
    log "suggested lint fixes: ${FIX_COUNT} ready (patch: ${FIX_PATCH_REL}, overlay: ${FIX_OVERLAY_REL})"
    if [[ "${can_comment}" == "true" ]]; then
      HEAD="$(resolve_head_sha)"
      set +e
      POSTED="$(HEAD_SHA="${HEAD}" "${FIX_SUGGESTIONS_BIN}" "${FIX_DIR}/fixes.json" | tail -n 1)"
      set -e
      POSTED="${POSTED:-0}"
      if [[ "${POSTED}" =~ ^[0-9]+$ && "${POSTED}" -gt 0 ]]; then
        {
          echo
          echo "${POSTED} suggestion block(s) on the changed lines can be accepted in one click from the review."
        } >>"${FIX_DIR}/fixes.md"
      fi
      post_section fixes "${FIX_DIR}/fixes.md"
    fi
  else
    log "warning: apiome lint suggest failed (exit ${SUGGEST_EXIT}); no suggested fixes this run"
    write_output "fix-count" ""
    if [[ "${can_comment}" == "true" ]]; then
      {
        echo "### Suggested fixes"
        echo
        echo "_Suggested fixes could not be computed for \`${SPEC_REL}\` this run; see the job log._"
      } >"${FIX_DIR}/fixes.md"
      post_section fixes "${FIX_DIR}/fixes.md"
    fi
  fi
  rm -rf "${FIX_DIR}"
fi

rm -f "${COMMENT_BODY_PATH}"
exit "${DIFF_EXIT}"
