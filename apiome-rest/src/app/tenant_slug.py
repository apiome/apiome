"""
Tenant slug derivation and validation for first-tenant provisioning (OLO-4.3, #4207).

Python parity of ``apiome-ui/lib/auth/tenant-slug.ts`` — the UI validates slugs
for instant feedback, but this module is the authoritative server-side check
behind ``POST /v1/onboarding/first-tenant``. Keep the two in sync when rules
change (same discipline as the account-resolution engine, OLO-1.3).

Pure and dependency-free so it is importable from routes and tests alike.
"""

from __future__ import annotations

import re
from typing import Optional

# Allowed shape of a stored tenant slug: lowercase letters, digits, dashes.
_SLUG_REGEX = re.compile(r"^[a-z0-9-]+$")

# Shortest accepted tenant slug.
TENANT_SLUG_MIN_LENGTH = 2

# Longest accepted tenant slug — the ``apiome.tenants.slug`` column is
# VARCHAR(255) (V001), so anything longer fails at insert time.
TENANT_SLUG_MAX_LENGTH = 255

# Slugs that collide with REST route segments under ``/v1/tenants/*`` and would
# make the tenant unreachable (``HEAD /v1/tenants/me`` is the session's
# membership check, never a tenant lookup).
_RESERVED_SLUGS = frozenset({"me"})

# ASCII-only word characters so behaviour matches the JS ``\w`` class used by
# the UI's generateTenantSlug (JS \w is [A-Za-z0-9_], Python's defaults to
# the full Unicode word class).
_NON_WORD_RE = re.compile(r"[^\w\s-]", re.ASCII)
_SEPARATOR_RUN_RE = re.compile(r"[\s_-]+", re.ASCII)


def generate_tenant_slug(name: str) -> str:
    """
    Derive a URL-safe slug from a human-readable organization name.

    Lowercases, strips punctuation, and collapses whitespace/underscore runs to
    single dashes (e.g. ``"Acme, Inc."`` -> ``"acme-inc"``).

    Args:
        name: The organization display name to derive from.

    Returns:
        The derived slug; empty string when the name has no usable characters.
    """
    slug = (name or "").lower().strip()
    slug = _NON_WORD_RE.sub("", slug)
    slug = _SEPARATOR_RUN_RE.sub("-", slug)
    return slug.strip("-")


def validate_tenant_slug(slug: str) -> Optional[str]:
    """
    Validate a candidate tenant slug.

    Args:
        slug: The candidate slug (already trimmed/lowercased by the caller).

    Returns:
        A human-readable error message, or ``None`` when the slug is valid.
    """
    if not slug or not slug.strip():
        return "Tenant slug is required"
    s = slug.strip().lower()
    if len(s) < TENANT_SLUG_MIN_LENGTH:
        return f"Slug must be at least {TENANT_SLUG_MIN_LENGTH} characters"
    if len(s) > TENANT_SLUG_MAX_LENGTH:
        return f"Slug must be at most {TENANT_SLUG_MAX_LENGTH} characters"
    if not _SLUG_REGEX.match(s):
        return "Slug must contain only lowercase letters, numbers, and dashes"
    if s in _RESERVED_SLUGS:
        return f'"{s}" is a reserved word and cannot be used as a slug'
    return None
