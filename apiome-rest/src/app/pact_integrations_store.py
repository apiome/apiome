"""The Contracts landing's integrations list — PFX-8.1 (#7298): the database half.

Reads, for the tenant's consumer ↔ provider pairs, the facts :func:`app.pact_integrations.classify`
turns into rows. Every statement is bounded:

1. **The pairs** (:data:`PAIRS_SQL`): for each live provider of the tenant, the consumers with a
   pact for it (``idx_pact_version_provider``), at most :data:`app.pact_integrations.MAX_INTEGRATIONS`
   pairs by consumer then provider name, each with its newest publication (the one whose consumer
   version was recorded last, as the health rollup reads it) and the number of pairs in all, so a
   capped read says how many it left out. It has a plan-check entry
   (``apiome-db/plan-check/hot-queries.json``, ``pact.integrations_pairs``).
2. **The newest result** of each listed pact version, with its kind and provider version.
3. **The pact versions the provider ever passed natively** (the pending rule, PFX-1.7).
4. **Which listed providers have a provider contract**, the sweep's **staleness** records, the
   **current deployments** of every listed pacticipant, and the caller's **owned** pacticipants.

Every query is scoped to the tenant; nothing is written.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, FrozenSet, List, Mapping, Optional, Set, Tuple
from uuid import UUID

from .pact_integrations import (
    MAX_INTEGRATIONS,
    IntegrationFacts,
    IntegrationsQuery,
    PactIntegrationsPage,
    build_page,
)

__all__ = ["PAIRS_SQL", "list_integrations"]

#: The pairs, capped, each with its newest publication. $1 tenant, $2 the cap.
PAIRS_SQL = """
    WITH pairs AS (
        SELECT pr.id AS provider_id, pr.slug AS provider_slug, pr.name AS provider_name,
               c.id AS consumer_id, c.slug AS consumer_slug, c.name AS consumer_name,
               count(*) OVER () AS pair_total
        FROM apiome.pacticipant pr
        CROSS JOIN LATERAL (
            -- A loose index scan over idx_pact_publication_pair: one probe per consumer, however
            -- many pacts the pair has.
            WITH RECURSIVE pc AS (
                (SELECT p.consumer_id FROM apiome.pact_publication p
                 WHERE p.provider_id = pr.id ORDER BY p.consumer_id LIMIT 1)
                UNION ALL
                SELECT (SELECT p.consumer_id FROM apiome.pact_publication p
                        WHERE p.provider_id = pr.id AND p.consumer_id > pc.consumer_id
                        ORDER BY p.consumer_id LIMIT 1)
                FROM pc WHERE pc.consumer_id IS NOT NULL
            )
            SELECT pc.consumer_id FROM pc WHERE pc.consumer_id IS NOT NULL
        ) pc
        JOIN apiome.pacticipant c
          ON c.id = pc.consumer_id AND c.tenant_id = pr.tenant_id AND c.deleted_at IS NULL
        WHERE pr.tenant_id = %s::uuid AND pr.deleted_at IS NULL
        ORDER BY lower(c.name), lower(pr.name), c.id, pr.id
        LIMIT %s
    )
    SELECT pairs.provider_id::text AS provider_id, pairs.provider_slug, pairs.provider_name,
           pairs.consumer_id::text AS consumer_id, pairs.consumer_slug, pairs.consumer_name,
           pairs.pair_total, newest.pact_version_id::text AS pact_version_id, newest.sha,
           newest.consumer_version, newest.published_at
    FROM pairs
    CROSS JOIN LATERAL (
        -- The consumer's versions newest first (idx_pacticipant_version_latest), each probed for a
        -- pact for this provider (pact_publication_version_provider_key): the first hit is the
        -- newest pact, without sorting the pair's whole history.
        SELECT p.pact_version_id, pv.sha, v.number AS consumer_version, p.created_at AS published_at
        FROM apiome.pacticipant_version v
        JOIN apiome.pact_publication p
          ON p.consumer_version_id = v.id AND p.consumer_id = v.pacticipant_id
         AND p.provider_id = pairs.provider_id
        JOIN apiome.pact_version pv ON pv.id = p.pact_version_id
        WHERE v.pacticipant_id = pairs.consumer_id AND v.deleted_at IS NULL
        ORDER BY v.seq DESC
        LIMIT 1
    ) newest
