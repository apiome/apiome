"""Verification results and operations — PFX-5.5 (#6949).

What the **Verification** page of a provider reads and does, on top of the results Pact verifiers
publish (PFX-1.4) and the hosted verifier (PFX-3.2):

* **Status** (:func:`verification_status`): each consumer's newest pact for the provider, with its
  newest verification result, and whether it is *stale*. A pact is stale when its pact version
  has no verification result at all: it changed since the provider last verified, or was never
  verified.
* **History** (:func:`list_results`): every result of the provider, newest first, paged by an
  opaque cursor, optionally for one consumer.
* **One result** (:func:`read_result`): its per-interaction ``testResults`` (with each mismatch's
  expected and actual values) and, when Apiome ran it, the evidence run (ECA-1.3) with every
  request's assertions — the run's log.
* **Re-run** (:func:`reverify_pact`): verify one pact version again on a verification target, as
  the provider version of the result being re-run unless another is given.
* **Verify all stale** (:func:`verify_stale_pacts`): verify every stale pact in one run.
* **Scheduled runs** (:func:`run_scheduled_verification`, PFX-6.2): the verification scheduler
  (:mod:`app.pact_remediation_sweep`) verifies one pair on its cadence through the same path.

The status also carries PFX-6.2's remediation view of each pact: whether it is *overdue* (not
verified for longer than its stale threshold), its open re-publish request, its last scheduled
verification attempt, and the cadence and threshold that apply to it.

**Overlapping runs are refused per pair.** A console run of a consumer ↔ provider pair holds a
session advisory lock (:class:`app.db_advisory_lock.SessionAdvisoryLock`) on that pair while it
runs. A re-run of a pair that is already running is a :class:`PactVerifierError` with
:data:`CODE_IN_PROGRESS` (HTTP 409); in a verify-all-stale run the pair is listed as skipped, with
the reason. Pacts past :data:`app.pact_verifier.MAX_PACTS_PER_RUN` are listed as not run, never
dropped.

Every read starts from the provider of the caller's tenant
(:func:`app.pacticipant_store.get_pacticipant`); nothing reaches another tenant's results.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

from .consumer_contract_store import ConsumerActor
from .db_advisory_lock import SessionAdvisoryLock
from .pact_pending_store import load_pending_evidence
from .pact_publication import CODE_PACT_NOT_FOUND, PactPublicationError
from .pact_publication_store import list_pact_candidates
from .pact_remediation import (
    EffectiveSettings,
    RepublishRequestRecord,
    ScheduledAttempt,
    is_stale,
    reference_time,
    resolve_settings,
)
from .pact_selectors import (
    PactCandidate,
    VerifiablePact,
    is_pending,
    latest_per_consumer,
    parse_for_verification_request,
)
from .pact_verifier import MAX_PACTS_PER_RUN, PactVerificationOptions, ProviderStateHandler
from .pact_verifier_service import (
    PactVerification,
    PactVerifierError,
    PactVerifyRequest,
    PactVerifyResponse,
    open_verification_session,
)
from .pacticipant import PacticipantRecord, validate_branch, validate_url, validate_version_number
from .pacticipant_store import get_pacticipant
from .verification_evidence import EvidenceValidationError, VerificationRunRecord
from .verification_evidence_store import get_run
from .verification_result import (
    TRIGGER_MANUAL,
    TRIGGER_SCHEDULED,
    TRIGGER_STALE_RECHECK,
    VerificationResultRecord,
)
from .verification_result_store import (
    MAX_HISTORY_PAGE,
    get_provider_result,
    latest_results_by_pact,
    list_provider_results,
    record_broker_version,
)

logger = logging.getLogger(__name__)

__all__ = [
    "CODE_CURSOR_INVALID",
    "CODE_IN_PROGRESS",
    "CODE_NO_PROVIDER_VERSION",
    "CODE_OVER_LIMIT",
    "EVIDENCE_ATTACHED",
    "EVIDENCE_FORBIDDEN",
    "EVIDENCE_NOT_FOUND",
    "EVIDENCE_NOT_RECORDED",
    "MAX_STATUS_PACTS",
    "ConsoleRunRequest",
    "ConsoleRunResponse",
    "ResultDetail",
    "ResultHistoryPage",
    "ResultSummary",
    "SkippedPact",
    "StatusCounts",
    "VerificationStatus",
    "VerificationStatusEntry",
    "decode_cursor",
    "latest_pacts",
    "list_results",
    "read_result",
    "reverify_pact",
    "run_scheduled_verification",
    "summarise",
    "verification_status",
    "verify_stale_pacts",
]

#: The history cursor is not one this API handed out (HTTP 400).
CODE_CURSOR_INVALID = "pact-history-cursor-invalid"
#: A console run of this consumer ↔ provider pair is already running (HTTP 409).
CODE_IN_PROGRESS = "pact-verify-in-progress"
#: The pact is past the most one run verifies; it was not run (listed, never dropped).
CODE_OVER_LIMIT = "pact-verify-over-limit"
#: A re-run names no provider version and the pact has no result to take one from (HTTP 422).
CODE_NO_PROVIDER_VERSION = "pact-verify-provider-version-required"

#: The result's evidence run is included.
EVIDENCE_ATTACHED = "attached"
#: The result has no evidence run: a Pact verifier published it, or it predates apiome-db V444.
EVIDENCE_NOT_RECORDED = "not-recorded"
#: The result names an evidence run that is gone (pruned by evidence retention).
EVIDENCE_NOT_FOUND = "not-found"
#: The caller may read results but not verification evidence.
EVIDENCE_FORBIDDEN = "forbidden"

#: The most pacts (one per consumer) the status read returns.
MAX_STATUS_PACTS = 500

#: Builds the per-pair lock of a console run (replaced in tests).
LockFactory = Callable[[Any, str], Any]


def _pair_lock_key(tenant_id: str, provider_id: str, consumer_id: str) -> str:
    """The advisory-lock name of one consumer ↔ provider pair's console runs."""
    return f"apiome.pact_verify:{tenant_id}:{provider_id}:{consumer_id}"


