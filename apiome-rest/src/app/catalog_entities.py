"""The catalog entity-kind registry — CDG-5.1 (#5979).

Search, ownership, the graph and scorecards all need "every thing in the catalog". Rather than each
hand-rolling a union over projects, catalog items, MCP servers, consumers, connectors and teams, they
read this registry: one :class:`EntityKind` per kind, declaring where its rows live, how to read the
common envelope (id, slug, name, description, updated time), whether it can have an owner team
(:mod:`app.entity_owners`), which graph node kind it is (:mod:`app.catalog_graph`), which RBAC
resource gates reading it, and the UI routes that render it.

The catalog/projects boundary holds: ``api`` (a publishable Project) and ``spec`` (a catalog item)
are both ``apiome.projects`` rows told apart by ``publishable``, and they are distinct kinds — a
``spec`` never appears where ``api`` is asked for.

A kind added to :data:`REGISTRY` appears in the entity list, its facet counts and (when it declares
a ``graph_kind``) the graph labeller without any other change; later kinds (``agent``, ``model``,
``gateway_config``, CDG-5.2/5.3) are new rows here. Reads live in :mod:`app.catalog_entity_store`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Sequence, Tuple
from urllib.parse import quote

from .permissions import Resource

__all__ = [
    "EntityKind",
    "EntityKindError",
    "REGISTRY",
    "entity_href",
    "kind",
    "kind_keys",
    "kinds_by_graph_kind",
    "parse_kinds",
]


class EntityKindError(ValueError):
    """A request named an entity kind the registry does not have.

    Attributes:
        code: Always ``kind-invalid``.
    """

    code = "kind-invalid"


@dataclass(frozen=True)
class EntityKind:
    """One kind of catalog entity.

    Every SQL expression is written against the alias ``e`` for :attr:`table`.

    Attributes:
        key: The kind's wire name (``api``, ``spec``, ``mcp_server``, …).
        label: Singular display name, in the app's words (``Project`` for ``api``).
        plural_label: Plural display name, for facets and tiles (``Projects``).
        table: The table holding the rows (``apiome.projects``).
        live_where: Predicate a live row of this kind satisfies (soft-deletes excluded).
        slug_sql: SQL for the slug (``NULL::text`` when the kind has none).
        description_sql: SQL for the description (``NULL::text`` when the kind has none).
        owner_kind: The :data:`app.entity_owners.KINDS` key the owner is stored under, or ``None``
            when the kind cannot have an owner team.
        graph_kind: The :data:`app.catalog_graph.NODE_KINDS` value, or ``None`` when the kind is not
            a graph node.
        resource: The RBAC resource whose ``view`` permission is needed to list the kind.
        detail_route: The UI page for one entity; ``{id}`` and ``{slug}`` are filled in.
        list_route: The UI page listing the kind, or ``None`` when it has no list of its own.
    """

    key: str
    label: str
    plural_label: str
    table: str
    live_where: str
    slug_sql: str
    description_sql: str
    owner_kind: Optional[str]
    graph_kind: Optional[str]
    resource: str
    detail_route: str
    list_route: Optional[str]


#: Every kind, in display order (tiles, facets, and the tie-break when two names sort equal).
REGISTRY: Tuple[EntityKind, ...] = (
    EntityKind(
        key="api",
        label="Project",
        plural_label="Projects",
        table="apiome.projects",
        live_where="e.publishable AND e.deleted_at IS NULL",
        slug_sql="e.slug",
        description_sql="e.description",
        owner_kind="project",
        graph_kind="project",
        resource=Resource.PROJECTS,
        detail_route="/ade/dashboard/versions?projectId={id}",
        list_route="/ade/dashboard/projects",
    ),
    EntityKind(
        key="spec",
        label="Catalog item",
        plural_label="Catalog items",
        table="apiome.projects",
        live_where="NOT e.publishable AND e.deleted_at IS NULL",
        slug_sql="e.slug",
        description_sql="e.description",
        owner_kind="catalog_item",
        graph_kind="catalog_item",
        resource=Resource.PROJECTS,
        detail_route="/ade/dashboard/catalog/{id}",
        list_route="/ade/dashboard/catalog",
    ),
    EntityKind(
        key="mcp_server",
        label="MCP server",
        plural_label="MCP servers",
        table="apiome.mcp_endpoints",
        live_where="e.deleted_at IS NULL",
        slug_sql="e.slug",
        description_sql="e.description",
        owner_kind="mcp_endpoint",
        graph_kind="mcp_endpoint",
        resource=Resource.PROJECTS,
        detail_route="/ade/dashboard/mcp/{id}",
        list_route="/ade/dashboard/mcp",
    ),
    EntityKind(
        key="consumer",
        label="Consumer",
        plural_label="Consumers",
        table="apiome.consumer",
        live_where="e.deleted_at IS NULL",
        slug_sql="e.slug",
        description_sql="e.description",
        owner_kind="consumer",
        graph_kind="consumer",
        resource=Resource.CONSUMER_CONTRACTS,
        detail_route="/ade/dashboard/graph?entity=consumer%3A{id}",
        list_route=None,
    ),
    EntityKind(
        key="connector",
        label="Connector",
        plural_label="Connectors",
        table="apiome.catalog_connectors",
        live_where="e.deleted_at IS NULL",
        slug_sql="NULL::text",
        description_sql="NULL::text",
        owner_kind="connector",
        graph_kind="connector",
        resource=Resource.IMPORTS,
        detail_route="/ade/dashboard/connectors/{id}",
        list_route="/ade/dashboard/connectors",
    ),
    EntityKind(
        key="agent",
        label="Agent",
        plural_label="Agents",
        table="apiome.catalog_agents",
        live_where="e.deleted_at IS NULL",
        slug_sql="e.slug",
        description_sql="e.description",
        owner_kind="agent",
        # In the graph an agent is the consumer it is in each project (CDG-5.2), not a node of its own.
        graph_kind=None,
        resource=Resource.CONSUMER_CONTRACTS,
        detail_route="/ade/dashboard/catalog/agents/{slug}",
        list_route=None,
    ),
    EntityKind(
        key="model",
        label="Model",
        plural_label="Models",
        table="apiome.catalog_models",
        live_where="e.deleted_at IS NULL",
        slug_sql="e.slug",
        description_sql="e.provider || ' · ' || e.model_name || COALESCE(' ' || e.model_version, '')",
        owner_kind="model",
        graph_kind=None,
        resource=Resource.CONSUMER_CONTRACTS,
        detail_route="/ade/dashboard/catalog/models/{slug}",
        list_route=None,
    ),
    EntityKind(
        key="gateway_config",
        label="Gateway config",
        plural_label="Gateway configs",
        table="apiome.catalog_gateway_configs",
        live_where="e.deleted_at IS NULL",
        slug_sql="e.slug",
        description_sql="NULLIF(e.environment, '')",
        owner_kind="gateway_config",
        graph_kind="gateway_config",
        resource=Resource.IMPORTS,
        detail_route="/ade/dashboard/connectors/environments/{slug}",
        list_route="/ade/dashboard/connectors",
    ),
    EntityKind(
        key="team",
        label="Team",
        plural_label="Teams",
        table="apiome.teams",
        live_where="e.deleted_at IS NULL",
        slug_sql="e.slug",
        description_sql="e.description",
        owner_kind=None,
        graph_kind=None,
        resource=Resource.TEAMS,
        detail_route="/ade/dashboard/teams/{slug}",
        list_route="/ade/dashboard/teams",
    ),
)


def kind_keys() -> Tuple[str, ...]:
    """Return every kind's key, in display order."""
    return tuple(entry.key for entry in REGISTRY)


