"""Tests for ``apiome registry subjects|versions|register|compat|config`` (CDG-4.5 / #5977)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from apiome_cli.client.schema_registry import (
    normalize_choice,
    refusal_message,
    schema_type_for,
    subject_rows,
    version_rows,
)
from apiome_cli.exit_codes import EXIT_ERROR, EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app

runner = CliRunner()

_BASE = "http://localhost:8000/v1/tenants/acme-corp/schema-registry"
_CONFLUENT = "http://localhost:8000/registry/schema/acme-corp"

_SUBJECT = {
    "name": "orders-value",
    "strategy": "topic",
    "compatibilityLevel": None,
    "effectiveCompatibilityLevel": "BACKWARD",
    "mode": "READWRITE",
    "projectId": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    "versionCount": 2,
    "latestVersion": 2,
    "createdAt": "2026-10-19T10:00:00Z",
    "updatedAt": "2026-10-19T10:00:00Z",
}

_VERSION = {
    "subject": "orders-value",
    "version": 1,
    "id": 7,
    "schemaType": "AVRO",
    "fingerprint": "sha256:abc",
    "references": [],
    "projectId": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    "versionRecordId": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    "createdAt": "2026-10-19T10:00:00Z",
}

_AVRO = '{"type":"record","name":"Order","namespace":"acme","fields":[{"name":"id","type":"string"}]}'


@pytest.fixture(autouse=True)
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


@pytest.fixture
def avro_file(tmp_path: Path) -> Path:
    path = tmp_path / "order.avsc"
    path.write_text(_AVRO, encoding="utf-8")
    return path


def _sent(httpx_mock: object) -> dict:
    """The JSON body of the last request the CLI sent."""
    return json.loads(httpx_mock.get_requests()[-1].content)


# --------------------------------------------------------------------------- helpers


def test_schema_type_follows_the_extension_unless_type_is_given() -> None:
    assert schema_type_for(Path("a.avsc"), None) == "AVRO"
    assert schema_type_for(Path("a.JSON"), None) == "JSON"
    assert schema_type_for(Path("a.proto"), None) == "PROTOBUF"
    assert schema_type_for(Path("a.txt"), None) is None
    assert schema_type_for(Path("a.txt"), "json") == "JSON"


def test_normalize_choice_upper_cases_and_validates() -> None:
    assert normalize_choice(None, ("NONE",)) == (None, True)
    assert normalize_choice(" none ", ("NONE",)) == ("NONE", True)
    assert normalize_choice("bogus", ("NONE",)) == ("BOGUS", False)
    assert normalize_choice("Topic", ("topic",), upper=False) == ("topic", True)


def test_subject_rows_mark_the_tenant_default() -> None:
    rows = subject_rows({"subjects": [_SUBJECT, {**_SUBJECT, "compatibilityLevel": "NONE",
                                                 "effectiveCompatibilityLevel": "NONE"}]})
    assert rows[0]["level"] == "BACKWARD (default)"
    assert rows[1]["level"] == "NONE"
    assert rows[0]["versions"] == 2


def test_version_rows() -> None:
    assert version_rows({"versions": [_VERSION]}) == [
        {"version": 1, "id": 7, "type": "AVRO", "revision": _VERSION["versionRecordId"],
         "created": "2026-10-19T10:00:00Z"}
    ]


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"error_code": 42290, "message": "no rules"}, ("no rules", 42290)),
        ({"detail": {"code": "subject-not-found", "message": "gone"}}, ("gone", "subject-not-found")),
        ({"detail": "Forbidden"}, ("Forbidden", None)),
        ({"message": "plain", "code": 409}, ("plain", 409)),
        ([], ("HTTP 422", None)),
    ],
)
def test_refusal_message_reads_both_error_shapes(body: object, expected: tuple) -> None:
    assert refusal_message(httpx.Response(422, json=body)) == expected


# --------------------------------------------------------------------------- subjects / versions


def test_subjects_lists_the_table(httpx_mock: object) -> None:
    httpx_mock.add_response(url=f"{_BASE}/subjects", json={"subjects": [_SUBJECT]})
    result = runner.invoke(app, ["registry", "subjects"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "orders-value" in result.stdout
    assert "BACKWARD (default)" in result.stdout


def test_subjects_empty_prints_the_next_step(httpx_mock: object) -> None:
    httpx_mock.add_response(url=f"{_BASE}/subjects", json={"subjects": []})
    result = runner.invoke(app, ["registry", "subjects"])
    assert result.exit_code == EXIT_SUCCESS
    assert "apiome registry register" in result.stdout


def test_subjects_json(httpx_mock: object) -> None:
    httpx_mock.add_response(url=f"{_BASE}/subjects", json={"subjects": [_SUBJECT]})
    result = runner.invoke(app, ["--json", "registry", "subjects"])
    assert json.loads(result.stdout)["subjects"][0]["name"] == "orders-value"


def test_versions_lists_a_subject(httpx_mock: object) -> None:
    httpx_mock.add_response(
        url=f"{_BASE}/subjects/orders-value/versions", json={"subject": "orders-value", "versions": [_VERSION]}
    )
    result = runner.invoke(app, ["registry", "versions", "orders-value"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "AVRO" in result.stdout


def test_versions_one_prints_the_schema(httpx_mock: object) -> None:
    httpx_mock.add_response(
        url=f"{_BASE}/subjects/orders-value/versions/latest", json={**_VERSION, "schema": _AVRO}
    )
    result = runner.invoke(app, ["registry", "versions", "orders-value", "--version", "latest"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert '"name":"Order"' in result.stdout


def test_subject_names_are_url_quoted(httpx_mock: object) -> None:
    httpx_mock.add_response(
        url=f"{_BASE}/subjects/orders%2Fv1/versions", json={"subject": "orders/v1", "versions": []}
    )
    result = runner.invoke(app, ["registry", "versions", "orders/v1"])
    assert result.exit_code == EXIT_SUCCESS, result.output


def test_unknown_subject_exits_usage(httpx_mock: object) -> None:
    httpx_mock.add_response(
        url=f"{_BASE}/subjects/nope/versions",
        status_code=404,
        json={"detail": {"code": "subject-not-found", "message": "Subject 'nope' not found."}},
    )
    result = runner.invoke(app, ["registry", "versions", "nope"])
    assert result.exit_code == EXIT_USAGE
    assert "Subject 'nope' not found." in result.stderr


# --------------------------------------------------------------------------- register


def test_register_sends_the_schema_and_type(httpx_mock: object, avro_file: Path) -> None:
    httpx_mock.add_response(
        url=f"{_BASE}/subjects/orders-value/versions", method="POST", json={**_VERSION, "created": True}
    )
    result = runner.invoke(app, ["registry", "register", "orders-value", str(avro_file), "--strategy", "topic"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "Registered: orders-value version 1 (schema id 7)." in result.stdout
    assert _sent(httpx_mock) == {"schema": _AVRO, "schemaType": "AVRO", "strategy": "topic"}


def test_register_again_says_already_registered(httpx_mock: object, avro_file: Path) -> None:
    httpx_mock.add_response(
        url=f"{_BASE}/subjects/orders-value/versions", method="POST", json={**_VERSION, "created": False}
    )
    result = runner.invoke(app, ["registry", "register", "orders-value", str(avro_file)])
    assert "Already registered" in result.stdout


def test_register_needs_a_type_for_an_unknown_extension(tmp_path: Path) -> None:
    path = tmp_path / "schema.txt"
    path.write_text(_AVRO, encoding="utf-8")
    result = runner.invoke(app, ["registry", "register", "orders-value", str(path)])
    assert result.exit_code == EXIT_USAGE
    assert "--type" in result.output


def test_register_rejects_a_bad_type(avro_file: Path) -> None:
    result = runner.invoke(app, ["registry", "register", "s", str(avro_file), "--type", "XML"])
    assert result.exit_code == EXIT_USAGE


def test_register_missing_file(tmp_path: Path) -> None:
    result = runner.invoke(app, ["registry", "register", "s", str(tmp_path / "gone.avsc")])
    assert result.exit_code == EXIT_USAGE
    assert "cannot read" in result.output


def test_register_refused_for_compatibility_prints_the_hint(httpx_mock: object, avro_file: Path) -> None:
    httpx_mock.add_response(
        url=f"{_BASE}/subjects/orders-value/versions",
        method="POST",
        status_code=422,
        json={"detail": {"code": "compatibility-rules-unavailable", "message": "No rules yet."}},
    )
    result = runner.invoke(app, ["registry", "register", "orders-value", str(avro_file)])
    assert result.exit_code == EXIT_USAGE
    assert "No rules yet." in result.stderr
    assert "--level NONE" in result.stderr


def test_register_other_refusal_prints_no_hint(httpx_mock: object, avro_file: Path) -> None:
    httpx_mock.add_response(
        url=f"{_BASE}/subjects/orders-value/versions",
        method="POST",
        status_code=422,
        json={"detail": {"code": "schema-invalid", "message": "Invalid AVRO schema"}},
    )
    result = runner.invoke(app, ["registry", "register", "orders-value", str(avro_file)])
    assert "Invalid AVRO schema" in result.stderr
    assert "--level NONE" not in result.stderr


# --------------------------------------------------------------------------- compat


def test_compat_compatible_exits_zero(httpx_mock: object, avro_file: Path) -> None:
    httpx_mock.add_response(
        url=f"{_CONFLUENT}/compatibility/subjects/orders-value/versions",
        method="POST",
        json={"is_compatible": True, "messages": []},
    )
    result = runner.invoke(app, ["registry", "compat", "orders-value", str(avro_file)])
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "orders-value: compatible" in result.stdout
    assert _sent(httpx_mock) == {"schema": _AVRO, "schemaType": "AVRO"}


def test_compat_against_one_version(httpx_mock: object, avro_file: Path) -> None:
    httpx_mock.add_response(
        url=f"{_CONFLUENT}/compatibility/subjects/orders-value/versions/2",
        method="POST",
        json={"is_compatible": True, "messages": []},
    )
    result = runner.invoke(app, ["registry", "compat", "orders-value", str(avro_file), "--version", "2"])
    assert result.exit_code == EXIT_SUCCESS, result.output


def test_compat_incompatible_exits_one(httpx_mock: object, avro_file: Path) -> None:
    httpx_mock.add_response(
        url=f"{_CONFLUENT}/compatibility/subjects/orders-value/versions",
        method="POST",
        json={"is_compatible": False, "messages": ["field id removed"]},
    )
    result = runner.invoke(app, ["registry", "compat", "orders-value", str(avro_file)])
    assert result.exit_code == EXIT_ERROR
    assert "NOT compatible" in result.stdout
    assert "field id removed" in result.stdout


def test_compat_rules_unavailable_exits_usage_with_hint(httpx_mock: object, avro_file: Path) -> None:
    httpx_mock.add_response(
        url=f"{_CONFLUENT}/compatibility/subjects/orders-value/versions",
        method="POST",
        status_code=422,
        json={"error_code": 42290, "message": "Compatibility level BACKWARD needs AVRO rules."},
    )
    result = runner.invoke(app, ["registry", "compat", "orders-value", str(avro_file)])
    assert result.exit_code == EXIT_USAGE
    assert "needs AVRO rules" in result.stderr
    assert "--level NONE" in result.stderr


# --------------------------------------------------------------------------- config


def test_config_reads_the_tenant_defaults(httpx_mock: object) -> None:
    httpx_mock.add_response(url=f"{_BASE}/config", json={"compatibilityLevel": "BACKWARD", "mode": "READWRITE"})
    result = runner.invoke(app, ["registry", "config"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "BACKWARD" in result.stdout


def test_config_changes_the_tenant_defaults(httpx_mock: object) -> None:
    httpx_mock.add_response(
        url=f"{_BASE}/config", method="PUT", json={"compatibilityLevel": "NONE", "mode": "READONLY"}
    )
    result = runner.invoke(app, ["registry", "config", "--level", "none", "--mode", "readonly"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert _sent(httpx_mock) == {"compatibilityLevel": "NONE", "mode": "READONLY"}


def test_config_changes_one_subject(httpx_mock: object) -> None:
    httpx_mock.add_response(url=f"{_BASE}/subjects/orders-value", method="PUT", json=_SUBJECT)
    result = runner.invoke(app, ["registry", "config", "orders-value", "--strategy", "record"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert _sent(httpx_mock) == {"strategy": "record"}
    assert "(tenant default)" in result.stdout


def test_config_reads_one_subject(httpx_mock: object) -> None:
    httpx_mock.add_response(url=f"{_BASE}/subjects/orders-value", json=_SUBJECT)
    result = runner.invoke(app, ["registry", "config", "orders-value"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "orders-value" in result.stdout


def test_config_rejects_a_bad_level() -> None:
    result = runner.invoke(app, ["registry", "config", "--level", "SIDEWAYS"])
    assert result.exit_code == EXIT_USAGE


def test_config_strategy_needs_a_subject() -> None:
    result = runner.invoke(app, ["registry", "config", "--strategy", "topic"])
    assert result.exit_code == EXIT_USAGE
    assert "subject" in result.output
