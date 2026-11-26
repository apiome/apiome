"""Stale-pact remediation and verification scheduling — PFX-6.2 (#6954): the pure half.

A pact is **stale** when the provider has not verified it for longer than the **stale threshold**:
counted from its newest verification result, or from when it was published if it was never
verified. (The Verification console's older ``stale`` flag, PFX-5.5, means "this pact version has no
result at all" and is unchanged; this module calls the threshold-based state *overdue* on that
page.)

Three things are configurable per workspace (:class:`VerificationSettingsInput`), and the first two
per provider or per consumer ↔ provider pair (:class:`OverrideInput`):

* the **cadence** — when Apiome's hosted verifier runs a pair on its own: ``on-publish`` (a newly
  published pact version, on the next sweep), ``hourly`` / ``nightly`` (every 1 h / 24 h, and a newly
  published pact version on the next sweep too), or ``manual-only`` (never; the default). A
  scheduled run needs a verification target, which only an override can name;
* the **stale threshold**, in hours;
* the **verification target** scheduled runs replay against (override only).

Workspace-only: how many scheduled verifications may run at once, how long a re-publish request
stays open, and whether stale pacts open requests at all.

The **remediation loop**: a stale pact opens a **re-publish request** to its consumer
(``requested``); the consumer may **acknowledge** it; it is **republished** when the consumer
publishes the pact again, **cleared** when the provider verifies it meanwhile, and **expired** —
and escalated — when its window passes first. One request per pact version since its last
verification: an expired request is not reopened for the same pact until it is verified again.

This module decides; it reads no database and sends nothing (:mod:`app.pact_remediation_store`,
:mod:`app.pact_remediation_sweep`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "ATTEMPT_ERRORED",
    "ATTEMPT_FAILED",
    "ATTEMPT_SKIPPED",
    "ATTEMPT_STATUSES",
    "ATTEMPT_VERIFIED",
    "CADENCES",
    "CADENCE_HOURLY",
    "CADENCE_INTERVAL_SECONDS",
    "CADENCE_MANUAL",
    "CADENCE_NIGHTLY",
    "CADENCE_ON_PUBLISH",
    "CODE_NO_PROVIDER_VERSION",
    "CODE_NO_TARGET",
    "CODE_OVERRIDE_INVALID",
    "CODE_OVERRIDE_NOT_FOUND",
    "CODE_REQUEST_CLOSED",
    "CODE_REQUEST_CURSOR_INVALID",
    "CODE_REQUEST_NOT_FOUND",
    "DEFAULT_CADENCE",
    "DEFAULT_MAX_CONCURRENT_RUNS",
    "DEFAULT_REQUEST_WINDOW_HOURS",
    "DEFAULT_STALE_THRESHOLD_HOURS",
    "MAX_CONCURRENT_RUNS",
    "MAX_OVERRIDES",
    "MAX_REQUEST_PAGE",
    "MAX_REQUEST_WINDOW_HOURS",
    "MAX_STALE_THRESHOLD_HOURS",
    "OPEN_STATES",
    "REQUEST_STATES",
    "SOURCE_PAIR",
    "SOURCE_PROVIDER",
    "SOURCE_WORKSPACE",
    "STATE_ACKNOWLEDGED",
    "STATE_CLEARED",
    "STATE_EXPIRED",
    "STATE_REPUBLISHED",
    "STATE_REQUESTED",
    "AcknowledgeRequest",
    "EffectiveSettings",
    "OverrideInput",
    "OverrideList",
    "OverrideRecord",
    "PairFacts",
    "RemediationError",
    "RepublishRequestPage",
    "RepublishRequestRecord",
    "RequestFacts",
    "ScheduleDecision",
    "ScheduledAttempt",
    "VerificationSettings",
    "VerificationSettingsInput",
    "decide_request",
    "decide_schedule",
    "is_stale",
    "reference_time",
    "resolve_settings",
    "should_open_request",
]

# ---------------------------------------------------------------------------------------------
# Vocabulary (mirrors apiome-db V448's CHECK constraints)
# ---------------------------------------------------------------------------------------------

#: Verify a newly published pact version on the next sweep.
CADENCE_ON_PUBLISH = "on-publish"
#: Re-verify every hour (and a newly published pact version on the next sweep).
CADENCE_HOURLY = "hourly"
#: Re-verify every 24 hours (and a newly published pact version on the next sweep).
CADENCE_NIGHTLY = "nightly"
#: Never verify on a schedule: only CI, **Re-run** and **Verify all stale** verify.
CADENCE_MANUAL = "manual-only"
#: Every cadence, in the order the settings screen lists them.
CADENCES = (CADENCE_ON_PUBLISH, CADENCE_HOURLY, CADENCE_NIGHTLY, CADENCE_MANUAL)
#: The re-verification interval of the periodic cadences.
CADENCE_INTERVAL_SECONDS = {CADENCE_HOURLY: 3600, CADENCE_NIGHTLY: 86400}

STATE_REQUESTED = "requested"
STATE_ACKNOWLEDGED = "acknowledged"
STATE_REPUBLISHED = "republished"
STATE_CLEARED = "cleared"
STATE_EXPIRED = "expired"
#: Every request state, in lifecycle order.
REQUEST_STATES = (STATE_REQUESTED, STATE_ACKNOWLEDGED, STATE_REPUBLISHED, STATE_CLEARED, STATE_EXPIRED)
#: The states of a request still waiting on the consumer.
OPEN_STATES = (STATE_REQUESTED, STATE_ACKNOWLEDGED)

ATTEMPT_VERIFIED = "verified"
ATTEMPT_FAILED = "failed"
ATTEMPT_SKIPPED = "skipped"
ATTEMPT_ERRORED = "errored"
#: What a scheduled verification attempt came to.
ATTEMPT_STATUSES = (ATTEMPT_VERIFIED, ATTEMPT_FAILED, ATTEMPT_SKIPPED, ATTEMPT_ERRORED)

#: Where an effective value came from.
SOURCE_WORKSPACE = "workspace"
SOURCE_PROVIDER = "provider"
SOURCE_PAIR = "pair"

DEFAULT_CADENCE = CADENCE_MANUAL
DEFAULT_STALE_THRESHOLD_HOURS = 72
DEFAULT_MAX_CONCURRENT_RUNS = 2
DEFAULT_REQUEST_WINDOW_HOURS = 72
#: 90 days.
MAX_STALE_THRESHOLD_HOURS = 2160
MAX_CONCURRENT_RUNS = 10
#: 30 days.
MAX_REQUEST_WINDOW_HOURS = 720
#: The most overrides one workspace may have (the list is read whole).
MAX_OVERRIDES = 500
#: The largest page of re-publish requests.
MAX_REQUEST_PAGE = 50

#: An override names a pair whose consumer is its provider, or says nothing (HTTP 422).
CODE_OVERRIDE_INVALID = "pact-verification-override-invalid"
#: No such override in this workspace (HTTP 404).
CODE_OVERRIDE_NOT_FOUND = "pact-verification-override-not-found"
#: No such re-publish request in this workspace (HTTP 404).
CODE_REQUEST_NOT_FOUND = "pact-republish-request-not-found"
#: The request is no longer open, so it cannot be acknowledged (HTTP 409).
CODE_REQUEST_CLOSED = "pact-republish-request-closed"
#: The list cursor is not one this API handed out (HTTP 400).
CODE_REQUEST_CURSOR_INVALID = "pact-republish-request-cursor-invalid"
#: A scheduled run was due but no verification target is set for the pair.
CODE_NO_TARGET = "pact-schedule-no-target"
#: A scheduled run was due but no provider version is known to verify as.
CODE_NO_PROVIDER_VERSION = "pact-schedule-no-provider-version"


class RemediationError(ValueError):
    """A settings, override or request call was refused, with a stable code.

    Attributes:
        code: One of the ``CODE_*`` values of this module.
    """

    def __init__(self, code: str, message: str) -> None:
        """Build the refusal.

        Args:
            code: The stable code.
            message: What was wrong, and what to do.
        """
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------------------------

_CADENCE_PATTERN = "^(on-publish|hourly|nightly|manual-only)$"


class VerificationSettingsInput(BaseModel):
    """The workspace's verification settings, as ``PUT`` replaces them."""

    model_config = ConfigDict(extra="forbid")

    cadence: str = Field(
        description="`on-publish`, `hourly`, `nightly` or `manual-only`: when the hosted verifier runs a pair.",
        pattern=_CADENCE_PATTERN,
    )
    stale_threshold_hours: int = Field(
        description="A pact not verified for longer than this is stale (1 … 2160).",
        ge=1,
        le=MAX_STALE_THRESHOLD_HOURS,
    )
    max_concurrent_runs: int = Field(
        description="How many scheduled verifications may run at once in the workspace (1 … 10).",
        ge=1,
        le=MAX_CONCURRENT_RUNS,
    )
    request_window_hours: int = Field(
        description="How long a re-publish request stays open before it expires and escalates (1 … 720).",
        ge=1,
        le=MAX_REQUEST_WINDOW_HOURS,
    )
    republish_requests_enabled: bool = Field(description="Whether a stale pact opens a re-publish request.")


