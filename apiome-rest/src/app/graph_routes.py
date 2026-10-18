"""``/v1/graph/{tenant_slug}/entities/…`` — the catalog graph read (CDG-3.1) and declared dependencies (CDG-3.2).

``…/dependencies`` (CDG-3.2, #5967): ``GET`` lists what an entity declares it depends on — its
``declared`` edges from every source and the references that resolved to nothing — and ``PUT``
replaces its ``manual`` declarations. Both are gated on the entity kind's own ``view`` / ``edit``,
like ownership.

``…/edges`` (CDG-3.1, #5966):

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
from .consumer_contract_store import actor_from_auth
from .database import db
from .declared_dependencies import MAX_DECLARED, DependencyValidationError
from .declared_dependency_store import put_dependencies, read_dependencies
from .entity_owners import KINDS
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


def _auth_tenant(auth_data: Dict[str, Any]) -> str:
    """The authenticated tenant id, or 403 when the credential carries none."""
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this credential.")
    return str(tenant_id)


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
    tenant_id = _auth_tenant(auth_data)
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


# ---------------------------------------------------------------------------------------------
# Declared dependencies (CDG-3.2, #5967)
# ---------------------------------------------------------------------------------------------


class DependencyTarget(BaseModel):
    """What a dependency points at: an entity by `kind` + `id`, or a project/catalog item by `slug`."""

    model_config = ConfigDict(extra="forbid")

    kind: Optional[str] = Field(default=None, description="The target's kind; required with `id`.")
    id: Optional[str] = None
    slug: Optional[str] = Field(default=None, description="A project or catalog item's slug.")


class DependencyInput(BaseModel):
    """One declared dependency."""

    model_config = ConfigDict(extra="forbid")

    to: DependencyTarget
    pointer: Optional[str] = Field(default=None, description="A JSON pointer into the target.")
    note: Optional[str] = Field(default=None, max_length=500)


class DependenciesInput(BaseModel):
    """The entity's complete list of manual dependencies."""

    model_config = ConfigDict(extra="forbid")

    dependencies: List[DependencyInput] = Field(default_factory=list, max_length=MAX_DECLARED)


class UnresolvedDependency(BaseModel):
    """A declared reference that names no entity."""

    model_config = ConfigDict(extra="forbid")

    source_ref: str = Field(description="`manual`, `spec` or `backstage:<path>`.")
    reference: str = Field(description="The reference as written.")
    pointer: Optional[str] = None
    edge_kind: str
    reason: str = Field(description="`not-found` or `self`.")
    note: Optional[str] = None
    created_at: Optional[str] = None


class DependenciesResponse(BaseModel):
    """What an entity declares it depends on, from every source."""

    model_config = ConfigDict(extra="forbid")

    kind: str
    entity_id: str
    declared: List[GraphEdge] = Field(default_factory=list, description="Outgoing `declared` edges.")
    unresolved: List[UnresolvedDependency] = Field(default_factory=list)
    truncated: bool = Field(description="True when the entity has more than 500 declared edges.")


_DEPENDENCY_HELP = (
    "`kind` is `project`, `catalog_item`, `mcp_endpoint`, `consumer` or `connector`; a project or "
    "catalog item may be named by slug instead of id. Reading needs the kind's `view` and changing "
    "needs its `edit` (`projects` for projects, catalog items and MCP endpoints, "
    "`consumer_contracts` for consumers, `imports` for connectors)."
)


def _dependency_guard(auth_data: Dict[str, Any], kind: str, entity: str, action: str) -> str:
    """Enforce the kind's own permission; 400 for an unknown kind. Returns the user id."""
    spec = KINDS.get(kind)
    if spec is None:
        raise HTTPException(
            status_code=400, detail={"code": "graph-invalid", "message": f"unknown entity kind '{kind}'"}
        )
    return enforce_permission(db, auth_data, spec.resource, action, target=f"{kind}:{entity}")


def _dependency_error(exc: DependencyValidationError) -> HTTPException:
    """404 for an unknown entity, 400 otherwise."""
    status = 404 if exc.code == "graph-entity-not-found" else 400
    return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})


def _dependencies_response(result: Dict[str, Any]) -> DependenciesResponse:
    return DependenciesResponse(
        kind=result["kind"],
        entity_id=result["entity_id"],
        declared=[GraphEdge(**edge) for edge in result["declared"]],
        unresolved=[UnresolvedDependency(**row) for row in result["unresolved"]],
        truncated=result["truncated"],
    )


@router.get(
    "/{tenant_slug}/entities/{kind}/{entity}/dependencies",
    response_model=DependenciesResponse,
    summary="Read an entity's declared dependencies",
    description=(
        "Every `declared` edge the entity has — written here (`source_ref: manual`), read from its "
        "spec's `x-apiome-depends-on` (`spec`) or from a Backstage `catalog-info.yaml` in its "
        "repository (`backstage:<path>`) — and the references that resolved to nothing "
        "(`unresolved`).\n\n" + _DEPENDENCY_HELP
    ),
)
async def get_entity_dependencies(
    tenant_slug: str,
    kind: str,
    entity: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> DependenciesResponse:
    """Read the declared dependencies."""
    _dependency_guard(auth_data, kind, entity, Action.VIEW)
    _ = tenant_slug
    try:
        return _dependencies_response(read_dependencies(_auth_tenant(auth_data), kind, entity))
    except DependencyValidationError as exc:
        raise _dependency_error(exc) from exc


@router.put(
    "/{tenant_slug}/entities/{kind}/{entity}/dependencies",
    response_model=DependenciesResponse,
    summary="Replace an entity's manual dependencies",
    description=(
        "Replace the entity's `manual` dependencies with `dependencies` — each "
        "`{to: {kind, id} | {slug}, pointer?, note?}` — as `depends_on` edges with provenance "
        "`declared`. An empty list clears them; spec and Backstage declarations are left alone. A "
        "target that does not exist is kept under `unresolved`, not refused. At most 200 entries. "
        "Audited as `graph.dependencies.update`.\n\n" + _DEPENDENCY_HELP
    ),
)
async def put_entity_dependencies(
    tenant_slug: str,
    kind: str,
    entity: str,
    body: DependenciesInput,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> DependenciesResponse:
    """Replace the manual dependencies."""
    user_id = _dependency_guard(auth_data, kind, entity, Action.EDIT)
    _ = tenant_slug
    try:
        result = put_dependencies(
            _auth_tenant(auth_data),
            kind,
            entity,
            [item.model_dump() for item in body.dependencies],
            actor=actor_from_auth(auth_data, user_id),
        )
    except DependencyValidationError as exc:
        raise _dependency_error(exc) from exc
    return _dependencies_response(result)
