"""Catalog categorization (MFI-6.3, #3755).

A catalog item is categorized three ways, and each is a browse facet on
``GET /v1/catalog/{tenant}``:

* **Paradigm** — *auto-derived*: the latest revision's ``versions.protocol`` (MFI-7.1), the
  canonical :class:`~app.canonical_model.ApiParadigm` (``rest``, ``rpc``, ``event``, ``graph``,
  ``data_schema``, ``agent``). Nothing is stored for it here.
* **Domain** — *manual*: the project's ``metadata.domainCategory``, from the same allow-list the
  Projects screen and the CLI use (:data:`app.projects_routes.PROJECT_DOMAIN_CATEGORY_IDS`). A
  free-text ``metadata.domain`` (older imports) still wins, exactly as the public browse
  directory reads it.
* **Tags** — *manual*, free-form: rows in ``apiome.artifact_tags`` (V277), lower-cased.

The facet semantics are the MCP catalog's (:mod:`app.mcp_facets`) and the public browse
directory's (:mod:`app.browse_facets`): facets AND together and the values within one facet OR;
an unknown value narrows to nothing rather than erroring; an item with no value for a facet
falls in the ``uncategorized`` bucket, which can itself be selected; and each facet's counts are
computed over the items every *other* facet leaves, so a count answers "how many would I see if I
ticked this".

Everything here is pure — the routes load rows and tags, then call :func:`filter_catalog_items`
and :func:`catalog_facet_counts`.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, Iterable, List, Mapping, Optional, Sequence

from .browse_facets import (
    format_label,
    normalize_format_filter,
    normalize_protocol_filter,
    protocol_label,
)
from .projects_routes import PROJECT_DOMAIN_CATEGORY_IDS

__all__ = [
    "MAX_TAGS_PER_ITEM",
    "MAX_TAG_LENGTH",
    "UNCATEGORIZED",
    "CatalogCategoryError",
    "CatalogFacetFilters",
    "catalog_domain_label",
    "catalog_facet_counts",
    "filter_catalog_items",
    "item_domain",
    "item_format",
    "item_paradigm",
    "normalize_domain",
    "normalize_tag",
    "normalize_tags",
]

#: The bucket for an item with no value in a facet; selectable like any other value.
UNCATEGORIZED = "uncategorized"

#: Longest tag accepted (matches ``artifact_tags.tag VARCHAR(64)``).
MAX_TAG_LENGTH = 64

#: Most tags one catalog item may carry — enough to describe it, few enough to stay a facet.
MAX_TAGS_PER_ITEM = 20

#: The domain ids a catalog item may be given, in the order the pickers list them.
DOMAIN_IDS: Sequence[str] = tuple(PROJECT_DOMAIN_CATEGORY_IDS)

#: Display names for the domain ids (kept in step with apiome-ui `project-domain-categories.ts`).
_DOMAIN_LABELS: Mapping[str, str] = {
    "iot": "IoT",
    "social": "Social",
    "gaming": "Gaming",
    "travel": "Travel",
    "media": "Media",
    "ecommerce": "E-commerce",
    "healthcare": "Healthcare",
    "finance": "Finance",
    "saas": "SaaS",
    "education": "Education",
    "realestate": "Real estate",
    "logistics": "Logistics",
}

_WHITESPACE_RE = re.compile(r"\s+")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


class CatalogCategoryError(ValueError):
    """A domain or tag the API refuses, with a message fit for a 422."""


# ---------------------------------------------------------------------------
# Writes: what a caller may set
# ---------------------------------------------------------------------------


def normalize_tag(raw: Any) -> str:
    """Return the stored form of one tag: trimmed, lower-cased, inner whitespace collapsed.

    Raises:
        CatalogCategoryError: When the tag is not text, is empty, is longer than
            :data:`MAX_TAG_LENGTH`, contains a control character, or is the reserved
            :data:`UNCATEGORIZED` bucket name.
    """
    if not isinstance(raw, str):
        raise CatalogCategoryError("A tag must be text.")
    tag = _WHITESPACE_RE.sub(" ", raw).strip().lower()
    if not tag:
        raise CatalogCategoryError("A tag cannot be empty.")
    if len(tag) > MAX_TAG_LENGTH:
        raise CatalogCategoryError(f"A tag can be at most {MAX_TAG_LENGTH} characters: {tag[:20]}…")
    if _CONTROL_RE.search(tag):
        raise CatalogCategoryError("A tag cannot contain control characters.")
    if tag == UNCATEGORIZED:
        raise CatalogCategoryError(f"'{UNCATEGORIZED}' is reserved for items with no tags.")
    return tag


def normalize_tags(raw: Optional[Iterable[Any]]) -> List[str]:
    """Normalize a tag list: each tag via :func:`normalize_tag`, duplicates dropped, order kept.

    Raises:
        CatalogCategoryError: On any invalid tag, or more than :data:`MAX_TAGS_PER_ITEM`.
    """
    tags: List[str] = []
    for value in raw or []:
        tag = normalize_tag(value)
        if tag not in tags:
            tags.append(tag)
    if len(tags) > MAX_TAGS_PER_ITEM:
        raise CatalogCategoryError(f"A catalog item can carry at most {MAX_TAGS_PER_ITEM} tags.")
    return tags


def normalize_domain(raw: Optional[str]) -> Optional[str]:
    """Return the stored domain id, or ``None`` to clear it.

    ``None``, an empty string and ``"none"`` (the pickers' "no domain" choice) all clear it.

    Raises:
        CatalogCategoryError: When the value is not one of :data:`DOMAIN_IDS`.
    """
    if raw is None:
        return None
    value = raw.strip().lower()
    if value in ("", "none"):
        return None
    if value not in DOMAIN_IDS:
        raise CatalogCategoryError(
            f"Unknown domain {raw!r}; expected one of {', '.join(DOMAIN_IDS)}."
        )
    return value


# ---------------------------------------------------------------------------
# Reads: what an item is
# ---------------------------------------------------------------------------


def item_paradigm(item: Mapping[str, Any]) -> Optional[str]:
    """The item's auto-derived paradigm — its latest revision's ``protocol``, normalized."""
    return normalize_protocol_filter(item.get("protocol"))


def item_format(item: Mapping[str, Any]) -> Optional[str]:
    """The item's source format — its latest revision's ``source_format``, normalized."""
    return normalize_format_filter(item.get("source_format"))


def item_domain(item: Mapping[str, Any]) -> Optional[str]:
    """The item's manual domain, read exactly as the public browse directory reads it.

    A free-text ``metadata.domain`` wins; otherwise ``metadata.domainCategory`` (``none`` means
    unset). The value is lower-cased; ``None`` when neither is set.
    """
    metadata = item.get("metadata")
    if not isinstance(metadata, Mapping):
        return None
    free_text = metadata.get("domain")
    if isinstance(free_text, str) and free_text.strip():
        return free_text.strip().lower()
    category = metadata.get("domainCategory")
    if isinstance(category, str) and category.strip().lower() not in ("", "none"):
        return category.strip().lower()
    return None


def catalog_domain_label(value: str) -> str:
    """Display name for a domain id (a free-text domain is shown as written)."""
    if value == UNCATEGORIZED:
        return "No domain"
    return _DOMAIN_LABELS.get(value, value)


# ---------------------------------------------------------------------------
# Facets
# ---------------------------------------------------------------------------


def _normalized_set(values: Optional[Iterable[str]], normalize) -> FrozenSet[str]:
    """Normalize each selected value; the ``uncategorized`` bucket passes through as-is."""
    selected = set()
    for value in values or []:
        if not isinstance(value, str) or not value.strip():
            continue
        if value.strip().lower() == UNCATEGORIZED:
            selected.add(UNCATEGORIZED)
            continue
        normalized = normalize(value)
        # An unknown value is kept (lower-cased) so it narrows to nothing, never to everything.
        selected.add(normalized if normalized else value.strip().lower())
    return frozenset(selected)


def _lower(value: str) -> Optional[str]:
    return value.strip().lower() or None


@dataclass(frozen=True)
class CatalogFacetFilters:
    """The facet selection a list or facet request carries (empty set = no filter)."""

    protocols: FrozenSet[str] = field(default_factory=frozenset)
    formats: FrozenSet[str] = field(default_factory=frozenset)
    domains: FrozenSet[str] = field(default_factory=frozenset)
    tags: FrozenSet[str] = field(default_factory=frozenset)

    @classmethod
    def from_query(
        cls,
        *,
        protocols: Optional[Iterable[str]] = None,
        formats: Optional[Iterable[str]] = None,
        domains: Optional[Iterable[str]] = None,
        tags: Optional[Iterable[str]] = None,
    ) -> "CatalogFacetFilters":
        """Normalize raw query values into a filter set."""
        return cls(
            protocols=_normalized_set(protocols, normalize_protocol_filter),
            formats=_normalized_set(formats, normalize_format_filter),
            domains=_normalized_set(domains, _lower),
            tags=_normalized_set(tags, _lower),
        )

    @property
    def active(self) -> bool:
        """Whether any facet is selected."""
        return bool(self.protocols or self.formats or self.domains or self.tags)


def _item_values(item: Mapping[str, Any], tags: Sequence[str]) -> Dict[str, FrozenSet[str]]:
    """Each facet's values for one item (the ``uncategorized`` bucket when it has none)."""
    paradigm = item_paradigm(item)
    fmt = item_format(item)
    domain = item_domain(item)
    return {
        "protocols": frozenset({paradigm or UNCATEGORIZED}),
        "formats": frozenset({fmt or UNCATEGORIZED}),
        "domains": frozenset({domain or UNCATEGORIZED}),
        "tags": frozenset(tags) if tags else frozenset({UNCATEGORIZED}),
    }


def _passes(values: Mapping[str, FrozenSet[str]], filters: CatalogFacetFilters, skip: str = "") -> bool:
    """AND across facets, OR within one; ``skip`` ignores one facet (for its own counts)."""
    for facet in ("protocols", "formats", "domains", "tags"):
        if facet == skip:
            continue
        selected = getattr(filters, facet)
        if selected and not (values[facet] & selected):
            return False
    return True


def filter_catalog_items(
    items: Sequence[Mapping[str, Any]],
    tags_by_item: Mapping[str, Sequence[str]],
    filters: CatalogFacetFilters,
) -> List[Mapping[str, Any]]:
    """Return the items the facet selection keeps, in their original order.

    Args:
        items: Catalog rows (``id``, ``protocol``, ``source_format``, ``metadata``).
        tags_by_item: Each item id's tags (missing → no tags).
        filters: The selection.
    """
    if not filters.active:
        return list(items)
    return [
        item
        for item in items
        if _passes(_item_values(item, tags_by_item.get(str(item["id"]), ())), filters)
    ]


def _buckets(counter: Counter, label, selected: FrozenSet[str]) -> List[Dict[str, Any]]:
    """Facet buckets, most items first then by label; a selected value stays listed at 0."""
    for value in selected:
        counter.setdefault(value, 0)
    ordered = sorted(
        counter.items(),
        key=lambda pair: (pair[0] == UNCATEGORIZED, -pair[1], str(label(pair[0])).lower()),
    )
    return [
        {"value": value, "label": label(value), "count": count, "selected": value in selected}
        for value, count in ordered
    ]


def _protocol_bucket_label(value: str) -> str:
    return "Unknown paradigm" if value == UNCATEGORIZED else protocol_label(value)


def _format_bucket_label(value: str) -> str:
    return "Unknown format" if value == UNCATEGORIZED else format_label(value)


def _tag_bucket_label(value: str) -> str:
    return "No tags" if value == UNCATEGORIZED else value


def catalog_facet_counts(
    items: Sequence[Mapping[str, Any]],
    tags_by_item: Mapping[str, Sequence[str]],
    filters: CatalogFacetFilters,
) -> Dict[str, List[Dict[str, Any]]]:
    """Count every facet's values over the items the *other* facets leave.

    Returns:
        ``{"protocols", "formats", "domains", "tags"}`` → buckets of
        ``{value, label, count, selected}``.
    """
    rows = [(_item_values(item, tags_by_item.get(str(item["id"]), ()))) for item in items]
    labels = {
        "protocols": _protocol_bucket_label,
        "formats": _format_bucket_label,
        "domains": catalog_domain_label,
        "tags": _tag_bucket_label,
    }
    result: Dict[str, List[Dict[str, Any]]] = {}
    for facet, label in labels.items():
        counter: Counter = Counter()
        for values in rows:
            if _passes(values, filters, skip=facet):
                counter.update(values[facet])
        result[facet] = _buckets(counter, label, getattr(filters, facet))
    return result
