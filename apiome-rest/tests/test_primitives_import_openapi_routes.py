"""API tests for importing OpenAPI 3.1 ``components/schemas`` as primitives (#3465).

``POST /v1/primitives/{tenant_slug}/import`` (and ``/import/review``) with
``source_kind='openapi'`` reads each ``components.schemas`` entry as a type. The DB is mocked,
so these assert that each component becomes one row, that ``#/components/schemas/X`` refs land
rewritten in the ``refs`` payload, and that a non-OpenAPI document is a clear 400.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app

client = TestClient(app)

_JWT = {"tenant_id": "t1", "user_id": "u1", "auth_method": "jwt"}

_PETSTORE = {
    "openapi": "3.1.0",
    "info": {"title": "Petstore", "version": "1.0.0"},
    "paths": {
        "/pets": {
            "get": {
                "responses": {
                    "200": {
                        "description": "ok",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Pet"}
                            }
                        },
                    }
                }
            }
        }
    },
    "components": {
        "schemas": {
            "Pet": {
                "type": "object",
                "required": ["id"],
                "properties": {
                    "id": {"type": "integer"},
                    "tag": {"$ref": "#/components/schemas/Tag"},
                    "contact": {"type": "string", "format": "email"},
                },
            },
            "Tag": {"type": "string", "examples": ["dog"]},
        }
    },
}


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = lambda: _JWT
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def _post(path, schema, **extra):
    body = {"schema": schema, "import_all": True, "source_kind": "openapi"}
    body.update(extra)
    return client.post(f"/v1/primitives/acme/{path}", json=body)


def test_components_schemas_import_as_rows_with_rewritten_refs():
    created = []

    def _create(**kwargs):
        created.append(kwargs)
        return {"name": kwargs["name"], "refs": kwargs.get("refs", [])}

    with patch("app.primitives_routes.db") as mdb:
        mdb.create_primitive.side_effect = _create
        mdb.get_primitive_by_schema_id.return_value = None
        mdb.get_primitive_by_namespace_name.return_value = None
        mdb.create_primitive_import.return_value = {"id": "imp-oa1"}
        r = _post("import", _PETSTORE, source_label="petstore.yaml")

    assert r.status_code == 200, r.text
    body = r.json()
    # One row per component schema; the document root (info/paths) is not a type.
    assert set(body["imported"]) == {"Pet", "Tag"}
    assert body["total_imported"] == 2
    assert [c["name"] for c in created] == ["Pet", "Tag"]

    pet = next(c for c in created if c["name"] == "Pet")
    # The sibling component pointer is persisted as a relative registry ref in `refs`.
    assert {
        "relative_ref": "./tag",
        "resolved_target": "https://api.apiome.dev/types/tenant/acme/tag",
        "status": "unresolved",
    } in pet["refs"]
    assert all(e["status"] != "internal" for e in pet["refs"])
    assert "#/components/schemas/Tag" not in str(pet["schema"])
    assert pet["schema"]["properties"]["tag"] == {"$ref": "./tag"}

    # The rewrite log records the component pointer as written in the source.
    assert {
        "from": "#/components/schemas/Tag",
        "to": "./tag",
        "kind": "internal",
    } in body["rewrites"]["Pet"]

    _, kwargs = mdb.create_primitive_import.call_args
    assert kwargs["source_kind"] == "openapi"
    assert kwargs["source_label"] == "petstore.yaml"
    assert kwargs["imported_count"] == 2


def test_review_lists_components_and_sibling_refs_are_not_dangling():
    with patch("app.primitives_routes.db") as mdb:
        mdb.get_primitive_by_schema_id.return_value = None
        mdb.get_primitive_by_namespace_name.return_value = None
        r = _post("import/review", _PETSTORE)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source_kind"] == "openapi"
    by_name = {t["name"]: t for t in body["types"]}
    assert set(by_name) == {"Pet", "Tag"}
    assert all(t["status"] == "new" for t in by_name.values())
    # Tag arrives in the same import, so Pet's ./tag ref is not reported as unresolved.
    assert not any(
        u.get("relative_ref") == "./tag" for u in by_name["Pet"]["unresolved_refs"]
    )
    mdb.create_primitive.assert_not_called()


def test_selected_definitions_filter_components():
    created = []
    with patch("app.primitives_routes.db") as mdb:
        mdb.create_primitive.side_effect = lambda **k: created.append(k) or {"name": k["name"]}
        mdb.get_primitive_by_schema_id.return_value = None
        mdb.get_primitive_by_namespace_name.return_value = None
        mdb.create_primitive_import.return_value = {"id": "imp-oa2"}
        r = _post("import", _PETSTORE, import_all=False, selected_definitions=["Tag"])
    assert r.status_code == 200
    assert [c["name"] for c in created] == ["Tag"]


def test_openapi_3_0_warning_is_returned():
    doc = {**_PETSTORE, "openapi": "3.0.3"}
    with patch("app.primitives_routes.db") as mdb:
        mdb.get_primitive_by_schema_id.return_value = None
        mdb.get_primitive_by_namespace_name.return_value = None
        r = _post("import/review", doc)
    assert r.status_code == 200
    assert any("3.0.3" in w for w in r.json()["warnings"])


@pytest.mark.parametrize(
    "document, needle",
    [
        ({"$defs": {"Money": {"type": "object"}}}, "'openapi' version field"),
        ({"swagger": "2.0", "definitions": {"Pet": {}}}, "Swagger 2.0"),
        ({"openapi": "3.1.0", "info": {"title": "x"}}, "No components.schemas"),
    ],
)
@pytest.mark.parametrize("path", ["import", "import/review"])
def test_non_openapi_documents_are_clear_400(document, needle, path):
    with patch("app.primitives_routes.db") as mdb:
        r = _post(path, document)
    assert r.status_code == 400
    assert needle in r.json()["detail"]
    mdb.create_primitive.assert_not_called()
