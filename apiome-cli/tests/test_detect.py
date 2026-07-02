"""Tests for OpenAPI vs JSON Schema document detection."""

from __future__ import annotations

import pytest

from apiome_cli.import_.detect import (
    DocumentKind,
    describe_document_format,
    detect_document_kind,
    is_draft_2020_12_schema_uri,
    is_recognized_json_schema_draft_uri,
    looks_like_arazzo,
    looks_like_arazzo_filename,
    looks_like_json_schema,
    looks_like_json_schema_type,
    looks_like_openapi,
    recommended_import_command,
    resolve_auto_import_command,
    type_library_importer_message,
    unrecognized_auto_import_message,
    wrong_importer_message,
)

_OPENAPI_SPEC = {
    "openapi": "3.1.0",
    "info": {"title": "API", "version": "1.0.0"},
    "paths": {},
}

_SWAGGER_SPEC = {
    "swagger": "2.0",
    "info": {"title": "API", "version": "1.0.0"},
    "paths": {},
}

_JSON_SCHEMA_WITH_META = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"id": {"type": "string"}},
}

_JSON_SCHEMA_FRAGMENT_URI = {
    "$schema": "https://example.com/meta/draft/2020-12/custom",
    "type": "string",
}

_JSON_SCHEMA_NO_META = {
    "type": "object",
    "properties": {"name": {"type": "string"}},
}

_ARAZZO_SPEC = {
    "arazzo": "1.0.0",
    "info": {"title": "Checkout", "version": "1.0.0"},
    "sourceDescriptions": [
        {"name": "api", "url": "https://example.test/openapi.json", "type": "openapi"},
    ],
    "workflows": [{"workflowId": "flow", "steps": []}],
}

_ARAZZO_NO_VERSION = {
    "info": {"title": "Checkout", "version": "1.0.0"},
    "sourceDescriptions": [
        {"name": "api", "url": "https://example.test/openapi.json", "type": "openapi"},
    ],
    "workflows": [{"workflowId": "flow", "steps": []}],
}

_TYPE_LIBRARY = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$defs": {
        "Email": {"type": "string", "format": "email"},
        "Timestamp": {"type": "string", "format": "date-time"},
    },
}


def test_looks_like_openapi_with_openapi_key() -> None:
    assert looks_like_openapi(_OPENAPI_SPEC) is True


def test_looks_like_openapi_with_swagger_key() -> None:
    assert looks_like_openapi(_SWAGGER_SPEC) is True


def test_looks_like_openapi_false_for_json_schema() -> None:
    assert looks_like_openapi(_JSON_SCHEMA_WITH_META) is False


def test_is_draft_2020_12_schema_uri_accepts_canonical_uris() -> None:
    assert is_draft_2020_12_schema_uri(
        "https://json-schema.org/draft/2020-12/schema",
    )
    assert is_draft_2020_12_schema_uri(
        "https://json-schema.org/draft/2020-12/hyper-schema",
    )


def test_is_draft_2020_12_schema_uri_accepts_fragment() -> None:
    assert is_draft_2020_12_schema_uri("https://example.com/draft/2020-12/schema")


def test_is_draft_2020_12_schema_uri_rejects_other_drafts() -> None:
    assert is_draft_2020_12_schema_uri("https://json-schema.org/draft/2019-09/schema") is False


def test_looks_like_json_schema_with_draft_2020_12_meta() -> None:
    assert looks_like_json_schema(_JSON_SCHEMA_WITH_META) is True


def test_looks_like_json_schema_with_fragment_uri() -> None:
    assert looks_like_json_schema(_JSON_SCHEMA_FRAGMENT_URI) is True


def test_looks_like_json_schema_without_meta_uses_vocabulary() -> None:
    assert looks_like_json_schema(_JSON_SCHEMA_NO_META) is True


def test_looks_like_json_schema_rejects_unsupported_schema_uri() -> None:
    document = {
        "$schema": "https://json-schema.org/draft/2019-09/schema",
        "type": "string",
    }
    assert looks_like_json_schema(document) is False


def test_looks_like_json_schema_false_for_openapi() -> None:
    assert looks_like_json_schema(_OPENAPI_SPEC) is False


def test_looks_like_arazzo_detects_version_field() -> None:
    assert looks_like_arazzo(_ARAZZO_SPEC) is True


