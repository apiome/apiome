"""MCP catalog categorization model & manual tags — vocabulary and normalization (V2-MCP-23.3 / MCAT-9.3, #3693).

Catalogers sort endpoints into **categories** (a lookup of built-in plus tenant-defined entries, V365
``mcp_categories``) and label them with free-form **tags** (V365 ``mcp_endpoint_tags``). Both become
facets on browse and search. This module is the pure, DB-free half: the built-in vocabulary, the
tag / category-slug normalizers, and the lenient category resolver the endpoint create/patch routes
use. The route, the SQL layer and the tests share it as one contract.

The category lookup is **lenient**: ``mcp_endpoints.category`` stays a free-form string. A written
value that matches a category's slug or label (case-insensitive) is stored as that category's slug;
a value that matches nothing is stored as given, so existing endpoints and clients keep working.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, List, Mapping, Optional, Sequence, Tuple

from .mcp_facets import UNCATEGORIZED_VALUE, UNTAGGED_VALUE, canonical_tag

# --- Vocabulary -------------------------------------------------------------------------------

#: The built-in categories every tenant sees, as ``(slug, label)`` in display order. Mirrors the
#: V365 seed rows; the tests pin the two together.
BUILTIN_CATEGORIES: Tuple[Tuple[str, str], ...] = (
    ("developer-tools", "Developer tools"),
    ("data-analytics", "Data & analytics"),
    ("databases", "Databases"),
    ("files-storage", "Files & storage"),
    ("search-web", "Search & web"),
    ("productivity", "Productivity"),
    ("communication", "Communication"),
    ("cloud-infrastructure", "Cloud & infrastructure"),
    ("finance-commerce", "Finance & commerce"),
    ("ai-ml", "AI & machine learning"),
    ("security", "Security"),
    ("other", "Other"),
)

#: Longest category slug / tag the V365 CHECK constraints accept.
MAX_CATEGORY_SLUG_LENGTH: int = 64
MAX_TAG_LENGTH: int = 64

#: Longest category label (``mcp_categories.label`` is ``VARCHAR(128)``).
MAX_CATEGORY_LABEL_LENGTH: int = 128

#: Most tags one endpoint may carry, so the facet stays a facet rather than a keyword dump.
MAX_TAGS_PER_ENDPOINT: int = 32

#: The V365 ``mcp_categories_slug_check`` pattern.
_CATEGORY_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

#: The V365 ``mcp_endpoint_tags_tag_check`` pattern.
_TAG_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,63}$")


class CategorizationValidationError(ValueError):
    """A category or tag value is invalid (the routes map this to a ``422``)."""


# --- Tags ---------------------------------------------------------------------------------------


def normalize_tag(raw: Optional[str]) -> str:
    """Canonicalize and validate one tag for storage.

    Args:
        raw: The tag as supplied.

    Returns:
        The canonical tag (see :func:`canonical_tag`).

    Raises:
        CategorizationValidationError: When the tag is blank, longer than :data:`MAX_TAG_LENGTH`,
            uses characters outside ``a-z 0-9 . _ : -``, does not start with a letter or digit, or
            is the reserved ``untagged`` facet sentinel.
    """
    tag = canonical_tag(raw)
    if not tag:
        raise CategorizationValidationError("tag must not be blank")
    if len(tag) > MAX_TAG_LENGTH:
        raise CategorizationValidationError(
            f"tag {tag!r} is longer than {MAX_TAG_LENGTH} characters"
        )
    if not _TAG_RE.match(tag):
        raise CategorizationValidationError(
            f"tag {tag!r} must start with a letter or digit and use only a-z, 0-9, '.', '_', ':' "
            "or '-'"
        )
    if tag == UNTAGGED_VALUE:
        raise CategorizationValidationError(
            f"{UNTAGGED_VALUE!r} is reserved for the untagged facet bucket"
        )
    return tag


def normalize_tags(raws: Optional[Iterable[Optional[str]]], *, limit: int = MAX_TAGS_PER_ENDPOINT) -> List[str]:
    """Normalize a list of tags: validate each, drop duplicates, enforce the per-endpoint limit.

    Args:
        raws: The tags as supplied (``None`` is an empty list).
        limit: The most distinct tags allowed (defaults to :data:`MAX_TAGS_PER_ENDPOINT`).

    Returns:
        The distinct canonical tags, in first-seen order.

    Raises:
        CategorizationValidationError: When any tag is invalid (see :func:`normalize_tag`) or there
            are more than ``limit`` distinct tags.
    """
    tags: List[str] = []
    for raw in raws or []:
        tag = normalize_tag(raw)
        if tag not in tags:
            tags.append(tag)
    if len(tags) > limit:
        raise CategorizationValidationError(
            f"an endpoint can have at most {limit} tags ({len(tags)} given)"
        )
    return tags


# --- Categories -----------------------------------------------------------------------------------


def slugify_category(label: str) -> str:
    """Derive a category slug from a label: lowercase, non-alphanumerics to single hyphens.

    ``"Data & Analytics"`` becomes ``"data-analytics"``. The result is cut to
    :data:`MAX_CATEGORY_SLUG_LENGTH` and may be empty when the label has no letters or digits.

    Args:
        label: The display label.

    Returns:
        The derived slug (possibly ``""``).
    """
    slug = re.sub(r"[^a-z0-9]+", "-", label.strip().lower()).strip("-")
    return slug[:MAX_CATEGORY_SLUG_LENGTH].rstrip("-")


def normalize_category_slug(raw: Optional[str]) -> str:
    """Validate a category slug for storage (lowercased and stripped first).

    Args:
        raw: The slug as supplied.

    Returns:
        The lowercase slug.

    Raises:
        CategorizationValidationError: When the slug is blank, does not match
            ``^[a-z0-9][a-z0-9-]{0,63}$``, or is the reserved ``uncategorized`` facet sentinel.
    """
    slug = (raw or "").strip().lower()
    if not slug:
        raise CategorizationValidationError("category slug must not be blank")
    if not _CATEGORY_SLUG_RE.match(slug):
        raise CategorizationValidationError(
            f"category slug {slug!r} must start with a letter or digit, use only a-z, 0-9 and "
            f"'-', and be at most {MAX_CATEGORY_SLUG_LENGTH} characters"
        )
    if slug == UNCATEGORIZED_VALUE:
        raise CategorizationValidationError(
            f"{UNCATEGORIZED_VALUE!r} is reserved for the uncategorized facet bucket"
        )
    return slug


def normalize_category_label(raw: Optional[str]) -> str:
    """Strip and validate a category label.

    Args:
        raw: The label as supplied.

    Returns:
        The stripped label.

    Raises:
        CategorizationValidationError: When blank or longer than :data:`MAX_CATEGORY_LABEL_LENGTH`.
    """
    label = (raw or "").strip()
    if not label:
        raise CategorizationValidationError("category label must not be blank")
    if len(label) > MAX_CATEGORY_LABEL_LENGTH:
        raise CategorizationValidationError(
            f"category label is longer than {MAX_CATEGORY_LABEL_LENGTH} characters"
        )
    return label


def resolve_category(value: Optional[str], categories: Sequence[Mapping[str, Any]]) -> Optional[str]:
    """Resolve an endpoint's written category against the lookup (lenient).

    A value that equals a category's ``slug`` or ``label`` (case-insensitive, ends stripped)
    resolves to that category's slug; slugs win over labels, so a tenant label can never capture a
    different category's slug. Anything else is kept as given (stripped), because the lookup does not
    restrict what an endpoint may store.

    Args:
        value: The category as supplied on create / patch.
        categories: The lookup rows visible to the tenant (each with ``slug`` and ``label``).

    Returns:
        The canonical slug, the stripped free-form value, or ``None`` when blank.
    """
    text = (value or "").strip()
    if not text:
        return None
    folded = text.lower()
    for row in categories:
        if str(row.get("slug") or "").lower() == folded:
            return str(row["slug"])
    for row in categories:
        if str(row.get("label") or "").strip().lower() == folded:
            return str(row["slug"])
    return text


__all__ = [
    "BUILTIN_CATEGORIES",
    "CategorizationValidationError",
    "MAX_CATEGORY_LABEL_LENGTH",
    "MAX_CATEGORY_SLUG_LENGTH",
    "MAX_TAGS_PER_ENDPOINT",
    "MAX_TAG_LENGTH",
    "canonical_tag",
    "normalize_category_label",
    "normalize_category_slug",
    "normalize_tag",
    "normalize_tags",
    "resolve_category",
    "slugify_category",
]
