#!/usr/bin/env python3
"""Regenerate the fixable-rule table of the scanner-evaluation corpus README (GVM-3.5, #5873).

Rewrites the block between the ``fixable-rules:begin`` / ``fixable-rules:end`` markers in
``tests/fixtures/scanner_evaluation/README.md`` from the fixable-rule registry and the ``fix``
fixtures. ``tests/test_scanner_fix_corpus.py`` fails when the block is stale.

Run from apiome-rest:
    uv run python scripts/generate_fix_corpus_readme.py
"""

from __future__ import annotations

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
src = project_root / "src"
if str(src) not in sys.path:
    sys.path.insert(0, str(src))

from app.scanner_evaluation_corpus import corpus_root, fixable_rules_table  # noqa: E402

BEGIN = "<!-- fixable-rules:begin -->"
END = "<!-- fixable-rules:end -->"


def main() -> int:
    """Rewrite the README table in place; return the process exit code."""
    path = corpus_root() / "README.md"
    text = path.read_text(encoding="utf-8")
    head, rest = text.split(BEGIN, 1)
    _old, tail = rest.split(END, 1)
    path.write_text(f"{head}{BEGIN}\n{fixable_rules_table()}{END}{tail}", encoding="utf-8")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
