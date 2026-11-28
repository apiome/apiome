"""Pact verdicts as commit statuses — the vocabulary of PFX-4.4 (#6941).

When a pact is published, or a verification result arrives, Apiome puts the verdict of that
consumer ↔ provider pair back on the commit it is about, so a pull request shows it next to its
other checks:

* **On publish**, the consumer's commit gets ``pending`` — *awaiting verification by the
  provider* — unless the provider's main branch has already verified this exact pact content, in
  which case it gets that verdict straight away.
* **On a verification result**, the consumer's commit (the version that published the pact) and
  the provider's commit (the version that verified it) both get ``pass`` or ``fail``.

Each status is named by its **context**, ``apiome-pact/<consumer>/<provider>``, the same on both
repositories, so a newer verdict for the pair moves the status instead of adding one.

**Where it goes.** A pacticipant's ``repository_url`` names its repository; the status is written
through the matching repository the tenant has registered (Repositories), with the stored
credential of the account it was registered with. The pacticipant version number must be the
commit SHA (the Pact convention ``--consumer-app-version $GIT_COMMIT``).

**Nothing is dropped silently.** Every verdict is recorded. One that cannot be sent is recorded as
``suppressed`` with one of the ``CODE_*`` reasons below, and one the provider refuses as ``failed``
with the provider's reason; both can be retried once the cause is fixed.

Like :mod:`app.provider_checks`, this module is data and pure functions only: no database, no HTTP.
"""

from __future__ import annotations

import re
from typing import List, Literal, Optional, Tuple
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field

from .provider_checks import STATE_FAIL, STATE_PASS, STATE_PENDING
from .repository_validation import normalize_clone_url_for_dedup

__all__ = [
    "CODE_DISABLED",
    "CODE_SWITCHED_OFF",
    "CODE_NO_REPOSITORY",
    "CODE_NOT_A_COMMIT",
    "CODE_PROVIDER_UNSUPPORTED",
    "CODE_REPOSITORY_NOT_REGISTERED",
    "CODE_STATUS_NOT_FOUND",
    "CODE_STATUS_NOT_RETRYABLE",
    "CONTEXT_PREFIX",
    "CommitStatusList",
    "CommitStatusRecord",
    "MAX_DESCRIPTION_LENGTH",
    "OUTCOMES",
    "OUTCOME_DISPATCHED",
    "OUTCOME_FAILED",
    "OUTCOME_QUEUED",
    "OUTCOME_SUPPRESSED",
    "PROVIDER_HOSTS",
    "PactCommitStatusError",
    "RETRYABLE_OUTCOMES",
    "SIDES",
    "SIDE_CONSUMER",
    "SIDE_PROVIDER",
    "STATES",
    "StatusIntent",
    "context_for",
    "is_commit_sha",
    "normalize_repository_url",
    "pending_description",
    "repository_host",
    "verdict_description",
]

# ---------------------------------------------------------------------------------------------
# States, sides and outcomes (mirrors V443's CHECKs)
# ---------------------------------------------------------------------------------------------

#: A status is one of three of :mod:`app.provider_checks`'s normalized states; a commit status has
#: no ``skipped``.
STATES: Tuple[str, ...] = (STATE_PENDING, STATE_PASS, STATE_FAIL)

SIDE_CONSUMER = "consumer"
SIDE_PROVIDER = "provider"
#: Which pacticipant of the pair the status is posted for.
SIDES: Tuple[str, ...] = (SIDE_CONSUMER, SIDE_PROVIDER)

#: Recorded and being sent.
OUTCOME_QUEUED = "queued"
#: The provider accepted the status.
OUTCOME_DISPATCHED = "dispatched"
#: Never attempted, for the reason in ``reason_code``.
OUTCOME_SUPPRESSED = "suppressed"
#: The provider refused it, or could not be reached.
OUTCOME_FAILED = "failed"
OUTCOMES: Tuple[str, ...] = (OUTCOME_QUEUED, OUTCOME_DISPATCHED, OUTCOME_SUPPRESSED, OUTCOME_FAILED)

#: Outcomes a retry may send again. A dispatched status is already on the commit; a queued one is
#: being sent.
RETRYABLE_OUTCOMES: Tuple[str, ...] = (OUTCOME_SUPPRESSED, OUTCOME_FAILED)

# ---------------------------------------------------------------------------------------------
# Reasons
# ---------------------------------------------------------------------------------------------

