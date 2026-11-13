"""Unit tests for style-guide import/export (#1747) — :mod:`app.style_guide_transfer`.

Covers the export document's shape, the round trip export → import, and every way an import
document is rejected (with its pointer) or partially reported (unknown built-in ids).
"""

import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.style_guide_transfer import (
    FORMAT_ID,
    FORMAT_VERSION,
    MAX_DOCUMENT_BYTES,
    REASON_UNKNOWN_RULE,
    StyleGuideTransferError,
    build_export_document,
    export_filename,
    fetch_style_guide_document,
    parse_import_document,
)

REGISTERED = frozenset({"naming.path-kebab-case", "documentation.info-missing-description"})
STAMP = datetime(2026, 11, 12, 10, 0, 0, tzinfo=timezone.utc)

GUIDE = {"name": "Payments Guide", "description": "House rules", "external_lint_profile": "strict"}

CUSTOM_DEF = {
    "description": "Every server URL uses https.",
    "severity": "error",
    "given": ["$.servers[*].url"],
    "then": [{"function": "pattern", "functionOptions": {"match": "^https://"}}],
}

ROWS = [
    {"rule_id": "naming.path-kebab-case", "enabled": True, "severity": "error", "custom_def": None},
    {
        "rule_id": "documentation.info-missing-description",
        "enabled": False,
        "severity": "warning",
        "custom_def": None,
    },
    {"rule_id": "servers-use-https", "enabled": True, "severity": "error", "custom_def": CUSTOM_DEF},
]


def _doc(**over):
    """A minimal valid import document, with top-level overrides."""
    doc = {
        "format": FORMAT_ID,
        "formatVersion": FORMAT_VERSION,
        "guide": {"name": "Imported"},
        "builtinRules": [],
        "customRules": [],
    }
    doc.update(over)
    return json.dumps(doc)


def _reject(text):
    """Parse ``text`` expecting a rejection; return the error."""
    with pytest.raises(StyleGuideTransferError) as info:
        parse_import_document(text, registered_rule_ids=REGISTERED)
    return info.value


# --- Export ------------------------------------------------------------------------------------


def test_export_document_shape():
    doc = build_export_document(GUIDE, ROWS, reserved_rule_ids=REGISTERED, exported_at=STAMP)
    assert doc["format"] == FORMAT_ID
    assert doc["formatVersion"] == FORMAT_VERSION
    assert doc["exportedAt"] == "2026-11-12T10:00:00+00:00"
    assert doc["guide"] == {
        "name": "Payments Guide",
        "description": "House rules",
        "externalLintProfile": "strict",
    }
    # Built-in rows are sorted by id; disabled rows are kept.
    assert [r["ruleId"] for r in doc["builtinRules"]] == [
        "documentation.info-missing-description",
        "naming.path-kebab-case",
    ]
    assert doc["builtinRules"][0] == {
        "ruleId": "documentation.info-missing-description",
        "enabled": False,
        "severity": "warning",
    }
    assert doc["customRules"] == [{"ruleId": "servers-use-https", "definition": CUSTOM_DEF}]


def test_export_folds_a_custom_rule_severity_override_into_its_definition():
    rows = [{**ROWS[2], "severity": "info"}]
    doc = build_export_document(GUIDE, rows, reserved_rule_ids=REGISTERED)
    assert doc["customRules"][0]["definition"]["severity"] == "info"


def test_export_defaults_the_profile_to_baseline():
    doc = build_export_document({"name": "G"}, [], reserved_rule_ids=REGISTERED)
    assert doc["guide"]["externalLintProfile"] == "baseline"
    assert doc["builtinRules"] == [] and doc["customRules"] == []


def test_export_then_import_round_trips():
    doc = build_export_document(GUIDE, ROWS, reserved_rule_ids=REGISTERED, exported_at=STAMP)
    plan = parse_import_document(json.dumps(doc), registered_rule_ids=REGISTERED)
    assert plan.name == "Payments Guide"
    assert plan.description == "House rules"
    assert plan.external_lint_profile == "strict"
    assert plan.exported_at == "2026-11-12T10:00:00+00:00"
    assert plan.skipped == ()
    assert sorted(plan.builtin_rows, key=lambda r: r["rule_id"]) == [
        {"rule_id": "documentation.info-missing-description", "enabled": False, "severity": "warning"},
        {"rule_id": "naming.path-kebab-case", "enabled": True, "severity": "error"},
    ]
    assert plan.custom_rows == (
        {
            "rule_id": "servers-use-https",
            "enabled": True,
            "severity": "error",
            "custom_def": CUSTOM_DEF,
        },
    )


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Payments Guide", "payments-guide.style-guide.json"),
        ("  API / v2 — Rules!! ", "api-v2-rules.style-guide.json"),
        ("***", "style-guide.json"),
    ],
)
def test_export_filename(name, expected):
    assert export_filename(name) == expected


# --- Import: partial reports -------------------------------------------------------------------


def test_import_skips_and_reports_unknown_builtin_rule_ids():
    text = _doc(
        builtinRules=[
            {"ruleId": "naming.path-kebab-case", "enabled": True, "severity": "error"},
            {"ruleId": "future.rule", "enabled": True, "severity": "warning"},
        ]
    )
    plan = parse_import_document(text, registered_rule_ids=REGISTERED)
    assert [r["rule_id"] for r in plan.builtin_rows] == ["naming.path-kebab-case"]
    assert len(plan.skipped) == 1
    assert plan.skipped[0].rule_id == "future.rule"
    assert plan.skipped[0].reason == REASON_UNKNOWN_RULE


