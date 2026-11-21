#!/usr/bin/env python3
"""Run the document lifecycle job once (COA-5.10 / #7086).

Deletes stored documents no live revision uses (after the grace period), drops replaced rendered
documents, empties the store prefix of deleted tenants, and re-hashes stored objects to check
they are unchanged. See :mod:`app.document_lifecycle`. The REST server runs the same job every
``APIOME_DOCUMENT_LIFECYCLE_INTERVAL_SECONDS``; use this script for a full integrity check or a
dry run. Run from apiome-rest, with the same environment as the REST server:

    PYTHONPATH=src python scripts/document_lifecycle.py --dry-run
    PYTHONPATH=src python scripts/document_lifecycle.py --integrity-only --all
    PYTHONPATH=src python scripts/document_lifecycle.py --grace-hours 0

Prints the JSON report. Exit status: 0 when no object failed its integrity check, 1 when any did,
2 when another run holds the lock.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
src = project_root / "src"
if str(src) not in sys.path:
    sys.path.insert(0, str(src))

from app.config import settings  # noqa: E402
from app.database import db  # noqa: E402
from app.document_lifecycle import LifecycleOptions, run_document_lifecycle  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    """The command line: what to run and how far."""
    parser = argparse.ArgumentParser(description="Collect unused stored documents and check stored bytes.")
    parser.add_argument("--dry-run", action="store_true", help="Report what would be deleted; change nothing")
    parser.add_argument(
        "--grace-hours",
        type=float,
        default=None,
        help=f"How long an unused object waits before deletion (default {settings.document_gc_grace_hours:g})",
    )
    parser.add_argument(
        "--sample",
        type=int,
        default=None,
        help=(
            "Objects to re-hash, least recently verified first; 0 skips "
            f"(default {settings.document_integrity_sample})"
        ),
    )
    parser.add_argument("--all", action="store_true", help="Re-hash every stored object")
    parser.add_argument("--integrity-only", action="store_true", help="Skip garbage collection")
    return parser


def options_from(args: argparse.Namespace) -> LifecycleOptions:
    """Build the run's options from the parsed arguments and the settings."""
    options = LifecycleOptions.from_settings()
    if args.grace_hours is not None:
        options.grace = timedelta(hours=max(0.0, args.grace_hours))
    if args.sample is not None:
        options.integrity_sample = max(0, args.sample)
    options.integrity_all = bool(args.all)
    options.gc = not args.integrity_only
    options.dry_run = bool(args.dry_run)
    return options


def main(argv: list[str] | None = None) -> int:
    """Run the job once and print its report.

    Returns:
        The exit status (see the module docstring).
    """
    args = build_parser().parse_args(argv)
    report = run_document_lifecycle(db, options_from(args))
    if report.locked:
        print(json.dumps({"error": "Another document lifecycle run is in progress."}), file=sys.stderr)
        return 2
    print(json.dumps(report.as_dict(), indent=2))
    return 1 if report.integrity_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
