#!/usr/bin/env python3
"""Move documents still held in the database into the document store (COA-5.8 / #7084).

Copies import sources (``format_metadata.sourceContent``, ``version_import_snapshots.source_text``),
frozen schemas (``version_spec_snapshots.content``) and export artifacts
(``export_job_artifact.content``) into the store configured by ``APIOME_DOCUMENT_STORE``, verifies
every object after upload and links it. See :mod:`app.document_migration`. Run from apiome-rest,
with the same environment as the REST server:

    PYTHONPATH=src python scripts/migrate_documents_to_store.py --dry-run
    PYTHONPATH=src python scripts/migrate_documents_to_store.py [--tenant <tenant-uuid>]
    PYTHONPATH=src python scripts/migrate_documents_to_store.py --purge-db-copies [--dry-run]

The copy step leaves the database copies in place. ``--purge-db-copies`` is the separate, later
step that re-verifies each stored object against its database copy and only then drops the copy
(refused while ``APIOME_DOCUMENT_STORE=db``).

Prints the JSON report. Safe to re-run (a finished row is never selected again) and to interrupt
(the next run resumes after the last checkpointed batch). Exit status: 0 when no row failed, 1 when
any did, 2 when the run was refused or another run holds the lock.
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
from app.document_migration import (  # noqa: E402
    MAX_BATCH_SIZE,
    MAX_WORKERS,
    SOURCES,
    MigrationBusy,
    MigrationOptions,
    MigrationRefused,
    run_document_migration,
)
from app.document_store import get_document_store  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    """The command line: the step, its scope and its pace."""
    parser = argparse.ArgumentParser(description="Move documents held in the database into the document store.")
    parser.add_argument("--tenant", default=None, help="Only this tenant (UUID); default every tenant")
    parser.add_argument("--dry-run", action="store_true", help="Report what the step would do; write nothing")
    parser.add_argument(
        "--purge-db-copies",
        action="store_true",
        help="Run the purge step: drop database copies whose stored object verifies (after a copy run)",
    )
    parser.add_argument(
        "--source",
        action="append",
        choices=SOURCES,
        help="Only this source (repeatable); default every source",
    )
    parser.add_argument("--rate", type=float, default=20.0, help="Most rows per second; 0 for no limit (default 20)")
    parser.add_argument(
        "--batch-size", type=int, default=50, help=f"Rows per page and checkpoint, 1-{MAX_BATCH_SIZE} (default 50)"
    )
    parser.add_argument(
        "--workers", type=int, default=1, help=f"Rows processed in parallel, 1-{MAX_WORKERS} (default 1)"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run one step and print its report.

    Returns:
        The exit status (see the module docstring).
    """
    args = build_parser().parse_args(argv)
    options = MigrationOptions(
        purge_db_copies=args.purge_db_copies,
        dry_run=args.dry_run,
        tenant_id=args.tenant,
        sources=tuple(args.source) if args.source else SOURCES,
        batch_size=args.batch_size,
        rate=args.rate,
        workers=args.workers,
    )
    try:
        report = run_document_migration(db, get_document_store(), options)
    except (MigrationRefused, MigrationBusy) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(report.as_dict(), indent=2, default=str))
    return 1 if report.total("failed") else 0


if __name__ == "__main__":
    raise SystemExit(main())
