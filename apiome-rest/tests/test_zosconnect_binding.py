"""z/OS Connect copybook ↔ REST binding — MFI-21.2 (#3992).

Acceptance: a z/OS Connect OpenAPI and its copybooks import and are linked in the catalog so the
binding is browsable and diffable; fixtures (``fixtures/zosconnect_binding``) cover one binding —
the Inventory API, its requester descriptor, and two copybooks that each hold a request and a
response 01 record.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.api_identity_service import rank_identity_suggestions
from app.auth import validate_authentication
from app.canonical_model import CanonicalApi
from app.diff import diff
from app.import_source import get_import_source, load_builtin_import_sources
from app.main import app
from app.zosconnect_binding import (
    binding_metadata,
    cobol_record_names,
    matches_api_title,
    resolve_binding,
    shared_cobol_structures,
)

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "zosconnect_binding"
_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"

load_builtin_import_sources()


def _import(key: str, name: str, text: str | None = None) -> CanonicalApi:
    source = get_import_source(key)
    body = text if text is not None else (_FIXTURES / name).read_text(encoding="utf-8")
    return source.normalize(source.parse(body, source_label=name))


def _descriptor(text: str | None = None) -> CanonicalApi:
    return _import("zosconnect", "inventory-requester.json", text)


_STRUCTURES = ["GET-STOCK-REQUEST", "GET-STOCK-RESPONSE", "RESERVE-REQUEST", "RESERVE-RESPONSE"]


# ===========================================================================
# Recorded on import
# ===========================================================================


def test_a_descriptor_records_its_binding():
    binding = binding_metadata(_descriptor())["zosConnectBinding"]
    assert binding["kind"] == "requester"
    assert binding["api"] == {
        "title": "Inventory API",
        "specification": "openapi-3.0",
        "basePath": "https://api.example.com/inventory",
    }
    assert binding["structures"] == _STRUCTURES
    get_stock = binding["operations"][0]
    assert get_stock == {
        "operation": "GET /items/{sku}/stock",
        "operationId": "getStockLevel",
        "method": "GET",
        "path": "/items/{sku}/stock",
        "requestStructure": "GET-STOCK-REQUEST",
        "responseStructure": "GET-STOCK-RESPONSE",
        "program": "INVPGM",
    }


def test_a_copybook_records_every_01_record():
    model = _import("cobolcopybook", "GETSTOCK.cpy")
    assert model.extras["cobolcopybook_root"] == "GET-STOCK-REQUEST"  # the model keeps the first only
    assert binding_metadata(model) == {"cobolRecords": ["GET-STOCK-REQUEST", "GET-STOCK-RESPONSE"]}


def test_a_copybook_without_its_source_falls_back_to_its_root():
    model = _import("cobolcopybook", "RESERVE.cpy")
    model.raw = None
    assert cobol_record_names(model) == ["RESERVE-REQUEST"]


def test_other_formats_record_nothing():
    assert binding_metadata(_import("openapi", "inventory-openapi.yaml")) == {}


def test_the_corpus_requester_records_a_binding():
    path = _EXAMPLES / "zos-connect" / "01-api-requester.json"
    binding = binding_metadata(_import("zosconnect", path.name, path.read_text()))["zosConnectBinding"]
    assert "GET-STOCK-REQUEST" in binding["structures"]


# ===========================================================================
# Suggested as links
# ===========================================================================


def _meta(model: CanonicalApi) -> Dict[str, Any]:
    return binding_metadata(model)


def test_shared_structures_either_way():
    descriptor, copybook = _meta(_descriptor()), _meta(_import("cobolcopybook", "RESERVE.cpy"))
    assert shared_cobol_structures(descriptor, copybook) == ["RESERVE-REQUEST", "RESERVE-RESPONSE"]
    assert shared_cobol_structures(copybook, descriptor) == ["RESERVE-REQUEST", "RESERVE-RESPONSE"]
    assert shared_cobol_structures(copybook, copybook) == []
    assert shared_cobol_structures(None, descriptor) == []


def test_the_target_api_title_names_the_openapi():
    descriptor = _meta(_descriptor())
    assert matches_api_title(descriptor, {"name": "inventory-api", "source_format": "openapi-3.0"})
    assert matches_api_title(descriptor, {"name": "x", "identity_name": "Inventory API"})
    assert not matches_api_title(descriptor, {"name": "Inventory API", "source_format": "zosconnect"})
    assert not matches_api_title({}, {"name": "Inventory API"})


def _row(pid: str, name: str, source_format: str, metadata: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return {
        "project_id": pid,
        "name": name,
        "slug": pid,
        "publishable": source_format.startswith("openapi"),
        "source_format": source_format,
        "protocol": "rest" if source_format != "cobolcopybook" else "data_schema",
        "format_metadata": metadata or {},
    }


def test_suggestions_pair_a_descriptor_with_its_copybooks_and_its_openapi():
    anchor = {**_row("desc", "InventoryRequester", "zosconnect", _meta(_descriptor())), "identity_name": "x"}
    candidates = [
        _row("get", "GETSTOCK", "cobolcopybook", _meta(_import("cobolcopybook", "GETSTOCK.cpy"))),
        _row("api", "Inventory API", "openapi-3.0"),
        _row("other", "Customer record", "cobolcopybook", {"cobolRecords": ["CUSTOMER-RECORD"]}),
    ]
    ops = {"GET /items/{sku}/stock", "POST /items/{sku}/reservations"}
    suggestions = rank_identity_suggestions(
        anchor=anchor, anchor_ops=ops, candidates=candidates, candidate_ops={"api": ops}
    )
    by_id = {s.project_id: s.reason for s in suggestions}
    assert set(by_id) == {"get", "api"}
    assert "binds COBOL structure(s) GET-STOCK-REQUEST, GET-STOCK-RESPONSE" in by_id["get"]
    assert "z/OS Connect target API" in by_id["api"] and "2 shared operation(s)" in by_id["api"]


def test_a_copybook_is_suggested_its_descriptor():
    anchor = {**_row("res", "RESERVE", "cobolcopybook", _meta(_import("cobolcopybook", "RESERVE.cpy")))}
    suggestions = rank_identity_suggestions(
        anchor=anchor,
        anchor_ops=set(),
        candidates=[_row("desc", "InventoryRequester", "zosconnect", _meta(_descriptor()))],
        candidate_ops={},
    )
    (suggestion,) = suggestions
    assert suggestion.project_id == "desc" and "RESERVE-REQUEST" in suggestion.reason


# ===========================================================================
# Browsed
# ===========================================================================


def _peers() -> List[Dict[str, Any]]:
    return [
        {**_row("get", "GETSTOCK", "cobolcopybook", _meta(_import("cobolcopybook", "GETSTOCK.cpy"))), "linked": True},
        {**_row("dup", "get-stock-copy", "cobolcopybook", {"cobolRecords": ["GET-STOCK-REQUEST"]}), "linked": False},
        {**_row("api", "Inventory API", "openapi-3.0"), "linked": False, "operations": {"GET /items/{sku}/stock"}},
        {**_row("self", "Other requester", "zosconnect", _meta(_descriptor())), "linked": True},
    ]


def test_the_binding_resolves_to_copybooks_and_openapi():
    view = resolve_binding(_meta(_descriptor())["zosConnectBinding"], _peers())
    get_stock, reserve = view["operations"]
    assert get_stock["operation"] == "GET /items/{sku}/stock" and get_stock["program"] == "INVPGM"
    assert [c["project_id"] for c in get_stock["request"]["copybooks"]] == ["get", "dup"]  # linked first
    assert [c["project_id"] for c in get_stock["response"]["copybooks"]] == ["get"]
    assert [o["project_id"] for o in get_stock["openapi"]] == ["api"]
    assert reserve["request"] == {"structure": "RESERVE-REQUEST", "copybooks": []}
    assert reserve["openapi"] == []
    assert view["summary"] == {
        "operations": 2,
        "structures": 4,
        "structures_with_copybook": 2,
        "structures_linked": 2,
        "operations_with_openapi": 1,
    }


def test_a_rebound_structure_shows_in_the_version_diff():
    before = _descriptor()
    text = (_FIXTURES / "inventory-requester.json").read_text().replace(
        '"responseStructure": "RESERVE-RESPONSE"', '"responseStructure": "RESERVE-RESULT"'
    )
    after = _descriptor(text)
    changes = {(c.category.value, c.kind.value, c.key) for c in diff(before, after).changes}
    assert ("operation", "modified", "POST /items/{sku}/reservations") in changes
    assert ("type", "added", "InventoryRequester.RESERVE-RESULT") in changes


client = TestClient(app)


@pytest.fixture
def authed():
    app.dependency_overrides[validate_authentication] = lambda: {"tenant_id": "t", "user_id": "u", "auth_method": "jwt"}
    yield
    app.dependency_overrides.pop(validate_authentication, None)


_URL = "/v1/identity/t/projects/desc/zosconnect-binding"


def test_the_route_serves_the_binding(authed):
    peers = _peers()
    with patch("app.identity_routes.db") as db:
        anchor = _row("desc", "InventoryRequester", "zosconnect", _meta(_descriptor()))
        db.get_project_identity_profile.return_value = anchor
        db.get_related_artifact_rows.return_value = [
            {"project_id": "get", "name": "GETSTOCK", "source_format": "cobolcopybook"}
        ]
        db.get_cobol_record_holders.return_value = [peers[0], peers[1]]
        db.get_identity_suggestion_candidates.return_value = [_row("api", "Inventory API", "openapi-3.0")]
        db.get_operation_keys_for_project.return_value = ["GET /items/{sku}/stock"]
        response = client.get(_URL)
    assert response.status_code == 200
    body = response.json()
    db.get_cobol_record_holders.assert_called_once_with("t", _STRUCTURES)
    first = body["operations"][0]
    assert first["operationId"] == "getStockLevel"
    assert first["request"]["copybooks"][0] == {
        "projectId": "get",
        "name": "GETSTOCK",
        "sourceFormat": "cobolcopybook",
        "publishable": False,
        "linked": True,
    }
    assert first["openapi"][0]["projectId"] == "api" and first["openapi"][0]["linked"] is False
    assert body["summary"]["structuresLinked"] == 2 and body["summary"]["operationsWithOpenApi"] == 1


def test_the_route_is_404_for_an_item_without_a_binding(authed):
    with patch("app.identity_routes.db") as db:
        db.get_project_identity_profile.return_value = _row("api", "Inventory API", "openapi-3.0")
        assert client.get(_URL).status_code == 404
        db.get_project_identity_profile.return_value = None
        assert client.get(_URL).status_code == 404


def test_the_record_holder_query_matches_any_structure():
    from app.database import Database

    database = Database.__new__(Database)
    with patch.object(Database, "execute_query", return_value=[{"project_id": "get"}]) as query:
        assert database.get_cobol_record_holders("t", ["GET-STOCK-REQUEST"]) == [{"project_id": "get"}]
    sql, params = query.call_args.args
    assert "format_metadata -> 'cobolRecords' ?| %s::text[]" in sql
    assert params == ("t", ["GET-STOCK-REQUEST"], 200)
    assert database.get_cobol_record_holders("t", []) == []
