"""``apiome tags list`` / ``tags show`` (CLI 11.4, #3263).

Snapshot tests of the human output (``tests/fixtures/tags/*.txt``; regenerate with
``UPDATE_SNAPSHOTS=1``) and the command against a mocked ``GET /v1/version-tags/{t}/{p}``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apiome_cli.exit_codes import EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app
from apiome_cli.tag_view import TagNotFound, find_tag, render_tag_list, render_tag_show, sort_tags

runner = CliRunner()

SNAPSHOTS = Path(__file__).parent / "fixtures" / "tags"
UPDATE_SNAPSHOTS = os.environ.get("UPDATE_SNAPSHOTS") == "1"

_ENV = {
    "APIOME_API_KEY": "obj_test_key",
    "APIOME_BASE_URL": "http://localhost:8000",
    "APIOME_TENANT_ID": "acme",
}
_HOST = "http://localhost:8000/v1"
_PROJECT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_STABLE_ID = "5ab1e000-0000-4000-8000-000000000001"


def _tag(name, label, version_id, *, updated, email="kenji@example.com", **extra):
    return {
        "id": extra.pop("id", f"00000000-0000-4000-8000-{abs(hash(name)) % 10**12:012d}"),
        "project_id": _PROJECT,
        "version_id": version_id,
        "name": name,
        "message": None,
        "channel": None,
        "immutable": False,
        "protected": False,
        "created_by": "11111111-1111-4111-8111-111111111111",
        "created_by_email": email,
        "created_at": "2026-02-18T09:00:00Z",
        "updated_at": updated,
        "target_version_string": label,
        **extra,
    }


_TAGS = [
    _tag(
        "stable",
        "2.1.0",
        "v-21",
        updated="2026-05-04T12:43:10Z",
        id=_STABLE_ID,
        channel="stable",
        message="GA",
    ),
    _tag("latest", "2.1.0", "v-21", updated="2026-05-04T12:43:00Z"),
    _tag("prod", "2.0.0", "v-20", updated="2026-02-18T09:00:00Z", immutable=True, protected=True),
    _tag("next", "2.2.0", "v-22", updated="2026-05-06T08:00:00+02:00", email="morgan@example.com"),
]


def _snapshot(name: str, text: str) -> None:
    path = SNAPSHOTS / f"{name}.txt"
    if UPDATE_SNAPSHOTS:
        SNAPSHOTS.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    assert path.exists(), f"missing snapshot {path.name}; run with UPDATE_SNAPSHOTS=1"
    assert text + "\n" == path.read_text(encoding="utf-8")


def _mock(httpx_mock, tags=_TAGS) -> None:
    httpx_mock.add_response(url=f"{_HOST}/projects/acme/by-slug/payments-api", json={"id": _PROJECT})
    httpx_mock.add_response(url=f"{_HOST}/version-tags/acme/{_PROJECT}", json=list(tags))


# --- presentation ---------------------------------------------------------------------------


def test_list_snapshot() -> None:
    _snapshot("list", render_tag_list(sort_tags(_TAGS)))


def test_list_snapshot_when_limited() -> None:
    _snapshot("list_limited", render_tag_list(sort_tags(_TAGS)[:2], total=4))


def test_show_snapshot() -> None:
    _snapshot("show_stable", render_tag_show(_TAGS[0]))


def test_show_snapshot_with_locks_and_no_email() -> None:
    _snapshot("show_prod", render_tag_show({**_TAGS[2], "created_by_email": None}))


def test_no_tags() -> None:
    assert render_tag_list([]) == "No version tags."


def test_find_by_name_then_id() -> None:
    assert find_tag(_TAGS, "next")["name"] == "next"
    assert find_tag(_TAGS, _STABLE_ID)["name"] == "stable"
    with pytest.raises(TagNotFound):
        find_tag(_TAGS, "Stable")  # names are exact


# --- the commands ---------------------------------------------------------------------------


def test_list_prints_the_table(httpx_mock) -> None:
    _mock(httpx_mock)
    result = runner.invoke(app, ["tags", "list", "payments-api"], env=_ENV)
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert result.stdout == render_tag_list(sort_tags(_TAGS)) + "\n"


def test_list_limit_and_all(httpx_mock) -> None:
    _mock(httpx_mock)
    limited = runner.invoke(app, ["tags", "list", "payments-api", "--limit", "2"], env=_ENV)
    assert "Showing 2 of 4 tags" in limited.stdout
    _mock(httpx_mock)
    everything = runner.invoke(app, ["tags", "list", "payments-api", "--limit", "2", "--all"], env=_ENV)
    assert "Showing" not in everything.stdout
    assert everything.stdout.count("\n") == 5  # header + 4 tags


def test_list_json_returns_the_tag_array(httpx_mock) -> None:
    _mock(httpx_mock)
    result = runner.invoke(app, ["--json", "tags", "list", "payments-api", "--limit", "3"], env=_ENV)
    body = json.loads(result.stdout)
    assert body["total"] == 4
    assert [t["name"] for t in body["items"]] == ["latest", "next", "prod"]


def test_show_prints_one_tag(httpx_mock) -> None:
    _mock(httpx_mock)
    result = runner.invoke(app, ["tags", "show", "payments-api", "stable"], env=_ENV)
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert result.stdout == render_tag_show(_TAGS[0]) + "\n"


def test_show_json_returns_the_tag_object(httpx_mock) -> None:
    _mock(httpx_mock)
    result = runner.invoke(app, ["--json", "tags", "show", "payments-api", _STABLE_ID], env=_ENV)
    assert json.loads(result.stdout) == _TAGS[0]


def test_show_an_unknown_tag_is_a_usage_error(httpx_mock) -> None:
    _mock(httpx_mock)
    result = runner.invoke(app, ["tags", "show", "payments-api", "canary"], env=_ENV)
    assert result.exit_code == EXIT_USAGE
    assert "No version tag 'canary'" in result.stderr


def test_an_empty_project(httpx_mock) -> None:
    _mock(httpx_mock, tags=[])
    result = runner.invoke(app, ["tags", "list", "payments-api"], env=_ENV)
    assert result.stdout == "No version tags.\n"
