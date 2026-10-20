"""The unified catalog entity list — CDG-5.1 (#5979).

Two routes over the kind registry (:mod:`app.catalog_entities`), under ``/v1/catalog``:

* ``GET /{tenant_slug}/entities?kind=&team=&q=&cursor=&limit=`` — one page of entities of every kind
  (or the kinds asked for), each in the common envelope with a ``kind`` discriminator and its owner;
* ``GET /{tenant_slug}/entities/summary?team=&q=`` — the count of every kind (the catalog home's Kind
  facet and tiles) and the home callouts: **unowned**, **stale** (not refreshed within cadence × 2)
  and **shadow** (the shadow-API report's count).

A kind is listed only when the caller may ``view`` its RBAC resource; the others are left out of
the list and the counts rather than refusing the whole request. ``…/entities/{kind}/{id}/facts`` returns
one entity's catalog facts (CDG-5.4).

This router is included before :mod:`app.catalog_routes`, whose ``/{tenant_slug}/{item_id}`` would
otherwise read ``entities`` as an item id.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from . import catalog_entity_store as store
from . import shadow_api_store
from .auth import validate_authentication
from .catalog_entities import EntityKind, EntityKindError, entity_href, kind, parse_kinds
from .catalog_fact_store import CadenceSettings, entity_name, read_facts
from .catalog_facts import CatalogFactsOut
from .database import db
from .entity_owners import EntityOwnerRef, owner_ref_from_value
from .permissions import Action, Resource, has_permission
from .revision_deprecation import is_uuid_string
from .shadow_api_report import build_shadow_report

router = APIRouter(prefix="/v1/catalog", tags=["catalog-entities"])

#: Default and largest page size.
DEFAULT_LIMIT = 50
MAX_LIMIT = 200


class _CamelModel(BaseModel):
    """Wire base: snake_case fields, camelCase JSON."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class GraphNodeRef(_CamelModel):
    """Where the entity sits in the dependency graph."""

    kind: str = Field(description="The graph node kind (`project`, `catalog_item`, `mcp_endpoint`, …).")
    id: str


class CatalogEntity(_CamelModel):
    """One entity in the common envelope."""

    kind: str = Field(
        description="The registry kind: `api`, `spec`, `mcp_server`, `consumer`, `connector`, `agent`, `model`, "
        "`gateway_config`, `component` or `team`."
    )
    id: str
    slug: Optional[str] = Field(default=None, description="`null` for a kind without slugs (connectors).")
    name: str
    description: Optional[str] = None
    owner: Optional[EntityOwnerRef] = Field(
        default=None, description="The confirmed owner team, else the first suggestion; `null` for none or for teams."
    )
    updated_at: Optional[datetime] = None
    href: str = Field(description="The UI page that renders the entity.")
    graph_node: Optional[GraphNodeRef] = Field(default=None, description="`null` for a kind that is not a graph node.")


class EntityPagination(_CamelModel):
    """Paging state."""

    next_cursor: Optional[str] = Field(
        default=None, description="Pass as `cursor` for the next page; `null` on the last."
    )


class CatalogEntityPage(_CamelModel):
    """One page of entities, ordered by name, then kind, then id."""

    items: List[CatalogEntity]
    pagination: EntityPagination


class EntityKindSummary(_CamelModel):
    """One registry kind with its count."""

    kind: str
    label: str
    plural_label: str
    count: int
    owner_support: bool = Field(description="Whether entities of the kind can have an owner team.")
    graph_kind: Optional[str] = Field(default=None, description="The graph node kind, or `null`.")
    list_href: Optional[str] = Field(default=None, description="The kind's own list page in the UI, when it has one.")


class CatalogCallouts(_CamelModel):
    """The catalog home's three callouts; a count the caller may not see is `null`."""

    unowned: Optional[int] = Field(default=None, description="Live entities with no confirmed owner team.")
    stale: Optional[int] = Field(
        default=None, description="Connectors and MCP servers not refreshed within twice their cadence."
    )
    shadow: Optional[int] = Field(
        default=None, description="Gateway APIs with no catalog entry (the shadow-API report)."
    )


