"""Normalized provider checks — the shared vocabulary of GNC-2.2 (#4738).

A **check run** is one verdict about one commit of one branch-to-draft binding (GNC-2.1), in a
vocabulary that belongs to this platform rather than to any provider: ``pending``, ``pass``,
``fail``, ``skipped``. Everything above this module — the store, the routes, the webhook path,
and GNC-3.1's check suite — thinks only in those four words. Turning one of them into the shape a
provider actually wants is the adapter's job (:mod:`app.provider_status_adapter`), and this module
holds the tables it maps through so the mapping is data, testable against literals, rather than
three branches of ``if provider ==``.

Why a normalized model at all, when GitHub's check-runs API is right there: because the three
providers disagree about what a status *is*. GitHub splits it in two (``status`` says whether the
run finished, ``conclusion`` says how), GitLab has a single commit ``state`` with a ``running``
that means what GitHub calls ``in_progress``, and Bitbucket has build states in capitals with no
``skipped`` at all. Store any one of those and the other two become lossy translations of it. Store
four words we chose and every provider is an edge, none of them is the centre, and a check written
before an adapter existed still reads correctly after one does.

Like :mod:`app.draft_bindings`, this module is data and pure functions only: no database handle, no
HTTP client, no clock. Nothing here can publish anything.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Dict, List, Literal, Mapping, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "AUDIT_CHECK_PUBLISHED",
    "AUDIT_CHECK_RECORDED",
    "CHECK_NAME_PATTERN",
    "CHECK_ORIGINS",
    "CHECK_STATES",
    "CODE_BINDING_NOT_FOUND",
    "CODE_BINDING_RELEASED",
    "CODE_CHECK_NOT_FOUND",
    "CODE_COMMIT_UNKNOWN",
    "CODE_INVALID_COMMIT",
    "CODE_INVALID_DETAILS_URL",
    "CODE_INVALID_NAME",
    "CODE_PROJECT_NOT_FOUND",
    "CODE_PROVIDER_FORBIDDEN",
    "CODE_PROVIDER_REFUSED",
    "CODE_PROVIDER_UNAVAILABLE",
    "CODE_PROVIDER_UNSUPPORTED",
    "CODE_VERSION_NOT_FOUND",
    "CheckDeliveryRecord",
    "CheckOrigin",
    "CheckRunDetail",
    "CheckRunRecord",
    "CheckRunUpsert",
    "CheckState",
    "DEFAULT_CHECK_NAME",
    "MAX_DETAILS_URL_LENGTH",
    "MAX_NAME_LENGTH",
    "MAX_SUMMARY_LENGTH",
    "MAX_TITLE_LENGTH",
    "ORIGIN_API",
    "ORIGIN_SWEEP",
    "ORIGIN_WEBHOOK",
    "OUTCOME_DISPATCHED",
    "PUBLISH_OUTCOMES",
    "OUTCOME_FAILED",
    "OUTCOME_SUPPRESSED",
    "ProviderCheckValidationError",
    "PublishOutcome",
    "STATE_FAIL",
    "STATE_PASS",
    "STATE_PENDING",
    "STATE_SKIPPED",
    "TERMINAL_STATES",
    "bitbucket_state",
    "github_conclusion",
    "github_status",
    "gitlab_state",
    "is_terminal",
    "normalize_check_name",
    "normalize_commit_sha",
    "normalize_details_url",
    "normalize_state",
    "request_fingerprint",
    "summarize_states",
]

# ---------------------------------------------------------------------------------------------
# The four states
# ---------------------------------------------------------------------------------------------

#: The check is running (or queued). It has no verdict yet and no ``completed_at``.
STATE_PENDING = "pending"
#: The check ran and the change is acceptable.
STATE_PASS = "pass"
#: The check ran and the change is not acceptable. This is the state a merge gate blocks on.
STATE_FAIL = "fail"
#: The check did not apply — nothing it inspects changed, or it is deliberately not run here. A
#: skip is a real verdict and must never be reported as a pass: "we did not look" and "we looked
#: and it is fine" answer different questions.
STATE_SKIPPED = "skipped"

#: Every state, in the order the V265 CHECK lists them.
CHECK_STATES: Tuple[str, ...] = (STATE_PENDING, STATE_PASS, STATE_FAIL, STATE_SKIPPED)

#: The states that mean the check has finished. Exactly the complement of ``pending``.
TERMINAL_STATES: Tuple[str, ...] = (STATE_PASS, STATE_FAIL, STATE_SKIPPED)

CheckState = Literal["pending", "pass", "fail", "skipped"]

#: How a check came to exist. Mirrors the V265 CHECK.
ORIGIN_WEBHOOK = "webhook"
ORIGIN_API = "api"
ORIGIN_SWEEP = "sweep"
CHECK_ORIGINS: Tuple[str, ...] = (ORIGIN_WEBHOOK, ORIGIN_API, ORIGIN_SWEEP)

CheckOrigin = Literal["webhook", "api", "sweep"]

#: What one publish attempt did. Mirrors the V265 CHECK.
OUTCOME_DISPATCHED = "dispatched"
#: Nothing was sent, on purpose: checks are off, no credential resolved, or no adapter exists.
OUTCOME_SUPPRESSED = "suppressed"
#: It was sent and the provider refused it.
OUTCOME_FAILED = "failed"
PUBLISH_OUTCOMES: Tuple[str, ...] = (OUTCOME_DISPATCHED, OUTCOME_SUPPRESSED, OUTCOME_FAILED)

PublishOutcome = Literal["dispatched", "suppressed", "failed"]

#: ``workflow_audit`` actions, written inside the transaction of the change they record.
AUDIT_CHECK_RECORDED = "check.recorded"
AUDIT_CHECK_PUBLISHED = "check.published"

# ---------------------------------------------------------------------------------------------
# Bounds and names
# ---------------------------------------------------------------------------------------------

#: Mirrors ``provider_check_runs.name VARCHAR(128)``.
MAX_NAME_LENGTH = 128

#: Mirrors ``provider_check_runs.title VARCHAR(255)``.
MAX_TITLE_LENGTH = 255

#: The summary column is TEXT; this is the bound a request is held to, chosen to sit under every
#: provider's own limit (GitHub truncates a check-run summary at 65535 characters).
MAX_SUMMARY_LENGTH = 16_000

#: The details URL column is TEXT; the bound keeps a pathological link out of a provider request.
MAX_DETAILS_URL_LENGTH = 2_048

#: The check a delivery seeds when nobody named one. Namespaced so it is obvious on a pull request
#: which system put it there, and stable so a re-run lands on the same row (V265 rule 2).
DEFAULT_CHECK_NAME = "apiome/api-change"

#: A check name is a provider-safe slug: letters, digits, and ``. _ - /``. Slashes are allowed
#: because every provider displays a namespaced context that way, and nothing else is, because a
#: name ends up in a URL path segment and in a provider's own display.
CHECK_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")

#: A commit is a hexadecimal object id — every provider's, in every hash algorithm any of them
#: uses. Short forms are allowed because a caller may legitimately hold one, but nothing else is:
#: the value goes into a provider URL, and a verdict must never be attached to something that is
#: not a commit.
COMMIT_SHA_PATTERN = re.compile(r"^[0-9a-fA-F]{7,64}$")

#: The only schemes a details link may use. A check's link is rendered as a link on a pull request
#: by every provider, so a `javascript:` or `data:` URL recorded here would be one this platform
#: put in front of a reviewer. Providers reject most of these themselves; relying on that would
#: make our safety somebody else's implementation detail.
DETAILS_URL_SCHEMES = ("http://", "https://")

# ---------------------------------------------------------------------------------------------
# Refusal codes. A client branches on the code, never on the message.
# ---------------------------------------------------------------------------------------------

CODE_PROJECT_NOT_FOUND = "check-project-not-found"
CODE_VERSION_NOT_FOUND = "check-version-not-found"
#: The version has no active binding, so there is no repository to report a check against.
CODE_BINDING_NOT_FOUND = "check-binding-not-found"
#: The binding has been released, or its repository registration was removed: it is history.
CODE_BINDING_RELEASED = "check-binding-released"
CODE_CHECK_NOT_FOUND = "check-not-found"
#: The name is empty, too long, or not a provider-safe slug.
CODE_INVALID_NAME = "check-invalid-name"
#: A commit was named that this binding has never been observed at.
CODE_COMMIT_UNKNOWN = "check-commit-unknown"
#: The commit is empty, too long, or not a hexadecimal object id.
CODE_INVALID_COMMIT = "check-invalid-commit"
#: The details link is not an ``http``/``https`` URL.
CODE_INVALID_DETAILS_URL = "check-invalid-details-url"
#: No stored credential grants a write of this repository's checks.
CODE_PROVIDER_FORBIDDEN = "check-provider-forbidden"
#: The provider was reached and refused the publish.
CODE_PROVIDER_REFUSED = "check-provider-refused"
#: The provider could not be reached.
CODE_PROVIDER_UNAVAILABLE = "check-provider-unavailable"
#: The binding names a provider no status adapter covers.
CODE_PROVIDER_UNSUPPORTED = "check-provider-unsupported"


class ProviderCheckValidationError(Exception):
    """A refusal from the check store, carrying a stable code.

    Attributes:
        code: One of the ``CODE_*`` constants in this module.
    """

    def __init__(self, code: str, message: str) -> None:
        """Create the refusal.

        Args:
            code: The stable refusal code.
            message: A human-readable explanation.
        """
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------------------------------
# Provider spellings
#
# One table per provider, so "what does `skipped` look like on Bitbucket" is a dictionary lookup a
# test can assert on, not a branch buried in an HTTP client.
# ---------------------------------------------------------------------------------------------

#: GitHub check-runs split a status in two: ``status`` says whether the run finished.
_GITHUB_STATUS: Dict[str, str] = {
    STATE_PENDING: "in_progress",
    STATE_PASS: "completed",
    STATE_FAIL: "completed",
    STATE_SKIPPED: "completed",
}

#: …and ``conclusion`` says how, which only a completed run has.
_GITHUB_CONCLUSION: Dict[str, Optional[str]] = {
    STATE_PENDING: None,
    STATE_PASS: "success",
    STATE_FAIL: "failure",
    STATE_SKIPPED: "skipped",
}

#: GitLab commit statuses are a single state. ``running`` is its ``in_progress``.
_GITLAB_STATE: Dict[str, str] = {
    STATE_PENDING: "running",
    STATE_PASS: "success",
    STATE_FAIL: "failed",
    STATE_SKIPPED: "canceled",
}

#: Bitbucket build statuses, in capitals. It has no "skipped", and ``STOPPED`` is the nearest
#: honest thing: the build did not run to a verdict. It is deliberately not ``SUCCESSFUL``.
_BITBUCKET_STATE: Dict[str, str] = {
    STATE_PENDING: "INPROGRESS",
    STATE_PASS: "SUCCESSFUL",
    STATE_FAIL: "FAILED",
    STATE_SKIPPED: "STOPPED",
}


def normalize_state(raw: object) -> Optional[str]:
    """Normalize a state to one of the four, or ``None``.

    Accepts the handful of spellings callers reach for — ``passed``, ``success``, ``failed``,
    ``failure``, ``skip`` — because a check suite written against a provider's vocabulary should
    not silently record the wrong verdict. Anything else is ``None``: an unrecognised state is
    never guessed at, since guessing between ``pass`` and ``fail`` is the one mistake that matters.

    Args:
        raw: The state as given.

    Returns:
        The normalized state, or ``None`` when it is not one of the four.
    """
    text = str(raw or "").strip().lower()
    if text in CHECK_STATES:
        return text
    aliases = {
        "passed": STATE_PASS,
        "success": STATE_PASS,
        "successful": STATE_PASS,
        "failed": STATE_FAIL,
        "failure": STATE_FAIL,
        "skip": STATE_SKIPPED,
        "in_progress": STATE_PENDING,
        "running": STATE_PENDING,
        "queued": STATE_PENDING,
    }
    return aliases.get(text)


def is_terminal(state: str) -> bool:
    """True when a state means the check has finished.

    Args:
        state: A normalized state.

    Returns:
        Whether the check has a verdict. ``pending`` is the only state that does not.
    """
    return state in TERMINAL_STATES


def normalize_check_name(raw: object) -> str:
    """Normalize and validate a check name.

    Args:
        raw: The name as given; blank falls back to :data:`DEFAULT_CHECK_NAME`.

    Returns:
        The trimmed name.

    Raises:
        ProviderCheckValidationError: ``check-invalid-name`` when the name is too long or is not a
            provider-safe slug.
    """
    text = str(raw or "").strip() or DEFAULT_CHECK_NAME
    if len(text) > MAX_NAME_LENGTH:
        raise ProviderCheckValidationError(
            CODE_INVALID_NAME,
            f"A check name is at most {MAX_NAME_LENGTH} characters.",
        )
    if not CHECK_NAME_PATTERN.match(text):
        raise ProviderCheckValidationError(
            CODE_INVALID_NAME,
            "A check name may contain only letters, digits, '.', '_', '-' and '/', "
            "and must start with a letter or a digit.",
        )
    return text


def normalize_commit_sha(raw: object) -> str:
    """Normalize and validate a commit id.

    Args:
        raw: The commit as given.

    Returns:
        The trimmed, lowercased commit id.

    Raises:
        ProviderCheckValidationError: ``check-invalid-commit`` when it is not a hexadecimal object
            id of a plausible length.
    """
    text = str(raw or "").strip().lower()
    if not COMMIT_SHA_PATTERN.match(text):
        raise ProviderCheckValidationError(
            CODE_INVALID_COMMIT,
            "A commit must be a hexadecimal object id of 7 to 64 characters.",
        )
    return text


def normalize_details_url(raw: object) -> str:
    """Normalize and validate the link a check points a reviewer at.

    Args:
        raw: The URL as given; blank is allowed and means "no link".

    Returns:
        The trimmed URL, or ``""``.

    Raises:
        ProviderCheckValidationError: ``check-invalid-details-url`` when it is too long or uses a
            scheme other than ``http``/``https``.
    """
    text = str(raw or "").strip()
    if not text:
        return ""
    if len(text) > MAX_DETAILS_URL_LENGTH:
        raise ProviderCheckValidationError(
            CODE_INVALID_DETAILS_URL,
            f"A details link is at most {MAX_DETAILS_URL_LENGTH} characters.",
        )
    if not text.lower().startswith(DETAILS_URL_SCHEMES):
        raise ProviderCheckValidationError(
            CODE_INVALID_DETAILS_URL,
            "A details link must be an http:// or https:// URL.",
        )
    return text


def github_status(state: str) -> str:
    """The GitHub check-run ``status`` for a normalized state.

    Args:
        state: A normalized state.

    Returns:
        ``in_progress`` while pending, ``completed`` once there is a verdict.
    """
    return _GITHUB_STATUS.get(state, "completed")


def github_conclusion(state: str) -> Optional[str]:
    """The GitHub check-run ``conclusion`` for a normalized state.

    Args:
        state: A normalized state.

    Returns:
        ``success`` / ``failure`` / ``skipped``, or ``None`` while the run is pending — GitHub
        refuses a conclusion on a run that has not completed.
    """
    return _GITHUB_CONCLUSION.get(state)


def gitlab_state(state: str) -> str:
    """The GitLab commit-status ``state`` for a normalized state.

    Args:
        state: A normalized state.

    Returns:
        ``running`` / ``success`` / ``failed`` / ``canceled``.
    """
    return _GITLAB_STATE.get(state, "failed")


def bitbucket_state(state: str) -> str:
    """The Bitbucket build-status ``state`` for a normalized state.

    Args:
        state: A normalized state.

    Returns:
        ``INPROGRESS`` / ``SUCCESSFUL`` / ``FAILED`` / ``STOPPED``.
    """
    return _BITBUCKET_STATE.get(state, "FAILED")


def request_fingerprint(payload: Mapping[str, object]) -> str:
    """Fingerprint the normalized request an adapter would send.

    Two publish attempts that would put the same bytes in front of the same provider are the same
    attempt, and V265's ``UNIQUE (check_run_id, request_fingerprint)`` turns that into a collision
    rather than a second call. Sorting the keys is what makes the fingerprint depend on the content
    and not on the order a dict happened to be built in.

    Args:
        payload: The provider-shaped request body, plus whatever else distinguishes the call (the
            endpoint, the commit, the check name).

    Returns:
        ``"sha256:<hex>"`` — the spelling :func:`app.draft_bindings.source_digest` uses, so the two
        are never mistaken for one another's format.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def summarize_states(states: List[str]) -> str:
    """Reduce a set of check states to the one a merge gate would act on.

    The precedence is the one every CI system converges on, and it is deliberately pessimistic:
    one failure fails the set, an unfinished check holds it, and a set of skips is a skip rather
    than a pass. Only "everything ran and nothing objected" is a pass.

    Args:
        states: Normalized states, in any order. An empty list is ``skipped`` — nothing ran, so
            nothing may claim it passed.

    Returns:
        The aggregate state.
    """
    present = [state for state in states if state in CHECK_STATES]
    if not present:
        return STATE_SKIPPED
    if STATE_FAIL in present:
        return STATE_FAIL
    if STATE_PENDING in present:
        return STATE_PENDING
    if STATE_PASS in present:
        return STATE_PASS
    return STATE_SKIPPED


