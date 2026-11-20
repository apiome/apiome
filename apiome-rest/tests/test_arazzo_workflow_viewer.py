"""Tests for the Arazzo workflow viewer's read API — COA-1.3 (#7039).

Two layers:

* :mod:`app.arazzo_workflow_view` (pure) — built from rows the real importer maps, so the payload
  is checked against what an Arazzo import actually persists: steps in order, the operation a
  step resolved to, its ``onSuccess`` / ``onFailure`` actions, called workflows, and each
  workflow's source-description status from the COA-1.2 report.
* :mod:`app.arazzo_workflow_routes` — the three GETs, with the database patched: tenant scoping,
  404/400 handling, and the catalog item → latest revision hop.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.arazzo_import_source import ArazzoImportSource
from app.arazzo_workflow_persistence import (
    OperationIndex,
    WorkflowRow,
    WorkflowStepRow,
    build_workflow_rows,
    resolve_workflow_steps,
)
from app.arazzo_workflow_view import (
    SOURCE_MISSING,
    SOURCE_RESOLVED,
    SOURCE_UNKNOWN,
    build_source_views,
    build_workflow_views,
    step_source_names,
)
from app.auth import validate_authentication
from app.main import app

_FIXTURES = Path(__file__).parent / "fixtures" / "arazzo"

_TENANT = "11111111-1111-1111-1111-111111111111"
_VERSION = "33333333-3333-3333-3333-333333333333"
_PROJECT = "22222222-2222-2222-2222-222222222222"
_OP_LOGIN = "55555555-5555-5555-5555-555555555555"
_OP_PET = "66666666-6666-6666-6666-666666666666"

_AUTH = {"tenant_id": _TENANT, "user_id": "u-1", "auth_method": "jwt"}

#: A two-source workflow with explicit success/failure routing (`goto` / `end` / `retry`),
#: which the official example bundles do not exercise.
_ROUTED_DOCUMENT = """
arazzo: 1.1.0
info: {title: Routed checkout, version: 1.0.0}
sourceDescriptions:
  - {name: shop, url: ./shop.openapi.yaml, type: openapi}
  - {name: payments, url: https://payments.example.com/openapi.yaml, type: openapi}
workflows:
  - workflowId: checkout
    summary: Pay for a cart
    inputs:
      type: object
      properties: {cartId: {type: string}}
    outputs: {receipt: $steps.pay.outputs.receipt}
    steps:
      - stepId: load-cart
        operationId: $sourceDescriptions.shop.getCart
        successCriteria: [{condition: $statusCode == 200}]
        onSuccess: [{name: to-pay, type: goto, stepId: pay}]
        onFailure: [{name: give-up, type: end}]
        outputs: {total: $response.body#/total}
      - stepId: pay
        operationRef: $sourceDescriptions.payments.url#/paths/~1charges/post
        onFailure: [{name: again, type: retry, retryAfter: 1, retryLimit: 3}]
        outputs: {receipt: $response.body#/id}
      - stepId: notify
        workflowId: send-receipt
  - workflowId: send-receipt
    steps:
      - stepId: email
        operationId: $sourceDescriptions.shop.sendEmail
"""


def _rows_from_text(text: str, label: str, index_rows: List[Dict[str, Any]]) -> List[WorkflowRow]:
    """Map an Arazzo document onto workflow rows the way an import persists them."""
    adapter = ArazzoImportSource()
    model = adapter.normalize(adapter.parse(text, source_label=label))
    result = build_workflow_rows(model)
    resolve_workflow_steps(result, OperationIndex(index_rows))
    return result.workflows


def _index_row(row_id: str, pathname: str, method: str, operation_id: str) -> Dict[str, Any]:
    """One path-operation index record, shaped like ``get_scan_path_operation_index`` returns."""
    return {
        "id": row_id,
        "operation": method,
        "pathname": pathname,
        "operation_id": operation_id,
        "project_id": _PROJECT,
        "version_id": _VERSION,
        "source_path": None,
    }


def _summary(row_id: str, method: str, path: str, operation_id: str) -> Dict[str, Any]:
    """An operation summary as ``get_arazzo_step_operations`` returns it."""
    return {
        "path_operation_id": row_id,
        "method": method,
        "path": path,
        "path_id": f"path-{row_id[:4]}",
        "summary": f"{method} {path}",
        "description": None,
        "operation_id": operation_id,
        "version_id": _VERSION,
        "version_label": "1.0.0",
        "project_id": _PROJECT,
        "project_name": "Petstore",
        "project_publishable": True,
    }


# --------------------------------------------------------------------------------------------
# Source descriptions
# --------------------------------------------------------------------------------------------


def test_sources_take_their_status_from_the_resolution_report():
    declared = [
        {"name": "shop", "url": "./shop.openapi.yaml", "type": "openapi"},
        {"name": "payments", "url": "https://payments.example.com/openapi.yaml"},
    ]
    report = {
        "resolved": 1,
        "unresolved": 1,
        "sources": [{"name": "shop", "url": "./shop.openapi.yaml", "tier": "fileset"}],
        "unresolved_sources": [
            {
                "name": "payments",
                "url": "https://payments.example.com/openapi.yaml",
                "reason": "resolution-disabled",
                "detail": "Remote resolution is off",
            }
        ],
    }

    views = build_source_views(declared, report)

    assert [(v["name"], v["status"]) for v in views] == [
        ("shop", SOURCE_RESOLVED),
        ("payments", SOURCE_MISSING),
    ]
    assert views[0]["tier"] == "fileset" and views[0]["type"] == "openapi"
    assert views[1]["reason"] == "resolution-disabled"
    assert views[1]["detail"] == "Remote resolution is off"


def test_sources_are_unknown_without_a_report_and_nameless_entries_are_skipped():
    views = build_source_views([{"name": "shop", "url": "x.yaml"}, {"url": "nameless.yaml"}, "junk"], None)

    assert [(v["name"], v["status"]) for v in views] == [("shop", SOURCE_UNKNOWN)]


def test_a_source_counted_but_not_itemized_is_resolved_when_nothing_went_unresolved():
    # The report caps its itemized lists; a fully resolved import still says so.
    views = build_source_views([{"name": "late"}], {"resolved": 60, "unresolved": 0, "sources": []})

    assert views[0]["status"] == SOURCE_RESOLVED


def test_non_list_source_descriptions_yield_nothing():
    assert build_source_views({"name": "shop"}, None) == []


# --------------------------------------------------------------------------------------------
# Workflow views
# --------------------------------------------------------------------------------------------


def test_routed_workflow_carries_steps_actions_and_targets_in_order():
    rows = _rows_from_text(
        _ROUTED_DOCUMENT,
        "checkout.arazzo.yaml",
        [_index_row(_OP_LOGIN, "/carts/{cartId}", "GET", "getCart")],
    )
    sources = build_source_views(
        [{"name": "shop", "url": "./shop.openapi.yaml"}, {"name": "payments", "url": "p"}],
        {"sources": [{"name": "shop", "tier": "fileset"}], "unresolved": 1,
         "unresolved_sources": [{"name": "payments", "reason": "resolution-disabled"}]},
    )

    views = build_workflow_views(
        rows,
        operations={_OP_LOGIN: _summary(_OP_LOGIN, "GET", "/carts/{cartId}", "getCart")},
        sources=sources,
    )

    checkout, send_receipt = views
    assert checkout["workflow_id"] == "checkout"
    assert checkout["summary"] == "Pay for a cart"
    assert checkout["inputs"]["properties"] == {"cartId": {"type": "string"}}
    assert checkout["outputs"] == {"receipt": "$steps.pay.outputs.receipt"}
    assert [s["step_id"] for s in checkout["steps"]] == ["load-cart", "pay", "notify"]

    load_cart, pay, notify = checkout["steps"]
    assert load_cart["target_kind"] == "operation"
    assert load_cart["resolution_status"] == "resolved"
    assert load_cart["operation"]["path"] == "/carts/{cartId}"
    assert load_cart["on_success"] == [{"name": "to-pay", "type": "goto", "stepId": "pay"}]
    assert load_cart["on_failure"] == [{"name": "give-up", "type": "end"}]
    assert load_cart["success_criteria"] == [{"condition": "$statusCode == 200"}]
    assert load_cart["outputs"] == {"total": "$response.body#/total"}
    assert load_cart["source_names"] == ["shop"]

    assert pay["resolution_status"] == "unresolved"
    assert pay["operation"] is None
    assert pay["source_names"] == ["payments"]
    assert pay["on_failure"][0]["type"] == "retry"

    assert notify["target_kind"] == "workflow"
    assert notify["target_workflow_id"] == "send-receipt"
    assert notify["resolution_status"] == "not_applicable"

    # Each workflow lists only the sources its steps use.
    assert [(s["name"], s["status"]) for s in checkout["sources"]] == [
        ("shop", "resolved"),
        ("payments", "missing"),
    ]
    assert [s["name"] for s in send_receipt["sources"]] == ["shop"]


def test_a_resolved_step_whose_operation_was_deleted_has_no_operation():
    rows = _rows_from_text(
        _ROUTED_DOCUMENT,
        "checkout.arazzo.yaml",
        [_index_row(_OP_LOGIN, "/carts/{cartId}", "GET", "getCart")],
    )

    views = build_workflow_views(rows, operations={}, sources=[])

    assert views[0]["steps"][0]["resolution_status"] == "resolved"
    assert views[0]["steps"][0]["operation"] is None


def test_workflow_without_attributable_sources_lists_every_declared_source():
    workflow = WorkflowRow(
        workflow_id="w",
        steps=[WorkflowStepRow(step_id="s", order_index=0, operation_id="plain")],
    )
    sources = build_source_views([{"name": "a"}, {"name": "b"}], None)

    views = build_workflow_views([workflow], sources=sources)

    assert [s["name"] for s in views[0]["sources"]] == ["a", "b"]
    assert views[0]["steps"][0]["source_names"] == []


def test_official_bundle_maps_operation_ids_and_called_workflows():
    rows = _rows_from_text(
        (_FIXTURES / "pet-coupons.arazzo.yaml").read_text(encoding="utf-8"),
        "pet-coupons.arazzo.yaml",
        [_index_row(_OP_PET, "/pet/findByTags", "GET", "findPetsByTags")],
    )

    views = build_workflow_views(
        rows,
        operations={_OP_PET: _summary(_OP_PET, "GET", "/pet/findByTags", "findPetsByTags")},
        sources=build_source_views([{"name": "pet-coupons", "url": "./pet-coupons.openapi.yaml"}], None),
    )

    apply_coupon = next(v for v in views if v["workflow_id"] == "apply-coupon")
    find_pet = apply_coupon["steps"][0]
    assert find_pet["operation"]["method"] == "GET"
    assert find_pet["source_names"] == ["pet-coupons"]
    assert apply_coupon["steps"][-1]["target_kind"] == "workflow"
    assert apply_coupon["steps"][-1]["target_workflow_id"] == "place-order"


def test_step_source_names_reads_the_normalizer_hint():
    step = WorkflowStepRow(
        step_id="s",
        order_index=0,
        operation_ref="{$sourceDescriptions.pets.url}#/paths/~1pet",
        extras={"sourceDescription": "pets"},
    )

    assert step_source_names(step, {"pets", "other"}) == ["pets"]
    # A hint naming no declared source attributes nothing when several are declared …
    assert step_source_names(step, {"other", "more"}) == []
    # … and falls back to the only source when the document declares one.
    assert step_source_names(step, {"other"}) == ["other"]


# --------------------------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------------------------


@pytest.fixture
def client():
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    yield TestClient(app)
    app.dependency_overrides.pop(validate_authentication, None)


def _patched_db(mdb, rows: List[WorkflowRow]) -> None:
    """Wire a patched ``db`` with one revision's workflows and context."""
    mdb.get_version_for_tenant.return_value = {"id": _VERSION, "project_id": _PROJECT}
    mdb.load_arazzo_workflows.return_value = rows
    mdb.get_arazzo_source_context.return_value = {
        "source_descriptions": [{"name": "shop", "url": "./shop.openapi.yaml"}],
        "report": {"resolved": 1, "unresolved": 0, "sources": [{"name": "shop", "tier": "fileset"}]},
    }
    mdb.get_arazzo_step_operations.return_value = {
        _OP_LOGIN: _summary(_OP_LOGIN, "GET", "/carts/{cartId}", "getCart")
    }


def test_version_route_returns_the_viewer_payload(client):
    rows = _rows_from_text(
        _ROUTED_DOCUMENT,
        "checkout.arazzo.yaml",
        [_index_row(_OP_LOGIN, "/carts/{cartId}", "GET", "getCart")],
    )
    with patch("app.arazzo_workflow_routes.db") as mdb:
        _patched_db(mdb, rows)
        response = client.get(f"/v1/workflows/acme/versions/{_VERSION}")

    assert response.status_code == 200
    body = response.json()
    assert body["version_id"] == _VERSION and body["project_id"] == _PROJECT
    assert body["sources"][0]["status"] == "resolved"
    assert [w["workflow_id"] for w in body["workflows"]] == ["checkout", "send-receipt"]
    first = body["workflows"][0]["steps"][0]
    assert first["operation"]["path_operation_id"] == _OP_LOGIN
    assert first["operation"]["project_publishable"] is True
    mdb.load_arazzo_workflows.assert_called_once_with(tenant_id=_TENANT, version_id=_VERSION)
    mdb.get_arazzo_step_operations.assert_called_once_with(
        tenant_id=_TENANT, path_operation_ids=[_OP_LOGIN]
    )


def test_version_route_404s_outside_the_tenant(client):
    with patch("app.arazzo_workflow_routes.db") as mdb:
        mdb.get_version_for_tenant.return_value = None
        response = client.get(f"/v1/workflows/acme/versions/{_VERSION}")

    assert response.status_code == 404
    mdb.load_arazzo_workflows.assert_not_called()


def test_version_route_rejects_a_malformed_id(client):
    with patch("app.arazzo_workflow_routes.db") as mdb:
        response = client.get("/v1/workflows/acme/versions/not-a-uuid")

    assert response.status_code == 400
    mdb.get_version_for_tenant.assert_not_called()


def test_version_without_workflows_is_an_empty_list(client):
    with patch("app.arazzo_workflow_routes.db") as mdb:
        _patched_db(mdb, [])
        response = client.get(f"/v1/workflows/acme/versions/{_VERSION}")

    assert response.status_code == 200
    assert response.json()["workflows"] == []


def test_catalog_route_reads_the_latest_revision(client):
    with patch("app.arazzo_workflow_routes.db") as mdb:
        _patched_db(mdb, [])
        mdb.get_catalog_item_by_id.return_value = {"id": _PROJECT}
        mdb.get_latest_revision_id_for_project.return_value = _VERSION
        response = client.get(f"/v1/workflows/acme/catalog/{_PROJECT}")

    assert response.status_code == 200
    assert response.json()["version_id"] == _VERSION
    mdb.get_latest_revision_id_for_project.assert_called_once_with(_PROJECT, _TENANT)
    mdb.load_arazzo_workflows.assert_called_once_with(tenant_id=_TENANT, version_id=_VERSION)


def test_catalog_route_with_no_revision_is_empty(client):
    with patch("app.arazzo_workflow_routes.db") as mdb:
        mdb.get_catalog_item_by_id.return_value = {"id": _PROJECT}
        mdb.get_latest_revision_id_for_project.return_value = None
        response = client.get(f"/v1/workflows/acme/catalog/{_PROJECT}")

    assert response.status_code == 200
    assert response.json() == {
        "version_id": None,
        "project_id": _PROJECT,
        "sources": [],
        "workflows": [],
    }
    mdb.load_arazzo_workflows.assert_not_called()


def test_catalog_route_404s_for_a_non_catalog_id(client):
    with patch("app.arazzo_workflow_routes.db") as mdb:
        mdb.get_catalog_item_by_id.return_value = None
        response = client.get(f"/v1/workflows/acme/catalog/{_PROJECT}")

    assert response.status_code == 404


def test_operation_route_returns_parameters_and_responses(client):
    detail = {
        **_summary(_OP_LOGIN, "GET", "/carts/{cartId}", "getCart"),
        "parameters": [{"name": "cartId", "in_location": "path", "description": None}],
        "responses": [{"status_code": "200", "description": "The cart"}],
    }
    with patch("app.arazzo_workflow_routes.db") as mdb:
        mdb.get_arazzo_operation_detail.return_value = detail
        response = client.get(f"/v1/workflows/acme/operations/{_OP_LOGIN}")

    assert response.status_code == 200
    body = response.json()
    assert body["method"] == "GET" and body["path"] == "/carts/{cartId}"
    assert body["parameters"][0]["in_location"] == "path"
    assert body["responses"][0]["status_code"] == "200"
    mdb.get_arazzo_operation_detail.assert_called_once_with(
        tenant_id=_TENANT, path_operation_id=_OP_LOGIN
    )


def test_operation_route_404s_for_an_unknown_operation(client):
    with patch("app.arazzo_workflow_routes.db") as mdb:
        mdb.get_arazzo_operation_detail.return_value = None
        response = client.get(f"/v1/workflows/acme/operations/{_OP_LOGIN}")

    assert response.status_code == 404


# --------------------------------------------------------------------------------------------
# Database reads (SQL shape; a live Postgres is not needed)
# --------------------------------------------------------------------------------------------


def test_step_operation_lookup_is_tenant_scoped_and_skips_empty_input():
    from app.database import Database

    database = Database.__new__(Database)
    calls: List[Any] = []

    def _execute(query, params=None):
        calls.append((query, params))
        return [{"path_operation_id": _OP_LOGIN, "method": "GET"}]

    database.execute_query = _execute  # type: ignore[assignment]

    assert database.get_arazzo_step_operations(tenant_id=_TENANT, path_operation_ids=[]) == {}
    assert calls == []

    found = database.get_arazzo_step_operations(
        tenant_id=_TENANT, path_operation_ids=[_OP_LOGIN, _OP_LOGIN, None]
    )
    assert list(found) == [_OP_LOGIN]
    query, params = calls[0]
    assert "p.tenant_id = %s::uuid" in query and "ANY(%s::uuid[])" in query
    assert params == (_TENANT, [_OP_LOGIN])


def test_source_context_decodes_text_json_and_defaults_missing_values():
    from app.database import Database

    database = Database.__new__(Database)
    database.execute_query = lambda q, p=None: [  # type: ignore[assignment]
        {"report": '{"resolved": 1}', "source_descriptions": None}
    ]

    assert database.get_arazzo_source_context(tenant_id=_TENANT, version_id=_VERSION) == {
        "source_descriptions": [],
        "report": {"resolved": 1},
    }

    database.execute_query = lambda q, p=None: []  # type: ignore[assignment]
    assert database.get_arazzo_source_context(tenant_id=_TENANT, version_id=_VERSION) == {
        "source_descriptions": [],
        "report": None,
    }
