"""``apiome data create --class <project>/<version>/<Class>`` (CLI 10.3, #3255).

The rules (:mod:`apiome_cli.data_record`) and the command against a mocked REST API: the class
address, ``--field`` parsing, the three input modes reaching the same POST body, the class lookup
(``GET /v1/data/{tenant}/classes``), local validation (exit 7 with field-level errors),
``--dry-run``, ``--json`` and the usage errors (exit 2).
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from apiome_cli.data_record import (
    RECORD_FIELD,
    ClassAddress,
    DataInputError,
    SchemaUnusable,
    build_payload,
    find_class,
    parse_class_address,
    parse_field,
    render_created,
    render_valid,
    validate_record,
)
from apiome_cli.exit_codes import EXIT_RECORD_INVALID, EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app
from apiome_cli.property_create import FieldError

runner = CliRunner()

_ENV = {
    "APIOME_API_KEY": "obj_test_key",
    "APIOME_BASE_URL": "http://localhost:8000",
    "APIOME_TENANT_ID": "acme",
}
_CLASSES = "http://localhost:8000/v1/data/acme/classes?project=billing&version=1.0.0"
_RECORDS = "http://localhost:8000/v1/data/acme/records"
_CLASS_SCHEMA_ID = "33333333-3333-3333-3333-333333333333"

_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://apiome.dev/acme/billing/1.0.0/Charge.json",
    "type": "object",
    "properties": {
        "amount": {"type": "number", "minimum": 0},
        "currency": {"type": "string", "enum": ["USD", "EUR"]},
        "customer_id": {"type": "string"},
        "email": {"type": "string", "format": "email"},
    },
    "required": ["amount", "currency"],
}
_CHARGE = {"class_schema_id": _CLASS_SCHEMA_ID, "class_id": "c-1", "class_name": "Charge", "schema": _SCHEMA}
_REFUND = {"class_schema_id": "r-1", "class_id": "c-2", "class_name": "Refund", "schema": {"type": "object"}}
_LOOKUP = {"success": True, "project": "billing", "version": "1.0.0", "published": True, "classes": [_CHARGE, _REFUND]}
_RECORD = {"amount": 19.99, "currency": "USD", "customer_id": "cu_1"}


def _invoke(*args: str, input: str | None = None):
    return runner.invoke(app, ["data", "create", "--class", "billing/1.0.0/Charge", *args], env=_ENV, input=input)


def _posted(httpx_mock) -> list[dict]:
    return [json.loads(r.content) for r in httpx_mock.get_requests() if str(r.url) == _RECORDS]


# ---- rules: the class address ---------------------------------------------------------------------


def test_parse_class_address() -> None:
    assert parse_class_address(" billing/v1.0.0/Charge ") == ClassAddress("billing", "v1.0.0", "Charge")
    assert str(ClassAddress("billing", "1.0.0", "Charge")) == "billing/1.0.0/Charge"


@pytest.mark.parametrize("text", ["Charge", "billing/Charge", "billing//Charge", "a/b/c/d", "/1.0.0/Charge"])
def test_parse_class_address_needs_three_segments(text: str) -> None:
    with pytest.raises(DataInputError, match="<project>/<version>/<Class>"):
        parse_class_address(text)


# ---- rules: --field and the payload ---------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("currency=USD", ("currency", "USD")),
        ("note=", ("note", "")),
        ("expr=a=b", ("expr", "a=b")),
        ("amount=:19.99", ("amount", 19.99)),
        ("active=:true", ("active", True)),
        ("tags=:[\"a\",\"b\"]", ("tags", ["a", "b"])),
        ("meta=:{\"k\":1}", ("meta", {"k": 1})),
        ("note=:null", ("note", None)),
        ("code=:\"007\"", ("code", "007")),
        (" currency =USD", ("currency", "USD")),
    ],
)
def test_parse_field(text: str, expected) -> None:
    assert parse_field(text) == expected


@pytest.mark.parametrize("text, message", [("currency", "key=value"), ("=USD", "key=value"), ("amount=:1.", "not valid JSON")])
def test_parse_field_refuses(text: str, message: str) -> None:
    with pytest.raises(DataInputError, match=message):
        parse_field(text)


def test_build_payload_applies_fields_on_top_of_the_document() -> None:
    document = {"amount": 1, "currency": "EUR"}
    payload = build_payload(document, ["currency=USD", "amount=:2", "amount=:3"])
    assert payload == {"amount": 3, "currency": "USD"}
    assert document == {"amount": 1, "currency": "EUR"}


def test_build_payload_from_fields_only() -> None:
    assert build_payload(None, ["amount=:1.0", "currency=USD"]) == {"amount": 1.0, "currency": "USD"}


# ---- rules: the class ----------------------------------------------------------------------------


def test_find_class_exact_then_case_insensitive() -> None:
    assert find_class([_CHARGE, _REFUND], "Charge") is _CHARGE
    assert find_class([_CHARGE, _REFUND], "refund") is _REFUND


def test_find_class_lists_the_classes_when_missing() -> None:
    with pytest.raises(DataInputError, match=r"No class 'Invoice' in this version\. Classes: Charge, Refund\."):
        find_class([_REFUND, _CHARGE], "Invoice")


def test_find_class_refuses_a_name_only_matching_several_by_case() -> None:
    rows = [{**_CHARGE, "class_name": "Item"}, {**_CHARGE, "class_name": "ITEM"}]
    with pytest.raises(DataInputError):
        find_class(rows, "item")


# ---- rules: validation ---------------------------------------------------------------------------


def test_a_valid_record_has_no_problems() -> None:
    assert validate_record(_SCHEMA, _RECORD) == []


def test_validation_reports_each_field() -> None:
    problems = validate_record(_SCHEMA, {"amount": -1, "email": "not-an-email"})
    assert problems == [
        FieldError("amount", "-1 is less than the minimum of 0"),
        FieldError("currency", "is required"),
        FieldError("email", "'not-an-email' is not a 'email'"),
    ]


def test_validation_names_nested_fields_and_the_record_itself() -> None:
    schema = {
        "type": "object",
        "properties": {"address": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["zip"]}},
        "additionalProperties": False,
    }
    problems = validate_record(schema, {"address": {"city": 3}, "extra": 1})
    assert [str(p) for p in problems] == [
        "(record): Additional properties are not allowed ('extra' was unexpected)",
        "address/city: 3 is not of type 'string'",
        "address/zip: is required",
    ]
    assert problems[0].field == RECORD_FIELD


def test_an_unresolvable_ref_makes_the_schema_unusable() -> None:
    schema = {"type": "object", "properties": {"id": {"$ref": "https://apiome.dev/types/acme/id.json"}}}
    with pytest.raises(SchemaUnusable, match=r"\$ref that cannot be resolved"):
        validate_record(schema, {"id": "x"})


def test_an_invalid_schema_is_unusable() -> None:
    with pytest.raises(SchemaUnusable, match="not valid JSON Schema"):
        validate_record({"type": 12}, {})


def test_render_lines() -> None:
    address = ClassAddress("billing", "1.0.0", "Charge")
    assert render_created("rc_1", address) == "✔ Created rc_1 in billing/1.0.0/Charge."
    assert render_valid(address) == "✔ Valid billing/1.0.0/Charge record. Nothing was created (--dry-run)."


# ---- command: input modes -------------------------------------------------------------------------


def test_create_from_file(httpx_mock, tmp_path) -> None:
    path = tmp_path / "charge.json"
    path.write_text(json.dumps(_RECORD), encoding="utf-8")
    httpx_mock.add_response(url=_CLASSES, json=_LOOKUP)
    httpx_mock.add_response(url=_RECORDS, method="POST", json={"success": True, "record_id": "rc_9b3e"})
    result = _invoke("--from-file", str(path))
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert result.stdout == "✔ Created rc_9b3e in billing/1.0.0/Charge.\n"
    assert _posted(httpx_mock) == [{"class_schema_id": _CLASS_SCHEMA_ID, "data": _RECORD}]
    assert httpx_mock.get_requests()[0].headers["X-API-Key"] == "obj_test_key"


def test_every_input_mode_reaches_the_same_post_body(httpx_mock, tmp_path) -> None:
    yaml_file = tmp_path / "charge.yaml"
    yaml_file.write_text("amount: 19.99\ncurrency: USD\ncustomer_id: cu_1\n", encoding="utf-8")
    for _ in range(3):
        httpx_mock.add_response(url=_CLASSES, json=_LOOKUP)
        httpx_mock.add_response(url=_RECORDS, method="POST", json={"success": True, "record_id": "rc_1"})
    assert _invoke("--from-file", str(yaml_file)).exit_code == EXIT_SUCCESS
    assert _invoke("--stdin", input=json.dumps(_RECORD)).exit_code == EXIT_SUCCESS
    assert _invoke("--field", "amount=:19.99", "--field", "currency=USD", "--field", "customer_id=cu_1").exit_code == 0
    bodies = _posted(httpx_mock)
    assert len(bodies) == 3
    assert bodies[0] == bodies[1] == bodies[2] == {"class_schema_id": _CLASS_SCHEMA_ID, "data": _RECORD}


def test_fields_override_the_file(httpx_mock, tmp_path) -> None:
    path = tmp_path / "charge.json"
    path.write_text(json.dumps({**_RECORD, "currency": "EUR"}), encoding="utf-8")
    httpx_mock.add_response(url=_CLASSES, json=_LOOKUP)
    httpx_mock.add_response(url=_RECORDS, method="POST", json={"success": True, "record_id": "rc_1"})
    assert _invoke("--from-file", str(path), "--field", "currency=USD").exit_code == EXIT_SUCCESS
    assert _posted(httpx_mock)[0]["data"]["currency"] == "USD"


def test_a_v_prefixed_version_is_sent_as_written(httpx_mock) -> None:
    httpx_mock.add_response(
        url="http://localhost:8000/v1/data/acme/classes?project=billing&version=v1.0.0", json=_LOOKUP
    )
    httpx_mock.add_response(url=_RECORDS, method="POST", json={"success": True, "record_id": "rc_1"})
    result = runner.invoke(
        app, ["data", "create", "--class", "billing/v1.0.0/Charge", "--field", "amount=:1", "--field", "currency=USD"], env=_ENV
    )
    assert result.exit_code == EXIT_SUCCESS, result.output


# ---- command: validation, --dry-run, --json -------------------------------------------------------


def test_an_invalid_record_exits_7_with_field_errors_and_sends_nothing(httpx_mock) -> None:
    httpx_mock.add_response(url=_CLASSES, json=_LOOKUP)
    result = _invoke("--field", "amount=:-5")
    assert result.exit_code == EXIT_RECORD_INVALID
    assert result.stderr == "amount: -5 is less than the minimum of 0\ncurrency: is required\nNothing was created.\n"
    assert _posted(httpx_mock) == []


def test_a_string_where_a_number_belongs_is_caught(httpx_mock) -> None:
    httpx_mock.add_response(url=_CLASSES, json=_LOOKUP)
    result = _invoke("--field", "amount=19.99", "--field", "currency=USD")
    assert result.exit_code == EXIT_RECORD_INVALID
    assert "amount: '19.99' is not of type 'number'" in result.stderr


def test_dry_run_validates_without_posting(httpx_mock) -> None:
    httpx_mock.add_response(url=_CLASSES, json=_LOOKUP)
    result = _invoke("--stdin", "--dry-run", input=json.dumps(_RECORD))
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert result.stdout == "✔ Valid billing/1.0.0/Charge record. Nothing was created (--dry-run).\n"
    assert _posted(httpx_mock) == []


def test_dry_run_still_fails_an_invalid_record(httpx_mock) -> None:
    httpx_mock.add_response(url=_CLASSES, json=_LOOKUP)
    result = _invoke("--field", "currency=GBP", "--field", "amount=:1", "--dry-run")
    assert result.exit_code == EXIT_RECORD_INVALID
    assert "currency: 'GBP' is not one of ['USD', 'EUR']" in result.stderr


@pytest.mark.parametrize("global_flag", [True, False])
def test_json_prints_the_created_record(httpx_mock, global_flag: bool) -> None:
    httpx_mock.add_response(url=_CLASSES, json=_LOOKUP)
    httpx_mock.add_response(url=_RECORDS, method="POST", json={"success": True, "record_id": "rc_9b3e"})
    argv = ["data", "create", "--class", "billing/1.0.0/Charge", "--stdin"]
    argv = ["--json", *argv] if global_flag else [*argv, "--json"]
    result = runner.invoke(app, argv, env=_ENV, input=json.dumps(_RECORD))
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert json.loads(result.stdout) == {
        "record_id": "rc_9b3e",
        "project": "billing",
        "version": "1.0.0",
        "class": "Charge",
        "class_schema_id": _CLASS_SCHEMA_ID,
        "data": _RECORD,
    }


def test_json_dry_run(httpx_mock) -> None:
    httpx_mock.add_response(url=_CLASSES, json=_LOOKUP)
    result = _invoke("--stdin", "--dry-run", "--json", input=json.dumps(_RECORD))
    assert result.exit_code == EXIT_SUCCESS, result.output
    body = json.loads(result.stdout)
    assert body["valid"] is True and body["dry_run"] is True
    assert "record_id" not in body


def test_a_schema_that_cannot_be_checked_locally_warns_and_still_creates(httpx_mock) -> None:
    schema = {"type": "object", "properties": {"id": {"$ref": "https://apiome.dev/types/acme/id.json"}}}
    httpx_mock.add_response(url=_CLASSES, json={**_LOOKUP, "classes": [{**_CHARGE, "schema": schema}]})
    httpx_mock.add_response(url=_RECORDS, method="POST", json={"success": True, "record_id": "rc_1"})
    result = _invoke("--field", "id=x")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "Warning: billing/1.0.0/Charge was not validated locally" in result.stderr
    assert len(_posted(httpx_mock)) == 1


# ---- command: the class lookup --------------------------------------------------------------------


def test_an_unpublished_version_exits_2(httpx_mock) -> None:
    httpx_mock.add_response(url=_CLASSES, json={**_LOOKUP, "published": False, "classes": []})
    result = _invoke("--field", "amount=:1")
    assert result.exit_code == EXIT_USAGE
    assert "Version billing/1.0.0 is not published" in result.stderr


def test_a_published_version_without_classes_exits_2(httpx_mock) -> None:
    httpx_mock.add_response(url=_CLASSES, json={**_LOOKUP, "classes": []})
    result = _invoke("--field", "amount=:1")
    assert result.exit_code == EXIT_USAGE
    assert "Version billing/1.0.0 has no classes." in result.stderr


def test_an_unknown_class_lists_the_classes(httpx_mock) -> None:
    httpx_mock.add_response(url=_CLASSES, json=_LOOKUP)
    result = runner.invoke(app, ["data", "create", "--class", "billing/1.0.0/Invoice", "--field", "a=b"], env=_ENV)
    assert result.exit_code == EXIT_USAGE
    assert "No class 'Invoice' in this version. Classes: Charge, Refund." in result.stderr


def test_an_unknown_version_is_a_usage_error(httpx_mock) -> None:
    httpx_mock.add_response(url=_CLASSES, status_code=404, json={"detail": "Version billing/1.0.0 not found"})
    result = _invoke("--field", "amount=:1")
    assert result.exit_code == EXIT_USAGE
    assert "not found" in result.stderr


def test_a_server_error_on_create_exits_1(httpx_mock) -> None:
    httpx_mock.add_response(url=_CLASSES, json=_LOOKUP)
    httpx_mock.add_response(url=_RECORDS, method="POST", status_code=500, json={"detail": "boom"})
    result = _invoke("--field", "amount=:1", "--field", "currency=USD")
    assert result.exit_code == 1


# ---- command: usage errors (nothing is called) ----------------------------------------------------


@pytest.mark.parametrize(
    "args, message",
    [
        ([], "Give the record with --from-file <path>, --stdin or --field key=value."),
        (["--field", "currency"], "--field 'currency' must be key=value"),
        (["--field", "amount=:{"], "--field amount: the value after ':' is not valid JSON"),
    ],
)
def test_usage_errors_exit_2(httpx_mock, args, message) -> None:
    result = _invoke(*args)
    assert result.exit_code == EXIT_USAGE
    assert message in result.stderr
    assert httpx_mock.get_requests() == []


def test_a_malformed_class_exits_2(httpx_mock) -> None:
    result = runner.invoke(app, ["data", "create", "--class", "Charge", "--field", "a=b"], env=_ENV)
    assert result.exit_code == EXIT_USAGE
    assert "must be <project>/<version>/<Class>" in result.stderr


def test_from_file_and_stdin_together_exit_2(httpx_mock, tmp_path) -> None:
    path = tmp_path / "charge.json"
    path.write_text("{}", encoding="utf-8")
    result = _invoke("--from-file", str(path), "--stdin", input="{}")
    assert result.exit_code == EXIT_USAGE
    assert "not both" in result.stderr


def test_stdin_from_a_terminal_exits_2(httpx_mock, monkeypatch) -> None:
    monkeypatch.setattr("apiome_cli.terminal.stdin_is_tty", lambda: True)
    result = _invoke("--stdin")
    assert result.exit_code == EXIT_USAGE
    assert "--stdin reads the record from a pipe" in result.stderr


@pytest.mark.parametrize("text, message", [("[1, 2]", "stdin must hold one record object"), ("{a: [", "stdin is not valid JSON or YAML")])
def test_stdin_must_hold_one_object(httpx_mock, text, message) -> None:
    result = _invoke("--stdin", input=text)
    assert result.exit_code == EXIT_USAGE
    assert message in result.stderr


def test_an_unreadable_file_exits_2(httpx_mock, tmp_path) -> None:
    result = _invoke("--from-file", str(tmp_path / "missing.json"))
    assert result.exit_code == EXIT_USAGE
    assert "Cannot read" in result.stderr
