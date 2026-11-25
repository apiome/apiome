"""Running bi-directional comparisons and storing them as verification results — PFX-2.3 (#6927).

:mod:`app.bidirectional_verification` says what a comparison is stored as; this module decides
which pairs to compare when one side publishes, runs :func:`app.pact_oas_compare.compare_pact_to_oas`
on each — or, for an AsyncAPI provider contract, :func:`app.pact_asyncapi_compare.compare_pact_to_asyncapi`
(PFX-3.6) — and writes the ``verification_result`` rows (``kind = bidirectional``, apiome-db V439).

**When a consumer publishes a pact** (:func:`compare_published_pacts`), each pact is compared with
the provider versions can-i-deploy will ask about: the latest provider version with a contract,
the head of each provider branch, and every provider version deployed or released
(:func:`app.bidirectional_verification.select_contract_targets`).

**When a provider publishes a contract** (:func:`compare_provider_contract`), the contract is
compared with the pacts a Pact verifier of that build would be given: the broker's default
selectors (each consumer's main branch, everything deployed or released), the latest pact of each
consumer on the provider version's branch, and — the *re-run* — every pact compared before with a
contract of that branch.

**One comparison per pair.** A pact version and a provider version are compared once: a pair
that already has a bi-directional result is reported as ``already-compared`` without reading
either document. The unique index of V439 settles a race between two publishes.

**A publish never fails because of a comparison.** The publish has committed when these run. Each
pair is written in its own transaction; a pair that cannot be written is logged and reported with
status ``error`` (no row, so can-i-deploy says "no verification result" for it). A pair that
cannot be *compared* — the engine refuses its inputs — is stored as a failed result with the
reason, since the same inputs would fail the same way again.

**Tenancy.** Pacticipants are resolved in the caller's tenant; every other id comes from those
rows, and the result row is tied to the pact, provider and contract by V434/V439's composite keys.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from psycopg2.extras import Json

from .bidirectional_verification import (
    ENGINE_NAME,
    KIND_BIDIRECTIONAL,
    MAX_CONTRACTS_PER_PACT,
    MAX_PACTS_PER_CONTRACT,
    STATUS_ALREADY_COMPARED,
    STATUS_COMPARED,
    STATUS_ERROR,
    STATUS_SKIPPED,
    ComparisonRun,
    ContractTarget,
    RunEntry,
    StoredComparison,
    apply_evidence_policy,
    error_comparison,
    select_contract_targets,
    stored_comparison,
)
from .config import settings
from .consumer_contract_store import ConsumerActor
from .pact_asyncapi_compare import compare_pact_to_asyncapi, is_asyncapi_document
from .pact_oas_compare import PactOasCompareError, compare_pact_to_oas
from .pact_publication_store import PublishOutcome, list_pact_candidates
from .pact_selectors import ConsumerVersionSelector, ForVerificationQuery, PactCandidate, select_verifiable_pacts
from .pacticipant import PacticipantRecord
from .pacticipant_store import get_pacticipant
from .provider_contract_evidence import evidence_of
from .revision_deprecation import is_uuid_string

__all__ = [
    "compare_provider_contract",
    "compare_published_pacts",
    "list_contract_targets",
]

logger = logging.getLogger(__name__)

#: Every live provider version of a provider that published a contract, with its branches and the
#: environments it is deployed to or released in. %s: provider id.
_TARGETS_SELECT = """
    SELECT v.id::text AS version_id, v.number AS version_number, v.seq AS version_seq,
           c.id::text AS contract_id, c.sha,
           -- PFX-2.4: the evidence read at publish time; a publication from before then has none,
           -- and its results (with the report) are read again. Never the report of a newer one.
           CASE WHEN p.verification_results ? 'evidence'
                THEN jsonb_build_object('evidence', p.verification_results->'evidence')
                ELSE p.verification_results END AS verification_results,
           COALESCE(
               (SELECT array_agg(b.name ORDER BY b.name)
                FROM apiome.pacticipant_branch_version bv
                JOIN apiome.pacticipant_branch b ON b.id = bv.branch_id AND b.pacticipant_id = bv.pacticipant_id
                WHERE bv.version_id = v.id AND bv.pacticipant_id = v.pacticipant_id),
               ARRAY[]::text[]) AS branches,
           COALESCE(
               (SELECT array_agg(DISTINCT e.name::text ORDER BY e.name::text)
                FROM (SELECT d.environment_id, d.tenant_id FROM apiome.deployed_version d
                      WHERE d.version_id = v.id AND d.pacticipant_id = v.pacticipant_id AND d.currently_deployed
                      UNION ALL
                      SELECT r.environment_id, r.tenant_id FROM apiome.released_version r
                      WHERE r.version_id = v.id AND r.pacticipant_id = v.pacticipant_id AND r.currently_supported) s
                JOIN apiome.pact_environment e ON e.id = s.environment_id AND e.tenant_id = s.tenant_id),
               ARRAY[]::text[]) AS environments
    FROM apiome.provider_contract_publication p
    JOIN apiome.provider_contract c ON c.id = p.provider_contract_id AND c.provider_id = p.provider_id
    JOIN apiome.pacticipant_version v ON v.id = p.provider_version_id AND v.pacticipant_id = p.provider_id
    WHERE p.provider_id = %s::uuid AND v.deleted_at IS NULL
    ORDER BY v.seq
