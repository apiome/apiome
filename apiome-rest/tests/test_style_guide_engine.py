"""Style-guide engine integration & score mapping — GOV-1.4 (#4430).

Covers the three halves of the engine module plus the DB accessors:

* **Compilation** — enabled built-in rules become the severity map, disabled rows are
  dropped, custom-rule rows re-validate their stored definition (invalid ones are skipped
  and recorded, never raised), the row severity overrides the definition's, and identical
  row content hits the content-addressed compile cache.
* **Application** — the default (fallback) guide is a byte-identical no-op; a custom guide
  drops disabled/unlisted findings, remaps severities (keeping stable finding ids),
  evaluates custom rules against the document, preserves the entry point's category bars,
  and re-scores through the one shared severity-weighted formula.
* **Resolution** — project beats tenant beats default; anything unresolvable (no guide,
  malformed accessor output, DB fault) degrades to the built-in defaults and never raises.
* **DB accessors** — tenant scoping, UUID guards, and the precedence ORDER BY in
  ``get_assigned_style_guide``'s single resolution query.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.database import Database
from app.lint_rule_registry import builtin_rule_descriptors
from app.schema_lint import lint_openapi_spec
from app.style_guide_engine import (
    apply_style_guide_to_lint_report,
    builtin_fallback_guide,
    compile_style_guide,
    guided_lint_openapi_spec,
    resolve_style_guide,
)

TENANT = "00000000-0000-4000-8000-0000000000a1"
PROJECT = "00000000-0000-4000-8000-0000000000b1"
GUIDE = "00000000-0000-4000-8000-0000000000c1"

#: A deliberately imperfect spec: PascalCase violation on the schema name, a missing
#: info/schema description, and a property naming violation — several rules, mixed severities.
DIRTY_SPEC = {
    "openapi": "3.1.0",
    "info": {"title": "Payments"},
    "paths": {},
    "components": {
        "schemas": {
            "payment_record": {
                "type": "object",
                "properties": {"BadProp": {"type": "string"}},
            }
        }
    },
}


def _rows(*rows):
    """Helper: build style_guide_rules rows with defaults."""
    return [
        {
            "rule_id": r[0],
            "enabled": r[1] if len(r) > 1 else True,
            "severity": r[2] if len(r) > 2 else "warning",
            "custom_def": r[3] if len(r) > 3 else None,
        }
        for r in rows
    ]


# ===========================================================================
# Compilation
# ===========================================================================


def test_fallback_guide_mirrors_the_full_builtin_registry():
    guide = builtin_fallback_guide()
    descriptors = builtin_rule_descriptors()
    assert guide.guide_id is None
    assert guide.name == "Apiome Recommended"
    assert guide.source == "fallback"
    assert set(guide.rule_severities) == {d.rule_id for d in descriptors}
    for d in descriptors:
        assert guide.rule_severities[d.rule_id] == d.default_severity
    assert not guide.custom_rules.rules


def test_compile_skips_disabled_rows_and_keeps_enabled_severities():
    guide = compile_style_guide(
        GUIDE,
        "Strict",
        "custom",
        _rows(
            ("naming.schema-pascal-case", True, "error"),
            ("documentation.info-missing-description", False, "info"),
        ),
    )
    assert guide.is_enabled("naming.schema-pascal-case")
    assert guide.severity_for("naming.schema-pascal-case") == "error"
    assert not guide.is_enabled("documentation.info-missing-description")
    assert guide.severity_for("documentation.info-missing-description") is None


def test_compile_validates_custom_rules_and_row_severity_wins():
    custom_def = {
        "description": "Info must carry a description",
        "severity": "info",  # the row's severity column below must win over this
        "given": ["$.info"],
        "then": [{"field": "description", "function": "truthy"}],
    }
    guide = compile_style_guide(
        GUIDE, "Strict", "custom", _rows(("require-info-description", True, "error", custom_def))
    )
    assert guide.custom_rules.rule_ids() == ["require-info-description"]
    assert guide.custom_rules.rules[0].severity == "error"
    assert not guide.custom_rule_errors


def test_compile_skips_invalid_stored_custom_defs_without_raising():
    guide = compile_style_guide(
        GUIDE,
        "Broken",
        "custom",
        _rows(
            ("bad-rule", True, "error", {"description": "x"}),  # missing given/then
            ("naming.schema-pascal-case", True, "warning"),
        ),
    )
    assert "bad-rule" in guide.custom_rule_errors
    assert not guide.custom_rules.rules
    # The valid built-in row still compiled.
    assert guide.is_enabled("naming.schema-pascal-case")


def test_compile_rejects_custom_def_shadowing_a_builtin_rule_id():
    custom_def = {
        "description": "shadow attempt",
        "given": ["$.info"],
        "then": [{"function": "truthy"}],
    }
    guide = compile_style_guide(
        GUIDE, "Shadow", "custom", _rows(("naming.schema-pascal-case", True, "error", custom_def))
    )
    assert "naming.schema-pascal-case" in guide.custom_rule_errors
    assert not guide.custom_rules.rules


def test_compile_cache_is_content_addressed():
    rows = _rows(("naming.schema-pascal-case", True, "error"))
    a = compile_style_guide(GUIDE, "Strict", "custom", rows)
    b = compile_style_guide(GUIDE, "Strict", "custom", list(rows))
    assert a is b  # identical content -> cached object
    c = compile_style_guide(GUIDE, "Strict", "custom", _rows(("naming.schema-pascal-case", True, "info")))
    assert c is not a
    assert c.fingerprint != a.fingerprint  # content change -> new fingerprint (cache self-invalidates)


# ===========================================================================
# Application / score mapping
# ===========================================================================


def test_default_guide_is_a_noop_on_score_grade_and_fingerprint():
    legacy = lint_openapi_spec(DIRTY_SPEC)
    guided = builtin_fallback_guide().apply(legacy, document=DIRTY_SPEC)
    assert guided == legacy  # findings, score, grade, categories, fingerprint — all identical


def test_apply_drops_unlisted_findings_and_remaps_severity():
    legacy = lint_openapi_spec(DIRTY_SPEC)
    assert any(f.rule == "naming.schema-pascal-case" for f in legacy.findings)

    guide = compile_style_guide(
        GUIDE, "Naming only", "custom", _rows(("naming.schema-pascal-case", True, "error"))
    )
    result = guide.apply(legacy, document=DIRTY_SPEC)

    assert {f.rule for f in result.findings} == {"naming.schema-pascal-case"}
    assert all(f.severity == "error" for f in result.findings)
    # One rule firing once at error severity: 100 - 10. The dropped documentation/property
    # findings no longer count, and the remap weighs the kept finding as an error.
    assert result.score == 90


def test_apply_keeps_stable_finding_ids_across_severity_remap():
    legacy = lint_openapi_spec(DIRTY_SPEC)
    original = {f.id: f for f in legacy.findings if f.rule == "naming.schema-pascal-case"}
    guide = compile_style_guide(
        GUIDE, "Naming only", "custom", _rows(("naming.schema-pascal-case", True, "error"))
    )
    result = guide.apply(legacy, document=DIRTY_SPEC)
    for f in result.findings:
        assert f.id in original  # same finding identity, new severity
        assert original[f.id].severity == "warning"
        assert f.severity == "error"


def test_apply_merges_custom_rule_findings_from_the_document():
    legacy = lint_openapi_spec(DIRTY_SPEC)
    custom_def = {
        "description": "Info must carry a description",
        "given": ["$.info"],
        "then": [{"field": "description", "function": "truthy"}],
    }
    guide = compile_style_guide(
        GUIDE, "Custom", "custom", _rows(("require-info-description", True, "error", custom_def))
    )
    result = guide.apply(legacy, document=DIRTY_SPEC)
    assert {f.rule for f in result.findings} == {"require-info-description"}
    assert result.findings[0].category == "custom"
    assert result.findings[0].severity == "error"
    assert result.score == 90  # one error finding: 100 - 10


def test_apply_without_document_skips_custom_rules_but_still_governs():
    legacy = lint_openapi_spec(DIRTY_SPEC)
    custom_def = {
        "description": "Info must carry a description",
        "given": ["$.info"],
        "then": [{"field": "description", "function": "truthy"}],
    }
    guide = compile_style_guide(
        GUIDE,
        "Mixed",
        "custom",
        _rows(
            ("naming.schema-pascal-case", True, "info"),
            ("require-info-description", True, "error", custom_def),
        ),
    )
    result = guide.apply(legacy)  # no document (canonical-model path)
    assert {f.rule for f in result.findings} == {"naming.schema-pascal-case"}
    assert all(f.severity == "info" for f in result.findings)


def test_apply_passes_through_findings_from_unregistered_rules():
    """External-tool extras (eslint/buf/…) are ungovernable and survive any guide intact."""
    from app.schema_lint import LintFinding, assemble_lint_result

    external = LintFinding(
        path="$.x", category="external", rule="eslint.no-anonymous-operations",
        severity="warning", message="external tool finding",
    )
    base = assemble_lint_result([external])
    for guide in (
        builtin_fallback_guide(),  # enables every registry rule
        compile_style_guide(GUIDE, "Empty", "custom", []),  # enables none
    ):
        result = guide.apply(base)
        assert [f.rule for f in result.findings] == ["eslint.no-anonymous-operations"]
        assert result.findings[0].severity == "warning"


def test_apply_preserves_the_entry_points_category_bars():
    legacy = lint_openapi_spec(DIRTY_SPEC)  # always surfaces naming/documentation/structure
    guide = compile_style_guide(GUIDE, "Empty", "custom", [])
    result = guide.apply(legacy, document=DIRTY_SPEC)
    assert not result.findings
    assert result.score == 100 and result.grade == "A"
    assert {c.name for c in result.categories} >= {"naming", "documentation", "structure"}
    assert all(c.score == 100 for c in result.categories)


def test_guided_lint_openapi_spec_returns_result_and_guide():
    with patch("app.style_guide_engine.resolve_style_guide", return_value=builtin_fallback_guide()):
        result, guide = guided_lint_openapi_spec(DIRTY_SPEC, TENANT, project_id=PROJECT)
    assert guide is builtin_fallback_guide()
    assert result == lint_openapi_spec(DIRTY_SPEC)


# ===========================================================================
# Canonical-import LintReport re-scoring
# ===========================================================================


def test_lint_report_rescoring_is_a_noop_under_the_default_guide():
    from app.import_source import LintReport

    legacy = lint_openapi_spec(DIRTY_SPEC)
    report = LintReport.from_lint_result(legacy)
    rescored = apply_style_guide_to_lint_report(report, builtin_fallback_guide())
    assert rescored.score == report.score
    assert rescored.grade == report.grade
    assert rescored.report_fingerprint == report.report_fingerprint
    assert rescored.severity_counts == report.severity_counts


def test_lint_report_rescoring_applies_guide_overrides():
    from app.import_source import LintReport

    legacy = lint_openapi_spec(DIRTY_SPEC)
    report = LintReport.from_lint_result(legacy)
    guide = compile_style_guide(
        GUIDE, "Naming only", "custom", _rows(("naming.schema-pascal-case", True, "error"))
    )
    rescored = apply_style_guide_to_lint_report(report, guide)
    assert {f.rule for f in rescored.findings} == {"naming.schema-pascal-case"}
    assert rescored.severity_counts.get("error", 0) >= 1
    assert rescored.report_fingerprint != report.report_fingerprint


def test_lint_report_rescoring_skips_unscored_reports():
    from app.import_source import LintReport

    unscored = LintReport()
    assert apply_style_guide_to_lint_report(unscored, builtin_fallback_guide()) is unscored


# ===========================================================================
# Resolution
# ===========================================================================


def _db_stub(assigned=None, rows=None):
    stub = MagicMock()
    stub.get_assigned_style_guide.return_value = assigned
    stub.get_style_guide_rules.return_value = rows if rows is not None else []
    return stub


def test_resolution_compiles_the_assigned_guide():
    stub = _db_stub(
        assigned={"id": GUIDE, "name": "Team Guide", "source": "custom"},
        rows=_rows(("naming.schema-pascal-case", True, "error")),
    )
    with patch("app.database.db", stub):
        guide = resolve_style_guide(TENANT, PROJECT)
    assert guide.guide_id == GUIDE
    assert guide.name == "Team Guide"
    assert guide.severity_for("naming.schema-pascal-case") == "error"
    stub.get_assigned_style_guide.assert_called_once_with(TENANT, PROJECT)
    stub.get_style_guide_rules.assert_called_once_with(GUIDE, TENANT)


def test_resolution_passes_project_id_so_project_guides_can_win():
    """The engine always feeds the project into the accessor's project→tenant→default chain."""
    stub = _db_stub(assigned=None)
    with patch("app.database.db", stub):
        resolve_style_guide(TENANT, PROJECT)
        resolve_style_guide(TENANT)  # entry points without a project skip the project tier
    assert stub.get_assigned_style_guide.call_args_list[0].args == (TENANT, PROJECT)
    assert stub.get_assigned_style_guide.call_args_list[1].args == (TENANT, None)


