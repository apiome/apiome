"""Catalog facts — the reads — CDG-5.4 (#5982).

One small read per fact, each reusing the module that owns the data:

* ``owner.*`` — :func:`app.ownership_policy.owner_facts` (CDG-2.5);
* ``consumers.declared`` — live ``consumer`` rows of a Project or catalog item (CTG-4.1), or the
  projects an agent consumes (``catalog_agent_consumers``, CDG-5.2);
* ``dependencies.declared`` / ``deployment.known`` — current (not stale) ``catalog_edges`` (CDG-3.x);
* ``refresh.fresh`` — the entity's source last succeeded within twice its cadence: the repository
  (RAR-3) or connector (CDG-1.x) a Project or catalog item came from, an MCP server's discovery,
  a connector's runs, a gateway config's last sync;
* ``shadow.none`` — the CDG-1.6 shadow-API report, scoped to the connector (and environment);
* ``registry.level-set`` — the catalog item's schema-registry subjects (CDG-4.2);
* ``mcp.baseline-approved`` — the endpoint's live trust baseline (MCAT);
* ``agent.readiness`` — not assessed: ATQ-2 has not shipped.

Unknown data is ``not_assessed``; a fact the entity cannot have is ``not_applicable``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Sequence
from urllib.parse import quote

from .catalog_entities import EntityKind, entity_href
from .catalog_facts import (
    FACT_LABELS,
    CatalogFact,
    CatalogFactsOut,
    FactEvidence,
    FactStatus,
    count_status,
    facts_for_kind,
    freshness,
)
from .repository_refresh_cadence import resolve_refresh_interval

__all__ = ["CadenceSettings", "entity_name", "read_facts"]

#: Projects rows may be a Project or a catalog item in the graph and the owner tables.
_PROJECT_KINDS = ("project", "catalog_item")


class CadenceSettings:
    """The cadence defaults :func:`refresh.fresh <read_facts>` needs (from :mod:`app.config`).

    Attributes:
        refresh_default: Default connector / repository refresh interval, seconds.
        refresh_floor: Floor below which a refresh interval is clamped, seconds.
        mcp_default: Default MCP discovery cadence, seconds.
    """

    def __init__(self, refresh_default: int = 300, refresh_floor: int = 60, mcp_default: int = 3600) -> None:
        self.refresh_default = int(refresh_default)
        self.refresh_floor = int(refresh_floor)
        self.mcp_default = int(mcp_default)


def _fact(
    key: str, status: FactStatus, value: Any = None, detail: Optional[str] = None, evidence: Sequence[FactEvidence] = ()
) -> CatalogFact:
    """Build one fact with its label."""
    return CatalogFact(
        key=key, label=FACT_LABELS[key], status=status, value=value, detail=detail, evidence=list(evidence)
    )


def _when(value: Any) -> str:
    """A timestamp as a date-time string for a detail line."""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M UTC")
    return str(value) if value else "never"


def _duration(seconds: int) -> str:
    """``5 min`` / ``2 h`` / ``1 d``."""
    if seconds % 86400 == 0:
        return f"{seconds // 86400} d"
    if seconds % 3600 == 0:
        return f"{seconds // 3600} h"
    if seconds % 60 == 0:
        return f"{seconds // 60} min"
    return f"{seconds} s"


def entity_name(db: Any, entry: EntityKind, tenant_id: str, entity_id: str) -> Optional[str]:
    """The live entity's name, or ``None`` when there is none (wrong tenant, deleted, not this kind)."""
    rows = db.execute_query(
        f"SELECT e.name FROM {entry.table} e WHERE e.tenant_id = %s::uuid AND e.id = %s::uuid AND {entry.live_where}",
        (tenant_id, entity_id),
    )
    return str(rows[0]["name"]) if rows else None


# ---------------------------------------------------------------------------------------------
# One function per fact
# ---------------------------------------------------------------------------------------------


def _owner(db: Any, entry: EntityKind, tenant_id: str, entity_id: str, base: str) -> List[CatalogFact]:
    """``owner.present`` and ``owner.contactable``."""
    from .ownership_policy import owner_facts

    facts = owner_facts(tenant_id, entry.owner_kind or entry.key, entity_id)
    api = f"/v1/tenants/{tenant_id}/owners/{entry.owner_kind}/{entity_id}"
    evidence = [FactEvidence(label="Owner", href=base, api=api)]
    present = facts["owner.present"]
    return [
        _fact(
            "owner.present",
            "met" if present else "unmet",
            present,
            None if present else "No confirmed owner team.",
            evidence,
        ),
        _fact(
            "owner.contactable",
            "met" if facts["owner.contactable"] else ("unmet" if present else "not_applicable"),
            facts["owner.contactable"],
            "The owner team has an on-call or chat link."
            if facts["owner.contactable"]
            else ("The owner team has no on-call or chat link." if present else "No owner team to contact."),
            evidence,
        ),
    ]


