#!/usr/bin/env bash
# Smoke tests for the GitLab CI / Bitbucket Pipelines / Jenkins / Azure Pipelines Pact recipes
# (PFX-4.3 / #6940, PFX-4.6 / #6943).
#
# Each job of a recipe is executed the way the runner executes it: its `script:` lines (and
# GitLab's `variables:` block) are pulled out of the YAML and run under `set -e` in a throw-away
# workspace, against a stub `apiome` that logs its arguments and exits with a chosen code. A
# renamed variable, a wrong flag or a lost exit code fails here without a GitLab or Bitbucket
# runner. The guide must embed each recipe byte for byte.
#
# Usage: test_ci_recipes.sh [--recipe gitlab|bitbucket|jenkins|azure|all]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPO_ROOT="$(cd "${ROOT}/.." && pwd)"
DOC="${REPO_ROOT}/apiome-docs/docs/ship/pact-broker/ci-pact.mdx"

# shellcheck source=diff-action/tests/recipe_lib.sh
. "${REPO_ROOT}/diff-action/tests/recipe_lib.sh"

SELECTED="all"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --recipe)
      SELECTED="${2:?--recipe needs a value}"
      shift 2
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT
BIN="${TMP}/bin"
mkdir -p "${BIN}"
export PATH="${BIN}:${PATH}"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

# Print the lines of one job (GitLab) or step (Bitbucket) of a recipe.
#
# The section starts at the first line matching the pattern and ends before the next non-blank
# line indented no deeper than it — the next job, or the next `- step:`.
#
# Args: $1 — recipe file, $2 — awk regex for the section's first line.
# Stdout: the section, header included.
recipe_section() {
  awk -v header="$2" '
    !insec && $0 ~ header { insec = 1; ind = match($0, /[^ ]/); print; next }
    insec {
      if ($0 ~ /^[[:space:]]*$/) { print; next }
      if (match($0, /[^ ]/) <= ind) { exit }
      print
    }
  ' "$1"
}

# Materialise one job of a recipe as a runnable script: the recipe's `variables:` (GitLab's
# top-level block) followed by the job's script lines, under `set -e`.
#
# Args: $1 — recipe file, $2 — section header regex, $3 — destination script.
job_to_shell() {
  local section="${TMP}/section.yml"
  recipe_section "$1" "$2" >"${section}"
  {
    echo "#!/usr/bin/env bash"
    echo "set -e"
    recipe_variable_exports "$1"
    recipe_script_lines "${section}"
  } >"$3"
  chmod +x "$3"
  [[ "$(recipe_script_lines "${section}" | wc -l)" -ge 3 ]] ||
    fail "the job matching [$2] in $1 did not parse into script lines"
}

# Materialise one Jenkins stage as a runnable script: the single-quoted `environment { }` values
# (the broker URL and token come from the test, so PACT_BROKER_* are skipped) followed by the
# stage's `sh '...'` lines, under `set -e` as Jenkins runs `sh` with `-e`.
#
# Args: $1 — Jenkinsfile, $2 — section header regex, $3 — destination script.
jenkins_stage_to_shell() {
  local section="${TMP}/section.groovy"
  recipe_section "$1" "$2" >"${section}"
  {
    echo "#!/usr/bin/env bash"
    echo "set -e"
    sed -nE "s/^[[:space:]]+([A-Z_]+) = '([^']*)'\$/\1 \2/p" "$1" | while read -r key value; do
      [[ "${key}" == PACT_BROKER_* ]] || printf 'export %s=%q\n' "${key}" "${value}"
    done
    sed -nE "s/^[[:space:]]*sh '(.*)'\$/\1/p" "${section}"
  } >"$3"
  chmod +x "$3"
  [[ "$(sed -nE "s/^[[:space:]]*sh '(.*)'\$/\1/p" "${section}" | wc -l)" -ge 1 ]] ||
    fail "the stage matching [$2] in $1 did not parse into sh lines"
}

