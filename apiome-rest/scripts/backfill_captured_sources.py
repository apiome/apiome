#!/usr/bin/env python3
"""Backfill catalog revisions that have no captured source (E1-6 / #6221).

A revision with no captured source cannot be exported (``422 source-not-captured``). This one-off
job repairs each one from a stored copy proven identical to what it was imported from — another
revision of the same item, or the linked repository file — and reports how many it repaired. See
:mod:`app.source_backfill`. Run from apiome-rest:

    PYTHONPATH=src python scripts/backfill_captured_sources.py --dry-run
    PYTHONPATH=src python scripts/backfill_captured_sources.py [--tenant <tenant-uuid>]

Prints the JSON report (``scanned``, ``repaired``, ``unrepaired``, ``unverifiable``, ``no_copy`` and
each revision's outcome). Safe to re-run: a repaired revision is no longer a candidate.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
src = project_root / "src"
if str(src) not in sys.path:
    sys.path.insert(0, str(src))

from app.database import db  # noqa: E402
from app.source_backfill import backfill_captured_sources  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Repair revisions with no captured source.")
    parser.add_argument("--tenant", default=None, help="Only this tenant (UUID); default every tenant")
    parser.add_argument("--dry-run", action="store_true", help="Report what would be repaired; write nothing")
    args = parser.parse_args(argv)

    report = backfill_captured_sources(db, tenant_id=args.tenant, dry_run=args.dry_run)
    print(json.dumps(report.as_dict(), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
