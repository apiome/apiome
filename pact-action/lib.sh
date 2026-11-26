#!/usr/bin/env bash
# Pure helpers for apiome/pact-action (PFX-4.3 / #6940). Sourced by entrypoint.sh and the tests;
# nothing here reaches the network. Written for bash 3.2 (macOS) as well as the runners' bash 5.

# Write one step output, or print it when GITHUB_OUTPUT is unset (a local run).
#
# Args: $1 — output name, $2 — value (single line).
set_output() {
  if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
    printf '%s=%s\n' "$1" "$2" >>"${GITHUB_OUTPUT}"
  fi
}

# Normalise a true/false input.
#
# Args: $1 — input name (for the message), $2 — raw value.
# Stdout: `true` or `false`; on anything else, the refusal reason.
# Returns: 0 for a valid value, 1 otherwise.
bool_input() {
  case "$(printf '%s' "$2" | tr '[:upper:]' '[:lower:]')" in
    true) echo true ;;
    false) echo false ;;
    *)
      echo "input '$1' must be true or false (got: $2)"
      return 1
      ;;
  esac
}

# Split a multi-line input into its non-empty lines, each trimmed.
#
# Args: $1 — the raw input (lines separated by newlines).
# Stdout: one value per line; nothing for an empty input.
input_lines() {
  local line
  while IFS= read -r line || [[ -n "${line}" ]]; do
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    [[ -z "${line}" ]] || printf '%s\n' "${line}"
  done <<<"$1"
}

# Read can-i-deploy's verdict from its markdown output.
#
# Args: $1 — the report file.
# Stdout: `true` ("Computer says yes"), `false` ("Computer says no", including a missing result),
#   or nothing when the command printed no verdict (it failed before asking).
deployable_from_report() {
  if grep -q "Computer says yes" "$1" 2>/dev/null; then
    echo true
  elif grep -q "Computer says no" "$1" 2>/dev/null; then
    echo false
  fi
}

# The key that names one sticky comment, safe inside an HTML comment.
#
# Args: $1 — command, $2 — comment-id input, $3 — pacticipant, $4 — environment.
# Stdout: e.g. `can-i-deploy:Billing-Service@production`, `publish`, `publish:web-app`.
comment_key() {
  local key="$1"
  if [[ -n "$2" ]]; then
    key="${key}:$2"
  elif [[ "$1" == "can-i-deploy" ]]; then
    key="${key}:$3@$4"
  fi
  # Anything but a plain name character becomes '-', squeezed, so `-->` can never close the marker.
  printf '%s' "${key}" | tr -c 'A-Za-z0-9._@:/+' '-' | tr -s '-'
  echo
}

# Render the job-summary / PR-comment body for one run.
#
# Args: $1 — command, $2 — exit code, $3 — report file (the CLI's markdown stdout),
#   $4 — stderr file, $5 — pacticipant, $6 — environment, $7 — version, $8 — dry-run (true|false).
# Stdout: markdown.
render_comment() {
  local command="$1" code="$2" report="$3" errors="$4"
  local pacticipant="$5" environment="$6" version="$7" dry_run="$8"
  local short="${version:0:12}"

  case "${command}" in
    publish)
      echo "### Pact: published pacts"
      echo
      if [[ "${code}" -eq 0 ]]; then
        echo "Version \`${short}\` — **published**."
      else
        echo "Version \`${short}\` — **not published** (exit ${code})."
      fi
      ;;
    can-i-deploy)
      echo "### Pact: can \`${pacticipant}\` deploy to \`${environment}\`?"
      echo
      local verdict
      verdict="$(deployable_from_report "${report}")"
      if [[ "${verdict}" == "true" ]]; then
        echo "Version \`${short}\` — **yes**, it can be deployed."
      elif [[ "${verdict}" == "false" ]]; then
        echo "Version \`${short}\` — **no**, it cannot be deployed yet."
      else
        echo "Version \`${short}\` — **no verdict**: the check could not run (exit ${code})."
      fi
      if [[ "${dry_run}" == "true" ]]; then
        echo
        echo "_Dry run: the verdict is reported but does not fail the check._"
      fi
      ;;
    record-deployment)
      echo "### Pact: recorded deployment"
      echo
      if [[ "${code}" -eq 0 ]]; then
        echo "\`${pacticipant}\` version \`${short}\` — **recorded** in \`${environment}\`."
      else
        echo "\`${pacticipant}\` version \`${short}\` — **not recorded** (exit ${code})."
      fi
      ;;
  esac

  if [[ -s "${report}" ]]; then
    echo
    cat "${report}"
  fi
  if [[ -s "${errors}" ]]; then
    echo
    echo "<details><summary>Messages</summary>"
    echo
    echo '```text'
    cat "${errors}"
    echo '```'
    echo
    echo "</details>"
  fi
}