class VerificationSettings(VerificationSettingsInput):
    """The workspace's verification settings, as read."""

    customised: bool = Field(description="False while the workspace uses the defaults (never saved).")
    updated_at: Optional[str] = Field(default=None, description="When they were last saved.")


#: The settings of a workspace that never saved any.
def default_settings() -> VerificationSettings:
    """The defaults: manual-only, stale after 72 h, 2 concurrent runs, 72 h request window, requests on.

    Returns:
        The default settings (``customised: false``).
    """
    return VerificationSettings(
        cadence=DEFAULT_CADENCE,
        stale_threshold_hours=DEFAULT_STALE_THRESHOLD_HOURS,
        max_concurrent_runs=DEFAULT_MAX_CONCURRENT_RUNS,
        request_window_hours=DEFAULT_REQUEST_WINDOW_HOURS,
        republish_requests_enabled=True,
        customised=False,
    )


class OverrideInput(BaseModel):
    """A provider-wide or per-pair override, as ``PUT …/overrides`` creates or replaces it."""

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(description="The provider's handle, id or name.", min_length=1, max_length=255)
    consumer: Optional[str] = Field(
        default=None,
        description="The consumer's handle, id or name; omit for every consumer of the provider.",
        min_length=1,
        max_length=255,
    )
    cadence: Optional[str] = Field(default=None, description="The cadence; null inherits.", pattern=_CADENCE_PATTERN)
    stale_threshold_hours: Optional[int] = Field(
        default=None, description="The stale threshold (1 … 2160); null inherits.", ge=1, le=MAX_STALE_THRESHOLD_HOURS
    )
    target_ref: Optional[str] = Field(
        default=None,
        description="Slug or id of the verification target scheduled runs replay against; null inherits.",
        min_length=1,
        max_length=200,
    )


