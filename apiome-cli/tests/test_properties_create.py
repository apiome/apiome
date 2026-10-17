"""``apiome properties create <project>`` (CLI 6.3, #3225).

The rules (:mod:`apiome_cli.property_create`), the primitive cache
(:mod:`apiome_cli.client.primitive_cache`), and the command against a mocked REST API: the flags,
``--from-file`` (JSON and YAML) and the prompts send **identical** bodies; content problems exit 7
with one ``field: message`` line each.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from apiome_cli.client import primitive_cache
from apiome_cli.exit_codes import EXIT_PROPERTY_INVALID, EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app
from apiome_cli.property_create import (
    FieldError,
    PropertyDraft,
    PropertyInvalid,
    check_examples,
    check_name,
    find_primitive,
    merge_draft,
    parse_example,
    property_schema,
    request_body,
    search_primitives,
    split_examples,
)

runner = CliRunner()

_ENV = {
    "APIOME_API_KEY": "obj_test_key",
    "APIOME_BASE_URL": "http://localhost:8000",
    "APIOME_TENANT_ID": "acme",
}
_HOST = "http://localhost:8000/v1"
_PROJECT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_MONEY_ID = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
_PROPS = f"{_HOST}/properties/acme/{_PROJECT}"
_PRIMS = f"{_HOST}/primitives/acme"

_MONEY = {
    "id": _MONEY_ID,
    "name": "iso4217-money",
    "schema_id": "https://apiome.dev/acme/money",
    "schema": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://apiome.dev/acme/money",
        "type": "number",
        "minimum": 0,
        "multipleOf": 0.01,
    },
}
_PRIMITIVES = [
    _MONEY,
    {"id": "id-email", "name": "email", "schema": {"type": "string", "format": "email"}},
    {"id": "id-iso8601", "name": "iso8601-date", "schema": {"type": "string", "format": "date", "examples": ["2026-01-01"]}},
]
_BODY = {
    "name": "amount",
    "description": "Monetary amount in smallest unit.",
    "data": {"type": "number", "minimum": 0, "multipleOf": 0.01, "examples": [19.99, 1000.0]},
}


@pytest.fixture(autouse=True)
def _cache_home(tmp_path, monkeypatch):
    """Keep the primitive cache out of the real home directory."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))


def _mock(httpx_mock, *, post=True, status=200, existing=()):
    httpx_mock.add_response(
        url=f"{_HOST}/projects/acme/by-slug/payments-api", json={"id": _PROJECT}, is_optional=True
    )
    httpx_mock.add_response(url=_PROPS, method="GET", json=[{"id": f"id-{n}", "name": n} for n in existing])
    httpx_mock.add_response(url=_PRIMS, method="GET", json=_PRIMITIVES)
    if post:
        httpx_mock.add_response(
            url=_PROPS, method="POST", status_code=status, json={"id": "new", "name": "amount"} if status == 200 else {"detail": "x"}
        )


def _posted(httpx_mock):
    [request] = [r for r in httpx_mock.get_requests() if r.method == "POST"]
    return json.loads(request.content)


def _run(*args, input=None, json_mode=False):
    argv = (["--json"] if json_mode else []) + ["properties", "create", "payments-api", *args]
    return runner.invoke(app, argv, env=_ENV, input=input)


_FLAGS = (
    "--name", "amount", "--primitive", "iso4217-money",
    "--description", "Monetary amount in smallest unit.",
    "--example", "19.99", "--example", "1000.00",
)


# ---- rules ----------------------------------------------------------------------------------------


def test_parse_example_reads_json_else_text() -> None:
    assert parse_example("19.99") == 19.99
    assert parse_example(" true ") is True
    assert parse_example('{"a": 1}') == {"a": 1}
    assert parse_example("usd") == "usd"
    assert split_examples("19.99, 1000.00 ,, x") == [19.99, 1000.0, "x"]


def test_flags_win_over_the_file() -> None:
    draft = merge_draft(
        name="amount", primitive=None, description=None, examples=["5"],
        document={"name": "old", "primitive": "email", "description": "d", "examples": [1, 2]},
    )
    assert draft == PropertyDraft(name="amount", primitive="email", description="d", examples=[5])


def test_file_examples_keep_their_types_and_one_value_is_a_list() -> None:
    assert merge_draft(name=None, primitive=None, description=None, examples=[], document={"examples": ["19.99"]}).examples == ["19.99"]
    assert merge_draft(name=None, primitive=None, description=None, examples=[], document={"examples": 3}).examples == [3]


def test_unknown_file_keys_and_tags_are_field_errors() -> None:
    with pytest.raises(PropertyInvalid) as exc:
        merge_draft(name=None, primitive=None, description=None, examples=[], document={"tags": ["money"], "kind": 1})
    assert [str(e) for e in exc.value.errors] == [
        "tags: properties have no tags",
        "kind: unknown key (use name, primitive, description, examples)",
    ]