# =============================================================================================
# Models
# =============================================================================================


class ResultCounts(BaseModel):
    """How a result's interactions went, from its ``testResults``."""

    model_config = ConfigDict(extra="forbid")

    total: int = Field(description="Entries in `testResults`.")
    passed: int = Field(description="Entries with `success: true`.")
    failed: int = Field(description="Every other entry (failed, skipped, unsupported).")


class ResultSummary(BaseModel):
    """One verification result, as the history and the status list show it."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="The result's id (what `…/results/{result_id}` reads).")
    number: int = Field(description="Its number among the results of its pact version.")
    consumer: str = Field(description="The consumer's handle.")
    consumer_name: str = Field(description="The consumer's display name.")
    consumer_version: Optional[str] = Field(default=None, description="The latest consumer version of the pact.")
    pact_version_sha: str = Field(description="The pact version verified.")
    provider_version: str = Field(description="The provider version (build) that verified.")
    provider_branch: Optional[str] = Field(default=None, description="Its branch, when known.")
    success: bool = Field(description="Whether every interaction passed.")
    kind: str = Field(description="`native` or `bidirectional`.")
    pending: Optional[bool] = Field(default=None, description="Whether the pact was pending when verified.")
    wip: bool = Field(default=False, description="Whether it was verified as a work-in-progress pact.")
    build_url: Optional[str] = Field(default=None, description="The CI build that ran it.")
    verified_by: Optional[str] = Field(default=None, description="The verifier and its version (`Pact-Rust 1.2.0`).")
    trigger: Optional[str] = Field(
        default=None,
        description=(
            "How it came to be: `published`, `hosted`, `manual`, `stale-recheck`, `bidirectional` or "
            "`scheduled`; null for a result recorded before triggers were recorded."
        ),
    )
    duration_ms: Optional[int] = Field(default=None, description="How long the run took, when Apiome ran it.")
    evidence_run_id: Optional[str] = Field(default=None, description="The evidence run holding its log.")
    created_at: Optional[str] = Field(default=None, description="When it was published.")
    counts: ResultCounts = Field(description="How its interactions went.")


class ResultHistoryPage(BaseModel):
    """One page of a provider's verification history."""

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(description="The provider's handle.")
    provider_name: str = Field(description="The provider's display name.")
    consumer: Optional[str] = Field(default=None, description="The consumer the page is narrowed to.")
    results: List[ResultSummary] = Field(default_factory=list, description="Newest first.")
    next_cursor: Optional[str] = Field(default=None, description="Pass as `cursor` for the next page; null at the end.")


class ResultDetail(BaseModel):
    """One verification result in full."""

    model_config = ConfigDict(extra="forbid")

    result: ResultSummary = Field(description="The result.")
    provider: str = Field(description="The provider's handle.")
    provider_name: str = Field(description="The provider's display name.")
    test_results: List[Any] = Field(
        default_factory=list,
        description=(
            "The per-interaction results as stored: `interactionDescription`, `success`, and for a "
            "failure `mismatches` (`attribute`, `identifier`, `description`, and — from the hosted "
            "verifier and most Pact verifiers — `expected` and `actual`) or `exceptions`."
        ),
    )
    comparison: Optional[Dict[str, Any]] = Field(default=None, description="A bi-directional result's comparison.")
    evidence_status: str = Field(
        description="`attached`, `not-recorded`, `not-found` (pruned) or `forbidden` (no `verification_evidence:view`)."
    )
    evidence: Optional[VerificationRunRecord] = Field(
        default=None, description="The evidence run: every request with its assertions, when `attached`."
    )