class OverrideRecord(BaseModel):
    """A stored override."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="The override's id (what `DELETE …/overrides/{id}` removes).")
    provider: str = Field(description="The provider's handle.")
    provider_name: str = Field(description="The provider's display name.")
    consumer: Optional[str] = Field(default=None, description="The consumer's handle; null for every consumer.")
    consumer_name: Optional[str] = Field(default=None, description="The consumer's display name.")
    cadence: Optional[str] = Field(default=None, description="The cadence; null inherits.")
    stale_threshold_hours: Optional[int] = Field(default=None, description="The threshold; null inherits.")
    target: Optional[str] = Field(default=None, description="The verification target's handle; null inherits.")
    target_name: Optional[str] = Field(default=None, description="Its display name.")
    target_deleted: bool = Field(
        default=False, description="True when the target was deleted: scheduled runs of this override cannot run."
    )
    updated_at: Optional[str] = Field(default=None, description="When it was last saved.")


class OverrideList(BaseModel):
    """Every override of the workspace, by provider then consumer."""

    model_config = ConfigDict(extra="forbid")

    overrides: List[OverrideRecord] = Field(default_factory=list)


class EffectiveSettings(BaseModel):
    """What applies to one pair (or provider), and where each value came from."""

    model_config = ConfigDict(extra="forbid")

    cadence: str = Field(description="The cadence that applies.")
    cadence_source: str = Field(description="`workspace`, `provider` or `pair`.")
    stale_threshold_hours: int = Field(description="The stale threshold that applies.")
    stale_threshold_source: str = Field(description="`workspace`, `provider` or `pair`.")
    target: Optional[str] = Field(default=None, description="The verification target scheduled runs use, if any.")
    target_source: Optional[str] = Field(default=None, description="`provider` or `pair` when a target is set.")


class ScheduledAttempt(BaseModel):
    """A pair's last scheduled verification attempt."""

    model_config = ConfigDict(extra="forbid")

    pact_version_sha: str = Field(description="The pact version it was for.")
    attempted_at: Optional[str] = Field(default=None, description="When.")
    status: str = Field(description="`verified`, `failed`, `skipped` or `errored`.")
    code: Optional[str] = Field(default=None, description="Why it did not verify, as a stable code.")
    reason: Optional[str] = Field(default=None, description="Why it did not verify, and what to do.")