def test_looks_like_arazzo_false_for_openapi() -> None:
    assert looks_like_arazzo(_OPENAPI_SPEC) is False


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("checkout.arazzo.yaml", True),
        ("checkout.arazzo.yml", True),
        ("checkout.arazzo.json", True),
        ("CHECKOUT.ARAZZO.YAML", True),
        ("  checkout.arazzo.yaml  ", True),
        ("checkout.yaml", False),
        ("arazzo.yaml", False),
        ("checkout-arazzo.yaml", False),
        ("checkout.arazzo.txt", False),
        ("", False),
        (None, False),
    ],
)
def test_looks_like_arazzo_filename(filename: str | None, expected: bool) -> None:
    assert looks_like_arazzo_filename(filename) is expected


def test_detect_document_kind_arazzo() -> None:
    assert detect_document_kind(_ARAZZO_SPEC) is DocumentKind.arazzo


def test_detect_document_kind_openapi() -> None:
    assert detect_document_kind(_OPENAPI_SPEC) is DocumentKind.openapi
    assert detect_document_kind(_SWAGGER_SPEC) is DocumentKind.openapi


def test_detect_document_kind_json_schema() -> None:
    assert detect_document_kind(_JSON_SCHEMA_WITH_META) is DocumentKind.json_schema
    assert detect_document_kind(_JSON_SCHEMA_NO_META) is DocumentKind.json_schema


def test_detect_document_kind_unknown() -> None:
    assert detect_document_kind({"foo": "bar"}) is DocumentKind.unknown


def test_recommended_import_command() -> None:
    assert recommended_import_command(DocumentKind.openapi) == "import openapi"
    assert (
        recommended_import_command(DocumentKind.openapi, document=_SWAGGER_SPEC)
        == "import swagger"
    )
    assert recommended_import_command(DocumentKind.arazzo) == "import arazzo"
    assert recommended_import_command(DocumentKind.json_schema) == "import json-schema"
    assert (
        recommended_import_command(DocumentKind.json_schema, document=_TYPE_LIBRARY)
        == "import json-schema-type"
    )
    assert recommended_import_command(DocumentKind.unknown) is None


@pytest.mark.parametrize(
    ("document", "expected"),
    [
        (_SWAGGER_SPEC, "swagger"),
        (_OPENAPI_SPEC, "openapi"),
        (_ARAZZO_SPEC, "arazzo"),
        (_TYPE_LIBRARY, "json-schema-type"),
        (_JSON_SCHEMA_WITH_META, "json-schema"),
        (_JSON_SCHEMA_NO_META, "json-schema"),
        ({"title": "mystery"}, None),
    ],
)
def test_resolve_auto_import_command(document: dict, expected: str | None) -> None:
    assert resolve_auto_import_command(document) == expected


def test_resolve_auto_import_command_arazzo_filename_hint_when_inconclusive() -> None:
    """A marker-less Arazzo file routes to ``arazzo`` via its filename hint."""
    assert resolve_auto_import_command(_ARAZZO_NO_VERSION) is None
    assert (
        resolve_auto_import_command(
            _ARAZZO_NO_VERSION,
            filename="checkout.arazzo.yaml",
        )
        == "arazzo"
    )


def test_resolve_auto_import_command_content_marker_wins_over_filename() -> None:
    """An ``arazzo:`` content marker is authoritative regardless of filename."""
    assert (
        resolve_auto_import_command(_ARAZZO_SPEC, filename="weird.yaml") == "arazzo"
    )


def test_resolve_auto_import_command_openapi_content_beats_arazzo_filename() -> None:
    """An OpenAPI document named ``*.arazzo.yaml`` still resolves to OpenAPI."""
    assert (
        resolve_auto_import_command(
            _OPENAPI_SPEC,
            filename="api.arazzo.yaml",
        )
        == "openapi"
    )


def test_resolve_auto_import_command_json_schema_content_beats_arazzo_filename() -> None:
    """A JSON Schema document named ``*.arazzo.yaml`` still resolves to JSON Schema."""
    assert (
        resolve_auto_import_command(
            _JSON_SCHEMA_WITH_META,
            filename="thing.arazzo.json",
        )
        == "json-schema"
    )


def test_resolve_auto_import_command_unknown_without_filename_hint() -> None:
    """Unknown content with a non-Arazzo filename stays unresolved."""
    assert (
        resolve_auto_import_command(_ARAZZO_NO_VERSION, filename="checkout.yaml")
        is None
    )


