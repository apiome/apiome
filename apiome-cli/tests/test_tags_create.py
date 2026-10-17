"""``apiome tags create`` (CLI 11.5, #3264).

The rules (:mod:`apiome_cli.tag_create`) and the command against a mocked
``POST /v1/version-tags/{tenant}/{project}``: names are lower-cased and validated client-side; an
existing tag (found first, or the server's ``409 TAG_NAME_CONFLICT``) exits 6 with a hint to move it
with ``tags update``; ``--from-file`` sits under the flags; an immutable tag asks first; ``--json``
returns the created tag.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from apiome_cli.exit_codes import EXIT_SUCCESS, EXIT_TAG_EXISTS, EXIT_USAGE
from apiome_cli.main import app
from apiome_cli.tag_create import (
    TagCreateError,
    TagRequest,
    merge_request,
    needs_confirmation,
    normalize_tag_name,
    request_body,
)

runner = CliRunner()

_ENV = {
    "APIOME_API_KEY": "obj_test_key",
    "APIOME_BASE_URL": "http://localhost:8000",
    "APIOME_TENANT_ID": "acme",
}
_HOST = "http://localhost:8000/v1"
_PROJECT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_V21 = "21212121-2121-4121-8121-212121212121"
_V20 = "20202020-2020-4020-8020-202020202020"
_TAGS_URL = f"{_HOST}/version-tags/acme/{_PROJECT}"
_VERSIONS = [
    {"id": _V21, "version_id": "2.1.0", "created_at": "2026-10-01T00:00:00Z"},
    {"id": _V20, "version_id": "2.0.0", "created_at": "2026-09-01T00:00:00Z"},
]
_EXISTING = [{"id": "t1", "name": "prod", "version_id": _V20, "target_version_string": "2.0.0"}]


@pytest.fixture
def interactive(monkeypatch):
    """Pretend stdin is a terminal so the confirmation runs."""
    monkeypatch.setattr("apiome_cli.terminal.interactive_enabled", lambda: True)


def _created(name="stable", version_id=_V21, **extra):
    return {"id": "t-new", "project_id": _PROJECT, "version_id": version_id, "name": name, **extra}


def _mock(httpx_mock, *, post_status=200, post_json=None) -> None:
    httpx_mock.add_response(url=f"{_HOST}/projects/acme/by-slug/payments-api", json={"id": _PROJECT})
    httpx_mock.add_response(method="GET", url=_TAGS_URL, json=_EXISTING)
    httpx_mock.add_response(url=f"{_HOST}/versions/acme/{_PROJECT}", json=_VERSIONS, is_optional=True)
    httpx_mock.add_response(
        method="POST", url=_TAGS_URL, status_code=post_status, json=post_json or _created(), is_optional=True
    )


def _posted(httpx_mock) -> list[dict]:
    return [json.loads(r.content) for r in httpx_mock.get_requests() if r.method == "POST"]


# --- rules ----------------------------------------------------------------------------------


@pytest.mark.parametrize(("raw", "name"), [("stable", "stable"), (" Prod-EU ", "prod-eu"), ("v2", "v2")])
def test_names_are_lower_cased(raw, name) -> None:
    assert normalize_tag_name(raw) == name


@pytest.mark.parametrize("raw", ["", "a", "2stable", "prod_eu", "prod.eu", "release/1", "-x", "x" * 42])
def test_invalid_names_are_refused(raw) -> None:
    with pytest.raises(TagCreateError, match="Invalid tag name"):
        normalize_tag_name(raw)


def test_flags_win_over_the_file() -> None:
    request = merge_request(
        name="Stable",
        version="v2.1.0",
        description="GA",
        document={
            "name": "other",
            "version": "1.0.0",
            "description": "old",
            "channel": "stable",
            "immutable": True,
        },
    )
    assert request == TagRequest(
        name="stable", version_ref="v2.1.0", message="GA", channel="stable", immutable=True, protected=False
    )


def test_a_tags_show_dump_works_as_the_file() -> None:
    dump = {
        "name": "prod",
        "target_version_string": "2.0.0",
        "version_id": _V20,
        "message": "pinned",
        "channel": None,
    }
    request = merge_request(name=None, version=None, description=None, document=dump)
    assert (request.name, request.version_ref, request.message) == ("prod", "2.0.0", "pinned")


def test_name_and_version_are_required() -> None:
    with pytest.raises(TagCreateError, match="Name the tag"):
        merge_request(name=None, version="2.1.0", description=None)
    with pytest.raises(TagCreateError, match="--version is required"):
        merge_request(name="stable", version=None, description=None)


def test_only_immutable_tags_are_confirmed() -> None:
    plain = merge_request(name="stable", version="2.1.0", description=None)
    assert not needs_confirmation(plain)
    assert needs_confirmation(
        merge_request(name="ga", version="2.1.0", description=None, document={"immutable": True})
    )


def test_the_request_body() -> None:
    body = request_body(merge_request(name="stable", version="2.1.0", description="GA"), _V21)
    assert body == {
        "version_id": _V21,
        "name": "stable",
        "message": "GA",
        "channel": None,
        "immutable": False,
        "protected": False,
    }


# --- the command ----------------------------------------------------------------------------


def test_create_a_tag(httpx_mock) -> None:
    _mock(httpx_mock)
    result = runner.invoke(app, ["tags", "create", "payments-api", "Stable", "--version", "v2.1.0"], env=_ENV)
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert result.stdout == "✔ Tag 'stable' created → 2.1.0.\n"
    assert _posted(httpx_mock)[0]["name"] == "stable" and _posted(httpx_mock)[0]["version_id"] == _V21


def test_description_becomes_the_message(httpx_mock) -> None:
    _mock(httpx_mock, post_json=_created(name="prod-eu", version_id=_V20))
    result = runner.invoke(
        app,
        [
            "tags",
            "create",
            "payments-api",
            "prod-eu",
            "--version",
            "2.0.0",
            "--description",
            "Pinned for review",
        ],
        env=_ENV,
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert _posted(httpx_mock)[0]["message"] == "Pinned for review"


def test_json_returns_the_created_tag(httpx_mock) -> None:
    _mock(httpx_mock)
    result = runner.invoke(
        app, ["--json", "tags", "create", "payments-api", "stable", "--version", "2.1.0"], env=_ENV
    )
    assert json.loads(result.stdout) == _created()


def test_an_existing_tag_exits_6_with_an_update_hint(httpx_mock) -> None:
    _mock(httpx_mock)
    result = runner.invoke(app, ["tags", "create", "payments-api", "PROD", "--version", "2.1.0"], env=_ENV)
    assert result.exit_code == EXIT_TAG_EXISTS
    assert "Tag 'prod' already exists (it points to 2.0.0)" in result.stderr
    assert "tags update" in result.stderr
    assert _posted(httpx_mock) == []


def test_a_server_conflict_also_exits_6(httpx_mock) -> None:
    _mock(
        httpx_mock,
        post_status=409,
        post_json={"detail": {"code": "TAG_NAME_CONFLICT", "message": "A tag with this name already exists"}},
    )
    result = runner.invoke(app, ["tags", "create", "payments-api", "stable", "--version", "2.1.0"], env=_ENV)
    assert result.exit_code == EXIT_TAG_EXISTS
    assert "already exists" in result.stderr


def test_an_invalid_name_is_refused_before_any_request(httpx_mock) -> None:
    result = runner.invoke(app, ["tags", "create", "payments-api", "prod_eu", "--version", "2.1.0"], env=_ENV)
    assert result.exit_code == EXIT_USAGE
    assert "Invalid tag name" in result.stderr
    assert httpx_mock.get_requests() == []


def test_an_unknown_version_is_a_usage_error(httpx_mock) -> None:
    _mock(httpx_mock)
    result = runner.invoke(app, ["tags", "create", "payments-api", "stable", "--version", "9.9.9"], env=_ENV)
    assert result.exit_code == EXIT_USAGE
    assert "No version or version tag '9.9.9'" in result.stderr


def test_from_file(httpx_mock, tmp_path) -> None:
    _mock(httpx_mock, post_json=_created(name="prod-eu", version_id=_V20, channel="stable"))
    path = tmp_path / "tag.json"
    path.write_text(
        json.dumps({"name": "prod-eu", "version": "2.0.0", "description": "EU", "channel": "stable"})
    )
    result = runner.invoke(app, ["tags", "create", "payments-api", "--from-file", str(path)], env=_ENV)
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert _posted(httpx_mock)[0] == {
        "version_id": _V20,
        "name": "prod-eu",
        "message": "EU",
        "channel": "stable",
        "immutable": False,
        "protected": False,
    }


def test_a_bad_file_is_a_usage_error(tmp_path) -> None:
    path = tmp_path / "tag.json"
    path.write_text("[1, 2]")
    result = runner.invoke(app, ["tags", "create", "payments-api", "--from-file", str(path)], env=_ENV)
    assert result.exit_code == EXIT_USAGE
    assert "must hold one tag object" in result.stderr


def test_an_immutable_tag_asks_first(httpx_mock, tmp_path, interactive) -> None:
    _mock(httpx_mock, post_json=_created(name="ga", immutable=True))
    path = tmp_path / "tag.json"
    path.write_text(json.dumps({"immutable": True}))
    declined = runner.invoke(
        app,
        ["tags", "create", "payments-api", "ga", "--version", "2.1.0", "--from-file", str(path)],
        env=_ENV,
        input="n\n",
    )
    assert declined.exit_code == EXIT_SUCCESS
    assert "can never be moved or deleted" in declined.output
    assert _posted(httpx_mock) == []


def test_yes_skips_the_immutable_confirmation(httpx_mock, tmp_path) -> None:
    _mock(httpx_mock, post_json=_created(name="ga", immutable=True))
    path = tmp_path / "tag.json"
    path.write_text(json.dumps({"immutable": True}))
    result = runner.invoke(
        app,
        ["tags", "create", "payments-api", "ga", "--version", "2.1.0", "--from-file", str(path), "--yes"],
        env=_ENV,
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert _posted(httpx_mock)[0]["immutable"] is True
