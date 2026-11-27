"""Persistence for Pact verification results — PFX-1.4 (#6917).

:mod:`app.verification_result` says what a result *is*; this module is the only place one is read or
written (apiome-db V434).

**A publish is one transaction.** :func:`publish_verification_result` locks the verified pact
version, records the provider version through the registry's own statement
(:func:`app.pacticipant_store.record_version_tx`) — a verifier may publish for a version nothing
recorded yet — numbers the result (1, 2, 3 … per pact version, the lock keeping two concurrent
publishes from taking one number), and inserts it. Results are never updated (a V434 trigger).

**The provider branch** of a result is the branch its provider version was recorded on most
recently. Pact verifiers record it (``PUT …/pacticipants/{p}/branches/{b}/versions/{v}``) just
before they publish, so that is the branch the verification ran on.

**Everything starts from pacticipants of the caller's tenant**, resolved by
:func:`app.pacticipant_store.get_pacticipant`; nothing reaches another tenant's results.

Every function takes the :class:`~app.database.Database` it runs on, so the live-database tests can
pass one bound to a rolled-back transaction.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

import psycopg2
from psycopg2.extras import Json

from .consumer_contract_store import ConsumerActor
from .pact_publication import CODE_PACT_NOT_FOUND, PactPublicationError
from .pacticipant import (
    CODE_NOT_FOUND,
    PacticipantRecord,
    PacticipantValidationError,
    RecordedPacticipantVersion,
    validate_branch,
    validate_tags,
    validate_version_number,
)
from .pacticipant_store import ensure_pacticipant_tx, get_pacticipant, record_version_tx
from .revision_deprecation import is_uuid_string
from .verification_result import (
    CODE_REPORT_NOT_FOUND,
    CODE_VERIFICATION_NOT_FOUND,
    TRIGGER_PUBLISHED,
    VerificationRequest,
    VerificationResultRecord,
    verification_result_from_row,
)

__all__ = [
    "get_bidirectional_result",
    "get_latest_verification_result",
    "get_provider_result",
    "get_verification_result",
    "latest_results_by_pact",
    "list_bidirectional_results",
    "list_provider_results",
    "publish_verification_result",
    "record_broker_version",
]

#: What every result read returns: the row and the names its links need.
_RESULT_SELECT = """
    SELECT r.id::text AS id, r.number, r.success, r.build_url, r.provider_branch, r.test_results,
           r.verified_by_implementation, r.verified_by_version, r.verified_by_client_implementation,
           r.verified_by_client_version, r.verified_by_client_test_framework, r.pact_pending, r.wip,
           r.provider_verification_report_id::text AS provider_verification_report_id, r.created_at,
           r.kind, r.comparison, r.trigger, r.duration_ms, r.evidence_run_id::text AS evidence_run_id, r.seq,
           r.consumer_id::text AS consumer_id,
           c.slug AS consumer_slug, c.name AS consumer_name, pr.slug AS provider_slug, pr.name AS provider_name,
           pvn.number AS provider_version, pv.sha,
           (SELECT v.number FROM apiome.pact_publication p
            JOIN apiome.pacticipant_version v ON v.id = p.consumer_version_id
            WHERE p.pact_version_id = r.pact_version_id AND v.deleted_at IS NULL
            ORDER BY v.seq DESC LIMIT 1) AS consumer_version
    FROM apiome.verification_result r
    JOIN apiome.pact_version pv ON pv.id = r.pact_version_id
    JOIN apiome.pacticipant c ON c.id = r.consumer_id
    JOIN apiome.pacticipant pr ON pr.id = r.provider_id
    -- PFX-1.11: a result published by a deleted provider version is gone with it.
    JOIN apiome.pacticipant_version pvn ON pvn.id = r.provider_version_id AND pvn.deleted_at IS NULL
"""

_REPORT_FK = "verification_result_report_fk"


def _user_id(actor: ConsumerActor) -> Optional[str]:
    """The actor's user id when it is a storable UUID, else ``None``."""
    return actor.user_id if actor.user_id and is_uuid_string(str(actor.user_id)) else None


def _normalise_sha(sha: str) -> str:
    """A pact version SHA as stored: trimmed and lowercase."""
    return (sha or "").strip().lower()


def _pair(db: Any, tenant_id: str, provider_ref: str, consumer_ref: str) -> Tuple[PacticipantRecord, PacticipantRecord]:
    """Resolve the provider and the consumer in the caller's tenant.

    Raises:
        PacticipantValidationError: ``pacticipant-not-found``.
    """
    return get_pacticipant(db, tenant_id, provider_ref), get_pacticipant(db, tenant_id, consumer_ref)


