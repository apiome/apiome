"""Tests for OpenAPI info metadata extraction.

Covers:
- Basic title/version extraction into name/version/project_slug/version_slug/data
- title and version stripped from data but present in InfoMetadata columns
- CLI overrides (project_name, version) replace info values
- x-* extension fields preserved in data
- Remaining info fields (description, contact, license, etc.) go into data
- Derived slugs satisfy V13/V14 DB constraints (see test_extract_slug.py)
- Error handling: missing info block, missing title, missing version
- Empty or whitespace-only title/version
"""

from __future__ import annotations

from typing import Any

import pytest

from apiome_cli.extract.openapi_info import InfoMetadata, extract_info_metadata
from apiome_cli.extract.slug import PROJECT_SLUG_RE, VERSION_SLUG_RE

# DB constraint regexes (mirrors V13/V14 migrations).
_PROJECT_SLUG_RE = PROJECT_SLUG_RE
_VERSION_SLUG_RE = VERSION_SLUG_RE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _doc(info: dict[str, Any]) -> dict[str, Any]:
    """Build a minimal OpenAPI document with the given info block."""
    return {"openapi": "3.1.0", "info": info, "paths": {}}


def _valid_project_slug(slug: str) -> bool:
    """Return True when *slug* satisfies the V13 DB constraint."""
    return bool(_PROJECT_SLUG_RE.match(slug))


def _valid_version_slug(slug: str) -> bool:
    """Return True when *slug* satisfies the V14 DB constraint."""
    return bool(_VERSION_SLUG_RE.match(slug))


# ---------------------------------------------------------------------------
# Basic extraction
# ---------------------------------------------------------------------------


def test_basic_extraction_returns_info_metadata() -> None:
    """extract_info_metadata returns an InfoMetadata instance."""
    doc = _doc({"title": "Pet Store", "version": "1.0.0"})
    result = extract_info_metadata(doc)
    assert isinstance(result, InfoMetadata)


def test_title_maps_to_name() -> None:
    """info.title is mapped to InfoMetadata.name."""
    doc = _doc({"title": "Pet Store", "version": "1.0.0"})
    result = extract_info_metadata(doc)
    assert result.name == "Pet Store"


def test_version_maps_to_version() -> None:
    """info.version is mapped to InfoMetadata.version."""
    doc = _doc({"title": "Pet Store", "version": "2.3.4"})
    result = extract_info_metadata(doc)
    assert result.version == "2.3.4"


def test_title_stripped_from_data() -> None:
    """title is NOT present in InfoMetadata.data."""
    doc = _doc({"title": "My API", "version": "1.0"})
    result = extract_info_metadata(doc)
    assert "title" not in result.data


def test_version_stripped_from_data() -> None:
    """version is NOT present in InfoMetadata.data."""
    doc = _doc({"title": "My API", "version": "1.0"})
    result = extract_info_metadata(doc)
    assert "version" not in result.data


def test_data_empty_when_only_title_and_version() -> None:
    """data is empty dict when info has only title and version."""
    doc = _doc({"title": "My API", "version": "1.0"})
    result = extract_info_metadata(doc)
    assert result.data == {}


# ---------------------------------------------------------------------------
# data field: remaining info keys preserved
# ---------------------------------------------------------------------------


def test_description_preserved_in_data() -> None:
    """info.description is included in data."""
    doc = _doc({"title": "My API", "version": "1.0", "description": "A great API."})
    result = extract_info_metadata(doc)
    assert result.data == {"description": "A great API."}


def test_contact_preserved_in_data() -> None:
    """info.contact is included in data."""
    contact = {"name": "Support", "email": "support@example.com"}
    doc = _doc({"title": "My API", "version": "1.0", "contact": contact})
    result = extract_info_metadata(doc)
    assert result.data["contact"] == contact


def test_license_preserved_in_data() -> None:
    """info.license is included in data."""
    license_info = {"name": "MIT", "url": "https://opensource.org/licenses/MIT"}
    doc = _doc({"title": "My API", "version": "1.0", "license": license_info})
    result = extract_info_metadata(doc)
    assert result.data["license"] == license_info


def test_terms_of_service_preserved_in_data() -> None:
    """info.termsOfService is included in data."""
    doc = _doc(
        {
            "title": "My API",
            "version": "1.0",
            "termsOfService": "https://example.com/tos",
        }
    )
    result = extract_info_metadata(doc)
    assert result.data["termsOfService"] == "https://example.com/tos"


# ---------------------------------------------------------------------------
# x-* extension fields
# ---------------------------------------------------------------------------


def test_x_extension_preserved_in_data() -> None:
    """Single x-* field in info is included in data."""
    doc = _doc(
        {"title": "My API", "version": "1.0", "x-internal-id": "abc-123"}
    )
    result = extract_info_metadata(doc)
    assert result.data["x-internal-id"] == "abc-123"