#: The pacticipant has no ``repository_url``.
CODE_NO_REPOSITORY = "pact-status-no-repository"
#: The pacticipant version number is not a commit SHA, so there is no commit to put a status on.
CODE_NOT_A_COMMIT = "pact-status-version-not-a-commit"
#: No live repository registered in the workspace matches the pacticipant's ``repository_url``.
CODE_REPOSITORY_NOT_REGISTERED = "pact-status-repository-not-registered"
#: The repository is on a provider (or a self-hosted instance) statuses cannot be written to.
CODE_PROVIDER_UNSUPPORTED = "pact-status-provider-unsupported"
#: Status publishing is switched off for the deployment (``APIOME_PROVIDER_CHECKS_ENABLED``).
CODE_DISABLED = "check-publishing-disabled"
#: The workspace switched this kind of status off (Contracts → Settings → CI and commit statuses, PFX-8.15).
CODE_SWITCHED_OFF = "pact-status-switched-off"
#: The status id names no status of this workspace.
CODE_STATUS_NOT_FOUND = "pact-status-not-found"
#: A retry of a status that was accepted, or is being sent.
CODE_STATUS_NOT_RETRYABLE = "pact-status-not-retryable"

#: The only provider hosts statuses are written to, by provider. The API host is fixed per
#: provider (:mod:`app.provider_status_adapter`), so a repository on any other host — a
#: self-hosted GitLab, GitHub Enterprise — is reported unsupported rather than sent to the wrong
#: API.
PROVIDER_HOSTS = {"github": "github.com", "gitlab": "gitlab.com"}

#: Prefix of every status context.
CONTEXT_PREFIX = "apiome-pact"

#: GitLab keeps 255 characters of a description; GitHub 140 (the adapter trims further).
MAX_DESCRIPTION_LENGTH = 255

#: A full or abbreviated git commit SHA (SHA-1 or SHA-256), as a build reports it.
_SHA_PATTERN = re.compile(r"^[0-9a-f]{7,64}$", re.IGNORECASE)


class PactCommitStatusError(Exception):
    """A request about commit statuses that cannot be served.

    Attributes:
        code: ``pact-status-not-found`` or ``pact-status-not-retryable``.
    """

    def __init__(self, code: str, message: str) -> None:
        """Create the error.

        Args:
            code: The stable reason code.
            message: What went wrong, for the caller.
        """
        super().__init__(message)
        self.code = code


def is_commit_sha(value: Optional[str]) -> bool:
    """Whether a pacticipant version number is a git commit SHA.

    Args:
        value: The version number as the build reported it.

    Returns:
        ``True`` for 7–64 hexadecimal characters.
    """
    return bool(value) and bool(_SHA_PATTERN.match(str(value).strip()))


def normalize_repository_url(url: Optional[str]) -> Optional[str]:
    """The key a pacticipant's ``repository_url`` is matched to a registered repository by.

    The same normalization the Repositories registration stores in ``clone_url_normalized``, so
    ``https://github.com/Acme/Web``, ``https://github.com/acme/web.git`` and
    ``https://www.github.com/acme/web/`` all find the same registration.

    Args:
        url: The pacticipant's repository URL.

    Returns:
        The normalized clone URL, or ``None`` when the URL is empty or cannot be normalized (not
        HTTPS, no host).
    """
    if not url or not str(url).strip():
        return None
    try:
        return normalize_clone_url_for_dedup(str(url))
    except ValueError:
        return None


def repository_host(url: Optional[str]) -> str:
    """The lower-cased host of a repository URL, without ``www.``.

    Args:
        url: A repository or clone URL.

    Returns:
        The host, or ``""``.
    """
    try:
        host = urlparse(str(url or "").strip()).hostname or ""
    except ValueError:
        return ""
    return host.lower().removeprefix("www.")


def context_for(consumer_slug: str, provider_slug: str) -> str:
    """The status context of a consumer ↔ provider pair.

    Args:
        consumer_slug: The consumer's handle.
        provider_slug: The provider's handle.

    Returns:
        ``apiome-pact/<consumer>/<provider>``, at most 255 characters.
    """
    return f"{CONTEXT_PREFIX}/{consumer_slug}/{provider_slug}"[:255]


def _clip(text: str) -> str:
    """Bound a description to :data:`MAX_DESCRIPTION_LENGTH`."""
    return text if len(text) <= MAX_DESCRIPTION_LENGTH else text[: MAX_DESCRIPTION_LENGTH - 1] + "…"