# ---------------------------------------------------------------------------------------------
# Records
#
# None of these models carries a credential, and none ever will: they are read straight into an
# API response a browser client receives (V265 rule 5). `extra="forbid"` means a column that later
# grows a token cannot arrive here by accident — it raises.
# ---------------------------------------------------------------------------------------------


class CheckDeliveryRecord(BaseModel):
    """One attempt to publish a verdict to a provider."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="The delivery id.")
    check_run_id: str
    provider: str = Field(description="`github`, `gitlab`, or `bitbucket`.")
    state: CheckState = Field(description="The state this attempt published.")
    outcome: PublishOutcome = Field(
        description="`dispatched` (accepted), `suppressed` (deliberately not sent), or `failed`."
    )
    status_code: Optional[int] = Field(
        default=None, description="The provider's HTTP status, when a request went out."
    )
    external_id: Optional[str] = Field(
        default=None, description="The provider's id for the check, when it returned one."
    )
    error_code: Optional[str] = Field(default=None, description="Stable reason for a refusal.")
    error_message: str = Field(
        default="", description="The provider's message, redacted before it was stored."
    )
    created_at: datetime


class CheckRunRecord(BaseModel):
    """One normalized check verdict about one commit."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="The check run id.")
    tenant_id: str
    binding_id: str = Field(description="The branch-to-draft binding the check belongs to.")
    project_id: str
    version_id: str
    version_label: Optional[str] = Field(default=None, description="The version's label.")
    provider: str = Field(description="`github`, `gitlab`, or `bitbucket`.")
    repo_full_name: str = Field(description="Lowercased `owner/name`.")
    ref: Optional[str] = Field(default=None, description="The bound ref, read from the binding.")
    commit_sha: str = Field(description="The commit the verdict is about.")
    pr_number: Optional[int] = Field(
        default=None, description="The pull request the commit belongs to, when one was named."
    )
    name: str = Field(description="The check's stable name, e.g. `apiome/api-change`.")
    state: CheckState = Field(description="`pending`, `pass`, `fail`, or `skipped`.")
    title: str = Field(default="", description="The one-line title a reviewer sees.")
    summary: str = Field(default="", description="The longer explanation.")
    details_url: str = Field(default="", description="Where the check points a reviewer.")
    external_id: Optional[str] = Field(
        default=None, description="The provider's own id for the check, when it has one."
    )
    origin: CheckOrigin = Field(description="`webhook`, `api`, or `sweep`.")
    delivery_id: Optional[str] = Field(
        default=None, description="The provider delivery that seeded it."
    )
    attempt: int = Field(ge=1, description="How many times this check has been run.")
    started_at: datetime
    completed_at: Optional[datetime] = Field(
        default=None, description="When it left `pending`; null exactly while it is pending."
    )
    created_by: Optional[str] = Field(default=None, description="Who recorded it, when a person did.")
    created_by_name: Optional[str] = Field(default=None, description="Their display name.")
    created_at: datetime
    updated_at: datetime
    last_publish_outcome: Optional[PublishOutcome] = Field(
        default=None, description="What the most recent publish attempt did."
    )
    last_publish_error: Optional[str] = Field(
        default=None, description="Stable reason code of the most recent failed attempt."
    )


