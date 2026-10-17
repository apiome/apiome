"""Tests for ``apiome schema diff <tenant>/<project> <v1> <v2>`` (CLI 9.8, #3251).

Two fixture versions of acme-corp/payments-api live in ``tests/fixtures/schema_diff/``. Between
2.0.0 and 2.1.0:

* paths — ``POST /refunds`` and ``GET /refunds/{id}`` added, ``GET /v1/charges/legacy`` removed,
  ``POST /charges`` changed (summary text only);
* classes — ``Refund`` added, ``Payout`` removed, ``Charge`` changed, ``Customer`` changed
  (description text only);
* properties — ``Charge.refunded`` added, ``Charge.legacy_code`` removed, ``Charge.amount``
  changed (``minimum``), ``Customer.email`` changed (description only).
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
from typer.testing import CliRunner

from apiome_cli import schema_diff as d
from apiome_cli.exit_codes import EXIT_DIFFERENCES, EXIT_ERROR, EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app
from apiome_cli.published_spec import parse_project_ref

runner = CliRunner()

_HOST = "http://localhost:8000"
_SCHEMA = f"{_HOST}/v1/schema/acme-corp/payments-api"
_FIXTURES = Path(__file__).parent / "fixtures" / "schema_diff"
_V200 = (_FIXTURES / "payments-2.0.0.json").read_bytes()
_V210 = (_FIXTURES / "payments-2.1.0.json").read_bytes()
_BASE = json.loads(_V200)
_HEAD = json.loads(_V210)
_SARIF_SCHEMA = json.loads((Path(__file__).parent / "fixtures" / "sarif" / "sarif-schema-2.1.0.json").read_text())
_ARGS = ["schema", "diff", "acme-corp/payments-api", "2.0.0", "2.1.0"]


@pytest.fixture(autouse=True)
def base_url_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the CLI at the mocked host with no API key or tenant (public routes)."""
    monkeypatch.setenv("APIOME_BASE_URL", _HOST)
    monkeypatch.delenv("APIOME_API_KEY", raising=False)
    monkeypatch.delenv("APIOME_TENANT_ID", raising=False)


def _serve(httpx_mock: object, base: bytes = _V200, head: bytes = _V210) -> None:
    httpx_mock.add_response(url=f"{_SCHEMA}/2.0.0", content=base, headers={"Content-Type": "application/json"})
    httpx_mock.add_response(url=f"{_SCHEMA}/2.1.0", content=head, headers={"Content-Type": "application/json"})


def _targets(changes: list[d.Change], kind: str, action: str) -> list[str]:
    return [c.target for c in changes if c.kind == kind and c.action == action]


# --- differ ----------------------------------------------------------------------------------


def test_diff_specs_finds_every_kind_and_action() -> None:
    """Operations, classes and properties are each reported added / removed / changed."""
    changes = d.diff_specs(_BASE, _HEAD)
    assert _targets(changes, "path", "added") == ["GET /refunds/{id}", "POST /refunds"]
    assert _targets(changes, "path", "removed") == ["GET /v1/charges/legacy"]
    assert _targets(changes, "path", "changed") == ["POST /charges"]
    assert _targets(changes, "class", "added") == ["Refund"]
    assert _targets(changes, "class", "removed") == ["Payout"]
    assert _targets(changes, "class", "changed") == ["Charge", "Customer"]
    assert _targets(changes, "property", "added") == ["Charge.refunded"]
    assert _targets(changes, "property", "removed") == ["Charge.legacy_code"]
    assert _targets(changes, "property", "changed") == ["Charge.amount", "Customer.email"]


def test_added_class_properties_are_not_counted_separately() -> None:
    """Refund's properties belong to the 'class added' row, not to 'property added'."""
    assert not [c for c in d.diff_specs(_BASE, _HEAD) if c.target.startswith("Refund.")]


def test_description_only_flag_and_ignore() -> None:
    """Prose-only changes are flagged, and --ignore description-only drops just those."""
    changes = d.diff_specs(_BASE, _HEAD)
    prose = {c.target for c in changes if c.description_only}
    assert prose == {"POST /charges", "Customer", "Customer.email"}
    kept = d.apply_ignore(changes, ["description-only"])
    assert {c.target for c in kept} == {c.target for c in changes} - prose


