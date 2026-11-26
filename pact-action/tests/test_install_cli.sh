#!/usr/bin/env bash
# Tests for pact-action/install_cli.sh (PFX-4.3 / #6940), against a stub curl and installer.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

BIN="${TMP}/bin"
mkdir -p "${BIN}"
# A PATH with the basics but no apiome: the system dirs plus the stub folder.
BASE_PATH="${BIN}:/usr/bin:/bin"

# Stub curl: writes an installer that logs its arguments, or fails the download.
#
# Args: $1 — `ok`, `fail-download` or `fail-install`.
install_curl_stub() {
  local mode="$1"
  cat >"${BIN}/curl" <<EOF
#!/usr/bin/env bash
echo "curl \$*" >>"${TMP}/curl.log"
[[ "${mode}" != "fail-download" ]] || exit 22
out=""
while [[ \$# -gt 0 ]]; do
  if [[ "\$1" == "-o" ]]; then out="\$2"; shift; fi
  shift
done
cat >"\${out}" <<'INSTALLER'
echo "installer \$*" >>"${TMP}/installer.log"
[ "${mode}" != "fail-install" ] || exit 3
INSTALLER
EOF
  chmod +x "${BIN}/curl"
}

run() {
  set +e
  OUT="$(PATH="${BASE_PATH}" HOME="${TMP}/home" CURL_BIN="${BIN}/curl" GITHUB_PATH="${TMP}/github_path" \
    APIOME_VERSION="${1:-}" bash "${ROOT}/install_cli.sh" 2>&1)"
  CODE=$?
  set -e
}

# Installs the requested version for the user and puts ~/.local/bin on the next steps' PATH.
rm -f "${TMP}"/*.log "${TMP}/github_path"
install_curl_stub ok
run v1.2.0
[[ "${CODE}" -eq 0 ]] || fail "install: expected 0, got ${CODE}: ${OUT}"
grep -q "curl -fsSL https://get.apiome.dev -o " "${TMP}/curl.log" || fail "installer URL: $(cat "${TMP}/curl.log")"
grep -qxF "installer --user --no-modify-path --version v1.2.0" "${TMP}/installer.log" ||
  fail "installer flags: $(cat "${TMP}/installer.log")"
grep -qxF "${TMP}/home/.local/bin" "${TMP}/github_path" || fail "GITHUB_PATH not updated"

# Empty version means main.
rm -f "${TMP}"/*.log
run ""
grep -qxF "installer --user --no-modify-path --version main" "${TMP}/installer.log" || fail "default version"

# A failed download or install fails the step with the reason.
rm -f "${TMP}"/*.log
install_curl_stub fail-download
run main
[[ "${CODE}" -eq 1 ]] || fail "download failure: expected 1, got ${CODE}"
grep -q "::error::pact-action: could not download the Apiome CLI installer" <<<"${OUT}" || fail "download reason"
install_curl_stub fail-install
run main
[[ "${CODE}" -eq 1 ]] || fail "install failure: expected 1, got ${CODE}"
grep -q "::error::pact-action: the Apiome CLI installer failed (version main)" <<<"${OUT}" || fail "install reason"

# An apiome already on PATH is used as it is: nothing is downloaded.
rm -f "${TMP}"/*.log
install_curl_stub ok
printf '#!/usr/bin/env bash\n' >"${BIN}/apiome"
chmod +x "${BIN}/apiome"
run main
[[ "${CODE}" -eq 0 ]] || fail "present: expected 0"
grep -q "using the apiome already on PATH" <<<"${OUT}" || fail "present message"
[[ ! -e "${TMP}/curl.log" ]] || fail "nothing must be downloaded when apiome is present"

echo "test_install_cli: ok"
