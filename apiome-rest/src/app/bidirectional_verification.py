"""Bi-directional verdicts: comparisons stored as verification results — PFX-2.3 (#6927). Pure.

A consumer's pact is checked against the provider in one of two ways. A Pact verifier replays it
against the running provider and publishes a *native* result (PFX-1.4). Or the provider publishes
its OpenAPI document (a *provider contract*, PFX-2.1) and Apiome compares the pact with it
(:func:`app.pact_oas_compare.compare_pact_to_oas`, PFX-2.2). This module turns that comparison into
a ``verification_result`` row with ``kind = bidirectional``, so the matrix and can-i-deploy
(PFX-1.6) read it exactly as they read a native one.

This module holds the parts with no database:

* **which provider versions a new pact is compared with** (:func:`select_contract_targets`): the
  latest version with a contract on each provider branch, every version with a contract that is
  currently deployed or released, and the latest version with a contract overall;
* **what is stored** (:func:`stored_comparison`): ``success`` (the comparison's verdict is not
  ``fail``: a ``partial`` verdict passes, and its fidelity notes travel with it), Pact-shaped
  ``testResults`` so a Pact client reading the result sees one entry per interaction, and the
  comparison payload itself;
* **what the caller is told** (:class:`ComparisonRun`, :func:`run_notices`): one entry per pair,
  including the ones that were already compared, could not be stored, or went over the limit, so
  nothing is dropped without a reason.

The database side is :mod:`app.bidirectional_store`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .pact_oas_result import VERDICT_FAIL, ComparisonResult

__all__ = [
    "ENGINE_NAME",
    "KIND_BIDIRECTIONAL",
    "KIND_NATIVE",
    "MAX_CONTRACTS_PER_PACT",
    "MAX_PACTS_PER_CONTRACT",
    "STATUS_ALREADY_COMPARED",
    "STATUS_COMPARED",
    "STATUS_ERROR",
    "STATUS_SKIPPED",
    "ComparisonRun",
    "ContractTarget",
    "RunEntry",
    "SelectedTarget",
    "StoredComparison",
    "error_comparison",
    "run_notices",
    "select_contract_targets",
    "stored_comparison",
]

#: A result a Pact verifier published (PFX-1.4).
KIND_NATIVE = "native"
#: A result Apiome wrote from a pact-to-OpenAPI comparison.
KIND_BIDIRECTIONAL = "bidirectional"

#: How a bi-directional result names its verifier (``verifiedBy.implementation``).
ENGINE_NAME = "Apiome bi-directional comparison"

#: The most provider versions one published pact is compared with.
MAX_CONTRACTS_PER_PACT = 20
#: The most pact versions one published provider contract is compared with.
MAX_PACTS_PER_CONTRACT = 50

#: A new result was stored.
STATUS_COMPARED = "compared"
#: The pair had a bi-directional result already; nothing was stored.
STATUS_ALREADY_COMPARED = "already-compared"
#: The comparison could not be stored (logged); the pair has no result.
STATUS_ERROR = "error"
#: The pair was not compared: over the limit.
STATUS_SKIPPED = "skipped"

#: The code of a stored comparison that could not be run at all.
CODE_NOT_COMPARABLE = "comparison-not-possible"

#: The most mismatches one test result lists (the comparison payload keeps them all).
_MAX_MISMATCHES = 50


# ---------------------------------------------------------------------------------------------
# Which provider versions a pact is compared with
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ContractTarget:
    """A provider version that published a provider contract.

    Attributes:
        version_id: The provider version's id.
        version_number: Its number.
        version_seq: The order it was recorded in (higher is later).
        contract_id: The ``provider_contract`` it published.
        contract_sha: The contract's content address.
        branches: The branches the version was recorded on.
        environments: The environments it is currently deployed to or released in.
    """

    version_id: str
    version_number: str
    version_seq: int
    contract_id: str
    contract_sha: str
    branches: Tuple[str, ...] = ()
    environments: Tuple[str, ...] = ()


@dataclass
class SelectedTarget:
    """A provider version a pact is compared with, and why.

    Attributes:
        target: The provider version.
        reasons: ``latest``, ``branch <name>`` and ``environment <name>``, in that order.
    """

    target: ContractTarget
    reasons: List[str] = field(default_factory=list)


def select_contract_targets(targets: Sequence[ContractTarget]) -> List[SelectedTarget]:
    """The provider versions a newly published pact is compared with.

    These are the versions can-i-deploy asks about: the head of each branch (a consumer deploying
    against ``main``, or a matching feature branch), and every version that runs somewhere.

    Args:
        targets: Every live provider version of the provider that published a contract.

    Returns:
        The latest version overall, the latest of each branch and every version deployed or
        released, each once, newest first.
    """
    by_id: Dict[str, SelectedTarget] = {}
    ordered = sorted(targets, key=lambda target: target.version_seq, reverse=True)

    def pick(target: ContractTarget, reason: str) -> None:
        selected = by_id.setdefault(target.version_id, SelectedTarget(target))
        if reason not in selected.reasons:
            selected.reasons.append(reason)

    if ordered:
        pick(ordered[0], "latest")
    heads: Dict[str, ContractTarget] = {}
    for target in ordered:
        for branch in target.branches:
            heads.setdefault(branch, target)
    for branch in sorted(heads):
        pick(heads[branch], f"branch {branch}")
    for target in ordered:
        for environment in target.environments:
            pick(target, f"environment {environment}")
    return sorted(by_id.values(), key=lambda selected: selected.target.version_seq, reverse=True)


# ---------------------------------------------------------------------------------------------
# What is stored
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class StoredComparison:
    """The fields of a bi-directional ``verification_result`` row.

    Attributes:
        success: Whether the provider contract contradicts nothing in the pact.
        verdict: ``pass``, ``partial`` or ``fail``.
        test_results: One Pact-shaped test result per interaction.
        payload: The comparison payload (the ``comparison`` column).
    """

    success: bool
    verdict: str
    test_results: List[Dict[str, Any]]
    payload: Dict[str, Any]


def _test_result(interaction: Dict[str, Any]) -> Dict[str, Any]:
    """One interaction's comparison as a Pact verifier's test result."""
    failures = interaction.get("failures") or []
    mismatches = [
        {
            "attribute": finding["code"],
            "description": finding["message"],
            "identifier": finding.get("pactPointer"),
        }
        for finding in failures[:_MAX_MISMATCHES]
    ]
    entry: Dict[str, Any] = {
        "interactionDescription": interaction.get("description"),
        "success": interaction.get("verdict") != VERDICT_FAIL,
        "verdict": interaction.get("verdict"),
    }
    if mismatches:
        entry["mismatches"] = mismatches
    return entry


def stored_comparison(result: ComparisonResult, *, contract_sha: str) -> StoredComparison:
    """What a comparison is stored as.

    Args:
        result: The comparison of the pact with the provider contract.
        contract_sha: The provider contract's content address, recorded in the payload.

    Returns:
        The row's fields. ``success`` is ``False`` only for a ``fail`` verdict: a ``partial`` one
        passes, and its fidelity notes stay in the payload for a reader to see.
    """
    payload = result.to_dict()
    payload["providerContractSha"] = contract_sha
    return StoredComparison(
        success=result.success,
        verdict=result.verdict,
        test_results=[_test_result(interaction) for interaction in payload["interactions"]],
        payload=payload,
    )


def error_comparison(message: str, *, contract_sha: str) -> StoredComparison:
    """What is stored when the pair cannot be compared at all.

    The pact and the contract never change, so comparing them again would fail again: the failure
    is stored, with its reason, rather than leaving the pair without a result.

    Args:
        message: Why the comparison could not run.
        contract_sha: The provider contract's content address.

    Returns:
        A failed result whose payload carries ``error``.
    """
    payload: Dict[str, Any] = {
        "verdict": VERDICT_FAIL,
        "success": False,
        "error": {"code": CODE_NOT_COMPARABLE, "message": message},
        "providerContractSha": contract_sha,
        "summary": {"interactions": 0, "passed": 0, "partial": 0, "failed": 0, "failures": 0},
        "interactions": [],
    }
    test_result = {
        "interactionDescription": None,
        "success": False,
        "mismatches": [{"attribute": CODE_NOT_COMPARABLE, "description": message}],
    }
    return StoredComparison(success=False, verdict=VERDICT_FAIL, test_results=[test_result], payload=payload)


# ---------------------------------------------------------------------------------------------
# What the caller is told
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RunEntry:
    """One pair of a comparison run.

    Attributes:
        consumer: The consumer's display name.
        consumer_version: The consumer version the pact is named after.
        provider: The provider's display name.
        provider_version: The provider version whose contract was compared.
        sha: The pact version.
        status: :data:`STATUS_COMPARED`, :data:`STATUS_ALREADY_COMPARED`, :data:`STATUS_ERROR` or
            :data:`STATUS_SKIPPED`.
        verdict: ``pass``, ``partial`` or ``fail`` for a compared pair.
        number: The stored result's number within its pact version.
        reason: Why a pair was not compared, or why it was selected.
    """

    consumer: str
    consumer_version: Optional[str]
    provider: str
    provider_version: str
    sha: str
    status: str
    verdict: Optional[str] = None
    number: Optional[int] = None
    reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for an API response (camelCase, unset fields left out)."""
        payload = {
            "consumer": self.consumer,
            "consumerVersion": self.consumer_version,
            "provider": self.provider,
            "providerVersion": self.provider_version,
            "pactVersionSha": self.sha,
            "status": self.status,
            "verdict": self.verdict,
            "verificationNumber": self.number,
            "reason": self.reason,
        }
        return {key: value for key, value in payload.items() if value is not None}


