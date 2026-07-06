"""
Deterministic capability-surface metrics over a normalized MCP surface (V2-MCP-28.1).

Every insight panel over a discovered MCP server needs the same derived numbers — how
many tools/resources/prompts a surface exposes, how complex each tool's argument schema
is, how much of the surface is documented, and how many tools declare their behavioural
annotations. Computing those ad-hoc per panel duplicates logic and drifts. This module is
the single, pure metrics layer over a version's capability items, so every visualization
reads one canonical set of numbers.

It is the metrics counterpart to :mod:`app.schema_lint` (which lints a reconstructed
OpenAPI/JSON-Schema document) and to :mod:`app.mcp_lint` / :mod:`app.mcp_score` (which lint
and score the same MCP surface). It intentionally mirrors their pure-function style and reuses
the JSON-Schema shape helpers those linters established.

Design goals:

* **Pure** — no database or network access; the caller passes a fully built
  :class:`~app.mcp_client.normalize.DiscoverySurface`. The engine never performs I/O, so it
  is cheap to call at version-creation time or per request.
* **Deterministic** — the same surface always yields the same metrics object and the same
  ``metrics_fingerprint``. Identical surfaces therefore produce byte-identical output, which
  makes the result cacheable per ``surface_fingerprint``.
* **Total** — the schema walk never throws on adversarial input. Nested objects, ``$ref``
  nodes (left unresolved, treated as leaves), ``array`` items, and combinator branches
  (``oneOf``/``anyOf``/``allOf``) are all handled, and a depth budget caps runaway recursion
  on pathological schemas.

The metrics object (:class:`SurfaceMetrics`) carries:

* ``type_counts``            — per-kind item counts (tools/resources/resource templates/prompts).
* ``tool_complexity``        — per tool: input-schema property/required/optional counts, max
  nesting depth, ``enum``/``oneOf`` usage, and output-schema presence.
* ``output_schema_count``    — how many tools declare an ``outputSchema``.
* ``annotation_coverage``    — how many tools assert each behavioural hint
  (``readOnlyHint``/``destructiveHint``/``idempotentHint``/``openWorldHint``).
* ``documentation_coverage`` — % of items with a ``description``, % with a ``title``, and %
  of tool parameters that carry a ``description``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .mcp_client.normalize import CapabilityItem, DiscoverySurface

# --- Configuration --------------------------------------------------------------------------

#: Maximum schema nesting the complexity walk descends before it stops recursing. A generous
#: cap that no realistic tool schema reaches; it exists only so a pathological or maliciously
#: deep ``input_schema`` cannot exhaust the Python recursion limit. Reported depths therefore
#: saturate at this value rather than raising.
MAX_SCHEMA_DEPTH: int = 64

#: The four MCP tool behavioural annotation hints, in a stable order (wire spelling). Coverage
#: counts how many tools assert each one as a JSON boolean.
#: See https://modelcontextprotocol.io/specification/2025-06-18/server/tools#annotations.
ANNOTATION_HINTS: Tuple[str, ...] = (
    "readOnlyHint",
    "destructiveHint",
    "idempotentHint",
    "openWorldHint",
)


# --- Small shared helpers -------------------------------------------------------------------


def _nonempty_str(value: Any) -> bool:
    """True when ``value`` is a non-blank string (mirrors :func:`app.schema_lint._nonempty_str`)."""
    return isinstance(value, str) and value.strip() != ""


def _pct(numerator: int, denominator: int) -> float:
    """Return ``numerator/denominator`` as a 0-100 percentage rounded to two decimals.

    A zero denominator yields ``0.0`` (an empty population is 0% covered, never a divide-by-zero).
    The result is always within ``[0.0, 100.0]`` for the ``0 <= numerator <= denominator`` inputs
    this module produces. Rounding is deterministic so identical surfaces hash identically.
    """
    if denominator <= 0:
        return 0.0
    return round(100.0 * numerator / denominator, 2)


def _bool_hint(annotations: Optional[Mapping[str, Any]], key: str) -> Optional[bool]:
    """Return a tool annotation hint as a strict ``bool``, or ``None`` when not a clean bool.

    Mirrors :func:`app.mcp_lint_annotations._bool_hint`: a missing key, a non-mapping
    ``annotations``, or a non-boolean value (e.g. the string ``"true"``) is treated as *unset*
    (``None``) so a hint is only counted as asserted when the server actually declared it as a
    JSON boolean.

    Args:
        annotations: The tool's normalized ``annotations`` object (may be ``None``).
        key: The hint name to read.

    Returns:
        ``True``/``False`` only when the hint is present and is a JSON boolean; else ``None``.
    """
    if not isinstance(annotations, Mapping):
        return None
    value = annotations.get(key)
    return value if isinstance(value, bool) else None


def _child_schemas(schema: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    """Return the immediate sub-schemas nested inside ``schema``.

    Collects the structural children a JSON Schema node can carry: object ``properties``
    values, ``array`` ``items`` (a single schema or a tuple list) and 2020-12 ``prefixItems``,
    a schema-form ``additionalProperties``, and the branches of the ``oneOf``/``anyOf``/``allOf``
    combinators. A pure ``$ref`` node carries none of these, so it is treated as a leaf and the
    reference is never resolved — that is what keeps the walk total on ``$ref``/recursive schemas.

    Args:
        schema: A JSON Schema object node.

    Returns:
        Every immediate child schema that is itself a mapping, in a deterministic order. Non-dict
        entries (a boolean ``additionalProperties``, a malformed ``items``) are skipped.
    """
    children: List[Mapping[str, Any]] = []

    props = schema.get("properties")
    if isinstance(props, dict):
        children.extend(v for v in props.values() if isinstance(v, Mapping))

    items = schema.get("items")
    if isinstance(items, Mapping):
        children.append(items)
    elif isinstance(items, list):  # draft-04 tuple validation
        children.extend(v for v in items if isinstance(v, Mapping))

    prefix_items = schema.get("prefixItems")
    if isinstance(prefix_items, list):  # 2020-12 tuple validation
        children.extend(v for v in prefix_items if isinstance(v, Mapping))

    additional = schema.get("additionalProperties")
    if isinstance(additional, Mapping):
        children.append(additional)

    for combinator in ("oneOf", "anyOf", "allOf"):
        branch = schema.get(combinator)
        if isinstance(branch, list):
            children.extend(v for v in branch if isinstance(v, Mapping))

    return children


@dataclass(frozen=True)
class _SchemaWalk:
    """The aggregate signals one recursive pass over a schema collects."""

    depth: int
    uses_enum: bool
    uses_one_of: bool


def _walk_schema(schema: Any, budget: int) -> _SchemaWalk:
    """Recursively measure a schema's nesting depth and ``enum``/``oneOf`` usage.

    Nesting depth counts *levels of containers*: a leaf (scalar, ``$ref``, or any node with no
    structural children) is depth ``0``; a flat object of scalar properties is depth ``1``; an
    object whose property is itself an object is depth ``2``; and so on for arrays and combinator
    branches. ``uses_enum``/``uses_one_of`` are ``True`` when an ``enum``/``oneOf`` keyword appears
    anywhere in the (bounded) subtree.

    The walk is total: a non-mapping node returns the empty signal, ``$ref`` nodes are leaves
    (never resolved), and the ``budget`` decrements on each descent so a pathological schema
    saturates at :data:`MAX_SCHEMA_DEPTH` instead of overflowing the stack.

    Args:
        schema: The schema node to measure (any type; non-mappings are treated as leaves).
        budget: Remaining recursion allowance; when it reaches zero the walk stops descending.

    Returns:
        A :class:`_SchemaWalk` with the subtree's depth and enum/oneOf flags.
    """
    if not isinstance(schema, Mapping) or budget <= 0:
        return _SchemaWalk(depth=0, uses_enum=False, uses_one_of=False)

    uses_enum = isinstance(schema.get("enum"), list)
    uses_one_of = isinstance(schema.get("oneOf"), list)

    children = _child_schemas(schema)
    if not children:
        return _SchemaWalk(depth=0, uses_enum=uses_enum, uses_one_of=uses_one_of)

    max_child_depth = 0
    for child in children:
        walk = _walk_schema(child, budget - 1)
        max_child_depth = max(max_child_depth, walk.depth)
        uses_enum = uses_enum or walk.uses_enum
        uses_one_of = uses_one_of or walk.uses_one_of

    return _SchemaWalk(depth=1 + max_child_depth, uses_enum=uses_enum, uses_one_of=uses_one_of)


# --- Metric value objects -------------------------------------------------------------------


@dataclass(frozen=True)
class TypeCounts:
    """Per-kind capability item counts of a surface (plus their total)."""

    tools: int
    resources: int
    resource_templates: int
    prompts: int
    total: int

    def as_dict(self) -> Dict[str, int]:
        return {
            "tools": self.tools,
            "resources": self.resources,
            "resource_templates": self.resource_templates,
            "prompts": self.prompts,
            "total": self.total,
        }


@dataclass(frozen=True)
class ToolComplexity:
    """The complexity profile of a single tool's ``input_schema`` (and its output-schema flag).

    Attributes:
        name: The tool's programmatic name (``""`` when the server omitted it).
        property_count: Number of top-level ``properties`` in ``input_schema``.
        required_count: Top-level properties named in the schema's ``required`` list.
        optional_count: ``property_count - required_count`` (never negative).
        documented_property_count: Top-level properties carrying a non-blank ``description``.
        max_nesting_depth: Deepest level of nested containers in ``input_schema`` (0 for a flat
            or absent schema; saturates at :data:`MAX_SCHEMA_DEPTH`).
        uses_enum: Whether an ``enum`` keyword appears anywhere in ``input_schema``.
        uses_one_of: Whether a ``oneOf`` keyword appears anywhere in ``input_schema``.
        has_output_schema: Whether the tool declares a non-empty ``output_schema``.
    """

    name: str
    property_count: int
    required_count: int
    optional_count: int
    documented_property_count: int
    max_nesting_depth: int
    uses_enum: bool
    uses_one_of: bool
    has_output_schema: bool

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "property_count": self.property_count,
            "required_count": self.required_count,
            "optional_count": self.optional_count,
            "documented_property_count": self.documented_property_count,
            "max_nesting_depth": self.max_nesting_depth,
            "uses_enum": self.uses_enum,
            "uses_one_of": self.uses_one_of,
            "has_output_schema": self.has_output_schema,
        }


@dataclass(frozen=True)
class AnnotationCoverage:
    """How many of a surface's tools assert each behavioural annotation hint.

    Each per-hint count is the number of tools whose ``annotations`` declare that hint as a JSON
    boolean (``readOnlyHint:false`` counts as asserted — the server made a claim). ``annotated_tools``
    is the number of tools asserting *at least one* of the four hints. ``tool_count`` is the divisor
    for turning any of these into a percentage.

    Attributes:
        tool_count: Total number of tools on the surface.
        annotated_tools: Tools asserting at least one behavioural hint.
        read_only_hint / destructive_hint / idempotent_hint / open_world_hint: Per-hint asserted counts.
    """

    tool_count: int
    annotated_tools: int
    read_only_hint: int
    destructive_hint: int
    idempotent_hint: int
    open_world_hint: int

    def as_dict(self) -> Dict[str, int]:
        return {
            "tool_count": self.tool_count,
            "annotated_tools": self.annotated_tools,
            "read_only_hint": self.read_only_hint,
            "destructive_hint": self.destructive_hint,
            "idempotent_hint": self.idempotent_hint,
            "open_world_hint": self.open_world_hint,
        }


@dataclass(frozen=True)
class DocumentationCoverage:
    """Documentation completeness of a surface, as raw counts and 0-100 percentages.

    Item-level coverage spans every capability kind; parameter-level coverage spans the top-level
    properties of every tool's ``input_schema``. All percentages are in ``[0, 100]`` and are ``0.0``
    when their population is empty.

    Attributes:
        item_count: Total capability items across all kinds.
        described_items / titled_items: Items with a non-blank ``description`` / ``title``.
        description_pct / title_pct: The above as percentages of ``item_count``.
        tool_param_count: Total top-level tool input-schema properties across all tools.
        documented_tool_params: Those properties carrying a non-blank ``description``.
        tool_param_description_pct: ``documented_tool_params`` as a percentage of ``tool_param_count``.
    """

    item_count: int
    described_items: int
    titled_items: int
    description_pct: float
    title_pct: float
    tool_param_count: int
    documented_tool_params: int
    tool_param_description_pct: float

    def as_dict(self) -> Dict[str, Any]:
        return {
            "item_count": self.item_count,
            "described_items": self.described_items,
            "titled_items": self.titled_items,
            "description_pct": self.description_pct,
            "title_pct": self.title_pct,
            "tool_param_count": self.tool_param_count,
            "documented_tool_params": self.documented_tool_params,
            "tool_param_description_pct": self.tool_param_description_pct,
        }


@dataclass(frozen=True)
class SurfaceMetrics:
    """The full, deterministic metrics roll-up for one MCP discovery surface.

    Attributes:
        type_counts: Per-kind item counts.
        tool_complexity: Per-tool input-schema complexity, in surface (ordinal) order.
        output_schema_count: How many tools declare a non-empty ``output_schema``.
        annotation_coverage: Per-hint behavioural-annotation coverage over the tools.
        documentation_coverage: Item- and parameter-level documentation coverage.
        metrics_fingerprint: Stable SHA-256 over the whole metrics payload; identical surfaces
            yield the same fingerprint, so a caller can cache the result per ``surface_fingerprint``.
    """

    type_counts: TypeCounts
    tool_complexity: Tuple[ToolComplexity, ...]
    output_schema_count: int
    annotation_coverage: AnnotationCoverage
    documentation_coverage: DocumentationCoverage
    metrics_fingerprint: str

    def as_dict(self) -> Dict[str, Any]:
        """Return the full metrics object as a JSON-ready dict with a stable key set/order."""
        return {
            "type_counts": self.type_counts.as_dict(),
            "tool_complexity": [tool.as_dict() for tool in self.tool_complexity],
            "output_schema_count": self.output_schema_count,
            "annotation_coverage": self.annotation_coverage.as_dict(),
            "documentation_coverage": self.documentation_coverage.as_dict(),
            "metrics_fingerprint": self.metrics_fingerprint,
        }


# --- Per-metric computation -----------------------------------------------------------------


def _type_counts(surface: DiscoverySurface) -> TypeCounts:
    """Count the surface's items per kind."""
    tools = len(surface.tools)
    resources = len(surface.resources)
    resource_templates = len(surface.resource_templates)
    prompts = len(surface.prompts)
    return TypeCounts(
        tools=tools,
        resources=resources,
        resource_templates=resource_templates,
        prompts=prompts,
        total=tools + resources + resource_templates + prompts,
    )