class VerificationStatusEntry(BaseModel):
    """One consumer's newest pact for the provider, and how it stands."""

    model_config = ConfigDict(extra="forbid")

    consumer: str = Field(description="The consumer's handle.")
    consumer_name: str = Field(description="The consumer's display name.")
    consumer_version: str = Field(description="The consumer version that published the pact last.")
    pact_version_sha: str = Field(description="The pact version.")
    published_at: Optional[str] = Field(default=None, description="When that version published it.")
    stale: bool = Field(description="True when the pact version has no verification result.")
    latest_result: Optional[ResultSummary] = Field(default=None, description="Its newest result.")
    overdue: bool = Field(
        default=False,
        description=(
            "True when the pact has not been verified for longer than its stale threshold (counted from "
            "its newest result, or its publication when never verified) — what opens a re-publish request."
        ),
    )
    stale_since: Optional[str] = Field(
        default=None, description="When it crossed the stale threshold, when `overdue`."
    )
    settings: Optional[EffectiveSettings] = Field(
        default=None, description="The cadence, stale threshold and target that apply to this pair."
    )
    republish_request: Optional[RepublishRequestRecord] = Field(
        default=None, description="Its open re-publish request, when there is one."
    )
    scheduled: Optional[ScheduledAttempt] = Field(
        default=None, description="Its last scheduled verification attempt, when the scheduler tried it."
    )


class StatusCounts(BaseModel):
    """The KPI strip of the Verification page."""

    model_config = ConfigDict(extra="forbid")

    pacts: int = Field(description="Consumers with a pact (one newest pact each).")
    verified: int = Field(description="Newest pacts whose newest result passed.")
    failing: int = Field(description="Newest pacts whose newest result failed.")
    stale: int = Field(description="Newest pacts with no result.")
    overdue: int = Field(default=0, description="Newest pacts not verified within their stale threshold.")
    republish_requests: int = Field(default=0, description="Open re-publish requests.")
    interactions: int = Field(description="Interactions in the newest results.")
    passing_interactions: int = Field(description="Of those, the ones that passed.")
    last_verified_at: Optional[str] = Field(default=None, description="When the newest of the results was published.")


class VerificationStatus(BaseModel):
    """Where a provider's verification stands."""

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(description="The provider's handle.")
    provider_name: str = Field(description="The provider's display name.")
    counts: StatusCounts = Field(description="The KPI strip.")
    pacts: List[VerificationStatusEntry] = Field(default_factory=list, description="One per consumer, by handle.")
    truncated: bool = Field(
        default=False,
        description=f"True when the provider has more than {MAX_STATUS_PACTS} consumers (the rest are left out).",
    )
    settings: Optional[EffectiveSettings] = Field(
        default=None, description="The cadence, stale threshold and target that apply to the provider (PFX-6.2)."
    )


class ConsoleRunRequest(BaseModel):
    """A re-run or verify-all-stale from the Verification console."""

    model_config = ConfigDict(extra="forbid")

    target_ref: str = Field(
        description="Slug or id of the registered verification target to replay against.",
        min_length=1,
        max_length=200,
    )
    provider_version: Optional[str] = Field(
        default=None,
        description=(
            "The provider version being verified. A re-run defaults to the provider version of the "
            "pact's newest result; verify-all-stale requires it."
        ),
        max_length=255,
    )
    provider_branch: Optional[str] = Field(
        default=None,
        description="Its branch. A re-run that takes the provider version from a result takes its branch too.",
        max_length=255,
    )
    build_url: Optional[str] = Field(default=None, description="http(s) URL of the CI build.", max_length=2000)
    verification: PactVerificationOptions = Field(
        default_factory=PactVerificationOptions,
        description="What the run may send: the mutating-method opt-in, fixtures and the provider-state choice.",
    )
    context: Dict[str, Any] = Field(
        default_factory=dict, description="Non-secret context stored with the evidence. Never credentials."
    )


class SkippedPact(BaseModel):
    """A pact the run chose but did not verify, with the reason."""

    model_config = ConfigDict(extra="forbid")

    consumer: str = Field(description="The consumer's handle.")
    consumer_name: str = Field(description="The consumer's display name.")
    consumer_version: str = Field(description="The consumer version of the pact.")
    pact_version_sha: str = Field(description="The pact version.")
    code: str = Field(description="`pact-verify-in-progress` or `pact-verify-over-limit`.")
    reason: str = Field(description="Why it was not verified, and what to do.")


