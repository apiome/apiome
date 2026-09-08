"""CTG-4.2 consumer-aware analysis, wired to the registry (#4480).

:mod:`app.consumer_impact` is pure — it knows how to intersect a classified diff with declared
surfaces but not where surfaces live. This module is the one seam that loads them, so callers
(the classified-diff endpoint today, the CTG-4.5 deploy gate next) do not each re-implement the
"read every current contract in the project" step.
"""

from __future__ import annotations

from typing import Optional

from .change_taxonomy import ClassifiedDiff
from .consumer_contract_store import list_consumer_summaries
from .consumer_impact import ConsumerImpactReport, analyze_consumer_impact

__all__ = ["consumer_impact_for_diff"]


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
    return analyze_consumer_impact(diff, summaries, base_version_id=base_version_id)
