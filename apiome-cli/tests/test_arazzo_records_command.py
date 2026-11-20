"""Tests for ``apiome arazzo list|show|validate`` — stored Arazzo workflow records (COA-1.5, #7041)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apiome_cli.arazzo_records import (
    describe_problem,
    document_summary,
    record_problems,
    step_counts,
    workflow_rows,
)
from apiome_cli.exit_codes import EXIT_ARAZZO_INVALID, EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app

pytestmark = pytest.mark.usefixtures("api_key_env")

runner = CliRunner()

_FIXTURES = Path(__file__).parent / "fixtures"
_BASE = "http://localhost:8000"
_PROJECT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_VERSION_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
_ITEM_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
_REVISION_ID = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
_OPERATION_ID = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"

_PROJECT = {"id": _PROJECT_ID, "name": "Checkout", "slug": "checkout-flow"}
_VERSION = {"id": _VERSION_ID, "project_id": _PROJECT_ID, "version": "1.0.0", "slug": "1.0.0"}

_RESOLVED_STEP = {
    "step_id": "createCart",
    "order_index": 0,
    "target_kind": "operation",
    "operation_ref": None,
    "operation_id": "createCart",
    "resolution_status": "resolved",
    "resolution_reason": None,
    "operation": {
        "path_operation_id": _OPERATION_ID,
        "method": "POST",
        "path": "/carts",
        "path_id": "p-1",
        "version_id": _VERSION_ID,
        "project_id": _PROJECT_ID,
    },
}
_UNRESOLVED_STEP = {
    "step_id": "submitPayment",
    "order_index": 1,
    "target_kind": "operation",
    "operation_ref": "$sourceDescriptions.payments.url#/paths/~1charges/post",
    "operation_id": None,
    "resolution_status": "unresolved",
    "resolution_reason": "unknown-operation",
    "operation": None,
}
_CALL_STEP = {
    "step_id": "notify",
    "order_index": 2,
    "target_kind": "workflow",
    "target_workflow_id": "send-receipt",
    "resolution_status": "not_applicable",
    "operation": None,
}


def _payload(*steps: dict, source_status: str = "resolved", version_id: str = _VERSION_ID) -> dict:
    """A REST ``ArazzoWorkflowsResponse`` body with one ``checkout`` workflow."""
    source = {"name": "payments", "url": "./payments.yaml", "type": "openapi", "status": source_status}
    if source_status == "missing":
        source["reason"] = "resolution-disabled"
    return {
        "version_id": version_id,
        "project_id": _PROJECT_ID,
        "sources": [source],
        "workflows": [
            {
                "workflow_id": "checkout",
                "summary": "Checkout cart and pay",
                "sources": [source],
                "steps": list(steps),
            }
        ],
    }


@pytest.fixture
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tier-2 commands require an API key."""
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_BASE_URL", _BASE)
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def _mock_scope(httpx_mock: object) -> None:
    httpx_mock.add_response(url=f"{_BASE}/v1/projects/acme-corp/by-slug/checkout-flow", json=_PROJECT)
    httpx_mock.add_response(
        url=f"{_BASE}/v1/versions/acme-corp/{_PROJECT_ID}/by-version/1.0.0", json=_VERSION
    )


_SCOPE = ["--project", "checkout-flow", "--version", "1.0.0"]


# ------------------------------------------------------------------------------------------
# Pure helpers
# ------------------------------------------------------------------------------------------


def test_step_counts_prefer_the_server_block_and_fall_back_to_counting():
    assert step_counts({"step_resolution": {"resolved": 2}, "steps": []}) == {"resolved": 2}
    assert step_counts({"steps": [_RESOLVED_STEP, _UNRESOLVED_STEP, _RESOLVED_STEP]}) == {
        "resolved": 2,
        "unresolved": 1,
    }