class CatalogEntitySummary(_CamelModel):
    """Every visible kind with its count, and the home callouts."""

    kinds: List[EntityKindSummary]
    callouts: CatalogCallouts


def _tenant_id(auth_data: Mapping[str, Any]) -> str:
    """The authenticated tenant id, or a 403."""
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for the catalog.")
    return str(tenant_id)


def _visible(auth_data: Dict[str, Any], kinds: Sequence[EntityKind]) -> List[EntityKind]:
    """The kinds whose RBAC resource the caller may view (one check per distinct resource)."""
    allowed: Dict[str, bool] = {}
    for entry in kinds:
        if entry.resource not in allowed:
            allowed[entry.resource] = has_permission(db, auth_data, entry.resource, Action.VIEW)
    return [entry for entry in kinds if allowed[entry.resource]]


def _requested_kinds(values: Optional[List[str]]) -> Sequence[EntityKind]:
    """Resolve the ``kind`` query, or a 422 naming the valid kinds."""
    try:
        return parse_kinds(values)
    except EntityKindError as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code, "message": str(exc)}) from exc


def _envelope(row: Mapping[str, Any]) -> CatalogEntity:
    """Project a store row onto the envelope."""
    entry: EntityKind = row["kind"]
    entity_id = str(row["id"])
    return CatalogEntity(
        kind=entry.key,
        id=entity_id,
        slug=row.get("slug"),
        name=str(row.get("name") or ""),
        description=row.get("description"),
        owner=owner_ref_from_value(row.get("entity_owner")),
        updated_at=row.get("updated_at"),
        href=entity_href(entry, entity_id, row.get("slug")),
        graph_node=GraphNodeRef(kind=entry.graph_kind, id=entity_id) if entry.graph_kind else None,
    )


@router.get("/{tenant_slug}/entities", response_model=CatalogEntityPage, response_model_by_alias=True)
async def list_catalog_entities(
    tenant_slug: str,
    kind_filter: Optional[List[str]] = Query(
        None, alias="kind", description="Only these kinds (repeat the parameter, or comma-separate)."
    ),
    team: Optional[str] = Query(
        None, max_length=128, description="Only entities whose owner (confirmed, else suggested) is this team slug."
    ),
    q: Optional[str] = Query(
        None, max_length=200, description="Only entities whose name, slug or description contains this."
    ),
    cursor: Optional[str] = Query(None, max_length=2000, description="`pagination.nextCursor` of the previous page."),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT, description="Page size."),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> CatalogEntityPage:
    """List the catalog's entities across kinds, in one envelope with a `kind` discriminator.

    Ordered by name (case-insensitive), then registry kind order, then id; page with `cursor`. One
    bounded read per kind, whatever the page holds. Kinds the caller may not view are left out; a
    `team` filter leaves out kinds that cannot have an owner (teams). An unknown `kind` is a 422 and a
    malformed `cursor` a 400.
    """
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    kinds = _visible(auth_data, _requested_kinds(kind_filter))
    try:
        page = store.list_entities(db, tenant_id, kinds, team=team, q=q, cursor=cursor, limit=limit)
    except store.CursorError as exc:
        raise HTTPException(status_code=400, detail={"code": "cursor-invalid", "message": str(exc)}) from exc
    return CatalogEntityPage(
        items=[_envelope(row) for row in page.rows],
        pagination=EntityPagination(next_cursor=page.next_cursor),
    )