def kind(key: str) -> EntityKind:
    """Return the registry entry for ``key``.

    Args:
        key: A kind's wire name.

    Returns:
        The :class:`EntityKind`.

    Raises:
        EntityKindError: The registry has no such kind.
    """
    for entry in REGISTRY:
        if entry.key == key:
            return entry
    raise EntityKindError(f"Unknown entity kind '{key}'; use one of {', '.join(kind_keys())}.")


def parse_kinds(values: Optional[Sequence[str]]) -> Tuple[EntityKind, ...]:
    """Resolve a ``kind`` filter to registry entries, in display order.

    Args:
        values: The ``kind`` values sent (repeated, or comma-separated); ``None`` or empty = every kind.

    Returns:
        The kinds asked for, without duplicates, in :data:`REGISTRY` order.

    Raises:
        EntityKindError: A value names no kind.
    """
    wanted = {part.strip() for value in values or () for part in str(value).split(",") if part.strip()}
    if not wanted:
        return REGISTRY
    for key in wanted:
        kind(key)
    return tuple(entry for entry in REGISTRY if entry.key in wanted)


def kinds_by_graph_kind() -> Dict[str, EntityKind]:
    """Return the kinds that are graph nodes, keyed by their graph node kind."""
    return {entry.graph_kind: entry for entry in REGISTRY if entry.graph_kind}


def entity_href(entry: EntityKind, entity_id: str, slug: Optional[str]) -> str:
    """Return the UI page of one entity.

    Args:
        entry: Its kind.
        entity_id: Its id.
        slug: Its slug (``None`` for a kind without one).

    Returns:
        :attr:`EntityKind.detail_route` with ``{id}`` and ``{slug}`` filled in (URL-safe).
    """
    return entry.detail_route.replace("{id}", quote(str(entity_id), safe="")).replace(
        "{slug}", quote(str(slug or entity_id), safe="")
    )
