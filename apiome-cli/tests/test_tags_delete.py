"""``apiome tags delete`` (CLI 11.7, #3266).

Against a mocked ``DELETE /v1/version-tags/{tenant}/{project}/{tag}``: the typed confirmation must
match the tag name exactly; ``--yes`` skips it; an immutable tag exits 6 (pre-checked, and the
server's ``409 TAG_IMMUTABLE``); only the tag is deleted, never the version; ``--json`` returns
``{deleted, tag, was_pointing_to}``.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from apiome_cli.exit_codes import EXIT_SUCCESS, EXIT_TAG_LOCKED, EXIT_USAGE
from apiome_cli.main import app

runner = CliRunner()

_ENV = {
    "APIOME_API_KEY": "obj_test_key",
    "APIOME_BASE_URL": "http://localhost:8000",
    "APIOME_TENANT_ID": "acme",
}
_HOST = "http://localhost:8000/v1"
_PROJECT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_TAG_ID = "5ab1e000-0000-4000-8000-000000000009"
_TAGS_URL = f"{_HOST}/version-tags/acme/{_PROJECT}"
_TAG = {
    "id": _TAG_ID,
    "name": "next-rc",
    "version_id": "v22",
    "target_version_string": "2.2.0",
    "immutable": False,
}


@pytest.fixture
def interactive(monkeypatch):
    """Pretend stdin is a terminal so the typed confirmation runs."""
    monkeypatch.setattr("apiome_cli.terminal.interactive_enabled", lambda: True)


def _mock(httpx_mock, *, tag=_TAG, delete_status=200) -> None:
    httpx_mock.add_response(url=f"{_HOST}/projects/acme/by-slug/payments-api", json={"id": _PROJECT})
    httpx_mock.add_response(method="GET", url=_TAGS_URL, json=[tag])
    httpx_mock.add_response(
        method="DELETE",
        url=f"{_TAGS_URL}/{_TAG_ID}",
        status_code=delete_status,
        json={"status": "deleted", "id": _TAG_ID}
        if delete_status == 200
        else {"detail": {"code": "TAG_IMMUTABLE", "message": "This tag is immutable and cannot be deleted"}},
        is_optional=True,
    )


def _deletes(httpx_mock) -> list[str]:
    return [r.url.path for r in httpx_mock.get_requests() if r.method == "DELETE"]


def test_typing_the_name_deletes_only_the_tag(httpx_mock, interactive) -> None:
    _mock(httpx_mock)
    result = runner.invoke(app, ["tags", "delete", "payments-api", "next-rc"], env=_ENV, input="next-rc\n")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "Deleting tag 'next-rc' (currently points to 2.2.0)" in result.stderr
    assert "✔ Deleted tag 'next-rc'." in result.stdout
    assert _deletes(httpx_mock) == [f"/v1/version-tags/acme/{_PROJECT}/{_TAG_ID}"]


def test_the_typed_name_is_exact(httpx_mock, interactive) -> None:
    _mock(httpx_mock)
    result = runner.invoke(app, ["tags", "delete", "payments-api", "next-rc"], env=_ENV, input="Next-RC\n")
    assert result.exit_code == EXIT_USAGE
    assert "nothing was changed" in result.stderr
    assert _deletes(httpx_mock) == []


def test_without_a_terminal_it_refuses_unless_yes(httpx_mock) -> None:
    _mock(httpx_mock)
    result = runner.invoke(app, ["tags", "delete", "payments-api", "next-rc"], env=_ENV)
    assert result.exit_code == EXIT_USAGE
    assert "--yes" in result.stderr
    assert _deletes(httpx_mock) == []


def test_yes_skips_the_confirmation(httpx_mock) -> None:
    _mock(httpx_mock)
    result = runner.invoke(app, ["tags", "delete", "payments-api", "next-rc", "--yes"], env=_ENV)
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert len(_deletes(httpx_mock)) == 1


def test_by_uuid(httpx_mock) -> None:
    _mock(httpx_mock)
    result = runner.invoke(app, ["tags", "delete", "payments-api", _TAG_ID, "--yes"], env=_ENV)
    assert result.exit_code == EXIT_SUCCESS


def test_json(httpx_mock) -> None:
    _mock(httpx_mock)
    result = runner.invoke(app, ["--json", "tags", "delete", "payments-api", "next-rc", "--yes"], env=_ENV)
    assert json.loads(result.stdout) == {
        "deleted": True,
        "tag": "next-rc",
        "tag_id": _TAG_ID,
        "was_pointing_to": "2.2.0",
    }


def test_an_immutable_tag_exits_6_before_any_write(httpx_mock) -> None:
    _mock(httpx_mock, tag={**_TAG, "immutable": True})
    result = runner.invoke(app, ["tags", "delete", "payments-api", "next-rc", "--yes"], env=_ENV)
    assert result.exit_code == EXIT_TAG_LOCKED
    assert "can never be deleted" in result.stderr
    assert _deletes(httpx_mock) == []


def test_a_server_immutable_conflict_also_exits_6(httpx_mock) -> None:
    _mock(httpx_mock, delete_status=409)
    result = runner.invoke(app, ["tags", "delete", "payments-api", "next-rc", "--yes"], env=_ENV)
    assert result.exit_code == EXIT_TAG_LOCKED


def test_a_protected_tag_refusal_uses_the_shared_mapping(httpx_mock) -> None:
    httpx_mock.add_response(url=f"{_HOST}/projects/acme/by-slug/payments-api", json={"id": _PROJECT})
    httpx_mock.add_response(method="GET", url=_TAGS_URL, json=[{**_TAG, "protected": True}])
    httpx_mock.add_response(
        method="DELETE",
        url=f"{_TAGS_URL}/{_TAG_ID}",
        status_code=403,
        json={"detail": {"code": "TAG_PROTECTED", "message": "This tag is protected and cannot be deleted"}},
    )
    result = runner.invoke(app, ["tags", "delete", "payments-api", "next-rc", "--yes"], env=_ENV)
    assert result.exit_code == EXIT_USAGE
    assert "protected" in result.stderr


def test_an_unknown_tag_is_a_usage_error(httpx_mock) -> None:
    _mock(httpx_mock)
    result = runner.invoke(app, ["tags", "delete", "payments-api", "canary", "--yes"], env=_ENV)
    assert result.exit_code == EXIT_USAGE
    assert "No version tag 'canary'" in result.stderr
    assert _deletes(httpx_mock) == []