class RepublishRequestRecord(BaseModel):
    """A request to a consumer to re-publish a stale pact."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="The request's id.")
    provider: str = Field(description="The provider's handle.")
    provider_name: str = Field(description="The provider's display name.")
    consumer: str = Field(description="The consumer's handle.")
    consumer_name: str = Field(description="The consumer's display name.")
    pact_version_sha: str = Field(description="The stale pact version.")
    consumer_version: str = Field(description="The consumer version that published it last.")
    state: str = Field(description="`requested`, `acknowledged`, `republished`, `cleared` or `expired`.")
    threshold_hours: int = Field(description="The stale threshold it crossed.")
    reference_at: Optional[str] = Field(
        default=None, description="When the pact was last verified (or published, when never verified)."
    )
    requested_at: Optional[str] = Field(default=None, description="When the request was opened.")
    expires_at: Optional[str] = Field(default=None, description="When it expires and escalates, unless answered.")
    acknowledged_at: Optional[str] = Field(default=None, description="When the consumer acknowledged it.")
    acknowledged_by: Optional[str] = Field(default=None, description="Who acknowledged it.")
    note: Optional[str] = Field(default=None, description="The acknowledgement's note.")
    resolved_at: Optional[str] = Field(default=None, description="When it was republished, cleared or expired.")
    resolved_consumer_version: Optional[str] = Field(
        default=None, description="The consumer version that re-published, for `republished`."
    )
    notification_status: Optional[str] = Field(
        default=None,
        description=(
            "What notifying the consumer's owners did: `routed`, `throttled`, `unowned`, `catch_all`, "
            "`unlinked` (the consumer is linked to no consumer or project with owners) or `failed`."
        ),
    )
    escalation_status: Optional[str] = Field(default=None, description="The same, for the escalation on expiry.")
    webhook_deliveries: int = Field(default=0, description="Contract webhook deliveries queued for it.")


class RepublishRequestPage(BaseModel):
    """One page of re-publish requests, newest first."""

    model_config = ConfigDict(extra="forbid")

    requests: List[RepublishRequestRecord] = Field(default_factory=list)
    next_cursor: Optional[str] = Field(default=None, description="Pass as `cursor` for the next page.")


class AcknowledgeRequest(BaseModel):
    """The consumer acknowledges a re-publish request."""

    model_config = ConfigDict(extra="forbid")

    note: Optional[str] = Field(default=None, description="What the consumer will do, and when.", max_length=1000)


# ---------------------------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class OverrideValues:
    """The values one override sets (``None`` inherits)."""

    cadence: Optional[str] = None
    stale_threshold_hours: Optional[int] = None
    target: Optional[str] = None


def resolve_settings(
    workspace: VerificationSettingsInput,
    provider: Optional[OverrideValues] = None,
    pair: Optional[OverrideValues] = None,
) -> EffectiveSettings:
    """What applies to a pair: the pair's override, else the provider's, else the workspace's.

    Args:
        workspace: The workspace settings.
        provider: The provider-wide override, if any.
        pair: The pair's override, if any.

    Returns:
        The effective cadence, threshold and target, each with its source.
    """
    cadence, cadence_source = workspace.cadence, SOURCE_WORKSPACE
    threshold, threshold_source = workspace.stale_threshold_hours, SOURCE_WORKSPACE
    target: Optional[str] = None
    target_source: Optional[str] = None
    for values, source in ((provider, SOURCE_PROVIDER), (pair, SOURCE_PAIR)):
        if values is None:
            continue
        if values.cadence:
            cadence, cadence_source = values.cadence, source
        if values.stale_threshold_hours:
            threshold, threshold_source = values.stale_threshold_hours, source
        if values.target:
            target, target_source = values.target, source
    return EffectiveSettings(
        cadence=cadence,
        cadence_source=cadence_source,
        stale_threshold_hours=threshold,
        stale_threshold_source=threshold_source,
        target=target,
        target_source=target_source,
    )


def _aware(value: datetime) -> datetime:
    """A timestamp as timezone-aware (UTC when it has no zone)."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def reference_time(last_verified_at: Optional[datetime], published_at: Optional[datetime]) -> Optional[datetime]:
    """What the stale threshold counts from: the newest result, else the publication.

    Args:
        last_verified_at: When the pact version's newest result was published.
        published_at: When the pact was published by the consumer version that published it last.

    Returns:
        The reference time, or ``None`` when neither is known (never stale).
    """
    if last_verified_at is not None:
        return _aware(last_verified_at)
    return _aware(published_at) if published_at is not None else None


