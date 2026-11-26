"""Recording and sending pact commit statuses — PFX-4.4 (#6941).

:mod:`app.pact_commit_status` says what a status *is*; this module decides which statuses a
publish or a verification result produces, records them in ``pact_commit_status`` (apiome-db
V443), and sends them through :mod:`app.provider_status_adapter`.

**The order is record, resolve, send.** Every verdict is written first, together with where it can
go: the pacticipant's ``repository_url`` is matched to a repository registered in the workspace,
and the version number must be a commit SHA. A verdict that has nowhere to go is recorded as
``suppressed`` with the reason and never leaves the process. One that has is recorded as
``queued``, then sent with the stored credential of that registration (the same vault lookup the
GNC-2.2 provider checks use — :func:`app.provider_check_store._repository_token`), and its row
moves to ``dispatched`` or ``failed``.

**It never fails the write that caused it.** :func:`post_publish_statuses` and
:func:`post_verification_statuses` run after the publish or the verification result has committed,
catch everything, and log what they could not do: a provider having a bad minute must not turn a
published pact into an error for the CI job that published it. The failure is on the status row,
and :func:`retry_commit_status` sends it again.

**Everything starts from the caller's tenant.** Pacticipants, repositories and statuses are read by
``tenant_id``; a status id from another tenant reads as not found.

Every function takes the :class:`~app.database.Database` it runs on, so the live-database tests can
pass one bound to a rolled-back transaction.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from .keyset_pagination import encode_time_id_cursor
from .pact_commit_status import (
    CODE_DISABLED,
    CODE_NO_REPOSITORY,
    CODE_NOT_A_COMMIT,
    CODE_PROVIDER_UNSUPPORTED,
    CODE_REPOSITORY_NOT_REGISTERED,
    CODE_STATUS_NOT_FOUND,
    CODE_STATUS_NOT_RETRYABLE,
    OUTCOME_DISPATCHED,
    OUTCOME_FAILED,
    OUTCOME_QUEUED,
    OUTCOME_SUPPRESSED,
    PROVIDER_HOSTS,
    RETRYABLE_OUTCOMES,
    SIDE_CONSUMER,
    SIDE_PROVIDER,
    CommitStatusRecord,
    PactCommitStatusError,
    StatusIntent,
    context_for,
    is_commit_sha,
    normalize_repository_url,
    pending_description,
    repository_host,
    verdict_description,
)
from .pact_publication_store import PublishOutcome
from .provider_checks import CODE_PROVIDER_FORBIDDEN, STATE_FAIL, STATE_PASS, STATE_PENDING
from .provider_status_adapter import (
    ClientFactory,
    PublishRequest,
    StatusPublishError,
    commit_status_adapter_for,
)
from .verification_result import VerificationResultRecord

logger = logging.getLogger(__name__)

__all__ = [
    "Resolution",
    "intents_for_publish",
    "intents_for_verification",
    "list_commit_statuses",
    "post_publish_statuses",
    "post_verification_statuses",
    "resolve_target",
    "retry_commit_status",
    "send_status",
]

#: How the adapter obtains an HTTP client. ``None`` uses the adapter's default; tests replace it.
CLIENT_FACTORY: Optional[ClientFactory] = None

#: The columns a status row is read with (owner, consumer and provider handles joined in).
_SELECT = """
    SELECT s.id::text AS id, s.tenant_id::text AS tenant_id, s.pacticipant_id::text AS pacticipant_id,
           s.pacticipant_version_id::text AS pacticipant_version_id, s.consumer_id::text AS consumer_id,
           s.provider_id::text AS provider_id, s.side, s.context, s.state, s.description, s.target_url,
           s.pact_version_sha, s.verification_number, s.commit_sha, s.repository_id::text AS repository_id,
           s.provider AS git_provider, s.repo_full_name, s.outcome, s.reason_code, s.message, s.http_status,
           s.attempts, s.created_at, s.updated_at,
           p.slug AS pacticipant_slug, p.repository_url, v.number AS version_number,
           c.slug AS consumer_slug, pr.slug AS provider_slug
    FROM apiome.pact_commit_status s
    JOIN apiome.pacticipant p ON p.id = s.pacticipant_id AND p.tenant_id = s.tenant_id
    JOIN apiome.pacticipant_version v ON v.id = s.pacticipant_version_id
    JOIN apiome.pacticipant c ON c.id = s.consumer_id AND c.tenant_id = s.tenant_id
    JOIN apiome.pacticipant pr ON pr.id = s.provider_id AND pr.tenant_id = s.tenant_id
