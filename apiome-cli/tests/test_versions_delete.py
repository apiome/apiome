"""``apiome versions delete`` (CLI 4.9, #3216).

The rules (:mod:`apiome_cli.version_delete`) and the command against a mocked REST API: the typed
confirmation must match the version exactly; a published or frozen version is refused (exit 6)
unless ``--force``, which unpublishes (with ``--reason``) and unfreezes it first; tags pointing at
the version stop the delete unless ``--detach-tags`` or ``--force`` removes them; ``--json``
returns ``{deleted, version, removed_tags, …}``.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from apiome_cli.exit_codes import EXIT_DELETE_REFUSED, EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app
from apiome_cli.version_delete import (
    DeletePlan,
    DeleteRefused,
    DeleteUsageError,
    json_result,
    plan_delete,
    render_plan,
    state_of,
)

runner = CliRunner()

_ENV = {
    "APIOME_API_KEY": "obj_test_key",
    "APIOME_BASE_URL": "http://localhost:8000",
    "APIOME_TENANT_ID": "acme",
}
_HOST = "http://localhost:8000/v1"
_PROJECT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_V22 = "22222222-2222-4222-8222-222222222222"
_V21 = "21212121-2121-4121-8121-212121212121"
_RECORD = f"{_HOST}/versions/acme/{_PROJECT}/{_V22}"
_FREEZE = f"{_RECORD}/freeze-schema"
_TAGS_URL = f"{_HOST}/version-tags/acme/{_PROJECT}"

_DRAFT = {"id": _V22, "version_id": "2.2.0", "published": False, "created_at": "2026-10-10T00:00:00Z"}
_OTHER = {"id": _V21, "version_id": "2.1.0", "published": True, "created_at": "2026-10-01T00:00:00Z"}


@pytest.fixture
def interactive(monkeypatch):
    """Pretend stdin is a terminal so the typed confirmation runs."""
    monkeypatch.setattr("apiome_cli.terminal.interactive_enabled", lambda: True)


def _mock(httpx_mock, *, version=_DRAFT, tags=(), frozen=None, tags_after=None) -> None:
    """Serve the reads (optional — refusals stop early) and accept the writes."""
    httpx_mock.add_response(url=f"{_HOST}/projects/acme/by-slug/payments-api", json={"id": _PROJECT})
    httpx_mock.add_response(url=f"{_HOST}/versions/acme/{_PROJECT}", json=[version, _OTHER])
    httpx_mock.add_response(url=_TAGS_URL, json=list(tags))
    if tags_after is not None:
        httpx_mock.add_response(url=_TAGS_URL, json=list(tags_after), is_optional=True)
    httpx_mock.add_response(
        method="GET", url=_FREEZE, json=frozen or {"frozen": False, "versionLabel": version["version_id"]}
    )
    httpx_mock.add_response(
        url=f"{_HOST}/classes/acme/version/{_V22}/with-properties-tags",
        json=[{"name": "Charge"}, {"name": "Refund"}],
        is_optional=True,
    )
    httpx_mock.add_response(url=f"{_HOST}/paths/acme/{_V22}", json=[{"id": "p1"}], is_optional=True)
    httpx_mock.add_response(
        method="DELETE",
        url=_RECORD,
        json={"message": "Version '2.2.0' deleted successfully"},
        is_optional=True,
    )


def _calls(httpx_mock) -> list[tuple[str, str]]:
    return [(r.method, r.url.path) for r in httpx_mock.get_requests() if r.method in ("POST", "DELETE")]


# --- rules ----------------------------------------------------------------------------------


def test_states() -> None:
    assert state_of(_DRAFT, frozen=False) == "draft"
    assert state_of(_OTHER, frozen=True) == "published, frozen"
    assert state_of(_DRAFT, frozen=True) == "frozen"


def test_a_draft_without_tags_needs_nothing_first() -> None:
    plan = plan_delete(_DRAFT, frozen=False, tags=[], force=False, detach_tags=False, reason=None)
    assert plan == DeletePlan(label="2.2.0", state="draft", unpublish=False, unfreeze=False, detach=[])


def test_published_or_frozen_is_refused_without_force() -> None:
    with pytest.raises(DeleteRefused, match="is published.*--force to unpublish it"):
        plan_delete(_OTHER, frozen=False, tags=[], force=False, detach_tags=False, reason="x")
    with pytest.raises(DeleteRefused, match="unpublish and unfreeze"):
        plan_delete(_OTHER, frozen=True, tags=[], force=False, detach_tags=False, reason="x")


def test_tags_are_refused_without_detach_or_force() -> None:
    tags = [{"name": "stable"}, {"name": "beta"}]
    with pytest.raises(DeleteRefused, match="beta, stable.*--detach-tags"):
        plan_delete(_DRAFT, frozen=False, tags=tags, force=False, detach_tags=False, reason=None)
    assert plan_delete(
        _DRAFT, frozen=False, tags=tags, force=False, detach_tags=True, reason=None
    ).detach == [
        "beta",
        "stable",
    ]
    assert plan_delete(
        _DRAFT, frozen=False, tags=tags, force=True, detach_tags=False, reason=None
    ).detach == [
        "beta",
        "stable",
    ]


def test_force_on_a_published_version_needs_a_reason() -> None:
    with pytest.raises(DeleteUsageError, match="--reason is required"):
        plan_delete(_OTHER, frozen=False, tags=[], force=True, detach_tags=False, reason="  ")
    plan = plan_delete(_OTHER, frozen=True, tags=[], force=True, detach_tags=False, reason="spike")
    assert (plan.unpublish, plan.unfreeze) == (True, True)


def test_a_frozen_draft_only_needs_unfreezing() -> None:
    plan = plan_delete(_DRAFT, frozen=True, tags=[], force=True, detach_tags=False, reason=None)
    assert (plan.unpublish, plan.unfreeze) == (False, True)


def test_the_draft_preview() -> None:
    plan = plan_delete(_DRAFT, frozen=False, tags=[], force=False, detach_tags=False, reason=None)
    text = render_plan(plan, classes=24, paths=18)
    assert text.splitlines()[:4] == [
        "This will delete:",
        "  • Version:  2.2.0  (state: draft)",
        "  • Classes:  24",
        "  • Paths:    18",
    ]
    assert "No published artifacts will be affected." in text


def test_the_forced_preview_names_each_step() -> None:
    plan = plan_delete(
        _OTHER, frozen=True, tags=[{"name": "stable"}], force=True, detach_tags=False, reason="spike"
    )
    text = render_plan(plan, classes=1, paths=1, downloads=2, reason="spike")
    assert "Tags:     stable (removed first)" in text
    assert "unpublished (reason: spike)" in text
    assert "downloaded 2 time(s)" in text
    assert "No published artifacts" not in text


def test_the_json_shape() -> None:
    body = json_result(
        label="2.2.0",
        version_record_id=_V22,
        removed_tags=["beta"],
        moved_tags=[{"name": "stable", "toVersionLabel": "2.1.0"}],
        unpublished=True,
        unfrozen=False,
    )
    assert body["deleted"] is True and body["version"] == "2.2.0" and body["removed_tags"] == ["beta"]
    assert body["moved_tags"] == [{"name": "stable", "to_version": "2.1.0"}]


# --- the command ----------------------------------------------------------------------------


def test_typing_the_version_deletes_a_draft(httpx_mock, interactive) -> None:
    _mock(httpx_mock)
    result = runner.invoke(app, ["versions", "delete", "payments-api", "v2.2.0"], env=_ENV, input="2.2.0\n")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "This will delete:" in result.stderr and "Classes:  2" in result.stderr
    assert "✔ Deleted 2.2.0." in result.stdout
    assert _calls(httpx_mock) == [("DELETE", f"/v1/versions/acme/{_PROJECT}/{_V22}")]


def test_a_mistyped_version_changes_nothing(httpx_mock, interactive) -> None:
    _mock(httpx_mock)
    result = runner.invoke(app, ["versions", "delete", "payments-api", "2.2.0"], env=_ENV, input="v2.2.0\n")
    assert result.exit_code == EXIT_USAGE
    assert _calls(httpx_mock) == []


def test_without_a_terminal_it_refuses_unless_yes(httpx_mock) -> None:
    _mock(httpx_mock)
    result = runner.invoke(app, ["versions", "delete", "payments-api", "2.2.0"], env=_ENV)
    assert result.exit_code == EXIT_USAGE
    assert _calls(httpx_mock) == []


def test_a_published_version_is_refused_with_exit_6(httpx_mock) -> None:
    _mock(httpx_mock, version={**_DRAFT, "published": True})
    result = runner.invoke(app, ["versions", "delete", "payments-api", "2.2.0", "--yes"], env=_ENV)
    assert result.exit_code == EXIT_DELETE_REFUSED
    assert "is published" in result.stderr
    assert _calls(httpx_mock) == []


def test_a_frozen_version_is_refused_with_exit_6(httpx_mock) -> None:
    _mock(httpx_mock, frozen={"frozen": True, "downloadCount": 0})
    result = runner.invoke(app, ["versions", "delete", "payments-api", "2.2.0", "--yes"], env=_ENV)
    assert result.exit_code == EXIT_DELETE_REFUSED
    assert "is frozen" in result.stderr


def test_pointing_tags_are_listed_and_refused(httpx_mock) -> None:
    _mock(
        httpx_mock,
        tags=[{"id": "t1", "name": "rc", "version_id": _V22}, {"id": "t2", "name": "x", "version_id": _V21}],
    )
    result = runner.invoke(app, ["versions", "delete", "payments-api", "2.2.0", "--yes"], env=_ENV)
    assert result.exit_code == EXIT_DELETE_REFUSED
    assert "version tag(s): rc." in result.stderr
    assert _calls(httpx_mock) == []


def test_detach_tags_removes_them_first(httpx_mock) -> None:
    tags = [{"id": "t1", "name": "rc", "version_id": _V22}]
    _mock(httpx_mock, tags=tags, tags_after=tags)
    httpx_mock.add_response(method="DELETE", url=f"{_TAGS_URL}/t1", json={"status": "deleted", "id": "t1"})
    result = runner.invoke(
        app, ["--json", "versions", "delete", "payments-api", "2.2.0", "--detach-tags", "--yes"], env=_ENV
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert json.loads(result.stdout)["removed_tags"] == ["rc"]
    assert _calls(httpx_mock) == [
        ("DELETE", f"/v1/version-tags/acme/{_PROJECT}/t1"),
        ("DELETE", f"/v1/versions/acme/{_PROJECT}/{_V22}"),
    ]


def test_force_unpublishes_and_unfreezes_first(httpx_mock) -> None:
    tags = [{"id": "t1", "name": "latest", "version_id": _V22}]
    _mock(
        httpx_mock,
        version={**_DRAFT, "published": True},
        tags=tags,
        tags_after=[{"id": "t1", "name": "latest", "version_id": _V21}],  # moved back by the unpublish
        frozen={"frozen": True, "downloadCount": 3},
    )
    httpx_mock.add_response(
        method="POST",
        url=f"{_RECORD}/unpublish",
        json={"version_id": "2.2.0", "tagsMoved": [{"name": "latest", "toVersionLabel": "2.1.0"}]},
    )
    httpx_mock.add_response(method="DELETE", url=f"{_FREEZE}?force=true", json={"frozen": False})
    result = runner.invoke(
        app,
        ["--json", "versions", "delete", "payments-api", "2.2.0", "--force", "--reason", "spike", "--yes"],
        env=_ENV,
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    body = json.loads(result.stdout)
    assert body == {
        "deleted": True,
        "version": "2.2.0",
        "version_record_id": _V22,
        "removed_tags": [],
        "moved_tags": [{"name": "latest", "to_version": "2.1.0"}],
        "unpublished": True,
        "unfrozen": True,
    }
    assert _calls(httpx_mock) == [
        ("POST", f"/v1/versions/acme/{_PROJECT}/{_V22}/unpublish"),
        ("DELETE", f"/v1/versions/acme/{_PROJECT}/{_V22}/freeze-schema"),
        ("DELETE", f"/v1/versions/acme/{_PROJECT}/{_V22}"),
    ]
    unpublish = [r for r in httpx_mock.get_requests() if r.method == "POST"][0]
    assert json.loads(unpublish.content) == {"reason": "spike", "silent": False, "keepTags": False}


def test_force_on_a_published_version_without_reason_is_a_usage_error(httpx_mock) -> None:
    _mock(httpx_mock, version={**_DRAFT, "published": True})
    result = runner.invoke(app, ["versions", "delete", "payments-api", "2.2.0", "--force", "--yes"], env=_ENV)
    assert result.exit_code == EXIT_USAGE
    assert "--reason is required" in result.stderr
    assert _calls(httpx_mock) == []


def test_an_unknown_version_is_a_usage_error(httpx_mock) -> None:
    httpx_mock.add_response(url=f"{_HOST}/projects/acme/by-slug/payments-api", json={"id": _PROJECT})
    httpx_mock.add_response(url=f"{_HOST}/versions/acme/{_PROJECT}", json=[_DRAFT])
    httpx_mock.add_response(url=_TAGS_URL, json=[])
    result = runner.invoke(app, ["versions", "delete", "payments-api", "9.9.9", "--yes"], env=_ENV)
    assert result.exit_code == EXIT_USAGE
    assert "No version or version tag '9.9.9'" in result.stderr


def test_a_server_refusal_uses_the_shared_error_mapping(httpx_mock) -> None:
    _mock(httpx_mock)
    httpx_mock.reset()
    httpx_mock.add_response(url=f"{_HOST}/projects/acme/by-slug/payments-api", json={"id": _PROJECT})
    httpx_mock.add_response(url=f"{_HOST}/versions/acme/{_PROJECT}", json=[_DRAFT])
    httpx_mock.add_response(url=_TAGS_URL, json=[])
    httpx_mock.add_response(method="GET", url=_FREEZE, json={"frozen": False})
    httpx_mock.add_response(url=f"{_HOST}/classes/acme/version/{_V22}/with-properties-tags", json=[])
    httpx_mock.add_response(url=f"{_HOST}/paths/acme/{_V22}", json=[])
    httpx_mock.add_response(
        method="DELETE",
        url=_RECORD,
        status_code=403,
        json={"detail": "This revision is locked by policy and cannot be deleted"},
    )
    result = runner.invoke(app, ["versions", "delete", "payments-api", "2.2.0", "--yes"], env=_ENV)
    assert result.exit_code == EXIT_USAGE
    assert "locked by policy" in result.stderr
