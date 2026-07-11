"""Grade-stability regression corpus for the style-guide engine — GOV-1.4 (#4430).

Acceptance criterion: under the **default** guide ("Apiome Recommended" — every shipped
rule at its default severity), the regression corpus must reproduce the pre-guide A–F
grades within ±1 grade. Because the default guide mirrors the shipped rule packs exactly,
the expectation here is stronger and byte-exact: same findings, same score, same grade,
same report fingerprint. The pinned scores/grades below also freeze the legacy engine
output itself, so an accidental recalibration of the severity weights or grade thresholds
fails this suite loudly.

The corpus spans the OpenAPI-family fixtures (Swagger 2.0, OpenAPI 3.0/3.1/3.2, and the
Arazzo workflow document linted as a JSON document) plus a canonical-model pair (clean and
dirty) through :func:`app.lint_engine.lint_canonical_model`, so both engine tails are held
stable.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.canonical_model import ApiIdentity, ApiParadigm, CanonicalApi, CanonicalField, Type, TypeKind, TypeRef
from app.lint_engine import lint_canonical_model
from app.schema_lint import GRADE_THRESHOLDS, lint_openapi_spec
from app.style_guide_engine import builtin_fallback_guide

FIXTURES = Path(__file__).parent / "fixtures" / "openapi_family"

#: The pinned corpus: fixture file -> (score, grade) produced by the shipped defaults.
#: These values freeze today's calibration; a change here is a deliberate re-calibration
#: and must stay within ±1 grade of the previous pin (GOV-1.4 acceptance criterion).
PINNED_OPENAPI_CORPUS = {
    "arazzo-checkout.yaml": (99, "A"),
    "openapi-3.0-inventory.yaml": (85, "B"),
    "openapi-3.1-petstore.yaml": (92, "A"),
    "openapi-3.2-search.yaml": (91, "A"),
    "swagger-2.0-petstore.yaml": (96, "A"),
}

#: Grade letters ordered best-to-worst, for the ±1-grade tolerance check.
GRADE_ORDER = [grade for _, grade in GRADE_THRESHOLDS]


def _grades_within_one(a: str, b: str) -> bool:
    return abs(GRADE_ORDER.index(a) - GRADE_ORDER.index(b)) <= 1


def _load(name: str) -> dict:
    return yaml.safe_load((FIXTURES / name).read_text())


def test_corpus_covers_every_openapi_family_fixture():
    """A new fixture must be pinned into the corpus, so coverage can't silently shrink."""
    assert {p.name for p in FIXTURES.glob("*.yaml")} == set(PINNED_OPENAPI_CORPUS)


@pytest.mark.parametrize("fixture_name", sorted(PINNED_OPENAPI_CORPUS))
def test_legacy_engine_grades_are_pinned(fixture_name: str):
    """The ungoverned engine still produces the frozen calibration."""
    expected_score, expected_grade = PINNED_OPENAPI_CORPUS[fixture_name]
    result = lint_openapi_spec(_load(fixture_name))
    assert (result.score, result.grade) == (expected_score, expected_grade)


@pytest.mark.parametrize("fixture_name", sorted(PINNED_OPENAPI_CORPUS))
def test_default_guide_reproduces_legacy_grades_exactly(fixture_name: str):
    """The default guide is a no-op: identical findings, score, grade, and fingerprint."""
    doc = _load(fixture_name)
    legacy = lint_openapi_spec(doc)
    guided = builtin_fallback_guide().apply(legacy, document=doc)

    assert guided.report_fingerprint == legacy.report_fingerprint
    assert guided.score == legacy.score
    assert guided.grade == legacy.grade
    assert guided.findings == legacy.findings
    # And, explicitly, the stated acceptance bound (trivially satisfied by exactness):
    assert _grades_within_one(guided.grade, legacy.grade)


def _canonical_pair() -> tuple[CanonicalApi, CanonicalApi]:
    """A fully documented model (grades A) and an undocumented one with generated names."""
    clean = CanonicalApi(
        identity=ApiIdentity(name="Orders"),
        format="jsonschema",
        paradigm=ApiParadigm.REST,
        version="1.0.0",
        description="Order management.",
        types=[
            Type(
                key="Order",
                name="Order",
                kind=TypeKind.RECORD,
                description="One order.",
                fields=[
                    CanonicalField(
                        key="Order.id",
                        name="id",
                        type=TypeRef(name="string", nullable=False),
                        description="The order id.",
                    )
                ],
            )
        ],
    )
    dirty = CanonicalApi(
        identity=ApiIdentity(name="Orders"),
        format="jsonschema",
        paradigm=ApiParadigm.REST,
        version="1.0.0",
        types=[
            Type(
                key="GeneratedType1",
                name="GeneratedType1",
                kind=TypeKind.RECORD,
                fields=[
                    CanonicalField(
                        key="GeneratedType1.field_1",
                        name="field_1",
                        type=TypeRef(name="string", nullable=False),
                    )
                ],
            )
        ],
    )
    return clean, dirty


def test_default_guide_reproduces_canonical_model_grades_exactly():
    """The canonical-model engine tail (imports of non-OpenAPI formats) is equally stable."""
    for model in _canonical_pair():
        legacy = lint_canonical_model(model)
        guided = builtin_fallback_guide().apply(legacy)  # no JSON document on this path
        assert guided.report_fingerprint == legacy.report_fingerprint
        assert guided.score == legacy.score
        assert guided.grade == legacy.grade
        assert _grades_within_one(guided.grade, legacy.grade)