def _consumers(db: Any, entry: EntityKind, tenant_id: str, entity_id: str) -> CatalogFact:
    """``consumers.declared``: live consumers of an API, or the APIs an agent consumes."""
    if entry.key == "agent":
        rows = db.execute_query(
            "SELECT count(*) AS n FROM apiome.catalog_agent_consumers "
            "WHERE agent_id = %s::uuid AND tenant_id = %s::uuid",
            (entity_id, tenant_id),
        )
        count = int(rows[0]["n"]) if rows else 0
        return _fact(
            "consumers.declared",
            count_status(count),
            count,
            f"Consumes {count} API{'s' if count != 1 else ''} through its keys.",
            [FactEvidence(label="Agent", href=entity_href(entry, entity_id, None))],
        )
    rows = db.execute_query(
        "SELECT count(*) AS n FROM apiome.consumer "
        "WHERE tenant_id = %s::uuid AND project_id = %s::uuid AND deleted_at IS NULL",
        (tenant_id, entity_id),
    )
    count = int(rows[0]["n"]) if rows else 0
    return _fact(
        "consumers.declared",
        count_status(count),
        count,
        f"{count} consumer{'s' if count != 1 else ''} registered.",
        [FactEvidence(label="Consumers", api=f"/v1/tenants/{tenant_id}/projects/{entity_id}/consumers")],
    )


def _edge_count(
    db: Any,
    tenant_id: str,
    kinds: Sequence[str],
    entity_id: str,
    edge_kind: str,
    *,
    direction: str,
    provenance: Optional[str] = None,
) -> int:
    """Current (not stale) edges of one kind from (``out``) or to (``in``) an entity."""
    end = "from" if direction == "out" else "to"
    sql = (
        f"SELECT count(*) AS n FROM apiome.catalog_edges WHERE tenant_id = %s::uuid AND {end}_kind = ANY(%s::text[]) "
        f"AND {end}_id = %s::uuid AND edge_kind = %s AND stale_since IS NULL"
    )
    params: List[Any] = [tenant_id, list(kinds), entity_id, edge_kind]
    if provenance:
        sql += " AND provenance = %s"
        params.append(provenance)
    rows = db.execute_query(sql, tuple(params))
    return int(rows[0]["n"]) if rows else 0


def _graph_kinds(entry: EntityKind) -> Sequence[str]:
    """The node kinds an entity of this kind may appear as."""
    if entry.graph_kind in _PROJECT_KINDS:
        return _PROJECT_KINDS
    return (entry.graph_kind,) if entry.graph_kind else ()


def _graph_api(tenant_id: str, entry: EntityKind, entity_id: str, tail: str) -> str:
    return f"/v1/graph/{tenant_id}/entities/{entry.graph_kind}/{entity_id}/{tail}"


def _dependencies(db: Any, entry: EntityKind, tenant_id: str, entity_id: str) -> CatalogFact:
    """``dependencies.declared``: current declared ``depends_on`` edges from the entity."""
    count = _edge_count(
        db, tenant_id, _graph_kinds(entry), entity_id, "depends_on", direction="out", provenance="declared"
    )
    return _fact(
        "dependencies.declared",
        count_status(count),
        count,
        f"{count} declared dependenc{'ies' if count != 1 else 'y'}.",
        [FactEvidence(label="Dependencies", api=_graph_api(tenant_id, entry, entity_id, "dependencies"))],
    )


def _deployment(db: Any, entry: EntityKind, tenant_id: str, entity_id: str) -> CatalogFact:
    """``deployment.known``: current ``deployed_on`` edges — from an API, or to a gateway config."""
    direction = "in" if entry.key == "gateway_config" else "out"
    count = _edge_count(db, tenant_id, _graph_kinds(entry), entity_id, "deployed_on", direction=direction)
    detail = (
        f"Serves {count} API{'s' if count != 1 else ''}."
        if direction == "in"
        else f"Deployed on {count} gateway environment{'s' if count != 1 else ''}."
    )
    return _fact(
        "deployment.known",
        count_status(count),
        count,
        detail,
        [
            FactEvidence(
                label="Graph",
                href=f"/ade/dashboard/graph?entity={quote(f'{entry.graph_kind}:{entity_id}')}",
                api=_graph_api(tenant_id, entry, entity_id, f"edges?direction={direction}&kind=deployed_on"),
            )
        ],
    )