def test_multiple_x_extensions_all_in_data() -> None:
    """Multiple x-* fields are all preserved in data."""
    doc = _doc(
        {
            "title": "My API",
            "version": "1.0",
            "x-logo": {"url": "https://example.com/logo.png"},
            "x-stability": "stable",
            "x-api-owner": "platform-team",
        }
    )
    result = extract_info_metadata(doc)
    assert result.data["x-logo"] == {"url": "https://example.com/logo.png"}
    assert result.data["x-stability"] == "stable"
    assert result.data["x-api-owner"] == "platform-team"
    assert "title" not in result.data
    assert "version" not in result.data


def test_x_extension_with_nested_object_preserved() -> None:
    """Nested x-* objects are preserved exactly in data."""
    custom = {"deprecated": True, "sunset": "2027-01-01", "info": "See v2"}
    doc = _doc({"title": "Legacy API", "version": "0.9", "x-deprecation": custom})
    result = extract_info_metadata(doc)
    assert result.data["x-deprecation"] == custom


def test_x_extension_alongside_standard_fields_in_data() -> None:
    """x-* fields and standard extras co-exist in data."""
    doc = _doc(
        {
            "title": "Mixed API",
            "version": "3.0",
            "description": "Mixes standard and custom fields.",
            "x-custom-field": "custom-value",
        }
    )
    result = extract_info_metadata(doc)
    assert result.data == {
        "description": "Mixes standard and custom fields.",
        "x-custom-field": "custom-value",
    }


# ---------------------------------------------------------------------------
# CLI overrides: project_name
# ---------------------------------------------------------------------------


def test_project_name_override_replaces_title() -> None:
    """--project-name CLI override takes precedence over info.title."""
    doc = _doc({"title": "Original Title", "version": "1.0"})
    result = extract_info_metadata(doc, project_name="Overridden Name")
    assert result.name == "Overridden Name"


def test_project_name_override_slug_derived_from_override() -> None:
    """project_slug is derived from the overridden name, not info.title."""
    doc = _doc({"title": "Original Title", "version": "1.0"})
    result = extract_info_metadata(doc, project_name="My Override")
    assert result.project_slug == "my-override"


def test_project_name_override_does_not_affect_data() -> None:
    """data still reflects the original info (minus title/version), not the override."""
    doc = _doc({"title": "Original Title", "version": "1.0", "x-note": "keep me"})
    result = extract_info_metadata(doc, project_name="New Name")
    assert "title" not in result.data
    assert result.data == {"x-note": "keep me"}


def test_empty_project_name_override_raises_even_when_title_present() -> None:
    """Empty project_name override is treated as provided and rejected."""
    doc = _doc({"title": "Original Title", "version": "1.0"})
    with pytest.raises(ValueError, match="project name"):
        extract_info_metadata(doc, project_name="")


def test_whitespace_project_name_override_raises_even_when_title_present() -> None:
    """Whitespace-only project_name override is treated as provided and rejected."""
    doc = _doc({"title": "Original Title", "version": "1.0"})
    with pytest.raises(ValueError, match="project name"):
        extract_info_metadata(doc, project_name="   ")


def test_project_name_field_resolves_from_info_summary() -> None:
    doc = _doc(
        {
            "title": "Ignored Title",
            "version": "1.0",
            "summary": "Summary API Name",
        }
    )
    result = extract_info_metadata(doc, project_name_field="info.summary")
    assert result.name == "Summary API Name"
    assert result.project_slug == "summary-api-name"


def test_project_name_field_honours_embedded_extension() -> None:
    doc = _doc(
        {
            "title": "Ignored Title",
            "version": "1.0",
            "summary": "Embedded Field Name",
            "x-apiome-project-name-field": "info.summary",
        }
    )
    result = extract_info_metadata(doc)
    assert result.name == "Embedded Field Name"
    assert "x-apiome-project-name-field" not in result.data


# ---------------------------------------------------------------------------
# CLI overrides: version
# ---------------------------------------------------------------------------


def test_version_override_replaces_info_version() -> None:
    """--version CLI override takes precedence over info.version."""
    doc = _doc({"title": "My API", "version": "1.0.0"})
    result = extract_info_metadata(doc, version="2.5.0")
    assert result.version == "2.5.0"


def test_version_override_slug_derived_from_override() -> None:
    """version_slug is derived from the overridden version, not info.version."""
    doc = _doc({"title": "My API", "version": "1.0.0"})
    result = extract_info_metadata(doc, version="2.0-rc1")
    assert result.version_slug == "2.0-rc1"


def test_both_overrides_applied_simultaneously() -> None:
    """Both project_name and version overrides can be applied at once."""
    doc = _doc({"title": "Orig", "version": "0.1"})
    result = extract_info_metadata(doc, project_name="New Name", version="9.9.9")
    assert result.name == "New Name"
    assert result.version == "9.9.9"


def test_empty_version_override_raises_even_when_info_version_present() -> None:
    """Empty version override is treated as provided and rejected."""
    doc = _doc({"title": "My API", "version": "1.0.0"})
    with pytest.raises(ValueError, match="version"):
        extract_info_metadata(doc, version="")


def test_whitespace_version_override_raises_even_when_info_version_present() -> None:
    """Whitespace-only version override is treated as provided and rejected."""
    doc = _doc({"title": "My API", "version": "1.0.0"})
    with pytest.raises(ValueError, match="version"):
        extract_info_metadata(doc, version="   ")