"""

#: The pact versions compared before with a contract of another provider version on one of these
#: branches — what a new contract on the branch is compared with again. %s: provider id, tenant
#: id, branch names, the new provider version's id.
_BRANCH_HISTORY_SELECT = """
    SELECT DISTINCT pv.consumer_id::text AS consumer_id, pv.sha
    FROM apiome.verification_result r
    JOIN apiome.pact_version pv ON pv.id = r.pact_version_id
    JOIN apiome.pacticipant_branch_version bv
      ON bv.version_id = r.provider_version_id AND bv.pacticipant_id = r.provider_id
    JOIN apiome.pacticipant_branch b ON b.id = bv.branch_id AND b.pacticipant_id = bv.pacticipant_id
    WHERE r.provider_id = %s::uuid AND r.tenant_id = %s::uuid AND r.kind = 'bidirectional'
      AND b.name = ANY(%s) AND r.provider_version_id <> %s::uuid
    LIMIT 1000
"""

_PACT_VERSION_SELECT = """
    SELECT id::text AS id FROM apiome.pact_version
    WHERE consumer_id = %s::uuid AND provider_id = %s::uuid AND sha = %s
"""

_EXISTING_SELECT = """
    SELECT number, success, comparison->>'verdict' AS verdict FROM apiome.verification_result
    WHERE pact_version_id = %s::uuid AND provider_version_id = %s::uuid AND kind = 'bidirectional'
"""

_INSERT = """
    INSERT INTO apiome.verification_result (
        tenant_id, consumer_id, provider_id, pact_version_id, provider_version_id, number,
        success, provider_branch, test_results, verified_by_implementation,
        kind, provider_contract_id, comparison, created_by, actor_label
    )
    VALUES (
        %s::uuid, %s::uuid, %s::uuid, %s::uuid, %s::uuid,
        (SELECT COALESCE(MAX(number), 0) + 1 FROM apiome.verification_result WHERE pact_version_id = %s::uuid),
        %s,
        (SELECT b.name FROM apiome.pacticipant_branch_version bv
         JOIN apiome.pacticipant_branch b ON b.id = bv.branch_id AND b.pacticipant_id = bv.pacticipant_id
         WHERE bv.version_id = %s::uuid AND bv.pacticipant_id = %s::uuid
         ORDER BY bv.created_at DESC, b.name LIMIT 1),
        %s, %s, %s, %s::uuid, %s, %s::uuid, %s
    )
    ON CONFLICT (pact_version_id, provider_version_id) WHERE kind = 'bidirectional' DO NOTHING
    RETURNING number
"""


def _user_id(actor: ConsumerActor) -> Optional[str]:
    """The actor's user id when it is a storable UUID, else ``None``."""
    return actor.user_id if actor.user_id and is_uuid_string(str(actor.user_id)) else None


def list_contract_targets(db: Any, provider_id: str) -> List[ContractTarget]:
    """Every live provider version of a provider that published a provider contract.

    Args:
        db: The database.
        provider_id: The provider pacticipant's id (already resolved in the caller's tenant).

    Returns:
        The versions, in the order they were recorded.
    """
    rows = db.execute_query(_TARGETS_SELECT, (provider_id,)) or []
    return [
        ContractTarget(
            version_id=row["version_id"],
            version_number=row["version_number"],
            version_seq=int(row["version_seq"]),
            contract_id=row["contract_id"],
            contract_sha=str(row["sha"]).strip(),
            branches=tuple(row.get("branches") or ()),
            environments=tuple(row.get("environments") or ()),
            evidence=evidence_of(
                _json_object(row.get("verification_results")), max_bytes=settings.pact_evidence_max_bytes
            ),
        )
        for row in rows
    ]


