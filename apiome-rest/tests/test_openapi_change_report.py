"""Semantic OpenAPI change report engine and REST route (#2699)."""

import copy

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app
from app.openapi_change_report import (
    build_change_report,
    change_report_change_counts,
    change_report_is_noop,
    change_report_total_changes,
)

client = TestClient(app)

_MOCK_AUTH = {
    "tenant_id": "test-tenant-id",
    "user_id": "test-user-id",
    "auth_method": "jwt",
}


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_AUTH
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def _min_openapi(**kwargs):
    doc = {
        "openapi": "3.1.0",
        "info": {"title": "API", "version": "1.0.0", "description": "d0"},
        "paths": {},
        "components": {"schemas": {}},
    }
    doc.update(kwargs)
    return doc


def test_new_schema_added():
    base = _min_openapi()
    cand = copy.deepcopy(base)
    cand["components"]["schemas"]["Pet"] = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
    }
    r = build_change_report(base, cand)
    assert r["schemaVersion"] == "1.0"
    assert r["schemas"]["added"] == [{"name": "Pet"}]
    assert r["schemas"]["removed"] == []
    assert r["schemas"]["modified"] == []


def test_removed_property():
    base = _min_openapi()
    base["components"]["schemas"]["Pet"] = {
        "type": "object",
        "properties": {"name": {"type": "string"}, "tag": {"type": "string"}},
    }
    cand = copy.deepcopy(base)
    del cand["components"]["schemas"]["Pet"]["properties"]["tag"]
    r = build_change_report(base, cand)
    assert {"name": "Pet"} in r["schemas"]["modified"]
    prop = next(p for p in r["properties"] if p["path"].endswith("/tag"))
    assert prop["changeKind"] == "removed"
    assert prop["schemaName"] == "Pet"


def test_type_change():
    base = _min_openapi()
    base["components"]["schemas"]["N"] = {"type": "string"}
    cand = copy.deepcopy(base)
    cand["components"]["schemas"]["N"] = {"type": "integer"}
    r = build_change_report(base, cand)
    p = next(x for x in r["properties"] if x["path"] == "/type")
    assert p["changeKind"] == "type_changed"
    assert p["schemaName"] == "N"


def test_required_change():
    base = _min_openapi()
    base["components"]["schemas"]["Box"] = {
        "type": "object",
        "properties": {"a": {"type": "string"}, "b": {"type": "string"}},
        "required": ["a"],
    }
    cand = copy.deepcopy(base)
    cand["components"]["schemas"]["Box"]["required"] = ["a", "b"]
    r = build_change_report(base, cand)
    req = next(x for x in r["properties"] if x["changeKind"] == "required_changed")
    assert req["schemaName"] == "Box"


def test_ref_retarget():
    base = _min_openapi()
    base["components"]["schemas"]["R"] = {"$ref": "#/components/schemas/A"}
    cand = copy.deepcopy(base)
    cand["components"]["schemas"]["R"] = {"$ref": "#/components/schemas/B"}
    r = build_change_report(base, cand)
    ref = next(x for x in r["references"] if x["changeKind"] == "retargeted")
    assert ref["baselineRef"] == "#/components/schemas/A"
    assert ref["candidateRef"] == "#/components/schemas/B"
    assert ref["schemaName"] == "R"


def test_info_description_change():
    base = _min_openapi()
    cand = copy.deepcopy(base)
    cand["info"]["description"] = "d1"
    r = build_change_report(base, cand)
    doc = next(d for d in r["documentation"] if d["scope"] == "info" and d["field"] == "description")
    assert doc["changeKind"] == "modified"
    assert doc["baselinePreview"] == "d0"
    assert doc["candidatePreview"] == "d1"


def test_external_ref_warning():
    base = _min_openapi()
    base["components"]["schemas"]["X"] = {"$ref": "http://example.com/other.json#/Foo"}
    cand = copy.deepcopy(base)
    r = build_change_report(base, cand)
    assert any(w["code"] == "external_ref_not_followed" for w in r["warnings"])


def test_callbacks_skipped_not_silent():
    base = _min_openapi()
    cand = copy.deepcopy(base)
    cand["callbacks"] = {"cb": {}}
    r = build_change_report(base, cand)
    assert any(s.get("reason") == "callbacks_not_diffed_mvp" for s in r["skipped"])


def test_deterministic_output():
    base = _min_openapi()
    base["components"]["schemas"]["S"] = {"type": "object", "properties": {"z": {"type": "number"}}}
    cand = copy.deepcopy(base)
    cand["components"]["schemas"]["S"]["properties"]["a"] = {"type": "string"}
    r1 = build_change_report(base, cand)
    r2 = build_change_report(base, cand)
    assert r1 == r2


def test_change_report_is_noop_for_identical_documents():
    base = _min_openapi()
    base["components"]["schemas"]["S"] = {"type": "object"}
    cand = copy.deepcopy(base)
    report = build_change_report(base, cand)
    assert change_report_is_noop(report) is True
    assert change_report_total_changes(report) == 0
    assert change_report_change_counts(report) == {
        "schemasAdded": 0,
        "schemasRemoved": 0,
        "schemasModified": 0,
        "properties": 0,
        "references": 0,
        "relationships": 0,
        "documentation": 0,
    }


def test_change_report_warning_only_is_still_noop():
    # An external $ref emits a warning but no substantive delta: still a no-op.
    base = _min_openapi()
    base["components"]["schemas"]["X"] = {"$ref": "http://example.com/other.json#/Foo"}
    cand = copy.deepcopy(base)
    report = build_change_report(base, cand)
    assert report["warnings"]
    assert change_report_is_noop(report) is True


def test_change_report_counts_added_schema():
    base = _min_openapi()
    cand = copy.deepcopy(base)
    cand["components"]["schemas"]["New"] = {"type": "boolean"}
    report = build_change_report(base, cand)
    assert change_report_is_noop(report) is False
    counts = change_report_change_counts(report)
    assert counts["schemasAdded"] == 1
    assert change_report_total_changes(report) == 1


def test_post_change_report_route():
    base = _min_openapi()
    cand = copy.deepcopy(base)
    cand["components"]["schemas"]["New"] = {"type": "boolean"}
    res = client.post(
        "/v1/openapi/change-report",
        json={"baselineOpenApi": base, "candidateOpenApi": cand},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["schemaVersion"] == "1.0"
    assert data["schemas"]["added"] == [{"name": "New"}]
