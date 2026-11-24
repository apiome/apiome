"""The provider's verification history the pending rule reads — PFX-1.7 (#6920).

:func:`load_pending_evidence` reads, in two statements, what :func:`app.pact_pending.pact_is_pending`
needs: each pact content's successful verifications by the provider (summarised per ``sha`` in
SQL, so a provider with thousands of results returns one row per content), and when the
verifying provider branch was first recorded.
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, Optional

from .pact_pending import PactSuccesses, PendingEvidence

__all__ = ["load_pending_evidence"]

#: One row per pact content the provider has verified successfully at least once. A result's
#: branches are the branch recorded on the result and every branch its provider version is on.
_SUCCESSES_SELECT = """
    SELECT pv.sha,
           MIN(r.created_at) AS first_success_at,
           COALESCE(array_agg(DISTINCT r.provider_branch) FILTER (WHERE r.provider_branch IS NOT NULL),
                    ARRAY[]::text[]) AS result_branches,
           COALESCE(array_agg(DISTINCT b.name) FILTER (WHERE b.name IS NOT NULL), ARRAY[]::text[]) AS version_branches,
           COALESCE(array_agg(DISTINCT t.name) FILTER (WHERE t.name IS NOT NULL), ARRAY[]::text[]) AS tags
    FROM apiome.verification_result r
    JOIN apiome.pact_version pv ON pv.id = r.pact_version_id
    LEFT JOIN apiome.pacticipant_branch_version bv
           ON bv.version_id = r.provider_version_id AND bv.pacticipant_id = r.provider_id
    LEFT JOIN apiome.pacticipant_branch b ON b.id = bv.branch_id AND b.pacticipant_id = bv.pacticipant_id
    LEFT JOIN apiome.pacticipant_version_tag t
           ON t.version_id = r.provider_version_id AND t.pacticipant_id = r.provider_id
    WHERE r.provider_id = %s::uuid AND r.tenant_id = %s::uuid AND r.success
      -- PFX-1.11: a deleted provider version's results no longer count.
      AND EXISTS (SELECT 1 FROM apiome.pacticipant_version lr
                  WHERE lr.id = r.provider_version_id AND lr.deleted_at IS NULL)
    GROUP BY pv.sha
"""

_BRANCH_CREATED_SELECT = """
    SELECT created_at FROM apiome.pacticipant_branch WHERE pacticipant_id = %s::uuid AND name = %s
"""


def _as_datetime(value: Any) -> Optional[datetime.datetime]:
    """A ``timestamptz`` column as a datetime (``None`` stays ``None``)."""
    if value is None or isinstance(value, datetime.datetime):
        return value
    return datetime.datetime.fromisoformat(str(value))


def load_pending_evidence(
    db: Any, tenant_id: str, provider_id: str, provider_version_branch: Optional[str]
) -> PendingEvidence:
    """Read a provider's successful verifications and its verifying branch's creation time.

    Args:
        db: The database.
        tenant_id: The caller's tenant (results of another tenant are never read).
        provider_id: The provider pacticipant's id.
        provider_version_branch: The request's ``providerVersionBranch``; when ``None`` the branch
            creation time is not read.

    Returns:
        The evidence for :func:`app.pact_pending.pact_is_pending`.
    """
    rows = db.execute_query(_SUCCESSES_SELECT, (provider_id, tenant_id)) or []
    successes: Dict[str, PactSuccesses] = {}
    for row in rows:
        successes[row["sha"]] = PactSuccesses(
            branches=frozenset(row.get("result_branches") or ()) | frozenset(row.get("version_branches") or ()),
            tags=frozenset(row.get("tags") or ()),
            first_success_at=_as_datetime(row.get("first_success_at")),
        )
    created_at = None
    if provider_version_branch:
        found = db.execute_query(_BRANCH_CREATED_SELECT, (provider_id, provider_version_branch)) or []
        if found:
            created_at = _as_datetime(found[0]["created_at"])
    return PendingEvidence(successes=successes, branch_created_at=created_at)