@dataclass
class ComparisonRun:
    """Everything one publish compared, or did not.

    Attributes:
        entries: One entry per pair, in the order they were considered.
    """

    entries: List[RunEntry] = field(default_factory=list)

    def count(self, status: str) -> int:
        """How many entries have ``status``."""
        return sum(1 for entry in self.entries if entry.status == status)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for an API response: the counts per status, and every entry."""
        return {
            "compared": self.count(STATUS_COMPARED),
            "alreadyCompared": self.count(STATUS_ALREADY_COMPARED),
            "errors": self.count(STATUS_ERROR),
            "skipped": self.count(STATUS_SKIPPED),
            "results": [entry.to_dict() for entry in self.entries],
        }


def _pair(entry: RunEntry) -> str:
    """``the pact between Billing Service 2.0.0 and the provider contract of Ledger API 5.1.0``."""
    consumer = f"{entry.consumer} {entry.consumer_version}" if entry.consumer_version else entry.consumer
    return f"the pact between {consumer} and the provider contract of {entry.provider} {entry.provider_version}"


def run_notices(run: ComparisonRun) -> List[Dict[str, str]]:
    """Pact Broker ``notices`` for a run, for the publish response ``pact-broker publish`` prints.

    Args:
        run: The run.

    Returns:
        One notice per pair that was compared, could not be stored or was skipped. Pairs already
        compared are only counted, so a republish stays quiet.
    """
    notices: List[Dict[str, str]] = []
    for entry in run.entries:
        if entry.status == STATUS_COMPARED:
            kind = "success" if entry.verdict != VERDICT_FAIL else "error"
            notices.append({"type": kind, "text": f"Bi-directional comparison of {_pair(entry)}: {entry.verdict}."})
        elif entry.status == STATUS_ERROR:
            notices.append(
                {
                    "type": "warning",
                    "text": f"Bi-directional comparison of {_pair(entry)} failed to run: {entry.reason}.",
                }
            )
        elif entry.status == STATUS_SKIPPED:
            notices.append({"type": "warning", "text": f"Not compared: {_pair(entry)} ({entry.reason})."})
    return notices
