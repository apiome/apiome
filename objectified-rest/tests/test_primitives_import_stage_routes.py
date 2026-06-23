"""API tests for the import-pipeline staging endpoint (#3460).

``POST /v1/primitives/{tenant_slug}/import/stage`` is the unified orchestrator:
fetch (paste/file/url/git) → parse → detect candidates → record provenance →
return the staged result. The DB and the network fetchers are mocked, so these
assert the staged response and the provenance row written per source kind/method.
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import import_ingestion
from app.auth import validate_authentication
from app.main import app

client = TestClient(app)

_JWT = {"tenant_id": "t1", "user_id": "u1", "auth_method": "jwt"}
_NOW = datetime(2026, 6, 22, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = lambda: _JWT
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def _import_row(**overrides):
    row = {"id": "imp-1", "tenant_id": "t1", "created_at": _NOW}
    row.update(overrides)
    return row


# ===========================================================================
# Source KIND coverage — each reaches a staged result + import record
# ===========================================================================


def test_stage_json_schema_paste():
    with patch("app.primitives_routes.db") as mdb:
        mdb.create_primitive_import.return_value = _import_row()
        r = client.post(
            "/v1/primitives/std/import/stage",
            json={
                "source_kind": "json-schema",
                "source_method": "paste",
                "content": '{"$defs": {"Money": {"type": "object"}, "Date": {"type": "string"}}}',
                "target_namespace": "std/v0/types",
            },
        )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "staged"
    assert body["import_id"] == "imp-1"
    assert body["detected_count"] == 2
    assert {c["name"] for c in body["candidates"]} == {"Money", "Date"}

    # An import record was recorded with the staged report and zero commit counts.
    _, kwargs = mdb.create_primitive_import.call_args
    assert kwargs["source_kind"] == "json-schema"
    assert kwargs["imported_count"] == 0
    assert kwargs["report"]["status"] == "staged"
    assert kwargs["options"]["source_method"] == "paste"


def test_stage_type_def_bundle_paste():
    with patch("app.primitives_routes.db") as mdb:
        mdb.create_primitive_import.return_value = _import_row(id="imp-2")
        r = client.post(
            "/v1/primitives/std/import/stage",
            json={
                "source_kind": "type-def-bundle",
                "source_method": "paste",
                "content": '{"types": {"Order": {"type": "object"}, "Line": {"type": "object"}}}',
            },
        )
    assert r.status_code == 200
    body = r.json()
    assert body["detected_count"] == 2
    assert body["import_id"] == "imp-2"


def test_stage_openapi_paste():
    with patch("app.primitives_routes.db") as mdb:
        mdb.create_primitive_import.return_value = _import_row(id="imp-3")
        r = client.post(
            "/v1/primitives/std/import/stage",
            json={
                "source_kind": "openapi",
                "source_method": "paste",
                "content": '{"openapi": "3.1.0", "components": {"schemas": {"Pet": {"type": "object"}}}}',
            },
        )
    assert r.status_code == 200
    body = r.json()
    assert body["candidates"][0]["name"] == "Pet"


# ===========================================================================
# Source METHOD coverage — file / url / git all reach a staged result
# ===========================================================================


def test_stage_file_method_records_label():
    with patch("app.primitives_routes.db") as mdb:
        mdb.create_primitive_import.return_value = _import_row()
        r = client.post(
            "/v1/primitives/std/import/stage",
            json={
                "source_kind": "json-schema",
                "source_method": "file",
                "source_label": "money.json",
                "content": '{"type": "object", "title": "Money"}',
            },
        )
    assert r.status_code == 200
    assert r.json()["source_label"] == "money.json"
    assert r.json()["candidates"][0]["name"] == "Money"


def test_stage_url_method_mocks_fetch():
    with patch("app.primitives_routes.db") as mdb, patch.object(
        import_ingestion, "_fetch_url_text", return_value='{"$defs": {"A": {"type": "string"}}}'
    ):
        mdb.create_primitive_import.return_value = _import_row()
        r = client.post(
            "/v1/primitives/std/import/stage",
            json={
                "source_kind": "json-schema",
                "source_method": "url",
                "url": "https://example.com/schema.json",
            },
        )
    assert r.status_code == 200
    body = r.json()
    assert body["detected_count"] == 1
    assert body["source_label"] == "https://example.com/schema.json"


def test_stage_git_method_mocks_fetch():
    with patch("app.primitives_routes.db") as mdb, patch.object(
        import_ingestion, "_fetch_git_text", return_value="types:\n  A:\n    type: string\n"
    ):
        mdb.create_primitive_import.return_value = _import_row()
        r = client.post(
            "/v1/primitives/std/import/stage",
            json={
                "source_kind": "type-def-bundle",
                "source_method": "git",
                "git": {"repo_url": "https://github.com/acme/types", "path": "bundle.yaml"},
            },
        )
    assert r.status_code == 200
    assert r.json()["candidates"][0]["name"] == "A"


# ===========================================================================
# Validation / error mapping
# ===========================================================================


def test_stage_invalid_source_kind_400():
    r = client.post(
        "/v1/primitives/std/import/stage",
        json={"source_kind": "rdf", "source_method": "paste", "content": "{}"},
    )
    assert r.status_code == 400
    assert "Invalid source_kind" in r.json()["detail"]


def test_stage_missing_content_400():
    r = client.post(
        "/v1/primitives/std/import/stage",
        json={"source_kind": "json-schema", "source_method": "paste"},
    )
    assert r.status_code == 400
    assert "content" in r.json()["detail"]


def test_stage_unparseable_content_400():
    r = client.post(
        "/v1/primitives/std/import/stage",
        json={
            "source_kind": "json-schema",
            "source_method": "paste",
            "content": "{ not valid : : :",
        },
    )
    assert r.status_code == 400
    assert "JSON or YAML" in r.json()["detail"]


def test_stage_url_fetch_failure_502():
    from app.import_ingestion import IngestionError

    with patch.object(
        import_ingestion, "_fetch_url_text", side_effect=IngestionError("Failed to fetch URL: boom")
    ):
        r = client.post(
            "/v1/primitives/std/import/stage",
            json={
                "source_kind": "json-schema",
                "source_method": "url",
                "url": "https://example.com/down.json",
            },
        )
    assert r.status_code == 502


def test_stage_three_defs_carry_internal_refs_and_validation():
    """#3461: a doc with 3 $defs stages 3 candidates with internal refs captured."""
    with patch("app.primitives_routes.db") as mdb:
        mdb.create_primitive_import.return_value = _import_row()
        r = client.post(
            "/v1/primitives/std/import/stage",
            json={
                "source_kind": "json-schema",
                "source_method": "paste",
                "content": (
                    '{"$defs": {'
                    '"Money": {"properties": {"c": {"$ref": "#/$defs/Currency"}}},'
                    '"Currency": {"type": "string"},'
                    '"Invoice": {"properties": {"t": {"$ref": "#/$defs/Money"}}}}}'
                ),
            },
        )
    assert r.status_code == 200
    body = r.json()
    assert body["detected_count"] == 3
    by_name = {c["name"]: c for c in body["candidates"]}
    assert by_name["Money"]["internal_refs"][0]["resolved_target"] == "Currency"
    assert by_name["Money"]["internal_refs"][0]["status"] == "internal"
    assert by_name["Currency"]["valid"] is True
    # The staged provenance report carries the same per-def detail.
    _, kwargs = mdb.create_primitive_import.call_args
    staged = {s["name"]: s for s in kwargs["report"]["staged"]}
    assert staged["Invoice"]["internal_refs"][0]["resolved_target"] == "Money"


def test_stage_provenance_failure_is_surfaced_as_warning():
    # A record-write failure must not lose the staged result; it becomes a warning.
    with patch("app.primitives_routes.db") as mdb:
        mdb.create_primitive_import.side_effect = Exception("db down")
        r = client.post(
            "/v1/primitives/std/import/stage",
            json={
                "source_kind": "json-schema",
                "source_method": "paste",
                "content": '{"type": "object", "title": "X"}',
            },
        )
    assert r.status_code == 200
    body = r.json()
    assert body["import_id"] is None
    assert any("provenance" in w for w in body["warnings"])