"""


@dataclass(frozen=True)
class Resolution:
    """Where a verdict can be sent — or why it cannot.

    Attributes:
        outcome: ``queued`` (it can be sent) or ``suppressed``.
        reason_code: Why it is suppressed; ``None`` when queued.
        message: The reason in words.
        commit_sha: The commit, when the version number is one.
        repository_id: The matching registered repository.
        provider: ``github`` or ``gitlab``, once a repository matched.
        repo_full_name: The repository's lower-cased full name.
    """

    outcome: str
    reason_code: Optional[str] = None
    message: str = ""
    commit_sha: Optional[str] = None
    repository_id: Optional[str] = None
    provider: Optional[str] = None
    repo_full_name: Optional[str] = None


# ---------------------------------------------------------------------------------------------
# Small reads
# ---------------------------------------------------------------------------------------------


def _one(cursor: Any, query: str, params: Any) -> Optional[Dict[str, Any]]:
    """Run ``query`` and return its first row, or ``None``."""
    cursor.execute(query, params)
    row = cursor.fetchone()
    return dict(row) if row else None


def _pacticipant(cursor: Any, tenant_id: str, slug: str) -> Optional[Dict[str, Any]]:
    """A live pacticipant of the tenant by handle: id, slug, name and repository URL."""
    return _one(
        cursor,
        """
        SELECT id::text AS id, slug, name, repository_url
        FROM apiome.pacticipant
        WHERE tenant_id = %s::uuid AND slug = %s AND deleted_at IS NULL
        """,
        (tenant_id, slug),
    )


def _version_id(cursor: Any, pacticipant_id: str, number: str) -> Optional[str]:
    """The id of a live version of a pacticipant, by number."""
    row = _one(
        cursor,
        """
        SELECT id::text AS id FROM apiome.pacticipant_version
        WHERE pacticipant_id = %s::uuid AND number = %s AND deleted_at IS NULL
        """,
        (pacticipant_id, number),
    )
    return row["id"] if row else None


def _absolute(url: Optional[str]) -> Optional[str]:
    """Keep a link only when it is an absolute http(s) URL (V443's check)."""
    text = str(url or "").strip()
    if text.lower().startswith(("http://", "https://")) and len(text) <= 2048 and " " not in text:
        return text
    return None


# ---------------------------------------------------------------------------------------------
# Which statuses an event produces
# ---------------------------------------------------------------------------------------------


def intents_for_publish(cursor: Any, tenant_id: str, base: str, outcome: PublishOutcome) -> List[StatusIntent]:
    """The statuses a committed publish produces: one per stored or replaced pact.

    Each goes on the consumer's commit. It is ``pending`` — awaiting verification by the provider —
    unless the provider's main branch has already verified this exact pact content, in which case
    it carries that verdict. A pact the request left unchanged produces nothing (its status is
    already on the commit).

    Args:
        cursor: An open cursor.
        tenant_id: The publisher's tenant.
        base: The broker base URL the client used; the status links to the pact under it.
        outcome: What the publish stored.

    Returns:
        The intents, in request order.
    """
    from .pact_webhook_events import _latest_main_verification, pact_url, verification_result_url

    consumer = outcome.consumer
    intents: List[StatusIntent] = []
    for published in outcome.pacts:
        if not (published.created or published.replaced):
            continue
        pact = published.pact
        provider = _pacticipant(cursor, tenant_id, pact.provider_slug)
        version_id = _version_id(cursor, consumer.id, pact.consumer_version)
        if provider is None or version_id is None:
            continue
        main = _latest_main_verification(cursor, consumer.id, provider["id"], pact.sha)
        if main is None:
            state, description = STATE_PENDING, pending_description(pact.provider_name)
            target = pact_url(base, pact.provider_slug, pact.consumer_slug, pact.sha, pact.consumer_version)
            number = None
        else:
            success = bool(main["success"])
            state = STATE_PASS if success else STATE_FAIL
            description = verdict_description(SIDE_CONSUMER, success, pact.provider_name, main["provider_version"])
            number = int(main["number"])
            target = verification_result_url(base, pact.provider_slug, pact.consumer_slug, pact.sha, number)
        intents.append(
            StatusIntent(
                tenant_id=tenant_id,
                pacticipant_id=consumer.id,
                pacticipant_version_id=version_id,
                version_number=pact.consumer_version,
                repository_url=consumer.repository_url,
                consumer_id=consumer.id,
                provider_id=provider["id"],
                side=SIDE_CONSUMER,
                context=context_for(pact.consumer_slug, pact.provider_slug),
                state=state,
                description=description,
                target_url=_absolute(target),
                pact_version_sha=pact.sha,
                verification_number=number,
            )
        )
    return intents


def intents_for_verification(
    cursor: Any, tenant_id: str, base: str, result: VerificationResultRecord
) -> List[StatusIntent]:
    """The statuses a committed verification result produces.

    One on the provider's commit (the version that verified) and, when the result names it, one on
    the consumer's commit (the latest version that published the verified pact). Both carry
    ``pass`` or ``fail`` and link to the result.

    Args:
        cursor: An open cursor.
        tenant_id: The publisher's tenant.
        base: The broker base URL the client used.
        result: The stored result.

    Returns:
        The intents: provider first, then consumer.
    """
    from .pact_webhook_events import verification_result_url

    consumer = _pacticipant(cursor, tenant_id, result.consumer_slug)
    provider = _pacticipant(cursor, tenant_id, result.provider_slug)
    if consumer is None or provider is None:
        return []
    state = STATE_PASS if result.success else STATE_FAIL
    target = _absolute(
        verification_result_url(base, result.provider_slug, result.consumer_slug, result.sha, result.number)
    )
    context = context_for(result.consumer_slug, result.provider_slug)
    sides: List[Tuple[str, Dict[str, Any], Optional[str], str, Optional[str]]] = [
        (SIDE_PROVIDER, provider, result.provider_version, result.consumer_name, result.consumer_version),
    ]
    if result.consumer_version:
        sides.append((SIDE_CONSUMER, consumer, result.consumer_version, result.provider_name, result.provider_version))
    intents: List[StatusIntent] = []
    for side, owner, number, other_name, other_version in sides:
        if not number:
            continue
        version_id = _version_id(cursor, owner["id"], number)
        if version_id is None:
            continue
        intents.append(
            StatusIntent(
                tenant_id=tenant_id,
                pacticipant_id=owner["id"],
                pacticipant_version_id=version_id,
                version_number=number,
                repository_url=owner.get("repository_url"),
                consumer_id=consumer["id"],
                provider_id=provider["id"],
                side=side,  # type: ignore[arg-type]
                context=context,
                state=state,  # type: ignore[arg-type]
                description=verdict_description(side, result.success, other_name, other_version),
                target_url=target,
                pact_version_sha=result.sha,
                verification_number=result.number,
            )
        )
    return intents


# ---------------------------------------------------------------------------------------------
# Where a status can go
# ---------------------------------------------------------------------------------------------


def _full_name_from_normalized(normalized: str) -> str:
    """``owner/name`` from a normalized clone URL (``https://host/owner/name.git``)."""
    path = normalized.split("://", 1)[-1].split("/", 1)[-1]
    return path[: -len(".git")] if path.endswith(".git") else path


def resolve_target(cursor: Any, tenant_id: str, repository_url: Optional[str], version_number: str) -> Resolution:
    """Decide where a verdict about ``version_number`` can be written, or why it cannot.

    Checks, in order: the pacticipant names a repository; the version number is a commit SHA; a
    live repository registered in the workspace matches the URL; that repository is on GitHub or
    GitLab (``github.com`` / ``gitlab.com``); status publishing is switched on.

    Args:
        cursor: An open cursor.
        tenant_id: The tenant.
        repository_url: The pacticipant's repository URL.
        version_number: The pacticipant version number.

    Returns:
        A ``queued`` resolution naming the repository and commit, or a ``suppressed`` one with the
        reason.
    """
    from .config import settings

    if not repository_url:
        return Resolution(
            OUTCOME_SUPPRESSED,
            CODE_NO_REPOSITORY,
            "The pacticipant has no repository URL; set one (pacticipant `repositoryUrl`) to get commit statuses.",
        )
    if not is_commit_sha(version_number):
        return Resolution(
            OUTCOME_SUPPRESSED,
            CODE_NOT_A_COMMIT,
            f"Version {version_number[:80]!r} is not a git commit SHA; publish with the commit as the version "
            "number to get commit statuses.",
        )
    commit = version_number.strip().lower()
    normalized = normalize_repository_url(repository_url)
    row = (
        _one(
            cursor,
            """
            SELECT id::text AS id, provider, clone_url, repository_full_name
            FROM apiome.tenant_repositories
            WHERE tenant_id = %s::uuid AND clone_url_normalized = %s AND deleted_at IS NULL
            LIMIT 1
            """,
            (tenant_id, normalized),
        )
        if normalized
        else None
    )
    if row is None:
        return Resolution(
            OUTCOME_SUPPRESSED,
            CODE_REPOSITORY_NOT_REGISTERED,
            f"No repository registered in this workspace matches {repository_url[:200]}; register it under "
            "Repositories with a linked GitHub or GitLab account.",
            commit_sha=commit,
        )
    provider = str(row.get("provider") or "").lower()
    full_name = str(row.get("repository_full_name") or _full_name_from_normalized(str(normalized))).lower()
    host = repository_host(row.get("clone_url"))
    if PROVIDER_HOSTS.get(provider) != host:
        return Resolution(
            OUTCOME_SUPPRESSED,
            CODE_PROVIDER_UNSUPPORTED,
            f"Commit statuses can be written to github.com and gitlab.com repositories; this one is "
            f"{provider or 'unknown'} on {host or 'an unknown host'}.",
            commit_sha=commit,
            repository_id=row["id"],
            provider=provider or None,
            repo_full_name=full_name,
        )
    if not settings.provider_checks_enabled:
        return Resolution(
            OUTCOME_SUPPRESSED,
            CODE_DISABLED,
            "Status publishing is switched off for this deployment; the verdict was recorded only.",
            commit_sha=commit,
            repository_id=row["id"],
            provider=provider,
            repo_full_name=full_name,
        )
    return Resolution(
        OUTCOME_QUEUED, commit_sha=commit, repository_id=row["id"], provider=provider, repo_full_name=full_name
    )


# ---------------------------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------------------------


def _upsert(cursor: Any, intent: StatusIntent, resolution: Resolution) -> Dict[str, Any]:
    """Record the verdict for its version and context (a newer one moves the row)."""
    cursor.execute(
        """
        INSERT INTO apiome.pact_commit_status
          (tenant_id, pacticipant_id, pacticipant_version_id, consumer_id, provider_id, side, context, state,
           description, target_url, pact_version_sha, verification_number, commit_sha, repository_id, provider,
           repo_full_name, outcome, reason_code, message, http_status, created_at, updated_at)
        VALUES (%s::uuid, %s::uuid, %s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s::uuid, %s,
                %s, %s, %s, %s, NULL, clock_timestamp(), clock_timestamp())
        ON CONFLICT (tenant_id, pacticipant_version_id, context) DO UPDATE SET
          side = EXCLUDED.side, consumer_id = EXCLUDED.consumer_id, provider_id = EXCLUDED.provider_id,
          state = EXCLUDED.state, description = EXCLUDED.description, target_url = EXCLUDED.target_url,
          pact_version_sha = EXCLUDED.pact_version_sha, verification_number = EXCLUDED.verification_number,
          commit_sha = EXCLUDED.commit_sha, repository_id = EXCLUDED.repository_id, provider = EXCLUDED.provider,
          repo_full_name = EXCLUDED.repo_full_name, outcome = EXCLUDED.outcome,
          reason_code = EXCLUDED.reason_code, message = EXCLUDED.message, http_status = NULL,
          updated_at = clock_timestamp()
        RETURNING id::text AS id
        """,
        (
            intent.tenant_id,
            intent.pacticipant_id,
            intent.pacticipant_version_id,
            intent.consumer_id,
            intent.provider_id,
            intent.side,
            intent.context,
            intent.state,
            intent.description[:255],
            intent.target_url,
            intent.pact_version_sha,
            intent.verification_number,
            resolution.commit_sha,
            resolution.repository_id,
            resolution.provider,
            resolution.repo_full_name,
            resolution.outcome,
            resolution.reason_code,
            resolution.message[:2000],
        ),
    )
    status_id = cursor.fetchone()["id"]
    row = _one(cursor, _SELECT + " WHERE s.id = %s::uuid", (status_id,))
    assert row is not None  # just written in this transaction
    return row


def _record_all(db: Any, intents_of: Callable[[Any], List[StatusIntent]]) -> List[Dict[str, Any]]:
    """Plan and record statuses in one transaction; returns the written rows."""

    def work(cursor: Any) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for intent in intents_of(cursor):
            resolution = resolve_target(cursor, intent.tenant_id, intent.repository_url, intent.version_number)
            rows.append(_upsert(cursor, intent, resolution))
        return rows

    return list(db._guarded_tx(work) or [])


def _finish(db: Any, row: Mapping[str, Any], **changes: Any) -> Dict[str, Any]:
    """Write the result of a send onto its row — unless a newer verdict moved the row meanwhile.

    The row's ``updated_at`` is the version token: a verdict recorded while this one was in flight
    keeps its own outcome instead of inheriting this one's.
    """

    def work(cursor: Any) -> Dict[str, Any]:
        cursor.execute(
            """
            UPDATE apiome.pact_commit_status
            SET outcome = %s, reason_code = %s, message = %s, http_status = %s,
                attempts = attempts + %s, updated_at = clock_timestamp()
            WHERE id = %s::uuid AND tenant_id = %s::uuid AND updated_at = %s
            """,
            (
                changes["outcome"],
                changes.get("reason_code"),
                str(changes.get("message") or "")[:2000],
                changes.get("http_status"),
                1 if changes.get("attempted") else 0,
                row["id"],
                row["tenant_id"],
                row["updated_at"],
            ),
        )
        fresh = _one(
            cursor, _SELECT + " WHERE s.id = %s::uuid AND s.tenant_id = %s::uuid", (row["id"], row["tenant_id"])
        )
        return fresh or dict(row)

    return dict(db._guarded_tx(work) or row)


def send_status(db: Any, row: Mapping[str, Any], *, actor_id: Optional[str] = None) -> Dict[str, Any]:
    """Send one ``queued`` status to its provider and record what happened. Never raises.

    Args:
        db: The database.
        row: The recorded status row (from this module's reads).
        actor_id: The acting user, when a person triggered the send (a retry).

    Returns:
        The row after the send: ``dispatched``, ``failed``, or ``suppressed`` when no stored
        credential covers the repository. A row that is not ``queued`` is returned unchanged.
    """
    from .provider_check_store import _repository_token

    if row.get("outcome") != OUTCOME_QUEUED:
        return dict(row)
    try:
        token = _repository_token(str(row["tenant_id"]), str(row["repository_id"]), actor_id)
        if not token:
            return _finish(
                db,
                row,
                outcome=OUTCOME_SUPPRESSED,
                reason_code=CODE_PROVIDER_FORBIDDEN,
                message=(
                    "No stored credential authorizes writing a status on this repository; link the account "
                    "it was registered with. The verdict was recorded only."
                ),
            )
        adapter = commit_status_adapter_for(str(row["git_provider"]), token, client_factory=CLIENT_FACTORY)
        request = PublishRequest(
            repo_full_name=str(row["repo_full_name"]),
            commit_sha=str(row["commit_sha"]),
            name=str(row["context"]),
            state=str(row["state"]),
            title=str(row.get("description") or ""),
            details_url=str(row.get("target_url") or ""),
        )
        try:
            published = adapter.publish(request)
        except StatusPublishError as exc:
            return _finish(
                db,
                row,
                outcome=OUTCOME_FAILED,
                reason_code=exc.code,
                message=exc.message,
                http_status=exc.http_status,
                attempted=True,
            )
        return _finish(db, row, outcome=OUTCOME_DISPATCHED, http_status=published.status_code, attempted=True)
    except Exception:  # noqa: BLE001 - a status problem never fails the caller
        logger.exception("pact commit status: send failed for status %s", row.get("id"))
        return dict(row)


def _post(db: Any, tenant_id: str, intents_of: Callable[[Any], List[StatusIntent]]) -> List[CommitStatusRecord]:
    """Record, then send, the statuses ``intents_of`` plans. Never raises."""
    try:
        rows = _record_all(db, intents_of)
    except Exception:  # noqa: BLE001 - a status problem never fails the publish
        logger.exception("pact commit status: failed to record statuses for tenant %s", tenant_id)
        return []
    return [_record(send_status(db, row)) for row in rows]


def post_publish_statuses(db: Any, tenant_id: str, base: str, outcome: PublishOutcome) -> List[CommitStatusRecord]:
    """Post the consumer-commit statuses of a publish that has committed.

    Args:
        db: The database.
        tenant_id: The publisher's tenant.
        base: The broker base URL the client used.
        outcome: What the publish stored.

    Returns:
        The recorded statuses after sending; empty when nothing changed or recording failed (logged).
    """
    if not any(published.created or published.replaced for published in outcome.pacts):
        return []
    return _post(db, tenant_id, lambda cursor: intents_for_publish(cursor, tenant_id, base, outcome))


def post_verification_statuses(
    db: Any, tenant_id: str, base: str, result: VerificationResultRecord
) -> List[CommitStatusRecord]:
    """Post the provider- and consumer-commit statuses of a verification result that has committed.

    Args:
        db: The database.
        tenant_id: The publisher's tenant.
        base: The broker base URL the client used.
        result: The stored result.

    Returns:
        The recorded statuses after sending; empty when recording failed (logged).
    """
    return _post(db, tenant_id, lambda cursor: intents_for_verification(cursor, tenant_id, base, result))


# ---------------------------------------------------------------------------------------------
# Reads and retry
# ---------------------------------------------------------------------------------------------


def _iso(value: Any) -> Optional[str]:
    """A timestamp as ISO-8601 text."""
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    return isoformat() if callable(isoformat) else str(value)


def _record(row: Mapping[str, Any]) -> CommitStatusRecord:
    """The API shape of a status row."""
    return CommitStatusRecord(
        id=str(row["id"]),
        pacticipant=str(row["pacticipant_slug"]),
        version=str(row["version_number"]),
        consumer=str(row["consumer_slug"]),
        provider=str(row["provider_slug"]),
        side=row["side"],
        context=str(row["context"]),
        state=row["state"],
        description=str(row.get("description") or ""),
        target_url=row.get("target_url"),
        pact_version_sha=row.get("pact_version_sha"),
        verification_number=row.get("verification_number"),
        commit_sha=row.get("commit_sha"),
        git_provider=row.get("git_provider"),
        repository=row.get("repo_full_name"),
        repository_id=row.get("repository_id"),
        outcome=row["outcome"],
        reason_code=row.get("reason_code"),
        message=str(row.get("message") or ""),
        http_status=row.get("http_status"),
        attempts=int(row.get("attempts") or 0),
        created_at=_iso(row.get("created_at")),
        updated_at=_iso(row.get("updated_at")),
    )


def list_commit_statuses(
    db: Any,
    tenant_id: str,
    *,
    pacticipant: Optional[str] = None,
    version: Optional[str] = None,
    outcome: Optional[str] = None,
    limit: int = 50,
    after: Optional[Tuple[Any, str]] = None,
) -> Tuple[List[CommitStatusRecord], Optional[str]]:
    """A page of the tenant's commit statuses, most recently updated first.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        pacticipant: Only statuses on this pacticipant's commits (handle).
        version: Only statuses about this version number (with or without ``pacticipant``).
        outcome: Only statuses with this outcome.
        limit: Page size.
        after: ``(updated_at, id)`` of the last row of the previous page.

    Returns:
        ``(items, next_cursor)``; ``next_cursor`` is ``None`` on the last page.
    """
    clauses = ["s.tenant_id = %s::uuid"]
    params: List[Any] = [tenant_id]
    if pacticipant:
        clauses.append("p.slug = %s")
        params.append(pacticipant)
    if version:
        clauses.append("v.number = %s")
        params.append(version)
    if outcome:
        clauses.append("s.outcome = %s")
        params.append(outcome)
    if after is not None:
        clauses.append("(s.updated_at, s.id) < (%s, %s::uuid)")
        params.extend([after[0], after[1]])
    query = (
        _SELECT + " WHERE " + " AND ".join(clauses) + " ORDER BY s.updated_at DESC, s.id DESC LIMIT %s"
    )
    params.append(limit + 1)
    rows = [dict(row) for row in db.execute_query(query, tuple(params))]
    items = rows[:limit]
    next_cursor = (
        encode_time_id_cursor(items[-1]["updated_at"], items[-1]["id"]) if len(rows) > limit and items else None
    )
    return [_record(row) for row in items], next_cursor


def retry_commit_status(
    db: Any, tenant_id: str, status_id: str, *, actor_id: Optional[str] = None
) -> CommitStatusRecord:
    """Send a ``suppressed`` or ``failed`` status again.

    Where it can go is decided afresh, so a retry after registering the repository, linking the
    account or fixing the repository URL sends the status; one whose cause is still there is
    recorded with the same reason again.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        status_id: The status.
        actor_id: The acting user; their linked account may authorize the send.

    Returns:
        The status after the retry.

    Raises:
        PactCommitStatusError: ``pact-status-not-found`` for an id of no status of this tenant
            (including a malformed id), ``pact-status-not-retryable`` for a status that was
            accepted or is being sent.
    """
    from .revision_deprecation import is_uuid_string

    if not is_uuid_string(status_id):
        raise PactCommitStatusError(CODE_STATUS_NOT_FOUND, "No such commit status in this workspace.")

    def work(cursor: Any) -> Any:
        query = _SELECT + " WHERE s.id = %s::uuid AND s.tenant_id = %s::uuid FOR UPDATE OF s"
        row = _one(cursor, query, (status_id, tenant_id))
        if row is None:
            return {"error": CODE_STATUS_NOT_FOUND}
        if row["outcome"] not in RETRYABLE_OUTCOMES:
            return {"error": CODE_STATUS_NOT_RETRYABLE, "outcome": row["outcome"]}
        resolution = resolve_target(cursor, tenant_id, row.get("repository_url"), str(row["version_number"]))
        intent = StatusIntent(
            tenant_id=tenant_id,
            pacticipant_id=row["pacticipant_id"],
            pacticipant_version_id=row["pacticipant_version_id"],
            version_number=str(row["version_number"]),
            repository_url=row.get("repository_url"),
            consumer_id=row["consumer_id"],
            provider_id=row["provider_id"],
            side=row["side"],
            context=row["context"],
            state=row["state"],
            description=str(row.get("description") or ""),
            target_url=row.get("target_url"),
            pact_version_sha=row.get("pact_version_sha"),
            verification_number=row.get("verification_number"),
        )
        return {"row": _upsert(cursor, intent, resolution)}

    found = db._guarded_tx(work) or {}
    if found.get("error") == CODE_STATUS_NOT_FOUND:
        raise PactCommitStatusError(CODE_STATUS_NOT_FOUND, "No such commit status in this workspace.")
    if found.get("error") == CODE_STATUS_NOT_RETRYABLE:
        raise PactCommitStatusError(
            CODE_STATUS_NOT_RETRYABLE,
            f"Only a suppressed or failed status can be retried; this one is {found.get('outcome')}.",
        )
    return _record(send_status(db, found["row"], actor_id=actor_id))
