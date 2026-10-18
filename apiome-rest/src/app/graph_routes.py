"""``/v1/graph/{tenant_slug}/entities/{kind}/{entity_id}/edges`` — the catalog graph read (CDG-3.1, #5966).

One entity's edges in ``apiome.catalog_edges``, outgoing (``direction=out``, the default) or incoming
(``direction=in``), filtered by edge ``kind`` and ``provenance`` (each repeatable), paged with
``limit`` (at most 500) and ``offset``. The response says whether more edges match (``truncated``).
Stale edges — their source rows are gone — come last, flagged ``stale: true``.

Edges point at projects, catalog items, consumers, connectors, MCP endpoints and more, so the read
needs ``projects:view``, the permission every catalog read shares.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from .auth import validate_authentication
from .catalog_graph import MAX_READ_LIMIT, GraphValidationError, list_edges
from .database import db
from .permissions import Action, Resource, enforce_permission
from .revision_deprecation import is_uuid_string

__all__ = ["router"]

router = APIRouter(prefix="/v1/graph", tags=["graph"])


class GraphEdge(BaseModel):
    """One edge."""

    model_config = ConfigDict(extra="forbid")

    id: str
    from_kind: str = Field(description="The source node's kind.")
    from_id: str
    to_kind: str = Field(description="The target node's kind.")
    to_id: str
    edge_kind: str = Field(description="`consumes`, `converted_from`, `identity_of`, `built_from`, `deployed_on`, …")
    pointer: Optional[str] = Field(default=None, description="The JSON pointer a `consumes` edge depends on.")
    provenance: str = Field(description="`declared`, `derived` or `runtime`.")
    source_ref: str = Field(description="The row the edge was derived from, e.g. `consumer_contract:<id>`.")
    evidence: Dict[str, Any] = Field(default_factory=dict)
    first_seen_at: Optional[str] = None
    last_seen_at: Optional[str] = None
    stale_since: Optional[str] = None
    stale: bool = Field(description="True when the edge's source is gone; purged 30 days after `stale_since`.")


class GraphEdgePage(BaseModel):
    """One page of an entity's edges."""

    model_config = ConfigDict(extra="forbid")

    edges: List[GraphEdge] = Field(default_factory=list)
    total: int = Field(description="How many edges match the filters.")
    truncated: bool = Field(description="True when more edges match than this page holds.")
    limit: int
    offset: int


@router.get(
    "/{tenant_slug}/entities/{kind}/{entity_id}/edges",
    response_model=GraphEdgePage,
    summary="List an entity's graph edges",
    description=(
        "The entity's edges in the catalog dependency graph. `direction` is `out` (edges from the "
        "entity, the default) or `in` (edges to it); `kind` and `provenance` filter and may repeat. "
        f"`limit` is 1–{MAX_READ_LIMIT} (default 100); `truncated` is true when more edges match. "
        "Stale edges come last with `stale: true`.\n\nRequires `projects:view`."
    ),
)
async def get_entity_edges(
    tenant_slug: str,
    kind: str,
    entity_id: str,
    direction: str = Query("out", description="`out` or `in`."),
    edge_kind: Optional[List[str]] = Query(None, alias="kind", description="Edge kinds to keep."),
    provenance: Optional[List[str]] = Query(None, description="Provenances to keep."),
    limit: int = Query(100, ge=1, le=MAX_READ_LIMIT),
    offset: int = Query(0, ge=0),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> GraphEdgePage:
    """Read one page of an entity's edges.

    Raises:
        HTTPException: 400 ``graph-invalid`` for a bad id, kind, direction or filter; 403 without
            ``projects:view`` or a tenant context.
    """
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.VIEW, target="graph")
    _ = tenant_slug
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this credential.")
    if not is_uuid_string(entity_id):
        raise HTTPException(status_code=400, detail={"code": "graph-invalid", "message": "entity_id must be an id"})
    try:
        page = list_edges(
            db,
            str(tenant_id),
            kind,
            entity_id,
            direction=direction,
            edge_kinds=tuple(edge_kind or ()),
            provenances=tuple(provenance or ()),
            limit=limit,
            offset=offset,
        )
    except GraphValidationError as exc:
        raise HTTPException(status_code=400, detail={"code": exc.code, "message": str(exc)}) from exc
    return GraphEdgePage(
        edges=[GraphEdge(**edge) for edge in page.edges],
        total=page.total,
        truncated=page.truncated,
        limit=limit,
        offset=offset,
    )
