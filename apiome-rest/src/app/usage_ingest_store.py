"""Persistence for the usage ingest pipeline — RDG-1.2 (#5760).

:mod:`app.usage_ingest` decides; this module reads what it needs to decide and writes what it
decided. One batch is:

1. **outside the transaction** — read the ``usage_source`` row and build the
   :class:`~app.usage_ingest.RevisionMatcher` over the project's published revisions (rendering a
   revision commits on the shared connection, so it can never run inside the write transaction);
2. **still outside the transaction** (DBP-1.8, #7191) — read the finalized days and the project's
   live consumer bindings, and run :func:`~app.usage_ingest.plan_batch` (steps 2–4). Planning is
   the CPU-heavy part of a batch, so it never runs under the tenant lock;
3. **inside one transaction** (:meth:`app.database.Database._guarded_tx`) —

   * take a transaction advisory lock per tenant, so two concurrent batches cannot both slip
     under the daily cap;
   * **step 1, the tier cap**: today's ``usage_tenant_day`` counter (V410: the events the ledger
     admitted, ``received - rejected``) against ``licenses.seats.usage_events_per_day`` (Free
     100,000 when unlicensed or unset; zero or negative = unlimited). Over it, the batch is ledgered
     as wholly rejected and the caller answers ``429``;
   * if a day the plan writes to was finalized since planning, or the live bindings changed, plan
     again under the lock (rare);
   * write the plan's counters with additive upserts, **one statement per table** whatever the
     batch's size — ``usage_hourly``, the binding stamps, ``usage_unattributed_client_daily``,
     ``usage_unmatched_daily``, ``usage_field_daily`` (two) and any clean ``usage_sample`` rows.
     Rows are sent sorted by key, so writers lock them in a stable order;
   * **step 5**: one statement inserts the ``usage_ingest_batch`` ledger row, adds it to the
     tenant's day counter and stamps the source's ``last_received_at``.

Everything commits together or not at all, so the ledger (and the day counter) always says
exactly what reached the index.
"""

from __future__ import annotations

import json
import logging
from collections import OrderedDict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Dict, FrozenSet, List, Mapping, Optional, Sequence, Tuple

from .consumer_binding import ConsumerMatcher, LiveBinding
from .consumer_binding_store import live_bindings, load_live_bindings, stamp_matches
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


# ---------------------------------------------------------------------------------------------
# Step 1 — the tier cap, and what planning needs (DBP-1.8, #7191)
# ---------------------------------------------------------------------------------------------

#: The tenant's ``usage_events_per_day`` as a scalar subquery. Parameters: the Free default, then
#: the tenant id. ``NULL`` when the tenant does not exist.
_CAP_SQL = """
    SELECT CASE WHEN jsonb_typeof(l.seats -> 'usage_events_per_day') = 'number'
                THEN (l.seats ->> 'usage_events_per_day')::numeric::bigint
                ELSE %s END
    FROM apiome.tenants t
    LEFT JOIN apiome.tenant_licenses tl ON tl.tenant_id = t.id
    LEFT JOIN apiome.licenses l ON l.id = tl.license_id
    WHERE t.id = %s::uuid
    LIMIT 1
"""

#: Everything the write phase checks before it writes, in one statement: the cap, the events
#: already admitted today (``usage_tenant_day``, V410) and which of the plan's days were finalized
#: since it was planned.
_ADMISSION_SQL = f"""
    SELECT ({_CAP_SQL}) AS cap,
           COALESCE((SELECT d.events_used FROM apiome.usage_tenant_day d
                     WHERE d.tenant_id = %s::uuid AND d.day = %s), 0) AS used,
           ARRAY(SELECT r.day FROM apiome.usage_rollup_days r
                 WHERE r.day = ANY (%s::date[]) AND r.finalized_at IS NOT NULL ORDER BY r.day) AS finalized
"""

_FINALIZED_DAYS_SQL = "SELECT day FROM apiome.usage_rollup_days WHERE finalized_at IS NOT NULL"


