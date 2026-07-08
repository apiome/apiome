"""Faceted catalog search — facet vocabulary & filter normalization (V2-MCP-35.1 / MCAT-21.1, #4660).

The catalog grid's rich metrics (grade, safety, complexity, protocol, health) become queryable
*facets*: a caller filters endpoints by any combination of facet values and gets live bucket counts
back. This module is the pure, DB-free half of that feature — the single place the facet
vocabulary (which dimensions exist, which values each accepts, which sentinel names a NULL bucket)
and the request-side normalization live, so the route, the SQL layer, and the tests all agree on
one contract.

Facet semantics (mirrored by the SQL in :mod:`app.database`):

* **Across facets, filters AND** — an endpoint must satisfy every supplied dimension.
* **Within a facet, values OR** — ``grade=A&grade=B`` matches endpoints graded A *or* B.
* **Sentinels select the NULL bucket** — ``ungraded`` (no score yet), ``uncategorized`` (no
  category), and ``unknown`` (no reported protocol / underivable complexity) are real, filterable
  values, so every bucket a count reports can be clicked back into a filter.

Everything here is pure and total: normalizers only validate/canonicalize strings, and
:func:`complexity_band` is the Python mirror of the SQL banding expression so tests can pin the
two to the same thresholds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

# --- Vocabulary -------------------------------------------------------------------------------

#: The A-F letter grades a scored snapshot can carry (see ``mcp_version_scores.grade``).
GRADE_VALUES: Tuple[str, ...] = ("A", "B", "C", "D", "F")

#: Sentinel grade value selecting endpoints whose current snapshot has no grade yet.
UNGRADED_VALUE: str = "ungraded"

#: The transports an endpoint can be registered with (matches the V126 CHECK constraint).
TRANSPORT_VALUES: Tuple[str, ...] = ("streamable_http", "sse", "stdio")

#: Sentinel category value selecting endpoints with no category (NULL or blank).
UNCATEGORIZED_VALUE: str = "uncategorized"

#: Sentinel protocol value selecting endpoints with no reported protocol version (undiscovered,
#: or the server never reported one).
UNKNOWN_VALUE: str = "unknown"

#: Safety posture: the endpoint's current surface has at least one tool asserting
#: ``destructiveHint: true``.
SAFETY_HAS_DESTRUCTIVE: str = "has_destructive"

#: Safety posture: the endpoint's current surface has at least one tool and *every* tool asserts
#: ``readOnlyHint: true`` — the whole surface is declared read-only.
SAFETY_READ_ONLY_ONLY: str = "read_only_only"

#: The safety-posture facet values. Not mutually exclusive complements: an endpoint with no
#: annotated tools matches neither.
SAFETY_VALUES: Tuple[str, ...] = (SAFETY_HAS_DESTRUCTIVE, SAFETY_READ_ONLY_ONLY)

#: Complexity banding thresholds over the *maximum* top-level ``input_schema`` property count
#: across an endpoint's current tools (the same "property count" the 28.1 surface metrics
#: report per tool). A surface whose busiest tool takes ≤ 3 properties is ``simple``; ≤ 7 is
#: ``moderate``; anything above is ``complex``.
COMPLEXITY_SIMPLE_MAX_PROPERTIES: int = 3
COMPLEXITY_MODERATE_MAX_PROPERTIES: int = 7

#: The complexity-band facet values. ``unknown`` is the NULL bucket: an endpoint with no
#: discovered surface or no tools has no schema to band.
COMPLEXITY_VALUES: Tuple[str, ...] = ("simple", "moderate", "complex", UNKNOWN_VALUE)

#: The discovery-health facet values — the same five labels the inventory export derives
#: (:func:`app.mcp_catalog_inventory.derive_health`), in that module's precedence order.
HEALTH_VALUES: Tuple[str, ...] = (
    "quarantined",
    "disabled",
    "undiscovered",
    "failing",
    "healthy",
)


# --- Banding ------------------------------------------------------------------------------------


def complexity_band(max_tool_properties: Optional[int]) -> str:
    """Band an endpoint's busiest-tool property count into its complexity facet value.

    The Python mirror of the SQL banding expression (``Database._MCP_COMPLEXITY_BAND_EXPR``), kept
    next to the thresholds so the two can never drift apart silently — the tests assert both sides
    band identically.

    Args:
        max_tool_properties: The maximum top-level ``input_schema`` property count across the
            endpoint's current tools, or ``None`` when the endpoint has no tools / no surface.

    Returns:
        ``"simple"`` / ``"moderate"`` / ``"complex"``, or ``"unknown"`` for ``None``.
    """
    if max_tool_properties is None:
        return UNKNOWN_VALUE
    if max_tool_properties <= COMPLEXITY_SIMPLE_MAX_PROPERTIES:
        return "simple"
    if max_tool_properties <= COMPLEXITY_MODERATE_MAX_PROPERTIES:
        return "moderate"
    return "complex"


# --- Request normalization ------------------------------------------------------------------------


class FacetValidationError(ValueError):
    """A supplied facet value is not in its facet's vocabulary (the route maps this to a 422)."""


