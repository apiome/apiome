"""``apiome classes create <project> <version>`` (CLI 7.3, #3231).

The rules (:mod:`apiome_cli.class_create`) and the command against a mocked REST API: flags,
``--from-file`` (JSON/YAML class spec) and the prompts produce the same requests; a published or
frozen version exits 6; field problems exit 7; missing project tags are created; a failed attach
deletes the class again (exit 1); ``--create-missing`` creates properties from a chosen primitive.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from apiome_cli.class_create import (
    ClassDraft,
    PropertyRef,
    VersionLocked,
    check_draft,
    check_version,
    class_body,
    class_property_body,
    merge_draft,
    missing_properties,
    normalize_tags,
    parse_property,
    render_created,
    tags_to_create,
)
from apiome_cli.exit_codes import EXIT_ERROR, EXIT_PROPERTY_INVALID, EXIT_SUCCESS, EXIT_USAGE, EXIT_VERSION_LOCKED
from apiome_cli.main import app
from apiome_cli.property_create import PropertyInvalid

runner = CliRunner()

_ENV = {
    "APIOME_API_KEY": "obj_test_key",
    "APIOME_BASE_URL": "http://localhost:8000",
    "APIOME_TENANT_ID": "acme",
}
_HOST = "http://localhost:8000/v1"
_PROJECT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_VERSION = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
_CLASS = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
_LIBRARY = [
    {"id": "p-amount", "name": "amount", "description": "Minor units.", "data": {"type": "number", "minimum": 0}},
    {"id": "p-currency", "name": "currency", "description": None, "data": {"type": "string"}},
    {"id": "p-reason", "name": "reason", "description": None, "data": {"type": "string", "required": True}},
]
_CLASSES = f"{_HOST}/classes/acme"
_CLASS_PROPS = f"{_HOST}/classes/acme/{_CLASS}/properties"
_PROJECT_TAGS = f"{_HOST}/project-tags/acme/{_PROJECT}"
_CLASS_TAGS = f"{_HOST}/project-tags/acme/classes/{_CLASS}"


@pytest.fixture(autouse=True)
def _cache_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))


# ---- rules ----------------------------------------------------------------------------------------


def test_parse_property() -> None:
    assert parse_property("amount", where="p") == PropertyRef("amount", False)
    assert parse_property(" amount:Required ", where="p") == PropertyRef("amount", True)
    assert parse_property("amount:optional", where="p") == PropertyRef("amount", False)
    assert parse_property({"name": "reason", "required": True}, where="p") == PropertyRef("reason", True)
    for bad in ("amount:maybe", ":required", {"name": "x", "required": "yes"}, {}):
        with pytest.raises(PropertyInvalid):
            parse_property(bad, where="p")


def test_normalize_tags() -> None:
    assert normalize_tags("Financial, core,,financial") == ["financial", "core"]
    assert normalize_tags([" PII ", "pii"]) == ["pii"]


def test_flags_win_over_the_file() -> None:
    doc = {"name": "Old", "description": "d", "tags": ["core"], "properties": ["amount:required", {"name": "reason"}]}
    draft = merge_draft(name="Refund", description=None, tags=[], properties=[], document=doc)
    assert draft == ClassDraft("Refund", "d", ["core"], [PropertyRef("amount", True), PropertyRef("reason", False)])
    flagged = merge_draft(name=None, description=None, tags=["Fin"], properties=["currency"], document=doc)
    assert flagged.tags == ["fin"] and flagged.properties == [PropertyRef("currency", False)]


def test_the_file_refuses_unknown_keys_and_bad_entries() -> None:
    with pytest.raises(PropertyInvalid) as exc:
        merge_draft(name=None, description=None, tags=[], properties=[], document={"kind": 1, "properties": ["a:x"]})
    assert [str(e) for e in exc.value.errors] == [
        "kind: unknown key (use name, description, tags, properties)",
        "properties[0]: 'a:x': use name or name:required",
    ]


def test_check_version() -> None:
    check_version({"version_id": "2.2.0-rc.1", "published": False}, frozen=False)
    with pytest.raises(VersionLocked, match="2.1.0 is published"):
        check_version({"version_id": "2.1.0", "published": True}, frozen=False)
    with pytest.raises(VersionLocked, match="is frozen"):
        check_version({"version_id": "2.1.0", "published": False}, frozen=True)


def test_check_draft() -> None:
    draft = ClassDraft("Charge", None, ["x" * 101], [PropertyRef("amount"), PropertyRef("amount"), PropertyRef("ghost")])
    assert [str(e) for e in check_draft(draft, existing_classes=["Charge"], library=["amount"])] == [
        "name: the version already has a class 'Charge'",
        f"tags: '{'x' * 101}' is longer than 100 characters",
        "properties: 'amount' is listed twice",
        "properties: no property 'ghost' in this project",
    ]
    assert check_draft(ClassDraft(None, None), existing_classes=[], library=[])[0].message == "required"
    assert check_draft(ClassDraft("A", None, [], [PropertyRef("ghost")]), existing_classes=[], library=[], allow_missing=True) == []
    assert missing_properties(ClassDraft("A", None, [], [PropertyRef("ghost"), PropertyRef("amount")]), ["amount"]) == ["ghost"]


def test_bodies_and_tags() -> None:
    assert class_body(ClassDraft("Refund", "d"), _VERSION) == {"version_id": _VERSION, "name": "Refund", "description": "d", "schema": {}}
    assert class_property_body(_LIBRARY[2], False) == {
        "property_id": "p-reason", "name": "reason", "description": None, "data": {"type": "string", "required": False},
    }
    assert _LIBRARY[2]["data"]["required"] is True  # the library property is untouched
    assert tags_to_create(ClassDraft("A", None, ["financial", "core"]), [{"name": "Core"}]) == ["financial"]
    assert render_created("Refund", 1, ["financial"]) == "✔ Created class 'Refund' with 1 property.\n  New project tags: financial"


# ---- command --------------------------------------------------------------------------------------


def _mock(httpx_mock, *, published=False, frozen=False, classes=(), project_tags=(), create=True):
    httpx_mock.add_response(url=f"{_HOST}/projects/acme/by-slug/payments-api", json={"id": _PROJECT})
    httpx_mock.add_response(url=f"{_HOST}/version-tags/acme/{_PROJECT}", json=[])
    httpx_mock.add_response(
        url=f"{_HOST}/versions/acme/{_PROJECT}", json=[{"id": _VERSION, "version_id": "2.2.0-rc.1", "published": published}]
    )
    httpx_mock.add_response(
        url=f"{_HOST}/versions/acme/{_PROJECT}/{_VERSION}/freeze-schema", json={"frozen": frozen}, is_optional=True
    )
    httpx_mock.add_response(url=f"{_CLASSES}?version_id={_VERSION}", json=[{"name": n} for n in classes], is_optional=True)
    httpx_mock.add_response(url=f"{_HOST}/properties/acme/{_PROJECT}", method="GET", json=_LIBRARY, is_optional=True)
    if create:
        httpx_mock.add_response(url=_CLASSES, method="POST", json={"id": _CLASS, "name": "Refund"})
        httpx_mock.add_response(url=_CLASS_PROPS, method="POST", json={"id": "cp"}, is_reusable=True, is_optional=True)
        httpx_mock.add_response(url=_PROJECT_TAGS, method="GET", json=list(project_tags), is_optional=True)
        httpx_mock.add_response(url=_PROJECT_TAGS, method="POST", json={"id": "t-new", "name": "financial"}, is_optional=True)
        httpx_mock.add_response(url=_CLASS_TAGS, method="POST", json={"id": "ct"}, is_reusable=True, is_optional=True)


def _writes(httpx_mock):
    return [
        (r.method, str(r.url).removeprefix(_HOST), json.loads(r.content) if r.content else None)
        for r in httpx_mock.get_requests()
        if r.method in ("POST", "DELETE")
    ]


def _run(*args, input=None, json_mode=False):
    argv = (["--json"] if json_mode else []) + ["classes", "create", "payments-api", "2.2.0-rc.1", *args]
    return runner.invoke(app, argv, env=_ENV, input=input)


_FLAGS = ("--name", "Refund", "--description", "Reversal of a charge.", "--tag", "financial",
          "--property", "amount:required", "--property", "currency:required", "--property", "reason", "--yes")
_EXPECTED_WRITES = [
    ("POST", "/classes/acme", {"version_id": _VERSION, "name": "Refund", "description": "Reversal of a charge.", "schema": {}}),
    ("POST", f"/classes/acme/{_CLASS}/properties",
     {"property_id": "p-amount", "name": "amount", "description": "Minor units.", "data": {"type": "number", "minimum": 0, "required": True}}),
    ("POST", f"/classes/acme/{_CLASS}/properties",
     {"property_id": "p-currency", "name": "currency", "description": None, "data": {"type": "string", "required": True}}),
    ("POST", f"/classes/acme/{_CLASS}/properties",
     {"property_id": "p-reason", "name": "reason", "description": None, "data": {"type": "string", "required": False}}),
    ("POST", f"/project-tags/acme/{_PROJECT}", {"name": "financial"}),
    ("POST", f"/project-tags/acme/classes/{_CLASS}", {"tag_id": "t-new"}),
]


def test_flags_create_the_class_properties_and_tag(httpx_mock) -> None:
    _mock(httpx_mock)
    result = _run(*_FLAGS)
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "✔ Created class 'Refund' with 3 properties." in result.output
    assert "New project tags: financial" in result.output
    assert _writes(httpx_mock) == _EXPECTED_WRITES


def test_from_file_sends_the_same_requests(httpx_mock, tmp_path) -> None:
    path = tmp_path / "refund.yaml"
    path.write_text(
        "name: Refund\ndescription: Reversal of a charge.\ntags: [Financial]\n"
        "properties:\n  - amount:required\n  - {name: currency, required: true}\n  - reason\n",
        encoding="utf-8",
    )
    _mock(httpx_mock)
    result = _run("--from-file", str(path), "--yes")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert _writes(httpx_mock) == _EXPECTED_WRITES


def test_the_prompts_send_the_same_requests(httpx_mock, monkeypatch) -> None:
    monkeypatch.setattr("apiome_cli.commands.classes.interactive_enabled", lambda: True)
    monkeypatch.setattr("apiome_cli.terminal.interactive_enabled", lambda: True)
    _mock(httpx_mock, classes=["Charge"])
    answers = "\n".join([
        "Charge", "Refund",                 # a taken name is refused, then accepted
        "Reversal of a charge.", "financial", "y",
        "am", "y",                          # one match → amount, required
        "re",                               # matches currency and reason: the matches are listed …
        "cur", "y",                         # … so narrow it
        "reason", "n",                      # an exact name, optional
        "", "y",                            # done; confirm
    ]) + "\n"
    result = _run(input=answers)
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "the version already has a class 'Charge'" in result.output
    assert "Matches: currency, reason" in result.output
    assert _writes(httpx_mock) == _EXPECTED_WRITES


def test_a_published_version_exits_6(httpx_mock) -> None:
    _mock(httpx_mock, published=True, create=False)
    result = _run(*_FLAGS)
    assert result.exit_code == EXIT_VERSION_LOCKED
    assert "is published" in result.output and _writes(httpx_mock) == []


def test_a_frozen_version_exits_6(httpx_mock) -> None:
    _mock(httpx_mock, frozen=True, create=False)
    result = _run(*_FLAGS)
    assert result.exit_code == EXIT_VERSION_LOCKED
    assert "is frozen" in result.output


def test_field_errors_exit_7_and_write_nothing(httpx_mock) -> None:
    _mock(httpx_mock, classes=["Refund"], create=False)
    result = _run("--name", "Refund", "--property", "ghost")
    assert result.exit_code == EXIT_PROPERTY_INVALID
    assert "name: the version already has a class 'Refund'" in result.output
    assert "properties: no property 'ghost' in this project" in result.output
    assert _writes(httpx_mock) == []


def test_without_a_terminal_a_missing_name_is_an_error(httpx_mock) -> None:
    _mock(httpx_mock, create=False)
    result = _run()
    assert result.exit_code == EXIT_PROPERTY_INVALID
    assert "name: required" in result.output


def test_an_existing_tag_is_reused(httpx_mock) -> None:
    _mock(httpx_mock, project_tags=[{"id": "t-fin", "name": "Financial"}])
    result = _run("--name", "Refund", "--tag", "financial", "--yes")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert ("POST", f"/project-tags/acme/classes/{_CLASS}", {"tag_id": "t-fin"}) in _writes(httpx_mock)
    assert "New project tags" not in result.output


def test_a_failed_attach_deletes_the_class(httpx_mock) -> None:
    httpx_mock.add_response(url=f"{_HOST}/projects/acme/by-slug/payments-api", json={"id": _PROJECT})
    httpx_mock.add_response(url=f"{_HOST}/version-tags/acme/{_PROJECT}", json=[])
    httpx_mock.add_response(url=f"{_HOST}/versions/acme/{_PROJECT}", json=[{"id": _VERSION, "version_id": "2.2.0-rc.1"}])
    httpx_mock.add_response(url=f"{_HOST}/versions/acme/{_PROJECT}/{_VERSION}/freeze-schema", status_code=404, json={})
    httpx_mock.add_response(url=f"{_CLASSES}?version_id={_VERSION}", json=[])
    httpx_mock.add_response(url=f"{_HOST}/properties/acme/{_PROJECT}", method="GET", json=_LIBRARY)
    httpx_mock.add_response(url=_CLASSES, method="POST", json={"id": _CLASS, "name": "Refund"})
    httpx_mock.add_response(url=_CLASS_PROPS, method="POST", status_code=500, json={"detail": "boom"})
    httpx_mock.add_response(url=f"{_CLASSES}/{_CLASS}", method="DELETE", json={"message": "deleted"})
    result = _run("--name", "Refund", "--property", "amount")
    assert result.exit_code == EXIT_ERROR
    assert "adding property 'amount' failed (HTTP 500)" in result.output
    assert "The class was deleted again" in result.output
    assert _writes(httpx_mock)[-1] == ("DELETE", f"/classes/acme/{_CLASS}", None)


def test_create_missing_needs_a_terminal() -> None:
    result = runner.invoke(app, ["classes", "create", "payments-api", "2.2.0-rc.1", "--name", "A", "--create-missing"], env=_ENV)
    assert result.exit_code == EXIT_USAGE
    assert "needs a terminal" in result.output


def test_create_missing_creates_the_property_from_a_primitive(httpx_mock, monkeypatch) -> None:
    monkeypatch.setattr("apiome_cli.commands.classes.interactive_enabled", lambda: True)
    _mock(httpx_mock)
    httpx_mock.add_response(
        url=f"{_HOST}/primitives/acme", json=[{"id": "pr", "name": "iso4217-money", "schema": {"$id": "x", "type": "number"}}]
    )
    httpx_mock.add_response(url=f"{_HOST}/properties/acme/{_PROJECT}", method="POST", json={"id": "p-fee", "name": "fee", "data": {"type": "number"}})
    result = _run("--name", "Refund", "--property", "fee:required", "--create-missing", "--yes", input="iso4217\n")
    assert result.exit_code == EXIT_SUCCESS, result.output
    writes = _writes(httpx_mock)
    assert ("POST", f"/properties/acme/{_PROJECT}", {"name": "fee", "description": None, "data": {"type": "number"}}) in writes
    assert writes[-1] == ("POST", f"/classes/acme/{_CLASS}/properties",
                          {"property_id": "p-fee", "name": "fee", "description": None, "data": {"type": "number", "required": True}})
    assert "Created properties: fee" in result.output


def test_json_output(httpx_mock) -> None:
    _mock(httpx_mock)
    result = _run(*_FLAGS, json_mode=True)
    document = json.loads(result.stdout)
    assert document["class"]["id"] == _CLASS
    assert document["properties"][0] == {"name": "amount", "required": True}
    assert document["createdTags"] == ["financial"]