def test_identical_documents_have_no_changes() -> None:
    """The same document twice — even with info.version bumped — is identical."""
    bumped = json.loads(_V200)
    bumped["info"]["version"] = "9.9.9"
    assert d.diff_specs(_BASE, bumped) == []


def test_scope_limits_the_comparison() -> None:
    """--scope paths compares only operations; schemas only classes and properties."""
    assert {c.kind for c in d.diff_specs(_BASE, _HEAD, scope="paths")} == {"path"}
    assert {c.kind for c in d.diff_specs(_BASE, _HEAD, scope="schemas")} == {"class", "property"}
    with pytest.raises(ValueError, match="--scope"):
        d.diff_specs(_BASE, _HEAD, scope="everything")


def test_path_level_keys_and_pointers() -> None:
    """Shared path-item keys are reported as '/path'; pointers escape '/' and '~' (RFC 6901)."""
    head = json.loads(_V200)
    head["paths"]["/customers/{id}"]["parameters"][0]["required"] = False
    change = d.diff_specs(_BASE, head)[0]
    assert (change.target, change.action, change.pointer) == (
        "/customers/{id}",
        "changed",
        "/paths/~1customers~1{id}",
    )
    assert d._escape_pointer("a~b/c") == "a~0b~1c"


def test_malformed_sections_are_tolerated() -> None:
    """Missing or non-mapping paths/components do not crash the differ."""
    assert d.diff_specs({"paths": None}, {"components": []}) == []


def test_normalize_ignore() -> None:
    """--ignore accepts any case and '_' spelling, de-duplicates, and rejects unknown rules."""
    assert d.normalize_ignore(["Description_Only", "description-only"]) == ["description-only"]
    with pytest.raises(ValueError, match="description-only"):
        d.normalize_ignore(["whitespace"])


def test_render_summary_matches_the_issue_shape() -> None:
    """One line per kind/action that occurred, three targets then '…', and a pointer line."""
    many = [d.Change("class", "changed", name, f"/x/{name}") for name in ("A", "B", "C", "D", "E")]
    text = d.render_summary(many, base_label="v2.0.0", head_label="v2.1.0")
    assert text.splitlines() == [
        "Comparing v2.0.0 → v2.1.0 …",
        "  ~ 5 changed classes (A, B, C, …)",
        "",
        "Use `--format unified` or `--format json` for the full diff.",
    ]
    assert d.render_summary([], base_label="a", head_label="b").endswith("No differences.")


def test_render_unified_is_a_sorted_json_diff() -> None:
    """Unified text has file headers and the changed lines; identical documents give ''."""
    text = d.render_unified(_BASE, _HEAD, base_label="a/2.0.0", head_label="a/2.1.0", scope="paths")
    assert text.startswith("--- a/2.0.0\n+++ a/2.1.0\n")
    assert '+    "/refunds": {' in text
    assert '"components"' not in text
    assert d.render_unified(_BASE, _BASE, base_label="a", head_label="b") == ""


def test_render_unified_ignores_prose_when_asked() -> None:
    """With description-only ignored, a prose-only edit leaves no diff lines."""
    head = json.loads(_V200)
    head["components"]["schemas"]["Customer"]["description"] = "Someone who pays."
    assert d.render_unified(_BASE, head, base_label="a", head_label="b") != ""
    assert d.render_unified(_BASE, head, base_label="a", head_label="b", ignore=["description-only"]) == ""


def test_to_sarif_validates_against_the_sarif_schema() -> None:
    """The SARIF log is valid SARIF 2.1.0, one note result per change, pointer as location."""
    changes = d.diff_specs(_BASE, _HEAD)
    log = d.to_sarif(changes, artifact_uri="/v1/schema/a/b/2.1.0", tool_version="0", base={}, head={})
    jsonschema.Draft4Validator(_SARIF_SCHEMA).validate(log)
    results = log["runs"][0]["results"]
    assert len(results) == len(changes)
    assert {r["level"] for r in results} == {"note"}
    first = results[0]
    assert first["ruleId"] == "path-added"
    assert first["locations"][0]["logicalLocations"][0]["fullyQualifiedName"] == "/paths/~1refunds~1{id}/get"
    empty = d.to_sarif([], artifact_uri="x", tool_version="0", base={}, head={})
    jsonschema.Draft4Validator(_SARIF_SCHEMA).validate(empty)


