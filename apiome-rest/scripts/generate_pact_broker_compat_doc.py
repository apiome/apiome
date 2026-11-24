#!/usr/bin/env python3
"""
Write the Pact Broker endpoint table into the *Pact Broker compatibility* guide (PFX-1.8, #6921).

Writes:
  - apiome-docs/docs/ship/pact-broker/compatibility.mdx (only the region between its
    `pact-broker-compat:begin` and `pact-broker-compat:end` markers)

The table comes from `app.pact_broker_compat`, the catalog of every Pact Broker endpoint and how
much of it Apiome serves. A test (`tests/test_pact_broker_compat_doc.py`) renders the region in
memory and compares it with the committed page, so CI fails when the two drift.

Run from apiome-rest:
    uv run python scripts/generate_pact_broker_compat_doc.py          # write
    uv run python scripts/generate_pact_broker_compat_doc.py --check  # exit 1 when stale
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
src = project_root / "src"
if str(src) not in sys.path:
    sys.path.insert(0, str(src))

from app.pact_broker_compat import COMPATIBILITY_PAGE  # noqa: E402
from app.pact_broker_compat_doc import REGENERATE_COMMAND, apply_compat_table  # noqa: E402

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

    target = MONOREPO / COMPATIBILITY_PAGE
    current = target.read_text(encoding="utf-8")
    rendered = apply_compat_table(current)

    if args.check:
        if current != rendered:
            print(
                f"The endpoint table in {COMPATIBILITY_PAGE} is out of date.\nRegenerate with: {REGENERATE_COMMAND}",
                file=sys.stderr,
            )
            return 1
        print(f"The endpoint table in {COMPATIBILITY_PAGE} is up to date.")
        return 0

    target.write_text(rendered, encoding="utf-8")
    print(f"Wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
