"""The usage index sweep — rollups, finalization and per-tier retention (RDG-1.1, #5759).

One tick, under a Postgres session advisory lock (so with several REST replicas only one does the
work and the rest skip):

1. ``rollup_usage_days`` recomputes ``usage_daily`` for every open UTC day from ``usage_hourly`` and
   finalizes days that ended more than the grace period ago (a final day is never recomputed and
   takes no new counts);
2. ``purge_usage`` prunes the index per license tier: hourly rows past
   ``usage_hourly_retention_days`` — only on finalized days, so every pruned row is already in
   ``usage_daily`` — samples after 7 days, and daily, field, unmatched and ledger rows past
   ``usage_rollup_retention_days``.

The SQL lives in migration V290, so the rules are the same whoever runs them. The REST lifespan runs
a tick every ``APIOME_USAGE_SWEEP_INTERVAL_SECONDS`` (0 disables it); operators run one from cron
with::

    python -m app.usage_sweep [--grace-hours 6] [--batch-size 10000]

(apiome-rest has no console script, so the module is the entry point:
``docker compose exec rest python -m app.usage_sweep``; from a checkout, run it from ``apiome-rest``
with ``PYTHONPATH=src``.)
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import asdict, dataclass
from datetime import timedelta
from typing import Any, List, Optional

__all__ = [
    "SWEEP_LOCK_KEY",
    "UsageSweepResult",
    "main",
    "run_usage_sweep",
    "run_usage_sweep_with_settings",
]

_logger = logging.getLogger(__name__)

#: The session advisory-lock key every replica shares (``hashtext`` of this name).
SWEEP_LOCK_KEY = "apiome.usage_sweep"

#: The per-table counts ``purge_usage`` reports, in its JSON's key order.
_PURGED_KEYS = ("hourly", "samples", "daily", "fields", "unmatched", "batches")


@dataclass(frozen=True)
class UsageSweepResult:
    """What one tick did.

    Attributes:
        days_rolled_up: UTC days recomputed into ``usage_daily``.
        hourly_purged: ``usage_hourly`` rows deleted.
        samples_purged: ``usage_sample`` rows deleted.
        daily_purged: ``usage_daily`` rows deleted.
        fields_purged: ``usage_field_daily`` rows deleted.
        unmatched_purged: ``usage_unmatched_daily`` rows deleted.
        batches_purged: ``usage_ingest_batch`` rows deleted.
    """

    days_rolled_up: int
    hourly_purged: int
    samples_purged: int
    daily_purged: int
    fields_purged: int
    unmatched_purged: int
    batches_purged: int


def run_usage_sweep(
    db: Any,
    *,
    finalize_grace: timedelta = timedelta(hours=6),
    batch_size: int = 10000,
) -> Optional[UsageSweepResult]:
    """Run one sweep tick.

    Args:
        db: A dedicated :class:`~app.database.Database` handle — the advisory lock lives on its
            connection, so it must not be the handle request handlers share.
        finalize_grace: How long after a UTC day ends before it is final. Must exceed the longest
            delay between a call and its ingest, or late counts are refused for a final day.
        batch_size: Most rows each prune deletes per table (the rest go on the next tick).

    Returns:
        What the tick did, or ``None`` when another replica holds the sweep lock.

    Raises:
        Exception: Database errors propagate after the lock is released; the lifespan loop logs them
            and retries on the next interval.
    """
    if finalize_grace < timedelta(0):
        raise ValueError("finalize_grace must not be negative")
    locked = db.execute_query("SELECT pg_try_advisory_lock(hashtext(%s)) AS locked", (SWEEP_LOCK_KEY,))
    if not (locked and locked[0].get("locked")):
        return None
    try:
        rolled = db.execute_query(
            "SELECT apiome.rollup_usage_days(CURRENT_TIMESTAMP, %s) AS days",
            (finalize_grace,),
        )
        purged_rows = db.execute_query(
            "SELECT apiome.purge_usage(CURRENT_TIMESTAMP, %s) AS purged",
            (max(1, int(batch_size)),),
        )
    finally:
        db.execute_query("SELECT pg_advisory_unlock(hashtext(%s)) AS unlocked", (SWEEP_LOCK_KEY,))
    purged = _as_dict(purged_rows[0].get("purged") if purged_rows else None)
    result = UsageSweepResult(
        days_rolled_up=int((rolled[0].get("days") if rolled else 0) or 0),
        **{f"{key}_purged": int(purged.get(key) or 0) for key in _PURGED_KEYS},
    )
    _logger.info("usage sweep finished %s", asdict(result))
    return result


def _as_dict(value: Any) -> dict:
    """``purge_usage``'s JSONB result as a dict (psycopg2 decodes it; a string is parsed)."""
    if isinstance(value, str):
        value = json.loads(value)
    return value if isinstance(value, dict) else {}


def run_usage_sweep_with_settings(db: Any, settings: Any) -> Optional[UsageSweepResult]:
    """Run one tick configured from the application settings.

    Args:
        db: A dedicated database handle (see :func:`run_usage_sweep`).
        settings: The settings (``usage_finalize_grace_hours``, ``usage_sweep_batch_size``).

    Returns:
        :func:`run_usage_sweep`'s result.
    """
    return run_usage_sweep(
        db,
        finalize_grace=timedelta(hours=float(settings.usage_finalize_grace_hours)),
        batch_size=int(settings.usage_sweep_batch_size),
    )


def main(argv: Optional[List[str]] = None, *, database: Any = None) -> int:
    """Run one sweep tick and print what it did as JSON.

    Args:
        argv: Command-line arguments; defaults to ``sys.argv[1:]``.
        database: The handle to sweep with; defaults to a new :class:`~app.database.Database`
            (imported lazily so ``--help`` needs no database). Closed afterwards only when this
            function opened it.

    Returns:
        ``0`` when the tick ran or another replica already holds the lock (``"skipped": true``).
    """
    from .config import settings

    parser = argparse.ArgumentParser(
        prog="python -m app.usage_sweep",
        description="Roll up, finalize and prune the usage index once (RDG-1.1).",
    )
    parser.add_argument(
        "--grace-hours",
        type=float,
        default=float(settings.usage_finalize_grace_hours),
        help="Hours after a UTC day ends before it is final (default: %(default)s)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=int(settings.usage_sweep_batch_size),
        help="Most rows each prune deletes per table (default: %(default)s)",
    )
    args = parser.parse_args(argv)
    if args.grace_hours < 0:
        parser.error("--grace-hours must not be negative")

    owned = database is None
    if owned:
        from .database import Database

        database = Database()
    try:
        result = run_usage_sweep(
            database,
            finalize_grace=timedelta(hours=args.grace_hours),
            batch_size=args.batch_size,
        )
    finally:
        if owned:
            database.close()
    summary = {"skipped": True} if result is None else {"skipped": False, **asdict(result)}
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
