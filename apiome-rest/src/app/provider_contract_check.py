"""Check a provider contract before publishing it — PFX-8.6 (#7303).

The **Publish a provider contract** page asks, before anything is stored, *what would publishing
this contract for this provider version say about each consumer?* This module answers it:

* :func:`fetch_contract_url` reads a contract from a URL, once, through the SSRF-guarded client,
  so the page can show what was fetched and publish exactly those bytes;
* :func:`run_contract_check` selects the pacts a publish would compare the contract with and
  compares each one in memory (:func:`app.bidirectional_store.preview_provider_contract` — the
  same selection, comparison and evidence policy as a publish), then reports per consumer, the
  operations no compared pact uses, and whether the version already has a different contract
  (which a publish would refuse with ``409``).

Nothing is written. The route is :mod:`app.provider_contract_check_routes`.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from .bidirectional_store import UNPUBLISHED_VERSION_ID, PreviewEntry, preview_provider_contract
from .bidirectional_verification import ContractTarget
from .consumer_surface import SpecIndex
from .import_source import ImportSourceError
from .live_fetch import check_public_url, guarded_client, guarded_get
from .pacticipant import CODE_NOT_FOUND as CODE_PACTICIPANT_NOT_FOUND
from .pacticipant import PacticipantValidationError
from .pacticipant_store import get_pacticipant
from .provider_contract import (
    CODE_CONTRACT_NOT_FOUND,
    CODE_URL_UNREADABLE,
    CONTRACT_TYPE_ASYNCAPI,
    ProviderContractError,
    ProviderContractToStore,
    contract_type_of,
)
from .provider_contract_evidence import Evidence
from .provider_contract_store import get_provider_contract

__all__ = [
    "CODE_URL_UNREADABLE",
    "MAX_FAILURES_PER_PACT",
    "MAX_UNUSED_OPERATIONS",
    "CheckOutcome",
    "FetchedContract",
    "fetch_contract_url",
    "run_contract_check",
]

#: The failures listed per pact; the rest are counted in ``moreFailures``.
MAX_FAILURES_PER_PACT = 10

#: The unused operations listed; the rest are counted in ``coverage.unusedMore``.
MAX_UNUSED_OPERATIONS = 50

_ACCEPT = "application/yaml, application/json;q=0.9, text/yaml;q=0.8, */*;q=0.1"


@dataclass(frozen=True)
class FetchedContract:
    """A contract read from a URL.

    Attributes:
        url: The URL it was read from.
        raw: The bytes read.
    """

    url: str
    raw: bytes

    def to_dict(self) -> Dict[str, Any]:
        """``{url, bytes, content}`` — ``content`` base64, ready to publish inline."""
        return {"url": self.url, "bytes": len(self.raw), "content": base64.b64encode(self.raw).decode("ascii")}


def fetch_contract_url(url: str, *, max_bytes: int) -> FetchedContract:
    """Read a provider contract from a URL, once.

    Args:
        url: An ``http(s)`` URL; private and loopback addresses are refused (on every redirect too).
        max_bytes: The largest document accepted (``pact_max_bytes``).

    Returns:
        The bytes read.

    Raises:
        ProviderContractError: ``provider-contract-url-unreadable`` with the reason, pointer ``/contentUrl``.
    """
    try:
        check_public_url(url, what="the contract URL")
        with guarded_client() as client:
            text = guarded_get(client, url, accept=_ACCEPT, headers={}, what="contract", max_bytes=max_bytes)
    except (ImportSourceError, ValueError) as exc:
        raise ProviderContractError(CODE_URL_UNREADABLE, f"could not read {url}: {exc}", pointer="/contentUrl") from exc
    return FetchedContract(url=url, raw=text.encode("utf-8"))


@dataclass
class CheckOutcome:
    """What publishing the contract would do, without doing it.

    Attributes:
        provider: The provider's name as sent, or as registered when it exists.
        provider_exists: Whether the provider is registered yet.
        provider_version: The provider version the contract would be published for.
        contract: The contract as it would be stored.
        self_verification: The evidence document (``status``, ``providerContractVerified``, …).
        existing: The contract the version already published, when it has one.
        results: One entry per pact compared (or left out, with the reason).
        coverage: The operations the compared pacts use and the ones none does; ``None`` for AsyncAPI.
        coverage_reason: Why ``coverage`` is ``None``.
        fetched: The document read from ``contentUrl``, when one was sent.
    """

    provider: str
    provider_exists: bool
    provider_version: str
    contract: ProviderContractToStore
    self_verification: Dict[str, Any]
    existing: Optional[Dict[str, Any]] = None
    results: List[Dict[str, Any]] = field(default_factory=list)
    coverage: Optional[Dict[str, Any]] = None
    coverage_reason: Optional[str] = None
    fetched: Optional[FetchedContract] = None

    def summary(self) -> Dict[str, Any]:
        """The counts the page's aside shows.

        Returns:
            ``pacts`` (listed), ``compared``, ``compatible`` / ``incompatible`` (by ``success``),
            ``notCompared``, ``consumers`` (distinct), ``unverified`` (results whose verdict reads
            unverified) and ``publishable`` (false when the version has a different contract).
        """
        compared = [r for r in self.results if r.get("success") is not None]
        return {
            "pacts": len(self.results),
            "compared": len(compared),
            "compatible": sum(1 for r in compared if r["success"]),
            "incompatible": sum(1 for r in compared if not r["success"]),
            "notCompared": len(self.results) - len(compared),
            "consumers": len({r["consumer"] for r in self.results}),
            "unverified": sum(1 for r in compared if r.get("verdict") == "unverified"),
            "publishable": not (self.existing and not self.existing["sameContent"]),
        }

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for the response (camelCase)."""
        contract = self.contract
        is_async = contract_type_of(contract.document) == CONTRACT_TYPE_ASYNCAPI
        payload: Dict[str, Any] = {
            "provider": {"name": self.provider, "exists": self.provider_exists},
            "providerVersion": self.provider_version,
            "contract": {
                "contractType": CONTRACT_TYPE_ASYNCAPI if is_async else "oas",
                ("asyncapiVersion" if is_async else "oasVersion"): contract.oas_version,
                ("messageCount" if is_async else "operationCount"): contract.operation_count,
                "contentSha": contract.sha,
                "contentType": contract.content_type,
                "source": (
                    {
                        "kind": contract.source,
                        "project": contract.source_project_slug,
                        "version": contract.source_version_label,
                    }
                    if contract.source_project_slug is not None
                    else {"kind": contract.source}
                ),
            },
            "selfVerification": self.self_verification,
            "existing": self.existing,
            "summary": self.summary(),
            "results": self.results,
            "coverage": self.coverage,
        }
        if self.coverage_reason:
            payload["coverageReason"] = self.coverage_reason
        if self.fetched is not None:
            payload["fetched"] = self.fetched.to_dict()
        return payload