# ---------------------------------------------------------------------------
# Slug validation: InfoMetadata slugs match DB constraints
# ---------------------------------------------------------------------------


def test_extracted_project_slug_matches_v13_constraint() -> None:
    """project_slug on InfoMetadata always satisfies the V13 DB check."""
    doc = _doc({"title": "My Pet Store API", "version": "1.0.0"})
    result = extract_info_metadata(doc)
    assert _valid_project_slug(result.project_slug)


def test_extracted_version_slug_matches_v14_constraint() -> None:
    """version_slug on InfoMetadata always satisfies the V14 DB check."""
    doc = _doc({"title": "My API", "version": "2.0.0-rc.1"})
    result = extract_info_metadata(doc)
    assert _valid_version_slug(result.version_slug)


def test_slug_override_still_matches_v13_constraint() -> None:
    """project_slug derived from project_name override matches V13."""
    doc = _doc({"title": "Old Name", "version": "1.0"})
    result = extract_info_metadata(doc, project_name="New Name With Spaces")
    assert _valid_project_slug(result.project_slug)


def test_slug_override_still_matches_v14_constraint() -> None:
    """version_slug derived from version override matches V14."""
    doc = _doc({"title": "My API", "version": "1.0"})
    result = extract_info_metadata(doc, version="3.0.0-alpha.1")
    assert _valid_version_slug(result.version_slug)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_missing_info_block_raises_value_error() -> None:
    """A document without an 'info' key raises ValueError."""
    doc: dict[str, Any] = {"openapi": "3.1.0", "paths": {}}
    with pytest.raises(ValueError, match="info"):
        extract_info_metadata(doc)


def test_non_dict_info_raises_value_error() -> None:
    """A document where 'info' is not a dict raises ValueError."""
    doc: dict[str, Any] = {"openapi": "3.1.0", "info": "not a dict", "paths": {}}
    with pytest.raises(ValueError, match="info"):
        extract_info_metadata(doc)


def test_missing_title_without_override_raises_value_error() -> None:
    """Missing info.title without a project_name override raises ValueError."""
    doc = _doc({"version": "1.0"})
    with pytest.raises(ValueError, match="project name"):
        extract_info_metadata(doc)


def test_missing_version_without_override_raises_value_error() -> None:
    """Missing info.version without a version override raises ValueError."""
    doc = _doc({"title": "My API"})
    with pytest.raises(ValueError, match="version"):
        extract_info_metadata(doc)


def test_empty_title_without_override_raises_value_error() -> None:
    """Empty string info.title without a project_name override raises ValueError."""
    doc = _doc({"title": "", "version": "1.0"})
    with pytest.raises(ValueError, match="project name"):
        extract_info_metadata(doc)


def test_whitespace_title_without_override_raises_value_error() -> None:
    """Whitespace-only info.title without a project_name override raises ValueError."""
    doc = _doc({"title": "   ", "version": "1.0"})
    with pytest.raises(ValueError, match="project name"):
        extract_info_metadata(doc)


def test_empty_version_without_override_raises_value_error() -> None:
    """Empty string info.version without a version override raises ValueError."""
    doc = _doc({"title": "My API", "version": ""})
    with pytest.raises(ValueError, match="version"):
        extract_info_metadata(doc)


def test_empty_title_falls_back_to_provider_name_extension() -> None:
    """Empty info.title uses info.x-providerName when present."""
    doc = _doc({"title": "", "version": "1.0", "x-providerName": "ipinfodb.com"})
    result = extract_info_metadata(doc)
    assert result.name == "ipinfodb.com"
    assert result.project_slug == "ipinfodb-com"


def test_whitespace_title_falls_back_to_provider_and_service_extensions() -> None:
    doc = _doc(
        {
            "title": "   ",
            "version": "v3",
            "x-providerName": "hubapi.com",
            "x-serviceName": "files",
        }
    )
    result = extract_info_metadata(doc)
    assert result.name == "files (hubapi.com)"


def test_project_name_override_when_title_missing() -> None:
    """project_name override rescues a document without info.title."""
    doc = _doc({"version": "1.0"})
    result = extract_info_metadata(doc, project_name="Rescue Name")
    assert result.name == "Rescue Name"


def test_version_override_when_info_version_missing() -> None:
    """version override rescues a document without info.version."""
    doc = _doc({"title": "My API"})
    result = extract_info_metadata(doc, version="0.0.1")
    assert result.version == "0.0.1"


# ---------------------------------------------------------------------------
# Title whitespace trimming
# ---------------------------------------------------------------------------


def test_title_whitespace_trimmed_from_name() -> None:
    """Leading/trailing whitespace in info.title is stripped from name."""
    doc = _doc({"title": "  My API  ", "version": "1.0"})
    result = extract_info_metadata(doc)
    assert result.name == "My API"


def test_version_whitespace_trimmed_from_version() -> None:
    """Leading/trailing whitespace in info.version is stripped from version."""
    doc = _doc({"title": "My API", "version": "  1.0.0  "})
    result = extract_info_metadata(doc)
    assert result.version == "1.0.0"
