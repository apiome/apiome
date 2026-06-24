"""Unit tests for the deterministic lint / quality-scoring engine (#3609)."""

from dataclasses import dataclass

from src.app.schema_lint import (
    GRADE_THRESHOLDS,
    lint_openapi_spec,
    merge_compatibility_findings,
)

CLEAN_SPEC = {
    "openapi": "3.1.0",
    "info": {"title": "Payments", "version": "1.0.0", "description": "A well documented API."},
    "paths": {
        "/payments": {
            "get": {
                "operationId": "listPayments",
                "summary": "List payments",
                "responses": {"200": {"description": "ok"}},
            }
        }
    },
    "components": {
        "schemas": {
            "Payment": {
                "type": "object",
                "description": "A payment record.",
                "properties": {
                    "amount": {
                        "type": "integer",
                        "description": "Amount in cents.",
                        "example": 1000,
                    },
                    "tags": {
                        "type": "array",
                        "description": "Free-form tags.",
                        "maxItems": 10,
                        "items": {"type": "string"},
                    },
                },
            }
        }
    },
}

DIRTY_SPEC = {
    "openapi": "3.1.0",
    "info": {"title": "Payments", "version": "1.0.0"},  # no description
    "paths": {
        "/payments": {
            "get": {"operationId": "listPayments", "responses": {"200": {"description": "ok"}}}
        }
    },
    "components": {
        "schemas": {
            "payment": {  # not PascalCase, no description
                "type": "object",
                "properties": {
                    "amount-due": {"type": "integer"},  # bad name, no description, no example
                    "tags": {"type": "array", "items": {"type": "string"}},  # unbounded array
                },
            }
        }
    },
}


def test_clean_spec_scores_high_grade_a():
    result = lint_openapi_spec(CLEAN_SPEC)
    assert result.score == 100
    assert result.grade == "A"
    assert result.findings == ()
    assert result.severity_counts == {"error": 0, "warning": 0, "info": 0}


def test_dirty_spec_surfaces_each_rule():
    result = lint_openapi_spec(DIRTY_SPEC)
    rules = {f.rule for f in result.findings}
    assert "naming.schema-pascal-case" in rules
    assert "naming.property-name" in rules
    assert "documentation.schema-missing-description" in rules
    assert "documentation.property-missing-description" in rules
    assert "documentation.property-missing-example" in rules
    assert "documentation.operation-missing-summary" in rules
    assert "documentation.info-missing-description" in rules
    assert "structure.unbounded-array" in rules
    assert result.score < 100
    assert result.grade in {"A", "B", "C", "D", "F"}


def test_determinism_same_input_same_output():
    a = lint_openapi_spec(DIRTY_SPEC)
    b = lint_openapi_spec(DIRTY_SPEC)
    assert a.report_fingerprint == b.report_fingerprint
    assert a.score == b.score
    assert [f.id for f in a.findings] == [f.id for f in b.findings]


def test_findings_sorted_by_path_rule_id():
    result = lint_openapi_spec(DIRTY_SPEC)
    keys = [(f.path, f.rule, f.id) for f in result.findings]
    assert keys == sorted(keys)


def test_finding_ids_are_stable_hashes():
    result = lint_openapi_spec(DIRTY_SPEC)
    for finding in result.findings:
        assert finding.id.startswith("lint-")
        assert len(finding.id) == len("lint-") + 16


def test_rule_hits_count_matches_findings():
    result = lint_openapi_spec(DIRTY_SPEC)
    assert sum(result.rule_hits.values()) == len(result.findings)


def test_per_rule_penalty_cap_bounds_score():
    # Many properties missing examples should not drive the score below the cap allows.
    props = {f"field{i}": {"type": "string"} for i in range(200)}
    spec = {
        "info": {"description": "ok"},
        "components": {
            "schemas": {
                "Widget": {"type": "object", "description": "ok", "properties": props}
            }
        },
    }
    result = lint_openapi_spec(spec)
    # Two capped rules apply (missing-description info + missing-example info), each capped at 20.
    assert result.score >= 50


def test_grade_thresholds_are_descending():
    thresholds = [t for t, _ in GRADE_THRESHOLDS]
    assert thresholds == sorted(thresholds, reverse=True)


@dataclass
class _FakeCompatFinding:
    path: str
    category: str
    message: str


def test_merge_compatibility_findings_maps_breaking_and_unknown():
    compat = [
        _FakeCompatFinding("paths./a", "breaking", "removed path"),
        _FakeCompatFinding("schemas.B", "unknown", "ambiguous change"),
        _FakeCompatFinding("schemas.C", "safe", "added optional field"),
    ]
    merged = merge_compatibility_findings(compat)
    rules = sorted(f.rule for f in merged)
    assert rules == ["compatibility.breaking", "compatibility.unknown"]
    breaking = next(f for f in merged if f.rule == "compatibility.breaking")
    assert breaking.severity == "error"


def test_compatibility_findings_fold_into_score():
    breaking = merge_compatibility_findings(
        [_FakeCompatFinding("paths./a", "breaking", "removed path")]
    )
    base = lint_openapi_spec(CLEAN_SPEC)
    with_compat = lint_openapi_spec(CLEAN_SPEC, extra_findings=breaking)
    assert with_compat.score < base.score
    assert with_compat.severity_counts["error"] == 1