def _api_freshness(
    db: Any, tenant_id: str, entity_id: str, cadence: CadenceSettings, now: Optional[datetime]
) -> CatalogFact:
    """``refresh.fresh`` for a Project or catalog item: any source fresh → met."""
    sources: List[Dict[str, Any]] = []
    for row in (
        db.execute_query(
            """
        SELECT r.id::text AS id, COALESCE(r.repository_full_name, r.clone_url_normalized) AS name,
               r.last_refreshed_at AS last_success, r.refresh_interval_seconds AS interval,
               r.auto_refresh_enabled AS auto, r.refresh_paused_at AS paused_at
        FROM apiome.repository_import_spec s
        JOIN apiome.tenant_repositories r ON r.id = s.repository_id AND r.deleted_at IS NULL
        WHERE s.tenant_id = %s::uuid AND s.project_id = %s::uuid
        """,
            (tenant_id, entity_id),
        )
        or []
    ):
        cadence_s = resolve_refresh_interval(
            row.get("interval"), floor_seconds=cadence.refresh_floor, default_seconds=cadence.refresh_default
        )
        paused = row.get("paused_at") is not None or row.get("auto") is False
        sources.append(
            {
                "label": f"Repository {row['name']}",
                "last": row.get("last_success"),
                "cadence": cadence_s,
                "paused": paused,
                "href": f"/ade/dashboard/repositories/{row['id']}",
            }
        )
    for row in (
        db.execute_query(
            """
        SELECT DISTINCT c.id::text AS id, c.name, c.status, c.refresh_interval_seconds AS interval,
               (SELECT max(COALESCE(j.finished_at, j.created_at)) FROM apiome.tenant_repository_refresh_jobs j
                 WHERE j.connector_id = c.id AND j.status = 'succeeded') AS last_success
        FROM apiome.catalog_connector_items i
        JOIN apiome.catalog_connectors c ON c.id = i.connector_id AND c.deleted_at IS NULL
        WHERE c.tenant_id = %s::uuid AND i.project_id = %s::uuid AND i.status IN ('imported', 'discovered')
        """,
            (tenant_id, entity_id),
        )
        or []
    ):
        cadence_s = max(int(row.get("interval") or cadence.refresh_default), cadence.refresh_floor)
        sources.append(
            {
                "label": f"Connector {row['name']}",
                "last": row.get("last_success"),
                "cadence": cadence_s,
                "paused": row.get("status") == "paused",
                "href": f"/ade/dashboard/connectors/{row['id']}",
            }
        )
    latest = db.execute_query(
        "SELECT max(created_at) AS at FROM apiome.versions WHERE project_id = %s::uuid AND deleted_at IS NULL",
        (entity_id,),
    )
    revision = f" Last revision {_when(latest[0]['at'])}." if latest and latest[0].get("at") else ""
    if not sources:
        return _fact(
            "refresh.fresh",
            "not_applicable",
            None,
            f"Imported once; no repository or connector refreshes it.{revision}",
        )
    evidence = [FactEvidence(label=s["label"], href=s["href"]) for s in sources]
    statuses = [freshness(s["last"], s["cadence"], now) for s in sources if not s["paused"]]
    lines = "; ".join(
        f"{s['label']} last refreshed {_when(s['last'])} (cadence {_duration(s['cadence'])}"
        f"{', paused' if s['paused'] else ''})"
        for s in sources
    )
    if "met" in statuses:
        return _fact("refresh.fresh", "met", True, f"{lines}.{revision}", evidence)
    if not statuses:
        return _fact("refresh.fresh", "not_assessed", None, f"Every source is paused: {lines}.{revision}", evidence)
    return _fact("refresh.fresh", "unmet", False, f"{lines}.{revision}", evidence)


def _connector_success(db: Any, connector_id: str) -> Optional[Dict[str, Any]]:
    """A connector's status, interval and last successful run."""
    rows = db.execute_query(
        """
        SELECT c.id::text AS id, c.name, c.kind, c.status, c.refresh_interval_seconds AS interval,
               (SELECT max(COALESCE(j.finished_at, j.created_at)) FROM apiome.tenant_repository_refresh_jobs j
                 WHERE j.connector_id = c.id AND j.status = 'succeeded') AS last_success
        FROM apiome.catalog_connectors c WHERE c.id = %s::uuid AND c.deleted_at IS NULL
        """,
        (connector_id,),
    )
    return dict(rows[0]) if rows else None


