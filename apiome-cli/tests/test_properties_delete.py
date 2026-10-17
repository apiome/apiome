"""``apiome properties delete <project> <name-or-id>`` (CLI 6.5, #3227).

The wording (:mod:`apiome_cli.property_delete`) and the command against a mocked REST API: an unused
property is deleted after the typed name (or ``--yes``); one in use exits 6 listing its class
attributes, unless ``--force --yes``, which sends ``?force=true``; a published use (409) exits 6.
"""

from __future__ import annotations

import json

from typer.testing import CliRunner

from apiome_cli.exit_codes import EXIT_PROPERTY_IN_USE, EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app
from apiome_cli.property_delete import (
    IN_USE_HINT,
    render_deleted,
    render_force_plan,
    render_in_use,
    render_published_refusal,
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
_USAGE = [
    {"class_name": "Charge", "attribute_name": "amount", "required": True},
    {"class_name": "Payout", "attribute_name": "amount", "required": True},
    {"class_name": "Refund", "attribute_name": "amount", "required": False},
]
_PUBLISHED = [{"class_name": "Charge", "attribute_name": "amount", "version": "1.0.0"}]


def _prop(name="amount", usage=_USAGE):
    return {"id": _ID, "name": name, "data": {"type": "number"}, "usage": usage}


def _mock(httpx_mock, *, prop, delete_status=None, delete_json=None, force=False):
    httpx_mock.add_response(
        url=f"{_HOST}/projects/acme/by-slug/payments-api", json={"id": _PROJECT}, is_optional=True
    )
    httpx_mock.add_response(url=_PROPS, json=[{"id": _ID, "name": prop["name"]}])
    httpx_mock.add_response(url=_RECORD, method="GET", json=prop)
    if delete_status is not None:
        httpx_mock.add_response(
            url=f"{_RECORD}?force=true" if force else _RECORD,
            method="DELETE",
            status_code=delete_status,
            json=delete_json if delete_json is not None else {"message": "deleted"},
        )


def _deletes(httpx_mock):
    return [r for r in httpx_mock.get_requests() if r.method == "DELETE"]


def _run(*args, name="amount", input=None, json_mode=False):
    argv = (["--json"] if json_mode else []) + ["properties", "delete", "payments-api", name, *args]
    return runner.invoke(app, argv, env=_ENV, input=input)


# ---- wording --------------------------------------------------------------------------------------


def test_render_in_use_lists_each_attribute_and_the_hint() -> None:
    assert render_in_use("amount", _USAGE).splitlines() == [
        "✘ Property 'amount' is in use by 3 class attributes:",
        "     Charge.amount  (required)",
        "     Payout.amount  (required)",
        "     Refund.amount  (optional)",
        *IN_USE_HINT.splitlines(),
    ]
    assert "apiome classes" not in IN_USE_HINT and "--force --yes" in IN_USE_HINT


def test_render_force_plan_and_one_attribute() -> None:
    assert render_force_plan("amount", _USAGE[:1]).splitlines()[0] == (
        "Removing 'amount' from 1 class attribute, then deleting it:"
    )


def test_render_published_refusal() -> None:
    text = render_published_refusal("amount", _PUBLISHED)
    assert "Charge.amount  (version 1.0.0)" in text and "nothing was deleted" in text


def test_render_deleted() -> None:
    assert render_deleted("amount") == "✔ Deleted property 'amount'."
    assert render_deleted("amount", 0) == "✔ Deleted property 'amount'."
    assert render_deleted("amount", 3) == "✔ Deleted property 'amount' and removed it from 3 class attributes."


# ---- command --------------------------------------------------------------------------------------


def test_an_unused_property_is_deleted_after_typing_its_name(httpx_mock, monkeypatch) -> None:
    monkeypatch.setattr("apiome_cli.terminal.interactive_enabled", lambda: True)
    _mock(httpx_mock, prop=_prop("unused_prop", []), delete_status=200)
    result = _run(name="unused_prop", input="unused_prop\n")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "Used by 0 classes — safe to delete." in result.output
    assert "✔ Deleted property 'unused_prop'." in result.output
    [request] = _deletes(httpx_mock)
    assert "force" not in str(request.url)


def test_a_mistyped_name_deletes_nothing(httpx_mock, monkeypatch) -> None:
    monkeypatch.setattr("apiome_cli.terminal.interactive_enabled", lambda: True)
    _mock(httpx_mock, prop=_prop("unused_prop", []))
    result = _run(name="unused_prop", input="unused\n")
    assert result.exit_code == EXIT_USAGE
    assert not _deletes(httpx_mock)


def test_yes_skips_the_typed_name_and_json_reports(httpx_mock) -> None:
    _mock(httpx_mock, prop=_prop("unused_prop", []), delete_status=200)
    result = _run("--yes", name="unused_prop", json_mode=True)
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert json.loads(result.stdout) == {"deleted": True, "property": "unused_prop", "property_id": _ID, "detached": 0}


def test_without_a_terminal_or_yes_nothing_is_deleted(httpx_mock) -> None:
    _mock(httpx_mock, prop=_prop("unused_prop", []))
    assert _run(name="unused_prop").exit_code == EXIT_USAGE
    assert not _deletes(httpx_mock)


def test_a_property_in_use_exits_6_and_lists_its_classes(httpx_mock) -> None:
    _mock(httpx_mock, prop=_prop())
    result = _run("--yes")
    assert result.exit_code == EXIT_PROPERTY_IN_USE
    assert "✘ Property 'amount' is in use by 3 class attributes:" in result.output
    assert "Charge.amount  (required)" in result.output
    assert not _deletes(httpx_mock)


def test_force_needs_yes() -> None:
    result = runner.invoke(app, ["properties", "delete", "payments-api", "amount", "--force"], env=_ENV)
    assert result.exit_code == EXIT_USAGE
    assert "pass --yes" in result.output


def test_force_yes_removes_and_deletes(httpx_mock) -> None:
    _mock(httpx_mock, prop=_prop(), delete_status=200, delete_json={"message": "deleted", "detached": 3}, force=True)
    result = _run("--force", "--yes")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "Removing 'amount' from 3 class attributes" in result.output
    assert "✔ Deleted property 'amount' and removed it from 3 class attributes." in result.output
    [request] = _deletes(httpx_mock)
    assert request.url.params["force"] == "true"


def test_force_with_a_published_use_exits_6(httpx_mock) -> None:
    _mock(
        httpx_mock,
        prop=_prop(),
        delete_status=409,
        delete_json={"detail": {"code": "property_in_published_version", "uses": _PUBLISHED}},
        force=True,
    )
    result = _run("--force", "--yes")
    assert result.exit_code == EXIT_PROPERTY_IN_USE
    assert "Charge.amount  (version 1.0.0)" in result.output


def test_a_server_that_ignores_force_is_reported(httpx_mock) -> None:
    _mock(httpx_mock, prop=_prop(), delete_status=200, delete_json={"message": "deleted"}, force=True)
    result = _run("--force", "--yes")
    assert result.exit_code == EXIT_SUCCESS
    assert "Warning: this server ignored --force" in result.output


def test_a_server_without_usage_refuses(httpx_mock) -> None:
    _mock(httpx_mock, prop=_prop(usage=None))
    result = _run("--yes")
    assert result.exit_code == EXIT_PROPERTY_IN_USE
    assert "does not report which classes use the property" in result.output
    assert not _deletes(httpx_mock)


def test_an_unknown_property_suggests_names(httpx_mock) -> None:
    httpx_mock.add_response(url=f"{_HOST}/projects/acme/by-slug/payments-api", json={"id": _PROJECT})
    httpx_mock.add_response(url=_PROPS, json=[{"id": _ID, "name": "amount"}])
    result = _run("--yes", name="amont")
    assert result.exit_code == EXIT_USAGE
    assert "Did you mean: amount?" in result.output
