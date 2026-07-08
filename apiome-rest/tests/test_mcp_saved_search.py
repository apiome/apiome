"""Unit tests for saved-search filter normalization (V2-MCP-35.3 / MCAT-21.3, #4662)."""

import pytest

from app.mcp_facets import FacetValidationError
from app.mcp_saved_search import (
    EMPTY_FILTERS,
    SavedSearchValidationError,
    normalize_saved_search_filters,
    normalize_saved_search_name,
    normalize_saved_search_sort,
    saved_filters_to_facet_kwargs,
)


def test_empty_filters_default():
    assert normalize_saved_search_filters(None) == EMPTY_FILTERS


def test_normalize_filters_round_trip():
    raw = {
        "grades": ["B", "ungraded"],
        "safeties": ["has_destructive"],
        "hosts": ["api.example.com", ""],
    }
    out = normalize_saved_search_filters(raw)
    assert out["grades"] == ["B", "ungraded"]
    assert out["safeties"] == ["has_destructive"]
    assert out["hosts"] == ["api.example.com"]
    assert out["transports"] == []


def test_normalize_filters_rejects_non_object():
    with pytest.raises(SavedSearchValidationError):
        normalize_saved_search_filters(["bad"])


def test_normalize_name_trims_and_rejects_blank():
    assert normalize_saved_search_name("  Weekly review  ") == "Weekly review"
    with pytest.raises(SavedSearchValidationError):
        normalize_saved_search_name("   ")


def test_normalize_sort_defaults_and_validates():
    assert normalize_saved_search_sort(None) == "grade"
    assert normalize_saved_search_sort("recency") == "recency"
    with pytest.raises(SavedSearchValidationError):
        normalize_saved_search_sort("bogus")


def test_saved_filters_to_facet_kwargs_maps_dimensions():
    filters = normalize_saved_search_filters(
        {
            "grades": ["A", "ungraded"],
            "transports": ["sse"],
            "categories": ["weather"],
            "safeties": ["read_only_only"],
            "complexities": ["simple"],
            "protocols": ["2025-06-18"],
            "healths": ["healthy"],
            "visibilities": ["private"],
            "hosts": ["ignored.example.com"],
        }
    )
    facet_kwargs, visibility = saved_filters_to_facet_kwargs(filters)
    assert facet_kwargs["grades"] == ["A", "ungraded"]
    assert facet_kwargs["transports"] == ["sse"]
    assert facet_kwargs["categories"] == ["weather"]
    assert facet_kwargs["safety"] == ["read_only_only"]
    assert facet_kwargs["complexity"] == ["simple"]
    assert facet_kwargs["protocols"] == ["2025-06-18"]
    assert facet_kwargs["health"] == ["healthy"]
    assert visibility == "private"


def test_saved_filters_to_facet_kwargs_rejects_invalid_facet():
    filters = normalize_saved_search_filters({"healths": ["not-a-health"]})
    with pytest.raises(FacetValidationError):
        saved_filters_to_facet_kwargs(filters)