def test_to_json_counts_and_identical() -> None:
    """JSON carries per-kind counts (zeros included) and the identical flag."""
    payload = d.to_json(d.diff_specs(_BASE, _HEAD), base={}, head={}, scope="all", ignore=[])
    assert payload["identical"] is False
    assert payload["counts"]["path"] == {"added": 2, "removed": 1, "changed": 1}
    assert payload["changes"][0] == {
        "kind": "path",
        "action": "added",
        "target": "GET /refunds/{id}",
        "pointer": "/paths/~1refunds~1{id}/get",
        "rule": "path-added",
        "descriptionOnly": False,
    }
    assert d.to_json([], base={}, head={}, scope="all", ignore=[])["identical"] is True


def test_parse_project_ref() -> None:
    """tenant/project splits in two; anything else is a usage error."""
    assert parse_project_ref("acme-corp/payments-api") == ("acme-corp", "payments-api")
    for bad in ("acme-corp", "a/b/c", "a/"):
        with pytest.raises(ValueError, match="<tenant>/<project>"):
            parse_project_ref(bad)


# --- command ---------------------------------------------------------------------------------


def test_summary_is_the_default(httpx_mock: object) -> None:
    """With no flags both versions are fetched from /v1/schema and summarised on stdout."""
    _serve(httpx_mock)
    result = runner.invoke(app, _ARGS)
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert result.stdout.startswith("Comparing 2.0.0 → 2.1.0 …\n")
    assert "  + 2 added paths (GET /refunds/{id}, POST /refunds)\n" in result.stdout
    assert "  - 1 removed path (GET /v1/charges/legacy)\n" in result.stdout


def test_exit_code_one_when_versions_differ(httpx_mock: object) -> None:
    """--exit-code makes differences exit 1 (git-like)."""
    _serve(httpx_mock)
    result = runner.invoke(app, [*_ARGS, "--exit-code"])
    assert result.exit_code == EXIT_DIFFERENCES == 1