def events_per_day_cap(cursor: Any, tenant_id: str) -> int:
    """The tenant's ``usage_events_per_day`` (Free when unlicensed or unset; <= 0 = unlimited).

    Args:
        cursor: A cursor in the write transaction.
        tenant_id: The tenant.

    Returns:
        The cap.
    """
    cursor.execute(f"SELECT ({_CAP_SQL}) AS cap", (DEFAULT_EVENTS_PER_DAY, tenant_id))
    row = cursor.fetchone()
    return int(row["cap"]) if row and row["cap"] is not None else DEFAULT_EVENTS_PER_DAY


@dataclass(frozen=True)
class _Admission:
    """What the write phase read under the tenant lock.

    Attributes:
        cap: The tenant's daily cap (``<= 0`` = unlimited).
        used: Events the ledger admitted today, from ``usage_tenant_day``.
        finalized: Days the plan writes to that are finalized now.
    """

    cap: int
    used: int
    finalized: FrozenSet[date]

    def admits(self, events: int) -> bool:
        """Whether ``events`` more fit under the cap today."""
        return self.cap <= 0 or self.used + events <= self.cap


def _admission(cursor: Any, tenant_id: str, today: date, plan_days: Sequence[date]) -> _Admission:
    """Read the cap, today's count and the plan's newly finalized days (one statement)."""
    cursor.execute(_ADMISSION_SQL, (DEFAULT_EVENTS_PER_DAY, tenant_id, tenant_id, today, list(plan_days)))
    row = cursor.fetchone()
    cap = int(row["cap"]) if row["cap"] is not None else DEFAULT_EVENTS_PER_DAY
    return _Admission(cap=cap, used=int(row["used"]), finalized=frozenset(row["finalized"] or ()))


def _finalized_days(rows: Optional[Sequence[Mapping[str, Any]]]) -> FrozenSet[date]:
    """The ``day`` column of :data:`_FINALIZED_DAYS_SQL` rows as a set."""
    return frozenset(row["day"] for row in rows or ())


def _sorted_bindings(bindings: Sequence[LiveBinding]) -> Tuple[LiveBinding, ...]:
    """Bindings in id order, so two reads of the same set compare equal."""
    return tuple(sorted(bindings, key=lambda binding: binding.id))


def _plan_days(plan: BatchPlan) -> List[date]:
    """Every UTC day the plan writes counters to (what a finalization would refuse)."""
    days = {hour.astimezone(timezone.utc).date() for (_env, hour, *_rest) in plan.hourly}
    days.update(day for (_env, day, *_rest) in plan.unmatched_rows)
    days.update(day for (_env, day, *_rest) in plan.field_groups)
    days.update(day for (day, *_rest) in plan.unattributed_clients)
    return sorted(days)


# ---------------------------------------------------------------------------------------------
# The writes — one statement per table, whatever the batch's size (DBP-1.8, #7191)
# ---------------------------------------------------------------------------------------------


def _key_order(key: Tuple[Any, ...]) -> Tuple[Any, ...]:
    """A sort key for a grain tuple that may hold ``None`` (``None`` sorts first)."""
    return tuple((value is not None, value) for value in key)


def _columns(rows: Sequence[Sequence[Any]]) -> List[List[Any]]:
    """Transpose rows into one list per column (the ``unnest`` array parameters)."""
    return [list(column) for column in zip(*rows)]


