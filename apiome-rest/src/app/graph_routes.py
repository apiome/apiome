"""``/v1/graph/{tenant_slug}/entities/…`` — the catalog graph read (CDG-3.1) and declared dependencies (CDG-3.2).

``…/dependencies`` (CDG-3.2, #5967): ``GET`` lists what an entity declares it depends on — its
``declared`` edges from every source and the references that resolved to nothing — and ``PUT``
replaces its ``manual`` declarations. Both are gated on the entity kind's own ``view`` / ``edit``,
like ownership.

``…/blast-radius`` (CDG-3.3, #5968): ``POST`` answers "what does changing this affect" — direct
and transitive dependents plus the evidence a change invalidates (:mod:`app.blast_radius`).

``…/export`` (CDG-3.6, #5971): ``GET`` streams the tenant's graph — or one entity's neighbourhood —
as JSON or Graphviz DOT, bounded at 10,000 edges (:mod:`app.graph_export`).

``…/edges`` (CDG-3.1, #5966):

One entity's edges in ``apiome.catalog_edges``, outgoing (``direction=out``, the default) or incoming
(``direction=in``), filtered by edge ``kind`` and ``provenance`` (each repeatable), paged with
``limit`` (at most 500) and ``offset``. The response says whether more edges match (``truncated``).
Stale edges — their source rows are gone — come last, flagged ``stale: true``.

Edges point at projects, catalog items, consumers, connectors, MCP endpoints and more, so the read
needs ``projects:view``, the permission every catalog read shares.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from .auth import validate_authentication
from .blast_radius import BlastRadiusRequest, blast_radius
from .catalog_graph import MAX_READ_LIMIT, GraphValidationError, list_edges
from .consumer_contract_store import actor_from_auth
from .database import db
from .declared_dependencies import MAX_DECLARED, DependencyValidationError
from .declared_dependency_store import put_dependencies, read_dependencies
from .entity_owners import KINDS
from .graph_export import DEFAULT_DEPTH as DEFAULT_EXPORT_DEPTH
from .graph_export import FORMATS as EXPORT_FORMATS
from .graph_export import MAX_DEPTH as MAX_EXPORT_DEPTH
from .graph_export import export_graph, render_dot, render_json
from .graph_nodes import MAX_SEARCH_LIMIT, node_labels_with_owners, search_entities
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
    from_label: Optional[Dict[str, Any]] = Field(
        default=None, description="With `labels=true`: the source's `{name, slug, owner}`."
    )
    to_label: Optional[Dict[str, Any]] = Field(
        default=None, description="With `labels=true`: the target's `{name, slug, owner}`."
    )


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
    labels: bool = Query(False, description="Add each end's name, slug and owner team."),
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
    edges = page.edges
    if labels and edges:
        refs = {(e["from_kind"], e["from_id"]) for e in edges} | {(e["to_kind"], e["to_id"]) for e in edges}
        info = node_labels_with_owners(db, str(tenant_id), sorted(refs))
        edges = [{**e, "from_label": info.get(e["from_id"]), "to_label": info.get(e["to_id"])} for e in edges]
    return GraphEdgePage(
        edges=[GraphEdge(**edge) for edge in edges],
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


# ---------------------------------------------------------------------------------------------
# Blast radius (CDG-3.3, #5968)
# ---------------------------------------------------------------------------------------------


class BlastRadiusEntity(BaseModel):
    """The changed entity."""

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(description="`project`, `catalog_item`, `mcp_endpoint`, `consumer` or `connector`.")
    id: str = Field(description="Its id, or a project or catalog item's slug.")


class BlastRadiusInput(BaseModel):
    """One blast-radius question."""

    model_config = ConfigDict(extra="forbid")

    entity: BlastRadiusEntity
    pointers: List[str] = Field(
        default_factory=list,
        max_length=200,
        description="JSON pointers that change (`/paths/~1pets~1{id}/get`, `/components/schemas/Pet`); "
        "empty means the whole entity.",
    )
    depth: int = Field(default=3, ge=1, le=5, description="Levels of dependents to walk (1–5).")
    provenance: List[str] = Field(
        default_factory=lambda: ["declared", "derived", "runtime"], description="Edge provenances to follow."
    )
    version: Optional[str] = Field(
        default=None, description="Version label or id for the evidence; default the latest published."
    )


class AffectedEntity(BaseModel):
    """One entity a change reaches."""

    model_config = ConfigDict(extra="forbid")

    kind: str
    id: str
    name: Optional[str] = None
    slug: Optional[str] = None
    depth: int = Field(description="1 for a direct dependent, 2+ for a transitive one.")
    edge_kind: str = Field(description="The edge that reached it: `consumes`, `depends_on` or `runtime_calls`.")
    provenance: str
    pointers: List[str] = Field(default_factory=list, description="The changed pointers it depends on.")
    path: List[Dict[str, Any]] = Field(default_factory=list, description="The edges from it back to the change.")
    owner: Optional[Dict[str, Any]] = Field(default=None, description="Its owner team `{slug, name, status}`.")


class InvalidatedEvidence(BaseModel):
    """The evidence a change invalidates."""

    model_config = ConfigDict(extra="forbid")

    verification_runs: List[Dict[str, Any]] = Field(default_factory=list)
    consumer_contracts: List[Dict[str, Any]] = Field(default_factory=list)
    deploy_gate_evaluations: List[Dict[str, Any]] = Field(default_factory=list)
    sdk_regen_targets: List[Dict[str, Any]] = Field(default_factory=list)
    agent_toolset_tools: List[Dict[str, Any]] = Field(default_factory=list)
    mock_fixture_packs: List[Dict[str, Any]] = Field(default_factory=list)
    sunset_consumers: List[Dict[str, Any]] = Field(default_factory=list)


class BlastRadiusResponse(BaseModel):
    """What a change affects."""

    model_config = ConfigDict(extra="forbid")

    entity: Dict[str, Any]
    version: Optional[Dict[str, Any]] = Field(default=None, description="The version the evidence is from.")
    pointers: List[str]
    operations: Optional[List[str]] = Field(
        default=None, description="The operations the pointers reach; `null` means every operation."
    )
    depth: int
    provenance: List[str]
    direct: List[AffectedEntity]
    transitive: List[AffectedEntity]
    invalidated_evidence: InvalidatedEvidence
    evidence_checked: bool = Field(description="True whenever evidence was looked for: empty means none.")
    truncated: bool = Field(description="True when the depth or the 2,000-entity bound cut the walk short.")
    node_count: int
    total_found: int = Field(
        default=0, description="Entities found, including those past the cap; a lower bound when `truncated`."
    )
    warnings: List[str] = Field(default_factory=list)


@router.post(
    "/{tenant_slug}/blast-radius",
    response_model=BlastRadiusResponse,
    summary="Ask what a change affects",
    description=(
        "Who depends on `entity` (optionally narrowed to `pointers` into it), directly and "
        "transitively, along inbound `consumes`, `depends_on` and `runtime_calls` edges — each with "
        "its edge path, provenance and owner team — and the evidence a change invalidates: "
        "verification runs, consumer contracts, deploy-gate evaluations, SDK regeneration targets, "
        "agent-toolset tools, mock fixture packs and scenarios, and consumers pinned to a deprecated "
        "or sunset version. The direct `consumes` layer is the consumer-impact intersection, so the "
        "two agree. At most 5 levels and 2,000 entities; `truncated` is true past that. "
        "`evidence_checked: true` with empty sections means nothing is affected.\n\n"
        "Requires `projects:view`."
    ),
)
async def post_blast_radius(
    tenant_slug: str,
    body: BlastRadiusInput,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> BlastRadiusResponse:
    """Answer one blast-radius question."""
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.VIEW, target="graph")
    _ = tenant_slug
    request = BlastRadiusRequest(
        kind=body.entity.kind,
        entity=body.entity.id,
        pointers=tuple(body.pointers),
        depth=body.depth,
        provenances=tuple(body.provenance),
        version=body.version,
    )
    try:
        return BlastRadiusResponse(**blast_radius(db, _auth_tenant(auth_data), request))
    except DependencyValidationError as exc:
        raise _dependency_error(exc) from exc


# ---------------------------------------------------------------------------------------------
# Tenant-wide entity search (CDG-3.4, #5969)
# ---------------------------------------------------------------------------------------------


class GraphEntity(BaseModel):
    """An entity that has edges."""

    model_config = ConfigDict(extra="forbid")

    kind: str
    id: str
    name: Optional[str] = None
    slug: Optional[str] = None
    owner: Optional[Dict[str, Any]] = Field(default=None, description="Its owner team `{slug, name, status}`.")
    in_count: int = Field(description="Edges pointing at it.")
    out_count: int = Field(description="Edges leaving it.")
    stale_count: int = Field(description="How many of those edges are stale.")


class GraphEntityPage(BaseModel):
    """One page of the tenant-wide entity search."""

    model_config = ConfigDict(extra="forbid")

    entities: List[GraphEntity] = Field(default_factory=list)
    total: int = Field(description="How many entities match.")
    truncated: bool = Field(description="True when more entities match than this page holds.")
    limit: int
    offset: int


@router.get(
    "/{tenant_slug}/entities",
    response_model=GraphEntityPage,
    summary="Search the entities in the dependency graph",
    description=(
        "Every entity that has at least one edge, most connected first, with its name, owner team "
        "and in/out/stale edge counts. Filter with `q` (name or slug), `kind` and `provenance` "
        "(each repeatable) and `team` (owner team slug). `limit` is 1–2000 (default 200); "
        "`truncated` is true when more match.\n\nRequires `projects:view`."
    ),
)
async def get_graph_entities(
    tenant_slug: str,
    q: Optional[str] = Query(None, max_length=200, description="Substring of the name or slug."),
    kind: Optional[List[str]] = Query(None, description="Node kinds to keep."),
    team: Optional[str] = Query(None, max_length=128, description="Owner team slug."),
    provenance: Optional[List[str]] = Query(None, description="Only count edges of these provenances."),
    limit: int = Query(200, ge=1, le=MAX_SEARCH_LIMIT),
    offset: int = Query(0, ge=0),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> GraphEntityPage:
    """Search the graph's entities."""
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.VIEW, target="graph")
    _ = tenant_slug
    try:
        page = search_entities(
            db, _auth_tenant(auth_data), query=q, kinds=tuple(kind or ()), team=team,
            provenances=tuple(provenance or ()), limit=limit, offset=offset,
        )
    except GraphValidationError as exc:
        raise HTTPException(status_code=400, detail={"code": exc.code, "message": str(exc)}) from exc
    return GraphEntityPage(
        entities=[GraphEntity(**e) for e in page.entities], total=page.total, truncated=page.truncated,
        limit=limit, offset=offset,
    )