class ConsoleRunResponse(PactVerifyResponse):
    """A console run: the hosted verifier's answer, its trigger, and what it did not run."""

    trigger: str = Field(description="`manual` (re-run), `stale-recheck` (verify all stale) or `scheduled`.")
    skipped: List[SkippedPact] = Field(default_factory=list, description="Chosen but not verified, each with why.")


# =============================================================================================
# Reads
# =============================================================================================


def _verified_by(record: VerificationResultRecord) -> Optional[str]:
    """``Pact-Rust 1.2.0`` from the result's verifier fields, or ``None``."""
    parts = [record.verified_by.get("implementation"), record.verified_by.get("version")]
    label = " ".join(part for part in parts if part)
    return label or None


def _counts(test_results: List[Any]) -> ResultCounts:
    """How the entries of ``testResults`` went; a non-object entry counts as not passed."""
    passed = sum(1 for entry in test_results if isinstance(entry, dict) and entry.get("success") is True)
    return ResultCounts(total=len(test_results), passed=passed, failed=len(test_results) - passed)


def summarise(record: VerificationResultRecord) -> ResultSummary:
    """The summary of a stored result.

    Args:
        record: The stored result.

    Returns:
        Its summary.
    """
    return ResultSummary(
        id=record.id,
        number=record.number,
        consumer=record.consumer_slug,
        consumer_name=record.consumer_name,
        consumer_version=record.consumer_version,
        pact_version_sha=record.sha,
        provider_version=record.provider_version,
        provider_branch=record.provider_branch,
        success=record.success,
        kind=record.kind,
        pending=record.pact_pending,
        wip=record.wip,
        build_url=record.build_url,
        verified_by=_verified_by(record),
        trigger=record.trigger,
        duration_ms=record.duration_ms,
        evidence_run_id=record.evidence_run_id,
        created_at=record.created_at,
        counts=_counts(record.test_results),
    )


def _iso(value: Any) -> Optional[str]:
    """A timestamp as ISO 8601 text."""
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _parse(value: Any) -> Optional[datetime]:
    """A timestamp (``datetime`` or ISO text) as an aware ``datetime``; ``None`` when unreadable."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _latest_pacts(db: Any, tenant_id: str, provider_ref: str) -> Tuple[PacticipantRecord, List[PactCandidate]]:
    """The provider and each consumer's newest publication, by consumer handle."""
    provider, candidates = list_pact_candidates(db, tenant_id, provider_ref)
    latest = latest_per_consumer(candidates, lambda _candidate: True)
    return provider, sorted(latest, key=lambda candidate: candidate.consumer_slug)


def latest_pacts(db: Any, tenant_id: str, provider_ref: str) -> Tuple[PacticipantRecord, List[PactCandidate]]:
    """The provider and each consumer's newest publication, by consumer handle.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        provider_ref: The provider's handle, id or name.

    Returns:
        The provider and one candidate per consumer.

    Raises:
        PacticipantValidationError: ``pacticipant-not-found``.
    """
    return _latest_pacts(db, tenant_id, provider_ref)


class _RemediationView:
    """What PFX-6.2 adds to the status of one provider: settings, open requests, attempts."""

    def __init__(self, db: Any, tenant_id: str, provider: PacticipantRecord) -> None:
        """Read the provider's remediation state.

        A failure is logged and leaves the view empty: the status read never fails because of it.

        Args:
            db: The database.
            tenant_id: The caller's tenant.
            provider: The provider.
        """
        from .pact_remediation_store import (
            attempts_for_provider,
            get_settings,
            open_requests_for_provider,
            override_values_for_provider,
        )

        self.available = False
        self.requests: Dict[str, RepublishRequestRecord] = {}
        self.attempts: Dict[str, ScheduledAttempt] = {}
        self.provider_settings: Optional[EffectiveSettings] = None
        try:
            self.workspace = get_settings(db, tenant_id)
            self.provider_override, self.pair_overrides = override_values_for_provider(db, tenant_id, provider.id)
            self.requests = open_requests_for_provider(db, tenant_id, provider.id)
            self.attempts = attempts_for_provider(db, tenant_id, provider.id)
            self.provider_settings = resolve_settings(self.workspace, self.provider_override)
            self.available = True
        except Exception:  # noqa: BLE001 - the status read stands without the remediation view
            logger.exception("verification status: remediation state unavailable for tenant %s", tenant_id)

    def settings_for(self, consumer_id: str) -> Optional[EffectiveSettings]:
        """The effective settings of one pair, or ``None`` when the view is unavailable."""
        if not self.available:
            return None
        return resolve_settings(self.workspace, self.provider_override, self.pair_overrides.get(str(consumer_id)))


