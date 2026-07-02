"""OPTIONS operations: OpenAPI path item export and default responses."""

from app.paths_generator import build_operation_for_openapi, build_path_item_for_openapi


def test_options_default_response_is_204_when_no_responses():
    op = {
        "operation": "OPTIONS",
        "parameters": [],
        "responses": [],
    }
    out = build_operation_for_openapi(op)
    assert out["responses"]["204"]["description"] == "No Content"


def test_options_request_body_not_exported():
    op = {
        "operation": "OPTIONS",
        "parameters": [],
        "requestBody": {"description": "x", "required": False, "content_types": []},
        "responses": [],
    }
    out = build_operation_for_openapi(op)
    assert "requestBody" not in out


def test_path_item_includes_options_key():
    path = {
        "pathname": "/items",
        "operations": [
            {
                "operation": "OPTIONS",
                "parameters": [],
                "responses": [],
            }
        ],
    }
    item = build_path_item_for_openapi(path)
    assert "options" in item
    assert item["options"]["responses"]["204"]["description"] == "No Content"
