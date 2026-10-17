"""``apiome properties show <project> <name-or-id>`` (CLI 6.2, #3224).

The rules (:mod:`apiome_cli.property_show`), snapshot tests of the pane and the ``--json`` document
(``tests/fixtures/properties_show/``; regenerate with ``UPDATE_SNAPSHOTS=1``), and the command against
a mocked ``GET /v1/properties/{tenant}/{project}`` (to resolve the name) and
``GET /v1/properties/{tenant}/{project}/{id}`` (the property with its ``usage``).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apiome_cli.exit_codes import EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app
from apiome_cli.property_show import (
    PropertyNotFound,
    constraints,
    examples,
    find_property,
    render_show,
    usage_lines,
)

runner = CliRunner()

SNAPSHOTS = Path(__file__).parent / "fixtures" / "properties_show"
UPDATE_SNAPSHOTS = os.environ.get("UPDATE_SNAPSHOTS") == "1"

_ENV = {
    "APIOME_API_KEY": "obj_test_key",
    "APIOME_BASE_URL": "http://localhost:8000",
    "APIOME_TENANT_ID": "acme",
}
_HOST = "http://localhost:8000/v1"
_PROJECT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_AMOUNT_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
_LIST = f"{_HOST}/properties/acme/{_PROJECT}"

_AMOUNT_DATA = {
    "type": "number",
    "minimum": 0,
    "multipleOf": 0.01,
    "examples": [19.99, 1000.0, 0.5],
    "required": True,
}
_ITEMS = [
    {"id": _AMOUNT_ID, "name": "amount", "data": _AMOUNT_DATA, "used_by": ["Charge", "Payout", "Refund"]},
    {"id": "id-currency", "name": "currency", "data": {"type": "string"}, "used_by": ["Charge"]},
    {"id": "id-created", "name": "created_at", "data": {"type": "string", "format": "date-time"}, "used_by": []},
]
_AMOUNT = {
    "id": _AMOUNT_ID,
    "project_id": _PROJECT,
    "name": "amount",
    "description": "Monetary amount in the smallest unit for the currency.",
    "data": _AMOUNT_DATA,
    "enabled": True,
    "created_at": "2026-10-01T12:00:00Z",
    "updated_at": "2026-10-02T12:00:00Z",
    "used_by": None,
    "used_by_count": None,
    "usage": [
        {"class_name": "Charge", "attribute_name": "amount", "required": True},
        {"class_name": "Payout", "attribute_name": "amount", "required": True},
        {"class_name": "Refund", "attribute_name": "refund_amount", "required": False},
    ],
}


def _snapshot(name: str, text: str) -> None:
    path = SNAPSHOTS / f"{name}.txt"
    if UPDATE_SNAPSHOTS:
        SNAPSHOTS.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    assert path.exists(), f"missing snapshot {path.name}; run with UPDATE_SNAPSHOTS=1"
    assert text + "\n" == path.read_text(encoding="utf-8")


def _mock(httpx_mock, *, record=True) -> None:
    httpx_mock.add_response(
        url=f"{_HOST}/projects/acme/by-slug/payments-api", json={"id": _PROJECT}, is_optional=True
    )
    httpx_mock.add_response(url=_LIST, json=_ITEMS)
    if record:
        httpx_mock.add_response(url=f"{_LIST}/{_AMOUNT_ID}", json=_AMOUNT)


def _run(*args, json_mode=False):
    argv = (["--json"] if json_mode else []) + ["properties", "show", *args]
    return runner.invoke(app, argv, env=_ENV)


# ---- rules ----------------------------------------------------------------------------------------


def test_find_by_exact_name_then_ignoring_case_then_id() -> None:
    assert find_property(_ITEMS, "amount", project="p")["id"] == _AMOUNT_ID
    assert find_property(_ITEMS, "  AMOUNT ", project="p")["id"] == _AMOUNT_ID
    assert find_property(_ITEMS, _AMOUNT_ID.upper(), project="p")["name"] == "amount"


def test_an_exact_name_wins_over_a_case_insensitive_one() -> None:
    items = [{"id": "1", "name": "Amount"}, {"id": "2", "name": "amount"}]
    assert find_property(items, "Amount", project="p")["id"] == "1"


def test_a_name_matching_several_only_ignoring_case_is_ambiguous() -> None:
    items = [{"id": "1", "name": "Amount"}, {"id": "2", "name": "amount"}]
    with pytest.raises(PropertyNotFound, match=r"more than one property \(Amount, amount\)"):
        find_property(items, "AMOUNT", project="p")


def test_a_typo_suggests_close_names() -> None:
    with pytest.raises(PropertyNotFound) as exc:
        find_property(_ITEMS, "amont", project="payments-api")
    assert str(exc.value) == "No property 'amont' in project 'payments-api'. Did you mean: amount?"


def test_a_typo_in_case_still_suggests() -> None:
    with pytest.raises(PropertyNotFound, match="Did you mean: created_at"):
        find_property(_ITEMS, "CREATED-AT", project="p")


def test_nothing_close_has_no_suggestion() -> None:
    with pytest.raises(PropertyNotFound) as exc:
        find_property(_ITEMS, "zzzzzz", project="p")
    assert "Did you mean" not in str(exc.value)


def test_an_unknown_uuid_is_not_found() -> None:
    with pytest.raises(PropertyNotFound, match="No property"):
        find_property(_ITEMS, "cccccccc-cccc-4ccc-8ccc-cccccccccccc", project="p")


def test_constraints_in_keyword_order() -> None:
    assert constraints({"multipleOf": 0.01, "minimum": 0}) == "minimum=0, multipleOf=0.01"
    assert constraints({"enum": ["usd", "eur"], "pattern": "^[a-z]+$"}) == 'pattern=^[a-z]+$, enum=["usd","eur"]'
    assert constraints({"type": "string"}) == "—"
    assert constraints(None) == "—"


def test_examples_from_examples_or_example() -> None:
    assert examples({"examples": [19.99, "a"]}) == "19.99, a"
    assert examples({"example": {"k": 1}}) == '{"k":1}'
    assert examples({}) == "—"


def test_usage_lines() -> None:
    assert usage_lines(None)[0].startswith("not reported by this server")
    assert usage_lines([]) == ["— (no class uses it)"]
    assert usage_lines(_AMOUNT["usage"]) == [
        "Charge.amount         (required)",
        "Payout.amount         (required)",
        "Refund.refund_amount  (optional)",
    ]


def test_a_ref_shows_as_the_primitive() -> None:
    pane = render_show({"id": "x", "name": "currency", "data": {"$ref": "std/v0/primitives/iso4217"}})
    assert "Primitive:    std/v0/primitives/iso4217" in pane
    assert "Type:         iso4217" in pane


def test_the_pane_snapshot() -> None:
    _snapshot("pane", render_show(_AMOUNT))


# ---- command --------------------------------------------------------------------------------------


def test_show_by_name(httpx_mock) -> None:
    _mock(httpx_mock)
    result = _run("payments-api", "amount")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert result.output == render_show(_AMOUNT) + "\n"


def test_show_by_uuid_with_a_project_uuid(httpx_mock) -> None:
    _mock(httpx_mock)
    result = _run(_PROJECT, _AMOUNT_ID)
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "Charge.amount" in result.output


def test_json_is_the_full_property_with_usage(httpx_mock) -> None:
    _mock(httpx_mock)
    result = _run("payments-api", "amount", json_mode=True)
    assert result.exit_code == EXIT_SUCCESS, result.output
    document = json.loads(result.output)
    assert document["usage"] == _AMOUNT["usage"]
    _snapshot("json", json.dumps(document, indent=2, sort_keys=True))


def test_a_typo_exits_2_with_did_you_mean(httpx_mock) -> None:
    _mock(httpx_mock, record=False)
    result = _run("payments-api", "amont")
    assert result.exit_code == EXIT_USAGE
    assert "Did you mean: amount?" in result.output


def test_both_arguments_are_required() -> None:
    result = runner.invoke(app, ["properties", "show", "payments-api"], env=_ENV)
    assert result.exit_code == EXIT_USAGE