def _failures(payload: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], int]:
    """The first failures of a comparison, each with its interaction and operation, and how many more."""
    listed: List[Dict[str, Any]] = []
    total = 0
    for interaction in payload.get("interactions") or []:
        for failure in interaction.get("failures") or []:
            total += 1
            if len(listed) < MAX_FAILURES_PER_PACT:
                operation = interaction.get("operation") or {}
                listed.append(
                    {
                        "interaction": interaction.get("description"),
                        "operation": (
                            f"{str(operation.get('method', '')).upper()} {operation.get('path', '')}".strip() or None
                        ),
                        "code": failure.get("code"),
                        "message": failure.get("message"),
                    }
                )
    error = payload.get("error")
    if isinstance(error, dict) and total == 0:
        listed.append(
            {"interaction": None, "operation": None, "code": error.get("code"), "message": error.get("message")}
        )
        total = 1
    return listed, max(0, total - len(listed))


def _used_operations(payload: Dict[str, Any]) -> Set[Tuple[str, str]]:
    """The ``(method, path)`` of every operation a comparison matched an interaction to."""
    used: Set[Tuple[str, str]] = set()
    for interaction in payload.get("interactions") or []:
        operation = interaction.get("operation")
        if isinstance(operation, dict) and operation.get("path"):
            used.add((str(operation.get("method", "")).lower(), str(operation["path"])))
    return used


