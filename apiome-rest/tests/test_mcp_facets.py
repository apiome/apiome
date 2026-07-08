"""Unit tests for the pure faceted-search vocabulary module (V2-MCP-35.1 / MCAT-21.1, #4660).

Covers :mod:`app.mcp_facets` — the complexity banding and its thresholds, and the request-side
normalization of every facet dimension (case canonicalization, sentinel handling, de-duplication,
and vocabulary rejection). Also pins the SQL banding expression in :mod:`app.database` to the
Python :func:`complexity_band` thresholds, so the two mirrors cannot drift silently.
"""

import pytest

from app.database import Database
from app.mcp_facets import (
    COMPLEXITY_MODERATE_MAX_PROPERTIES,
    COMPLEXITY_SIMPLE_MAX_PROPERTIES,
    COMPLEXITY_VALUES,
    GRADE_VALUES,
    HEALTH_VALUES,
    SAFETY_HAS_DESTRUCTIVE,
    SAFETY_READ_ONLY_ONLY,
    SAFETY_VALUES,
    TRANSPORT_VALUES,
    UNCATEGORIZED_VALUE,
    UNGRADED_VALUE,
    UNKNOWN_VALUE,
    FacetValidationError,
    complexity_band,
    normalize_catalog_facet_filters,
)

# ===========================================================================
# Complexity banding
# ===========================================================================


def test_complexity_band_none_is_unknown():
    assert complexity_band(None) == UNKNOWN_VALUE


@pytest.mark.parametrize(
    "props,expected",
    [
        (0, "simple"),
        (COMPLEXITY_SIMPLE_MAX_PROPERTIES, "simple"),
        (COMPLEXITY_SIMPLE_MAX_PROPERTIES + 1, "moderate"),
        (COMPLEXITY_MODERATE_MAX_PROPERTIES, "moderate"),
        (COMPLEXITY_MODERATE_MAX_PROPERTIES + 1, "complex"),
        (50, "complex"),
    ],
)
def test_complexity_band_thresholds(props, expected):
    assert complexity_band(props) == expected


def test_complexity_band_values_cover_every_band():
    bands = {complexity_band(n) for n in range(0, 20)} | {complexity_band(None)}
    assert bands == set(COMPLEXITY_VALUES)


def test_sql_banding_expression_uses_the_same_thresholds():
    """The SQL CASE mirror must embed exactly the Python thresholds (drift guard)."""
    expr = Database._MCP_COMPLEXITY_BAND_EXPR
    assert f"<= {COMPLEXITY_SIMPLE_MAX_PROPERTIES} THEN 'simple'" in expr
    assert f"<= {COMPLEXITY_MODERATE_MAX_PROPERTIES} THEN 'moderate'" in expr
    assert "'unknown'" in expr and "'complex'" in expr


# ===========================================================================
# Normalization — closed vocabularies
# ===========================================================================


def test_grades_normalize_case_and_sentinel_and_dedupe():
    filters = normalize_catalog_facet_filters(grade=["a", "B", "A", " Ungraded "])
    assert filters.grades == ["A", "B", UNGRADED_VALUE]


def test_invalid_grade_is_rejected_with_vocabulary_in_message():
    with pytest.raises(FacetValidationError) as exc:
        normalize_catalog_facet_filters(grade=["E"])
    assert "grade" in str(exc.value)
    for letter in GRADE_VALUES:
        assert letter in str(exc.value)


@pytest.mark.parametrize(
    "field,value",
    [
        ("transport", "carrier_pigeon"),
        ("safety", "mostly_safe"),
        ("complexity", "gnarly"),
        ("health", "sideways"),
    ],
)
def test_invalid_enum_values_are_rejected(field, value):
    with pytest.raises(FacetValidationError) as exc:
        normalize_catalog_facet_filters(**{field: [value]})
    assert field in str(exc.value)
    assert value in str(exc.value)


def test_enum_facets_lowercase_and_accept_full_vocabulary():
    filters = normalize_catalog_facet_filters(
        transport=[t.upper() for t in TRANSPORT_VALUES],
        safety=[s.upper() for s in SAFETY_VALUES],
        complexity=[c.upper() for c in COMPLEXITY_VALUES],
        health=[h.upper() for h in HEALTH_VALUES],
    )
    assert filters.transports == list(TRANSPORT_VALUES)
    assert filters.safety == list(SAFETY_VALUES)
    assert filters.complexity == list(COMPLEXITY_VALUES)
    assert filters.health == list(HEALTH_VALUES)


def test_safety_vocabulary_is_exactly_the_two_postures():
    assert set(SAFETY_VALUES) == {SAFETY_HAS_DESTRUCTIVE, SAFETY_READ_ONLY_ONLY}


# ===========================================================================
# Normalization — free-form facets & cleaning
# ===========================================================================


def test_categories_keep_case_but_canonicalize_the_sentinel():
    filters = normalize_catalog_facet_filters(category=["Weather", "UNCATEGORIZED"])
    assert filters.categories == ["Weather", UNCATEGORIZED_VALUE]


def test_protocols_keep_value_but_canonicalize_the_sentinel():
    filters = normalize_catalog_facet_filters(protocol=["2025-06-18", "Unknown"])
    assert filters.protocols == ["2025-06-18", UNKNOWN_VALUE]


def test_blank_and_duplicate_values_are_dropped():
    filters = normalize_catalog_facet_filters(
        category=["  ", "", "weather", "weather"], protocol=["", "2025-06-18"]
    )
    assert filters.categories == ["weather"]
    assert filters.protocols == ["2025-06-18"]


def test_no_input_yields_empty_filters():
    filters = normalize_catalog_facet_filters()
    assert filters.grades == []
    assert filters.transports == []
    assert filters.categories == []
    assert filters.safety == []
    assert filters.complexity == []
    assert filters.protocols == []
    assert filters.health == []