"""

_LATEST_SQL = """
    SELECT DISTINCT ON (r.pact_version_id)
           r.pact_version_id::text AS pact_version_id, r.success, r.kind, r.created_at,
           pv.number AS provider_version
    FROM apiome.verification_result r
    JOIN apiome.pacticipant_version pv ON pv.id = r.provider_version_id
    WHERE r.tenant_id = %s::uuid AND r.pact_version_id = ANY(%s::uuid[])
    ORDER BY r.pact_version_id, r.seq DESC
"""

_NATIVE_SUCCESS_SQL = """
    SELECT DISTINCT r.pact_version_id::text AS pact_version_id
    FROM apiome.verification_result r
    WHERE r.tenant_id = %s::uuid AND r.pact_version_id = ANY(%s::uuid[]) AND r.success AND r.kind = 'native'
"""

_CONTRACT_SQL = """
    SELECT DISTINCT pc.provider_id::text AS provider_id
    FROM apiome.provider_contract pc
    WHERE pc.tenant_id = %s::uuid AND pc.provider_id = ANY(%s::uuid[])
"""

_STALENESS_SQL = """
    SELECT provider_id::text AS provider_id, consumer_id::text AS consumer_id, sha, stale
    FROM apiome.pact_staleness
    WHERE tenant_id = %s::uuid AND provider_id = ANY(%s::uuid[])
"""

_DEPLOYED_SQL = """
    SELECT DISTINCT d.pacticipant_id::text AS pacticipant_id, e.name
    FROM apiome.deployed_version d
    JOIN apiome.pact_environment e ON e.id = d.environment_id AND e.tenant_id = d.tenant_id
    WHERE d.tenant_id = %s::uuid AND d.currently_deployed AND d.pacticipant_id = ANY(%s::uuid[])
"""

_OWNED_SQL = """
    SELECT DISTINCT eo.entity_id::text AS pacticipant_id
    FROM apiome.entity_owners eo
    JOIN apiome.team_members tm ON tm.team_id = eo.team_id
    WHERE eo.tenant_id = %s::uuid AND eo.entity_kind = 'pacticipant' AND eo.status = 'confirmed'
      AND tm.user_id = %s::uuid
"""

_COUNTS_SQL = """
    SELECT (SELECT count(*) FROM apiome.pacticipant WHERE tenant_id = %s::uuid AND deleted_at IS NULL) AS pacticipants,
           (SELECT count(*) FROM apiome.pact_environment WHERE tenant_id = %s::uuid) AS environments
"""


def _iso(value: Any) -> Optional[str]:
    """A stored instant as ISO 8601, or ``None``."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _rows(db: Any, sql: str, params: Tuple[Any, ...]) -> List[Mapping[str, Any]]:
    """Run a read and return its rows (an empty list for none)."""
    return list(db.execute_query(sql, params) or [])


def _environments(rows: List[Mapping[str, Any]]) -> Dict[str, FrozenSet[str]]:
    """The environments each pacticipant is deployed in now, by pacticipant id."""
    found: Dict[str, Set[str]] = {}
    for row in rows:
        found.setdefault(row["pacticipant_id"], set()).add(str(row["name"]))
    return {key: frozenset(names) for key, names in found.items()}


def _is_uuid(value: str) -> bool:
    """Whether a value parses as a UUID (an API-key principal's id may not)."""
    try:
        UUID(str(value))
    except ValueError:
        return False
    return True