def pending_description(provider_name: str) -> str:
    """What a consumer commit says while its pact waits for the provider.

    Args:
        provider_name: The provider's display name.

    Returns:
        The one-line description.
    """
    return _clip(f"Pact awaiting verification by {provider_name}")


def verdict_description(side: str, success: bool, other_name: str, other_version: Optional[str]) -> str:
    """What a commit says once a verification result is in.

    Args:
        side: ``consumer`` (the status is on the consumer's commit) or ``provider``.
        success: Whether the verification passed.
        other_name: The display name of the other pacticipant of the pair.
        other_version: The other pacticipant's version, when known.

    Returns:
        The one-line description, e.g. ``Pact verified by Billing API 4f2a9c1`` on a consumer
        commit or ``Pact with Web App 9b1e0d2 failed verification`` on a provider commit.
    """
    version = f" {other_version[:12]}" if other_version else ""
    if side == SIDE_CONSUMER:
        verb = "verified by" if success else "failed verification by"
        return _clip(f"Pact {verb} {other_name}{version}")
    outcome = "verified" if success else "failed verification"
    return _clip(f"Pact with {other_name}{version} {outcome}")


class StatusIntent(BaseModel):
    """One verdict about to be recorded for one pacticipant version.

    Attributes:
        tenant_id: The workspace.
        pacticipant_id: Whose repository the status goes to.
        pacticipant_version_id: The version (commit) it is about.
        version_number: That version's number — the commit SHA when the build followed the
            convention.
        repository_url: The pacticipant's repository URL.
        consumer_id: The pair's consumer.
        provider_id: The pair's provider.
        side: ``consumer`` or ``provider``.
        context: The status context.
        state: ``pending``, ``pass`` or ``fail``.
        description: The one-line description.
        target_url: Where the status links (the pact or the verification result).
        pact_version_sha: The pact content.
        verification_number: The verification result, for a verdict.
    """

    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    pacticipant_id: str
    pacticipant_version_id: str
    version_number: str
    repository_url: Optional[str] = None
    consumer_id: str
    provider_id: str
    side: Literal["consumer", "provider"]
    context: str
    state: Literal["pending", "pass", "fail"]
    description: str = ""
    target_url: Optional[str] = None
    pact_version_sha: Optional[str] = None
    verification_number: Optional[int] = None


class CommitStatusRecord(BaseModel):
    """A recorded commit status, as the API returns it.

    Never carries a token: the credential is resolved at send time and stored nowhere.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="Status id.")
    pacticipant: str = Field(description="Handle of the pacticipant whose commit the status is on.")
    version: str = Field(description="The pacticipant version (commit) the status is about.")
    consumer: str = Field(description="Handle of the pair's consumer.")
    provider: str = Field(description="Handle of the pair's provider.")
    side: Literal["consumer", "provider"] = Field(description="Which pacticipant of the pair the status is for.")
    context: str = Field(description="Status context, `apiome-pact/<consumer>/<provider>`.")
    state: Literal["pending", "pass", "fail"] = Field(description="The verdict.")
    description: str = Field(default="", description="The one-line description shown on the commit.")
    target_url: Optional[str] = Field(default=None, description="Where the status links.")
    pact_version_sha: Optional[str] = Field(default=None, description="The pact content the verdict is about.")
    verification_number: Optional[int] = Field(default=None, description="The verification result, for a verdict.")
    commit_sha: Optional[str] = Field(default=None, description="The commit the status was written to.")
    git_provider: Optional[str] = Field(default=None, description="`github` or `gitlab`, once a repository matched.")
    repository: Optional[str] = Field(default=None, description="Full name of the repository written to.")
    repository_id: Optional[str] = Field(default=None, description="The registered repository used.")
    outcome: Literal["queued", "dispatched", "suppressed", "failed"] = Field(
        description="`dispatched` (accepted), `suppressed` (not attempted — see `reason_code`), `failed` or `queued`."
    )
    reason_code: Optional[str] = Field(default=None, description="Stable reason for a suppressed or failed status.")
    message: str = Field(default="", description="What happened, in words.")
    http_status: Optional[int] = Field(default=None, description="The provider's HTTP status, when a request went out.")
    attempts: int = Field(default=0, description="How many times the status was sent.")
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class CommitStatusList(BaseModel):
    """A page of commit statuses, newest first."""

    model_config = ConfigDict(extra="forbid")

    items: List[CommitStatusRecord]
    next_cursor: Optional[str] = Field(default=None, description="Pass as `cursor` for the next page.")