def verification_status(db: Any, tenant_id: str, provider_ref: str) -> VerificationStatus:
    """Each consumer's newest pact for the provider, its newest result, and whether it is stale.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        provider_ref: The provider's handle, id or name.

    Returns:
        The status, with the KPI counts.

    Raises:
        PacticipantValidationError: ``pacticipant-not-found``.
    """
    provider, latest = _latest_pacts(db, tenant_id, provider_ref)
    truncated = len(latest) > MAX_STATUS_PACTS
    latest = latest[:MAX_STATUS_PACTS]
    results = latest_results_by_pact(db, tenant_id, provider, [(c.consumer_id, c.sha) for c in latest])
    view = _RemediationView(db, tenant_id, provider)
    now = datetime.now(timezone.utc)
    entries: List[VerificationStatusEntry] = []
    for candidate in latest:
        record = results.get((str(candidate.consumer_id), candidate.sha))
        settings = view.settings_for(candidate.consumer_id)
        overdue, stale_since = False, None
        if settings is not None:
            reference = reference_time(_parse(record.created_at) if record else None, _parse(candidate.published_at))
            overdue = is_stale(reference, settings.stale_threshold_hours, now)
            if overdue and reference is not None:
                stale_since = (reference + timedelta(hours=settings.stale_threshold_hours)).isoformat()
        entries.append(
            VerificationStatusEntry(
                consumer=candidate.consumer_slug,
                consumer_name=candidate.consumer_name,
                consumer_version=candidate.version_number,
                pact_version_sha=candidate.sha,
                published_at=_iso(candidate.published_at),
                stale=record is None,
                latest_result=summarise(record) if record is not None else None,
                overdue=overdue,
                stale_since=stale_since,
                settings=settings,
                republish_request=view.requests.get(str(candidate.consumer_id)),
                scheduled=view.attempts.get(str(candidate.consumer_id)),
            )
        )
    summaries = [entry.latest_result for entry in entries if entry.latest_result is not None]
    dates = sorted(summary.created_at for summary in summaries if summary.created_at)
    counts = StatusCounts(
        pacts=len(entries),
        verified=sum(1 for summary in summaries if summary.success),
        failing=sum(1 for summary in summaries if not summary.success),
        stale=sum(1 for entry in entries if entry.stale),
        overdue=sum(1 for entry in entries if entry.overdue),
        republish_requests=sum(1 for entry in entries if entry.republish_request is not None),
        interactions=sum(summary.counts.total for summary in summaries),
        passing_interactions=sum(summary.counts.passed for summary in summaries),
        last_verified_at=dates[-1] if dates else None,
    )
    return VerificationStatus(
        provider=provider.slug,
        provider_name=provider.name,
        counts=counts,
        pacts=entries,
        truncated=truncated,
        settings=view.provider_settings,
    )


def decode_cursor(cursor: Optional[str]) -> Optional[int]:
    """The history position a cursor names.

    Args:
        cursor: The ``next_cursor`` of an earlier page, or ``None`` for the first page.

    Returns:
        The position, or ``None`` for the first page.

    Raises:
        PactPublicationError: :data:`CODE_CURSOR_INVALID` for anything else.
    """
    if cursor is None or cursor == "":
        return None
    text = cursor.strip()
    if not text.isdigit() or len(text) > 19 or int(text) < 1:
        raise PactPublicationError(
            CODE_CURSOR_INVALID, f"cursor '{cursor}' is not a history cursor this API handed out"
        )
    return int(text)


def list_results(
    db: Any,
    tenant_id: str,
    provider_ref: str,
    *,
    consumer_ref: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: int = MAX_HISTORY_PAGE,
) -> ResultHistoryPage:
    """One page of the provider's verification history, newest first.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        provider_ref: The provider's handle, id or name.
        consumer_ref: Only this consumer's results, when given.
        cursor: The ``next_cursor`` of the previous page.
        limit: Page size (1 … 50).

    Returns:
        The page.

    Raises:
        PacticipantValidationError: ``pacticipant-not-found`` for the provider or the consumer.
        PactPublicationError: :data:`CODE_CURSOR_INVALID`.
    """
    before = decode_cursor(cursor)
    provider = get_pacticipant(db, tenant_id, provider_ref)
    consumer = get_pacticipant(db, tenant_id, consumer_ref) if consumer_ref else None
    records, next_seq = list_provider_results(
        db, tenant_id, provider, consumer=consumer, before_seq=before, limit=limit
    )
    return ResultHistoryPage(
        provider=provider.slug,
        provider_name=provider.name,
        consumer=consumer.slug if consumer is not None else None,
        results=[summarise(record) for record in records],
        next_cursor=str(next_seq) if next_seq is not None else None,
    )


