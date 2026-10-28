#!/usr/bin/env python3
"""
Write the target × fidelity-tier table into the *Export catalog items* guide (X7, #6228).

Writes:
  - apiome-docs/docs/ship/export-catalog-items.mdx (only the region between its
    `export-target-tiers:begin` and `export-target-tiers:end` markers)

The table comes from `app.export_target_tiers_doc`, which walks the emitter registry and runs the
fidelity engine against four small reference sources. A test (`tests/test_export_target_tiers_doc.py`)
regenerates the region in memory and compares it against the committed page, so CI fails when the
two drift.

Run from apiome-rest:
    uv run python scripts/generate_export_target_tiers_doc.py

Exits non-zero when `--check` is passed and the committed table is stale, so the same script can
be used as a pre-commit gate.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
src = project_root / "src"
if str(src) not in sys.path:
    sys.path.insert(0, str(src))

from app.export_target_tiers_doc import (  # noqa: E402
    EXPORT_TARGET_TIERS_PAGE,
    REGENERATE_COMMAND,
    apply_target_tier_table,
)

MONOREPO = project_root.parent


def main() -> int:
    """Write (or check) the generated table.

    Returns:
        ``0`` on success; ``1`` when ``--check`` found the committed table stale.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Do not write; exit non-zero if the committed table differs from a fresh generation.",
    )
    args = parser.parse_args()

    target = MONOREPO / EXPORT_TARGET_TIERS_PAGE
    current = target.read_text(encoding="utf-8")
    rendered = apply_target_tier_table(current)

    if args.check:
        if current != rendered:
            print(
                f"The target tier table in {EXPORT_TARGET_TIERS_PAGE} is out of date.\n"
                f"Regenerate with: {REGENERATE_COMMAND}",
                file=sys.stderr,
            )
            return 1
        print(f"The target tier table in {EXPORT_TARGET_TIERS_PAGE} is up to date.")
        return 0

    target.write_text(rendered, encoding="utf-8")
    print(f"Wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