# ---------------------------------------------------------------------------------------------
# Export (CDG-3.6, #5971)
# ---------------------------------------------------------------------------------------------

#: The media type each export format is served as.
_EXPORT_MEDIA_TYPES = {"json": "application/json", "dot": "text/vnd.graphviz"}


@router.get(
    "/{tenant_slug}/export",
    summary="Export the dependency graph as JSON or DOT",
    description=(
        "The tenant's dependency graph as one document: `format=json` (default) writes "
        "`{format: \"apiome.graph.export/v1\", tenant, generated_at, filters, limit, truncated, node_count, "
        "edge_count, nodes, edges}`; `format=dot` writes a Graphviz `digraph` (`dot -Tsvg export.dot`). "
        "Every node carries its name, slug and owner team.\n\n"
        "Narrow it with `kind` (edges with either end of these node kinds), `team` (either end owned by "
        "this team slug), `provenance` (each repeatable) and `stale=false` (drop stale edges), or export "
        "one entity's neighbourhood with `entity=kind:id` and `depth` (1–5, default 2).\n\n"
        "Bounded at 10,000 edges, current before stale: `truncated` (JSON) or the first-line comment "
        "(DOT) says when more matched. The response is streamed and offered as a download.\n\n"
        "Requires `projects:view`."
    ),
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "The export.",
            "content": {
                "application/json": {"schema": {"type": "object"}},
                "text/vnd.graphviz": {"schema": {"type": "string"}},
            },
        },
        400: {"description": "`graph-invalid`: an unknown format, kind, provenance or entity, or a bad depth."},
    },
)
async def export_graph_route(
    tenant_slug: str,
    format: str = Query("json", description="`json` or `dot`."),
    kind: Optional[List[str]] = Query(None, description="Keep edges with an end of these node kinds."),
    team: Optional[str] = Query(None, max_length=128, description="Keep edges with an end owned by this team slug."),
    provenance: Optional[List[str]] = Query(None, description="Keep edges of these provenances."),
    stale: bool = Query(True, description="`false` drops stale edges."),
    entity: Optional[str] = Query(None, max_length=200, description="`kind:id`: export this entity's neighbourhood."),
    depth: int = Query(DEFAULT_EXPORT_DEPTH, ge=1, le=MAX_EXPORT_DEPTH, description="Hops around `entity`."),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> StreamingResponse:
    """Stream the tenant's graph as JSON or DOT."""
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.VIEW, target="graph")
    if format not in EXPORT_FORMATS:
        raise HTTPException(
            status_code=400, detail={"code": "graph-invalid", "message": "format must be 'json' or 'dot'"}
        )
    try:
        export = export_graph(
            db, _auth_tenant(auth_data), kinds=tuple(kind or ()), team=team, provenances=tuple(provenance or ()),
            include_stale=stale, entity=entity, depth=depth,
        )
    except GraphValidationError as exc:
        raise HTTPException(status_code=400, detail={"code": exc.code, "message": str(exc)}) from exc
    chunks = render_dot(export, tenant=tenant_slug) if format == "dot" else render_json(export, tenant=tenant_slug)
    filename = re.sub(r"[^A-Za-z0-9._-]", "-", tenant_slug) or "graph"
    return StreamingResponse(
        (chunk.encode("utf-8") for chunk in chunks),
        media_type=_EXPORT_MEDIA_TYPES[format],
        headers={"Content-Disposition": f'attachment; filename="{filename}-graph.{format}"'},
    )
