"""Persistence for the usage ingest pipeline — RDG-1.2 (#5760).

:mod:`app.usage_ingest` decides; this module reads what it needs to decide and writes what it
decided. One batch is:

1. **outside the transaction** — read the ``usage_source`` row and build the
   :class:`~app.usage_ingest.RevisionMatcher` over the project's published revisions (rendering a
   revision commits on the shared connection, so it can never run inside the write transaction);
2. **inside one transaction** (:meth:`app.database.Database._guarded_tx`) —

   * take a transaction advisory lock per tenant, so two concurrent batches cannot both slip
     under the daily cap;
   * **step 1, the tier cap**: sum the day's ledgered events (``received - rejected``) against
     ``licenses.seats.usage_events_per_day`` (Free 100,000 when unlicensed or unset; zero or
     negative = unlimited). Over it, the batch is ledgered as wholly rejected and the caller answers
     ``429``;
   * otherwise run :func:`~app.usage_ingest.plan_batch` (steps 2–4) and write its counters with
     additive upserts — ``usage_hourly``, ``usage_unmatched_daily``, ``usage_field_daily`` and any
     clean ``usage_sample`` rows;
   * **step 5**: insert the ``usage_ingest_batch`` ledger row and stamp the source's
     ``last_received_at``.

Everything commits together or not at all, so the ledger always says exactly what reached the
index.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from psycopg2.extras import Json

from .consumer_binding import ConsumerMatcher
from .consumer_binding_store import load_live_bindings, stamp_matches
from .consumer_surface import SpecIndex
from .revision_deprecation import is_uuid_string
from .usage_ingest import (
    CODE_QUOTA_EXCEEDED,
    CODE_SOURCE_DISABLED,
    CODE_SOURCE_NOT_FOUND,
    REASON_QUOTA_EXCEEDED,
    BatchPlan,
    RevisionMatcher,
    SourceConfig,
    UsageIngestError,
    next_utc_midnight,
    plan_batch,
    refuse_closed_body_window,
    rejected_plan,
    scale,
)

__all__ = [
    "DEFAULT_EVENTS_PER_DAY",
    "MAX_MATCH_REVISIONS",
    "IngestOutcome",
    "build_matcher",
    "events_per_day_cap",
    "ingest_batch",
    "load_source",
]

_logger = logging.getLogger(__name__)

#: The Free-tier daily cap a tenant gets when its license names none (V290 rule 7).
DEFAULT_EVENTS_PER_DAY = 100_000

#: How many of the newest published revisions traffic is matched against.
MAX_MATCH_REVISIONS = 20

#: Parsed revision indexes kept between batches, keyed by ``(versions.id, updated_at)``.
_INDEX_CACHE_SIZE = 128
_index_cache: "OrderedDict[Tuple[str, str], SpecIndex]" = OrderedDict()


@dataclass(frozen=True)
class IngestOutcome:
    """What one admitted batch did.

    Attributes:
        batch_id: The ledger row.
        received_at: When it was ledgered.
        plan: The pipeline's decisions (counts, rejections, samples).
    """

    batch_id: str
    received_at: datetime
    plan: BatchPlan


def load_source(db: Any, tenant_id: str, source_ref: Optional[str]) -> SourceConfig:
    """Read the source a batch names.

    Args:
        db: The database.
        tenant_id: The authenticated tenant.
        source_ref: The ``usage_source.id`` from the header or the body.

    Returns:
        The :class:`~app.usage_ingest.SourceConfig`.

    Raises:
        UsageIngestError: 404 ``usage-source-not-found`` for an unknown id (or another tenant's),
            403 ``usage-source-disabled`` for a source switched off.
    """
    if not source_ref or not is_uuid_string(source_ref):
        raise UsageIngestError(404, CODE_SOURCE_NOT_FOUND, "no usage source with that id in this tenant")
    rows = db.execute_query(
        """
        SELECT id::text AS id, tenant_id::text AS tenant_id, project_id::text AS project_id, kind,
               environment, sampling_rate, field_capture, body_sample_rate, body_sample_until, enabled
        FROM apiome.usage_source
        WHERE id = %s::uuid AND tenant_id = %s::uuid
        """,
        (source_ref, tenant_id),
    )
    if not rows:
        raise UsageIngestError(404, CODE_SOURCE_NOT_FOUND, "no usage source with that id in this tenant")
    row = rows[0]
    source = SourceConfig(
        id=row["id"],
        tenant_id=row["tenant_id"],
        project_id=row["project_id"],
        kind=row["kind"],
        environment=row["environment"],
        sampling_rate=float(row["sampling_rate"]),
        field_capture=bool(row["field_capture"]),
        body_sample_rate=float(row["body_sample_rate"]),
        body_sample_until=row["body_sample_until"],
        enabled=bool(row["enabled"]),
    )
    if not source.enabled:
        raise UsageIngestError(403, CODE_SOURCE_DISABLED, "this usage source is disabled")
    return source


def _cached_index(db: Any, tenant_id: str, version: Dict[str, Any]) -> Optional[SpecIndex]:
    """The revision's :class:`SpecIndex`, from the cache when the revision is unchanged."""
    from .blast_radius import version_document

    key = (version["id"], str(version.get("updated_at")))
    cached = _index_cache.get(key)
    if cached is not None:
        _index_cache.move_to_end(key)
        return cached
    document = version_document(db, tenant_id, version)
    if document is None:
        return None
    index = SpecIndex(document)
    _index_cache[key] = index
    while len(_index_cache) > _INDEX_CACHE_SIZE:
        _index_cache.popitem(last=False)
    return index


def build_matcher(db: Any, tenant_id: str, project_id: str) -> RevisionMatcher:
    """Index the project's newest published revisions, newest published first.

    Only ``published`` revisions that are not deleted are read, so an operation only a draft
    declares can never be matched. A revision whose document cannot be loaded is skipped (and
    logged) rather than failing the batch.

    Args:
        db: The database.
        tenant_id: The tenant.
        project_id: The source's project.

    Returns:
        The matcher (empty when the project has no published revision).
    """
    rows = db.execute_query(
        """
        SELECT v.id::text AS id, v.updated_at
        FROM apiome.versions v
        JOIN apiome.projects p ON p.id = v.project_id
        WHERE v.project_id = %s::uuid AND p.tenant_id = %s::uuid
          AND v.published AND v.deleted_at IS NULL
        ORDER BY COALESCE(v.published_at, v.created_at) DESC, v.created_at DESC
        LIMIT %s
        """,
        (project_id, tenant_id, MAX_MATCH_REVISIONS),
    )
    revisions: List[Tuple[str, SpecIndex]] = []
    for row in rows:
        index = _cached_index(db, tenant_id, dict(row))
        if index is None:
            _logger.info("usage ingest: revision %s has no document; not matched against", row["id"])
            continue
        revisions.append((row["id"], index))
    return RevisionMatcher(revisions)


def events_per_day_cap(cursor: Any, tenant_id: str) -> int:
    """The tenant's ``usage_events_per_day`` (Free when unlicensed or unset; <= 0 = unlimited).

    Args:
        cursor: A cursor in the write transaction.
        tenant_id: The tenant.

    Returns:
        The cap.
    """
    cursor.execute(
        """
        SELECT CASE WHEN jsonb_typeof(l.seats -> 'usage_events_per_day') = 'number'
                    THEN (l.seats ->> 'usage_events_per_day')::numeric::bigint
                    ELSE %s END AS cap
        FROM apiome.tenants t
        LEFT JOIN apiome.tenant_licenses tl ON tl.tenant_id = t.id
        LEFT JOIN apiome.licenses l ON l.id = tl.license_id
        WHERE t.id = %s::uuid
        """,
        (DEFAULT_EVENTS_PER_DAY, tenant_id),
    )
    row = cursor.fetchone()
    return int(row["cap"]) if row and row["cap"] is not None else DEFAULT_EVENTS_PER_DAY


def _events_used_today(cursor: Any, tenant_id: str, day: date) -> int:
    """Events the tenant's ledger admitted on UTC ``day`` (``received - rejected``)."""
    cursor.execute(
        """
        SELECT COALESCE(sum(received - rejected), 0) AS used
        FROM apiome.usage_ingest_batch
        WHERE tenant_id = %s::uuid AND received_day = %s
        """,
        (tenant_id, day),
    )
    return int(cursor.fetchone()["used"])


def _finalized_lookup(cursor: Any) -> Callable[[date], bool]:
    """A memoized "is this UTC day finalized?" over ``usage_rollup_days``."""
    known: Dict[date, bool] = {}

    def is_finalized(day: date) -> bool:
        if day not in known:
            cursor.execute(
                "SELECT 1 FROM apiome.usage_rollup_days WHERE day = %s AND finalized_at IS NOT NULL",
                (day,),
            )
            known[day] = cursor.fetchone() is not None
        return known[day]

    return is_finalized


def _write_hourly(cursor: Any, source: SourceConfig, plan: BatchPlan) -> None:
    """Add the plan's hourly grains into ``usage_hourly`` (scaled)."""
    for (environment, hour, version_id, operation_key, status, binding_id), counter in plan.hourly.items():
        row = counter.scaled(plan.sampling_rate)
        cursor.execute(
            """
            INSERT INTO apiome.usage_hourly AS h (
                tenant_id, project_id, source_id, environment, hour, version_record_id,
                operation_key, status_code, consumer_binding_id, calls, latency_buckets,
                latency_sum_ms, latency_max_ms, auth_present_calls, auth_unknown_calls,
                versioned_calls, version_unknown_calls, https_calls, request_bytes, response_bytes)
            VALUES (%s::uuid, %s::uuid, %s::uuid, %s, %s, %s::uuid, %s, %s, %s::uuid, %s, %s::bigint[],
                    %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT ON CONSTRAINT usage_hourly_grain_uq DO UPDATE SET
                calls = h.calls + EXCLUDED.calls,
                latency_buckets = (
                    SELECT array_agg(a + b ORDER BY i)
                    FROM unnest(h.latency_buckets, EXCLUDED.latency_buckets) WITH ORDINALITY AS t(a, b, i)
                ),
                latency_sum_ms = h.latency_sum_ms + EXCLUDED.latency_sum_ms,
                latency_max_ms = GREATEST(h.latency_max_ms, EXCLUDED.latency_max_ms),
                auth_present_calls = h.auth_present_calls + EXCLUDED.auth_present_calls,
                auth_unknown_calls = h.auth_unknown_calls + EXCLUDED.auth_unknown_calls,
                versioned_calls = h.versioned_calls + EXCLUDED.versioned_calls,
                version_unknown_calls = h.version_unknown_calls + EXCLUDED.version_unknown_calls,
                https_calls = h.https_calls + EXCLUDED.https_calls,
                request_bytes = h.request_bytes + EXCLUDED.request_bytes,
                response_bytes = h.response_bytes + EXCLUDED.response_bytes,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                source.tenant_id,
                source.project_id,
                source.id,
                environment,
                hour,
                version_id,
                operation_key,
                status,
                binding_id,
                row["calls"],
                row["latency_buckets"],
                row["latency_sum_ms"],
                row["latency_max_ms"],
                row["auth_present_calls"],
                row["auth_unknown_calls"],
                row["versioned_calls"],
                row["version_unknown_calls"],
                row["https_calls"],
                row["request_bytes"],
                row["response_bytes"],
            ),
        )


def _write_unmatched(cursor: Any, source: SourceConfig, plan: BatchPlan) -> None:
    """Add the plan's unmatched grains into ``usage_unmatched_daily`` (scaled)."""
    for (environment, day, method, template), counter in plan.unmatched_rows.items():
        row = counter.scaled(plan.sampling_rate)
        cursor.execute(
            """
            INSERT INTO apiome.usage_unmatched_daily AS u (
                tenant_id, project_id, source_id, environment, day, method, path_template, calls,
                first_seen_at, last_seen_at, calls_1xx, calls_2xx, calls_3xx, calls_4xx, calls_5xx)
            VALUES (%s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, project_id, source_id, environment, day, method, path_template)
            DO UPDATE SET
                calls = u.calls + EXCLUDED.calls,
                first_seen_at = LEAST(u.first_seen_at, EXCLUDED.first_seen_at),
                last_seen_at = GREATEST(u.last_seen_at, EXCLUDED.last_seen_at),
                calls_1xx = u.calls_1xx + EXCLUDED.calls_1xx,
                calls_2xx = u.calls_2xx + EXCLUDED.calls_2xx,
                calls_3xx = u.calls_3xx + EXCLUDED.calls_3xx,
                calls_4xx = u.calls_4xx + EXCLUDED.calls_4xx,
                calls_5xx = u.calls_5xx + EXCLUDED.calls_5xx,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                source.tenant_id,
                source.project_id,
                source.id,
                environment,
                day,
                method,
                template,
                row["calls"],
                counter.first_seen,
                counter.last_seen,
                row["calls_1xx"],
                row["calls_2xx"],
                row["calls_3xx"],
                row["calls_4xx"],
                row["calls_5xx"],
            ),
        )


def _write_unattributed(cursor: Any, source: SourceConfig, plan: BatchPlan) -> None:
    """Add the plan's unattributed client counts into ``usage_unattributed_client_daily`` (CDG-3.5)."""
    for (day, client_kind, client_key), counter in plan.unattributed_clients.items():
        calls = scale(counter.events, plan.sampling_rate)
        if calls <= 0:
            continue
        cursor.execute(
            """
            INSERT INTO apiome.usage_unattributed_client_daily AS u (
                tenant_id, project_id, day, client_kind, client_key, calls, first_seen_at, last_seen_at)
            VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s)
            ON CONFLICT ON CONSTRAINT usage_unattributed_client_daily_pk DO UPDATE SET
                calls = u.calls + EXCLUDED.calls,
                first_seen_at = LEAST(u.first_seen_at, EXCLUDED.first_seen_at),
                last_seen_at = GREATEST(u.last_seen_at, EXCLUDED.last_seen_at),
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                source.tenant_id,
                source.project_id,
                day,
                client_kind,
                client_key,
                calls,
                counter.first_seen,
                counter.last_seen,
            ),
        )


def _write_fields(cursor: Any, source: SourceConfig, plan: BatchPlan) -> None:
    """Add the plan's field presence into ``usage_field_daily`` (scaled).

    ``calls_sampled`` is the number of inspected calls since the row first appeared that day, so
    a group's inspected calls are added to **every** pointer row of the group — the ones this batch
    saw (with their ``calls_with_field``) and the ones it did not (as calls without the field).
    """
    for (environment, day, operation_key, direction, status), group in plan.field_groups.items():
        inspected = scale(group.inspected, plan.sampling_rate)
        grain = (source.tenant_id, source.project_id, source.id, environment, day, operation_key, direction, status)
        cursor.execute(
            """
            UPDATE apiome.usage_field_daily
            SET calls_sampled = calls_sampled + %s, updated_at = CURRENT_TIMESTAMP
            WHERE tenant_id = %s::uuid AND project_id = %s::uuid AND source_id = %s::uuid
              AND environment = %s AND day = %s AND operation_key = %s AND direction = %s
              AND status_code = %s AND NOT (pointer = ANY (%s::text[]))
            """,
            (inspected, *grain, list(group.pointers)),
        )
        for pointer, count in group.pointers.items():
            cursor.execute(
                """
                INSERT INTO apiome.usage_field_daily AS f (
                    tenant_id, project_id, source_id, environment, day, operation_key, direction,
                    status_code, pointer, calls_with_field, calls_sampled)
                VALUES (%s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, project_id, source_id, environment, day, operation_key,
                             direction, status_code, pointer)
                DO UPDATE SET
                    calls_with_field = f.calls_with_field + EXCLUDED.calls_with_field,
                    calls_sampled = f.calls_sampled + EXCLUDED.calls_sampled,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (*grain, pointer, scale(count, plan.sampling_rate), inspected),
            )


def _write_samples(cursor: Any, source: SourceConfig, plan: BatchPlan) -> None:
    """Insert the plan's clean, reduced samples into ``usage_sample``."""
    for environment, captured_at, operation_key, status, exchange in plan.samples:
        cursor.execute(
            """
            INSERT INTO apiome.usage_sample (
                tenant_id, project_id, source_id, environment, captured_at, operation_key,
                status_code, exchange)
            VALUES (%s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s, %s)
            """,
            (
                source.tenant_id,
                source.project_id,
                source.id,
                environment,
                captured_at,
                operation_key,
                status,
                Json(exchange),
            ),
        )


def _ledger(
    cursor: Any, source: SourceConfig, plan: BatchPlan, *, api_key_id: Optional[str], digest: str, now: datetime
) -> str:
    """Insert the batch's ledger row, stamp the source, and return the row id."""
    counts = plan.ledger_counts()
    cursor.execute(
        """
        INSERT INTO apiome.usage_ingest_batch (
            tenant_id, source_id, api_key_id, received_at, received, accepted, sampled_out,
            unmatched, rejected, scrub_findings, batch_digest)
        VALUES (%s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id::text AS id
        """,
        (
            source.tenant_id,
            source.id,
            api_key_id if api_key_id and is_uuid_string(api_key_id) else None,
            now,
            counts["received"],
            counts["accepted"],
            counts["sampled_out"],
            counts["unmatched"],
            counts["rejected"],
            counts["scrub_findings"],
            digest,
        ),
    )
    batch_id = cursor.fetchone()["id"]
    cursor.execute(
        "UPDATE apiome.usage_source SET last_received_at = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s::uuid",
        (now, source.id),
    )
    return batch_id


def ingest_batch(
    db: Any,
    *,
    tenant_id: str,
    source_ref: Optional[str],
    raw_events: List[Any],
    digest: str,
    api_key_id: Optional[str],
    now: datetime,
) -> IngestOutcome:
    """Run the whole pipeline for one batch and persist it.

    Args:
        db: The database.
        tenant_id: The authenticated tenant.
        source_ref: The source id the batch names.
        raw_events: The batch's events as parsed.
        digest: :func:`app.usage_ingest.batch_digest` of the batch.
        api_key_id: The key that sent it (ledgered; no FK).
        now: The current instant.

    Returns:
        The :class:`IngestOutcome` of an admitted batch.

    Raises:
        UsageIngestError: 404 / 403 for the source, 422 ``usage-body-not-accepted`` for a body the
            source may not send, 429 ``usage-quota-exceeded`` (with ``retry_at`` and the ledger
            row's id) when the batch would take the tenant over its daily cap.
    """
    source = load_source(db, tenant_id, source_ref)
    refuse_closed_body_window(raw_events, source, now)
    matcher = build_matcher(db, tenant_id, source.project_id)
    today = now.date()

    def work(cursor: Any) -> Tuple[str, Optional[str], BatchPlan]:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"apiome.usage_ingest:{tenant_id}",))
        cap = events_per_day_cap(cursor, tenant_id)
        if cap > 0 and _events_used_today(cursor, tenant_id, today) + len(raw_events) > cap:
            plan = rejected_plan(raw_events, REASON_QUOTA_EXCEEDED)
            return "quota", _ledger(cursor, source, plan, api_key_id=api_key_id, digest=digest, now=now), plan
        # RDG-1.8: bindings are read inside the transaction, so one deleted before the batch began
        # attributes nothing in it.
        consumers = ConsumerMatcher(load_live_bindings(cursor, tenant_id, source.project_id))
        plan = plan_batch(
            raw_events, source, matcher, now=now, is_day_finalized=_finalized_lookup(cursor), consumers=consumers
        )
        _write_hourly(cursor, source, plan)
        stamp_matches(cursor, plan.binding_matches, plan.binding_consumers)
        _write_unattributed(cursor, source, plan)
        _write_unmatched(cursor, source, plan)
        _write_fields(cursor, source, plan)
        _write_samples(cursor, source, plan)
        return "ok", _ledger(cursor, source, plan, api_key_id=api_key_id, digest=digest, now=now), plan

    status, batch_id, plan = db._guarded_tx(work)
    if status == "quota":
        raise UsageIngestError(
            429,
            CODE_QUOTA_EXCEEDED,
            "this workspace has reached its usage_events_per_day cap for today; the batch was ledgered "
            "as rejected",
            retry_at=next_utc_midnight(now),
            batch_id=batch_id,
        )
    return IngestOutcome(batch_id=batch_id or "", received_at=now, plan=plan)