def test_workflow_rows_count_unresolved_and_parse_errors_together():
    parse_error = dict(_UNRESOLVED_STEP, step_id="bad", resolution_status="parse_error")
    rows = workflow_rows(_payload(_RESOLVED_STEP, _UNRESOLVED_STEP, parse_error, _CALL_STEP))
    assert rows == [
        {
            "workflow_id": "checkout",
            "summary": "Checkout cart and pay",
            "steps": 4,
            "resolved": 1,
            "unresolved": 2,
        }
    ]


def test_record_problems_list_missing_sources_then_unresolved_steps():
    problems = record_problems(
        _payload(_RESOLVED_STEP, _UNRESOLVED_STEP, _CALL_STEP, source_status="missing")
    )
    assert [p["kind"] for p in problems] == ["source", "step"]
    assert describe_problem(problems[0]) == "source payments: missing (resolution-disabled)"
    assert describe_problem(problems[1]) == (
        "checkout/submitPayment: unresolved target "
        "$sourceDescriptions.payments.url#/paths/~1charges/post (unknown-operation)"
    )


def test_unknown_sources_and_workflow_calls_are_not_problems():
    assert record_problems(_payload(_RESOLVED_STEP, _CALL_STEP, source_status="unknown")) == []


def test_document_summary_counts_workflows_steps_and_sources():
    doc = {
        "arazzo": "1.0.1",
        "sourceDescriptions": [{"name": "a"}],
        "workflows": [{"steps": [{}, {}]}, {"steps": [{}]}, "junk"],
    }
    assert document_summary(doc) == {"arazzo": "1.0.1", "workflows": 3, "steps": 3, "sources": 1}


# ------------------------------------------------------------------------------------------
# apiome arazzo list
# ------------------------------------------------------------------------------------------


def test_list_reads_the_version_route_and_renders_counts(httpx_mock: object) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(
        url=f"{_BASE}/v1/workflows/acme-corp/versions/{_VERSION_ID}",
        json=_payload(_RESOLVED_STEP, _UNRESOLVED_STEP),
    )

    result = runner.invoke(app, ["arazzo", "list", *_SCOPE])

    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "checkout" in result.stdout
    assert "Checkout cart and pay" in result.stdout


def test_list_json_prints_the_rest_payload(httpx_mock: object) -> None:
    _mock_scope(httpx_mock)
    payload = _payload(_RESOLVED_STEP)
    httpx_mock.add_response(url=f"{_BASE}/v1/workflows/acme-corp/versions/{_VERSION_ID}", json=payload)

    result = runner.invoke(app, ["--json", "arazzo", "list", *_SCOPE])

    assert result.exit_code == EXIT_SUCCESS
    assert json.loads(result.stdout) == payload


def test_list_with_no_workflows_says_so(httpx_mock: object) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(
        url=f"{_BASE}/v1/workflows/acme-corp/versions/{_VERSION_ID}",
        json={"version_id": _VERSION_ID, "project_id": _PROJECT_ID, "sources": [], "workflows": []},
    )

    result = runner.invoke(app, ["arazzo", "list", *_SCOPE])

    assert result.exit_code == EXIT_SUCCESS
    assert "No Arazzo workflows." in result.stdout


def test_list_catalog_reads_the_latest_revision(httpx_mock: object) -> None:
    httpx_mock.add_response(
        url=f"{_BASE}/v1/workflows/acme-corp/catalog/{_ITEM_ID}", json=_payload(_RESOLVED_STEP)
    )

    result = runner.invoke(app, ["arazzo", "list", "--catalog", _ITEM_ID])

    assert result.exit_code == EXIT_SUCCESS
    assert "checkout" in result.stdout


