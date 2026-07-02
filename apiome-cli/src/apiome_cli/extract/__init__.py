"""Metadata extraction from API specifications."""

from apiome_cli.extract.openapi_info import InfoMetadata, extract_info_metadata
from apiome_cli.extract.slug import (
    PROJECT_SLUG_RE,
    VERSION_SLUG_RE,
    normalize_unicode_for_slug,
    slugify_project_name,
    slugify_version,
)

__all__ = [
    "InfoMetadata",
    "PROJECT_SLUG_RE",
    "VERSION_SLUG_RE",
    "extract_info_metadata",
    "normalize_unicode_for_slug",
    "slugify_project_name",
    "slugify_version",
]
