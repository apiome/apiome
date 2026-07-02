"""Slug derivation utilities for projects and project versions.

Slugs must satisfy the PostgreSQL ``CHECK`` constraints from migrations
V13 (``projects.slug``) and V14 (``project_versions.slug``):

* Project: ``^[a-z0-9]([a-z0-9-]*[a-z0-9])?$``
* Version: ``^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$``

Unicode policy (applied before ASCII slug rules):

1. **NFKC** — compatibility-normalise visually similar characters
   (e.g. fullwidth ``１`` → ``1``, ligature ``ﬁ`` → ``fi``).
2. **NFD + strip combining marks** — decompose accented letters and drop
   non-spacing marks so ``é`` → ``e``, ``ü`` → ``u``.
3. Remaining characters outside the slug alphabet are removed by the
   type-specific rules below.
"""

from __future__ import annotations

import re
import unicodedata

# Compiled regexes that mirror the DB CHECK constraints (V13/V14).
PROJECT_SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
VERSION_SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$")

# Allowed inner characters for each slug type.
_PROJECT_INVALID_CHARS_RE = re.compile(r"[^a-z0-9-]")
_VERSION_INVALID_CHARS_RE = re.compile(r"[^a-z0-9.\-]")


def normalize_unicode_for_slug(text: str) -> str:
    """Apply the slug unicode policy to *text*.

    Steps: NFKC compatibility normalization, then NFD decomposition with
    stripping of combining marks (Unicode category ``Mn``).

    Args:
        text: Raw user-facing string (project name or version label).

    Returns:
        A string safe to pass through ASCII slug rules (may still contain
        characters that will be removed or replaced by slugify helpers).
    """
    normalized = unicodedata.normalize("NFKC", text)
    decomposed = unicodedata.normalize("NFD", normalized)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def slugify_project_name(text: str) -> str:
    """Convert *text* to a valid project slug.

    The output matches ``^[a-z0-9]([a-z0-9-]*[a-z0-9])?$``, which is the
    ``CHECK`` constraint on ``projects.slug`` (V13).

    Args:
        text: Raw project name string (e.g. ``"My API Service"``).

    Returns:
        A lowercase, hyphen-separated slug string.

    Raises:
        ValueError: If *text* cannot be reduced to a non-empty slug.
    """
    slug = normalize_unicode_for_slug(text).lower()
    # Replace whitespace, underscores, dots, and slashes with hyphens.
    slug = re.sub(r"[\s_./\\]+", "-", slug)
    # Drop any characters outside [a-z0-9-].
    slug = _PROJECT_INVALID_CHARS_RE.sub("", slug)
    # Collapse consecutive hyphens and strip leading/trailing hyphens.
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    if not slug:
        raise ValueError(
            f"Cannot derive a valid project slug from {text!r}: "
            "no alphanumeric characters remain after normalisation."
        )
    if not PROJECT_SLUG_RE.fullmatch(slug):
        raise ValueError(
            f"Derived project slug {slug!r} from {text!r} violates "
            "the projects.slug DB constraint."
        )
    return slug


def slugify_version(text: str) -> str:
    """Convert *text* to a valid version slug.

    The output matches ``^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$``, which is the
    ``CHECK`` constraint on ``project_versions.slug`` (V14).  Dots are
    preserved so that ``"1.0.0"`` maps cleanly to ``"1.0.0"``.

    Args:
        text: Raw version string (e.g. ``"1.0.0-beta.1"`` or ``"v2.3"``).

    Returns:
        A lowercase slug string containing only ``[a-z0-9.-]``.

    Raises:
        ValueError: If *text* cannot be reduced to a non-empty slug.
    """
    slug = normalize_unicode_for_slug(text).lower()
    # Replace whitespace, underscores, and slashes with hyphens.
    slug = re.sub(r"[\s_/\\]+", "-", slug)
    # Drop any characters outside [a-z0-9.-].
    slug = _VERSION_INVALID_CHARS_RE.sub("", slug)
    # Collapse consecutive hyphens and dots; strip leading/trailing hyphens/dots.
    slug = re.sub(r"-{2,}", "-", slug)
    slug = re.sub(r"\.{2,}", ".", slug)
    slug = slug.strip("-.")
    if not slug:
        raise ValueError(
            f"Cannot derive a valid version slug from {text!r}: "
            "no alphanumeric characters remain after normalisation."
        )
    if not VERSION_SLUG_RE.fullmatch(slug):
        raise ValueError(
            f"Derived version slug {slug!r} from {text!r} violates "
            "the project_versions.slug DB constraint."
        )
    return slug