def test_list_catalog_revision_reads_the_named_revision(httpx_mock: object) -> None:
    httpx_mock.add_response(
        url=f"{_BASE}/v1/workflows/acme-corp/catalog/{_ITEM_ID}/revisions/{_REVISION_ID}",
        json=_payload(_RESOLVED_STEP, version_id=_REVISION_ID),
    )

    result = runner.invoke(
        app, ["--json", "arazzo", "list", "--catalog", _ITEM_ID, "--revision", _REVISION_ID]
    )

    assert result.exit_code == EXIT_SUCCESS
    assert json.loads(result.stdout)["version_id"] == _REVISION_ID


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--project", "checkout-flow"],
        ["--catalog", _ITEM_ID, "--project", "checkout-flow"],
        ["--revision", _REVISION_ID, *_SCOPE],
    ],
)
def test_list_rejects_a_missing_or_mixed_scope(args: list[str]) -> None:
    result = runner.invoke(app, ["arazzo", "list", *args])

    assert result.exit_code == EXIT_USAGE


def test_list_maps_an_unknown_catalog_item_to_usage(httpx_mock: object) -> None:
    httpx_mock.add_response(
        url=f"{_BASE}/v1/workflows/acme-corp/catalog/{_ITEM_ID}",
        status_code=404,
        json={"detail": f"Catalog item not found: {_ITEM_ID}"},
    )

    result = runner.invoke(app, ["arazzo", "list", "--catalog", _ITEM_ID])

    assert result.exit_code == EXIT_USAGE


# ------------------------------------------------------------------------------------------
# apiome arazzo show
# ------------------------------------------------------------------------------------------


def test_show_reads_the_workflow_route_and_lists_steps(httpx_mock: object) -> None:
    _mock_scope(httpx_mock)
    payload = _payload(_RESOLVED_STEP, _UNRESOLVED_STEP, _CALL_STEP)
    httpx_mock.add_response(
        url=f"{_BASE}/v1/workflows/acme-corp/versions/{_VERSION_ID}/workflows/checkout",
        json={
            "version_id": _VERSION_ID,
            "project_id": _PROJECT_ID,
            "sources": payload["sources"],
            "workflow": payload["workflows"][0],
        },
    )

    result = runner.invoke(app, ["arazzo", "show", "checkout", *_SCOPE])

    assert result.exit_code == EXIT_SUCCESS, result.output
    for text in ("createCart", "POST /carts", "unresolved", "workflow send-receipt", "payments"):
        assert text in result.stdout


def test_show_404_is_a_usage_error(httpx_mock: object) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(
        url=f"{_BASE}/v1/workflows/acme-corp/versions/{_VERSION_ID}/workflows/nope",
        status_code=404,
        json={"detail": "Workflow not found: nope"},
    )

    result = runner.invoke(app, ["arazzo", "show", "nope", *_SCOPE])

    assert result.exit_code == EXIT_USAGE


def test_show_catalog_picks_the_workflow_from_the_list(httpx_mock: object) -> None:
    payload = _payload(_RESOLVED_STEP)
    httpx_mock.add_response(url=f"{_BASE}/v1/workflows/acme-corp/catalog/{_ITEM_ID}", json=payload)

    result = runner.invoke(app, ["--json", "arazzo", "show", "checkout", "--catalog", _ITEM_ID])

    assert result.exit_code == EXIT_SUCCESS
    body = json.loads(result.stdout)
    assert body["workflow"]["workflow_id"] == "checkout"
    assert body["version_id"] == _VERSION_ID and body["sources"] == payload["sources"]


def test_show_catalog_unknown_workflow_is_a_usage_error(httpx_mock: object) -> None:
    httpx_mock.add_response(
        url=f"{_BASE}/v1/workflows/acme-corp/catalog/{_ITEM_ID}", json=_payload(_RESOLVED_STEP)
    )

    result = runner.invoke(app, ["arazzo", "show", "Checkout", "--catalog", _ITEM_ID])

    assert result.exit_code == EXIT_USAGE
    assert "Workflow not found: Checkout" in result.output


# ------------------------------------------------------------------------------------------
# apiome arazzo validate
# ------------------------------------------------------------------------------------------


