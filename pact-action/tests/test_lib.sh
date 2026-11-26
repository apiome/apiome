#!/usr/bin/env bash
# Unit tests for pact-action/lib.sh (PFX-4.3 / #6940).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=pact-action/lib.sh
. "${ROOT}/lib.sh"

TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

# Assert two strings are equal.
#
# Args: $1 — label, $2 — expected, $3 — actual.
eq() {
  [[ "$2" == "$3" ]] || fail "$1: expected [$2], got [$3]"
}

# bool_input
eq "bool true" "true" "$(bool_input comment true)"
eq "bool TRUE" "true" "$(bool_input comment TRUE)"
eq "bool False" "false" "$(bool_input comment False)"
if out="$(bool_input dry-run yes)"; then fail "bool yes must be refused"; fi
eq "bool refusal" "input 'dry-run' must be true or false (got: yes)" "${out}"
if bool_input dry-run "" >/dev/null; then fail "bool empty must be refused"; fi

# input_lines
eq "lines empty" "" "$(input_lines "")"
eq "lines one" "pacts" "$(input_lines "pacts")"
eq "lines trimmed, blanks dropped" $'a/b.json\nmy pacts\nc' "$(input_lines $'  a/b.json \n\n my pacts\nc\n')"

# deployable_from_report
printf '**Computer says yes \\o/**\n' >"${TMP}/yes.md"
printf '**Computer says no ¯\\_(ツ)_/¯**\n' >"${TMP}/no.md"
printf '**Computer says no ¯\\_(ツ)_/¯ (a verification result is missing)**\n' >"${TMP}/unknown.md"
: >"${TMP}/empty.md"
eq "deployable yes" "true" "$(deployable_from_report "${TMP}/yes.md")"
eq "deployable no" "false" "$(deployable_from_report "${TMP}/no.md")"
eq "deployable unknown" "false" "$(deployable_from_report "${TMP}/unknown.md")"
eq "deployable empty" "" "$(deployable_from_report "${TMP}/empty.md")"
eq "deployable missing file" "" "$(deployable_from_report "${TMP}/nope.md")"

# comment_key
eq "key publish" "publish" "$(comment_key publish "" "" "")"
eq "key publish id" "publish:web-app" "$(comment_key publish web-app "" "")"
eq "key can-i-deploy" "can-i-deploy:Billing-Service@production" \
  "$(comment_key can-i-deploy "" "Billing Service" production)"
eq "key cannot close the marker" "can-i-deploy:x-y-z@prod" "$(comment_key can-i-deploy "" "x-->y <z" prod)"

# render_comment
printf 'Published the pacts of web version abc\n' >"${TMP}/publish.md"
: >"${TMP}/noerr.txt"
body="$(render_comment publish 0 "${TMP}/publish.md" "${TMP}/noerr.txt" "" "" 0123456789abcdef false)"
grep -q "### Pact: published pacts" <<<"${body}" || fail "publish heading"
grep -q 'Version `0123456789ab` — \*\*published\*\*' <<<"${body}" || fail "publish short sha: ${body}"
grep -q "Published the pacts of web version abc" <<<"${body}" || fail "publish report embedded"
if grep -q "<details>" <<<"${body}"; then fail "no messages block without stderr"; fi

printf 'Error: 403 the key lacks pact:publish\n' >"${TMP}/err.txt"
body="$(render_comment publish 1 "${TMP}/empty.md" "${TMP}/err.txt" "" "" abc false)"
grep -q "not published\*\* (exit 1)" <<<"${body}" || fail "publish failure line: ${body}"
grep -q "403 the key lacks pact:publish" <<<"${body}" || fail "stderr shown in messages"

body="$(render_comment can-i-deploy 0 "${TMP}/yes.md" "${TMP}/noerr.txt" "Billing" production abc false)"
grep -q 'can `Billing` deploy to `production`?' <<<"${body}" || fail "cid heading"
grep -q "\*\*yes\*\*" <<<"${body}" || fail "cid yes"
body="$(render_comment can-i-deploy 0 "${TMP}/no.md" "${TMP}/noerr.txt" "Billing" production abc true)"
grep -q "\*\*no\*\*, it cannot be deployed yet" <<<"${body}" || fail "cid no"
grep -q "Dry run" <<<"${body}" || fail "cid dry run note"
body="$(render_comment can-i-deploy 1 "${TMP}/empty.md" "${TMP}/err.txt" "Billing" production abc false)"
grep -q "no verdict\*\*: the check could not run (exit 1)" <<<"${body}" || fail "cid no verdict"

body="$(render_comment record-deployment 0 "${TMP}/empty.md" "${TMP}/noerr.txt" "Billing" production abc false)"
grep -q '`Billing` version `abc` — \*\*recorded\*\* in `production`' <<<"${body}" || fail "record line"
body="$(render_comment record-deployment 1 "${TMP}/empty.md" "${TMP}/noerr.txt" "Billing" production abc false)"
grep -q "not recorded\*\* (exit 1)" <<<"${body}" || fail "record failure"

# set_output
export GITHUB_OUTPUT="${TMP}/out"
set_output exit-code 1
eq "set_output" "exit-code=1" "$(cat "${GITHUB_OUTPUT}")"
unset GITHUB_OUTPUT
set_output exit-code 2 # no runner: silently a no-op, nothing to write to

echo "test_lib: ok"