# Materialise one Azure Pipelines job as a runnable script: the top-level `variables:` followed
# by the body of every `- script: |` block of the job.
#
# Args: $1 — azure-pipelines.yml, $2 — section header regex, $3 — destination script.
azure_job_to_shell() {
  local section="${TMP}/section.yml"
  recipe_section "$1" "$2" >"${section}"
  {
    echo "#!/usr/bin/env bash"
    recipe_variable_exports "$1"
    awk '
      inblk && (/^[[:space:]]*$/ || match($0, /[^ ]/) > ind + 2) { print substr($0, ind + 4); next }
      { inblk = 0 }
      /^[[:space:]]*- script: \|[[:space:]]*$/ { inblk = 1; ind = match($0, /[^ ]/) }
    ' "${section}"
  } >"$3"
  chmod +x "$3"
  [[ "$(wc -l <"$3")" -ge 5 ]] || fail "the job matching [$2] in $1 did not parse into script lines"
}

# Install a stub `apiome`: logs its arguments (one per line) and the broker env, prints a
# report, exits with the given code.
#
# Args: $1 — exit code.
install_stub() {
  cat >"${BIN}/apiome" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$@" >"\${ARGS_LOG}"
env | grep -E '^(PACT_BROKER_BASE_URL|PACT_BROKER_TOKEN|APIOME_LOAD_DOTENV)=' | sort >"\${ENV_LOG}"
echo "stub report (exit $1)"
exit $1
EOF
  chmod +x "${BIN}/apiome"
}

OUT=""
CODE=0
WS=""
# Run a job script in a fresh workspace with a CI environment and the broker credentials.
#
# Args: $1 — script, $2 — broker URL, $3 — token; then KEY=VALUE pairs for the CI environment.
run_job() {
  local script="$1" url="$2" token="$3"
  shift 3
  WS="$(mktemp -d "${TMP}/ws.XXXXXX")"
  mkdir -p "${WS}/pacts"
  export ARGS_LOG="${WS}/args.log" ENV_LOG="${WS}/env.log"
  set +e
  OUT="$(cd "${WS}" && env -u PACT_BROKER_BASE_URL -u PACT_BROKER_TOKEN "$@" \
    ${url:+PACT_BROKER_BASE_URL="${url}"} ${token:+PACT_BROKER_TOKEN="${token}"} "${script}" 2>&1)"
  CODE=$?
  set -e
}

# Run every case for one job.
#
# Args: $1 — label, $2 — script, $3 — name of a function printing the expected CLI arguments,
#   $4 — report file the job keeps (empty when none); then the CI environment pairs.
check_job() {
  local label="$1" script="$2" expected_fn="$3" report="$4"
  shift 4
  local url=https://api.example.com/v1/tenants/acme/pact-broker
  local code
  for code in 0 1; do
    install_stub "${code}"
    run_job "${script}" "${url}" ci-key "$@"
    [[ "${CODE}" -eq "${code}" ]] || fail "${label}: stub exit ${code}, job exit ${CODE}: ${OUT}"
    [[ "$(cat "${ARGS_LOG}")" == "$("${expected_fn}")" ]] ||
      fail "${label}: CLI arguments\n--- expected\n$("${expected_fn}")\n--- got\n$(cat "${ARGS_LOG}")"
    grep -qxF "PACT_BROKER_BASE_URL=${url}" "${ENV_LOG}" || fail "${label}: broker URL not passed"
    grep -qxF "PACT_BROKER_TOKEN=ci-key" "${ENV_LOG}" || fail "${label}: token not passed"
    grep -qxF "APIOME_LOAD_DOTENV=0" "${ENV_LOG}" || fail "${label}: dotenv loading not disabled"
    grep -q "stub report (exit ${code})" <<<"${OUT}" || fail "${label}: report not in the job log"
    if [[ -n "${report}" ]]; then
      grep -q "stub report (exit ${code})" "${WS}/${report}" || fail "${label}: ${report} not written"
    fi
  done
  install_stub 0
  run_job "${script}" "" ci-key "$@"
  [[ "${CODE}" -eq 1 ]] || fail "${label}: missing URL must exit 1, got ${CODE}"
  grep -q "PACT_BROKER_BASE_URL is not set" <<<"${OUT}" || fail "${label}: missing URL reason: ${OUT}"
  [[ ! -e "${ARGS_LOG}" ]] || fail "${label}: the CLI must not run without a broker URL"
  run_job "${script}" "${url}" "" "$@"
  [[ "${CODE}" -eq 1 ]] || fail "${label}: missing token must exit 1, got ${CODE}"
  grep -q "PACT_BROKER_TOKEN is not set" <<<"${OUT}" || fail "${label}: missing token reason: ${OUT}"
  [[ ! -e "${ARGS_LOG}" ]] || fail "${label}: the CLI must not run without a token"
  echo "OK  ${label}"
}