def _missing_pact(consumer: PacticipantRecord, provider: PacticipantRecord, sha: str) -> PactPublicationError:
    """The 404 for a pact version the pair does not have."""
    return PactPublicationError(
        CODE_PACT_NOT_FOUND,
        f"no pact version '{sha}' between consumer '{consumer.slug}' and provider '{provider.slug}'",
    )


def publish_verification_result(
    db: Any,
    tenant_id: str,
    provider_ref: str,
    consumer_ref: str,
    sha: str,
    request: VerificationRequest,
    *,
    actor: ConsumerActor,
    pact_pending: Optional[bool] = None,
    wip: bool = False,
    trigger: Optional[str] = TRIGGER_PUBLISHED,
    duration_ms: Optional[int] = None,
    evidence_run_id: Optional[str] = None,
    number: Optional[int] = None,
    created_at: Optional[datetime] = None,
) -> VerificationResultRecord:
    """Store one verification of a pact version by a provider version.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        provider_ref: The provider's handle, id or name.
        consumer_ref: The consumer's handle, id or name.
        sha: The verified pact version.
        request: The checked result.
        actor: Who is publishing.
        pact_pending: Whether the for-verification link said the pact was pending (its metadata).
        wip: Whether the link said it was a work-in-progress pact.
        trigger: How the result came to be (:data:`app.verification_result.TRIGGERS`):
            ``published`` for a Pact verifier's post, the hosted verifier's own trigger otherwise.
        duration_ms: How long the run took, when Apiome ran it.
        evidence_run_id: The evidence run holding the run's assertions, when Apiome ran it.
        number: The result's number on its pact version, for an import from another broker that
            keeps the source's numbering (PFX-6.7, #6959); the next free number when ``None``.
        created_at: When the source recorded the result, for an import; ``None`` is now. It also
            dates the provider version when this call records it.

    Returns:
        The stored result.

    Raises:
        PacticipantValidationError: ``pacticipant-not-found`` for an unknown consumer or provider.
        PactPublicationError: ``pact-not-found`` when the pair has no such pact version;
            ``pact-verification-report-not-found`` when the linked report is not this workspace's.
    """
    provider, consumer = _pair(db, tenant_id, provider_ref, consumer_ref)
    wanted = _normalise_sha(sha)
    verified_by = request.verified_by

    def store(cursor: Any) -> str:
        # The row lock serialises numbering: a second publish for this pact version waits here.
        cursor.execute(
            """
            SELECT id::text AS id FROM apiome.pact_version
            WHERE consumer_id = %s::uuid AND provider_id = %s::uuid AND sha = %s
            FOR UPDATE
            """,
            (consumer.id, provider.id, wanted),
        )
        found = cursor.fetchone()
        if found is None:
            raise _missing_pact(consumer, provider, sha)
        pact_version_id = found["id"]
        version = record_version_tx(
            cursor,
            provider,
            request.provider_version,
            build_url=None,
            branch=None,
            tags=[],
            actor=actor,
            created_at=created_at,
        )
        cursor.execute(
            """
            SELECT b.name FROM apiome.pacticipant_branch_version bv
            JOIN apiome.pacticipant_branch b ON b.id = bv.branch_id AND b.pacticipant_id = bv.pacticipant_id
            WHERE bv.version_id = %s::uuid AND bv.pacticipant_id = %s::uuid
            ORDER BY bv.created_at DESC, b.name LIMIT 1
            """,
            (version.version.id, provider.id),
        )
        branch_row = cursor.fetchone()
        if number is not None:
            result_number = int(number)
        else:
            cursor.execute(
                "SELECT COALESCE(MAX(number), 0) + 1 AS next FROM apiome.verification_result"
                " WHERE pact_version_id = %s::uuid",
                (pact_version_id,),
            )
            result_number = int(cursor.fetchone()["next"])
        cursor.execute(
            """
            INSERT INTO apiome.verification_result (
                tenant_id, consumer_id, provider_id, pact_version_id, provider_version_id, number,
                success, build_url, provider_branch, test_results,
                verified_by_implementation, verified_by_version, verified_by_client_implementation,
                verified_by_client_version, verified_by_client_test_framework,
                pact_pending, wip, provider_verification_report_id, created_by, actor_label,
                trigger, duration_ms, evidence_run_id, created_at
            )
            VALUES (%s::uuid, %s::uuid, %s::uuid, %s::uuid, %s::uuid, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::uuid, %s::uuid, %s,
                    %s, %s, %s::uuid, COALESCE(%s::timestamptz, CURRENT_TIMESTAMP))
            RETURNING id::text AS id
            """,
            (
                tenant_id,
                consumer.id,
                provider.id,
                pact_version_id,
                version.version.id,
                result_number,
                request.success,
                request.build_url,
                branch_row["name"] if branch_row else None,
                Json(request.test_results),
                verified_by.get("implementation"),
                verified_by.get("version"),
                verified_by.get("client_implementation"),
                verified_by.get("client_version"),
                verified_by.get("client_test_framework"),
                pact_pending,
                wip,
                request.report_id,
                _user_id(actor),
                actor.label,
                trigger,
                max(0, int(duration_ms)) if duration_ms is not None else None,
                evidence_run_id if evidence_run_id and is_uuid_string(str(evidence_run_id)) else None,
                created_at,
            ),
        )
        return cursor.fetchone()["id"]

    def work(cursor: Any) -> VerificationResultRecord:
        # The savepoint makes the publish all or nothing whatever transaction the handle is in.
        cursor.execute("SAVEPOINT verification_publish")
        try:
            result_id = store(cursor)
            cursor.execute(_RESULT_SELECT + " WHERE r.id = %s::uuid", (result_id,))
            record = verification_result_from_row(dict(cursor.fetchone()))
        except Exception:
            cursor.execute("ROLLBACK TO SAVEPOINT verification_publish")
            raise
        cursor.execute("RELEASE SAVEPOINT verification_publish")
        return record

    try:
        return db._guarded_tx(work)
    except psycopg2.errors.ForeignKeyViolation as exc:
        if getattr(exc.diag, "constraint_name", None) == _REPORT_FK:
            raise PactPublicationError(
                CODE_REPORT_NOT_FOUND,
                f"/providerVerificationReportId: this workspace has no provider verification report "
                f"'{request.report_id}'",
                pointer="/providerVerificationReportId",
            ) from exc
        raise
    except psycopg2.DataError as exc:
        # JSONB cannot hold a string with a NUL escape (\u0000).
        raise PactPublicationError(
            "pact-verification-invalid",
            "/testResults: the test results contain a value the database does not accept "
            "(a \\u0000 character in a string is the usual cause)",
            pointer="/testResults",
        ) from exc


