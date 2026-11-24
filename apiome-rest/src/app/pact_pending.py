"""Pending pacts — PFX-1.7 (#6920).

A new consumer expectation must not break the provider's build the moment it is published. The
Pact Broker's answer is the **pending** pact: until the provider has shown it can satisfy a pact,
a failed verification of it is reported but does not fail the provider build.

This module is the pure rule — no database, no HTTP. :class:`PendingEvidence` holds what the
rule needs about the provider's past (read by :func:`app.pact_pending_store.load_pending_evidence`),
and :func:`pact_is_pending` answers for one pact content and one verifying provider build.

The rule, as the Pact Broker defines it (docs.pact.io/go/pending):

==========================  ======================================================================
The verifier sends          The pact is pending until …
==========================  ======================================================================
``providerVersionBranch``   … a provider version **from that branch** verified it successfully.
                            A branch created *after* a successful verification on any other
                            branch inherits it: a pact verified on ``main`` is not pending for a
                            new ``feat-x`` branch cut from ``main`` afterwards, but stays pending
                            for a branch that already existed when ``main`` verified it.
``providerVersionTags``     … a provider version **with each of those tags** verified it
                            successfully (pending for every tag still missing a success).
neither                     … **any** provider version verified it successfully.
==========================  ======================================================================

Only successful results count; a failure never ends the pending state. The state is per pact
*content* (its ``sha``): a consumer version that republishes verified content is not pending,
and changed content starts pending again.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Sequence

__all__ = [
    "NO_EVIDENCE",
    "PactSuccesses",
    "PendingEvidence",
    "pact_is_pending",
    "pending_provider_tags",
]


@dataclass(frozen=True)
class PactSuccesses:
    """Every successful verification of one pact content by the provider, summarised.

    Attributes:
        branches: The provider branches a successful verification ran on.
        tags: The tags of the provider versions that verified it successfully.
        first_success_at: When the earliest successful result was published.
    """

    branches: FrozenSet[str] = frozenset()
    tags: FrozenSet[str] = frozenset()
    first_success_at: Optional[datetime.datetime] = None


@dataclass(frozen=True)
class PendingEvidence:
    """What the pending rule needs to know about a provider's verification history.

    Attributes:
        successes: Successful verifications by pact content address (``sha``). A content with no
            entry has never been verified successfully.
        branch_created_at: When the verifying provider branch was first recorded; ``None`` when the
            branch does not exist yet (a brand-new branch: every earlier success predates it).
    """

    successes: Dict[str, PactSuccesses] = field(default_factory=dict)
    branch_created_at: Optional[datetime.datetime] = None


#: No history at all: every pact is pending.
NO_EVIDENCE = PendingEvidence()


def _predates(when: Optional[datetime.datetime], created_at: Optional[datetime.datetime]) -> bool:
    """Whether a success at ``when`` happened before a branch created at ``created_at``.

    A branch that does not exist yet (``created_at`` is ``None``) is created after everything.
    """
    if when is None:
        return False
    return created_at is None or when < created_at


def pending_provider_tags(sha: str, tags: Sequence[str], evidence: PendingEvidence) -> List[str]:
    """The verifying tags for which a pact content has not been verified successfully.

    Args:
        sha: The pact content address.
        tags: The request's ``providerVersionTags``.
        evidence: The provider's history.

    Returns:
        The tags, in request order, still lacking a successful verification.
    """
    verified = evidence.successes.get(sha, PactSuccesses()).tags
    return [tag for tag in tags if tag not in verified]


def pact_is_pending(
    sha: str,
    provider_version_branch: Optional[str],
    provider_version_tags: Sequence[str],
    evidence: PendingEvidence,
) -> bool:
    """Whether a pact is pending for the provider build about to verify it.

    Args:
        sha: The pact content address.
        provider_version_branch: The request's ``providerVersionBranch``, if sent.
        provider_version_tags: The request's ``providerVersionTags`` (used only without a branch).
        evidence: The provider's successful verifications, and when the branch was created.

    Returns:
        ``True`` while a failure of this pact must not fail the build (see the module table).
    """
    successes = evidence.successes.get(sha)
    if successes is None:
        return True
    if provider_version_branch:
        if provider_version_branch in successes.branches:
            return False
        return not _predates(successes.first_success_at, evidence.branch_created_at)
    if provider_version_tags:
        return bool(pending_provider_tags(sha, provider_version_tags, evidence))
    return False