def read_result(
    db: Any,
    tenant_id: str,
    provider_ref: str,
    result_id: str,
    *,
    include_evidence: bool,
    load_run: Callable[[str, str], VerificationRunRecord] = get_run,
) -> ResultDetail:
    """One result of the provider in full, with its evidence run when the caller may read it.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        provider_ref: The provider's handle, id or name.
        result_id: The result's id.
        include_evidence: Whether the caller holds ``verification_evidence:view``.
        load_run: Reads an evidence run (replaced in tests).

    Returns:
        The result, its test results, and the evidence run or why it is absent.

    Raises:
        PacticipantValidationError: ``pacticipant-not-found``.
        PactPublicationError: ``pact-verification-not-found``.
    """
    provider = get_pacticipant(db, tenant_id, provider_ref)
    record = get_provider_result(db, tenant_id, provider, result_id)
    evidence: Optional[VerificationRunRecord] = None
    if not record.evidence_run_id:
        status = EVIDENCE_NOT_RECORDED
    elif not include_evidence:
        status = EVIDENCE_FORBIDDEN
    else:
        try:
            evidence = load_run(tenant_id, record.evidence_run_id)
            status = EVIDENCE_ATTACHED
        except EvidenceValidationError:
            status = EVIDENCE_NOT_FOUND
    return ResultDetail(
        result=summarise(record),
        provider=provider.slug,
        provider_name=provider.name,
        test_results=list(record.test_results),
        comparison=record.comparison,
        evidence_status=status,
        evidence=evidence,
    )


# =============================================================================================
# Runs
# =============================================================================================


def _hosted_request(body: ConsoleRunRequest, version: str, branch: Optional[str]) -> PactVerifyRequest:
    """The hosted verifier's request for a console run (it always publishes)."""
    return PactVerifyRequest(
        target_ref=body.target_ref,
        provider_version=version,
        provider_branch=branch,
        build_url=body.build_url,
        verification=body.verification,
        publish=True,
        context=dict(body.context or {}),
    )


def _verifiable(
    db: Any, tenant_id: str, provider: PacticipantRecord, candidates: List[PactCandidate], branch: Optional[str]
) -> List[VerifiablePact]:
    """The candidates as pacts to verify, each with whether it is pending for this provider build."""
    query = parse_for_verification_request({"providerVersionBranch": branch} if branch else None)
    evidence = load_pending_evidence(db, tenant_id, provider.id, query.provider_version_branch)
    pacts = []
    for candidate in candidates:
        pact = VerifiablePact(candidate=candidate)
        pact.pending = is_pending(pact, query, evidence)
        pacts.append(pact)
    return pacts


def _skipped(candidate: PactCandidate, code: str, reason: str) -> SkippedPact:
    """A chosen pact the run did not verify."""
    return SkippedPact(
        consumer=candidate.consumer_slug,
        consumer_name=candidate.consumer_name,
        consumer_version=candidate.version_number,
        pact_version_sha=candidate.sha,
        code=code,
        reason=reason,
    )


def _in_progress_reason(candidate: PactCandidate, provider: PacticipantRecord) -> str:
    """The sentence for a pair whose console run is already running."""
    return (
        f"a verification of {candidate.consumer_name} ↔ {provider.name} is already running; "
        "wait for it to finish and run again"
    )


def _run(
    db: Any,
    tenant_id: str,
    provider: PacticipantRecord,
    pacts: List[VerifiablePact],
    request: PactVerifyRequest,
    *,
    trigger: str,
    description: Callable[[PactCandidate], str],
    actor: ConsumerActor,
    broker_base: str,
    refuse_busy: bool,
    skipped: List[SkippedPact],
    state_handler: Optional[ProviderStateHandler],
    lock_factory: LockFactory,
) -> ConsoleRunResponse:
    """Verify pacts one at a time, each under its pair's lock.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        provider: The provider.
        pacts: The pacts to verify.
        request: The hosted verifier's request.
        trigger: What started the run.
        description: Why each pact is verified.
        actor: Who is verifying.
        broker_base: The Pact Broker base URL.
        refuse_busy: Raise :data:`CODE_IN_PROGRESS` for a busy pair (a re-run) instead of skipping it.
        skipped: Pacts already set aside (over the limit); busy pairs are added.
        state_handler: A provider-state handler to use instead of the registered one (tests).
        lock_factory: Builds a pair's lock.

    Returns:
        The run.

    Raises:
        PactVerifierError: :data:`CODE_IN_PROGRESS` when ``refuse_busy`` and the pair is running.
        TargetValidationError: The target could not be resolved.
    """
    version = request.provider_version
    branch = request.provider_branch
    build_url = validate_url(request.build_url, what="build URL")
    session = open_verification_session(db, tenant_id, provider, request, actor=actor, state_handler=state_handler)
    verified: List[PactVerification] = []
    try:
        branch_recorded = False
        for pact in pacts:
            candidate = pact.candidate
            lock = lock_factory(db, _pair_lock_key(tenant_id, provider.id, str(candidate.consumer_id)))
            if not lock.acquire():
                if refuse_busy:
                    raise PactVerifierError(CODE_IN_PROGRESS, _in_progress_reason(candidate, provider))
                skipped.append(_skipped(candidate, CODE_IN_PROGRESS, _in_progress_reason(candidate, provider)))
                continue
            try:
                if branch and not branch_recorded:
                    # As a verifier does: the provider version's branch first, so each result carries it.
                    record_broker_version(db, tenant_id, provider.slug, version, actor=actor, branch=branch)
                    branch_recorded = True
                verified.append(
                    session.verify(
                        pact,
                        pending=pact.pending,
                        broker_base=broker_base,
                        build_url=build_url,
                        trigger=trigger,
                        description=description(candidate),
                    )
                )
            finally:
                lock.release()
    finally:
        session.close()
    answer = session.response(version, branch, verified)
    return ConsoleRunResponse(**answer.model_dump(), trigger=trigger, skipped=skipped)


