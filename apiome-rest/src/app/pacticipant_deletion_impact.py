"""What deleting a pacticipant takes with it — PFX-8.10 (#7307).

The pacticipant page's **Delete** dialog spells the consequence out before anyone types the name
to confirm (``docs/mockups/DESIGN.md`` §8, destructive): how many versions, pacts and verification
results go, which providers lose a consumer (their can-i-deploy answers change), which consumers
lose a provider, and — the one thing that blocks the delete — which versions are deployed or
released right now. :func:`read_deletion_impact` reads all of it for one live pacticipant that
:func:`app.pacticipant_store.get_pacticipant` already resolved in the caller's tenant, so nothing
here can reach another tenant's rows.

The counts are what :func:`app.pact_cleanup_store.delete_pacticipant` hides: the live versions, and
the pacts and results that name the pacticipant on either side. Names are capped at
:data:`MAX_NAMES`; ``providers_total`` / ``consumers_total`` say how many there are in all.
"""

from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, ConfigDict, Field

from .pact_cleanup_store import _in_use_sql, tenant_grace_days
from .pacticipant import PacticipantRecord

__all__ = ["MAX_NAMES", "DeletionImpact", "read_deletion_impact"]

#: Most provider and consumer names one answer lists (the delete names at most 20 versions too).
MAX_NAMES = 20

#: The three counts, in one round trip. Parameters: the pacticipant id, six times.
_COUNTS_SQL = """
    SELECT
        (SELECT count(*) FROM apiome.pacticipant_version v
         WHERE v.pacticipant_id = %s::uuid AND v.deleted_at IS NULL) AS versions,
        (SELECT count(DISTINCT pp.pact_version_id)
         FROM apiome.pact_publication pp
         JOIN apiome.pacticipant_version cv ON cv.id = pp.consumer_version_id AND cv.pacticipant_id = pp.consumer_id
         WHERE (pp.consumer_id = %s::uuid OR pp.provider_id = %s::uuid) AND cv.deleted_at IS NULL) AS pacts,
        (SELECT count(*) FROM apiome.verification_result vr
         WHERE vr.provider_id = %s::uuid
            OR vr.pact_version_id IN (SELECT pp.pact_version_id FROM apiome.pact_publication pp
                                      WHERE pp.consumer_id = %s::uuid AND pp.provider_id <> %s::uuid)) AS results
"""

#: The live pacticipants on the other side of this one's pacts. ``{mine}`` / ``{theirs}`` are the
#: literal column names ``consumer_id`` / ``provider_id``, never request text.
_PARTNERS_SQL = """
    SELECT p.name, count(*) OVER () AS total
    FROM apiome.pacticipant p
    WHERE p.deleted_at IS NULL AND p.id <> %s::uuid
      AND p.id IN (SELECT pp.{theirs} FROM apiome.pact_publication pp
                   JOIN apiome.pacticipant_version cv
                     ON cv.id = pp.consumer_version_id AND cv.pacticipant_id = pp.consumer_id
                   WHERE pp.{mine} = %s::uuid AND cv.deleted_at IS NULL)
    ORDER BY p.slug
    LIMIT %s
"""


class DeletionImpact(BaseModel):
    """What deleting one pacticipant would take with it, and whether it may be deleted now.

    Attributes:
        slug: The pacticipant's handle.
        name: Its name.
        versions: Live versions that would be deleted.
        pacts: Distinct pacts naming it, as consumer or provider.
        verification_results: Verification results of those pacts.
        providers: Providers that would lose it as a consumer (at most :data:`MAX_NAMES`).
        providers_total: How many providers in all.
        consumers: Consumers that would lose it as a provider (at most :data:`MAX_NAMES`).
        consumers_total: How many consumers in all.
        in_use: Versions currently deployed or released (at most :data:`MAX_NAMES`).
        blocked: Whether the delete is refused now (a version is in use).
        grace_days: Days the delete can be undone before it is purged.
    """

    model_config = ConfigDict(extra="forbid")

    slug: str
    name: str
    versions: int = Field(description="Live versions that would be deleted.")
    pacts: int = Field(description="Distinct pacts naming it, as consumer or provider.")
    verification_results: int = Field(description="Verification results of those pacts.")
    providers: List[str] = Field(default_factory=list, description="Providers that lose it as a consumer.")
    providers_total: int = 0
    consumers: List[str] = Field(default_factory=list, description="Consumers that lose it as a provider.")
    consumers_total: int = 0
    in_use: List[str] = Field(
        default_factory=list, description="Versions deployed or released now; while any is, the delete is refused."
    )
    blocked: bool = Field(description="Whether the delete is refused now: record the undeployment first.")
    grace_days: int = Field(description="Days the delete can be undone (`POST …/restore`) before it is purged.")


def _partners(db: Any, pacticipant_id: str, *, mine: str, theirs: str) -> tuple[List[str], int]:
    """The names on the other side of the pacticipant's pacts, and how many there are.

    Args:
        db: The database.
        pacticipant_id: The pacticipant.
        mine: ``consumer_id`` or ``provider_id``: its side.
        theirs: The other side's column.

    Returns:
        Up to :data:`MAX_NAMES` names, by handle, and the total.
    """
    rows = db.execute_query(
        _PARTNERS_SQL.format(mine=mine, theirs=theirs), (pacticipant_id, pacticipant_id, MAX_NAMES)
    ) or []
    names = [str(row["name"]) for row in rows]
    return names, int(rows[0]["total"]) if rows else 0


def read_deletion_impact(db: Any, pacticipant: PacticipantRecord) -> DeletionImpact:
    """Read what deleting ``pacticipant`` would take with it.

    Args:
        db: The database.
        pacticipant: A live pacticipant, already resolved in the caller's tenant.

    Returns:
        The counts, the pacticipants that lose a partner, the versions in use, and the grace period.
    """
    pid = pacticipant.id
    counts: Dict[str, Any] = dict((db.execute_query(_COUNTS_SQL, (pid,) * 6) or [{}])[0])
    providers, providers_total = _partners(db, pid, mine="consumer_id", theirs="provider_id")
    consumers, consumers_total = _partners(db, pid, mine="provider_id", theirs="consumer_id")
    # The same test the delete itself applies, so the dialog and the refusal never disagree.
    in_use = [str(row["number"]) for row in db.execute_query(_in_use_sql("v.pacticipant_id = %s::uuid"), (pid,)) or []]
    return DeletionImpact(
        slug=pacticipant.slug,
        name=pacticipant.name,
        versions=int(counts.get("versions") or 0),
        pacts=int(counts.get("pacts") or 0),
        verification_results=int(counts.get("results") or 0),
        providers=providers,
        providers_total=providers_total,
        consumers=consumers,
        consumers_total=consumers_total,
        in_use=in_use,
        blocked=bool(in_use),
        grace_days=tenant_grace_days(db.execute_query, pacticipant.tenant_id),
    )