def test_import_allows_missing_optional_sections():
    plan = parse_import_document(
        json.dumps({"format": FORMAT_ID, "formatVersion": 1}), registered_rule_ids=REGISTERED
    )
    assert plan.name is None
    assert plan.builtin_rows == () and plan.custom_rows == ()


def test_import_normalizes_blank_strings_to_none():
    plan = parse_import_document(
        _doc(guide={"name": "  ", "description": ""}), registered_rule_ids=REGISTERED
    )
    assert plan.name is None and plan.description is None


# --- Import: rejections ------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["", "   "])
def test_import_rejects_an_empty_document(text):
    assert "empty" in _reject(text).message


def test_import_rejects_an_oversized_document():
    assert "limit" in _reject(" " * 10 + "x" * MAX_DOCUMENT_BYTES).message


def test_import_rejects_invalid_json():
    assert "not valid JSON" in _reject("{not json").message


def test_import_rejects_a_non_object_document():
    assert "JSON object" in _reject("[1, 2]").message


def test_import_rejects_a_foreign_format():
    err = _reject(json.dumps({"format": "other"}))
    assert err.pointer == "format"


def test_import_points_a_spectral_ruleset_at_the_spectral_importer():
    err = _reject(json.dumps({"extends": "spectral:oas", "rules": {}}))
    assert "/v1/lint/custom-rules/import" in err.message


@pytest.mark.parametrize("version", [2, "1", True, None])
def test_import_rejects_an_unsupported_format_version(version):
    err = _reject(json.dumps({"format": FORMAT_ID, "formatVersion": version}))
    assert err.pointer == "formatVersion"


def test_import_rejects_unknown_top_level_keys():
    err = _reject(_doc(policy={}))
    assert err.pointer == "policy"


def test_import_rejects_unknown_guide_keys():
    err = _reject(_doc(guide={"name": "X", "colour": "red"}))
    assert err.pointer == "guide.colour"


def test_import_rejects_a_non_string_guide_name():
    assert _reject(_doc(guide={"name": 5})).pointer == "guide.name"


@pytest.mark.parametrize(
    "entry,pointer",
    [
        ("nope", "builtinRules[0]"),
        ({"enabled": True, "severity": "error"}, "builtinRules[0].ruleId"),
        ({"ruleId": "naming.path-kebab-case", "enabled": "yes", "severity": "error"},
         "builtinRules[0].enabled"),
        ({"ruleId": "naming.path-kebab-case", "enabled": True, "severity": "fatal"},
         "builtinRules[0].severity"),
        ({"ruleId": "naming.path-kebab-case", "enabled": True, "severity": "error", "x": 1},
         "builtinRules[0].x"),
    ],
)
def test_import_rejects_malformed_builtin_entries(entry, pointer):
    assert _reject(_doc(builtinRules=[entry])).pointer == pointer


def test_import_rejects_builtin_rules_that_are_not_an_array():
    assert _reject(_doc(builtinRules={})).pointer == "builtinRules"


def test_import_rejects_duplicate_builtin_rule_ids():
    entry = {"ruleId": "naming.path-kebab-case", "enabled": True, "severity": "error"}
    assert _reject(_doc(builtinRules=[entry, entry])).pointer == "builtinRules[1].ruleId"


def test_import_rejects_an_invalid_custom_definition_with_its_pointer():
    bad = {**CUSTOM_DEF, "then": [{"function": "eval"}]}
    err = _reject(_doc(customRules=[{"ruleId": "servers-use-https", "definition": bad}]))
    assert err.pointer.startswith("customRules[0].definition")


def test_import_rejects_a_custom_rule_shadowing_a_builtin_id():
    err = _reject(_doc(customRules=[{"ruleId": "naming.path-kebab-case", "definition": CUSTOM_DEF}]))
    assert err.pointer.startswith("customRules[0]")


def test_import_rejects_duplicate_custom_rule_ids():
    entry = {"ruleId": "servers-use-https", "definition": CUSTOM_DEF}
    assert _reject(_doc(customRules=[entry, entry])).pointer == "customRules[1].ruleId"


def test_import_rejects_too_many_custom_rules():
    entries = [{"ruleId": f"r-{i}", "definition": CUSTOM_DEF} for i in range(201)]
    assert _reject(_doc(customRules=entries)).pointer == "customRules"


# --- Fetch -------------------------------------------------------------------------------------


def test_fetch_returns_text_and_resolved_label():
    class _Ingested:
        text = "{}"
        resolved_label = "https://example.com/guide.json"

    with patch("app.import_ingestion.ingest_source", return_value=_Ingested()) as ingest:
        assert fetch_style_guide_document("https://example.com/guide.json") == (
            "{}",
            "https://example.com/guide.json",
        )
    assert ingest.call_args.kwargs["max_bytes"] == MAX_DOCUMENT_BYTES


def test_fetch_wraps_ingestion_errors():
    from app.import_ingestion import IngestionError

    with patch(
        "app.import_ingestion.ingest_source", side_effect=IngestionError("blocked address")
    ):
        with pytest.raises(StyleGuideTransferError) as info:
            fetch_style_guide_document("http://169.254.169.254/")
    assert "blocked" in info.value.message