def test_validate_file_accepts_a_valid_document() -> None:
    result = runner.invoke(app, ["arazzo", "validate", str(_FIXTURES / "checkout.arazzo.yaml")])

    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "Valid Arazzo 1.0.0 document: 1 workflow(s), 2 step(s)" in result.stdout


def test_validate_file_json_reports_the_summary() -> None:
    result = runner.invoke(
        app, ["--json", "arazzo", "validate", str(_FIXTURES / "order-to-cash-1.1.arazzo.yaml")]
    )

    assert result.exit_code == EXIT_SUCCESS, result.output
    body = json.loads(result.stdout)
    assert body["valid"] is True and body["arazzo"].startswith("1.1")


def test_validate_file_rejects_a_structurally_invalid_document(tmp_path: Path) -> None:
    bad = tmp_path / "bad.arazzo.yaml"
    bad.write_text("arazzo: 1.0.0\ninfo: {title: t, version: '1'}\nworkflows: []\n", encoding="utf-8")

    result = runner.invoke(app, ["--json", "arazzo", "validate", str(bad)])

    assert result.exit_code == EXIT_ARAZZO_INVALID
    body = json.loads(result.stdout)
    assert body["valid"] is False and body["error"]


def test_validate_file_that_cannot_be_read_is_a_usage_error(tmp_path: Path) -> None:
    result = runner.invoke(app, ["arazzo", "validate", str(tmp_path / "missing.arazzo.yaml")])

    assert result.exit_code == EXIT_USAGE


def test_validate_rejects_a_file_and_a_revision_together() -> None:
    result = runner.invoke(
        app, ["arazzo", "validate", str(_FIXTURES / "checkout.arazzo.yaml"), *_SCOPE]
    )

    assert result.exit_code == EXIT_USAGE


def test_validate_records_passes_when_everything_resolved(httpx_mock: object) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(
        url=f"{_BASE}/v1/workflows/acme-corp/versions/{_VERSION_ID}",
        json=_payload(_RESOLVED_STEP, _CALL_STEP),
    )

    result = runner.invoke(app, ["arazzo", "validate", *_SCOPE])

    assert result.exit_code == EXIT_SUCCESS
    assert "every step resolved" in result.stdout


def test_validate_records_fails_on_unresolved_steps_and_missing_sources(httpx_mock: object) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(
        url=f"{_BASE}/v1/workflows/acme-corp/versions/{_VERSION_ID}",
        json=_payload(_RESOLVED_STEP, _UNRESOLVED_STEP, source_status="missing"),
    )

    result = runner.invoke(app, ["--json", "arazzo", "validate", *_SCOPE])

    assert result.exit_code == EXIT_ARAZZO_INVALID
    body = json.loads(result.stdout)
    assert body["valid"] is False
    assert [(p["kind"], p.get("step_id")) for p in body["problems"]] == [
        ("source", None),
        ("step", "submitPayment"),
    ]


def test_validate_records_human_output_lists_each_problem(httpx_mock: object) -> None:
    httpx_mock.add_response(
        url=f"{_BASE}/v1/workflows/acme-corp/catalog/{_ITEM_ID}",
        json=_payload(_UNRESOLVED_STEP),
    )

    result = runner.invoke(app, ["arazzo", "validate", "--catalog", _ITEM_ID])

    assert result.exit_code == EXIT_ARAZZO_INVALID
    assert "checkout/submitPayment: unresolved" in result.output
    assert "1 problem(s) in 1 workflow(s)." in result.output


def test_validate_records_with_no_workflows_passes(httpx_mock: object) -> None:
    httpx_mock.add_response(
        url=f"{_BASE}/v1/workflows/acme-corp/catalog/{_ITEM_ID}",
        json={"version_id": None, "project_id": _ITEM_ID, "sources": [], "workflows": []},
    )

    result = runner.invoke(app, ["arazzo", "validate", "--catalog", _ITEM_ID])

    assert result.exit_code == EXIT_SUCCESS
    assert "stores no Arazzo workflows" in result.stdout