def _freshness(
    db: Any, entry: EntityKind, tenant_id: str, entity_id: str, cadence: CadenceSettings, now: Optional[datetime]
) -> CatalogFact:
    """``refresh.fresh`` for every kind that has a refreshing source."""
    if entry.key in ("api", "spec"):
        return _api_freshness(db, tenant_id, entity_id, cadence, now)
    if entry.key == "mcp_server":
        from .mcp_freshness_report import effective_discovery_cadence_seconds

        rows = db.execute_query(
            "SELECT last_discovered_at, discovery_cadence_seconds, enabled "
            "FROM apiome.mcp_endpoints WHERE id = %s::uuid",
            (entity_id,),
        )
        row = dict(rows[0]) if rows else {}
        cadence_s = effective_discovery_cadence_seconds(
            row.get("discovery_cadence_seconds"), default_cadence_seconds=cadence.mcp_default
        )
        detail = f"Last discovered {_when(row.get('last_discovered_at'))} (cadence {_duration(cadence_s)})."
        evidence = [FactEvidence(label="MCP server", href=f"/ade/dashboard/mcp/{entity_id}")]
        if row.get("enabled") is False:
            return _fact("refresh.fresh", "not_assessed", None, f"Discovery is disabled. {detail}", evidence)
        status = freshness(row.get("last_discovered_at"), cadence_s, now)
        return _fact("refresh.fresh", status, status == "met", detail, evidence)
    if entry.key in ("connector", "gateway_config"):
        last: Any = None
        if entry.key == "gateway_config":
            rows = db.execute_query(
                "SELECT connector_id::text AS connector_id, last_synced_at "
                "FROM apiome.catalog_gateway_configs WHERE id = %s::uuid",
                (entity_id,),
            )
            if not rows:
                return _fact("refresh.fresh", "not_assessed", None, "The gateway config was not found.")
            connector = _connector_success(db, rows[0]["connector_id"])
            last = rows[0].get("last_synced_at")
        else:
            connector = _connector_success(db, entity_id)
            last = connector.get("last_success") if connector else None
        if connector is None:
            return _fact("refresh.fresh", "not_assessed", None, "The connector was not found.")
        cadence_s = max(int(connector.get("interval") or cadence.refresh_default), cadence.refresh_floor)
        detail = f"Last synced {_when(last)} (cadence {_duration(cadence_s)})."
        evidence = [
            FactEvidence(
                label=f"Connector {connector['name']}",
                href=f"/ade/dashboard/connectors/{connector['id']}",
                api=f"/v1/tenants/{tenant_id}/refresh-runs",
            )
        ]
        if connector.get("status") == "paused":
            return _fact("refresh.fresh", "not_assessed", None, f"Scheduled syncs are paused. {detail}", evidence)
        status = freshness(last, cadence_s, now)
        return _fact("refresh.fresh", status, status == "met", detail, evidence)
    return _fact("refresh.fresh", "not_applicable")


def _shadow(db: Any, entry: EntityKind, tenant_id: str, entity_id: str) -> CatalogFact:
    """``shadow.none``: the shadow-API report for the connector (and environment) finds none."""
    from . import shadow_api_store
    from .shadow_api_report import build_shadow_report

    environment: Optional[str] = None
    connector_id = entity_id
    if entry.key == "gateway_config":
        rows = db.execute_query(
            "SELECT connector_id::text AS connector_id, environment "
            "FROM apiome.catalog_gateway_configs WHERE id = %s::uuid",
            (entity_id,),
        )
        if not rows:
            return _fact("shadow.none", "not_assessed", None, "The gateway config was not found.")
        connector_id, environment = rows[0]["connector_id"], rows[0].get("environment") or ""
    connectors = shadow_api_store.load_report_connectors(db, tenant_id, connector_id)
    if not connectors:
        return _fact("shadow.none", "not_applicable", None, "This connector does not list gateway APIs.")
    items = shadow_api_store.load_report_items(db, [connector_id], environment or None)
    if environment == "":
        # The '' environment is the items that report none (NULL in the inventory).
        items = [item for item in items if not item.get("environment")]
    report = build_shadow_report(
        connectors=connectors,
        items=items,
        entries=shadow_api_store.load_catalog_entries(db, tenant_id),
        connector_filter=connector_id,
        environment=environment or None,
    )
    evidence = [
        FactEvidence(
            label="Shadow APIs",
            href=f"/ade/dashboard/connectors/shadow?connector={connector_id}",
            api=f"/v1/tenants/{tenant_id}/shadow-report?connector={connector_id}",
        )
    ]
    if report.get("stale"):
        return _fact(
            "shadow.none",
            "not_assessed",
            None,
            "The inventory is stale: the connector's last sync failed or it never synced.",
            evidence,
        )
    count = int((report.get("summary") or {}).get("shadow", 0))
    return _fact(
        "shadow.none",
        "met" if count == 0 else "unmet",
        count == 0,
        f"{count} shadow API{'s' if count != 1 else ''}.",
        evidence,
    )