def _owned(db: Any, tenant_id: str, user_id: Optional[str]) -> FrozenSet[str]:
    """The pacticipant ids a team of the user owns (none without a user)."""
    if not user_id or not _is_uuid(user_id):
        return frozenset()
    return frozenset(row["pacticipant_id"] for row in _rows(db, _OWNED_SQL, (tenant_id, user_id)))


def _facts(db: Any, tenant_id: str, pairs: List[Mapping[str, Any]]) -> List[IntegrationFacts]:
    """Read everything the classifier needs about the listed pairs."""
    version_ids = [row["pact_version_id"] for row in pairs]
    provider_ids = sorted({row["provider_id"] for row in pairs})
    pacticipant_ids = sorted(set(provider_ids) | {row["consumer_id"] for row in pairs})
    latest = {row["pact_version_id"]: row for row in _rows(db, _LATEST_SQL, (tenant_id, version_ids))}
    passed = {row["pact_version_id"] for row in _rows(db, _NATIVE_SUCCESS_SQL, (tenant_id, version_ids))}
    contracts = {row["provider_id"] for row in _rows(db, _CONTRACT_SQL, (tenant_id, provider_ids))}
    stale = {
        (row["provider_id"], row["consumer_id"]): (str(row["sha"]), bool(row["stale"]))
        for row in _rows(db, _STALENESS_SQL, (tenant_id, provider_ids))
    }
    deployed = _environments(_rows(db, _DEPLOYED_SQL, (tenant_id, pacticipant_ids)))
    facts: List[IntegrationFacts] = []
    for row in pairs:
        verdict = latest.get(row["pact_version_id"])
        sha = str(row["sha"])
        swept = stale.get((row["provider_id"], row["consumer_id"]))
        facts.append(
            IntegrationFacts(
                provider=row["provider_slug"],
                provider_name=row["provider_name"],
                consumer=row["consumer_slug"],
                consumer_name=row["consumer_name"],
                provider_id=row["provider_id"],
                consumer_id=row["consumer_id"],
                consumer_version=str(row["consumer_version"]),
                pact_version_sha=sha,
                published_at=_iso(row.get("published_at")),
                latest_success=bool(verdict["success"]) if verdict else None,
                latest_kind=str(verdict["kind"]) if verdict else None,
                latest_at=_iso(verdict.get("created_at")) if verdict else None,
                provider_version=str(verdict["provider_version"]) if verdict else None,
                provider_has_contract=row["provider_id"] in contracts,
                native_success=row["pact_version_id"] in passed,
                # The sweep's record counts only while it is about the pair's newest content.
                stale=bool(swept and swept[1] and swept[0] == sha),
                consumer_environments=deployed.get(row["consumer_id"], frozenset()),
                provider_environments=deployed.get(row["provider_id"], frozenset()),
            )
        )
    return facts


def list_integrations(
    db: Any,
    tenant_id: str,
    query: IntegrationsQuery,
    *,
    user_id: Optional[str] = None,
    cap: int = MAX_INTEGRATIONS,
) -> PactIntegrationsPage:
    """The tenant's integrations, classified, counted, filtered and paged.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        query: The checked query (:func:`app.pact_integrations.parse_query`).
        user_id: The caller's user id, for the ``mine`` filter (``None`` for a credential with no user).
        cap: The most pairs read (tests lower it).

    Returns:
        The page.
    """
    pairs = _rows(db, PAIRS_SQL, (tenant_id, cap))
    counts = _rows(db, _COUNTS_SQL, (tenant_id, tenant_id))
    pacticipants = int(counts[0]["pacticipants"] or 0) if counts else 0
    environments = int(counts[0]["environments"] or 0) if counts else 0
    total = int(pairs[0]["pair_total"] or 0) if pairs else 0
    facts = _facts(db, tenant_id, pairs) if pairs else []
    return build_page(
        facts,
        query,
        owned=_owned(db, tenant_id, user_id),
        pacticipants=pacticipants,
        environments=environments,
        omitted=max(0, total - cap),
        mine_available=bool(user_id) and _is_uuid(str(user_id)),
    )
