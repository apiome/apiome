#!/usr/bin/env python3
"""Re-index existing catalog items into the canonical model tables (MFI-6.2 / #3754).

The cross-protocol search (``GET /v1/search/{tenant_slug}/model``) reads the MFI-2.2 canonical
tables. Run this once after deploying MFI-6.2 so catalog items imported before it become
searchable. From apiome-rest:

    PYTHONPATH=src python scripts/backfill_canonical_models.py
    # or
    uv run python scripts/backfill_canonical_models.py

Optional ``--limit N`` processes at most N catalog items (useful for smoke runs).
Safe to re-run: candidates are catalog items whose latest revision has no live canonical artifact.
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

from app.canonical_model_reindex import reindex_catalog_canonical_models  # noqa: E402
from app.database import db  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rebuild the canonical model of every catalog item whose latest revision lacks one."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max number of catalog items to process in this run",
    )
    args = parser.parse_args(argv)

    summary = reindex_catalog_canonical_models(db, limit=args.limit)
    print(json.dumps(summary, indent=2, default=str))
    return 1 if summary.get("failed") else 0


if __name__ == "__main__":
    raise SystemExit(main())
