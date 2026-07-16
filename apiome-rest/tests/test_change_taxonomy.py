"""Unit tests for CTG-1.1 change taxonomy & classifier (#4467)."""

from __future__ import annotations

import copy

import pytest

from app.change_taxonomy import (
    UNCLASSIFIED_RULE_ID,
    ClassifiedDiff,
    classify_openapi_changes,
    classify_raw_changes,
    clear_severity_overrides,
    get_rule,
    list_rules,
    override_severity,
    register_rule,
)
from app.change_taxonomy_enum import RawChange, json_pointer_escape, json_pointer_join
from app.change_taxonomy_rules import TaxonomyRule, unregister_rule


def _pet_docs() -> tuple[dict, dict]:
    base = {
        "openapi": "3.1.0",
        "info": {"title": "Pets", "version": "1.0.0"},
        "paths": {
            "/pets": {
                "get": {
                    "responses": {"200": {"description": "ok"}},
                }
            }
        },
        "components": {
            "schemas": {
                "Pet": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}, "name": {"type": "string"}},
                    "required": ["id"],
                }
            }
        },
    }
    return base, copy.deepcopy(base)


def test_json_pointer_escape_and_join() -> None:
    assert json_pointer_escape("a/b~c") == "a~1b~0c"
    assert json_pointer_join("paths", "/pets") == "/paths/~1pets"


def test_identical_documents_empty() -> None:
    base, head = _pet_docs()
    result = classify_openapi_changes(base, head)
    assert result.changes == []
    assert result.max_severity is None
    assert result.counts["total"] == 0


def test_path_removed_is_breaking() -> None:
    base, head = _pet_docs()
    del head["paths"]["/pets"]
    result = classify_openapi_changes(base, head)
    assert len(result.changes) == 1
    change = result.changes[0]
    assert change.rule_id == "ctg.path_removed"
    assert change.severity == "breaking"
    assert change.pointer == "/paths/~1pets"
    assert change.unclassified is False
    assert result.max_severity == "breaking"


def test_property_added_is_non_breaking() -> None:
    base, head = _pet_docs()
    head["components"]["schemas"]["Pet"]["properties"]["tag"] = {"type": "string"}
    result = classify_openapi_changes(base, head)
    assert len(result.changes) == 1
    assert result.changes[0].rule_id == "ctg.property_added"
    assert result.changes[0].severity == "non-breaking"
    assert result.max_severity == "non-breaking"


def test_docs_only_description() -> None:
    base, head = _pet_docs()
    head["info"]["description"] = "hello"
    result = classify_openapi_changes(base, head)
    assert len(result.changes) == 1
    assert result.changes[0].rule_id == "ctg.docs_description"
    assert result.changes[0].severity == "docs-only"
    assert result.changes[0].before is None
    assert result.changes[0].after == "hello"


def test_unclassified_fail_safe() -> None:
    result = classify_raw_changes(
        [RawChange(kind="no_such_kind", pointer="/foo", before=1, after=2)]
    )
    assert len(result.changes) == 1
    change = result.changes[0]
    assert change.rule_id == UNCLASSIFIED_RULE_ID
    assert change.severity == "breaking"
    assert change.unclassified is True
    assert result.counts["unclassified"] == 1


def test_severity_override_call_site() -> None:
    base, head = _pet_docs()
    del head["paths"]["/pets"]
    result = classify_openapi_changes(
        base, head, overrides={"ctg.path_removed": "non-breaking"}
    )
    assert result.changes[0].severity == "non-breaking"
    assert result.max_severity == "non-breaking"


def test_severity_override_registry() -> None:
    clear_severity_overrides()
    try:
        override_severity("ctg.path_removed", "docs-only")
        base, head = _pet_docs()
        del head["paths"]["/pets"]
        result = classify_openapi_changes(base, head)
        assert result.changes[0].severity == "docs-only"
    finally:
        clear_severity_overrides()


def test_override_unknown_rule_raises() -> None:
    with pytest.raises(ValueError, match="unknown taxonomy rule"):
        override_severity("ctg.does_not_exist", "breaking")


def test_register_rule_conflict_raises() -> None:
    existing = get_rule("ctg.path_removed")
    assert existing is not None
    with pytest.raises(ValueError, match="already registered"):
        register_rule(
            TaxonomyRule(
                rule_id="ctg.path_removed",
                change_kind="path_removed",
                severity="non-breaking",
                summary="conflict",
            )
        )


def test_register_identical_rule_noop() -> None:
    existing = get_rule("ctg.path_removed")
    assert existing is not None
    register_rule(existing)  # identical re-register


def test_register_new_rule_extends_classifier() -> None:
    rule = TaxonomyRule(
        rule_id="ctg.test_custom",
        change_kind="custom_test_kind",
        severity="docs-only",
        summary="test-only custom rule",
    )
    register_rule(rule)
    try:
        result = classify_raw_changes(
            [RawChange(kind="custom_test_kind", pointer="/custom", before=None, after=True)]
        )
        assert result.changes[0].rule_id == "ctg.test_custom"
        assert result.changes[0].severity == "docs-only"
        assert result.changes[0].unclassified is False
    finally:
        unregister_rule("ctg.test_custom")


def test_list_rules_includes_defaults() -> None:
    ids = {r.rule_id for r in list_rules()}
    assert "ctg.path_removed" in ids
    assert "ctg.docs_description" in ids
    assert "ctg.property_added" in ids


def test_max_severity_worst_of() -> None:
    result = classify_raw_changes(
        [
            RawChange(kind="docs_description", pointer="/a", before="x", after="y"),
            RawChange(kind="path_added", pointer="/b", after={}),
            RawChange(kind="path_removed", pointer="/c", before={}),
        ]
    )
    assert result.max_severity == "breaking"
    assert result.counts["breaking"] == 1
    assert result.counts["non-breaking"] == 1
    assert result.counts["docs-only"] == 1


def test_classified_diff_json_roundtrip() -> None:
    base, head = _pet_docs()
    head["info"]["description"] = "x"
    result = classify_openapi_changes(base, head)
    restored = ClassifiedDiff.model_validate(result.model_dump())
    assert restored == result
