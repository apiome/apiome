"""Executable GraphQL schema, settings and operation limits for the hosted mock (#5729, XPC-1.1).

A published GraphQL version is served at ``/{tenant}/{project}/{version}/graphql``. This module
holds the parts of that route that need no request:

* :func:`build_executable_schema` turns the version's canonical model into a ``graphql-core``
  :class:`~graphql.GraphQLSchema`. The normalizer keeps the source SDL on ``CanonicalApi.raw``
  (``raw["sdl"]``), which is the most faithful input, so that is tried first. A model without it
  (or whose SDL no longer builds on its own) is emitted from the canonical ``Type``/``Field`` graph
  by :class:`app.graphql_emitter.GraphQlEmitter`, the same writer the GraphQL export uses.
* :class:`GraphQlMockSettings` is the ``graphql`` key of ``versions.mock_settings``: the depth and
  complexity caps and the length of synthesized lists. Like every other runtime settings parser it
  is lenient. A malformed value falls back to its default and never breaks serving. Author-time
  validation happens in apiome-rest when the settings are saved.
* :func:`measure_operation` computes the depth and complexity of one operation, which the
  transport compares against the caps *before* anything executes.

Introspection fields (``__schema``, ``__type``, ``__typename``) are left out of both measures.
GraphiQL's own introspection query is about a dozen levels deep, so counting it would lock the
landing page out of the schema it is there to show.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.canonical_model import CanonicalApi
from app.graphql_emitter import GraphQlEmitter
from graphql import (
    FieldNode,
    FragmentDefinitionNode,
    FragmentSpreadNode,
    GraphQLError,
    GraphQLNamedType,
    GraphQLSchema,
    InlineFragmentNode,
    OperationDefinitionNode,
    SelectionSetNode,
    build_schema,
    get_named_type,
    get_nullable_type,
    is_list_type,
)

__all__ = [
    "DEFAULT_LIST_LENGTH",
    "DEFAULT_MAX_COMPLEXITY",
    "DEFAULT_MAX_DEPTH",
    "GRAPHQL_SETTINGS_KEY",
    "GraphQlMockSettings",
    "MAX_LIST_LENGTH",
    "OperationMeasure",
    "build_executable_schema",
    "measure_operation",
    "parse_graphql_settings",
]

GRAPHQL_SETTINGS_KEY = "graphql"
"""Key of ``versions.mock_settings`` that holds the GraphQL mock settings."""

DEFAULT_MAX_DEPTH = 10
"""Deepest field nesting an operation may select when the version sets no ``maxDepth``."""

DEFAULT_MAX_COMPLEXITY = 1000
"""Largest complexity score an operation may have when the version sets no ``maxComplexity``."""

DEFAULT_LIST_LENGTH = 3
"""Items in every synthesized list when the version sets no ``listLength``."""

MAX_DEPTH_CEILING = 50
"""Hard ceiling on ``maxDepth``: a stored value above it is clamped."""

MAX_COMPLEXITY_CEILING = 100_000
"""Hard ceiling on ``maxComplexity``: a stored value above it is clamped."""

MAX_LIST_LENGTH = 50
"""Hard ceiling on ``listLength``: a stored value above it is clamped."""


@dataclass(frozen=True)
class GraphQlMockSettings:
    """The GraphQL mock settings of one version (``mock_settings.graphql``).

    Attributes:
        max_depth: Deepest field nesting an operation may select (``maxDepth``).
        max_complexity: Largest complexity score an operation may have (``maxComplexity``). Each
            selected field costs 1, multiplied by ``list_length`` for every list it sits inside.
        list_length: Number of items in every synthesized list (``listLength``).
    """

    max_depth: int = DEFAULT_MAX_DEPTH
    max_complexity: int = DEFAULT_MAX_COMPLEXITY
    list_length: int = DEFAULT_LIST_LENGTH


def _bounded_int(raw: Any, *, default: int, minimum: int, maximum: int) -> int:
    """Read one integer setting, falling back to ``default`` and clamping to ``[minimum, maximum]``.

    Args:
        raw: The stored value (anything; booleans and non-integers are rejected).
        default: The value used when ``raw`` is not an integer.
        minimum: The smallest accepted value.
        maximum: The largest accepted value.

    Returns:
        The integer setting to apply.
    """
    if isinstance(raw, bool) or not isinstance(raw, int):
        return default
    return max(minimum, min(raw, maximum))


def parse_graphql_settings(mock_settings: Any) -> GraphQlMockSettings:
    """Parse the ``graphql`` block of ``versions.mock_settings``.

    Args:
        mock_settings: The raw JSONB value: a dict, JSON text, or ``None``.

    Returns:
        The settings to serve with. Missing or malformed entries take their defaults, and this
        function never raises.
    """
    settings: Any = mock_settings
    if isinstance(settings, str):
        try:
            settings = json.loads(settings)
        except json.JSONDecodeError:
            return GraphQlMockSettings()
    if not isinstance(settings, dict):
        return GraphQlMockSettings()
    block = settings.get(GRAPHQL_SETTINGS_KEY)
    if not isinstance(block, dict):
        return GraphQlMockSettings()
    return GraphQlMockSettings(
        max_depth=_bounded_int(block.get("maxDepth"), default=DEFAULT_MAX_DEPTH, minimum=1, maximum=MAX_DEPTH_CEILING),
        max_complexity=_bounded_int(
            block.get("maxComplexity"),
            default=DEFAULT_MAX_COMPLEXITY,
            minimum=1,
            maximum=MAX_COMPLEXITY_CEILING,
        ),
        list_length=_bounded_int(
            block.get("listLength"), default=DEFAULT_LIST_LENGTH, minimum=0, maximum=MAX_LIST_LENGTH
        ),
    )


def build_executable_schema(api: CanonicalApi) -> GraphQLSchema:
    """Build the ``graphql-core`` schema a GraphQL mock executes against.

    Args:
        api: The version's canonical model (paradigm ``GRAPH``).

    Returns:
        A valid :class:`~graphql.GraphQLSchema` whose type and field names are the canonical keys,
        so a resolver can find the canonical entity behind any field it is asked for.

    Raises:
        ValueError: When neither the stored SDL nor the emitted SDL builds a valid schema.
    """
    raw_sdl = (api.raw or {}).get("sdl")
    if isinstance(raw_sdl, str) and raw_sdl.strip():
        try:
            return build_schema(raw_sdl)
        except (GraphQLError, TypeError):
            # Federated SDL can name directives it does not define; the emitter below writes them.
            pass
    emitted = GraphQlEmitter().emit(api)
    sdl = emitted.files[0].content if emitted.files else ""
    try:
        return build_schema(str(sdl))
    except (GraphQLError, TypeError) as exc:
        raise ValueError(f"The GraphQL schema for this version could not be built: {exc}") from exc


@dataclass(frozen=True)
class OperationMeasure:
    """The size of one operation.

    Attributes:
        depth: Deepest field nesting it selects (``{ user { name } }`` is 2).
        complexity: Fields selected, each multiplied by the list length of every list above it.
    """

    depth: int
    complexity: int


def measure_operation(
    schema: GraphQLSchema,
    operation: OperationDefinitionNode,
    fragments: dict[str, FragmentDefinitionNode],
    *,
    list_length: int,
) -> OperationMeasure:
    """Measure an operation's depth and complexity, fragments expanded.

    Call it on a document that has already passed validation, so every field exists.

    Args:
        schema: The executable schema.
        operation: The operation about to run.
        fragments: The document's fragment definitions by name.
        list_length: The synthesized list length (the multiplier for list-typed fields).

    Returns:
        The operation's :class:`OperationMeasure`.
    """
    root = schema.get_root_type(operation.operation)
    if root is None:
        return OperationMeasure(depth=0, complexity=0)
    depth, complexity = _measure_selection_set(
        schema,
        operation.selection_set,
        root,
        depth=0,
        multiplier=1,
        list_length=max(list_length, 1),
        fragments=fragments,
        visiting=frozenset(),
    )
    return OperationMeasure(depth=depth, complexity=complexity)


def _measure_selection_set(
    schema: GraphQLSchema,
    selection_set: SelectionSetNode,
    parent: GraphQLNamedType,
    *,
    depth: int,
    multiplier: int,
    list_length: int,
    fragments: dict[str, FragmentDefinitionNode],
    visiting: frozenset[str],
) -> tuple[int, int]:
    """Walk one selection set and return ``(deepest depth, complexity)`` below ``depth``.

    Args:
        schema: The executable schema (resolves fragment type conditions).
        selection_set: The selections to measure.
        parent: The type the selections are made on.
        depth: How many field levels sit above this selection set.
        multiplier: Product of the list lengths of every list-typed field above it.
        list_length: The synthesized list length.
        fragments: The document's fragment definitions by name.
        visiting: Fragment names already being expanded (a cycle guard; validation forbids cycles).

    Returns:
        The deepest field depth reached and the summed complexity.
    """
    deepest = depth
    complexity = 0
    for selection in selection_set.selections:
        if isinstance(selection, FieldNode):
            name = selection.name.value
            if name.startswith("__"):
                continue
            complexity += multiplier
            deepest = max(deepest, depth + 1)
            # Object and interface types carry fields; a union selects only through fragments.
            fields = getattr(parent, "fields", None) or {}
            field_def = fields.get(name)
            if selection.selection_set is None or field_def is None:
                continue
            nullable = get_nullable_type(field_def.type)
            child_multiplier = multiplier * (list_length if is_list_type(nullable) else 1)
            child_depth, child_complexity = _measure_selection_set(
                schema,
                selection.selection_set,
                get_named_type(field_def.type),
                depth=depth + 1,
                multiplier=child_multiplier,
                list_length=list_length,
                fragments=fragments,
                visiting=visiting,
            )
            deepest = max(deepest, child_depth)
            complexity += child_complexity
        elif isinstance(selection, InlineFragmentNode):
            condition = selection.type_condition
            target = schema.get_type(condition.name.value) if condition is not None else parent
            child_depth, child_complexity = _measure_selection_set(
                schema,
                selection.selection_set,
                target or parent,
                depth=depth,
                multiplier=multiplier,
                list_length=list_length,
                fragments=fragments,
                visiting=visiting,
            )
            deepest = max(deepest, child_depth)
            complexity += child_complexity
        elif isinstance(selection, FragmentSpreadNode):
            name = selection.name.value
            fragment = fragments.get(name)
            if fragment is None or name in visiting:
                continue
            target = schema.get_type(fragment.type_condition.name.value)
            child_depth, child_complexity = _measure_selection_set(
                schema,
                fragment.selection_set,
                target or parent,
                depth=depth,
                multiplier=multiplier,
                list_length=list_length,
                fragments=fragments,
                visiting=visiting | {name},
            )
            deepest = max(deepest, child_depth)
            complexity += child_complexity
    return deepest, complexity
