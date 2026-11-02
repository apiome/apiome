"""Tests for ``apiome import avro`` and its ``--registry`` intake (MFI-12.6, #3787).

``--registry`` reads one schema from a Confluent-compatible schema registry's raw-schema route —
by subject (named outright, or from a topic / record under a subject naming strategy) and version,
or by global schema id — and imports it through the registry-dispatch import, against a mocked REST
service and a mocked registry.

The committed ``.avsc`` and ``.avdl`` fixtures are imported both ways — as a file and read from a
registry — so each Avro surface is proven to reach the server verbatim under ``source_kind: avro``.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apiome_cli.import_.avro_registry import avro_registry_schema_url, avro_subject_name
from apiome_cli.main import app
from helpers import strip_ansi

runner = CliRunner()

_FIXTURES = Path(__file__).parent / "fixtures"
#: The committed Avro fixtures (MFI-12.6), one per Avro surface the importer reads.
_SURFACE_FIXTURES = [
    pytest.param("orders-avro.avsc", id="avsc"),
    pytest.param("orders-avro.avdl", id="avdl"),
]
_SCHEMA = (_FIXTURES / "orders-avro.avsc").read_text(encoding="utf-8")
_REGISTRY = "https://registry.example.com:8081"
_SOURCES_URL = "http://localhost:8000/v1/import/sources"
_IMPORT_URL = "http://localhost:8000/v1/tenants/acme-corp/imports"
_JOB_ID = "cdcdcdcd-cdcd-4dcd-8dcd-cdcdcdcdcdcd"
_JOB_URL = f"http://localhost:8000/v1/tenants/acme-corp/imports/{_JOB_ID}"

_AVRO = {
    "key": "avro",
    "label": "Avro",
    "description": "Import an Apache Avro schema (.avsc) or Avro IDL protocol (.avdl) as a catalog source.",
    "icon": "binary",
    "paradigm": "data_schema",
    "input_kinds": ["file", "url", "paste", "fileset"],
    "supports_live_discovery": False,
    "formats": ["avro", "avsc", "avro-idl"],
    "file_extensions": [".avsc", ".avro", ".avdl", ".zip", ".tar.gz", ".tgz", ".tar"],
}


@pytest.fixture(autouse=True)
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tier-2 import commands require an API key and tenant scope."""
    monkeypatch.setenv("APIOME_API_KEY", "test-import-key")
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def _mock_import(httpx_mock: object) -> None:
    httpx_mock.add_response(url=_SOURCES_URL, method="GET", json={"sources": [_AVRO]})  # type: ignore[attr-defined]
    httpx_mock.add_response(  # type: ignore[attr-defined]
        url=_IMPORT_URL, method="POST", status_code=202, json={"job_id": _JOB_ID, "state": "pending"}
    )
    httpx_mock.add_response(  # type: ignore[attr-defined]
        url=_JOB_URL,
        method="GET",
        json={
            "state": "completed",
            "job_id": _JOB_ID,
            "summary": {
                "source": "avro",
                "paradigm": "data_schema",
                "format": "avro",
                "fingerprint": "sha256:avro",
                "counts": {"services": 0, "operations": 0, "types": 2, "channels": 0},
                "lint": {"score": 95, "grade": "A", "report_fingerprint": "fp", "findings": 0, "severity_counts": {}},
                "dry_run": False,
                "incremental_mode": False,
                "persisted": False,
            },
        },
    )


def _mock_registry(httpx_mock: object, url: str, text: str = _SCHEMA) -> None:
    httpx_mock.add_response(  # type: ignore[attr-defined]
        url=url,
        method="GET",
        text=text,
        headers={"Content-Type": "application/vnd.schemaregistry.v1+json"},
    )


def _post_body(httpx_mock: object) -> dict:
    for request in httpx_mock.get_requests():  # type: ignore[attr-defined]
        if request.method == "POST" and str(request.url) == _IMPORT_URL:
            return json.loads(request.content.decode("utf-8"))
    raise AssertionError("no spec-import POST recorded")