def _read_result(db: Any, where: str, params: Sequence[Any], *, missing: str) -> VerificationResultRecord:
    """Run one result read and return the latest match.

    Raises:
        PactPublicationError: ``pact-verification-not-found``.
    """
    rows = db.execute_query(_RESULT_SELECT + where + " ORDER BY r.seq DESC LIMIT 1", tuple(params))
    if not rows:
        raise PactPublicationError(CODE_VERIFICATION_NOT_FOUND, missing)
    return verification_result_from_row(dict(rows[0]))


def get_verification_result(
    db: Any, tenant_id: str, provider_ref: str, consumer_ref: str, sha: str, number: int
) -> VerificationResultRecord:
    """Read one result of a pact version by its number.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        provider_ref: The provider's handle, id or name.
        consumer_ref: The consumer's handle, id or name.
        sha: The pact version.
        number: The result's number.

    Returns:
        The result.

    Raises:
        PacticipantValidationError: ``pacticipant-not-found``.
        PactPublicationError: ``pact-verification-not-found``.
    """
    provider, consumer = _pair(db, tenant_id, provider_ref, consumer_ref)
    return _read_result(
        db,
        " WHERE r.provider_id = %s::uuid AND r.consumer_id = %s::uuid AND pv.sha = %s AND r.number = %s",
        (provider.id, consumer.id, _normalise_sha(sha), number),
        missing=f"pact version '{sha}' has no verification result {number}",
    )


def get_latest_verification_result(
    db: Any, tenant_id: str, provider_ref: str, consumer_ref: str, sha: str
) -> VerificationResultRecord:
    """Read the latest result of a pact version.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        provider_ref: The provider's handle, id or name.
        consumer_ref: The consumer's handle, id or name.
        sha: The pact version.

    Returns:
        The result published last.

    Raises:
        PacticipantValidationError: ``pacticipant-not-found``.
        PactPublicationError: ``pact-verification-not-found`` when it has none.
    """
    provider, consumer = _pair(db, tenant_id, provider_ref, consumer_ref)
    return _read_result(
        db,
        " WHERE r.provider_id = %s::uuid AND r.consumer_id = %s::uuid AND pv.sha = %s",
        (provider.id, consumer.id, _normalise_sha(sha)),
        missing=f"pact version '{sha}' has no verification results",
    )


#: The most bi-directional results :func:`list_bidirectional_results` returns at once.
MAX_BIDIRECTIONAL_LIST = 100


