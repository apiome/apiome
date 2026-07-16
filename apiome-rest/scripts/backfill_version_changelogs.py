#!/usr/bin/env python3
"""Backfill classified version_changelogs for latest published revisions (CTG-3.1 / #4475).

After applying V178 (table create), run from apiome-rest:

    PYTHONPATH=src python scripts/backfill_version_changelogs.py
    # or
    uv run python scripts/backfill_version_changelogs.py

Optional ``--limit N`` processes at most N projects (useful for smoke runs).
Safe to re-run: candidates are projects whose latest published revision has no row yet.
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

from app.publication_changelog import backfill_latest_version_changelogs  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Classify latest published revision per project lacking a version_changelogs row."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max number of projects to process in this run",
    )
    args = parser.parse_args(argv)

    summary = backfill_latest_version_changelogs(limit=args.limit)
    print(json.dumps(summary, indent=2, default=str))
    return 1 if summary.get("failed") else 0


if __name__ == "__main__":
    raise SystemExit(main())
