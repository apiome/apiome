"""Reading and applying a retention run — PFX-1.11 (#6924).

:mod:`app.pact_retention` decides; this module reads what it decides on (every live version of the
pacticipants a run covers, with its branches and whether it is deployed or released) and, for a run
with ``dry_run: false``, makes the deletions.

**Applying re-plans.** The facts are read again inside the transaction that deletes, and the plan's
digest must equal the one the caller sends back from its dry run. A publish, a deployment or a
delete in between changes the digest, and the run is refused (``pact-retention-plan-changed``) with
the fresh plan to review — so a run never deletes what its caller did not see.

Deletions are soft (cause ``retention``; :func:`app.pact_cleanup_store.soft_delete_versions_tx`),
carry the run's reason, and the run appends one ``pacts.retention.apply`` audit row with its digest,
selectors and counts.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, List, Optional, Sequence, Tuple

from .consumer_contract_store import ConsumerActor
from .pact_cleanup_store import audit_tx, grace_days, soft_delete_versions_tx
from .pact_retention import (
    CODE_PLAN_CHANGED,
    CODE_PLAN_DIGEST_REQUIRED,
    CODE_TOO_MANY_PACTICIPANTS,
    CODE_TOO_MANY_VERSIONS,
    MAX_PACTICIPANTS_PER_RUN,
    MAX_VERSIONS_EVALUATED,
    RetentionError,
    RetentionPlan,
    RetentionRequest,
    VersionFacts,
    plan_retention,
)
from .pacticipant import PacticipantRecord, validate_reason
from .pacticipant_store import get_pacticipant, list_pacticipants

__all__ = ["RetentionPlanChangedError", "run_retention"]

_FACTS = """
    SELECT v.id::text AS id, v.pacticipant_id::text AS pacticipant_id, v.number, v.seq, v.created_at,
           COALESCE((SELECT array_agg(b.name ORDER BY b.name)
                     FROM apiome.pacticipant_branch_version bv
                     JOIN apiome.pacticipant_branch b ON b.id = bv.branch_id AND b.pacticipant_id = bv.pacticipant_id
                     WHERE bv.version_id = v.id AND bv.pacticipant_id = v.pacticipant_id), '{}') AS branches,
           (EXISTS (SELECT 1 FROM apiome.deployed_version d
                    WHERE d.version_id = v.id AND d.pacticipant_id = v.pacticipant_id AND d.currently_deployed)
            OR EXISTS (SELECT 1 FROM apiome.released_version r
                       WHERE r.version_id = v.id AND r.pacticipant_id = v.pacticipant_id
                         AND r.currently_supported)) AS in_use
    FROM apiome.pacticipant_version v
    WHERE v.pacticipant_id = ANY(%s::uuid[]) AND v.deleted_at IS NULL
    LIMIT %s
"""


class RetentionPlanChangedError(RetentionError):
    """The plan changed between the dry run and the apply; carries the fresh plan.

    Attributes:
        plan: The plan as it is now, to review and apply with its own digest.
    """

    def __init__(self, plan: RetentionPlan) -> None:
        """Build the refusal.

        Args:
            plan: The fresh plan.
        """
        super().__init__(
            CODE_PLAN_CHANGED,
            "the retention plan changed since the dry run (a version was published, deployed or deleted "
            "meanwhile); review the new plan and apply it with its plan_digest",
        )
        self.plan = plan


def _as_aware(value: Any) -> datetime:
    """A timestamp column as a timezone-aware ``datetime`` (UTC when the column has no zone)."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(str(value))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _facts(
    fetch: Callable[[str, Tuple[Any, ...]], Sequence[Any]], pacticipant_ids: Sequence[str]
) -> List[VersionFacts]:
    """Read the live versions retention decides on.

    Args:
        fetch: Runs a query and returns its rows (the database, or a cursor in a transaction).
        pacticipant_ids: The pacticipants the run covers.

    Returns:
        One fact per live version.

    Raises:
        RetentionError: ``pact-retention-too-many-versions`` above :data:`MAX_VERSIONS_EVALUATED`.
    """
    if not pacticipant_ids:
        return []
    rows = fetch(_FACTS, (list(pacticipant_ids), MAX_VERSIONS_EVALUATED + 1)) or []
    if len(rows) > MAX_VERSIONS_EVALUATED:
        raise RetentionError(
            CODE_TOO_MANY_VERSIONS,
            f"more than {MAX_VERSIONS_EVALUATED} live versions to evaluate; name fewer pacticipants per run",
        )
    return [
        VersionFacts(
            id=row["id"],
            pacticipant_id=row["pacticipant_id"],
            number=row["number"],
            seq=int(row["seq"]),
            created_at=_as_aware(row["created_at"]),
            branches=tuple(row.get("branches") or ()),
            in_use=bool(row.get("in_use")),
        )
        for row in rows
    ]