def list_bidirectional_results(db: Any, tenant_id: str, limit: int = 50) -> List[VerificationResultRecord]:
    """The workspace's most recent bi-directional results (PFX-2.5), newest first.

    Read through ``idx_verification_result_tenant_bidirectional`` (apiome-db V440), so the list
    never scans the native results.

    Args:
        db: The database.
        tenant_id: The caller's tenant; nothing of another tenant is read.
        limit: How many to return, clamped to 1 … :data:`MAX_BIDIRECTIONAL_LIST`.

    Returns:
        The results, each with its comparison payload.
    """
    bounded = max(1, min(int(limit), MAX_BIDIRECTIONAL_LIST))
    rows = db.execute_query(
        _RESULT_SELECT + " WHERE r.tenant_id = %s::uuid AND r.kind = 'bidirectional' ORDER BY r.seq DESC LIMIT %s",
        (tenant_id, bounded),
    )
    return [verification_result_from_row(dict(row)) for row in rows or []]


def get_bidirectional_result(db: Any, tenant_id: str, result_id: str) -> VerificationResultRecord:
    """Read one bi-directional result of the caller's tenant by its id (PFX-2.5).

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        result_id: The result's id (a UUID).

    Returns:
        The result, with its comparison payload.

    Raises:
        PactPublicationError: ``pact-verification-not-found`` for a malformed id, an id of another
            tenant, or a native result (it has no comparison); the message says which, but never
            whether another tenant has the id.
    """
    missing = f"this workspace has no bi-directional result '{result_id}'"
    if not is_uuid_string(str(result_id)):
        raise PactPublicationError(CODE_VERIFICATION_NOT_FOUND, missing)
    record = _read_result(
        db,
        " WHERE r.id = %s::uuid AND r.tenant_id = %s::uuid",
        (result_id, tenant_id),
        missing=missing,
    )
    if record.kind != "bidirectional" or record.comparison is None:
        raise PactPublicationError(
            CODE_VERIFICATION_NOT_FOUND,
            f"verification result '{result_id}' was published by a Pact verifier, not compared by Apiome, "
            "so it has no comparison fidelity report",
        )
    return record


#: The most results one page of a provider's history returns.
MAX_HISTORY_PAGE = 50


def list_provider_results(
    db: Any,
    tenant_id: str,
    provider: PacticipantRecord,
    *,
    consumer: Optional[PacticipantRecord] = None,
    before_seq: Optional[int] = None,
    limit: int = MAX_HISTORY_PAGE,
) -> Tuple[List[VerificationResultRecord], Optional[int]]:
    """One page of a provider's verification results, newest first (PFX-5.5, #6949).

    Read through ``idx_verification_result_provider_history`` (apiome-db V444), or
    ``idx_verification_result_pair`` when the consumer is given. Native and bi-directional results
    are both listed: they share one numbering and both decide can-i-deploy.

    Args:
        db: The database.
        tenant_id: The caller's tenant; nothing of another tenant is read.
        provider: The provider (already resolved in the tenant).
        consumer: Only this consumer's results, when given.
        before_seq: The cursor: only results recorded before this one.
        limit: Page size, clamped to 1 … :data:`MAX_HISTORY_PAGE`.

    Returns:
        ``(results, next_cursor)``; ``next_cursor`` is ``None`` on the last page.
    """
    bounded = max(1, min(int(limit), MAX_HISTORY_PAGE))
    where = " WHERE r.tenant_id = %s::uuid AND r.provider_id = %s::uuid"
    params: List[Any] = [tenant_id, provider.id]
    if consumer is not None:
        where += " AND r.consumer_id = %s::uuid"
        params.append(consumer.id)
    if before_seq is not None:
        where += " AND r.seq < %s"
        params.append(int(before_seq))
    params.append(bounded + 1)
    rows = db.execute_query(_RESULT_SELECT + where + " ORDER BY r.seq DESC LIMIT %s", tuple(params)) or []
    records = [verification_result_from_row(dict(row)) for row in rows[:bounded]]
    more = len(rows) > bounded and records and records[-1].seq is not None
    return records, (records[-1].seq if more else None)


def get_provider_result(
    db: Any, tenant_id: str, provider: PacticipantRecord, result_id: str
) -> VerificationResultRecord:
    """Read one verification result of a provider by its id (PFX-5.5, #6949).

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        provider: The provider (already resolved in the tenant).
        result_id: The result's id (a UUID).

    Returns:
        The result.

    Raises:
        PactPublicationError: ``pact-verification-not-found`` for a malformed id, or an id that is
            not one of this provider's results in this workspace (never saying which).
    """
    missing = f"provider '{provider.slug}' has no verification result '{result_id}'"
    if not is_uuid_string(str(result_id)):
        raise PactPublicationError(CODE_VERIFICATION_NOT_FOUND, missing)
    return _read_result(
        db,
        " WHERE r.id = %s::uuid AND r.tenant_id = %s::uuid AND r.provider_id = %s::uuid",
        (result_id, tenant_id, provider.id),
        missing=missing,
    )


