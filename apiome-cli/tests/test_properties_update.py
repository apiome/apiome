"""``apiome properties update <project> <name-or-id>`` (CLI 6.4, #3226).

The rules (:mod:`apiome_cli.property_update`) and the command against a mocked REST API: the diff,
``--dry-run``, ``--primitive`` (exit 6 while a class requires the property, unless
``--allow-breaking``), examples, ``--required-everywhere``, ``--from-file`` (JSON/YAML, the
``updated_at`` precondition and 409 ``update_conflict`` → exit 6), and field errors (exit 7).
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from apiome_cli.exit_codes import (
    EXIT_PROPERTY_BREAKING,
    EXIT_PROPERTY_INVALID,
    EXIT_SUCCESS,
    EXIT_UPDATE_CONFLICT,
    EXIT_USAGE,
)
from apiome_cli.main import app
from apiome_cli.property_create import PropertyInvalid
from apiome_cli.property_update import (
    BreakingChange,
    FieldChange,
    PropertyUpdateError,
    breaking_uses,
    changes_from_file,
    changes_from_flags,
    check_changes,
    check_primitive_change,
    data_with_primitive,
    edit_examples,
    expected_updated_at,
    field_changes,
    render_diff,
    request_body,
    required_everywhere_line,
    summary,
)

runner = CliRunner()

_ENV = {
    "APIOME_API_KEY": "obj_test_key",
    "APIOME_BASE_URL": "http://localhost:8000",
    "APIOME_TENANT_ID": "acme",
}
_HOST = "http://localhost:8000/v1"
_PROJECT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
_PROPS = f"{_HOST}/properties/acme/{_PROJECT}"
_RECORD = f"{_PROPS}/{_ID}"
_STAMP = "2026-10-17T12:00:00Z"

_AMOUNT = {
    "id": _ID,
    "project_id": _PROJECT,
    "name": "amount",
    "description": "Amount.",
    "data": {"type": "number", "minimum": 0, "examples": [19.99], "required": True},
    "enabled": True,
    "updated_at": _STAMP,
    "usage": [
        {"class_name": "Charge", "attribute_name": "amount", "required": True},
        {"class_name": "Refund", "attribute_name": "amount", "required": False},
    ],
}
_OPTIONAL_ONLY = {**_AMOUNT, "usage": [{"class_name": "Refund", "attribute_name": "amount", "required": False}]}
_DECIMAL = {"id": "id-dec", "name": "decimal", "schema": {"$id": "x", "type": "string", "pattern": "^[0-9.]+$"}}


@pytest.fixture(autouse=True)
def _cache_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))


def _mock(httpx_mock, *, prop=_AMOUNT, put=None, put_status=200, primitives=False):
    httpx_mock.add_response(
        url=f"{_HOST}/projects/acme/by-slug/payments-api", json={"id": _PROJECT}, is_optional=True
    )
    httpx_mock.add_response(url=_PROPS, json=[{"id": _ID, "name": "amount"}, {"id": "id-price", "name": "price"}])
    httpx_mock.add_response(url=_RECORD, method="GET", json=prop)
    if primitives:
        httpx_mock.add_response(url=f"{_HOST}/primitives/acme", json=[_DECIMAL])
    if put is not None or put_status != 200:
        httpx_mock.add_response(url=_RECORD, method="PUT", status_code=put_status, json=put or {})


def _sent(httpx_mock):
    [request] = [r for r in httpx_mock.get_requests() if r.method == "PUT"]
    return json.loads(request.content)


def _run(*args, json_mode=False):
    argv = (["--json"] if json_mode else []) + ["properties", "update", "payments-api", "amount", *args]
    return runner.invoke(app, argv, env=_ENV)


# ---- rules ----------------------------------------------------------------------------------------


def test_flags_change_only_what_differs() -> None:
    changes = changes_from_flags(
        _AMOUNT, name="amount", description="New.", primitive=None, add_examples=["1234.56"], remove_examples=[]
    )
    assert changes == {
        "description": "New.",
        "data": {"type": "number", "minimum": 0, "examples": [19.99, 1234.56], "required": True},
    }


def test_an_empty_description_clears_it_and_is_sent_as_empty() -> None:
    changes = changes_from_flags(_AMOUNT, name=None, description="  ", primitive=None, add_examples=[], remove_examples=[])
    assert changes == {"description": None}
    assert request_body(changes, _STAMP) == {"description": "", "expectedUpdatedAt": _STAMP}


def test_edit_examples() -> None:
    data = {"examples": [1, "a"]}
    assert edit_examples(data, ["2", "1"], ["a"]) == {"examples": [1, 2]}
    assert edit_examples(data, [], ["1", "a"]) == {}
    with pytest.raises(PropertyInvalid, match='examples: "b" is not one of'):
        edit_examples(data, [], ["b"])


def test_a_new_primitive_keeps_examples_and_required() -> None:
    data = data_with_primitive(_AMOUNT, _DECIMAL)
    assert data == {"type": "string", "pattern": "^[0-9.]+$", "examples": [19.99], "required": True}


def test_check_changes_reports_a_taken_name_and_bad_examples() -> None:
    changes = {"name": "price", "data": {"type": "string", "examples": [19.99]}}
    assert [str(e) for e in check_changes(_AMOUNT, changes, ["price"])] == [
        "name: the project already has a property 'price'",
        "examples[0]: 19.99 — 19.99 is not of type 'string'",
    ]


def test_breaking_uses() -> None:
    assert breaking_uses(_AMOUNT["usage"]) == ["Charge.amount"]
    assert breaking_uses([]) == []
    with pytest.raises(BreakingChange, match="does not report"):
        breaking_uses(None)


def test_check_primitive_change() -> None:
    with pytest.raises(BreakingChange) as exc:
        check_primitive_change(_AMOUNT["usage"], allow_breaking=False)
    assert exc.value.uses == ["Charge.amount"]
    check_primitive_change(_AMOUNT["usage"], allow_breaking=True)
    check_primitive_change(_OPTIONAL_ONLY["usage"], allow_breaking=False)


def test_from_file_reads_only_editable_fields() -> None:
    document = {**_AMOUNT, "description": " Edited. ", "usage": [], "used_by": ["x"], "created_at": "later"}
    assert changes_from_file(_AMOUNT, document) == {"description": "Edited."}


@pytest.mark.parametrize(
    ("document", "message"),
    [
        ({"id": "other"}, "describes property 'other'"),
        ({"id": _ID, "tags": ["money"]}, "properties have no tags"),
        ({"id": _ID, "name": " "}, "name cannot be empty"),
        ({"id": _ID, "enabled": "yes"}, "enabled must be true or false"),
        ({"id": _ID, "data": [1]}, "data must be an object"),
    ],
)
def test_from_file_refuses(document, message) -> None:
    with pytest.raises(PropertyUpdateError, match=message):
        changes_from_file(_AMOUNT, document)


def test_expected_updated_at() -> None:
    assert expected_updated_at({"updated_at": _STAMP}) == _STAMP
    with pytest.raises(PropertyUpdateError, match="no updated_at"):
        expected_updated_at({})


def test_field_changes_split_data_by_key() -> None:
    rows = field_changes(_AMOUNT, {"name": "total", "data": {**_AMOUNT["data"], "minimum": 1, "required": None}})
    assert rows == [
        FieldChange("name", "amount", "total"),
        FieldChange("data.minimum", 0, 1),
        FieldChange("data.required", True, None),
    ]


def test_render_diff() -> None:
    diff = render_diff(_AMOUNT, {"description": "New."}, True)
    assert diff.splitlines() == [
        f"Property amount ({_ID})",
        '- description: "Amount."',
        '+ description: "New."',
        "~ required (unpublished versions only): Refund.amount",
    ]
    assert render_diff(_AMOUNT, {}).endswith("No changes.")


def test_required_everywhere_line() -> None:
    assert required_everywhere_line(_AMOUNT, False) == "~ optional (unpublished versions only): Charge.amount"
    assert required_everywhere_line(_OPTIONAL_ONLY, False) == "~ every class attribute using it is already optional"
    assert "unpublished versions" in required_everywhere_line({"usage": None}, True)


def test_request_body_and_summary() -> None:
    assert request_body({}, _STAMP, False) == {"expectedUpdatedAt": _STAMP, "requiredEverywhere": False}
    text = summary(_AMOUNT, {"description": "x"}, {"changed": 2, "unchanged": 1, "skipped_published": 3})
    assert text.splitlines() == [
        "✔ Updated property 'amount': description.",
        "  Class attributes: 2 changed, 1 already set, 3 in published versions left alone.",
    ]


# ---- command --------------------------------------------------------------------------------------


def test_flags_update_with_the_read_precondition(httpx_mock) -> None:
    _mock(httpx_mock, put={**_AMOUNT, "description": "Monetary amount."})
    result = _run("--description", "Monetary amount.", "--add-example", "1234.56")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert result.output == "✔ Updated property 'amount': description, data.examples.\n"
    sent = _sent(httpx_mock)
    assert sent["expectedUpdatedAt"] == _STAMP
    assert sent["description"] == "Monetary amount."
    assert sent["data"]["examples"] == [19.99, 1234.56]
    assert set(sent) == {"description", "data", "expectedUpdatedAt"}


def test_dry_run_prints_the_diff_and_sends_nothing(httpx_mock) -> None:
    _mock(httpx_mock)
    result = _run("--description", "New.", "--dry-run")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert '+ description: "New."' in result.output
    assert not [r for r in httpx_mock.get_requests() if r.method == "PUT"]


def test_dry_run_json(httpx_mock) -> None:
    _mock(httpx_mock)
    result = _run("--remove-example", "19.99", "--dry-run", json_mode=True)
    document = json.loads(result.output)
    assert document["dryRun"] is True
    assert document["changes"] == [{"field": "data.examples", "before": [19.99], "after": None}]
    assert document["request"]["expectedUpdatedAt"] == _STAMP


def test_a_primitive_change_is_refused_while_a_class_requires_it(httpx_mock) -> None:
    _mock(httpx_mock, primitives=True)
    result = _run("--primitive", "decimal", "--yes")
    assert result.exit_code == EXIT_PROPERTY_BREAKING
    assert "Charge.amount  (required)" in result.output
    assert "Refund.amount" not in result.output
    assert "--allow-breaking" in result.output


def test_allow_breaking_changes_the_primitive(httpx_mock) -> None:
    _mock(httpx_mock, primitives=True, prop=_AMOUNT, put=_AMOUNT)
    # 19.99 is a number, so the new string schema rejects it: replace the example first.
    result = _run("--primitive", "decimal", "--remove-example", "19.99", "--add-example", '"19.99"',
                  "--allow-breaking", "--yes")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "Classes keep their own copy of the schema" in result.output
    assert _sent(httpx_mock)["data"] == {"type": "string", "pattern": "^[0-9.]+$", "examples": ["19.99"], "required": True}


def test_a_primitive_change_rejecting_the_examples_exits_7(httpx_mock) -> None:
    _mock(httpx_mock, primitives=True, prop=_OPTIONAL_ONLY)
    result = _run("--primitive", "decimal", "--yes")
    assert result.exit_code == EXIT_PROPERTY_INVALID
    assert "examples[0]: 19.99 — 19.99 is not of type 'string'" in result.output


def test_an_unknown_primitive_exits_7(httpx_mock) -> None:
    _mock(httpx_mock, primitives=True)
    result = _run("--primitive", "decimel")
    assert result.exit_code == EXIT_PROPERTY_INVALID
    assert "Did you mean: decimal?" in result.output


def test_required_everywhere_needs_yes_without_a_terminal(httpx_mock) -> None:
    _mock(httpx_mock)
    result = _run("--required-everywhere")
    assert result.exit_code == EXIT_USAGE
    assert "~ required (unpublished versions only): Refund.amount" in result.output


def test_required_everywhere_reports_the_counts(httpx_mock) -> None:
    counts = {"changed": 1, "unchanged": 1, "skipped_published": 2}
    _mock(httpx_mock, put={**_AMOUNT, "required_everywhere_result": counts})
    result = _run("--required-everywhere", "--yes")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert _sent(httpx_mock) == {"expectedUpdatedAt": _STAMP, "requiredEverywhere": True}
    assert "1 changed, 1 already set, 2 in published versions left alone" in result.output


def test_a_rename_to_a_taken_name_exits_7(httpx_mock) -> None:
    _mock(httpx_mock)
    result = _run("--name", "price")
    assert result.exit_code == EXIT_PROPERTY_INVALID
    assert "name: the project already has a property 'price'" in result.output


def test_nothing_to_change(httpx_mock) -> None:
    _mock(httpx_mock)
    result = _run("--description", "Amount.")
    assert result.exit_code == EXIT_SUCCESS
    assert "already matches" in result.output


@pytest.mark.parametrize("suffix", [".yaml", ".json"])
def test_from_file_sends_the_files_precondition(httpx_mock, tmp_path, suffix) -> None:
    document = {**_AMOUNT, "description": "From the file.", "updated_at": "2026-10-16T08:00:00Z"}
    path = tmp_path / f"amount{suffix}"
    if suffix == ".yaml":
        path.write_text(
            f"id: {_ID}\nname: amount\ndescription: From the file.\nupdated_at: '2026-10-16T08:00:00Z'\n",
            encoding="utf-8",
        )
    else:
        path.write_text(json.dumps(document), encoding="utf-8")
    _mock(httpx_mock, put={**_AMOUNT, "description": "From the file."})
    result = _run("--from-file", str(path))
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert _sent(httpx_mock) == {"description": "From the file.", "expectedUpdatedAt": "2026-10-16T08:00:00Z"}


def test_from_file_dry_run(httpx_mock, tmp_path) -> None:
    path = tmp_path / "amount.json"
    path.write_text(json.dumps({**_AMOUNT, "description": "From the file."}), encoding="utf-8")
    _mock(httpx_mock)
    result = _run("--from-file", str(path), "--dry-run")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert '+ description: "From the file."' in result.output


def test_a_stale_file_exits_6(httpx_mock, tmp_path) -> None:
    path = tmp_path / "amount.json"
    path.write_text(json.dumps({**_AMOUNT, "description": "Stale."}), encoding="utf-8")
    _mock(httpx_mock, put_status=409, put={"detail": {"code": "update_conflict", "current_updated_at": "later"}})
    result = _run("--from-file", str(path))
    assert result.exit_code == EXIT_UPDATE_CONFLICT
    assert "changed since" in result.output and "server updated_at later" in result.output


def test_a_server_name_conflict_exits_7(httpx_mock) -> None:
    _mock(httpx_mock, put_status=409, put={"detail": "A property with that name already exists in this project"})
    result = _run("--name", "total")
    assert result.exit_code == EXIT_PROPERTY_INVALID


def test_from_file_with_flags_or_nothing_is_a_usage_error(tmp_path) -> None:
    path = tmp_path / "a.json"
    path.write_text("{}", encoding="utf-8")
    assert _run("--from-file", str(path), "--name", "x").exit_code == EXIT_USAGE
    assert _run().exit_code == EXIT_USAGE


def test_an_unknown_property_suggests_names(httpx_mock) -> None:
    httpx_mock.add_response(url=f"{_HOST}/projects/acme/by-slug/payments-api", json={"id": _PROJECT})
    httpx_mock.add_response(url=_PROPS, json=[{"id": _ID, "name": "amount"}])
    result = runner.invoke(app, ["properties", "update", "payments-api", "amont", "--name", "x"], env=_ENV)
    assert result.exit_code == EXIT_USAGE
    assert "Did you mean: amount?" in result.output
