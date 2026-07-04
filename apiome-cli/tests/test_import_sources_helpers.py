"""Unit tests for the import-source registry helpers (MFI-1.4)."""

from __future__ import annotations

import base64

import pytest

from apiome_cli.import_.sources import (
    build_adapter_import_body,
    find_source,
    source_keys,
    unknown_format_message,
)

_DESCRIPTORS = [
    {
        "key": "openapi",
        "label": "OpenAPI / Swagger",
        "description": "REST API description.",
        "icon": "FileJson",
        "paradigm": "rest",
        "input_kinds": ["file", "url", "paste"],
        "supports_live_discovery": False,
        "formats": ["openapi-3.0", "openapi-3.1"],
    },
    {
        "key": "sample",
        "label": "Sample",
        "description": "No-op acceptance adapter.",
        "icon": "Beaker",
        "paradigm": "rest",
        "input_kinds": ["file"],
        "supports_live_discovery": False,
        "formats": [],
    },
]


def test_source_keys_preserves_order_and_skips_blank() -> None:
    descriptors = [{"key": "a"}, {"key": ""}, {"nope": 1}, {"key": "b"}]
    assert source_keys(descriptors) == ["a", "b"]


def test_find_source_matches_exact_key() -> None:
    assert find_source(_DESCRIPTORS, "sample")["label"] == "Sample"
    assert find_source(_DESCRIPTORS, "missing") is None


def test_unknown_format_message_lists_available_sorted() -> None:
    message = unknown_format_message("graphql", _DESCRIPTORS)
    assert "graphql" in message
    assert "openapi, sample" in message
    assert "import --list" in message


def test_unknown_format_message_handles_empty_registry() -> None:
    assert "(none registered)" in unknown_format_message("x", [])


def test_build_adapter_import_body_sends_bytes_verbatim() -> None:
    raw = b"type Query { ping: String }"
    body = build_adapter_import_body(
        raw,
        source_format="graphql",
        source_label="schema.graphql",
        dry_run=True,
    )
    assert body["metadata"]["source_kind"] == "graphql"
    assert body["metadata"]["options"]["dry_run"] is True
    assert body["filename"] == "schema.graphql"
    # The project name is derived from the filename stem; slug follows DB rules.
    assert body["metadata"]["project"]["name"] == "schema"
    assert body["metadata"]["project"]["slug"] == "schema"
    assert body["metadata"]["version"]["version_id"] == "0.0.0"
    assert base64.b64decode(body["document_base64"]) == raw


def test_build_adapter_import_body_forwards_archive_root() -> None:
    body = build_adapter_import_body(
        b"PK",
        source_format="grpc",
        source_label="protos.zip",
        dry_run=False,
        archive_root="user/user_service.proto",
    )
    assert body["metadata"]["options"]["archive_root"] == "user/user_service.proto"


def test_build_adapter_import_body_defaults_name_to_format_for_stdin() -> None:
    body = build_adapter_import_body(
        b"{}",
        source_format="asyncapi",
        source_label=None,
        dry_run=False,
    )
    assert body["metadata"]["project"]["name"] == "asyncapi-import"
    assert "filename" not in body


@pytest.mark.parametrize(
    "label,expected",
    [
        ("/tmp/dir/petstore.openapi.yaml", "petstore.openapi"),
        ("schema", "schema"),
    ],
)
def test_build_adapter_import_body_project_name_from_label(label: str, expected: str) -> None:
    body = build_adapter_import_body(b"x", source_format="f", source_label=label, dry_run=False)
    assert body["metadata"]["project"]["name"] == expected