def latest_results_by_pact(
    db: Any, tenant_id: str, provider: PacticipantRecord, pacts: Sequence[Tuple[str, str]]
) -> Dict[Tuple[str, str], VerificationResultRecord]:
    """The newest result of each of a provider's pact versions (PFX-5.5, #6949).

    A pact version with no result (or only results of deleted provider versions) is absent from
    the answer: that is what makes it *stale*.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        provider: The provider (already resolved in the tenant).
        pacts: ``(consumer_id, sha)`` pairs.

    Returns:
        ``{(consumer_id, sha): result}`` for every pact version that has a result.
    """
    if not pacts:
        return {}
    keys = sorted({(str(consumer_id), _normalise_sha(sha)) for consumer_id, sha in pacts})
    # Start from the (consumer, sha) keys: each finds its pact version through its unique key and
    # that version's results through their index (PFX-6.6). Matching on
    # `consumer_id::text || ':' || sha` instead scanned every result of the provider.
    rows = (
        db.execute_query(
            _RESULT_SELECT
            + """
        WHERE r.id IN (
            SELECT DISTINCT ON (r2.pact_version_id) r2.id
            FROM unnest(%s::uuid[], %s::text[]) k(consumer_id, sha)
            JOIN apiome.pact_version pv2
              ON pv2.consumer_id = k.consumer_id AND pv2.provider_id = %s::uuid AND pv2.sha = k.sha
             AND pv2.tenant_id = %s::uuid
            JOIN apiome.verification_result r2
              ON r2.pact_version_id = pv2.id AND r2.tenant_id = %s::uuid AND r2.provider_id = %s::uuid
            JOIN apiome.pacticipant_version v2 ON v2.id = r2.provider_version_id AND v2.deleted_at IS NULL
            ORDER BY r2.pact_version_id, r2.seq DESC
        )
        """,
            (
                [consumer_id for consumer_id, _ in keys],
                [sha for _, sha in keys],
                provider.id,
                tenant_id,
                tenant_id,
                provider.id,
            ),
        )
        or []
    )
    found: Dict[Tuple[str, str], VerificationResultRecord] = {}
    for row in rows:
        record = verification_result_from_row(dict(row))
        found[(str(row["consumer_id"]), record.sha)] = record
    return found


def record_broker_version(
    db: Any,
    tenant_id: str,
    pacticipant_ref: str,
    number: str,
    *,
    actor: ConsumerActor,
    branch: Optional[str] = None,
    tags: Sequence[str] = (),
) -> Tuple[PacticipantRecord, RecordedPacticipantVersion]:
    """Record a version with a branch or tags, as a verifier does before it publishes a result.

    The broker's ``PUT …/branches/{b}/versions/{v}`` and ``PUT …/versions/{v}/tags/{t}`` create
    the version — and the pacticipant, named by the URL — when they do not exist yet.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        pacticipant_ref: The pacticipant's handle, id or name.
        number: The version number.
        actor: Who is recording it.
        branch: A branch to record the version on.
        tags: Tags to put on the version.

    Returns:
        The pacticipant, and the version with whether this call created it.

    Raises:
        PacticipantValidationError: For a malformed name, version, branch or tag, and
            ``pacticipant-not-found`` for an id that names no pacticipant.
    """
    version_number = validate_version_number(number)
    checked_branch = validate_branch(branch) if branch else None
    checked_tags = validate_tags(list(tags))
    try:
        existing: Optional[PacticipantRecord] = get_pacticipant(db, tenant_id, pacticipant_ref)
    except PacticipantValidationError as exc:
        # An unknown id names nothing to register; only a name creates a pacticipant.
        if exc.code != CODE_NOT_FOUND or is_uuid_string(pacticipant_ref.strip()):
            raise
        existing = None

    def work(cursor: Any) -> Tuple[PacticipantRecord, RecordedPacticipantVersion]:
        pacticipant = existing or ensure_pacticipant_tx(cursor, tenant_id, pacticipant_ref, actor=actor)
        recorded = record_version_tx(
            cursor, pacticipant, version_number, build_url=None, branch=checked_branch, tags=checked_tags, actor=actor
        )
        return pacticipant, recorded

    return db._guarded_tx(work)