def _write_hourly(cursor: Any, source: SourceConfig, plan: BatchPlan) -> None:
    """Add the plan's hourly grains into ``usage_hourly`` (scaled), in one statement.

    A histogram cannot travel as one element of an array parameter (``unnest`` would flatten a
    two-dimensional array), so each one is sent as its array literal and cast back.
    """
    rows = []
    for key, counter in sorted(plan.hourly.items(), key=lambda item: _key_order(item[0])):
        environment, hour, version_id, operation_key, status, binding_id = key
        row = counter.scaled(plan.sampling_rate)
        rows.append(
            (
                environment,
                hour,
                version_id,
                operation_key,
                status,
                binding_id,
                row["calls"],
                "{" + ",".join(str(int(count)) for count in row["latency_buckets"]) + "}",
                row["latency_sum_ms"],
                row["latency_max_ms"],
                row["auth_present_calls"],
                row["auth_unknown_calls"],
                row["versioned_calls"],
                row["version_unknown_calls"],
                row["https_calls"],
                row["request_bytes"],
                row["response_bytes"],
            )
        )
    if not rows:
        return
    cursor.execute(
        """
        INSERT INTO apiome.usage_hourly AS h (
            tenant_id, project_id, source_id, environment, hour, version_record_id,
            operation_key, status_code, consumer_binding_id, calls, latency_buckets,
            latency_sum_ms, latency_max_ms, auth_present_calls, auth_unknown_calls,
            versioned_calls, version_unknown_calls, https_calls, request_bytes, response_bytes)
        SELECT %s::uuid, %s::uuid, %s::uuid, g.environment, g.hour, g.version_record_id,
               g.operation_key, g.status_code, g.consumer_binding_id, g.calls, g.latency_buckets::bigint[],
               g.latency_sum_ms, g.latency_max_ms, g.auth_present_calls, g.auth_unknown_calls,
               g.versioned_calls, g.version_unknown_calls, g.https_calls, g.request_bytes, g.response_bytes
        FROM unnest(%s::text[], %s::timestamptz[], %s::uuid[], %s::text[], %s::smallint[], %s::uuid[],
                    %s::bigint[], %s::text[], %s::bigint[], %s::integer[], %s::bigint[], %s::bigint[],
                    %s::bigint[], %s::bigint[], %s::bigint[], %s::bigint[], %s::bigint[])
             AS g(environment, hour, version_record_id, operation_key, status_code, consumer_binding_id,
                  calls, latency_buckets, latency_sum_ms, latency_max_ms, auth_present_calls,
                  auth_unknown_calls, versioned_calls, version_unknown_calls, https_calls,
                  request_bytes, response_bytes)
        ON CONFLICT ON CONSTRAINT usage_hourly_grain_uq DO UPDATE SET
            calls = h.calls + EXCLUDED.calls,
            latency_buckets = apiome.usage_buckets_add(h.latency_buckets, EXCLUDED.latency_buckets),
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
        (source.tenant_id, source.project_id, source.id, *_columns(rows)),
    )


def _write_unmatched(cursor: Any, source: SourceConfig, plan: BatchPlan) -> None:
    """Add the plan's unmatched grains into ``usage_unmatched_daily`` (scaled), in one statement."""
    rows = []
    for key, counter in sorted(plan.unmatched_rows.items(), key=lambda item: _key_order(item[0])):
        environment, day, method, template = key
        row = counter.scaled(plan.sampling_rate)
        rows.append(
            (
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
            )
        )
    if not rows:
        return
    cursor.execute(
        """
        INSERT INTO apiome.usage_unmatched_daily AS u (
            tenant_id, project_id, source_id, environment, day, method, path_template, calls,
            first_seen_at, last_seen_at, calls_1xx, calls_2xx, calls_3xx, calls_4xx, calls_5xx)
        SELECT %s::uuid, %s::uuid, %s::uuid, g.*
        FROM unnest(%s::text[], %s::date[], %s::text[], %s::text[], %s::bigint[], %s::timestamptz[],
                    %s::timestamptz[], %s::bigint[], %s::bigint[], %s::bigint[], %s::bigint[], %s::bigint[]) AS g
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
        (source.tenant_id, source.project_id, source.id, *_columns(rows)),
    )


def _write_unattributed(cursor: Any, source: SourceConfig, plan: BatchPlan) -> None:
    """Add the unattributed client counts into ``usage_unattributed_client_daily`` (CDG-3.5)."""
    rows = []
    for key, counter in sorted(plan.unattributed_clients.items(), key=lambda item: _key_order(item[0])):
        calls = scale(counter.events, plan.sampling_rate)
        if calls > 0:
            rows.append((*key, calls, counter.first_seen, counter.last_seen))
    if not rows:
        return
    cursor.execute(
        """
        INSERT INTO apiome.usage_unattributed_client_daily AS u (
            tenant_id, project_id, day, client_kind, client_key, calls, first_seen_at, last_seen_at)
        SELECT %s::uuid, %s::uuid, g.*
        FROM unnest(%s::date[], %s::text[], %s::text[], %s::bigint[], %s::timestamptz[], %s::timestamptz[]) AS g
        ON CONFLICT ON CONSTRAINT usage_unattributed_client_daily_pk DO UPDATE SET
            calls = u.calls + EXCLUDED.calls,
            first_seen_at = LEAST(u.first_seen_at, EXCLUDED.first_seen_at),
            last_seen_at = GREATEST(u.last_seen_at, EXCLUDED.last_seen_at),
            updated_at = CURRENT_TIMESTAMP
        """,
        (source.tenant_id, source.project_id, *_columns(rows)),
    )


def _write_fields(cursor: Any, source: SourceConfig, plan: BatchPlan) -> None:
    """Add the plan's field presence into ``usage_field_daily`` (scaled), in two statements.

    ``calls_sampled`` is the number of inspected calls since the row first appeared that day, so
    a group's inspected calls are added to **every** pointer row of the group: first to the ones
    this batch did not see (as calls without the field, one ``UPDATE`` for every group), then to the
    ones it saw, with their ``calls_with_field`` (one upsert for every pointer). The two touch
    different rows, so the order between them does not change the result.
    """
    groups = []
    pointers = []
    for key, group in sorted(plan.field_groups.items(), key=lambda item: _key_order(item[0])):
        inspected = scale(group.inspected, plan.sampling_rate)
        groups.append((*key, inspected, json.dumps(sorted(group.pointers))))
        for pointer, count in sorted(group.pointers.items()):
            pointers.append((*key, pointer, scale(count, plan.sampling_rate), inspected))
    if not groups:
        return
    cursor.execute(
        """
        UPDATE apiome.usage_field_daily f
        SET calls_sampled = f.calls_sampled + g.inspected, updated_at = CURRENT_TIMESTAMP
        FROM unnest(%s::text[], %s::date[], %s::text[], %s::text[], %s::smallint[], %s::bigint[], %s::jsonb[])
             AS g(environment, day, operation_key, direction, status_code, inspected, pointers)
        WHERE f.tenant_id = %s::uuid AND f.project_id = %s::uuid AND f.source_id = %s::uuid
          AND f.environment = g.environment AND f.day = g.day AND f.operation_key = g.operation_key
          AND f.direction = g.direction AND f.status_code = g.status_code
          AND NOT (g.pointers ? f.pointer)
        """,
        (*_columns(groups), source.tenant_id, source.project_id, source.id),
    )
    if not pointers:
        return
    cursor.execute(
        """
        INSERT INTO apiome.usage_field_daily AS f (
            tenant_id, project_id, source_id, environment, day, operation_key, direction,
            status_code, pointer, calls_with_field, calls_sampled)
        SELECT %s::uuid, %s::uuid, %s::uuid, g.*
        FROM unnest(%s::text[], %s::date[], %s::text[], %s::text[], %s::smallint[], %s::text[],
                    %s::bigint[], %s::bigint[]) AS g
        ON CONFLICT (tenant_id, project_id, source_id, environment, day, operation_key,
                     direction, status_code, pointer)
        DO UPDATE SET
            calls_with_field = f.calls_with_field + EXCLUDED.calls_with_field,
            calls_sampled = f.calls_sampled + EXCLUDED.calls_sampled,
            updated_at = CURRENT_TIMESTAMP
        """,
        (source.tenant_id, source.project_id, source.id, *_columns(pointers)),
    )


def _write_samples(cursor: Any, source: SourceConfig, plan: BatchPlan) -> None:
    """Insert the plan's clean, reduced samples into ``usage_sample``, in one statement."""
    rows = [
        (environment, captured_at, operation_key, status, json.dumps(exchange))
        for environment, captured_at, operation_key, status, exchange in plan.samples
    ]
    if not rows:
        return
    cursor.execute(
        """
        INSERT INTO apiome.usage_sample (
            tenant_id, project_id, source_id, environment, captured_at, operation_key,
            status_code, exchange)
        SELECT %s::uuid, %s::uuid, %s::uuid, g.*
        FROM unnest(%s::text[], %s::timestamptz[], %s::text[], %s::smallint[], %s::jsonb[]) AS g
        """,
        (source.tenant_id, source.project_id, source.id, *_columns(rows)),
    )


def _ledger(
    cursor: Any, source: SourceConfig, plan: BatchPlan, *, api_key_id: Optional[str], digest: str, now: datetime
) -> str:
    """Ledger the batch, count it against the tenant's day, stamp the source; return the row id.

    One statement: the ledger row, the ``usage_tenant_day`` counter it adds to (the tenant's
    rows older than yesterday are pruned in passing) and the source's ``last_received_at``, so the
    counter can never disagree with the ledger.
    """
    counts = plan.ledger_counts()
    cursor.execute(
        """
        WITH batch AS (
            INSERT INTO apiome.usage_ingest_batch (
                tenant_id, source_id, api_key_id, received_at, received, accepted, sampled_out,
                unmatched, rejected, scrub_findings, batch_digest)
            VALUES (%s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, tenant_id, received_day, received - rejected AS admitted
        ), counted AS (
            INSERT INTO apiome.usage_tenant_day AS d (tenant_id, day, events_used)
            SELECT tenant_id, received_day, admitted FROM batch
            ON CONFLICT (tenant_id, day) DO UPDATE SET
                events_used = d.events_used + EXCLUDED.events_used,
                updated_at = CURRENT_TIMESTAMP
        ), pruned AS (
            DELETE FROM apiome.usage_tenant_day o
            USING batch
            WHERE o.tenant_id = batch.tenant_id AND o.day < batch.received_day - 1
        ), stamped AS (
            UPDATE apiome.usage_source
            SET last_received_at = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s::uuid
        )
        SELECT id::text AS id FROM batch
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
            now,
            source.id,
        ),
    )
    return cursor.fetchone()["id"]


def _write_plan(cursor: Any, source: SourceConfig, plan: BatchPlan) -> None:
    """Write every counter table the plan fills (at most one statement per table)."""
    _write_hourly(cursor, source, plan)
    stamp_matches(cursor, plan.binding_matches, plan.binding_consumers)
    _write_unattributed(cursor, source, plan)
    _write_unmatched(cursor, source, plan)
    _write_fields(cursor, source, plan)
    _write_samples(cursor, source, plan)


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

    The batch is planned **before** the tenant's advisory lock is taken (DBP-1.8, #7191), from the
    finalized days and the live consumer bindings as they stood when it arrived, so two batches of
    one tenant only wait for each other while they write. Under the lock the write phase checks
    the cap (``usage_tenant_day``), whether any day the plan writes to was finalized meanwhile and
    whether the bindings changed; if either changed it plans again, there, as before DBP-1.8.
    Then each table is written with one statement, and the ledger row with the day's counter.

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

    # Planning, outside the lock: the CPU-heavy part of a batch.
    finalized = _finalized_days(db.execute_query(_FINALIZED_DAYS_SQL))
    bindings = _sorted_bindings(live_bindings(db, tenant_id, source.project_id))
    planned = plan_batch(
        raw_events,
        source,
        matcher,
        now=now,
        is_day_finalized=finalized.__contains__,
        consumers=ConsumerMatcher(list(bindings)),
    )

    def work(cursor: Any) -> Tuple[str, Optional[str], BatchPlan]:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"apiome.usage_ingest:{tenant_id}",))
        admission = _admission(cursor, tenant_id, today, _plan_days(planned))
        if not admission.admits(len(raw_events)):
            plan = rejected_plan(raw_events, REASON_QUOTA_EXCEEDED)
            return "quota", _ledger(cursor, source, plan, api_key_id=api_key_id, digest=digest, now=now), plan
        plan = planned
        # RDG-1.8: a binding deleted (or added) before the write phase began changes attribution,
        # and a day finalized since planning takes no counts; either one means planning again.
        current = _sorted_bindings(load_live_bindings(cursor, tenant_id, source.project_id))
        if admission.finalized or current != bindings:
            cursor.execute(_FINALIZED_DAYS_SQL)
            plan = plan_batch(
                raw_events,
                source,
                matcher,
                now=now,
                is_day_finalized=_finalized_days(cursor.fetchall()).__contains__,
                consumers=ConsumerMatcher(list(current)),
            )
        _write_plan(cursor, source, plan)
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
