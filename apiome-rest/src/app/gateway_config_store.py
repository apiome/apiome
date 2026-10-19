"""Gateway configs — refresh and reads — CDG-5.3 (#5981).

:func:`refresh_gateway_configs` runs at the end of every connector sync, before the CDG-3.1
``deployed_on`` edges are re-derived (which now point at these rows): it groups the connector's
live items (``imported`` or ``discovered``) by environment, keeps one ``catalog_gateway_configs``
row per environment — name, API count, posture and declared losses — and soft-deletes the
environments the sync no longer saw.

Posture is read from the served APIs' imported revisions (the canonical model the import built,
via :func:`app.export_source.load_export_source`), at most :data:`MAX_POSTURE_ITEMS` per
environment; an API whose model cannot be rebuilt is skipped, never fatal to the sync.
"""

from __future__ import annotations

import json
import logging
from collections import OrderedDict
from typing import Any, Dict, List, Mapping, Optional

from .entity_owners import owner_envelope_join, owner_ref_from_value
from .gateway_configs import (
    GATEWAY_DECLARED_LOSSES,
    GatewayConfigOut,
    GatewayConnectorRef,
    GatewayLoss,
    GatewayPosture,
    GatewayPushBack,
    GatewayServedApi,
    empty_posture,
    gateway_config_name,
    gateway_config_slug,
    merge_postures,
    posture_from_api,
    push_back,
)
from .revision_deprecation import is_uuid_string

logger = logging.getLogger(__name__)

#: Most served APIs whose models one environment's posture is read from, per sync.
MAX_POSTURE_ITEMS = 50

#: Items that are deployed in the environment (not gone, not ignored).
_LIVE_STATUSES = ("imported", "discovered")


def _posture_for(tenant_id: str, project_ids: List[str]) -> Dict[str, Any]:
    """Merge the posture of the served APIs' latest revisions; unreadable ones are skipped."""
    from .export_source import load_export_source

    postures = []
    for project_id in project_ids[:MAX_POSTURE_ITEMS]:
        try:
            postures.append(posture_from_api(load_export_source(tenant_id, project_id).api))
        except Exception:  # noqa: BLE001 - a broken revision must not fail the sync
            logger.info("gateway config posture: skipped project %s", project_id, exc_info=True)
    return merge_postures(postures) if postures else empty_posture()


def refresh_gateway_configs(db: Any, tenant_id: str, connector_id: str) -> int:
    """Keep one gateway config per environment of a connector; soft-delete vanished ones.

    Args:
        db: Database handle.
        tenant_id: The connector's tenant.
        connector_id: The connector that just synced.

    Returns:
        The number of live gateway configs the connector has afterwards.
    """
    connectors = db.execute_query(
        "SELECT id::text AS id, name, kind FROM apiome.catalog_connectors "
        "WHERE id = %s::uuid AND tenant_id = %s::uuid AND deleted_at IS NULL",
        (connector_id, tenant_id),
    )
    if not connectors:
        return 0
    connector = dict(connectors[0])
    items = db.execute_query(
        """
        SELECT COALESCE(i.environment, '') AS environment, i.project_id::text AS project_id
        FROM apiome.catalog_connector_items i
        WHERE i.connector_id = %s::uuid AND i.status IN ('imported', 'discovered')
        ORDER BY COALESCE(i.environment, ''), i.remote_id
        """,
        (connector_id,),
    )
    environments: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
    for row in items or []:
        entry = environments.setdefault(str(row["environment"]), {"count": 0, "projects": []})
        entry["count"] += 1
        if row.get("project_id") and row["project_id"] not in entry["projects"]:
            entry["projects"].append(row["project_id"])
    postures = {env: _posture_for(tenant_id, entry["projects"]) for env, entry in environments.items()}
    losses = json.dumps(list(GATEWAY_DECLARED_LOSSES))

    def work(cursor: Any) -> int:
        cursor.execute(
            "SELECT id::text AS id, environment FROM apiome.catalog_gateway_configs "
            "WHERE connector_id = %s::uuid AND deleted_at IS NULL",
            (connector_id,),
        )
        existing = {row["environment"]: row["id"] for row in cursor.fetchall() or []}
        cursor.execute(
            "SELECT slug FROM apiome.catalog_gateway_configs WHERE tenant_id = %s::uuid AND deleted_at IS NULL",
            (tenant_id,),
        )
        taken = {row["slug"] for row in cursor.fetchall() or []}
        for environment, entry in environments.items():
            name = gateway_config_name(connector["name"], environment)
            posture = json.dumps(postures[environment])
            if environment in existing:
                cursor.execute(
                    """
                    UPDATE apiome.catalog_gateway_configs
                    SET name = %s, flavor = %s, api_count = %s, posture = %s::jsonb, declared_losses = %s::jsonb,
                        last_synced_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s::uuid
                    """,
                    (name, connector["kind"], entry["count"], posture, losses, existing[environment]),
                )
            else:
                slug = gateway_config_slug(connector["name"], environment, taken)
                taken.add(slug)
                cursor.execute(
                    """
                    INSERT INTO apiome.catalog_gateway_configs
                        (tenant_id, connector_id, environment, slug, name, flavor, api_count, posture,
                         declared_losses, last_synced_at)
                    VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, CURRENT_TIMESTAMP)
                    """,
                    (
                        tenant_id,
                        connector_id,
                        environment,
                        slug,
                        name,
                        connector["kind"],
                        entry["count"],
                        posture,
                        losses,
                    ),
                )
        gone = [config_id for environment, config_id in existing.items() if environment not in environments]
        if gone:
            cursor.execute(
                "UPDATE apiome.catalog_gateway_configs SET deleted_at = CURRENT_TIMESTAMP WHERE id = ANY(%s::uuid[])",
                (gone,),
            )
        return len(environments)  # any non-None value commits

    return int(db._guarded_tx(work) or 0)