def _registry_level(db: Any, entry: EntityKind, tenant_id: str, entity_id: str) -> CatalogFact:
    """``registry.level-set``: every live subject the catalog item backs has its own level."""
    rows = (
        db.execute_query(
            "SELECT name, compatibility_level FROM apiome.schema_subjects "
            "WHERE tenant_id = %s::uuid AND project_id = %s::uuid AND deleted_at IS NULL ORDER BY name",
            (tenant_id, entity_id),
        )
        or []
    )
    evidence = [
        FactEvidence(
            label="Subjects",
            href=f"{entity_href(entry, entity_id, None)}?tab=subjects",
            api=f"/v1/tenants/{tenant_id}/schema-registry/subjects",
        )
    ]
    if not rows:
        return _fact(
            "registry.level-set", "not_applicable", None, "The item backs no schema-registry subject.", evidence
        )
    unset = [row["name"] for row in rows if not row.get("compatibility_level")]
    if unset:
        return _fact(
            "registry.level-set", "unmet", False, f"Using the workspace default: {', '.join(unset)}.", evidence
        )
    return _fact(
        "registry.level-set",
        "met",
        True,
        f"{len(rows)} subject{'s' if len(rows) != 1 else ''} with a level of its own.",
        evidence,
    )


def _mcp_baseline(db: Any, tenant_id: str, entity_id: str) -> CatalogFact:
    """``mcp.baseline-approved``: the endpoint has a live trust baseline."""
    baseline = db.get_active_mcp_trust_baseline(entity_id)
    evidence = [
        FactEvidence(
            label="MCP server",
            href=f"/ade/dashboard/mcp/{entity_id}",
            api=f"/v1/mcp/{tenant_id}/endpoints/{entity_id}/trust-baseline",
        )
    ]
    if not baseline:
        return _fact("mcp.baseline-approved", "unmet", False, "No trust baseline has been approved.", evidence)
    return _fact("mcp.baseline-approved", "met", True, f"Approved {_when(baseline.get('created_at'))}.", evidence)


def _agent_readiness() -> CatalogFact:
    """``agent.readiness``: not assessed until ATQ-2 ships."""
    return _fact("agent.readiness", "not_assessed", None, "Agent readiness (ATQ-2) is not available yet.")


# ---------------------------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------------------------


def read_facts(
    db: Any,
    entry: EntityKind,
    tenant_id: str,
    entity_id: str,
    name: str,
    *,
    cadence: CadenceSettings,
    now: Optional[datetime] = None,
) -> CatalogFactsOut:
    """Every fact that applies to one entity, in display order.

    Args:
        db: Database handle.
        entry: The entity's kind.
        tenant_id: The tenant (the entity is already known to be live in it).
        entity_id: The entity.
        name: Its name.
        cadence: Cadence defaults for ``refresh.fresh``.
        now: Clock override for tests.

    Returns:
        The facts, with ``score: null``.
    """
    keys = facts_for_kind(entry.key)
    base = entity_href(entry, entity_id, None)
    readers: Dict[str, Callable[[], Any]] = {
        "consumers.declared": lambda: _consumers(db, entry, tenant_id, entity_id),
        "dependencies.declared": lambda: _dependencies(db, entry, tenant_id, entity_id),
        "refresh.fresh": lambda: _freshness(db, entry, tenant_id, entity_id, cadence, now),
        "deployment.known": lambda: _deployment(db, entry, tenant_id, entity_id),
        "shadow.none": lambda: _shadow(db, entry, tenant_id, entity_id),
        "registry.level-set": lambda: _registry_level(db, entry, tenant_id, entity_id),
        "mcp.baseline-approved": lambda: _mcp_baseline(db, tenant_id, entity_id),
        "agent.readiness": _agent_readiness,
    }
    facts: List[CatalogFact] = []
    if "owner.present" in keys:
        facts.extend(_owner(db, entry, tenant_id, entity_id, base))
    for key in keys:
        if key in readers:
            facts.append(readers[key]())
    return CatalogFactsOut(kind=entry.key, id=entity_id, name=name, facts=facts)