def test_check_name() -> None:
    assert check_name("amount", ["currency"]) == []
    assert check_name(None, []) == [FieldError("name", "required")]
    assert check_name("x" * 256, [])[0].message.startswith("at most 255")
    assert check_name("amount", ["amount"])[0].message == "the project already has a property 'amount'"


def test_find_primitive_by_name_case_uuid_and_id() -> None:
    assert find_primitive(_PRIMITIVES, "iso4217-money") is _MONEY
    assert find_primitive(_PRIMITIVES, "ISO4217-Money") is _MONEY
    assert find_primitive(_PRIMITIVES, _MONEY_ID.upper()) is _MONEY
    assert find_primitive(_PRIMITIVES, "https://apiome.dev/acme/money") is _MONEY


def test_an_unknown_primitive_suggests_names() -> None:
    with pytest.raises(PropertyInvalid) as exc:
        find_primitive(_PRIMITIVES, "iso4217-mony")
    assert str(exc.value) == "primitive: no primitive 'iso4217-mony' in this tenant. Did you mean: iso4217-money?"


def test_a_missing_or_ambiguous_primitive() -> None:
    with pytest.raises(PropertyInvalid, match="primitive: required"):
        find_primitive(_PRIMITIVES, None)
    twins = [{"id": "1", "name": "Money"}, {"id": "2", "name": "money"}]
    with pytest.raises(PropertyInvalid, match="names more than one primitive; use its id"):
        find_primitive(twins, "MONEY")


def test_search_primitives_prefers_prefixes() -> None:
    assert search_primitives(_PRIMITIVES, "iso") == ["iso4217-money", "iso8601-date"]
    assert search_primitives(_PRIMITIVES, "date") == ["iso8601-date"]
    assert search_primitives(_PRIMITIVES, "zzz") == []


def test_property_schema_copies_without_identity() -> None:
    data = property_schema(_MONEY, [1])
    assert data == {"type": "number", "minimum": 0, "multipleOf": 0.01, "examples": [1]}
    assert "$id" in _MONEY["schema"]  # the primitive itself is untouched
    assert property_schema(_PRIMITIVES[2], [])["examples"] == ["2026-01-01"]


def test_check_examples_reports_each_rejected_example() -> None:
    errors, warnings = check_examples(_MONEY["schema"], [19.99, -1, "x"])
    assert warnings == []
    assert [e.field for e in errors] == ["examples[1]", "examples[2]"]
    assert "less than the minimum of 0" in errors[0].message


def test_multiple_of_is_decimal_exact() -> None:
    errors, _ = check_examples({"type": "number", "multipleOf": 0.01}, [19.99, 1000.0, 0.5, 19.995])
    assert [e.field for e in errors] == ["examples[3]"]
    assert "19.995 is not a multiple of 0.01" in errors[0].message


def test_the_property_required_flag_is_not_read_as_json_schema() -> None:
    errors, warnings = check_examples({"type": "string", "required": True}, [1])
    assert warnings == [] and [e.field for e in errors] == ["examples[0]"]


def test_check_examples_checks_formats() -> None:
    errors, _ = check_examples({"type": "string", "format": "email"}, ["a@b.co", "nope"])
    assert [e.field for e in errors] == ["examples[1]"]


def test_check_examples_warns_when_it_cannot_check() -> None:
    errors, warnings = check_examples({"$ref": "https://elsewhere.example/x.json"}, [1])
    assert errors == [] and "not fully checked" in warnings[0]
    errors, warnings = check_examples({"type": 12}, [1])
    assert errors == [] and "not valid JSON Schema" in warnings[0]


def test_request_body() -> None:
    draft = PropertyDraft("amount", "iso4217-money", "Monetary amount in smallest unit.", [19.99, 1000.0])
    assert request_body(draft, _MONEY) == _BODY


# ---- cache ----------------------------------------------------------------------------------------


class _Client:
    base_url = "http://localhost:8000"


