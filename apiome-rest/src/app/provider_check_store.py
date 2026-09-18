"""Recording and publishing normalized provider checks — GNC-2.2 (#4738).

The database-and-provider half of the status adapter. The vocabulary is
:mod:`app.provider_checks`, the one call that reaches a provider is
:mod:`app.provider_status_adapter`, and the HTTP surface is :mod:`app.provider_check_routes`; what
lives here is the order those three happen in, and the three rules that order enforces.

**Recording comes before publishing, always.** A verdict is written to ``provider_check_runs``
first and only then offered to the provider. A check that was recorded and not published is
evidence somebody can act on; a check that was published and not recorded is a green tick with
nothing behind it. So a provider failure never rolls back a record — it appends a ``failed`` row to
the publish ledger and the verdict stands.

**Publishing is idempotent twice over.** V265 identifies a check by ``(binding, commit, name)``, so
recording the same verdict again moves one row rather than fanning out a second — that is what
makes a re-run of a check suite, a retried request and a webhook redelivery all converge. And every
attempt carries the fingerprint of the request it *would* send, unique per check, so a publish
whose bytes have already gone out collides in the ledger instead of reaching the provider twice.

**Authorization is the binding's, and the token never leaves this process.** A check exists only
for an active binding whose repository registration is intact (GNC-2.1 proved a read through a
stored credential before that binding was written). The token for the publish is resolved from that
registration in server memory through :func:`app.git_import_routes.resolve_stored_git_token` —
never accepted from a request, never stored on a check row, and never projected into a response.
That is the ticket's "browser clients never receive repository tokens", enforced at the only place
a token is ever in scope.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple

from fastapi import HTTPException

from .database import db
from .draft_binding_store import resolve_project as _resolve_binding_project
from .draft_binding_store import resolve_version as _resolve_binding_version
from .draft_bindings import DraftBindingValidationError, normalize_ref
from .provider_checks import (
    CODE_BINDING_NOT_FOUND,
    CODE_BINDING_RELEASED,
    CODE_CHECK_NOT_FOUND,
    CODE_PROJECT_NOT_FOUND,
    CODE_PROVIDER_FORBIDDEN,
    CODE_VERSION_NOT_FOUND,
    DEFAULT_CHECK_NAME,
    ORIGIN_API,
    ORIGIN_WEBHOOK,
    OUTCOME_DISPATCHED,
    OUTCOME_FAILED,
    OUTCOME_SUPPRESSED,
    STATE_PENDING,
    CheckDeliveryRecord,
    CheckRunDetail,
    CheckRunRecord,
    CheckRunUpsert,
    ProviderCheckValidationError,
    normalize_check_name,
    normalize_commit_sha,
    normalize_details_url,
)
from .provider_status_adapter import (
    PublishRequest,
    StatusPublishError,
    adapter_for,
)

_logger = logging.getLogger(__name__)

__all__ = [
    "CheckFilters",
    "DELIVERY_HISTORY_LIMIT",
    "PublishResult",
    "get_check",
    "list_checks",
    "publish_check",
    "record_check",
    "resolve_authorized_bindings",
    "seed_checks_for_ref_update",
    "version_details_url",
]

#: How many publish attempts a check detail carries. A check accumulates one per state change and
#: per retry; the detail shows a recent trail, not the whole life of the check.
DELIVERY_HISTORY_LIMIT = 50

#: Columns of a check row that belong on :class:`CheckRunRecord`.
_CHECK_FIELDS = tuple(CheckRunRecord.model_fields)

#: Columns of a delivery row that belong on :class:`CheckDeliveryRecord`.
_DELIVERY_FIELDS = tuple(CheckDeliveryRecord.model_fields)


@dataclass(frozen=True)
class CheckFilters:
    """What a check list read narrows to.

    Attributes:
        version: Only checks of this version (revision id or version label).
        commit_sha: Only checks about this commit.
        state: Only checks in this normalized state.
        limit: Page size.
        offset: Checks to skip.
    """

    version: Optional[str] = None
    commit_sha: Optional[str] = None
    state: Optional[str] = None
    limit: int = 50
    offset: int = 0


@dataclass(frozen=True)
class PublishResult:
    """What one publish attempt did, from the caller's point of view.

    Attributes:
        outcome: ``dispatched``, ``suppressed`` or ``failed``.
        error_code: The stable refusal code, for anything other than a dispatch.
        message: The redacted explanation, empty on success.
        status_code: The provider's HTTP status, when a request went out.
        ledgered: Whether this attempt produced a ledger row. ``False`` means an identical attempt
            was already recorded — the publish-once guarantee, seen from above.
    """

    outcome: str
    error_code: Optional[str] = None
    message: str = ""
    status_code: Optional[int] = None
    ledgered: bool = True


# ---------------------------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------------------------


def _resolve_project(tenant_id: str, project_ref: str) -> Dict[str, Any]:
    """Resolve a project slug or id, re-coding the binding store's refusal as a check refusal.

    Args:
        tenant_id: The caller's tenant.
        project_ref: Project slug or UUID.

    Returns:
        The project row.

    Raises:
        ProviderCheckValidationError: ``check-project-not-found`` when nothing matches.
    """
    try:
        return _resolve_binding_project(tenant_id, project_ref)
    except DraftBindingValidationError as exc:
        raise ProviderCheckValidationError(CODE_PROJECT_NOT_FOUND, str(exc)) from exc


def _resolve_version(tenant_id: str, project_id: str, version_ref: str) -> Dict[str, Any]:
    """Resolve a revision id or version label, re-coding the binding store's refusal.

    Args:
        tenant_id: The caller's tenant.
        project_id: The project the version must belong to.
        version_ref: A revision UUID or a version label.

    Returns:
        The version row.

    Raises:
        ProviderCheckValidationError: ``check-version-not-found`` when nothing matches.
    """
    try:
        return _resolve_binding_version(tenant_id, project_id, version_ref)
    except DraftBindingValidationError as exc:
        raise ProviderCheckValidationError(CODE_VERSION_NOT_FOUND, str(exc)) from exc


def _require_binding(tenant_id: str, project_id: str, version_id: str) -> Dict[str, Any]:
    """Read the version's active binding, or refuse.

    Args:
        tenant_id: The caller's tenant.
        project_id: The project.
        version_id: The version.

    Returns:
        The active binding row.

    Raises:
        ProviderCheckValidationError: ``check-binding-not-found`` when the version is not bound,
            ``check-binding-released`` when its repository registration has been removed — the
            binding still reads, but nothing can be published through it.
    """
    row = db.get_active_draft_binding(
        tenant_id=tenant_id, project_id=project_id, version_id=version_id
    )
    if not row:
        raise ProviderCheckValidationError(
            CODE_BINDING_NOT_FOUND,
            "This version is not bound to a repository ref, so there is nothing to check.",
        )
    if not row.get("repository_id"):
        raise ProviderCheckValidationError(
            CODE_BINDING_RELEASED,
            "The repository this draft is bound to is no longer registered, so no check can be "
            "published against it.",
        )
    return dict(row)


def resolve_authorized_bindings(
    db_handle: Any, *, repository_id: str, ref: str
) -> List[Dict[str, Any]]:
    """Resolve a provider event's repository and ref to the bindings it may be reported against.

    The ticket's "provider events resolve to an **authorized** branch binding". Three things make a
    binding authorized here, and all three are properties of rows rather than of the delivery: it
    is active, it belongs to the registered repository the *verified* subscription resolved to, and
    that registration still exists — which is the credential a verdict would be published with. A
    delivery cannot nominate a binding; it can only name a ref, and the rows decide.

    Args:
        db_handle: The database handle — a parameter rather than this module's ``db`` because the
            webhook path is driven against a double in its tests.
        repository_id: The registered repository the verified delivery resolved to.
        ref: The ref the delivery was about, in any spelling.

    Returns:
        One row per authorized binding, with the provider coordinates a publish is addressed by.
        Empty is the common case: no draft is bound to that ref.
    """
    short_ref = normalize_ref(ref)
    if not short_ref:
        return []
    rows = db_handle.find_authorized_bindings_for_check(
        repository_id=str(repository_id), ref=short_ref
    )
    return [dict(row) for row in rows or []]


# ---------------------------------------------------------------------------------------------
# Row mapping
# ---------------------------------------------------------------------------------------------


def _check_record(row: Mapping[str, Any]) -> CheckRunRecord:
    """Map a check row onto its record.

    Args:
        row: The database row.

    Returns:
        The record. Unknown columns are dropped rather than passed to a model that forbids extras,
        so adding a column to the query cannot break the response.
    """
    return CheckRunRecord(**{key: row[key] for key in _CHECK_FIELDS if key in row})


def _delivery_record(row: Mapping[str, Any]) -> CheckDeliveryRecord:
    """Map a publish-attempt row onto its record.

    Args:
        row: The database row.

    Returns:
        The record.
    """
    return CheckDeliveryRecord(**{key: row[key] for key in _DELIVERY_FIELDS if key in row})


def _detail(row: Mapping[str, Any]) -> CheckRunDetail:
    """Build a check detail: the verdict and the attempts to publish it.

    Args:
        row: The check row.

    Returns:
        The detail.
    """
    deliveries = db.list_provider_check_deliveries(
        check_run_id=str(row["id"]), limit=DELIVERY_HISTORY_LIMIT
    )
    return CheckRunDetail(
        check=_check_record(row),
        deliveries=[_delivery_record(delivery) for delivery in deliveries],
    )


# ---------------------------------------------------------------------------------------------
# Credentials — the only place a repository token is in scope
# ---------------------------------------------------------------------------------------------


def _repository_token(
    tenant_id: str, repository_id: str, user_id: Optional[str]
) -> Optional[str]:
    """Resolve the stored credential a check publish is authorized by.

    Reuses the import path's vault lookup rather than opening a second credential path: a check is
    publishable by exactly the account the repository was registered with. The webhook path has no
    acting user at all, which is fine — a registered repository carries its own ``created_by``, and
    the lookup falls back to it.

    Args:
        tenant_id: The tenant.
        repository_id: The registered repository the binding was authorized through.
        user_id: The acting user, when there is one.

    Returns:
        The access token, or ``None`` when no stored credential covers the repository — in which
        case the publish is suppressed rather than attempted anonymously, because no provider
        accepts an anonymous status write.
    """
    from .git_import_routes import resolve_stored_git_token

    try:
        return resolve_stored_git_token(
            tenant_id,
            str(user_id or ""),
            repository_id=repository_id,
            linked_account_id=None,
        )
    except HTTPException:
        # The registration vanished between the binding read and here.
        return None
    except Exception:  # pragma: no cover - defensive; the vault read is not expected to raise
        _logger.exception(
            "provider check credential lookup failed repository_id=%s", repository_id
        )
        return None


# ---------------------------------------------------------------------------------------------
# Publishing
# ---------------------------------------------------------------------------------------------


def _ledger(
    db_handle: Any,
    *,
    tenant_id: str,
    check_id: str,
    provider: str,
    state: str,
    fingerprint: str,
    outcome: str,
    status_code: Optional[int] = None,
    external_id: Optional[str] = None,
    error_code: Optional[str] = None,
    error_message: str = "",
    actor_id: Optional[str] = None,
) -> bool:
    """Append one publish attempt; never raises.

    Args:
        db_handle: The database handle.
        tenant_id: The tenant.
        check_id: The check the attempt belongs to.
        provider: The provider addressed.
        state: The state published.
        fingerprint: Fingerprint of the request; the idempotency key.
        outcome: ``dispatched``, ``suppressed`` or ``failed``.
        status_code: The provider's HTTP status, when a request went out.
        external_id: The provider's id for the check, when it returned one.
        error_code: Stable reason for a refusal.
        error_message: The provider's message, already redacted.
        actor_id: The acting user, when a person triggered the publish.

    Returns:
        Whether a row was written. ``False`` means an identical attempt is already on the ledger,
        or the ledger write itself failed — which is logged, because evidence that did not land is
        worth knowing about even though it must not fail the verdict.
    """
    try:
        return bool(
            db_handle.record_provider_check_delivery(
                tenant_id=tenant_id,
                check_run_id=check_id,
                provider=provider,
                state=state,
                request_fingerprint=fingerprint,
                outcome=outcome,
                status_code=status_code,
                external_id=external_id,
                error_code=error_code,
                error_message=error_message,
                actor_id=actor_id,
            )
        )
    except Exception:
        _logger.exception(
            "provider check delivery ledger write failed check_id=%s outcome=%s",
            check_id,
            outcome,
        )
        return False


def _already_published(
    db_handle: Any, *, check_id: str, fingerprint: str
) -> Optional[Mapping[str, Any]]:
    """Find a *dispatched* attempt at this exact verdict, if there is one.

    Only a dispatch stops a later attempt. A ``failed`` row is precisely the case where trying
    again is the right thing to do, and a ``suppressed`` one records a decision not to send — both
    must stay retryable, or a provider having one bad minute would freeze that verdict forever.

    Args:
        db_handle: The database handle.
        check_id: The check run.
        fingerprint: Fingerprint of the verdict about to be published.

    Returns:
        The prior dispatched attempt, or ``None``.
    """
    try:
        row = db_handle.find_provider_check_delivery(
            check_run_id=check_id, request_fingerprint=fingerprint
        )
    except Exception:
        # A ledger read that fails must not stop a verdict reaching the provider; at worst the
        # insert below collides and the attempt is reported as un-ledgered.
        _logger.exception("provider check delivery lookup failed check_id=%s", check_id)
        return None
    if row and str(row.get("outcome") or "") == OUTCOME_DISPATCHED:
        return dict(row)
    return None


def publish_check(
    db_handle: Any,
    check: Mapping[str, Any],
    *,
    repository_id: str,
    actor_id: Optional[str] = None,
    client_factory: Optional[Any] = None,
) -> PublishResult:
    """Put a recorded verdict on the provider, and ledger what happened.

    Never raises: every outcome — including "the provider refused" and "checks are switched off" —
    is a row on the publish ledger and a :class:`PublishResult`. A recorded verdict must not be
    undone by a provider having a bad day, and a webhook delivery must not become a 500 the
    provider will retry forever.

    Args:
        db_handle: The database handle.
        check: The recorded check row.
        repository_id: The registration whose stored credential authorizes the publish.
        actor_id: The acting user, when a person triggered it.
        client_factory: How the adapter obtains an HTTP client; injected in tests.

    Returns:
        What the attempt did.
    """
    from .config import settings

    tenant_id = str(check["tenant_id"])
    check_id = str(check["id"])
    provider = str(check["provider"])
    state = str(check["state"])

    request = PublishRequest(
        repo_full_name=str(check["repo_full_name"]),
        commit_sha=str(check["commit_sha"]),
        name=str(check["name"]),
        state=state,
        title=str(check.get("title") or ""),
        summary=str(check.get("summary") or ""),
        details_url=str(check.get("details_url") or ""),
        external_id=(str(check["external_id"]) if check.get("external_id") else None),
    )

    def suppressed(code: str, message: str, fingerprint: str) -> PublishResult:
        """Ledger a deliberate non-publish and describe it."""
        ledgered = _ledger(
            db_handle,
            tenant_id=tenant_id,
            check_id=check_id,
            provider=provider,
            state=state,
            fingerprint=fingerprint,
            outcome=OUTCOME_SUPPRESSED,
            error_code=code,
            error_message=message,
            actor_id=actor_id,
        )
        return PublishResult(
            outcome=OUTCOME_SUPPRESSED, error_code=code, message=message, ledgered=ledgered
        )

    try:
        adapter = adapter_for(provider, None, client_factory=client_factory)
    except StatusPublishError as exc:
        # No adapter covers this provider. The fingerprint cannot come from a call that cannot be
        # built, so it is derived from the check's identity instead — one suppressed row per
        # verdict, not one per attempt to publish a verdict that never can be.
        from .provider_checks import request_fingerprint

        fingerprint = request_fingerprint(
            {"unsupported": provider, "check": check_id, "state": state}
        )
        return suppressed(exc.code, exc.message, fingerprint)

    fingerprint = adapter.fingerprint(request)

    if not settings.provider_checks_enabled:
        return suppressed(
            "check-publishing-disabled",
            "Check publishing is switched off for this deployment; the verdict was recorded only.",
            fingerprint,
        )

    token = _repository_token(tenant_id, repository_id, actor_id)
    if not token:
        return suppressed(
            CODE_PROVIDER_FORBIDDEN,
            "No stored credential authorizes writing a check on this repository; the verdict was "
            "recorded only.",
            fingerprint,
        )

    already = _already_published(db_handle, check_id=check_id, fingerprint=fingerprint)
    if already:
        # This exact verdict has already gone out. Returning here is what makes a webhook
        # redelivery — or a retried request, or a check suite that reports the same result twice —
        # free at the provider and not merely deduplicated in our own ledger.
        return PublishResult(
            outcome=str(already.get("outcome") or OUTCOME_DISPATCHED),
            error_code=(str(already["error_code"]) if already.get("error_code") else None),
            message=str(already.get("error_message") or ""),
            status_code=already.get("status_code"),
            ledgered=False,
        )

    adapter = adapter_for(provider, token, client_factory=client_factory)
    try:
        published = adapter.publish(request)
    except StatusPublishError as exc:
        ledgered = _ledger(
            db_handle,
            tenant_id=tenant_id,
            check_id=check_id,
            provider=provider,
            state=state,
            fingerprint=fingerprint,
            outcome=OUTCOME_FAILED,
            status_code=exc.http_status,
            error_code=exc.code,
            error_message=exc.message,
            actor_id=actor_id,
        )
        return PublishResult(
            outcome=OUTCOME_FAILED,
            error_code=exc.code,
            message=exc.message,
            status_code=exc.http_status,
            ledgered=ledgered,
        )

    ledgered = _ledger(
        db_handle,
        tenant_id=tenant_id,
        check_id=check_id,
        provider=provider,
        state=state,
        fingerprint=published.fingerprint,
        outcome=OUTCOME_DISPATCHED,
        status_code=published.status_code,
        external_id=published.external_id,
        actor_id=actor_id,
    )
    return PublishResult(
        outcome=OUTCOME_DISPATCHED, status_code=published.status_code, ledgered=ledgered
    )


# ---------------------------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------------------------


def list_checks(
    tenant_id: str, project_ref: str, filters: CheckFilters
) -> Tuple[List[CheckRunRecord], Optional[str]]:
    """List a project's check runs, newest first.

    Args:
        tenant_id: The caller's tenant.
        project_ref: Project slug or id.
        filters: What to narrow to.

    Returns:
        ``(checks, version_id)`` — the page, and the version the filter resolved to when one was
        named, so a caller can echo what it actually filtered on.

    Raises:
        ProviderCheckValidationError: For an unknown project or version.
    """
    project = _resolve_project(tenant_id, project_ref)
    version_id: Optional[str] = None
    if filters.version:
        version_id = str(
            _resolve_version(tenant_id, str(project["id"]), filters.version)["id"]
        )
    rows = db.list_provider_check_runs(
        tenant_id=tenant_id,
        project_id=str(project["id"]),
        version_id=version_id,
        commit_sha=filters.commit_sha,
        state=filters.state,
        limit=filters.limit,
        offset=filters.offset,
    )
    return [_check_record(row) for row in rows], version_id


def get_check(tenant_id: str, project_ref: str, check_id: str) -> CheckRunDetail:
    """Read one check run with its publish attempts.

    Args:
        tenant_id: The caller's tenant.
        project_ref: Project slug or id.
        check_id: The check run.

    Returns:
        The detail.

    Raises:
        ProviderCheckValidationError: ``check-not-found`` when it is not this project's.
    """
    project = _resolve_project(tenant_id, project_ref)
    row = db.get_provider_check_run(tenant_id=tenant_id, check_id=check_id)
    if not row or str(row.get("project_id")) != str(project["id"]):
        raise ProviderCheckValidationError(CODE_CHECK_NOT_FOUND, "No such check run.")
    return _detail(row)


# ---------------------------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------------------------


def record_check(
    tenant_id: str,
    user_id: str,
    project_ref: str,
    version_ref: str,
    request: CheckRunUpsert,
    *,
    client_factory: Optional[Any] = None,
) -> CheckRunDetail:
    """Record a verdict against a version's active binding, and publish it unless told not to.

    Args:
        tenant_id: The caller's tenant.
        user_id: The acting user.
        project_ref: Project slug or id.
        version_ref: Revision id or version label.
        request: The verdict.
        client_factory: How the adapter obtains an HTTP client; injected in tests.

    Returns:
        The check detail, including the attempt this call made.

    Raises:
        ProviderCheckValidationError: For an unknown project or version, a version with no usable
            binding, or an invalid check name.
    """
    project = _resolve_project(tenant_id, project_ref)
    version = _resolve_version(tenant_id, str(project["id"]), version_ref)
    binding = _require_binding(tenant_id, str(project["id"]), str(version["id"]))

    name = normalize_check_name(request.name)
    details_url = normalize_details_url(request.details_url)
    # An explicit commit is validated; the binding's own is already a commit this platform read.
    commit_sha = (
        normalize_commit_sha(request.commit_sha)
        if (request.commit_sha or "").strip()
        else str(binding["commit_sha"])
    )

    produced = db.upsert_provider_check_run(
        tenant_id=tenant_id,
        binding_id=str(binding["id"]),
        commit_sha=commit_sha,
        name=name,
        state=request.state,
        title=request.title,
        summary=request.summary,
        details_url=details_url,
        pr_number=request.pr_number,
        origin=ORIGIN_API,
        created_by=user_id,
        rerun=request.rerun,
    )
    if not produced:
        # The binding was released, or its registration removed, between the read above and the
        # write — the same race _require_binding refuses, seen from inside the transaction.
        raise ProviderCheckValidationError(
            CODE_BINDING_RELEASED,
            "The binding was released before the check could be recorded.",
        )

    row = db.get_provider_check_run(tenant_id=tenant_id, check_id=str(produced["check_id"]))
    if not row:  # pragma: no cover - the row was just written in a committed transaction
        raise ProviderCheckValidationError(CODE_CHECK_NOT_FOUND, "No such check run.")

    if request.publish:
        publish_check(
            db,
            row,
            repository_id=str(binding["repository_id"]),
            actor_id=user_id,
            client_factory=client_factory,
        )
        # Re-read: a dispatch writes the provider's id back onto the check, and that id is what
        # makes the *next* publish move this check rather than stack a second one beside it.
        row = (
            db.get_provider_check_run(tenant_id=tenant_id, check_id=str(produced["check_id"]))
            or row
        )

    return _detail(row)


def seed_checks_for_ref_update(
    db_handle: Any,
    *,
    repository_id: str,
    ref: str,
    commit_sha: str,
    delivery_id: Optional[str] = None,
    pr_number: Optional[int] = None,
    client_factory: Optional[Any] = None,
) -> int:
    """Announce a pending check on every draft bound to a ref a delivery moved.

    Called from the provider webhook path once a delivery has verified. The check says only what is
    true at that moment — *this platform has seen the commit and is looking at it* — which is
    precisely what a ``pending`` state is for: a reviewer sees the check appear on the pull request
    immediately, and GNC-3.1's suite moves it to a verdict when it has one.

    Deliberately best-effort at every step. A ref that nothing is bound to seeds nothing, a binding
    whose registration is gone seeds nothing, and a provider that refuses the publish leaves a
    ``failed`` row on the ledger and a recorded pending check. None of those is an error a provider
    should be asked to retry.

    Args:
        db_handle: The database handle.
        repository_id: The registered repository the verified delivery resolved to.
        ref: The ref the delivery reported as moved.
        commit_sha: The commit it moved to.
        delivery_id: The provider delivery id, which the seeded check records.
        pr_number: The pull request the commit belongs to, when the delivery named one.
        client_factory: How the adapter obtains an HTTP client; injected in tests.

    Returns:
        How many checks were seeded.
    """
    from .config import settings

    head = (commit_sha or "").strip()
    if not head or not settings.provider_checks_webhook_seed_enabled:
        return 0

    bindings = resolve_authorized_bindings(db_handle, repository_id=repository_id, ref=ref)
    seeded = 0
    for binding in bindings:
        produced = db_handle.upsert_provider_check_run(
            tenant_id=str(binding["tenant_id"]),
            binding_id=str(binding["id"]),
            commit_sha=head,
            name=DEFAULT_CHECK_NAME,
            state=STATE_PENDING,
            title="Apiome is reviewing this change",
            summary=(
                "Apiome has a draft bound to this branch and is looking at the change. "
                "The verdict replaces this status when the check suite has one."
            ),
            details_url=_details_url(binding),
            pr_number=pr_number,
            origin=ORIGIN_WEBHOOK,
            delivery_id=delivery_id,
        )
        if not produced:
            continue
        seeded += 1
        row = db_handle.get_provider_check_run(
            tenant_id=str(binding["tenant_id"]), check_id=str(produced["check_id"])
        )
        if row:
            publish_check(
                db_handle,
                row,
                repository_id=str(binding["repository_id"]),
                client_factory=client_factory,
            )
    return seeded


def version_details_url(project_id: str, version_id: str) -> str:
    """Build the link a check about a version points a reviewer at.

    Shared with the GNC-3.1 check suite, so a seeded check and the verdict that replaces it point
    at the same page.

    Args:
        project_id: The project.
        version_id: The version.

    Returns:
        The version's page in the app, or ``""`` when no base URL is configured — an empty link is
        better than a broken one, and every adapter treats it as "no link".
    """
    from .config import settings

    base = (settings.provider_checks_details_base_url or "").strip().rstrip("/")
    if not base:
        return ""
    return f"{base}/ade/projects/{project_id}/versions/{version_id}"


def _details_url(binding: Mapping[str, Any]) -> str:
    """Build the link a seeded check points a reviewer at.

    Args:
        binding: The authorized binding row.

    Returns:
        The version's page in the app, or ``""`` when no base URL is configured.
    """
    return version_details_url(str(binding["project_id"]), str(binding["version_id"]))