# --- subject naming strategies ---------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs, expected",
    [
        ({"subject": "orders-value"}, "orders-value"),
        ({"topic": "orders"}, "orders-value"),
        ({"topic": "orders", "key": True}, "orders-key"),
        ({"topic": "orders", "strategy": "topic"}, "orders-value"),
        ({"record": "com.example.orders.Order", "strategy": "record"}, "com.example.orders.Order"),
        (
            {"topic": "orders", "record": "com.example.orders.Order", "strategy": "topic_record"},
            "orders-com.example.orders.Order",
        ),
        ({"topic": "orders", "strategy": "TOPIC"}, "orders-value"),
    ],
)
def test_avro_subject_name(kwargs: dict, expected: str) -> None:
    assert avro_subject_name(**kwargs) == expected


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({}, "Name the subject"),
        ({"topic": "orders", "strategy": "wire"}, "--strategy must be one of"),
        ({"subject": "orders-value", "topic": "orders"}, "--subject names the subject itself"),
        ({"strategy": "record"}, "needs --record"),
        ({"record": "com.x.R", "strategy": "record", "topic": "orders"}, "drop --topic"),
        ({"record": "com.x.R", "strategy": "topic_record"}, "needs --topic"),
        ({"topic": "orders", "record": "com.x.R"}, "--record applies to"),
        ({"record": "com.x.R", "strategy": "record", "key": True}, "--key applies to the topic strategy"),
    ],
)
def test_avro_subject_name_refuses_bad_input(kwargs: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        avro_subject_name(**kwargs)


# --- registry URLs ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "registry, kwargs, expected",
    [
        (_REGISTRY, {"subject": "orders-value"}, f"{_REGISTRY}/subjects/orders-value/versions/latest/schema"),
        (f"{_REGISTRY}/", {"subject": "orders-value", "version": "3"}, f"{_REGISTRY}/subjects/orders-value/versions/3/schema"),
        (_REGISTRY, {"subject": "orders-value", "version": "-1"}, f"{_REGISTRY}/subjects/orders-value/versions/latest/schema"),
        (_REGISTRY, {"subject": "a:b/c"}, f"{_REGISTRY}/subjects/a%3Ab%2Fc/versions/latest/schema"),
        (_REGISTRY, {"schema_id": 42}, f"{_REGISTRY}/schemas/ids/42/schema"),
        (
            "HTTPS://host/apis/ccompat/v7?tenant=a",
            {"subject": "s"},
            "https://host/apis/ccompat/v7/subjects/s/versions/latest/schema?tenant=a",
        ),
    ],
)
def test_avro_registry_schema_url(registry: str, kwargs: dict, expected: str) -> None:
    assert avro_registry_schema_url(registry, **kwargs) == expected


@pytest.mark.parametrize(
    "registry, kwargs",
    [
        ("", {"subject": "s"}),
        ("ftp://registry/", {"subject": "s"}),
        ("https:///nohost", {"subject": "s"}),
        (_REGISTRY, {}),
        (_REGISTRY, {"subject": "s", "schema_id": 1}),
        (_REGISTRY, {"subject": "s", "version": "0"}),
        (_REGISTRY, {"subject": "s", "version": "newest"}),
        (_REGISTRY, {"schema_id": 0}),
        (_REGISTRY, {"schema_id": 4, "version": "1"}),
    ],
)
def test_avro_registry_schema_url_refuses_unusable_input(registry: str, kwargs: dict) -> None:
    with pytest.raises(ValueError):
        avro_registry_schema_url(registry, **kwargs)


# --- the command -----------------------------------------------------------------------------


def test_registry_imports_a_subjects_latest_schema(httpx_mock: object) -> None:
    _mock_import(httpx_mock)
    schema_url = f"{_REGISTRY}/subjects/orders-value/versions/latest/schema"
    _mock_registry(httpx_mock, schema_url)
    result = runner.invoke(app, ["import", "avro", "--registry", _REGISTRY, "--subject", "orders-value"])
    assert result.exit_code == 0, result.output

    body = _post_body(httpx_mock)
    assert body["metadata"]["source_kind"] == "avro"
    assert base64.b64decode(body["document_base64"]).decode("utf-8") == _SCHEMA
    assert f"Discovered Avro schema (subject orders-value) at {schema_url}" in strip_ansi(result.output)


def test_registry_names_the_subject_by_strategy(httpx_mock: object) -> None:
    _mock_import(httpx_mock)
    _mock_registry(httpx_mock, f"{_REGISTRY}/subjects/orders-com.example.orders.Order/versions/2/schema")
    result = runner.invoke(
        app,
        [
            "import",
            "avro",
            "--registry",
            _REGISTRY,
            "--topic",
            "orders",
            "--record",
            "com.example.orders.Order",
            "--strategy",
            "topic_record",
            "--version",
            "2",
        ],
    )
    assert result.exit_code == 0, result.output
    assert base64.b64decode(_post_body(httpx_mock)["document_base64"]).decode("utf-8") == _SCHEMA