def reverify_pact(
    db: Any,
    tenant_id: str,
    provider_ref: str,
    consumer_ref: str,
    sha: str,
    body: ConsoleRunRequest,
    *,
    actor: ConsumerActor,
    broker_base: str,
    state_handler: Optional[ProviderStateHandler] = None,
    lock_factory: LockFactory = SessionAdvisoryLock,
) -> ConsoleRunResponse:
    """Verify one pact version again on a verification target (``trigger: manual``).

    Without ``provider_version`` the run verifies as the provider version (and branch) of the pact
    version's newest result, so **Re-run** answers "does that build still honour this pact?".

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        provider_ref: The provider's handle, id or name.
        consumer_ref: The consumer's handle, id or name.
        sha: The pact version.
        body: The target, and optionally the provider version, branch and build.
        actor: Who is re-running it.
        broker_base: The Pact Broker base URL for result links and webhooks.
        state_handler: A provider-state handler to use instead of the registered one (tests).
        lock_factory: Builds the pair's lock (tests).

    Returns:
        The run, with the one pact.

    Raises:
        PacticipantValidationError: ``pacticipant-not-found``; a malformed version, branch or build URL.
        PactPublicationError: ``pact-not-found`` when the pair has no such pact version.
        PactVerifierError: :data:`CODE_IN_PROGRESS`, :data:`CODE_NO_PROVIDER_VERSION`, or the
            hosted verifier's own refusals.
        TargetValidationError: The target could not be resolved.
    """
    provider, candidates = list_pact_candidates(db, tenant_id, provider_ref)
    consumer = get_pacticipant(db, tenant_id, consumer_ref)
    wanted = (sha or "").strip().lower()
    matching = [c for c in candidates if str(c.consumer_id) == str(consumer.id) and c.sha == wanted]
    if not matching:
        raise PactPublicationError(
            CODE_PACT_NOT_FOUND,
            f"no pact version '{sha}' between consumer '{consumer.slug}' and provider '{provider.slug}'",
        )
    candidate = max(matching, key=lambda c: c.version_seq)

    version, branch = body.provider_version, body.provider_branch
    if not version:
        newest = latest_results_by_pact(db, tenant_id, provider, [(str(consumer.id), wanted)]).get(
            (str(consumer.id), wanted)
        )
        if newest is None:
            raise PactVerifierError(
                CODE_NO_PROVIDER_VERSION,
                f"pact version '{wanted[:12]}' has no verification result to take a provider version from; "
                "give `provider_version`",
            )
        version = newest.provider_version
        branch = branch or newest.provider_branch
    version = validate_version_number(version)
    branch = validate_branch(branch) if branch else None
    pacts = _verifiable(db, tenant_id, provider, [candidate], branch)
    return _run(
        db,
        tenant_id,
        provider,
        pacts,
        _hosted_request(body, version, branch),
        trigger=TRIGGER_MANUAL,
        description=lambda c: f"re-run of {c.consumer_name} version {c.version_number}",
        actor=actor,
        broker_base=broker_base,
        refuse_busy=True,
        skipped=[],
        state_handler=state_handler,
        lock_factory=lock_factory,
    )


