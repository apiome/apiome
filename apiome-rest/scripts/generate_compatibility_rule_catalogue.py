#!/usr/bin/env python3
"""
Generate the compatibility rule catalogue section of the Compatibility modes docs page (XPC-4.5).

Rewrites the block between the ``compatibility-rule-catalogue:start`` / ``:end`` markers in
apiome-docs/docs/govern/compatibility-modes.md from :mod:`app.compatibility_rule_catalogue` — the
same data ``GET /v1/compatibility/rules`` serves — so the docs never restate a severity by hand.

Run from apiome-rest:
    uv run python scripts/generate_compatibility_rule_catalogue.py
"""

from __future__ import annotations

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
src = project_root / "src"
if str(src) not in sys.path:
    sys.path.insert(0, str(src))

from app.compatibility_rule_catalogue import replace_catalogue_section  # noqa: E402

#: The page carrying the generated block.
DOCS_PAGE = project_root.parent / "apiome-docs" / "docs" / "govern" / "compatibility-modes.md"


def main() -> int:
    """Rewrite the generated block; return a process exit code."""
    page = DOCS_PAGE.read_text(encoding="utf-8")
    updated = replace_catalogue_section(page)
    if updated != page:
        DOCS_PAGE.write_text(updated, encoding="utf-8")
        print(f"Updated {DOCS_PAGE.relative_to(project_root.parent)}")
    else:
        print(f"{DOCS_PAGE.relative_to(project_root.parent)} is current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