def _json_object(value: Any) -> Optional[Dict[str, Any]]:
    """A JSONB column as a dict (psycopg2 decodes it; a string is parsed), else ``None``."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    return value if isinstance(value, dict) else None


@dataclass(frozen=True)
class _Pact:
    """One pact version to compare, and how it is named in the run report."""

    consumer_id: str
    consumer_name: str
    consumer_version: Optional[str]
    sha: str


class _Documents:
    """Reads each pact and contract document at most once per run, and only when compared."""

    def __init__(self, db: Any) -> None:
        """Hold the database.

        Args:
            db: The database.
        """
        self._db = db
        self._pacts: Dict[str, Any] = {}
        self._contracts: Dict[str, Any] = {}

    def _one(self, cache: Dict[str, Any], key: str, sql: str) -> Any:
        if key not in cache:
            rows = self._db.execute_query(sql, (key,)) or []
            cache[key] = rows[0]["content"] if rows else None
        return cache[key]

    def pact(self, pact_version_id: str) -> Any:
        """The Pact document of a pact version."""
        return self._one(self._pacts, pact_version_id, "SELECT content FROM apiome.pact_version WHERE id = %s::uuid")

    def contract(self, contract_id: str) -> Any:
        """The OpenAPI or AsyncAPI document of a provider contract."""
        return self._one(
            self._contracts, contract_id, "SELECT content FROM apiome.provider_contract WHERE id = %s::uuid"
        )


def _compare(pact: Any, contract: Any, target: ContractTarget) -> StoredComparison:
    """Compare, turning an input the engine refuses into a stored failure with its reason.

    The result is weighed by the contract's self-verification evidence under the configured
    policy (PFX-2.4, ``APIOME_PACT_UNVERIFIED_PROVIDER_CONTRACT``).
    """
    try:
        # PFX-3.6: an AsyncAPI provider contract is compared with the pact's messages.
        compare = compare_pact_to_asyncapi if is_asyncapi_document(contract) else compare_pact_to_oas
        stored = stored_comparison(compare(pact, contract), contract_sha=target.contract_sha)
    except PactOasCompareError as exc:
        stored = error_comparison(str(exc), contract_sha=target.contract_sha)
    return apply_evidence_policy(stored, target.evidence, settings.pact_unverified_provider_contract)


def _compare_pair(
    db: Any,
    documents: _Documents,
    tenant_id: str,
    provider: PacticipantRecord,
    pact: _Pact,
    target: ContractTarget,
    actor: ConsumerActor,
) -> RunEntry:
    """Compare one pact version with one provider version's contract and store the result.

    Args:
        db: The database.
        documents: The run's document cache.
        tenant_id: The caller's tenant.
        provider: The provider.
        pact: The pact version.
        target: The provider version and its contract.
        actor: Who published (recorded on the result).

    Returns:
        The pair's entry in the run report. Never raises: a failure to store is logged and
        reported with status ``error``.
    """

    def entry(status: str, **fields: Any) -> RunEntry:
        return RunEntry(
            consumer=pact.consumer_name,
            consumer_version=pact.consumer_version,
            provider=provider.name,
            provider_version=target.version_number,
            sha=pact.sha,
            status=status,
            **fields,
        )

    try:
        found = db.execute_query(_PACT_VERSION_SELECT, (pact.consumer_id, provider.id, pact.sha)) or []
        if not found:
            return entry(STATUS_ERROR, reason="the pact version no longer exists")
        pact_version_id = found[0]["id"]
        existing = db.execute_query(_EXISTING_SELECT, (pact_version_id, target.version_id)) or []
        if existing:
            row = existing[0]
            return entry(
                STATUS_ALREADY_COMPARED,
                verdict=row.get("verdict"),
                number=int(row["number"]),
                success=row.get("success"),
            )
        stored = _compare(documents.pact(pact_version_id), documents.contract(target.contract_id), target)

        def work(cursor: Any) -> Optional[int]:
            # The row lock serialises numbering with native results published at the same time.
            cursor.execute("SELECT id FROM apiome.pact_version WHERE id = %s::uuid FOR UPDATE", (pact_version_id,))
            cursor.execute(
                _INSERT,
                (
                    tenant_id,
                    pact.consumer_id,
                    provider.id,
                    pact_version_id,
                    target.version_id,
                    pact_version_id,
                    stored.success,
                    target.version_id,
                    provider.id,
                    Json(stored.test_results),
                    ENGINE_NAME,
                    KIND_BIDIRECTIONAL,
                    target.contract_id,
                    Json(stored.payload),
                    _user_id(actor),
                    actor.label,
                ),
            )
            row = cursor.fetchone()
            return int(row["number"]) if row else None

        number = db._guarded_tx(work)
    except Exception as exc:  # noqa: BLE001 - a comparison never fails the publish that triggered it
        logger.exception(
            "bi-directional comparison: could not store pact %s against %s version %s",
            pact.sha,
            provider.slug,
            target.version_number,
        )
        return entry(STATUS_ERROR, reason=f"the result could not be stored ({type(exc).__name__})")
    if number is None:
        # Another publish stored this pair between the check and the insert.
        return entry(STATUS_ALREADY_COMPARED)
    return entry(STATUS_COMPARED, verdict=stored.verdict, number=number, success=stored.success)


def _skipped(provider: PacticipantRecord, pact: _Pact, target: ContractTarget, limit: int, what: str) -> RunEntry:
    """The report entry of a pair left out over the limit."""
    return RunEntry(
        consumer=pact.consumer_name,
        consumer_version=pact.consumer_version,
        provider=provider.name,
        provider_version=target.version_number,
        sha=pact.sha,
        status=STATUS_SKIPPED,
        reason=f"over the limit of {limit} {what} compared per publish",
    )


def compare_published_pacts(db: Any, tenant_id: str, outcome: PublishOutcome, *, actor: ConsumerActor) -> ComparisonRun:
    """Compare the pacts a consumer version just published with their providers' contracts.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        outcome: What the publish stored (it has committed).
        actor: Who published.

    Returns:
        The run: one entry per pact and provider version considered. Empty when no provider of
        the pacts has published a contract.
    """
    run = ComparisonRun()
    documents = _Documents(db)
    for published in outcome.pacts:
        record = published.pact
        try:
            provider = get_pacticipant(db, tenant_id, record.provider_slug)
            targets = select_contract_targets(list_contract_targets(db, provider.id))
        except Exception:  # noqa: BLE001 - never fail the publish
            logger.exception("bi-directional comparison: could not read the contracts of %s", record.provider_slug)
            continue
        pact = _Pact(outcome.consumer.id, outcome.consumer.name, record.consumer_version, record.sha)
        for position, selected in enumerate(targets):
            if position >= MAX_CONTRACTS_PER_PACT:
                run.entries.append(
                    _skipped(provider, pact, selected.target, MAX_CONTRACTS_PER_PACT, "provider versions")
                )
                continue
            run.entries.append(_compare_pair(db, documents, tenant_id, provider, pact, selected.target, actor))
    return run


def _pacts_for_contract(
    db: Any, tenant_id: str, provider: PacticipantRecord, target: ContractTarget, candidates: Sequence[PactCandidate]
) -> List[_Pact]:
    """The pact versions a new provider contract is compared with, in a stable order.

    The broker's default selectors, the latest pact of each consumer on the provider version's
    branches, and every pact compared before with a contract of one of those branches.
    """
    chosen: Dict[Tuple[str, str], PactCandidate] = {}

    def add(candidate: PactCandidate) -> None:
        key = (candidate.consumer_id, candidate.sha)
        current = chosen.get(key)
        if current is None or candidate.version_seq > current.version_seq:
            chosen[key] = candidate

    for pact in select_verifiable_pacts(candidates, ForVerificationQuery()):
        add(pact.candidate)
    if target.branches:
        branch_selectors = tuple(
            ConsumerVersionSelector(branch=branch, latest=True, matching_branch=True) for branch in target.branches
        )
        for pact in select_verifiable_pacts(candidates, ForVerificationQuery(selectors=branch_selectors)):
            add(pact.candidate)
        history = (
            db.execute_query(_BRANCH_HISTORY_SELECT, (provider.id, tenant_id, list(target.branches), target.version_id))
            or []
        )
        compared = {(row["consumer_id"], str(row["sha"]).strip()) for row in history}
        for candidate in candidates:
            if (candidate.consumer_id, candidate.sha) in compared:
                add(candidate)
    ordered = sorted(chosen.values(), key=lambda c: (c.consumer_name.casefold(), -c.version_seq, c.sha))
    return [_Pact(c.consumer_id, c.consumer_name, c.version_number, c.sha) for c in ordered]


def compare_provider_contract(
    db: Any, tenant_id: str, provider_ref: str, version_number: str, *, actor: ConsumerActor
) -> ComparisonRun:
    """Compare the contract a provider version just published with the pacts that need it.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        provider_ref: The provider's handle, id or name.
        version_number: The provider version that published the contract (it has committed).
        actor: Who published.

    Returns:
        The run: one entry per pact version considered. Empty when no consumer has a pact with
        the provider.
    """
    run = ComparisonRun()
    try:
        provider = get_pacticipant(db, tenant_id, provider_ref)
        target = next((t for t in list_contract_targets(db, provider.id) if t.version_number == version_number), None)
        if target is None:
            return run
        _, candidates = list_pact_candidates(db, tenant_id, provider.id)
        pacts = _pacts_for_contract(db, tenant_id, provider, target, candidates)
    except Exception:  # noqa: BLE001 - never fail the publish
        logger.exception("bi-directional comparison: could not select the pacts of %s", provider_ref)
        return run
    documents = _Documents(db)
    for position, pact in enumerate(pacts):
        if position >= MAX_PACTS_PER_CONTRACT:
            run.entries.append(_skipped(provider, pact, target, MAX_PACTS_PER_CONTRACT, "pacts"))
            continue
        run.entries.append(_compare_pair(db, documents, tenant_id, provider, pact, target, actor))
    return run