def _scope(db: Any, tenant_id: str, refs: Optional[Sequence[str]]) -> List[PacticipantRecord]:
    """The pacticipants a run covers: the named ones, or every live one.

    Raises:
        RetentionError: ``pact-retention-too-many-pacticipants`` above the request cap.
        PacticipantValidationError: ``pacticipant-not-found`` for a name that matches nothing — a
            run never silently skips a pacticipant it was asked to clean.
    """
    if refs is None:
        return list_pacticipants(db, tenant_id)
    if len(refs) > MAX_PACTICIPANTS_PER_RUN:
        raise RetentionError(
            CODE_TOO_MANY_PACTICIPANTS, f"a run names at most {MAX_PACTICIPANTS_PER_RUN} pacticipants"
        )
    seen = {}
    for ref in refs:
        record = get_pacticipant(db, tenant_id, ref)
        seen[record.id] = record
    return list(seen.values())


def run_retention(
    db: Any,
    tenant_id: str,
    request: RetentionRequest,
    *,
    actor: ConsumerActor,
    now: Optional[datetime] = None,
) -> RetentionPlan:
    """Plan a retention run and, when ``dry_run`` is false, apply it.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        request: The run.
        actor: Who is running it.
        now: The current time (tests pin it).

    Returns:
        The plan; ``applied`` true when the deletions were made.

    Raises:
        RetentionError: ``pact-retention-no-selector``, ``pact-retention-plan-digest-required``,
            ``pact-retention-too-many-pacticipants``, ``pact-retention-too-many-versions``, or
            :class:`RetentionPlanChangedError` (``pact-retention-plan-changed``) when the plan moved since the
            dry run.
        PacticipantValidationError: ``pacticipant-not-found`` for an unknown pacticipant,
            ``pacticipant-invalid-reason`` for a bad reason.
    """
    reason = validate_reason(request.reason)
    if not request.dry_run and not (request.plan_digest or "").strip():
        raise RetentionError(
            CODE_PLAN_DIGEST_REQUIRED,
            "applying a retention run needs the plan_digest of its dry run; send the same request with "
            "dry_run true first",
        )
    scope = _scope(db, tenant_id, request.pacticipants)
    triples = [(record.id, record.slug, record.name) for record in scope]
    ids = [record.id for record in scope]

    def plan_from(fetch: Callable[[str, Tuple[Any, ...]], Sequence[Any]]) -> Tuple[RetentionPlan, dict]:
        return plan_retention(
            request.keep,
            triples,
            _facts(fetch, ids),
            now=now,
            dry_run=request.dry_run,
            grace_days=grace_days(),
        )

    if request.dry_run:
        plan, _ = plan_from(db.execute_query)
        return plan

    slugs = {record.id: record.slug for record in scope}

    def work(cursor: Any) -> Tuple[str, RetentionPlan]:
        def fetch(query: str, params: Tuple[Any, ...]) -> Sequence[Any]:
            cursor.execute(query, params)
            return cursor.fetchall()

        plan, deletions = plan_from(fetch)
        if plan.plan_digest != request.plan_digest.strip():
            return "changed", plan
        deleted = 0
        for pacticipant_id, version_ids in deletions.items():
            deleted += len(
                soft_delete_versions_tx(
                    cursor, pacticipant_id, version_ids, cause="retention", reason=reason, actor=actor
                )
            )
        audit_tx(
            db,
            cursor,
            tenant_id,
            "pacts.retention.apply",
            actor,
            "pact-retention",
            {
                "plan_digest": plan.plan_digest,
                "keep": request.keep.model_dump(),
                "reason": reason,
                "deleted": deleted,
                "remaining": plan.remaining,
                "pacticipants": {slugs[pid]: len(vids) for pid, vids in deletions.items()},
            },
        )
        return "applied", plan.model_copy(update={"applied": True, "deleted": deleted})

    outcome, plan = db._guarded_tx(work)
    if outcome == "changed":
        raise RetentionPlanChangedError(plan)
    return plan
