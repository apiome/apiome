"""``apiome versions compatibility`` (CLI 4.8, #3215).

The rules (:mod:`apiome_cli.version_compat`) and the command against a mocked REST API. A known
breaking-change fixture (a removed path) exits 6; ``--ignore`` and ``--allow-removals`` suppress it
for the exit code; head defaults to the latest version and base to the previous published one;
server failures exit 8; ``--json`` carries rule ids, severities and paths; ``--sarif`` validates
against the official SARIF 2.1.0 schema (vendored in ``tests/fixtures/sarif``).
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
from typer.testing import CliRunner

from apiome_cli.exit_codes import (
    EXIT_BREAKING_CHANGES,
    EXIT_COMPAT_UNAVAILABLE,
    EXIT_SUCCESS,
    EXIT_USAGE,
)
from apiome_cli.main import app
from apiome_cli.version_compat import (
    CompatError,
    at_least,
    breaking,
    classify,
    default_base,
    default_head,
    normalize_rule,
    render_result,
    render_table,
    to_sarif,
)

runner = CliRunner()

_ENV = {
    "APIOME_API_KEY": "obj_test_key",
    "APIOME_BASE_URL": "http://localhost:8000",
    "APIOME_TENANT_ID": "acme",
}
_HOST = "http://localhost:8000/v1"
_PROJECT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_V19 = "19191919-1919-4919-8919-191919191919"
_V20 = "20202020-2020-4020-8020-202020202020"
_V21 = "21212121-2121-4121-8121-212121212121"
_V30 = "30303030-3030-4030-8030-303030303030"
_COMPAT = f"{_HOST}/versions/acme/{_PROJECT}/compatibility"
_SARIF_SCHEMA = json.loads(
    (Path(__file__).parent / "fixtures" / "sarif" / "sarif-schema-2.1.0.json").read_text()
)

_VERSIONS = [
    {
        "id": _V19,
        "version_id": "1.9.0",
        "published": True,
        "created_at": "2026-08-01T00:00:00Z",
        "project_slug": "payments-api",
    },
    {
        "id": _V20,
        "version_id": "2.0.0",
        "published": True,
        "created_at": "2026-09-01T00:00:00Z",
        "project_slug": "payments-api",
    },
    {
        "id": _V21,
        "version_id": "2.1.0",
        "published": False,
        "created_at": "2026-10-01T00:00:00Z",
        "project_slug": "payments-api",
    },
]
_TAGS = [{"id": "t1", "name": "stable", "version_id": _V20}]

#: The known breaking-change fixture: one path removed, plus safe and unknown findings.
_FINDINGS = [
    {
        "id": "cmp-1",
        "path": "/paths/~1v1~1charges~1legacy",
        "category": "breaking",
        "rule": "path_removed",
        "message": "Path removed",
    },
    {
        "id": "cmp-2",
        "path": "/components/schemas/RefundReason",
        "category": "safe",
        "rule": "schema_added",
        "message": "Schema added",
    },
    {
        "id": "cmp-3",
        "path": "/paths/~1refunds/post",
        "category": "safe",
        "rule": "operation_added",
        "message": "Operation added",
    },
    {
        "id": "cmp-4",
        "path": "/components/schemas/Charge/properties/idempotency",
        "category": "safe",
        "rule": "property_added",
        "message": "Optional property added",
    },
    {
        "id": "cmp-5",
        "path": "/components/schemas/Charge/properties/note/pattern",
        "category": "unknown",
        "rule": "pattern_changed",
        "message": "Pattern changed",
    },
]
_REPORT = {
    "overall": "breaking",
    "baseRevisionId": _V20,
    "headRevisionId": _V21,
    "findings": _FINDINGS,
    "reportFingerprint": "fp1",
}


def _mock(httpx_mock, *, report=_REPORT, status=200, tags=True) -> None:
    httpx_mock.add_response(url=f"{_HOST}/projects/acme/by-slug/payments-api", json={"id": _PROJECT})
    httpx_mock.add_response(url=f"{_HOST}/versions/acme/{_PROJECT}", json=_VERSIONS)
    if tags:
        httpx_mock.add_response(url=f"{_HOST}/version-tags/acme/{_PROJECT}", json=_TAGS, is_optional=True)
    httpx_mock.add_response(method="POST", url=_COMPAT, status_code=status, json=report, is_optional=True)


def _compat_body(httpx_mock) -> dict:
    return json.loads([r for r in httpx_mock.get_requests() if r.method == "POST"][0].content)


# --- rules ----------------------------------------------------------------------------------


def test_head_defaults_to_the_latest_and_base_to_the_previous_published() -> None:
    head = default_head(_VERSIONS)
    assert head["id"] == _V21
    assert default_base(_VERSIONS, head)["id"] == _V20


def test_a_draft_is_never_the_default_base() -> None:
    versions = [
        *_VERSIONS,
        {"id": _V30, "version_id": "3.0.0", "published": False, "created_at": "2026-10-10T00:00:00Z"},
    ]
    assert default_base(versions, default_head(versions))["id"] == _V20


def test_no_published_base_is_refused() -> None:
    with pytest.raises(CompatError, match="pass --base"):
        default_base([_VERSIONS[2]], _VERSIONS[2])
    with pytest.raises(CompatError, match="no versions"):
        default_head([])


@pytest.mark.parametrize(
    ("spelling", "rule"),
    [
        ("path_removed", "path_removed"),
        ("removed-path", "path_removed"),
        ("Path-Removed", "path_removed"),
        ("narrowed-enum", "enum_narrowed"),
        ("type_structure_change", "type_structure_change"),
    ],
)
def test_rule_spellings(spelling, rule) -> None:
    assert normalize_rule(spelling) == rule


def test_classification_maps_category_to_severity_and_kind() -> None:
    by_rule = {f.rule: f for f in classify(_FINDINGS)}
    assert (by_rule["path_removed"].severity, by_rule["path_removed"].kind) == ("error", "removal")
    assert (by_rule["schema_added"].severity, by_rule["schema_added"].kind) == ("info", "addition")
    assert (by_rule["pattern_changed"].severity, by_rule["pattern_changed"].kind) == ("warn", "change")
    assert [f.rule for f in breaking(classify(_FINDINGS))] == ["path_removed"]


def test_required_field_added_is_a_breaking_change_not_an_addition() -> None:
    (f,) = classify(
        [{"id": "x", "path": "/p", "category": "breaking", "rule": "required_field_added", "message": "m"}]
    )
    assert f.kind == "change" and f.breaking


def test_allow_removals_downgrades_removals_for_the_exit_logic() -> None:
    findings = classify(_FINDINGS, allow_removals=True)
    removed = next(f for f in findings if f.rule == "path_removed")
    assert (removed.severity, removed.original_severity, removed.suppressed_by) == (
        "warn",
        "error",
        "allow-removals",
    )
    assert breaking(findings) == []


def test_ignore_suppresses_a_rule() -> None:
    findings = classify(_FINDINGS, ignore=["removed-path"])
    assert breaking(findings) == []
    assert next(f for f in findings if f.rule == "path_removed").suppressed_by == "ignore"


def test_severity_filters_the_display() -> None:
    findings = classify(_FINDINGS)
    assert [f.severity for f in at_least(findings, "warn")] == ["error", "warn"]
    assert len(at_least(findings, "info")) == 5


def test_the_result_line_names_the_breaking_change() -> None:
    assert (
        render_result(classify(_FINDINGS))
        == "Result: 1 breaking change found (path_removed /paths/~1v1~1charges~1legacy)."
    )
    assert render_result(classify(_FINDINGS, allow_removals=True)) == (
        "Result: no breaking changes. 1 suppressed (--ignore / --allow-removals)."
    )


def test_the_table_is_boxed_and_most_severe_first() -> None:
    lines = render_table(classify(_FINDINGS)).splitlines()
    assert lines[0].startswith("  ╔") and lines[-1].startswith("  ╚")
    assert "SEVERITY" in lines[1] and "FINDING" in lines[1]
    assert "✖ error" in lines[3] and "- removal  path_removed" in lines[3]
    assert render_table([]) == "  No findings."


def test_sarif_validates_against_the_schema() -> None:
    log = to_sarif(
        findings=classify(_FINDINGS, ignore=["pattern_changed"]),
        artifact_uri="v1/schema/acme/payments-api/2.1.0",
        tool_version="0.0.0",
        base=_VERSIONS[1],
        head=_VERSIONS[2],
    )
    jsonschema.Draft4Validator(_SARIF_SCHEMA).validate(log)
    results = log["runs"][0]["results"]
    assert {r["ruleId"]: r["level"] for r in results}["path_removed"] == "error"
    assert (
        next(r for r in results if r["ruleId"] == "pattern_changed")["suppressions"][0]["kind"] == "external"
    )
    rules = log["runs"][0]["tool"]["driver"]["rules"]
    assert all(rules[r["ruleIndex"]]["id"] == r["ruleId"] for r in results)


def test_an_empty_sarif_log_validates_too() -> None:
    log = to_sarif(
        findings=[], artifact_uri="v1/schema/a/b/1", tool_version="0", base=_VERSIONS[1], head=_VERSIONS[2]
    )
    jsonschema.Draft4Validator(_SARIF_SCHEMA).validate(log)


# --- the command ----------------------------------------------------------------------------


def test_the_breaking_fixture_exits_6(httpx_mock) -> None:
    _mock(httpx_mock, tags=False)
    result = runner.invoke(app, ["versions", "compatibility", "payments-api"], env=_ENV)
    assert result.exit_code == EXIT_BREAKING_CHANGES, result.output
    assert "Comparing 2.0.0 → 2.1.0" in result.stderr
    assert "Result: 1 breaking change found" in result.stdout
    assert _compat_body(httpx_mock) == {"baseRevisionId": _V20, "headRevisionId": _V21}


def test_allow_removals_passes_the_gate(httpx_mock) -> None:
    _mock(httpx_mock, tags=False)
    result = runner.invoke(app, ["versions", "compatibility", "payments-api", "--allow-removals"], env=_ENV)
    assert result.exit_code == EXIT_SUCCESS, result.output


def test_ignore_accepts_repeats_and_commas(httpx_mock) -> None:
    _mock(httpx_mock, tags=False)
    result = runner.invoke(
        app,
        [
            "versions",
            "compatibility",
            "payments-api",
            "--ignore",
            "removed-path,pattern_changed",
            "--ignore",
            "schema_added",
        ],
        env=_ENV,
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "3 suppressed" in result.stdout


def test_a_clean_comparison_exits_0(httpx_mock) -> None:
    _mock(httpx_mock, report={**_REPORT, "overall": "safe", "findings": _FINDINGS[1:4]}, tags=False)
    result = runner.invoke(app, ["versions", "compatibility", "payments-api"], env=_ENV)
    assert result.exit_code == EXIT_SUCCESS
    assert "Result: no breaking changes." in result.stdout


def test_explicit_base_and_head_by_label_and_tag(httpx_mock) -> None:
    _mock(httpx_mock)
    result = runner.invoke(
        app, ["versions", "compatibility", "payments-api", "--base", "v1.9.0", "--head", "stable"], env=_ENV
    )
    assert result.exit_code == EXIT_BREAKING_CHANGES, result.output
    assert _compat_body(httpx_mock) == {"baseRevisionId": _V19, "headRevisionId": _V20}


def test_an_unknown_ref_is_a_usage_error(httpx_mock) -> None:
    _mock(httpx_mock)
    result = runner.invoke(app, ["versions", "compatibility", "payments-api", "--base", "9.9.9"], env=_ENV)
    assert result.exit_code == EXIT_USAGE
    assert "No version or version tag '9.9.9'" in result.stderr


def test_the_same_base_and_head_is_refused(httpx_mock) -> None:
    _mock(httpx_mock)
    result = runner.invoke(
        app, ["versions", "compatibility", "payments-api", "--base", "2.0.0", "--head", "stable"], env=_ENV
    )
    assert result.exit_code == EXIT_USAGE
    assert "same version" in result.stderr


def test_a_server_error_exits_8(httpx_mock) -> None:
    _mock(httpx_mock, report={"detail": "boom"}, status=500, tags=False)
    result = runner.invoke(app, ["versions", "compatibility", "payments-api"], env=_ENV)
    assert result.exit_code == EXIT_COMPAT_UNAVAILABLE, result.output


def test_a_server_error_listing_versions_exits_8(httpx_mock) -> None:
    httpx_mock.add_response(url=f"{_HOST}/projects/acme/by-slug/payments-api", json={"id": _PROJECT})
    httpx_mock.add_response(url=f"{_HOST}/versions/acme/{_PROJECT}", status_code=503, json={"detail": "down"})
    result = runner.invoke(app, ["versions", "compatibility", "payments-api"], env=_ENV)
    assert result.exit_code == EXIT_COMPAT_UNAVAILABLE


def test_a_missing_revision_404_is_a_usage_error_not_8(httpx_mock) -> None:
    _mock(httpx_mock, report={"detail": "Revision not found"}, status=404, tags=False)
    result = runner.invoke(app, ["versions", "compatibility", "payments-api"], env=_ENV)
    assert result.exit_code == EXIT_USAGE


def test_json_carries_rule_ids_severity_and_paths(httpx_mock) -> None:
    _mock(httpx_mock, tags=False)
    result = runner.invoke(
        app, ["--json", "versions", "compatibility", "payments-api", "--severity", "warn"], env=_ENV
    )
    assert result.exit_code == EXIT_BREAKING_CHANGES
    body = json.loads(result.stdout)
    assert body["base"] == {"id": _V20, "version": "2.0.0"} and body["head"] == {
        "id": _V21,
        "version": "2.1.0",
    }
    assert body["breaking"] == 1 and body["exitCode"] == 6
    assert [(f["rule"], f["severity"], f["path"]) for f in body["findings"]] == [
        ("path_removed", "error", "/paths/~1v1~1charges~1legacy"),
        ("pattern_changed", "warn", "/components/schemas/Charge/properties/note/pattern"),
    ]


def test_sarif_output_is_valid_and_keeps_the_exit_code(httpx_mock) -> None:
    _mock(httpx_mock, tags=False)
    result = runner.invoke(app, ["versions", "compatibility", "payments-api", "--sarif"], env=_ENV)
    assert result.exit_code == EXIT_BREAKING_CHANGES
    log = json.loads(result.stdout)
    jsonschema.Draft4Validator(_SARIF_SCHEMA).validate(log)
    location = log["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
    assert location == "v1/schema/acme/payments-api/2.1.0"


def test_sarif_and_json_together_are_refused() -> None:
    result = runner.invoke(app, ["--json", "versions", "compatibility", "payments-api", "--sarif"], env=_ENV)
    assert result.exit_code == EXIT_USAGE


def test_a_bad_severity_is_refused() -> None:
    result = runner.invoke(
        app, ["versions", "compatibility", "payments-api", "--severity", "fatal"], env=_ENV
    )
    assert result.exit_code == EXIT_USAGE
