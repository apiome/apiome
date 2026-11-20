#!/usr/bin/env python3
"""
Write the OpenAPI construct matrix into the docs site (COA-2.1, #7044).

Writes:
  - apiome-docs/docs/reference/openapi-construct-matrix.md (only the region between its
    `openapi-construct-matrix:begin` and `openapi-construct-matrix:end` markers)

The matrix comes from `app.openapi_construct_audit`, which runs every document of the construct
corpus (`tests/fixtures/openapi_construct_corpus`) through import → emit → re-import and grades
each construct occurrence. A test (`tests/test_openapi_construct_audit.py`) regenerates the region
in memory and compares it against the committed page, so CI fails when the two drift.

Run from apiome-rest:
    uv run python scripts/generate_openapi_construct_matrix_doc.py

Exits non-zero when `--check` is passed and the committed matrix is stale.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
src = project_root / "src"
if str(src) not in sys.path:
    sys.path.insert(0, str(src))

from app.openapi_construct_matrix_doc import (  # noqa: E402
    OPENAPI_CONSTRUCT_MATRIX_PAGE,
    REGENERATE_COMMAND,
    apply_construct_matrix,
    audit_monorepo_corpus,
)

MONOREPO = project_root.parent


def main() -> int:
    """Write (or check) the generated matrix.

    Returns:
        ``0`` on success; ``1`` when ``--check`` found the committed matrix stale.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Do not write; exit non-zero if the committed matrix differs from a fresh generation.",
    )
    args = parser.parse_args()

    target = MONOREPO / OPENAPI_CONSTRUCT_MATRIX_PAGE
    current = target.read_text(encoding="utf-8")
    rendered = apply_construct_matrix(current, audit_monorepo_corpus(MONOREPO))

    if args.check:
        if current != rendered:
            print(
                f"The construct matrix in {OPENAPI_CONSTRUCT_MATRIX_PAGE} is out of date.\n"
                f"Regenerate with: {REGENERATE_COMMAND}",
                file=sys.stderr,
            )
            return 1
        print(f"The construct matrix in {OPENAPI_CONSTRUCT_MATRIX_PAGE} is up to date.")
        return 0

    target.write_text(rendered, encoding="utf-8")
    print(f"Wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
