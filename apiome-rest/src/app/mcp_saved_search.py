"""Saved catalog searches — filter vocabulary & normalization (V2-MCP-35.3 / MCAT-21.3, #4662).

Persists named filter sets per user/tenant so operators can save, recall, and re-run catalog
searches. This module is the pure, DB-free half: the filter JSON shape the UI stores, validation,
and the mapping from a saved bundle onto the faceted-search query params the ``/run`` route
dispatches.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .mcp_facets import FacetValidationError, normalize_catalog_facet_filters

#: Filter dimensions persisted with every saved search (mirrors the ADE ``McpCatalogFilters``).
FILTER_KEYS: Tuple[str, ...] = (
    "hosts",
    "grades",
    "transports",
    "visibilities",
    "auths",
    "categories",
    "safeties",
    "complexities",
    "protocols",
    "healths",
)

#: Default empty filter state — every dimension is an empty list.
EMPTY_FILTERS: Dict[str, List[str]] = {key: [] for key in FILTER_KEYS}

#: Sort keys the catalog toolbar accepts.
SORT_KEYS: Tuple[str, ...] = ("grade", "name", "recency", "capabilities", "health")
DEFAULT_SORT: str = "grade"


class SavedSearchValidationError(ValueError):
    """A saved-search payload field is invalid (the route maps this to a 422)."""


def _clean_string_list(values: Any, *, field: str) -> List[str]:
    """Coerce a JSON value to a de-duplicated list of non-blank strings."""
    if values is None:
        return []
    if not isinstance(values, list):
        raise SavedSearchValidationError(f"{field} must be a list of strings")
    seen: List[str] = []
    for value in values:
        if not isinstance(value, str):
            raise SavedSearchValidationError(f"{field} must be a list of strings")
        text = value.strip()
        if text and text not in seen:
            seen.append(text)
    return seen


def normalize_saved_search_filters(raw: Any) -> Dict[str, List[str]]:
    """Validate and canonicalize the ``filters`` object of a saved search.

    Args:
        raw: The filters payload (typically parsed JSONB).

    Returns:
        A dict with every :data:`FILTER_KEYS` dimension present as a string list.

    Raises:
        SavedSearchValidationError: When the payload is not an object or a dimension is malformed.
    """
    if raw is None:
        return deepcopy(EMPTY_FILTERS)
    if not isinstance(raw, Mapping):
        raise SavedSearchValidationError("filters must be an object")
    normalized = deepcopy(EMPTY_FILTERS)
    for key in FILTER_KEYS:
        if key in raw:
            normalized[key] = _clean_string_list(raw[key], field=f"filters.{key}")
    return normalized


def normalize_saved_search_sort(raw: Any) -> str:
    """Validate a saved search sort key."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return DEFAULT_SORT
    if not isinstance(raw, str):
        raise SavedSearchValidationError("sort must be a string")
    key = raw.strip()
    if key not in SORT_KEYS:
        raise SavedSearchValidationError(
            f"invalid sort {raw!r}; expected one of: {', '.join(SORT_KEYS)}"
        )
    return key


def normalize_saved_search_query(raw: Any) -> str:
    """Validate a saved search free-text query (blank allowed)."""
    if raw is None:
        return ""
    if not isinstance(raw, str):
        raise SavedSearchValidationError("query must be a string")
    return raw


def normalize_saved_search_name(raw: Any) -> str:
    """Validate a saved search name (non-blank after trim)."""
    if not isinstance(raw, str):
        raise SavedSearchValidationError("name must be a string")
    name = raw.strip()
    if not name:
        raise SavedSearchValidationError("name must not be blank")
    if len(name) > 120:
        raise SavedSearchValidationError("name must be at most 120 characters")
    return name


def saved_filters_to_facet_kwargs(
    filters: Mapping[str, Sequence[str]],
) -> Tuple[Dict[str, Any], Optional[str]]:
    """Map a saved filter bundle onto faceted-search query kwargs.

    Host/auth dimensions are client-side only on the browse page; the server-side ``/run`` route
    applies the facet-compatible subset via :func:`normalize_catalog_facet_filters`.

    Args:
        filters: Canonical saved filters (output of :func:`normalize_saved_search_filters`).

    Returns:
        A ``(facet_kwargs, visibility)`` pair where ``facet_kwargs`` is suitable for
        :func:`normalize_catalog_facet_filters` and ``visibility`` is an optional single
        ``private``/``public`` filter when exactly one visibility is selected.

    Raises:
        FacetValidationError: When a facet-compatible value is outside the facet vocabulary.
    """
    visibilities = list(filters.get("visibilities") or [])
    visibility: Optional[str] = None
    if len(visibilities) == 1:
        vis = visibilities[0].strip().lower()
        if vis in ("private", "public"):
            visibility = vis

    facet_kwargs = normalize_catalog_facet_filters(
        grade=list(filters.get("grades") or []),
        transport=list(filters.get("transports") or []),
        category=list(filters.get("categories") or []),
        safety=list(filters.get("safeties") or []),
        complexity=list(filters.get("complexities") or []),
        protocol=list(filters.get("protocols") or []),
        health=list(filters.get("healths") or []),
    )
    return {
        "grades": facet_kwargs.grades,
        "transports": facet_kwargs.transports,
        "categories": facet_kwargs.categories,
        "safety": facet_kwargs.safety,
        "complexity": facet_kwargs.complexity,
        "protocols": facet_kwargs.protocols,
        "health": facet_kwargs.health,
    }, visibility