def test_the_cache_is_used_for_five_minutes(httpx_mock, monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(primitive_cache, "fetch_list", lambda client, path: (calls.append(path) or (_PRIMITIVES, 3)))
    assert primitive_cache.load_primitives(_Client(), "acme", clock=lambda: 1000.0) == _PRIMITIVES
    assert primitive_cache.load_primitives(_Client(), "acme", clock=lambda: 1299.0) == _PRIMITIVES
    assert len(calls) == 1
    primitive_cache.load_primitives(_Client(), "acme", clock=lambda: 1300.0)
    assert len(calls) == 2
    primitive_cache.load_primitives(_Client(), "other", clock=lambda: 1300.0)
    assert len(calls) == 3  # one cache per tenant


def test_a_broken_cache_file_is_fetched_again(monkeypatch) -> None:
    path = primitive_cache.cache_path("http://localhost:8000", "acme")
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(primitive_cache, "fetch_list", lambda client, p: (_PRIMITIVES, 3))
    assert primitive_cache.load_primitives(_Client(), "acme") == _PRIMITIVES
    assert json.loads(path.read_text(encoding="utf-8"))["items"] == _PRIMITIVES


# ---- command --------------------------------------------------------------------------------------


def test_flags_create_the_property(httpx_mock) -> None:
    _mock(httpx_mock)
    result = _run(*_FLAGS, "--yes")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert result.output == "✔ Created property 'amount'.\n"
    assert _posted(httpx_mock) == _BODY


def test_json_prints_the_created_property(httpx_mock) -> None:
    _mock(httpx_mock)
    result = _run(*_FLAGS, json_mode=True)
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert json.loads(result.output) == {"id": "new", "name": "amount"}


@pytest.mark.parametrize(
    ("filename", "text"),
    [
        (
            "amount.yaml",
            "name: amount\nprimitive: iso4217-money\ndescription: Monetary amount in smallest unit.\n"
            "examples:\n  - 19.99\n  - 1000.00\n",
        ),
        (
            "amount.json",
            json.dumps({"name": "amount", "primitive": "iso4217-money",
                        "description": "Monetary amount in smallest unit.", "examples": [19.99, 1000.0]}),
        ),
    ],
)
def test_from_file_sends_the_same_body(httpx_mock, tmp_path, filename, text) -> None:
    path = tmp_path / filename
    path.write_text(text, encoding="utf-8")
    _mock(httpx_mock)
    result = _run("--from-file", str(path), "--yes")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert _posted(httpx_mock) == _BODY


def test_the_prompts_send_the_same_body(httpx_mock, monkeypatch) -> None:
    monkeypatch.setattr("apiome_cli.commands.properties.interactive_enabled", lambda: True)
    monkeypatch.setattr("apiome_cli.terminal.interactive_enabled", lambda: True)
    _mock(httpx_mock, existing=["amount_old"])
    answers = "amount\niso\niso4217\nMonetary amount in smallest unit.\n19.99, 1000.00\ny\n"
    result = _run(input=answers)
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "Matches: iso4217-money, iso8601-date" in result.output
    assert "✔ Created property 'amount'." in result.output
    assert _posted(httpx_mock) == _BODY


def test_the_name_prompt_refuses_a_taken_name(httpx_mock, monkeypatch) -> None:
    monkeypatch.setattr("apiome_cli.commands.properties.interactive_enabled", lambda: True)
    _mock(httpx_mock, existing=["amount"])
    result = _run("--primitive", "iso4217-money", "--yes", input="amount\nprice\n\n\n")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "the project already has a property 'amount'" in result.output
    assert _posted(httpx_mock)["name"] == "price"


def test_field_errors_exit_7_and_create_nothing(httpx_mock) -> None:
    _mock(httpx_mock, post=False, existing=["amount"])
    result = _run("--name", "amount", "--primitive", "iso4217-mony", "--example", "-1")
    assert result.exit_code == EXIT_PROPERTY_INVALID
    assert "name: the project already has a property 'amount'" in result.output
    assert "primitive: no primitive 'iso4217-mony' in this tenant. Did you mean: iso4217-money?" in result.output
    assert "Nothing was created." in result.output


def test_a_rejected_example_exits_7(httpx_mock) -> None:
    _mock(httpx_mock, post=False)
    result = _run("--name", "amount", "--primitive", "iso4217-money", "--example", "-1")
    assert result.exit_code == EXIT_PROPERTY_INVALID
    assert "examples[0]: -1 — -1 is less than the minimum of 0" in result.output


def test_without_a_terminal_missing_fields_are_field_errors(httpx_mock) -> None:
    _mock(httpx_mock, post=False)
    result = _run()
    assert result.exit_code == EXIT_PROPERTY_INVALID
    assert "name: required" in result.output and "primitive: required" in result.output


def test_a_tags_key_in_the_file_exits_7(tmp_path) -> None:
    path = tmp_path / "p.yaml"
    path.write_text("name: amount\ntags: [money]\n", encoding="utf-8")
    result = _run("--from-file", str(path))
    assert result.exit_code == EXIT_PROPERTY_INVALID
    assert "tags: properties have no tags" in result.output


def test_an_unreadable_or_non_object_file_exits_2(tmp_path) -> None:
    assert _run("--from-file", str(tmp_path / "missing.yaml")).exit_code == EXIT_USAGE
    path = tmp_path / "list.yaml"
    path.write_text("- a\n- b\n", encoding="utf-8")
    result = _run("--from-file", str(path))
    assert result.exit_code == EXIT_USAGE
    assert "must hold one property object" in result.output


def test_a_server_conflict_exits_7(httpx_mock) -> None:
    _mock(httpx_mock, status=409)
    result = _run(*_FLAGS)
    assert result.exit_code == EXIT_PROPERTY_INVALID
    assert "name: the project already has a property 'amount'" in result.output