# ---------------------------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------------------------

_COLUMNS = """
    g.id::text AS id, g.slug, g.name, g.environment, g.flavor, g.api_count, g.posture,
    g.declared_losses, g.last_synced_at, g.updated_at,
    c.id::text AS connector_id, c.name AS connector_name, c.kind AS connector_kind
"""


def _out(row: Mapping[str, Any], apis: Optional[List[GatewayServedApi]] = None) -> GatewayConfigOut:
    """Build a :class:`GatewayConfigOut` from a joined row."""
    posture = row.get("posture") or {}
    return GatewayConfigOut(
        id=str(row["id"]),
        slug=row["slug"],
        name=row["name"],
        connector=GatewayConnectorRef(id=row["connector_id"], name=row["connector_name"], kind=row["connector_kind"]),
        environment=row.get("environment") or "",
        flavor=row["flavor"],
        api_count=int(row.get("api_count") or 0),
        posture=GatewayPosture(**{**empty_posture(), **posture}),
        declared_losses=[GatewayLoss(**loss) for loss in row.get("declared_losses") or []],
        push_back=GatewayPushBack(**push_back(row["connector_kind"])),
        owner=owner_ref_from_value(row.get("entity_owner")),
        apis=apis or [],
        last_synced_at=row.get("last_synced_at"),
        updated_at=row.get("updated_at"),
    )


def list_gateway_configs(db: Any, tenant_id: str, connector_id: Optional[str] = None) -> List[GatewayConfigOut]:
    """The tenant's live gateway configs (optionally one connector's), by name.

    Args:
        db: Database handle.
        tenant_id: The tenant.
        connector_id: Only this connector's environments.
    """
    connector = connector_id if connector_id and is_uuid_string(connector_id) else None
    rows = db.execute_query(
        f"""
        SELECT {_COLUMNS}, own.entity_owner
        FROM apiome.catalog_gateway_configs g
        JOIN apiome.catalog_connectors c ON c.id = g.connector_id AND c.deleted_at IS NULL
        {owner_envelope_join(("gateway_config",), "g.id", "g.tenant_id")}
        WHERE g.tenant_id = %s::uuid AND g.deleted_at IS NULL
          AND (%s::uuid IS NULL OR g.connector_id = %s::uuid)
        ORDER BY lower(g.name), g.id
        """,
        (tenant_id, connector, connector),
    )
    return [_out(dict(row)) for row in rows or []]


def get_gateway_config(db: Any, tenant_id: str, ref: str) -> Optional[GatewayConfigOut]:
    """One live gateway config, by slug or id, with the APIs it serves.

    Args:
        db: Database handle.
        tenant_id: The tenant.
        ref: The slug or id.

    Returns:
        The gateway config, or ``None`` when there is none.
    """
    rows = db.execute_query(
        f"""
        SELECT {_COLUMNS}, own.entity_owner
        FROM apiome.catalog_gateway_configs g
        JOIN apiome.catalog_connectors c ON c.id = g.connector_id AND c.deleted_at IS NULL
        {owner_envelope_join(("gateway_config",), "g.id", "g.tenant_id")}
        WHERE g.tenant_id = %s::uuid AND g.deleted_at IS NULL AND (g.slug = %s OR g.id::text = %s)
        ORDER BY (g.slug = %s) DESC
        LIMIT 1
        """,
        (tenant_id, ref, ref, ref),
    )
    if not rows:
        return None
    row = dict(rows[0])
    served = db.execute_query(
        """
        SELECT i.id::text AS item_id, COALESCE(i.remote_name, i.remote_id) AS name, i.remote_id, i.status,
               i.hosts, i.base_path, i.last_seen_at,
               p.id::text AS project_id, p.name AS project_name, p.publishable
        FROM apiome.catalog_connector_items i
        LEFT JOIN apiome.projects p ON p.id = i.project_id AND p.deleted_at IS NULL
        WHERE i.connector_id = %s::uuid AND COALESCE(i.environment, '') = %s
          AND i.status IN ('imported', 'discovered')
        ORDER BY lower(COALESCE(i.remote_name, i.remote_id)), i.id
        """,
        (row["connector_id"], row.get("environment") or ""),
    )
    apis = [GatewayServedApi(**{**dict(api), "hosts": list(api.get("hosts") or [])}) for api in served or []]
    return _out(row, apis)