def _cleaned(values: Optional[Sequence[str]]) -> List[str]:
    """Strip, drop blanks, and de-duplicate (order-preserving) a raw multi-value query param."""
    seen: List[str] = []
    for value in values or []:
        v = value.strip()
        if v and v not in seen:
            seen.append(v)
    return seen


def _normalize_enum(
    facet: str, values: Optional[Sequence[str]], allowed: Sequence[str]
) -> List[str]:
    """Normalize a closed-vocabulary facet: lowercase, validate, de-duplicate.

    Args:
        facet: The facet name (for the error message).
        values: The raw values as supplied on the query string.
        allowed: The facet's full vocabulary (lowercase).

    Returns:
        The canonical (lowercased, deduplicated) values, in supplied order.

    Raises:
        FacetValidationError: When a value is outside the vocabulary — the message names the facet
            and lists what it accepts, so the 422 is self-explanatory.
    """
    normalized: List[str] = []
    for value in _cleaned(values):
        canonical = value.lower()
        if canonical not in allowed:
            raise FacetValidationError(
                f"invalid {facet} facet value {value!r}; expected one of: {', '.join(allowed)}"
            )
        if canonical not in normalized:
            normalized.append(canonical)
    return normalized


def _normalize_grades(values: Optional[Sequence[str]]) -> List[str]:
    """Normalize the grade facet: uppercase letters A-F, plus the ``ungraded`` sentinel."""
    normalized: List[str] = []
    for value in _cleaned(values):
        if value.lower() == UNGRADED_VALUE:
            canonical = UNGRADED_VALUE
        else:
            canonical = value.upper()
            if canonical not in GRADE_VALUES:
                raise FacetValidationError(
                    f"invalid grade facet value {value!r}; expected one of: "
                    f"{', '.join(GRADE_VALUES)}, {UNGRADED_VALUE}"
                )
        if canonical not in normalized:
            normalized.append(canonical)
    return normalized


@dataclass(frozen=True)
class CatalogFacetFilters:
    """The validated, canonical facet selection of one faceted-search request.

    Every field is a (possibly empty) list of canonical facet values; an empty list means "no
    constraint on this dimension". Categories and protocols keep their free-form values verbatim
    (matching is case-insensitive for categories, exact for protocols, in SQL) apart from their
    NULL-bucket sentinels, which are canonicalized to lowercase.
    """

    grades: List[str] = field(default_factory=list)
    transports: List[str] = field(default_factory=list)
    categories: List[str] = field(default_factory=list)
    safety: List[str] = field(default_factory=list)
    complexity: List[str] = field(default_factory=list)
    protocols: List[str] = field(default_factory=list)
    health: List[str] = field(default_factory=list)


def normalize_catalog_facet_filters(
    *,
    grade: Optional[Sequence[str]] = None,
    transport: Optional[Sequence[str]] = None,
    category: Optional[Sequence[str]] = None,
    safety: Optional[Sequence[str]] = None,
    complexity: Optional[Sequence[str]] = None,
    protocol: Optional[Sequence[str]] = None,
    health: Optional[Sequence[str]] = None,
) -> CatalogFacetFilters:
    """Validate and canonicalize a faceted-search request's raw facet query params.

    Closed-vocabulary facets (grade, transport, safety, complexity, health) reject values outside
    their vocabulary; free-form facets (category, protocol) are only cleaned (stripped,
    de-blanked, de-duplicated) with their NULL-bucket sentinels canonicalized to lowercase, so a
    typo'd category simply matches nothing rather than erroring.

    Args:
        grade: Raw ``grade`` values (A-F, any case, or ``ungraded``).
        transport: Raw ``transport`` values (``streamable_http`` / ``sse`` / ``stdio``).
        category: Raw ``category`` values (free-form, or ``uncategorized``).
        safety: Raw ``safety`` values (``has_destructive`` / ``read_only_only``).
        complexity: Raw ``complexity`` values (``simple`` / ``moderate`` / ``complex`` / ``unknown``).
        protocol: Raw ``protocol`` values (free-form versions, or ``unknown``).
        health: Raw ``health`` values (the five derived health labels).

    Returns:
        The canonical :class:`CatalogFacetFilters`.

    Raises:
        FacetValidationError: When a closed-vocabulary value is invalid.
    """
    categories = [
        UNCATEGORIZED_VALUE if v.lower() == UNCATEGORIZED_VALUE else v
        for v in _cleaned(category)
    ]
    protocols = [
        UNKNOWN_VALUE if v.lower() == UNKNOWN_VALUE else v for v in _cleaned(protocol)
    ]
    return CatalogFacetFilters(
        grades=_normalize_grades(grade),
        transports=_normalize_enum("transport", transport, TRANSPORT_VALUES),
        categories=categories,
        safety=_normalize_enum("safety", safety, SAFETY_VALUES),
        complexity=_normalize_enum("complexity", complexity, COMPLEXITY_VALUES),
        protocols=protocols,
        health=_normalize_enum("health", health, HEALTH_VALUES),
    )
