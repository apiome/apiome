"""Tests for import document source loading (files, stdin, URLs)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from apiome_cli.import_.json_schema import load_json_schema_file
from apiome_cli.import_.openapi import load_openapi_file
from apiome_cli.import_.source import (
    format_document_import_progress,
    format_import_source_label,
    is_remote_source,
    load_document_bytes,
    read_document_text,
    source_basename,
    source_byte_size,
    suffix_from_source,
)

_OPENAPI_JSON = json.dumps(
    {
        "openapi": "3.1.0",
        "info": {"title": "Remote API", "version": "1.0.0"},
        "paths": {},
    }
)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("https://example.com/openapi.json", True),
        ("http://localhost:8000/spec.yaml", True),
        ("./local.json", False),
        ("-", False),
        ("/absolute/path.json", False),
    ],
)
def test_is_remote_source(source: str, expected: bool) -> None:
    assert is_remote_source(source) is expected


def test_source_basename_from_url() -> None:
    assert source_basename("https://example.com/schemas/email.json") == "email.json"


def test_format_import_source_label() -> None:
    assert format_import_source_label("-") == "stdin"
    assert format_import_source_label("./petstore.json") == "petstore.json"
    assert (
        format_import_source_label("https://example.com/schemas/email.json")
        == "email.json"
    )


def test_format_document_import_progress_includes_source_file(tmp_path: Path) -> None:
    path = tmp_path / "petstore.json"
    path.write_text('{"openapi":"3.1.0"}', encoding="utf-8")
    message = format_document_import_progress(
        document_label="OpenAPI",
        source=str(path),
        dry_run=False,
        target_label="Pet Store @ 1.0.0 (pet-store/1.0.0)",
    )
    assert message == (
        f"Uploading OpenAPI document petstore.json ({path.stat().st_size} bytes) for "
        "Pet Store @ 1.0.0 (pet-store/1.0.0)…"
    )


def test_source_byte_size_returns_local_file_length(tmp_path: Path) -> None:
    path = tmp_path / "spec.json"
    path.write_bytes(b'{"ok": true}')
    assert source_byte_size(str(path)) == path.stat().st_size
    assert source_byte_size("-") is None
    assert source_byte_size("https://example.com/openapi.json") is None


def test_suffix_from_source_url_with_query() -> None:
    assert (
        suffix_from_source("https://example.com/openapi.json?version=2")
        == ".json"
    )


def test_load_openapi_file_from_url(httpx_mock: object) -> None:
    url = "https://example.com/openapi.json"
    httpx_mock.add_response(url=url, text=_OPENAPI_JSON)

    spec = load_openapi_file(url)

    assert spec["info"]["title"] == "Remote API"


def test_load_openapi_file_from_url_http_error_exits_oserror(httpx_mock: object) -> None:
    url = "https://example.com/missing.json"
    httpx_mock.add_response(url=url, status_code=404)

    with pytest.raises(OSError, match="HTTP 404"):
        load_openapi_file(url)


def test_load_openapi_file_from_url_without_suffix_uses_json(
    httpx_mock: object,
) -> None:
    url = "https://example.com/openapi"
    httpx_mock.add_response(url=url, text=_OPENAPI_JSON)

    spec = load_openapi_file(url)

    assert spec["openapi"] == "3.1.0"


def test_load_openapi_file_from_url_content_type_yaml(httpx_mock: object) -> None:
    url = "https://example.com/openapi"
    httpx_mock.add_response(
        url=url,
        text='openapi: "3.1.0"\ninfo:\n  title: YAML API\n  version: "1.0.0"\npaths: {}\n',
        headers={"content-type": "application/yaml"},
    )

    spec = load_openapi_file(url)

    assert spec["info"]["title"] == "YAML API"


def test_load_document_bytes_local_file_returns_raw(tmp_path: Path) -> None:
    document = tmp_path / "schema.graphql"
    document.write_bytes(b"type Query { ping: String }")

    raw, filename = load_document_bytes(str(document))

    assert raw == b"type Query { ping: String }"
    assert filename == "schema.graphql"


def test_load_document_bytes_from_url(httpx_mock: object) -> None:
    url = "https://example.com/api.proto"
    httpx_mock.add_response(url=url, content=b"syntax = \"proto3\";")

    raw, filename = load_document_bytes(url)

    assert raw == b'syntax = "proto3";'
    assert filename == "api.proto"


def test_load_document_bytes_url_http_error_raises_oserror(httpx_mock: object) -> None:
    url = "https://example.com/missing.proto"
    httpx_mock.add_response(url=url, status_code=404)

    with pytest.raises(OSError, match="HTTP 404"):
        load_document_bytes(url)


def test_read_document_text_local_file(tmp_path: Path) -> None:
    path = tmp_path / "spec.json"
    path.write_text('{"ok": true}', encoding="utf-8")

    text, suffix = read_document_text(str(path))

    assert text == '{"ok": true}'
    assert suffix == ".json"


def test_load_json_schema_file_from_url(httpx_mock: object) -> None:
    url = "https://example.com/email.json"
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "string",
        "title": "Email",
    }
    httpx_mock.add_response(url=url, text=json.dumps(schema))

    document = load_json_schema_file(url)

    assert document["title"] == "Email"