# Assert the guide embeds the recipe byte for byte after its marker.
#
# Args: $1 — recipe file, $2 — marker line.
assert_doc_matches_recipe() {
  [[ -f "${DOC}" ]] || fail "guide not found: ${DOC}"
  local extracted="${TMP}/doc-block.yml"
  doc_fenced_block "${DOC}" "$2" >"${extracted}"
  [[ -s "${extracted}" ]] || fail "no fenced block after marker $2 in ${DOC}"
  diff -u "${extracted}" "$1" || fail "the guide block after $2 has drifted from $1"
}

SHA=0123456789abcdef

gitlab_publish_args() {
  printf '%s\n' pact publish pacts --consumer-app-version "${SHA}" --branch feature/x --build-url https://gitlab.example.com/acme/web/-/jobs/7
}
gitlab_publish_args_main() {
  printf '%s\n' pact publish pacts --consumer-app-version "${SHA}" --branch main --build-url https://gitlab.example.com/acme/web/-/jobs/7
}
cid_args() {
  printf '%s\n' pact can-i-deploy --pacticipant "Billing Service" --version "${SHA}" --to-environment production \
    --retry-while-unknown 12 --retry-interval 10 --output markdown
}
record_args() {
  printf '%s\n' pact record-deployment --pacticipant "Billing Service" --version "${SHA}" --environment production
}
bitbucket_publish_args() {
  printf '%s\n' pact publish pacts --consumer-app-version "${SHA}" --branch feature/x \
    --build-url https://bitbucket.org/acme/web/pipelines/results/7
}

