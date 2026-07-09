"""Unit tests for the example-first response resolver (SIM-1.2, #4417)."""

from __future__ import annotations

import pytest

from apiome_mock.response_resolver import (
    negotiate_media_type,
    parse_prefer_example,
    resolve_response_body,
    select_default_success_status,
)

MULTI_EXAMPLE_SPEC = {
    "openapi": "3.1.0",
    "info": {"title": "Examples", "version": "1.0.0"},
    "paths": {
        "/items": {
            "get": {
                "responses": {
                    "200": {
                        "description": "ok",
                        "content": {
                            "application/json": {
                                "schema": {"type": "object"},
                                "examples": {
                                    "alpha": {"value": {"name": "alpha"}},
                                    "beta": {"value": {"name": "beta"}},
                                    "gamma": {"value": {"name": "gamma"}},
                                },
                            }
                        },
                    }
                }
            }
        }
    },
}

DUAL_MEDIA_SPEC = {
    "openapi": "3.1.0",
    "info": {"title": "Dual", "version": "1.0.0"},
    "paths": {
        "/report": {
            "get": {
                "responses": {
                    "200": {
                        "description": "ok",
                        "content": {
                            "application/json": {
                                "example": {"format": "json"},
                            },
                            "application/xml": {
                                "example": "<report format='xml'/>",
                            },
                        },
                    }
                }
            }
        }
    },
}

FALLBACK_SPEC = {
    "openapi": "3.1.0",
    "info": {"title": "Fallback", "version": "1.0.0"},
    "paths": {
        "/fallback": {
            "get": {
                "responses": {
                    "200": {
                        "description": "ok",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "string",
                                    "enum": ["first", "second"],
                                    "default": "default-value",
                                },
                                "example": "media-example",
                            }
                        },
                    }
                }
            }
        },
        "/schema-only": {
            "get": {
                "responses": {
                    "200": {
                        "description": "ok",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "string",
                                    "enum": ["enum-first", "enum-second"],
                                    "default": "schema-default",
                                }
                            }
                        },
                    }
                }
            }
        },
        "/synthesis": {
            "get": {
                "responses": {
                    "200": {
                        "description": "ok",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["id"],
                                    "properties": {"id": {"type": "integer"}},
                                }
                            }
                        },
                    }
                }
            }
        },
    },
}


def _response_for(spec: dict, path: str) -> dict:
    return spec["paths"][path]["get"]["responses"]["200"]


def test_named_examples_return_first_in_document_order() -> None:
    response_obj = _response_for(MULTI_EXAMPLE_SPEC, "/items")
    resolved = resolve_response_body(response_obj, MULTI_EXAMPLE_SPEC)
    assert resolved.body == {"name": "alpha"}
    assert resolved.media_type == "application/json"


def test_named_examples_are_deterministic_across_calls() -> None:
    response_obj = _response_for(MULTI_EXAMPLE_SPEC, "/items")
    first = resolve_response_body(response_obj, MULTI_EXAMPLE_SPEC)
    second = resolve_response_body(response_obj, MULTI_EXAMPLE_SPEC)
    assert first.body == second.body == {"name": "alpha"}


def test_prefer_example_selects_named_example() -> None:
    response_obj = _response_for(MULTI_EXAMPLE_SPEC, "/items")
    resolved = resolve_response_body(
        response_obj,
        MULTI_EXAMPLE_SPEC,
        prefer_header="example=gamma",
    )
    assert resolved.body == {"name": "gamma"}


def test_unknown_prefer_example_falls_back_to_default_example() -> None:
    response_obj = _response_for(MULTI_EXAMPLE_SPEC, "/items")
    resolved = resolve_response_body(
        response_obj,
        MULTI_EXAMPLE_SPEC,
        prefer_header="example=missing",
    )
    assert resolved.body == {"name": "alpha"}


def test_parse_prefer_example_reads_prism_compatible_header() -> None:
    assert parse_prefer_example("example=dog") == "dog"
    assert parse_prefer_example('respond-async, example="cat"') == "cat"