def test_describe_document_format() -> None:
    assert describe_document_format(_SWAGGER_SPEC) == "Swagger 2.0"
    assert describe_document_format(_OPENAPI_SPEC) == "OpenAPI 3.1.0"
    assert describe_document_format(_ARAZZO_SPEC) == "Arazzo 1.0.0"


def test_describe_document_format_arazzo_filename_hint() -> None:
    assert (
        describe_document_format(
            _ARAZZO_NO_VERSION,
            filename="checkout.arazzo.yaml",
        )
        == "Arazzo (by filename)"
    )
    # Content markers keep their precise label even with an Arazzo filename.
    assert (
        describe_document_format(_OPENAPI_SPEC, filename="api.arazzo.yaml")
        == "OpenAPI 3.1.0"
    )
    # No filename hint and unknown content stays "unknown".
    assert describe_document_format(_ARAZZO_NO_VERSION) == "unknown"


def test_unrecognized_auto_import_message_lists_headers() -> None:
    message = unrecognized_auto_import_message({"foo": "bar", "title": "x"})
    assert "foo" in message
    assert "title" in message


def test_wrong_importer_message_json_schema_on_openapi_command() -> None:
    message = wrong_importer_message(
        DocumentKind.json_schema,
        attempted="openapi",
    )
    assert "JSON Schema" in message
    assert "import json-schema" in message
    assert "Use: apiome import json-schema" in message


def test_wrong_importer_message_openapi_on_json_schema_command() -> None:
    message = wrong_importer_message(
        DocumentKind.openapi,
        attempted="json-schema",
    )
    assert "OpenAPI" in message
    assert "import openapi" in message


def test_wrong_importer_message_arazzo_on_openapi_command() -> None:
    message = wrong_importer_message(DocumentKind.arazzo, attempted="openapi")
    assert "Arazzo" in message
    assert "import arazzo" in message


def test_wrong_importer_message_openapi_on_arazzo_command() -> None:
    message = wrong_importer_message(DocumentKind.openapi, attempted="arazzo")
    assert "OpenAPI" in message
    assert "import openapi" in message


@pytest.mark.parametrize(
    ("schema_uri", "expected"),
    [
        ("https://json-schema.org/draft/2020-12/schema", True),
        ("https://json-schema.org/draft/2020-12/hyper-schema", True),
        ("http://json-schema.org/draft/2020-12/schema", True),
        ("https://json-schema.org/draft/2019-09/schema", False),
        ("", False),
    ],
)
def test_is_draft_2020_12_schema_uri_cases(schema_uri: str, expected: bool) -> None:
    assert is_draft_2020_12_schema_uri(schema_uri) is expected


@pytest.mark.parametrize(
    ("schema_uri", "expected"),
    [
        ("http://json-schema.org/draft-07/schema#", True),
        ("https://json-schema.org/draft/2019-09/schema", True),
        ("http://json-schema.org/draft-04/schema", True),
        ("http://json-schema.org/draft-04/schema#", True),
        ("https://json-schema.org/draft/04/schema", True),
        ("https://json-schema.org/draft-04/schema#", True),
        ("https://example.com/custom/meta", False),
    ],
)
def test_is_recognized_json_schema_draft_uri_cases(
    schema_uri: str,
    expected: bool,
) -> None:
    assert is_recognized_json_schema_draft_uri(schema_uri) is expected


def test_looks_like_json_schema_type_detects_definitions_library() -> None:
    document = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "definitions": {
            "Email": {"type": "string"},
        },
    }
    assert looks_like_json_schema_type(document) is True


def test_looks_like_json_schema_type_detects_defs_library() -> None:
    assert looks_like_json_schema_type(_TYPE_LIBRARY) is True


def test_looks_like_json_schema_type_false_when_properties_present() -> None:
    assert looks_like_json_schema_type(_JSON_SCHEMA_WITH_META) is False


def test_looks_like_json_schema_type_false_for_openapi() -> None:
    assert looks_like_json_schema_type(_OPENAPI_SPEC) is False


def test_type_library_importer_message_names_correct_command() -> None:
    message = type_library_importer_message()
    assert "import json-schema-type" in message
    assert "Use: apiome import json-schema-type" in message