run_gitlab() {
  local recipe="${ROOT}/recipes/.gitlab-ci.yml"
  echo "==> recipe: gitlab"
  [[ -f "${recipe}" ]] || fail "recipe not found: ${recipe}"
  grep -q 'entrypoint: \[""\]' "${recipe}" || fail "gitlab: the image entrypoint must be cleared for a shell"
  grep -q "ghcr.io/apiome/diff-action" "${recipe}" || fail "gitlab: the jobs must run the Apiome CLI image"
  recipe_section "${recipe}" '^pact-record-deployment:' | grep -q 'if: \$CI_COMMIT_BRANCH == \$CI_DEFAULT_BRANCH' ||
    fail "gitlab: record-deployment must run on the default branch only"
  if recipe_section "${recipe}" '^pact-record-deployment:' | grep -q merge_request_event; then
    fail "gitlab: record-deployment must never run in a merge-request pipeline"
  fi

  local mr=(CI_COMMIT_SHA="${SHA}" CI_MERGE_REQUEST_SOURCE_BRANCH_NAME=feature/x
    CI_JOB_URL=https://gitlab.example.com/acme/web/-/jobs/7)
  local main=(CI_COMMIT_SHA="${SHA}" CI_COMMIT_BRANCH=main CI_JOB_URL=https://gitlab.example.com/acme/web/-/jobs/7)

  job_to_shell "${recipe}" '^pact-publish:' "${TMP}/gl-publish.sh"
  check_job "gitlab pact-publish (merge request)" "${TMP}/gl-publish.sh" gitlab_publish_args "" "${mr[@]}"
  check_job "gitlab pact-publish (default branch)" "${TMP}/gl-publish.sh" gitlab_publish_args_main "" "${main[@]}"
  job_to_shell "${recipe}" '^pact-can-i-deploy:' "${TMP}/gl-cid.sh"
  check_job "gitlab pact-can-i-deploy" "${TMP}/gl-cid.sh" cid_args can-i-deploy.md "${mr[@]}"
  job_to_shell "${recipe}" '^pact-record-deployment:' "${TMP}/gl-record.sh"
  check_job "gitlab pact-record-deployment" "${TMP}/gl-record.sh" record_args "" "${main[@]}"

  assert_doc_matches_recipe "${recipe}" "{/* recipe:pact-gitlab */}"
  echo "OK  recipe: gitlab"
}

run_bitbucket() {
  local recipe="${ROOT}/recipes/bitbucket-pipelines.yml"
  echo "==> recipe: bitbucket"
  [[ -f "${recipe}" ]] || fail "recipe not found: ${recipe}"
  grep -q "ghcr.io/apiome/diff-action" "${recipe}" || fail "bitbucket: the steps must run the Apiome CLI image"
  grep -q "pull-requests:" "${recipe}" || fail "bitbucket: the pipeline must be wired to pull requests"
  if recipe_section "${recipe}" '^  pull-requests:' | grep -q "pact-record-deployment"; then
    fail "bitbucket: record-deployment must never run in a pull-request pipeline"
  fi
  recipe_section "${recipe}" '^  branches:' | grep -q "step: \*pact-record-deployment" ||
    fail "bitbucket: record-deployment must run on the main branch"

  local env=(BITBUCKET_COMMIT="${SHA}" BITBUCKET_BRANCH=feature/x
    BITBUCKET_GIT_HTTP_ORIGIN=https://bitbucket.org/acme/web BITBUCKET_BUILD_NUMBER=7)

  job_to_shell "${recipe}" '- step: &pact-publish$' "${TMP}/bb-publish.sh"
  check_job "bitbucket Publish pacts" "${TMP}/bb-publish.sh" bitbucket_publish_args "" "${env[@]}"
  job_to_shell "${recipe}" '- step: &pact-can-i-deploy$' "${TMP}/bb-cid.sh"
  check_job "bitbucket Pact can-i-deploy" "${TMP}/bb-cid.sh" cid_args can-i-deploy.md "${env[@]}"
  job_to_shell "${recipe}" '- step: &pact-record-deployment$' "${TMP}/bb-record.sh"
  check_job "bitbucket Record deployment" "${TMP}/bb-record.sh" record_args "" "${env[@]}"

  assert_doc_matches_recipe "${recipe}" "{/* recipe:pact-bitbucket */}"
  echo "OK  recipe: bitbucket"
}

JENKINS_ENV_BASE=(GIT_COMMIT="${SHA}" BUILD_URL=https://jenkins.example.com/job/web/7/)

jenkins_publish_args() {
  printf '%s\n' pact publish pacts --consumer-app-version "${SHA}" --branch feature/x --build-url https://jenkins.example.com/job/web/7/
}
jenkins_publish_args_main() {
  printf '%s\n' pact publish pacts --consumer-app-version "${SHA}" --branch main --build-url https://jenkins.example.com/job/web/7/
}

run_jenkins() {
  local recipe="${ROOT}/recipes/Jenkinsfile"
  echo "==> recipe: jenkins"
  [[ -f "${recipe}" ]] || fail "recipe not found: ${recipe}"
  grep -q "credentials('apiome-pact-broker-token')" "${recipe}" ||
    fail "jenkins: the broker key must come from a Jenkins credential"
  if grep -qE '^[[:space:]]*sh +"' "${recipe}"; then
    fail "jenkins: commands must be single-quoted so Groovy never interpolates the key"
  fi
  recipe_section "${recipe}" "stage[(]'Record deployment'[)]" | grep -q "not { changeRequest() }" ||
    fail "jenkins: record-deployment must never run for a change request"
  recipe_section "${recipe}" "stage[(]'Record deployment'[)]" | grep -q "branch 'main'" ||
    fail "jenkins: record-deployment must run on the main branch"

  local pr=("${JENKINS_ENV_BASE[@]}" CHANGE_BRANCH=feature/x BRANCH_NAME=PR-12)
  local main=("${JENKINS_ENV_BASE[@]}" BRANCH_NAME=main)

  jenkins_stage_to_shell "${recipe}" "stage[(]'Publish pacts'[)]" "${TMP}/jk-publish.sh"
  check_job "jenkins Publish pacts (pull request)" "${TMP}/jk-publish.sh" jenkins_publish_args "" "${pr[@]}"
  check_job "jenkins Publish pacts (main)" "${TMP}/jk-publish.sh" jenkins_publish_args_main "" "${main[@]}"
  jenkins_stage_to_shell "${recipe}" "stage[(]'Can I deploy[?]'[)]" "${TMP}/jk-cid.sh"
  check_job "jenkins Can I deploy?" "${TMP}/jk-cid.sh" cid_args can-i-deploy.md "${pr[@]}"
  jenkins_stage_to_shell "${recipe}" "stage[(]'Record deployment'[)]" "${TMP}/jk-record.sh"
  check_job "jenkins Record deployment" "${TMP}/jk-record.sh" record_args "" "${main[@]}"

  # The install stage is a no-op when apiome is already on PATH, and fails when the download fails.
  install_stub 0
  jenkins_stage_to_shell "${recipe}" "stage[(]'Install Apiome CLI'[)]" "${TMP}/jk-install.sh"
  (cd "${TMP}" && bash "${TMP}/jk-install.sh") || fail "jenkins: install must pass when apiome is on PATH"
  assert_install_downloads "${TMP}/jk-install.sh" jenkins

  assert_doc_matches_recipe "${recipe}" "{/* recipe:pact-jenkins */}"
  echo "OK  recipe: jenkins"
}

# Assert an install script downloads the installer and fails with it when apiome is missing.
#
# Args: $1 — install script, $2 — label.
assert_install_downloads() {
  local bin2="${TMP}/bin-no-apiome" log="${TMP}/curl.log"
  mkdir -p "${bin2}"
  printf '#!/bin/sh\necho "$@" >"%s"\nexit 22\n' "${log}" >"${bin2}/curl"
  chmod +x "${bin2}/curl"
  ln -sf "$(command -v bash)" "${bin2}/bash"
  ln -sf "$(command -v sh)" "${bin2}/sh"
  ln -sf "$(command -v dirname)" "${bin2}/dirname"
  set +e
  (cd "${TMP}" && PATH="${bin2}" bash "$1" >/dev/null 2>&1)
  local code=$?
  set -e
  [[ "${code}" -ne 0 ]] || fail "$2: a failed installer download must fail the job"
  grep -q "https://get.apiome.dev" "${log}" || fail "$2: the install must download from get.apiome.dev"
}

AZURE_PR_ENV=(SYSTEM_PULLREQUEST_SOURCECOMMITID="${SHA}" SYSTEM_PULLREQUEST_SOURCEBRANCH=refs/heads/feature/x
  BUILD_SOURCEVERSION=fedcba9876543210 BUILD_SOURCEBRANCH=refs/pull/12/merge)
AZURE_MAIN_ENV=(BUILD_SOURCEVERSION="${SHA}" BUILD_SOURCEBRANCH=refs/heads/main)
AZURE_COMMON=(SYSTEM_COLLECTIONURI=https://dev.azure.com/acme/ SYSTEM_TEAMPROJECT=web BUILD_BUILDID=7)

azure_publish_args() {
  printf '%s\n' pact publish pacts --consumer-app-version "${SHA}" --branch feature/x \
    --build-url "https://dev.azure.com/acme/web/_build/results?buildId=7"
}
azure_publish_args_main() {
  printf '%s\n' pact publish pacts --consumer-app-version "${SHA}" --branch main \
    --build-url "https://dev.azure.com/acme/web/_build/results?buildId=7"
}

run_azure() {
  local recipe="${ROOT}/recipes/azure-pipelines.yml"
  echo "==> recipe: azure"
  [[ -f "${recipe}" ]] || fail "recipe not found: ${recipe}"
  grep -q "^pr:" "${recipe}" || fail "azure: the pipeline must be wired to pull requests"
  [[ "$(grep -c 'PACT_BROKER_TOKEN: \$(PACT_BROKER_TOKEN)' "${recipe}")" -eq 3 ]] ||
    fail "azure: every pact step must map the secret broker token into its environment"
  local record
  record="$(recipe_section "${recipe}" '^  - job: RecordDeployment')"
  grep -q "ne(variables\['Build.Reason'\], 'PullRequest')" <<<"${record}" ||
    fail "azure: record-deployment must never run in a pull-request run"
  grep -q "refs/heads/main" <<<"${record}" || fail "azure: record-deployment must run on main"

  azure_job_to_shell "${recipe}" '^  - job: Publish$' "${TMP}/az-publish.sh"
  check_job "azure Publish pacts (pull request)" "${TMP}/az-publish.sh" azure_publish_args "" "${AZURE_COMMON[@]}" "${AZURE_PR_ENV[@]}"
  check_job "azure Publish pacts (main)" "${TMP}/az-publish.sh" azure_publish_args_main "" "${AZURE_COMMON[@]}" "${AZURE_MAIN_ENV[@]}"
  azure_job_to_shell "${recipe}" '^  - job: CanIDeploy$' "${TMP}/az-cid.sh"
  check_job "azure Pact can-i-deploy" "${TMP}/az-cid.sh" cid_args can-i-deploy.md "${AZURE_COMMON[@]}" "${AZURE_PR_ENV[@]}"
  azure_job_to_shell "${recipe}" '^  - job: RecordDeployment$' "${TMP}/az-record.sh"
  check_job "azure Record deployment" "${TMP}/az-record.sh" record_args "" "${AZURE_COMMON[@]}" "${AZURE_MAIN_ENV[@]}"

  # Azure leaves an unset secret as the literal macro text; the job must treat that as missing.
  install_stub 0
  run_job "${TMP}/az-publish.sh" "https://api.example.com/v1/tenants/acme/pact-broker" '$(PACT_BROKER_TOKEN)' \
    "${AZURE_COMMON[@]}" "${AZURE_MAIN_ENV[@]}"
  [[ "${CODE}" -eq 1 ]] || fail "azure: an unexpanded secret macro must exit 1, got ${CODE}"
  grep -q "PACT_BROKER_TOKEN is not set" <<<"${OUT}" || fail "azure: unexpanded macro reason: ${OUT}"

  install_stub 0
  azure_job_to_shell "${recipe}" '^  - job: Publish$' "${TMP}/az-all.sh"
  assert_install_downloads "${TMP}/az-all.sh" azure

  assert_doc_matches_recipe "${recipe}" "{/* recipe:pact-azure */}"
  echo "OK  recipe: azure"
}

case "${SELECTED}" in
  gitlab) run_gitlab ;;
  bitbucket) run_bitbucket ;;
  jenkins) run_jenkins ;;
  azure) run_azure ;;
  all)
    run_gitlab
    run_bitbucket
    run_jenkins
    run_azure
    ;;
  *)
    echo "unknown recipe: ${SELECTED} (expected gitlab, bitbucket, jenkins, azure, or all)" >&2
    exit 2
    ;;
esac

echo "test_ci_recipes: ok (${SELECTED})"