def test_accept_header_selects_xml_example() -> None:
    response_obj = _response_for(DUAL_MEDIA_SPEC, "/report")
    resolved = resolve_response_body(
        response_obj,
        DUAL_MEDIA_SPEC,
        accept="application/xml",
    )
    assert resolved.media_type == "application/xml"
    assert resolved.body == "<report format='xml'/>"


def test_accept_header_selects_json_example() -> None:
    response_obj = _response_for(DUAL_MEDIA_SPEC, "/report")
    resolved = resolve_response_body(
        response_obj,
        DUAL_MEDIA_SPEC,
        accept="application/json",
    )
    assert resolved.media_type == "application/json"
    assert resolved.body == {"format": "json"}


def test_unacceptable_accept_returns_not_acceptable() -> None:
    response_obj = _response_for(DUAL_MEDIA_SPEC, "/report")
    resolved = resolve_response_body(
        response_obj,
        DUAL_MEDIA_SPEC,
        accept="application/pdf",
    )
    assert resolved.not_acceptable is True


def test_fallback_prefers_examples_over_media_example() -> None:
    response_obj = {
        "description": "ok",
        "content": {
            "application/json": {
                "example": "media-example",
                "examples": {"one": {"value": "named-example"}},
                "schema": {"type": "string", "default": "schema-default"},
            }
        },
    }
    resolved = resolve_response_body(response_obj, FALLBACK_SPEC)
    assert resolved.body == "named-example"


def test_fallback_uses_media_example_before_schema_defaults() -> None:
    response_obj = _response_for(FALLBACK_SPEC, "/fallback")
    resolved = resolve_response_body(response_obj, FALLBACK_SPEC)
    assert resolved.body == "media-example"


def test_fallback_uses_schema_example_when_no_media_example() -> None:
    response_obj = {
        "description": "ok",
        "content": {
            "application/json": {
                "schema": {
                    "type": "string",
                    "example": "schema-example",
                    "default": "schema-default",
                    "enum": ["enum-first"],
                }
            }
        },
    }
    resolved = resolve_response_body(response_obj, FALLBACK_SPEC)
    assert resolved.body == "schema-example"


def test_fallback_uses_schema_default_before_enum() -> None:
    response_obj = _response_for(FALLBACK_SPEC, "/schema-only")
    resolved = resolve_response_body(response_obj, FALLBACK_SPEC)
    assert resolved.body == "schema-default"


def test_fallback_uses_enum_before_synthesis() -> None:
    response_obj = {
        "description": "ok",
        "content": {
            "application/json": {
                "schema": {
                    "type": "string",
                    "enum": ["enum-first", "enum-second"],
                }
            }
        },
    }
    resolved = resolve_response_body(response_obj, FALLBACK_SPEC)
    assert resolved.body == "enum-first"


def test_fallback_uses_synthesis_when_no_examples_or_defaults() -> None:
    response_obj = _response_for(FALLBACK_SPEC, "/synthesis")
    resolved = resolve_response_body(response_obj, FALLBACK_SPEC, op_key="GET /synthesis")
    assert isinstance(resolved.body, dict)
    assert isinstance(resolved.body["id"], int)


def test_select_default_success_status_uses_lowest_2xx() -> None:
    operation = {
        "responses": {
            "201": {"description": "created"},
            "200": {"description": "ok"},
            "404": {"description": "missing"},
        }
    }
    status, response_obj = select_default_success_status(operation)
    assert status == 200
    assert response_obj == {"description": "ok"}


@pytest.mark.parametrize(
    ("accept", "available", "expected"),
    [
        ("application/xml", ["application/json", "application/xml"], "application/xml"),
        ("application/json", ["application/json", "application/xml"], "application/json"),
        (None, ["text/plain", "application/json"], "application/json"),
    ],
)
def test_negotiate_media_type(accept: str | None, available: list[str], expected: str) -> None:
    assert negotiate_media_type(accept, available) == expected
