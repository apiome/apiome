#!/usr/bin/env bash
# Run all pact-action shell tests (PFX-4.3 / #6940).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"

fail=0
for t in tests/test_*.sh; do
  echo "==> ${t}"
  if bash "${t}"; then
    echo "OK ${t}"
  else
    echo "FAIL ${t}" >&2
    fail=1
  fi
done

if [[ "${fail}" -ne 0 ]]; then
  echo "pact-action tests failed" >&2
  exit 1
fi
echo "All pact-action tests passed"