def test_resolution_falls_back_when_nothing_is_assigned():
    with patch("app.database.db", _db_stub(assigned=None)):
        assert resolve_style_guide(TENANT, PROJECT) is builtin_fallback_guide()


def test_resolution_falls_back_on_malformed_accessor_output():
    # A broadly-mocked db (or a buggy accessor) must degrade to defaults, not to an
    # accidentally empty guide that scores everything 100.
    with patch("app.database.db", MagicMock()):
        assert resolve_style_guide(TENANT, PROJECT) is builtin_fallback_guide()


def test_resolution_falls_back_and_never_raises_on_db_fault():
    stub = MagicMock()
    stub.get_assigned_style_guide.side_effect = RuntimeError("db down")
    with patch("app.database.db", stub):
        assert resolve_style_guide(TENANT, PROJECT) is builtin_fallback_guide()


# ===========================================================================
# DB accessors (mocked execute_query)
# ===========================================================================


def _database_with_mock_query():
    db = Database.__new__(Database)  # skip __init__ (no pool); execute_query is mocked
    db.execute_query = MagicMock(return_value=[])
    return db


def test_get_assigned_style_guide_resolution_query_shape():
    db = _database_with_mock_query()
    db.execute_query.return_value = [{"id": GUIDE, "name": "g", "source": "custom"}]

    row = db.get_assigned_style_guide(TENANT, PROJECT)

    assert row == {"id": GUIDE, "name": "g", "source": "custom"}
    query, params = db.execute_query.call_args.args
    assert params == (PROJECT, TENANT, TENANT, TENANT)
    # The chain is one query: project assignment (0) beats tenant assignment (1) beats the
    # tenant default (2), and every candidate joins back to the tenant's own guides.
    assert "ORDER BY candidate.precedence" in query
    assert "LIMIT 1" in query
    assert "g.tenant_id = %s" in query
    assert query.index("a.project_id = %s") < query.index("a.tenant_id = %s")
    assert query.index("a.tenant_id = %s") < query.index("g2.is_default")


def test_get_assigned_style_guide_guards_non_uuid_input():
    db = _database_with_mock_query()
    assert db.get_assigned_style_guide("t1", PROJECT) is None
    db.execute_query.assert_not_called()

    # A non-UUID project (e.g. a slug or catalog item label) skips the project tier only.
    db.get_assigned_style_guide(TENANT, "not-a-uuid")
    _, params = db.execute_query.call_args.args
    assert params == (None, TENANT, TENANT, TENANT)


def test_get_style_guide_rules_scopes_by_tenant_and_guards_uuids():
    db = _database_with_mock_query()
    db.execute_query.return_value = _rows(("naming.schema-pascal-case", True, "error"))

    rows = db.get_style_guide_rules(GUIDE, TENANT)
    assert rows and rows[0]["rule_id"] == "naming.schema-pascal-case"
    query, params = db.execute_query.call_args.args
    assert params == (GUIDE, TENANT)
    assert "g.tenant_id = %s" in query

    db.execute_query.reset_mock()
    assert db.get_style_guide_rules("nope", TENANT) == []
    assert db.get_style_guide_rules(GUIDE, "t1") == []
    db.execute_query.assert_not_called()
