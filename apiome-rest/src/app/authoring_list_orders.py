"""The orderings of the keyset-paged authoring lists (DBP-1.13, #7196).

Each constant spells the ``ORDER BY`` of one accessor in :mod:`app.database` (or of a store
module) and is used by both that accessor and the route that pages it. They live here, not on
the database class, so a route keeps its ordering when a test replaces ``db`` with a stand-in.
"""

from __future__ import annotations

from .keyset_lists import ListOrder, SortColumn, by_name, newest_first

__all__ = [
    "CLASSES_WITH_PARTS_ORDER",
    "COMPONENTS_ORDER",
    "COMPONENT_DEPRECATIONS_ORDER",
    "COMPONENT_USAGE_PINS_ORDER",
    "CUSTOM_ACTIONS_ORDER",
    "LINT_DECISIONS_ORDER",
    "LINT_DECISION_EVENTS_ORDER",
    "PROJECT_CONVERSIONS_ORDER",
    "PROJECT_PROPERTIES_ORDER",
    "PROJECT_TAGS_ORDER",
    "STYLE_GUIDES_ORDER",
    "STYLE_GUIDE_POLICY_VERSIONS_ORDER",
    "STYLE_GUIDE_REVISIONS_ORDER",
    "TYPE_NAMESPACES_ORDER",
    "UNRESOLVED_PRIMITIVES_ORDER",
    "VERSION_BRANCHES_ORDER",
    "VERSION_TAGS_ORDER",
]

#: ``get_primitives_with_unresolved_refs``: un-namespaced primitives first, then by name.
UNRESOLVED_PRIMITIVES_ORDER = ListOrder(
    "unresolved-primitives",
    (
        SortColumn("namespace", "text", ("namespace",), nullable=True, nulls_first=True),
        SortColumn("name", "text", ("name",)),
        SortColumn("id", "uuid", ("id",)),
    ),
)

#: ``list_type_namespaces``: system namespaces first, then by namespace.
TYPE_NAMESPACES_ORDER = ListOrder(
    "type-namespaces",
    (
        SortColumn("n.is_system", "bool", ("is_system",), descending=True),
        SortColumn("n.namespace", "text", ("namespace",)),
        SortColumn("n.id", "uuid", ("id",)),
    ),
)

#: ``get_classes_with_properties_and_tags_for_version``.
CLASSES_WITH_PARTS_ORDER = by_name("classes-with-parts")

#: ``get_conversions_for_project``: newest conversion first.
PROJECT_CONVERSIONS_ORDER = newest_first("project-conversions", "cp.created_at", "cp.id")

#: ``list_lint_finding_decisions``: most recently changed first.
LINT_DECISIONS_ORDER = newest_first(
    "lint-decisions", "d.updated_at", "d.id", timestamp_field="updated_at"
)

#: ``list_lint_finding_decision_events``: a decision's history, oldest first.
LINT_DECISION_EVENTS_ORDER = ListOrder(
    "lint-decision-events",
    (
        SortColumn("created_at", "time", ("created_at",)),
        SortColumn("id", "uuid", ("id",)),
    ),
)

#: ``list_style_guides``: the built-in guide first, then by name.
STYLE_GUIDES_ORDER = ListOrder(
    "style-guides",
    (
        SortColumn("(g.source = 'builtin')", "bool", ("is_builtin",), descending=True),
        SortColumn("g.name", "text", ("name",)),
        SortColumn("g.id", "uuid", ("id",)),
    ),
)

#: ``list_style_guide_revisions``: newest revision first.
STYLE_GUIDE_REVISIONS_ORDER = ListOrder(
    "style-guide-revisions",
    (
        SortColumn("revision_number", "int", ("revision_number",), descending=True),
        SortColumn("id", "uuid", ("id",), descending=True),
    ),
)

#: ``list_style_guide_policy_versions``: newest policy version first.
STYLE_GUIDE_POLICY_VERSIONS_ORDER = ListOrder(
    "style-guide-policy-versions",
    (
        SortColumn("version_number", "int", ("version_number",), descending=True),
        SortColumn("id", "uuid", ("id",), descending=True),
    ),
)

#: ``list_version_branches_detailed_for_project``.
VERSION_BRANCHES_ORDER = by_name("version-branches", "b.name", "b.id")

#: ``get_properties_for_project``.
PROJECT_PROPERTIES_ORDER = by_name("project-properties", "p.name", "p.id")

#: ``get_tags_for_project``.
PROJECT_TAGS_ORDER = by_name("project-tags")

#: ``list_version_tags_for_project``.
VERSION_TAGS_ORDER = by_name("version-tags", "t.name", "t.id")

#: ``workspace_custom_action_store.list_actions``: case-insensitively by name.
CUSTOM_ACTIONS_ORDER = by_name("custom-actions", "lower(name)", "id", name_field="name_sort")

#: ``list_operational_components``: by kind, then name.
COMPONENTS_ORDER = ListOrder(
    "components",
    (
        SortColumn("c.kind", "text", ("kind",)),
        SortColumn("c.name", "text", ("name",)),
        SortColumn("c.id", "uuid", ("id",)),
    ),
)

#: ``list_component_deprecations``: soonest sunset first.
COMPONENT_DEPRECATIONS_ORDER = ListOrder(
    "component-deprecations",
    (
        SortColumn("d.sunset_at", "time", ("sunset_at",)),
        SortColumn("c.name", "text", ("component_name",)),
        SortColumn("r.revision", "text", ("revision",)),
        SortColumn("d.id", "uuid", ("id",)),
    ),
)

#: ``get_component_usage_pins``: by component, then project and version.
COMPONENT_USAGE_PINS_ORDER = ListOrder(
    "component-usage-pins",
    (
        SortColumn("c.name", "text", ("component_name",)),
        SortColumn("v.project_id", "uuid", ("project_id",)),
        SortColumn("p.version_id", "uuid", ("version_id",)),
        SortColumn("p.id", "uuid", ("id",)),
    ),
)