def _result(entry: PreviewEntry) -> Dict[str, Any]:
    """One pact's entry in the response."""
    result: Dict[str, Any] = {
        "consumer": entry.consumer,
        "consumerVersion": entry.consumer_version,
        "sha": entry.sha,
        "environments": list(entry.environments),
    }
    if entry.comparison is None:
        return {**result, "verdict": None, "success": None, "reason": entry.reason, "failures": [], "moreFailures": 0}
    payload = entry.comparison.payload
    failures, more = _failures(payload)
    summary = payload.get("summary") or {}
    return {
        **result,
        "verdict": entry.comparison.verdict,
        "comparisonVerdict": payload.get("comparisonVerdict", entry.comparison.verdict),
        "success": entry.comparison.success,
        "interactions": int(summary.get("interactions") or 0),
        "failures": failures,
        "moreFailures": more,
    }


def _coverage(document: Dict[str, Any], entries: Sequence[PreviewEntry]) -> Dict[str, Any]:
    """The contract's operations, and the ones no compared pact uses."""
    used: Set[Tuple[str, str]] = set()
    for entry in entries:
        if entry.comparison is not None:
            used |= _used_operations(entry.comparison.payload)
    operations = SpecIndex(document).operations()
    unused = [op for op in operations if (op.method.lower(), op.path) not in used]
    return {
        "operations": len(operations),
        "used": len(operations) - len(unused),
        "unused": [
            {
                "method": op.method.upper(),
                "path": op.path,
                "operationId": op.operation.get("operationId")
                if isinstance(op.operation.get("operationId"), str)
                else None,
            }
            for op in unused[:MAX_UNUSED_OPERATIONS]
        ],
        "unusedMore": max(0, len(unused) - MAX_UNUSED_OPERATIONS),
    }


def _existing(db: Any, tenant_id: str, provider: str, version: str, sha: str) -> Optional[Dict[str, Any]]:
    """The contract the version already published, or ``None``."""
    try:
        record = get_provider_contract(db, tenant_id, provider, version)
    except PacticipantValidationError:
        return None
    except ProviderContractError as exc:
        if exc.code == CODE_CONTRACT_NOT_FOUND:
            return None
        raise
    return {"contentSha": record.sha, "sameContent": record.sha == sha, "createdAt": record.created_at}


def run_contract_check(
    db: Any,
    tenant_id: str,
    *,
    provider_ref: str,
    provider_version: str,
    branch: Optional[str],
    contract: ProviderContractToStore,
    evidence: Evidence,
    self_verification: Dict[str, Any],
    fetched: Optional[FetchedContract] = None,
) -> CheckOutcome:
    """Say what publishing ``contract`` for ``provider_version`` would record, and store nothing.

    Args:
        db: The database.
        tenant_id: The caller's tenant; the provider, its pacts and its contracts are read in it only.
        provider_ref: The provider's name or handle. An unknown provider has no pacts yet.
        provider_version: The provider version the contract would be published for.
        branch: The branch the version would be recorded on (selects branch pacts, as a publish does).
        contract: The contract as it would be stored.
        evidence: Its self-verification evidence, as read.
        self_verification: The ``selfVerification`` document for the response.
        fetched: The document read from a URL, echoed back.

    Returns:
        The outcome.
    """
    outcome = CheckOutcome(
        provider=provider_ref,
        provider_exists=False,
        provider_version=provider_version,
        contract=contract,
        self_verification=self_verification,
        fetched=fetched,
    )
    try:
        provider = get_pacticipant(db, tenant_id, provider_ref)
    except PacticipantValidationError as exc:
        if exc.code != CODE_PACTICIPANT_NOT_FOUND:
            raise
        provider = None
    entries: List[PreviewEntry] = []
    if provider is not None:
        outcome.provider = provider.name
        outcome.provider_exists = True
        outcome.existing = _existing(db, tenant_id, provider.id, provider_version, contract.sha)
        target = ContractTarget(
            version_id=UNPUBLISHED_VERSION_ID,
            version_number=provider_version,
            version_seq=0,
            contract_id=UNPUBLISHED_VERSION_ID,
            contract_sha=contract.sha,
            branches=(branch,) if branch else (),
            evidence=evidence,
        )
        entries = preview_provider_contract(db, tenant_id, provider, target, contract.document)
    outcome.results = [_result(entry) for entry in entries]
    if contract_type_of(contract.document) == CONTRACT_TYPE_ASYNCAPI:
        outcome.coverage_reason = "operation coverage is worked out for OpenAPI contracts only"
    else:
        outcome.coverage = _coverage(contract.document, entries)
    return outcome