def is_stale(reference_at: Optional[datetime], threshold_hours: int, now: datetime) -> bool:
    """Whether a pact last verified (or published) at ``reference_at`` is past the threshold.

    Args:
        reference_at: From :func:`reference_time`.
        threshold_hours: The stale threshold.
        now: The current time.

    Returns:
        True when more than ``threshold_hours`` have passed.
    """
    if reference_at is None:
        return False
    return _aware(now) - _aware(reference_at) > timedelta(hours=threshold_hours)


@dataclass(frozen=True)
class PairFacts:
    """What the sweep knows about a pair's newest pact.

    Attributes:
        sha: The newest pact version.
        consumer_version: The consumer version that published it last.
        published_at: When that consumer version published it.
        last_verified_at: When its newest verification result was published; ``None`` if never.
    """

    sha: str
    consumer_version: str
    published_at: Optional[datetime]
    last_verified_at: Optional[datetime]


@dataclass(frozen=True)
class RequestFacts:
    """An open re-publish request, as the sweep decides on it.

    Attributes:
        sha: The pact version it is about.
        requested_at: When it was opened.
        expires_at: When it expires.
    """

    sha: str
    requested_at: datetime
    expires_at: datetime


def decide_request(open_request: RequestFacts, pair: PairFacts, stale: bool, now: datetime) -> Optional[str]:
    """Where an open request goes next, if anywhere.

    In order: the consumer published the pact again after the request (``republished``); the pact
    is no longer stale — verified meanwhile (``cleared``); the window passed (``expired``).

    Args:
        open_request: The open request.
        pair: The pair's newest pact now.
        stale: Whether that pact is stale now.
        now: The current time.

    Returns:
        :data:`STATE_REPUBLISHED`, :data:`STATE_CLEARED`, :data:`STATE_EXPIRED`, or ``None`` to stay open.
    """
    if pair.published_at is not None and _aware(pair.published_at) > _aware(open_request.requested_at):
        return STATE_REPUBLISHED
    if pair.sha != open_request.sha or not stale:
        return STATE_CLEARED
    if _aware(now) >= _aware(open_request.expires_at):
        return STATE_EXPIRED
    return None


