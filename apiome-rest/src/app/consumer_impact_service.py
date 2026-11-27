"""CTG-4.2 consumer-aware analysis, wired to the registry (#4480).

:mod:`app.consumer_impact` is pure — it knows how to intersect a classified diff with declared
surfaces but not where surfaces live. This module is the one seam that loads them, so callers
(the classified-diff endpoint today, the CTG-4.5 deploy gate next) do not each re-implement the
"read every current contract in the project" step.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Sequence

from .change_taxonomy import ClassifiedDiff
from .consumer_contract_store import list_consumer_summaries
from .consumer_contract import SOURCE_PACT, ConsumerSummary
from .consumer_impact import ConsumerBroker, ConsumerImpactReport, analyze_consumer_impact
from .database import db

__all__ = ["broker_backing_for", "consumer_impact_for_diff"]


def broker_backing_for(
    tenant_id: str, summaries: Sequence[ConsumerSummary]
) -> Dict[str, ConsumerBroker]:
    """Which consumers are backed by a Pact Broker pacticipant (PFX-7.4, #6964).

    One tenant-scoped query reads the live pacticipants bound to these consumers; a consumer with
    none (registered by hand) is simply absent from the result. The contract's own provenance
    says whether its surface came from a published pact and which one.

    Args:
        tenant_id: The caller's tenant; pacticipants of other tenants are never read.
        summaries: The project's consumers with their current contracts.

    Returns:
        Consumer id → :class:`ConsumerBroker`.
    """
    ids = [s.consumer.id for s in summaries]
    if not ids:
        return {}
    rows: Sequence[Any] = db.execute_query(
        """
        SELECT consumer_id::text AS consumer_id, slug
        FROM apiome.pacticipant
        WHERE tenant_id = %s::uuid AND consumer_id = ANY(%s::uuid[]) AND deleted_at IS NULL
        ORDER BY slug
        """,
        (tenant_id, ids),
    )
    handles: Dict[str, str] = {}
    for row in rows:
        # Several pacticipants bound to one consumer: the first handle is the stable choice.
        handles.setdefault(str(row["consumer_id"]), str(row["slug"]))
    backing: Dict[str, ConsumerBroker] = {}
    for summary in summaries:
        handle = handles.get(summary.consumer.id)
        if handle is None:
            continue
        contract = summary.contract
        from_pact = bool(contract and contract.source == SOURCE_PACT)
        meta = contract.source_metadata if contract and from_pact else {}
        backing[summary.consumer.id] = ConsumerBroker(
            pacticipant=handle,
            from_pact=from_pact,
            consumer_version=(str(meta["consumer_version"]) if meta.get("consumer_version") else None),
            pact_sha=(str(meta["pact_sha"]) if meta.get("pact_sha") else None),
        )
    return backing


def consumer_impact_for_diff(
    tenant_id: str,
    project_id: str,
    diff: ClassifiedDiff,
    *,
    base_version_id: Optional[str] = None,
) -> ConsumerImpactReport:
    """Per-consumer verdicts for a classified diff against a project's registered consumers.

    Every live consumer is loaded, not only the ones a change touches: the "breaks 2 of 7"
    denominator is the whole registry, and a consumer that turns out to be unaffected is a
    result worth showing rather than an absence.

    Args:
        tenant_id: The caller's tenant.
        project_id: The project whose consumers to judge — the **base** side of the diff, since
            that is the published contract consumers registered against.
        diff: The CTG-1.1 classification of the base→head pair.
        base_version_id: Revision id of the base side, when known, so each verdict can say
            whether the consumer's surface was resolved against that same revision.

    Returns:
        The report, with one verdict per live consumer.
    """
    summaries = list_consumer_summaries(tenant_id, project_id)
    return analyze_consumer_impact(
        diff,
        summaries,
        base_version_id=base_version_id,
        brokers=broker_backing_for(tenant_id, summaries),
    )