@router.get("/{tenant_slug}/entities/summary", response_model=CatalogEntitySummary, response_model_by_alias=True)
async def summarize_catalog_entities(
    tenant_slug: str,
    team: Optional[str] = Query(None, max_length=128, description="Count only entities this team owns."),
    q: Optional[str] = Query(None, max_length=200, description="Count only entities matching this text."),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> CatalogEntitySummary:
    """Count every kind the caller may view, and compute the catalog home's callouts.

    `unowned` counts live entities (of kinds that can have owners) with no confirmed owner team;
    `stale` counts connectors (not paused) and enabled MCP servers whose last successful refresh is
    older than twice their cadence; `shadow` is the shadow-API report's count (needs `imports:view`).
    The callouts ignore `team` and `q`.
    """
    from .config import settings

    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    kinds = _visible(auth_data, parse_kinds(None))
    counts = store.kind_counts(db, tenant_id, kinds, team=team, q=q)
    visible = {entry.key for entry in kinds}
    shadow: Optional[int] = None
    # The shadow report is an `imports:view` read, like the Shadow APIs page.
    if any(entry.resource == Resource.IMPORTS for entry in kinds):
        connectors = shadow_api_store.load_report_connectors(db, tenant_id)
        items = shadow_api_store.load_report_items(db, [str(c["id"]) for c in connectors])
        entries = shadow_api_store.load_catalog_entries(db, tenant_id)
        report = build_shadow_report(connectors=connectors, items=items, entries=entries)
        shadow = int((report.get("summary") or {}).get("shadow", 0))
    callouts = CatalogCallouts(
        unowned=store.unowned_count(db, tenant_id, kinds) if any(e.owner_kind for e in kinds) else None,
        stale=(
            store.stale_count(
                db,
                tenant_id,
                connectors="connector" in visible,
                mcp_servers="mcp_server" in visible,
                connector_default_seconds=int(settings.refresh_default_interval_seconds),
                connector_floor_seconds=int(settings.refresh_min_interval_seconds),
                mcp_default_seconds=int(settings.mcp_discovery_default_cadence_seconds),
            )
            if visible & {"connector", "mcp_server"}
            else None
        ),
        shadow=shadow,
    )
    return CatalogEntitySummary(
        kinds=[
            EntityKindSummary(
                kind=entry.key,
                label=entry.label,
                plural_label=entry.plural_label,
                count=counts.get(entry.key, 0),
                owner_support=entry.owner_kind is not None,
                graph_kind=entry.graph_kind,
                list_href=entry.list_route,
            )
            for entry in kinds
        ],
        callouts=callouts,
    )


@router.get(
    "/{tenant_slug}/entities/{kind_key}/{entity_id}/facts",
    response_model=CatalogFactsOut,
    response_model_by_alias=True,
)
async def read_catalog_entity_facts(
    tenant_slug: str,
    kind_key: str,
    entity_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> CatalogFactsOut:
    """The facts one entity carries for per-kind scorecards (CDG-5.4), each with its evidence.

    `owner.present`, `owner.contactable`, `consumers.declared`, `dependencies.declared`,
    `refresh.fresh` (its source last succeeded within twice its cadence), `deployment.known`,
    `shadow.none`, `registry.level-set`, `mcp.baseline-approved` and `agent.readiness` — whichever
    apply to the kind. A fact Apiome cannot establish is `not_assessed`, never `met`. `score` is
    always `null` until maturity ladders (GVM-1.x) consume the facts. Needs `view` on the kind's
    resource; an unknown kind is a 422, an unknown entity a 404.
    """
    from .config import settings

    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    try:
        entry = kind(kind_key)
    except EntityKindError as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code, "message": str(exc)}) from exc
    if not has_permission(db, auth_data, entry.resource, Action.VIEW):
        raise HTTPException(status_code=403, detail=f"Permission denied: {entry.resource}:view is required")
    name = entity_name(db, entry, tenant_id, entity_id) if is_uuid_string(entity_id) else None
    if name is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "entity-not-found", "message": f"No live {entry.label.lower()} {entity_id!r}."},
        )
    cadence = CadenceSettings(
        refresh_default=int(settings.refresh_default_interval_seconds),
        refresh_floor=int(settings.refresh_min_interval_seconds),
        mcp_default=int(settings.mcp_discovery_default_cadence_seconds),
    )
    return read_facts(db, entry, tenant_id, entity_id, name, cadence=cadence)