def should_open_request(
    *,
    stale: bool,
    enabled: bool,
    has_open_request: bool,
    last_request_for_sha_at: Optional[datetime],
    last_verified_at: Optional[datetime],
) -> bool:
    """Whether the sweep opens a re-publish request for a pair.

    Once per pact version since its last verification: a request that expired (or was answered)
    is not reopened for the same pact until the provider verifies it again.

    Args:
        stale: Whether the pair's newest pact is stale.
        enabled: The workspace's ``republish_requests_enabled``.
        has_open_request: Whether the pair already has an open request.
        last_request_for_sha_at: When the newest request for this pact version was opened, if any.
        last_verified_at: When the pact version was last verified, if ever.

    Returns:
        True to open one.
    """
    if not stale or not enabled or has_open_request:
        return False
    if last_request_for_sha_at is None:
        return True
    if last_verified_at is None:
        return False
    return _aware(last_verified_at) > _aware(last_request_for_sha_at)


@dataclass(frozen=True)
class ScheduleDecision:
    """Whether a pair is due for a scheduled verification.

    Attributes:
        due: Whether to verify it now.
        blocked_code: When due but it cannot run: :data:`CODE_NO_TARGET`.
        blocked_reason: The sentence for that.
    """

    due: bool
    blocked_code: Optional[str] = None
    blocked_reason: Optional[str] = None


def decide_schedule(
    effective: EffectiveSettings,
    *,
    sha: str,
    has_result: bool,
    last_attempt_sha: Optional[str],
    last_attempt_at: Optional[datetime],
    last_verified_at: Optional[datetime],
    now: datetime,
    last_attempt_code: Optional[str] = None,
) -> ScheduleDecision:
    """Whether the scheduler verifies a pair's newest pact on this sweep.

    * ``manual-only``: never.
    * Every other cadence: a pact version with no result that the scheduler has not tried yet.
    * ``hourly`` / ``nightly`` also: when neither a result nor an attempt is newer than the interval.

    A due pair with no verification target is reported (``blocked_code``), never skipped silently;
    it is recorded once per pact version so the sweep does not repeat it every tick.

    Args:
        effective: The pair's effective settings.
        sha: The pair's newest pact version.
        has_result: Whether that version has a verification result.
        last_attempt_sha: The pact version of the pair's last scheduled attempt.
        last_attempt_at: When that attempt was made.
        last_verified_at: When the version's newest result was published.
        now: The current time.
        last_attempt_code: The code of that attempt; an attempt blocked for want of a target does
            not count as tried once a target is set.

    Returns:
        The decision.
    """
    if effective.cadence == CADENCE_MANUAL:
        return ScheduleDecision(due=False)
    blocked_before = last_attempt_sha == sha and last_attempt_code == CODE_NO_TARGET
    tried = last_attempt_sha == sha and not (blocked_before and effective.target)
    due = not has_result and not tried
    interval = CADENCE_INTERVAL_SECONDS.get(effective.cadence)
    if not due and interval is not None:
        latest = max(
            (_aware(moment) for moment in (last_attempt_at, last_verified_at) if moment is not None), default=None
        )
        due = latest is None or (_aware(now) - latest).total_seconds() >= interval
    if not due:
        return ScheduleDecision(due=False)
    if not effective.target:
        if blocked_before:
            return ScheduleDecision(due=False)
        return ScheduleDecision(
            due=True,
            blocked_code=CODE_NO_TARGET,
            blocked_reason=(
                f"the cadence is {effective.cadence} but no verification target is set for this pair; "
                "add one in an override on Verification settings"
            ),
        )
    return ScheduleDecision(due=True)