def test_exit_code_zero_when_identical(httpx_mock: object) -> None:
    """--exit-code exits 0 when nothing differs — the 'my pinned version did not move' check."""
    _serve(httpx_mock, head=_V200)
    result = runner.invoke(app, [*_ARGS, "--exit-code"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "No differences." in result.stdout


def test_exit_code_respects_ignore(httpx_mock: object) -> None:
    """A prose-only edit is a difference, unless --ignore description-only drops it."""
    head = json.loads(_V200)
    head["components"]["schemas"]["Customer"]["description"] = "Someone who pays."
    body = json.dumps(head).encode()
    httpx_mock.add_response(url=f"{_SCHEMA}/2.0.0", content=_V200, is_reusable=True)
    httpx_mock.add_response(url=f"{_SCHEMA}/2.1.0", content=body, is_reusable=True)
    assert runner.invoke(app, [*_ARGS, "--exit-code"]).exit_code == EXIT_DIFFERENCES
    ignored = runner.invoke(app, [*_ARGS, "--exit-code", "--ignore", "description-only"])
    assert ignored.exit_code == EXIT_SUCCESS, ignored.output


def test_server_error_with_exit_code_is_2(httpx_mock: object) -> None:
    """Under --exit-code a 5xx exits 2, so 1 can only mean 'differs'; without it, 1 as usual."""
    httpx_mock.add_response(url=f"{_SCHEMA}/2.0.0", status_code=500, json={"detail": "boom"}, is_reusable=True)
    assert runner.invoke(app, [*_ARGS, "--exit-code"]).exit_code == EXIT_USAGE
    assert runner.invoke(app, _ARGS).exit_code == EXIT_ERROR


def test_unknown_version_exits_2(httpx_mock: object) -> None:
    """An unknown or unpublished version is the route's 4xx: exit 2, nothing on stdout."""
    httpx_mock.add_response(url=f"{_SCHEMA}/2.0.0", status_code=403, json={"detail": "This version is not published"})
    result = runner.invoke(app, _ARGS)
    assert result.exit_code == EXIT_USAGE
    assert result.stdout == ""


def test_v_prefixed_labels_fall_back_to_bare(httpx_mock: object) -> None:
    """v2.0.0 / v2.1.0 are retried as 2.0.0 / 2.1.0 when the v-form is not found."""
    httpx_mock.add_response(url=f"{_SCHEMA}/v2.0.0", status_code=404, json={"detail": "Version not found"})
    httpx_mock.add_response(url=f"{_SCHEMA}/v2.1.0", status_code=404, json={"detail": "Version not found"})
    _serve(httpx_mock)
    result = runner.invoke(app, ["schema", "diff", "acme-corp/payments-api", "v2.0.0", "v2.1.0"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert result.stdout.startswith("Comparing 2.0.0 → 2.1.0 …")


def test_unified_format(httpx_mock: object) -> None:
    """--format unified prints a unified diff headed by both tenant/project/version labels."""
    _serve(httpx_mock)
    result = runner.invoke(app, [*_ARGS, "--format", "unified"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert result.stdout.startswith(
        "--- acme-corp/payments-api/2.0.0\n+++ acme-corp/payments-api/2.1.0\n"
    )
    assert '-    "/v1/charges/legacy": {' in result.stdout


def test_json_format_and_global_json(httpx_mock: object) -> None:
    """--format json and the global --json give the same document, with both sides' URLs."""
    httpx_mock.add_response(url=f"{_SCHEMA}/2.0.0", content=_V200, is_reusable=True)
    httpx_mock.add_response(url=f"{_SCHEMA}/2.1.0", content=_V210, is_reusable=True)
    flag = runner.invoke(app, [*_ARGS, "--format", "json"])
    glob = runner.invoke(app, ["--json", *_ARGS])
    assert flag.exit_code == glob.exit_code == EXIT_SUCCESS
    assert flag.stdout == glob.stdout
    payload = json.loads(flag.stdout)
    assert payload["base"] == {
        "label": "acme-corp/payments-api/2.0.0",
        "url": "/v1/schema/acme-corp/payments-api/2.0.0",
    }
    assert payload["counts"]["class"] == {"added": 1, "removed": 1, "changed": 2}


def test_sarif_to_output_file_validates(httpx_mock: object, tmp_path: Path) -> None:
    """--format sarif --output writes a schema-valid SARIF file and a one-line note on stderr."""
    _serve(httpx_mock)
    out = tmp_path / "diff.sarif"
    result = runner.invoke(app, [*_ARGS, "--format", "sarif", "--scope", "schemas", "-o", str(out)])
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert result.stdout == ""
    assert f"Wrote sarif diff (8 changes) to {out}" in result.stderr
    log = json.loads(out.read_text())
    jsonschema.Draft4Validator(_SARIF_SCHEMA).validate(log)
    assert log["runs"][0]["tool"]["driver"]["name"] == "apiome schema diff"
    assert {r["ruleId"].split("-")[0] for r in log["runs"][0]["results"]} == {"class", "property"}


def test_yaml_served_spec_is_parsed(httpx_mock: object) -> None:
    """A spec served as YAML (e.g. a frozen snapshot) is parsed too."""
    yaml_head = b"openapi: 3.1.0\ninfo:\n  title: Payments\n  version: 2.1.0\npaths: {}\n"
    _serve(httpx_mock, head=yaml_head)
    result = runner.invoke(app, [*_ARGS, "--scope", "paths", "--format", "json"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert json.loads(result.stdout)["counts"]["path"]["removed"] == 5


def test_non_document_response_exits_1(httpx_mock: object) -> None:
    """A body that is not an OpenAPI mapping is a server fault: exit 1."""
    _serve(httpx_mock, head=b"[1, 2]")
    result = runner.invoke(app, _ARGS)
    assert result.exit_code == EXIT_ERROR
    assert "did not return an OpenAPI document" in result.stderr


@pytest.mark.parametrize(
    "args",
    [
        ["schema", "diff", "acme-corp", "2.0.0", "2.1.0"],
        [*_ARGS, "--format", "yaml"],
        [*_ARGS, "--scope", "operations"],
        [*_ARGS, "--ignore", "whitespace"],
        [*_ARGS, "--output", " "],
    ],
)
def test_usage_errors_exit_2_without_a_request(httpx_mock: object, args: list[str]) -> None:
    """Bad refs, formats, scopes, ignore rules and outputs exit 2 before any HTTP call."""
    result = runner.invoke(app, args)
    assert result.exit_code == EXIT_USAGE
    assert httpx_mock.get_requests() == []