def verify_stale_pacts(
    db: Any,
    tenant_id: str,
    provider_ref: str,
    body: ConsoleRunRequest,
    *,
    actor: ConsumerActor,
    broker_base: str,
    state_handler: Optional[ProviderStateHandler] = None,
    lock_factory: LockFactory = SessionAdvisoryLock,
) -> ConsoleRunResponse:
    """Verify every stale pact of the provider in one run (``trigger: stale-recheck``).

    The stale pacts are those :func:`verification_status` marks stale, by consumer handle. The
    first :data:`~app.pact_verifier.MAX_PACTS_PER_RUN` are verified; the rest are listed as
    skipped with :data:`CODE_OVER_LIMIT`, and so is a pair already being verified
    (:data:`CODE_IN_PROGRESS`). No stale pact is an answer too: ``outcome: no-pacts``.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        provider_ref: The provider's handle, id or name.
        body: The target and the provider version (required).
        actor: Who is running it.
        broker_base: The Pact Broker base URL for result links and webhooks.
        state_handler: A provider-state handler to use instead of the registered one (tests).
        lock_factory: Builds each pair's lock (tests).

    Returns:
        The run.

    Raises:
        PacticipantValidationError: ``pacticipant-not-found``; a malformed version, branch or build URL.
        PactVerifierError: :data:`CODE_NO_PROVIDER_VERSION`, or the hosted verifier's own refusals.
        TargetValidationError: The target could not be resolved.
    """
    if not body.provider_version:
        raise PactVerifierError(
            CODE_NO_PROVIDER_VERSION, "give `provider_version`: the provider build the stale pacts are verified as"
        )
    version = validate_version_number(body.provider_version)
    branch = validate_branch(body.provider_branch) if body.provider_branch else None
    provider, latest = _latest_pacts(db, tenant_id, provider_ref)
    results = latest_results_by_pact(db, tenant_id, provider, [(c.consumer_id, c.sha) for c in latest])
    stale = [c for c in latest if (str(c.consumer_id), c.sha) not in results]
    chosen, over = stale[:MAX_PACTS_PER_RUN], stale[MAX_PACTS_PER_RUN:]
    skipped = [
        _skipped(
            candidate,
            CODE_OVER_LIMIT,
            f"one run verifies at most {MAX_PACTS_PER_RUN} pacts; run Verify all stale again for the rest",
        )
        for candidate in over
    ]
    pacts = _verifiable(db, tenant_id, provider, chosen, branch)
    return _run(
        db,
        tenant_id,
        provider,
        pacts,
        _hosted_request(body, version, branch),
        trigger=TRIGGER_STALE_RECHECK,
        description=lambda c: f"stale: {c.consumer_name} version {c.version_number} has no verification result",
        actor=actor,
        broker_base=broker_base,
        refuse_busy=False,
        skipped=skipped,
        state_handler=state_handler,
        lock_factory=lock_factory,
    )


#: Who a scheduled run is recorded as.
SCHEDULER_ACTOR = ConsumerActor(user_id=None, label="pact-verification-scheduler", kind="system")


def run_scheduled_verification(
    db: Any,
    tenant_id: str,
    provider: PacticipantRecord,
    candidate: PactCandidate,
    *,
    target_ref: str,
    provider_version: str,
    provider_branch: Optional[str],
    broker_base: str,
    state_handler: Optional[ProviderStateHandler] = None,
    lock_factory: LockFactory = SessionAdvisoryLock,
) -> ConsoleRunResponse:
    """Verify one pair's newest pact on its cadence (``trigger: scheduled``, PFX-6.2).

    The same path as **Re-run**: the hosted verifier, under the pair's lock, publishing the result.
    It sends no mutating request unless the target's default options allow it (they do not): those
    interactions are held back and reported in the result. A pair already being verified is
    returned in ``skipped`` with ``pact-verify-in-progress``, not waited for.

    Args:
        db: The database.
        tenant_id: The provider's tenant.
        provider: The provider.
        candidate: The pair's newest publication.
        target_ref: The verification target from the pair's settings.
        provider_version: The provider version to verify as.
        provider_branch: Its branch, when known.
        broker_base: The Pact Broker base URL for result links and webhooks.
        state_handler: A provider-state handler to use instead of the registered one (tests).
        lock_factory: Builds the pair's lock (tests).

    Returns:
        The run.

    Raises:
        PacticipantValidationError: A malformed provider version or branch.
        PactVerifierError: The hosted verifier's refusals.
        TargetValidationError: The target could not be resolved.
    """
    version = validate_version_number(provider_version)
    branch = validate_branch(provider_branch) if provider_branch else None
    body = ConsoleRunRequest(target_ref=target_ref, provider_version=version, provider_branch=branch)
    pacts = _verifiable(db, tenant_id, provider, [candidate], branch)
    return _run(
        db,
        tenant_id,
        provider,
        pacts,
        _hosted_request(body, version, branch),
        trigger=TRIGGER_SCHEDULED,
        description=lambda c: f"scheduled: {c.consumer_name} version {c.version_number}",
        actor=SCHEDULER_ACTOR,
        broker_base=broker_base,
        refuse_busy=False,
        skipped=[],
        state_handler=state_handler,
        lock_factory=lock_factory,
    )
