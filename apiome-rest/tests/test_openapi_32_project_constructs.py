"""OpenAPI 3.2 constructs in Projects (COA-2.5, #7048).

A project revision stores QUERY / custom-method operations, ``in: querystring`` parameters,
streaming media types (``item_schema``) and a tag hierarchy. These tests cover how each is written
for a 3.2 target (natively) and a 3.1 target (stashed or left out), how the tag list is checked and
stored, and that the REST requests accept the new values.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.auth import validate_authentication
from app.main import app
from app.models import (
    OperationCreateRequest,
    OperationUpdateRequest,
    RequestBodyContentTypeRequest,
    ResponseContentTypeRequest,
    SharedParameterCreateRequest,
)
from app.openapi_generator import generate_openapi_spec
from app.openapi_project_tags import (
    TAG_TAXONOMY_METADATA_KEY,
    build_document_tags,
    normalize_tag,
    read_stored_tags,
    stored_taxonomy,
    validate_tags,
)
from app.paths_generator import (
    build_parameter_for_openapi,
    generate_paths_for_openapi,
    is_openapi_32,
    method_takes_request_body,
)
from app.version_path_copy import CHILD_TABLES

_TENANT_ID = "550e8400-e29b-41d4-a716-446655440000"
_PROJECT_ID = "660e8400-e29b-41d4-a716-446655440010"


# --- fixtures ---------------------------------------------------------------------------------


def _operation(method, *, metadata=None, parameters=None, request_body=None, responses=None, op_id=None):
    """A stored operation as the loaders return it."""
    return {
        "id": f"op-{method}",
        "operation": method,
        "metadata": metadata,
        "description": {"operationId": op_id} if op_id else None,
        "parameters": parameters or [],
        "requestBody": request_body,
        "responses": responses or [],
    }


def _stream_response():
    """A 200 response whose JSON Lines content stores an element schema."""
    return {
        "status_code": "200",
        "description": "Log lines",
        "content_types": [
            {
                "media_type": "application/jsonl",
                "class_id": "c1",
                "class_name": "LogLine",
                "item_schema": True,
            },
            {"media_type": "application/json", "class_id": "c2", "class_name": "LogPage"},
        ],
    }


def _querystring_param():
    """A stored ``in: querystring`` parameter."""
    return {
        "name": "filter",
        "in_location": "querystring",
        "description": "The whole query string",
        "data": {
            "type": "object",
            "properties": {"q": {"type": "string"}},
            "contentMediaType": "application/x-www-form-urlencoded",
            "required": True,
        },
    }


def _paths():
    """One path with GET, QUERY and REPORT operations and each 3.2 construct."""
    return [
        {
            "id": "p1",
            "pathname": "/logs",
            "operations": [
                _operation("GET", parameters=[_querystring_param()], responses=[_stream_response()]),
                _operation(
                    "QUERY",
                    metadata={"httpMethod": "QUERY", "methodSource": "query"},
                    op_id="searchLogs",
                    request_body={
                        "required": True,
                        "content_types": [
                            {"media_type": "application/json", "class_id": "c3", "class_name": "LogQuery"}
                        ],
                    },
                ),
                _operation(
                    "REPORT",
                    metadata={"httpMethod": "Report", "methodSource": "additionalOperations"},
                    op_id="reportLogs",
                ),
            ],
        }
    ]


# --- target version ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "version,expected",
    [
        ("3.2.0", True), ("3.2", True), (" 3.2.1 ", True),
        ("3.1.0", False), ("3.0.3", False), (None, False), ("3.20", False),
    ],
)
def test_is_openapi_32(version, expected):
    assert is_openapi_32(version) is expected


@pytest.mark.parametrize(
    "method,expected",
    [
        ("POST", True), ("put", True), ("PATCH", True), ("QUERY", True), ("REPORT", True),
        ("GET", False), ("delete", False), ("", False),
    ],
)
def test_method_takes_request_body(method, expected):
    assert method_takes_request_body(method) is expected


# --- paths: 3.2 writes the constructs natively ------------------------------------------------


def test_32_writes_query_and_additional_operations_natively():
    item = generate_paths_for_openapi(_paths(), {"openapi_version": "3.2.0"})["/logs"]
    assert set(item) == {"get", "query", "additionalOperations"}
    assert item["query"]["operationId"] == "searchLogs"
    # The method token keeps its declared spelling.
    assert list(item["additionalOperations"]) == ["Report"]
    assert "x-apiome-query-operation" not in item


def test_query_operation_keeps_its_request_body():
    item = generate_paths_for_openapi(_paths(), {"openapi_version": "3.2.0"})["/logs"]
    body = item["query"]["requestBody"]
    assert body["content"]["application/json"]["schema"] == {"$ref": "#/components/schemas/LogQuery"}


def test_32_writes_item_schema_for_streaming_media_types_only():
    item = generate_paths_for_openapi(_paths(), {"openapi_version": "3.2.0"})["/logs"]
    content = item["get"]["responses"]["200"]["content"]
    assert content["application/jsonl"] == {"itemSchema": {"$ref": "#/components/schemas/LogLine"}}
    assert content["application/json"] == {"schema": {"$ref": "#/components/schemas/LogPage"}}


def test_32_writes_querystring_parameter_with_content():
    item = generate_paths_for_openapi(_paths(), {"openapi_version": "3.2.0"})["/logs"]
    [param] = item["get"]["parameters"]
    assert param == {
        "name": "filter",
        "in": "querystring",
        "description": "The whole query string",
        "required": True,
        "content": {
            "application/x-www-form-urlencoded": {
                "schema": {"type": "object", "properties": {"q": {"type": "string"}}}
            }
        },
    }


def test_querystring_parameter_defaults_its_media_type_and_schema():
    param = build_parameter_for_openapi({"name": "qs", "in_location": "querystring", "data": {"style": "form"}})
    assert param["content"] == {"application/x-www-form-urlencoded": {"schema": {"type": "object"}}}
    assert "style" not in param and "schema" not in param


# --- paths: 3.1 stashes them or leaves them out -----------------------------------------------


def test_31_stashes_query_and_additional_operations():
    item = generate_paths_for_openapi(_paths())["/logs"]
    assert set(item) == {"get", "x-apiome-query-operation", "x-apiome-additional-operations"}
    assert list(item["x-apiome-additional-operations"]) == ["Report"]


def test_31_stashes_item_schema():
    item = generate_paths_for_openapi(_paths(), {"openapi_version": "3.1.0"})["/logs"]
    content = item["get"]["responses"]["200"]["content"]
    assert content["application/jsonl"] == {"x-apiome-item-schema": {"$ref": "#/components/schemas/LogLine"}}


def test_31_leaves_out_querystring_parameters():
    item = generate_paths_for_openapi(_paths(), {"openapi_version": "3.1.0"})["/logs"]
    assert "parameters" not in item["get"]


# --- tags -------------------------------------------------------------------------------------


_TAGS = [
    {"name": "pets", "summary": "Pets", "kind": "nav", "description": "All pets"},
    {"name": "cats", "parent": "pets", "kind": "nav", "externalDocs": {"url": "https://example.com/cats"}},
]


def test_document_tags_for_32_keep_the_hierarchy():
    assert build_document_tags(_TAGS, True) == [
        {"name": "pets", "summary": "Pets", "description": "All pets", "kind": "nav"},
        {"name": "cats", "parent": "pets", "kind": "nav", "externalDocs": {"url": "https://example.com/cats"}},
    ]


def test_document_tags_for_31_drop_the_32_fields():
    assert build_document_tags(_TAGS, False) == [
        {"name": "pets", "description": "All pets"},
        {"name": "cats", "externalDocs": {"url": "https://example.com/cats"}},
    ]


def test_document_tags_never_point_at_a_missing_parent():
    assert build_document_tags([{"name": "a", "parent": "ghost"}], True) == [{"name": "a"}]


def test_normalize_tag_trims_and_drops_unknown_fields():
    assert normalize_tag({"name": " a ", "summary": " ", "x-foo": 1, "externalDocs": {"url": ""}}) == {"name": "a"}


def test_read_stored_tags():
    meta = {TAG_TAXONOMY_METADATA_KEY: {"version": 1, "tags": [{"name": "a"}, {"summary": "nameless"}, "junk"]}}
    assert read_stored_tags(meta) == [{"name": "a"}]
    assert read_stored_tags(None) == []
    assert read_stored_tags({TAG_TAXONOMY_METADATA_KEY: "bad"}) == []


def test_validate_tags_accepts_a_tree():
    assert validate_tags(_TAGS) == []


def test_validate_tags_reports_each_problem():
    errors = validate_tags(
        [
            {"name": "a", "parent": "b"},
            {"name": "b", "parent": "a"},
            {"name": "c", "parent": "c"},
            {"name": "d", "parent": "ghost"},
            {"name": "a"},
            {},
        ]
    )
    assert "tags[4]: the tag 'a' is listed more than once" in errors
    assert "tags[5]: name is required" in errors
    assert "tag 'c': parent cannot be the tag itself" in errors
    assert "tag 'd': parent 'ghost' is not a listed tag" in errors
    assert sum("parent cycle" in e for e in errors) == 1


def test_stored_taxonomy_shape():
    assert stored_taxonomy([{"name": "a"}]) == {"version": 1, "tags": [{"name": "a"}]}


# --- the whole document -----------------------------------------------------------------------


def _spec(openapi_version="3.1.0"):
    meta = {"summary": "S", TAG_TAXONOMY_METADATA_KEY: stored_taxonomy(_TAGS)}
    return generate_openapi_spec(
        "acme", "logs", "1.0.0", [], {},
        project_metadata=meta,
        paths_data=_paths(),
        security_scheme_rows=[],
        server_rows=[],
        component_pin_rows=[],
        openapi_version=openapi_version,
    )


def test_spec_declares_the_target_version():
    assert _spec()["openapi"] == "3.1.0"
    assert _spec("3.2.0")["openapi"] == "3.2.0"


def test_spec_writes_tags_and_keeps_them_out_of_info_and_x_metadata():
    spec = _spec("3.2.0")
    assert spec["tags"][1] == {
        "name": "cats", "parent": "pets", "kind": "nav", "externalDocs": {"url": "https://example.com/cats"},
    }
    assert TAG_TAXONOMY_METADATA_KEY not in spec["info"]
    assert spec["x-metadata"] == {"summary": "S"}
    assert "parent" not in _spec()["tags"][1]


def test_spec_32_paths_are_native():
    assert "query" in _spec("3.2.0")["paths"]["/logs"]
    assert "x-apiome-query-operation" in _spec()["paths"]["/logs"]


# --- requests ---------------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["GET", "query", "REPORT", "M-SEARCH", "x.y_z~"])
def test_operation_accepts_method_tokens(method):
    assert OperationCreateRequest(operation=f" {method} ").operation == method


@pytest.mark.parametrize("method", ["", "  ", "GET POST", "a/b", "(x)", "M" * 51])
def test_operation_rejects_non_tokens(method):
    with pytest.raises(ValidationError):
        OperationCreateRequest(operation=method)


def test_operation_update_leaves_a_missing_method_alone():
    assert OperationUpdateRequest().operation is None
    with pytest.raises(ValidationError):
        OperationUpdateRequest(operation="a b")


def test_parameter_accepts_querystring_and_rejects_unknown_locations():
    assert SharedParameterCreateRequest(name="qs", in_location="QueryString").in_location == "querystring"
    with pytest.raises(ValidationError):
        SharedParameterCreateRequest(name="x", in_location="body")


def test_content_type_requests_carry_item_schema():
    assert RequestBodyContentTypeRequest(media_type="application/json").item_schema is False
    assert ResponseContentTypeRequest(media_type="text/event-stream", item_schema=True).item_schema is True


def test_version_copy_copies_item_schema():
    columns = {spec.table: spec.columns for spec in CHILD_TABLES}
    assert "item_schema" in columns["shared_path_request_body_content"]
    assert "item_schema" in columns["shared_path_response_content"]


# --- /v1/projects/{tenant}/{project}/openapi-tags ---------------------------------------------

client = TestClient(app)


@pytest.fixture
def _auth():
    app.dependency_overrides[validate_authentication] = lambda: {
        "auth_method": "jwt",
        "user_id": "660e8400-e29b-41d4-a716-446655440001",
        "tenant_id": _TENANT_ID,
    }
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def _project(metadata):
    return {"id": _PROJECT_ID, "metadata": metadata, "updated_at": "2026-11-20T00:00:00+00:00"}


def _echo_update(_project_id, _tenant_id, updates, expected_updated_at=None):
    """``db.update_project`` stand-in: the project with the metadata it was given."""
    return _project(updates["metadata"])


def test_get_openapi_tags(_auth):
    with patch("app.projects_routes.db") as m:
        m.get_project_by_id.return_value = _project({TAG_TAXONOMY_METADATA_KEY: stored_taxonomy(_TAGS)})
        r = client.get(f"/v1/projects/acme/{_PROJECT_ID}/openapi-tags")
    assert r.status_code == 200
    body = r.json()
    assert body["project_id"] == _PROJECT_ID
    assert [t["name"] for t in body["tags"]] == ["pets", "cats"]
    assert body["tags"][1]["parent"] == "pets"
    assert body["tags"][1]["externalDocs"] == {"url": "https://example.com/cats", "description": None}


def test_get_openapi_tags_404(_auth):
    with patch("app.projects_routes.db") as m:
        m.get_project_by_id.return_value = None
        r = client.get(f"/v1/projects/acme/{_PROJECT_ID}/openapi-tags")
    assert r.status_code == 404


def test_put_openapi_tags_stores_the_list_and_keeps_other_metadata(_auth):
    with patch("app.projects_routes.db") as m:
        m.get_project_by_id.return_value = _project({"summary": "S"})
        m.update_project.side_effect = _echo_update
        r = client.put(f"/v1/projects/acme/{_PROJECT_ID}/openapi-tags", json={"tags": _TAGS})
    assert r.status_code == 200, r.text
    _, _, updates = m.update_project.call_args.args
    assert updates["metadata"]["summary"] == "S"
    assert updates["metadata"][TAG_TAXONOMY_METADATA_KEY]["tags"][1] == {
        "name": "cats", "parent": "pets", "kind": "nav", "externalDocs": {"url": "https://example.com/cats"},
    }
    assert m.update_project.call_args.kwargs["expected_updated_at"] == "2026-11-20T00:00:00+00:00"
    assert [t["name"] for t in r.json()["tags"]] == ["pets", "cats"]


def test_put_empty_list_clears_the_tags(_auth):
    with patch("app.projects_routes.db") as m:
        m.get_project_by_id.return_value = _project({TAG_TAXONOMY_METADATA_KEY: stored_taxonomy(_TAGS)})
        m.update_project.side_effect = _echo_update
        r = client.put(f"/v1/projects/acme/{_PROJECT_ID}/openapi-tags", json={"tags": []})
    assert r.status_code == 200
    assert TAG_TAXONOMY_METADATA_KEY not in m.update_project.call_args.args[2]["metadata"]
    assert r.json()["tags"] == []


def test_put_rejects_an_invalid_hierarchy(_auth):
    with patch("app.projects_routes.db") as m:
        m.get_project_by_id.return_value = _project({})
        r = client.put(
            f"/v1/projects/acme/{_PROJECT_ID}/openapi-tags",
            json={"tags": [{"name": "a", "parent": "b"}, {"name": "b", "parent": "a"}]},
        )
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "invalid_tags"
    m.update_project.assert_not_called()


def test_put_reports_a_concurrent_change(_auth):
    from app.database import ProjectUpdateConflict

    with patch("app.projects_routes.db") as m:
        m.get_project_by_id.return_value = _project({})
        m.update_project.side_effect = ProjectUpdateConflict("2026-11-21T00:00:00+00:00")
        r = client.put(f"/v1/projects/acme/{_PROJECT_ID}/openapi-tags", json={"tags": [{"name": "a"}]})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "update_conflict"
