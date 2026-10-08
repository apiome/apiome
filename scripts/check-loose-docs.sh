#!/usr/bin/env bash
# Loose-docs lint (DOCS-1.14, #5631).
#
# Product documentation lives on the documentation site (apiome-docs/docs/, which this skips). This fails when a
# Markdown file under apiome-*/docs/ is neither README.md, CHANGELOG.md nor AGENTS.md, nor listed in
# scripts/loose-docs-allowlist.txt (the contributor references that code points at by path). It
# also fails when an allow-listed file no longer exists, so the list cannot rot.
#
# Usage: scripts/check-loose-docs.sh [repo-root]   (default: the repository this script lives in)
# Checks tracked files plus untracked, non-ignored ones, so it catches a new note before `git add`.
# (In a git pathspec `*` also matches `/`, so `apiome-*/docs/*.md` covers nested folders too.)
set -euo pipefail

root="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
allowlist="$root/scripts/loose-docs-allowlist.txt"
cd "$root"

allowed=""
if [[ -f "$allowlist" ]]; then
  allowed="$(grep -v '^\s*#' "$allowlist" | sed '/^\s*$/d' || true)"
fi

problems=0

while IFS= read -r file; do
  [[ -z "$file" ]] && continue
  case "$(basename "$file")" in
    README.md | CHANGELOG.md | AGENTS.md) continue ;;
  esac
  if ! grep -qxF "$file" <<<"$allowed"; then
    echo "check-loose-docs: $file — new Markdown under apiome-*/docs/. Write it as a page of the" \
      "documentation site (apiome-docs/docs/; see admin/contribute-to-the-docs) instead, or list it" \
      "in scripts/loose-docs-allowlist.txt if code points at it." >&2
    problems=$((problems + 1))
  fi
done < <(git ls-files --cached --others --exclude-standard -- 'apiome-*/docs/*.md' ':!:apiome-docs/*' | sort -u)

while IFS= read -r file; do
  [[ -z "$file" ]] && continue
  if [[ ! -f "$file" ]]; then
    echo "check-loose-docs: $file is allow-listed but does not exist; remove it from scripts/loose-docs-allowlist.txt." >&2
    problems=$((problems + 1))
  fi
done <<<"$allowed"

if ((problems > 0)); then
  echo "check-loose-docs: $problems problem(s)." >&2
  exit 1
fi
echo "check-loose-docs: no loose Markdown under apiome-*/docs/."