def _top_level_properties(input_schema: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Return the top-level ``properties`` map of an ``input_schema``, or ``{}`` when absent.

    Tolerates a ``None`` schema, a non-mapping schema, or a missing/malformed ``properties`` block
    (e.g. a schema that is not an object) by returning an empty map, so callers never guard the shape.
    """
    if not isinstance(input_schema, Mapping):
        return {}
    props = input_schema.get("properties")
    return dict(props) if isinstance(props, dict) else {}


def _tool_complexity(tool: CapabilityItem) -> ToolComplexity:
    """Compute the :class:`ToolComplexity` profile for one tool item.

    Top-level ``properties`` drive the property/required/optional and documented-parameter counts;
    the recursive :func:`_walk_schema` supplies the max nesting depth and enum/oneOf usage. A tool
    with no ``input_schema`` (or a non-object one) reports all-zero counts and depth 0.
    """
    properties = _top_level_properties(tool.input_schema)
    property_count = len(properties)

    required_raw = (
        tool.input_schema.get("required") if isinstance(tool.input_schema, Mapping) else None
    )
    required_names = (
        {name for name in required_raw if isinstance(name, str)}
        if isinstance(required_raw, list)
        else set()
    )
    # Only count required names that actually name a declared property, so a stray/duplicate
    # entry in ``required`` can never push required_count above property_count (or optional below 0).
    required_count = sum(1 for name in properties if name in required_names)
    optional_count = property_count - required_count

    documented_property_count = sum(
        1
        for value in properties.values()
        if isinstance(value, Mapping) and _nonempty_str(value.get("description"))
    )

    walk = _walk_schema(tool.input_schema, MAX_SCHEMA_DEPTH)

    return ToolComplexity(
        name=tool.name,
        property_count=property_count,
        required_count=required_count,
        optional_count=optional_count,
        documented_property_count=documented_property_count,
        max_nesting_depth=walk.depth,
        uses_enum=walk.uses_enum,
        uses_one_of=walk.uses_one_of,
        has_output_schema=bool(tool.output_schema),
    )


def _annotation_coverage(surface: DiscoverySurface) -> AnnotationCoverage:
    """Tally how many tools assert each behavioural annotation hint."""
    per_hint = {hint: 0 for hint in ANNOTATION_HINTS}
    annotated_tools = 0
    for tool in surface.tools:
        asserted = [hint for hint in ANNOTATION_HINTS if _bool_hint(tool.annotations, hint) is not None]
        for hint in asserted:
            per_hint[hint] += 1
        if asserted:
            annotated_tools += 1
    return AnnotationCoverage(
        tool_count=len(surface.tools),
        annotated_tools=annotated_tools,
        read_only_hint=per_hint["readOnlyHint"],
        destructive_hint=per_hint["destructiveHint"],
        idempotent_hint=per_hint["idempotentHint"],
        open_world_hint=per_hint["openWorldHint"],
    )


def _documentation_coverage(
    surface: DiscoverySurface, tool_complexity: Tuple[ToolComplexity, ...]
) -> DocumentationCoverage:
    """Compute item- and parameter-level documentation coverage.

    Item coverage walks every capability kind; parameter coverage reuses the already-computed
    per-tool :class:`ToolComplexity` (so the top-level tool properties are counted exactly once).
    """
    items = surface.all_items()
    item_count = len(items)
    described_items = sum(1 for item in items if _nonempty_str(item.description))
    titled_items = sum(1 for item in items if _nonempty_str(item.title))

    tool_param_count = sum(tool.property_count for tool in tool_complexity)
    documented_tool_params = sum(tool.documented_property_count for tool in tool_complexity)

    return DocumentationCoverage(
        item_count=item_count,
        described_items=described_items,
        titled_items=titled_items,
        description_pct=_pct(described_items, item_count),
        title_pct=_pct(titled_items, item_count),
        tool_param_count=tool_param_count,
        documented_tool_params=documented_tool_params,
        tool_param_description_pct=_pct(documented_tool_params, tool_param_count),
    )


def _metrics_fingerprint(payload: Mapping[str, Any]) -> str:
    """Stable SHA-256 over the metrics ``payload`` (sorted keys, compact separators).

    Two surfaces that yield equal metrics hash equal, so a caller can key a cache on this value
    (or compare it against a ``surface_fingerprint``-scoped cache entry) to skip recomputation.
    """
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


# --- Engine entry point ---------------------------------------------------------------------


def compute_surface_metrics(surface: DiscoverySurface) -> SurfaceMetrics:
    """Compute the deterministic :class:`SurfaceMetrics` for an MCP discovery ``surface``.

    Pure and total: the surface is never mutated, no I/O is performed, and the schema walk never
    throws on nested/``$ref``/array/combinator schemas. The same surface always produces the same
    metrics and the same ``metrics_fingerprint``, so the result is safe to cache per
    ``surface_fingerprint``.

    Args:
        surface: The normalized MCP capability surface to measure.

    Returns:
        The rolled-up :class:`SurfaceMetrics` (per-type counts, per-tool complexity, output-schema
        count, annotation coverage, documentation coverage, and a stable fingerprint).
    """
    type_counts = _type_counts(surface)
    tool_complexity = tuple(_tool_complexity(tool) for tool in surface.tools)
    output_schema_count = sum(1 for tool in tool_complexity if tool.has_output_schema)
    annotation_coverage = _annotation_coverage(surface)
    documentation_coverage = _documentation_coverage(surface, tool_complexity)

    # Fingerprint over the assembled payload *minus* the fingerprint field itself, so the digest is
    # a pure function of the metric values. Assembling the dict once and hashing it keeps the hashed
    # bytes identical to what ``as_dict`` exposes (sans fingerprint), so identity never drifts.
    payload: Dict[str, Any] = {
        "type_counts": type_counts.as_dict(),
        "tool_complexity": [tool.as_dict() for tool in tool_complexity],
        "output_schema_count": output_schema_count,
        "annotation_coverage": annotation_coverage.as_dict(),
        "documentation_coverage": documentation_coverage.as_dict(),
    }
    fingerprint = _metrics_fingerprint(payload)

    return SurfaceMetrics(
        type_counts=type_counts,
        tool_complexity=tool_complexity,
        output_schema_count=output_schema_count,
        annotation_coverage=annotation_coverage,
        documentation_coverage=documentation_coverage,
        metrics_fingerprint=fingerprint,
    )
