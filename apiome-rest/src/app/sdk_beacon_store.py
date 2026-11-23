"""Storing and reading SDK compatibility beacon counts — RDG-1.7 / SGD-3.1 (#4736).

:func:`ingest_beacons` takes one :class:`~app.sdk_beacon.SdkBeaconBatch` from an SDK and adds its
counts to ``usage_sdk_beacon_daily`` (apiome-db V380). :func:`list_beacon_counts` is the owner's read.

The rules:

* **The source decides.** The batch names a ``usage_source``; :func:`app.usage_ingest_store
  .load_source` refuses an unknown one (404) and a disabled one (403) — the source's ``enabled`` flag
  is the tenant's off switch. The source must be of kind ``sdk_beacon`` (409 otherwise), so a key
  minted for a gateway source cannot write beacon rows and vice versa.
* **Only the source's own published revisions.** An event whose ``spec_revision_id`` is not a
  published revision of the source's project is rejected — reported by its index and a reason, never
  by its content — and the rest of the batch is kept.
* **The server's clock.** Counts land on the UTC day the server received the report; nothing from
  the SDK sets a time.
* **One transaction.** The admitted events of a batch are upserted together, so a report is counted
  wholly or not at all.

Retention is the usage sweep's: ``apiome.purge_usage_sdk_beacons`` prunes rows past the tier's
``usage_rollup_retention_days`` (:mod:`app.usage_sweep`).
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from .db_bulk import bulk_insert_arrays
from .revision_deprecation import is_uuid_string
from .sdk_beacon import SdkBeaconBatch
from .usage_ingest import UsageIngestError
from .usage_ingest_store import load_source

__all__ = [
    "CODE_SOURCE_KIND_MISMATCH",
    "REASON_REVISION_UNKNOWN",
    "BeaconIngestOutcome",
    "BeaconRejection",
    "ingest_beacons",
    "list_beacon_counts",
]

#: The source a batch names is not an ``sdk_beacon`` source.
CODE_SOURCE_KIND_MISMATCH = "usage-source-kind-mismatch"

#: An event names a revision that is not a published revision of the source's project.
REASON_REVISION_UNKNOWN = "revision-unknown"

#: The longest window the owner's read covers.
MAX_READ_DAYS = 400

#: The source kind beacon reports must arrive under.
SOURCE_KIND = "sdk_beacon"

_Key = Tuple[str, str, str, str, str, str]


@dataclass(frozen=True)
class BeaconRejection:
    """One rejected event — its position and why, never its content."""

    index: int
    reason: str


@dataclass(frozen=True)
class BeaconIngestOutcome:
    """What happened to a report.

    Attributes:
        accepted: Events counted.
        calls: Calls those events stood for.
        rejected: The events refused, by index.
    """

    accepted: int
    calls: int
    rejected: List[BeaconRejection]


def _published_revisions(db: Any, project_id: str, revision_ids: List[str]) -> set:
    """Which of the given ids are published revisions of the project.

    Args:
        db: The database.
        project_id: The source's project.
        revision_ids: Candidate ``versions.id`` values (UUID strings).

    Returns:
        The subset that are published, non-deleted revisions of the project.
    """
    ids = sorted({value for value in revision_ids if is_uuid_string(value)})
    if not ids:
        return set()
    rows = db.execute_query(
        """
        SELECT v.id::text AS id
        FROM apiome.versions v
        WHERE v.id = ANY(%s::uuid[]) AND v.project_id = %s::uuid
          AND v.published = true AND v.deleted_at IS NULL
        """,
        (ids, project_id),
    )
    return {str(row["id"]) for row in rows}


def ingest_beacons(
    db: Any, *, tenant_id: str, source_ref: Optional[str], batch: SdkBeaconBatch, now: datetime
) -> BeaconIngestOutcome:
    """Count one SDK beacon report.

    Args:
        db: The database.
        tenant_id: The authenticated tenant (from the ``usage:ingest`` key).
        source_ref: The ``sdk_beacon`` source id, from the header or the body.
        batch: The validated report.
        now: The receive instant (its UTC date is the counting day).

    Returns:
        How many events were counted and which were rejected.

    Raises:
        UsageIngestError: 404 ``usage-source-not-found``, 403 ``usage-source-disabled``, or 409
            ``usage-source-kind-mismatch``.
    """
    source = load_source(db, tenant_id, source_ref)
    if source.kind != SOURCE_KIND:
        raise UsageIngestError(
            409, CODE_SOURCE_KIND_MISMATCH, f"this usage source is a '{source.kind}' source, not an 'sdk_beacon' one"
        )
    known = _published_revisions(db, source.project_id, [str(event.spec_revision_id) for event in batch.events])

    totals: "OrderedDict[_Key, int]" = OrderedDict()
    rejected: List[BeaconRejection] = []
    for index, event in enumerate(batch.events):
        revision = str(event.spec_revision_id)
        if revision not in known:
            rejected.append(BeaconRejection(index=index, reason=REASON_REVISION_UNKNOWN))
            continue
        key = (revision, event.api_version, event.sdk_name, event.sdk_version, event.operation_id, event.outcome)
        totals[key] = totals.get(key, 0) + event.count

    if totals:
        day: date = now.date()

        def work(cursor: Any) -> None:
            # One statement for every counter (DBP-1.7, #7190). ``totals`` is keyed by the rest of
            # the primary key, so no row is named twice.
            bulk_insert_arrays(
                cursor,
                "apiome.usage_sdk_beacon_daily",
                [
                    ("tenant_id", "uuid"),
                    ("project_id", "uuid"),
                    ("source_id", "uuid"),
                    ("day", "date"),
                    ("spec_revision_id", "uuid"),
                    ("api_version", "text"),
                    ("sdk_name", "text"),
                    ("sdk_version", "text"),
                    ("operation_id", "text"),
                    ("outcome", "text"),
                    ("calls", "bigint"),
                    ("first_seen_at", "timestamptz"),
                    ("last_seen_at", "timestamptz"),
                ],
                [
                    (source.tenant_id, source.project_id, source.id, day, *key, calls, now, now)
                    for key, calls in totals.items()
                ],
                on_conflict="""
                    ON CONFLICT ON CONSTRAINT usage_sdk_beacon_daily_pk DO UPDATE
                    SET calls = apiome.usage_sdk_beacon_daily.calls + EXCLUDED.calls,
                        last_seen_at = GREATEST(apiome.usage_sdk_beacon_daily.last_seen_at, EXCLUDED.last_seen_at)
                """,
            )

        db._guarded_tx(work)

    return BeaconIngestOutcome(
        accepted=len(batch.events) - len(rejected), calls=sum(totals.values()), rejected=rejected
    )


def list_beacon_counts(
    db: Any, *, tenant_id: str, project_id: str, days: int, today: date
) -> List[Dict[str, Any]]:
    """A project's beacon counts over the last ``days`` UTC days, grouped by what the manifest keys on.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        project_id: The project.
        days: How many days back, including today (1 to :data:`MAX_READ_DAYS`).
        today: The current UTC date.

    Returns:
        One row per ``(spec_revision_id, api_version, sdk_name, sdk_version, operation_id, outcome)``
        with ``calls``, ``first_seen_at`` and ``last_seen_at``, most calls first.
    """
    since = today - timedelta(days=max(1, min(days, MAX_READ_DAYS)) - 1)
    rows = db.execute_query(
        """
        SELECT b.spec_revision_id::text AS spec_revision_id, b.api_version, b.sdk_name, b.sdk_version,
               b.operation_id, b.outcome, sum(b.calls)::bigint AS calls,
               min(b.first_seen_at) AS first_seen_at, max(b.last_seen_at) AS last_seen_at
        FROM apiome.usage_sdk_beacon_daily b
        WHERE b.tenant_id = %s::uuid AND b.project_id = %s::uuid AND b.day >= %s
        GROUP BY b.spec_revision_id, b.api_version, b.sdk_name, b.sdk_version, b.operation_id, b.outcome
        ORDER BY calls DESC, b.api_version, b.operation_id, b.outcome
        LIMIT 5000
        """,
        (tenant_id, project_id, since),
    )
    return [dict(row) for row in rows]