class CheckRunDetail(BaseModel):
    """A check run with the publish attempts behind it."""

    model_config = ConfigDict(extra="forbid")

    check: CheckRunRecord
    deliveries: List[CheckDeliveryRecord] = Field(
        default_factory=list, description="Publish attempts, newest first."
    )


# ---------------------------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------------------------


class CheckRunUpsert(BaseModel):
    """Record a check verdict against a version's active binding.

    Idempotent by construction: ``(binding, commit, name)`` identifies the check, so the same call
    twice is one verdict. A credential is never accepted in the body — the repository token is
    resolved server-side from the binding's registration.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        default=DEFAULT_CHECK_NAME,
        max_length=MAX_NAME_LENGTH,
        description="The check's stable name; the same name on the same commit is the same check.",
    )
    state: CheckState = Field(
        default=STATE_PENDING, description="`pending`, `pass`, `fail`, or `skipped`."
    )
    commit_sha: Optional[str] = Field(
        default=None,
        max_length=64,
        description="The commit to report against; defaults to the binding's synchronized commit.",
    )
    title: str = Field(default="", max_length=MAX_TITLE_LENGTH, description="One-line title.")
    summary: str = Field(
        default="", max_length=MAX_SUMMARY_LENGTH, description="The longer explanation."
    )
    details_url: str = Field(
        default="",
        max_length=MAX_DETAILS_URL_LENGTH,
        description="Where the check points a reviewer; a failure should be a reason, not a log.",
    )
    pr_number: Optional[int] = Field(
        default=None, gt=0, description="The pull request the commit belongs to, when known."
    )
    publish: bool = Field(
        default=True,
        description=(
            "Publish the verdict to the provider as well as recording it. False records it only — "
            "useful while a check suite is being developed against a real repository."
        ),
    )
    rerun: bool = Field(
        default=False,
        description=(
            "Treat this as a fresh run of the same check: the attempt counter advances. Without "
            "it, re-recording the same verdict leaves the row exactly as it is."
        ),
    )
