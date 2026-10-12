"""Seal linked-account tokens that are still stored in plaintext (OLO-7.3 follow-up, #4960).

Linked-account OAuth tokens and personal access tokens are encrypted at rest from V275 on. Rows
written before that hold plaintext until this command converts them. Run it once after upgrading,
with ``APIOME_LINKED_ACCOUNT_TOKEN_ENCRYPTION_KEYS`` set::

    python -m app.seal_linked_account_tokens --dry-run
    python -m app.seal_linked_account_tokens

It lives in the application package, not ``scripts/``, so it is present in the production image
(``docker compose exec rest python -m app.seal_linked_account_tokens``). From a source checkout,
run it from ``apiome-rest`` with ``PYTHONPATH=src``.

Run it again after rotating to a new key-version: tokens sealed under an older key are re-sealed
under the active one. Safe to re-run — a second run finds nothing to do. Prints counts only; no
token ever reaches the output.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, List, Optional

from .linked_account_token_crypto import (
    LinkedAccountTokenEncryptionError,
    seal_plaintext_tokens,
)

__all__ = ["main"]


def main(argv: Optional[List[str]] = None, *, database: Any = None) -> int:
    """Run the backfill and print its summary.

    Args:
        argv: Command-line arguments; defaults to ``sys.argv[1:]``.
        database: The database handle to sweep; defaults to the application's shared handle.
            Imported lazily so ``--help`` needs no database.

    Returns:
        ``0`` on success; ``1`` when encryption is not configured or a stored token could not be
        opened with any configured key (those rows are left untouched).
    """
    parser = argparse.ArgumentParser(
        prog="python -m app.seal_linked_account_tokens",
        description="Seal plaintext linked-account tokens and re-seal tokens on an old key.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without writing anything",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=200,
        help="Rows read per round trip (default: 200)",
    )
    args = parser.parse_args(argv)

    if database is None:
        from .database import db as database

    try:
        summary = seal_plaintext_tokens(database, dry_run=args.dry_run, batch_size=args.batch_size)
    except LinkedAccountTokenEncryptionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"dry_run": args.dry_run, **summary}, indent=2))
    return 1 if summary["tokens_unreadable"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