def test_registry_imports_a_key_schema_from_a_topic(httpx_mock: object) -> None:
    _mock_import(httpx_mock)
    _mock_registry(httpx_mock, f"{_REGISTRY}/subjects/orders-key/versions/latest/schema", '"string"')
    result = runner.invoke(app, ["import", "avro", "--registry", _REGISTRY, "--topic", "orders", "--key"])
    assert result.exit_code == 0, result.output
    assert base64.b64decode(_post_body(httpx_mock)["document_base64"]).decode("utf-8") == '"string"'


def test_registry_imports_by_schema_id(httpx_mock: object) -> None:
    _mock_import(httpx_mock)
    _mock_registry(httpx_mock, f"{_REGISTRY}/schemas/ids/7/schema")
    result = runner.invoke(app, ["import", "avro", "--registry", _REGISTRY, "--schema-id", "7"])
    assert result.exit_code == 0, result.output
    assert "Discovered Avro schema (schema id 7)" in strip_ansi(result.output)


def test_registry_is_the_only_input() -> None:
    result = runner.invoke(
        app, ["import", "avro", "x.avsc", "--registry", _REGISTRY, "--subject", "orders-value"]
    )
    assert result.exit_code != 0
    assert "Provide only one input: --registry" in strip_ansi(result.output)


@pytest.mark.parametrize(
    "args",
    [
        ["--subject", "orders-value"],
        ["--topic", "orders"],
        ["--schema-id", "3"],
        ["--key"],
    ],
)
def test_registry_options_need_registry(args: list[str]) -> None:
    result = runner.invoke(app, ["import", "avro", "x.avsc", *args])
    assert result.exit_code != 0
    assert "need --registry" in strip_ansi(result.output)


@pytest.mark.parametrize(
    "args, message",
    [
        ([], "Name the subject"),
        (["--subject", "s", "--schema-id", "3"], "Name exactly one schema"),
        (["--topic", "orders", "--strategy", "record"], "needs --record"),
        (["--subject", "s", "--version", "0"], "--version must be latest or a positive number"),
    ],
)
def test_registry_refuses_bad_naming(args: list[str], message: str) -> None:
    result = runner.invoke(app, ["import", "avro", "--registry", _REGISTRY, *args])
    assert result.exit_code != 0
    assert message in strip_ansi(result.output)


def test_registry_refuses_a_bad_url() -> None:
    result = runner.invoke(app, ["import", "avro", "--registry", "ftp://registry", "--subject", "s"])
    assert result.exit_code != 0
    assert "http or https" in strip_ansi(result.output)


@pytest.mark.parametrize("fixture", _SURFACE_FIXTURES)
def test_a_surface_fixture_file_imports_verbatim(httpx_mock: object, fixture: str) -> None:
    _mock_import(httpx_mock)
    path = _FIXTURES / fixture
    result = runner.invoke(app, ["import", "avro", str(path)])
    assert result.exit_code == 0, result.output

    body = _post_body(httpx_mock)
    assert body["metadata"]["source_kind"] == "avro"
    assert base64.b64decode(body["document_base64"]) == path.read_bytes()


def test_the_avsc_fixture_is_read_from_a_registry_verbatim(httpx_mock: object) -> None:
    _mock_import(httpx_mock)
    _mock_registry(httpx_mock, f"{_REGISTRY}/subjects/com.example.orders.Order/versions/latest/schema")
    result = runner.invoke(
        app,
        ["import", "avro", "--registry", _REGISTRY, "--strategy", "record", "--record", "com.example.orders.Order"],
    )
    assert result.exit_code == 0, result.output
    assert base64.b64decode(_post_body(httpx_mock)["document_base64"]).decode("utf-8") == _SCHEMA


@pytest.mark.parametrize(
    "fixture, marker",
    [
        ("orders-avro.avsc", '"type": "record"'),
        ("orders-avro.avdl", "protocol OrderService"),
    ],
)
def test_the_surface_fixtures_are_the_surface_they_claim(fixture: str, marker: str) -> None:
    assert marker in (_FIXTURES / fixture).read_text(encoding="utf-8")
