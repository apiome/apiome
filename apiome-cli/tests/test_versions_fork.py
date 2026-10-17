"""``apiome versions fork`` (CLI 4.4, #3211).

The rules (:mod:`apiome_cli.version_fork`) and the command against a mocked REST API: the source
resolves by label, UUID or version tag; ``--to`` must be a plain release strictly greater than the
source unless ``--allow-lesser``; a label the target already has is exit 6 (before or from the
server's ``409 version_exists``); ``--dry-run`` reports the class/property counts that would be
copied and sends nothing; ``--include-tags`` recreates the source's tags on the fork; ``--json``
prints the new version record. A fork is cross-project: ``--into`` the same project is refused.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from apiome_cli.exit_codes import EXIT_SUCCESS, EXIT_USAGE, EXIT_VERSION_EXISTS
from apiome_cli.main import app
from apiome_cli.version_fork import (
    ForkError,
    check_new_version,
    copy_counts,
    find_source_version,
    parse_release,
    render_summary,
    tags_to_copy,
)

runner = CliRunner()

_ENV = {
    "APIOME_API_KEY": "obj_test_key",
    "APIOME_BASE_URL": "http://localhost:8000",
    "APIOME_TENANT_ID": "acme-corp",
}
_HOST = "http://localhost:8000/v1"
_SRC = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_TGT = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
_V20 = "11111111-1111-4111-8111-111111111111"
_V21 = "22222222-2222-4222-8222-222222222222"
_NEW = "99999999-9999-4999-8999-999999999999"

_SOURCE_VERSIONS = [
    {"id": _V21, "version_id": "2.1.0", "created_at": "2026-10-02T00:00:00Z"},
    {"id": _V20, "version_id": "2.0.0", "created_at": "2026-10-01T00:00:00Z"},
]
_SOURCE_TAGS = [
    {"id": "t1", "name": "stable", "version_id": _V21, "message": "GA", "channel": "stable"},
    {"id": "t2", "name": "old", "version_id": _V20},
]
_CLASSES = [
    {"name": "Charge", "properties": [{"name": "id"}, {"name": "amount"}]},
    {"name": "Refund", "properties": [{"name": "id"}]},
]
_PATHS = [{"id": "p1", "pathname": "/charges"}, {"id": "p2", "pathname": "/refunds"}]


def _mock_reads(httpx_mock, *, target_versions=()) -> None:
    """Serve every read a fork makes; optional, since refusals stop before the later ones."""
    routes = {
        f"{_HOST}/projects/acme-corp/by-slug/payments-api": {"id": _SRC},
        f"{_HOST}/projects/acme-corp/by-slug/sandbox": {"id": _TGT},
        f"{_HOST}/versions/acme-corp/{_SRC}": _SOURCE_VERSIONS,
        f"{_HOST}/version-tags/acme-corp/{_SRC}": _SOURCE_TAGS,
        f"{_HOST}/versions/acme-corp/{_TGT}": list(target_versions),
        f"{_HOST}/classes/acme-corp/version/{_V21}/with-properties-tags": _CLASSES,
        f"{_HOST}/paths/acme-corp/{_V21}": _PATHS,
    }
    for url, payload in routes.items():
        httpx_mock.add_response(
            url=url, method="GET", json=payload, is_optional=True, is_reusable=True
        )


def _fork(*args: str) -> object:
    return runner.invoke(
        app,
        ["versions", "fork", "payments-api", *args],
        env=_ENV,
    )


def _posts(httpx_mock) -> list:
    return [r for r in httpx_mock.get_requests() if r.method == "POST"]


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


def test_releases_parse_with_or_without_v() -> None:
    assert parse_release("v2.1.0") == (2, 1, 0)
    assert parse_release("2.1.0") == (2, 1, 0)
    assert parse_release("3.0.0-rc.1") is None
    assert parse_release("latest") is None


def test_the_new_version_must_be_greater_unless_allowed() -> None:
    assert check_new_version("v3.0.0", "2.1.0", allow_lesser=False) == "3.0.0"
    assert check_new_version("2.1.1", "v2.1.0", allow_lesser=False) == "2.1.1"
    with pytest.raises(ForkError, match="must be greater"):
        check_new_version("2.1.0", "2.1.0", allow_lesser=False)
    with pytest.raises(ForkError, match="must be greater"):
        check_new_version("1.9.9", "2.1.0", allow_lesser=False)
    assert check_new_version("1.0.0", "2.1.0", allow_lesser=True) == "1.0.0"
    # A source label that is not a release version cannot be compared, so it is not enforced.
    assert check_new_version("1.0.0", "experimental", allow_lesser=False) == "1.0.0"


def test_prerelease_targets_are_refused_with_the_reason() -> None:
    with pytest.raises(ForkError, match="pre-release"):
        check_new_version("3.0.0-rc.1", "2.1.0", allow_lesser=False)


def test_the_source_resolves_by_uuid_label_or_tag() -> None:
    assert find_source_version(_SOURCE_VERSIONS, _SOURCE_TAGS, _V20).matched_by == "id"
    match = find_source_version(_SOURCE_VERSIONS, _SOURCE_TAGS, "v2.1.0")
    assert (match.version["id"], match.matched_by) == (_V21, "label")
    match = find_source_version(_SOURCE_VERSIONS, _SOURCE_TAGS, "old")
    assert (match.version["id"], match.matched_by) == (_V20, "tag")
    with pytest.raises(ForkError, match="No version or version tag"):
        find_source_version(_SOURCE_VERSIONS, _SOURCE_TAGS, "9.9.9")


def test_counts_and_tags() -> None:
    assert copy_counts(_CLASSES) == (2, 3)
    assert [t["name"] for t in tags_to_copy(_SOURCE_TAGS, _V21)] == ["stable"]


def test_summary_states_that_paths_are_not_copied() -> None:
    text = render_summary(
        dry_run=False,
        source="payments-api@2.1.0",
        target="sandbox@3.0.0",
        classes=24,
        properties=142,
        source_paths=18,
        new_id="vr_3a91",
    )
    assert text.splitlines() == [
        "✔ Forked payments-api@2.1.0 → sandbox@3.0.0 (vr_3a91)",
        "  Classes copied:    24",
        "  Properties copied: 142",
        "  Paths:             not copied (18 in the source)",
        "  State:             draft",
    ]


# ---------------------------------------------------------------------------
# The command
# ---------------------------------------------------------------------------


def test_fork_posts_the_source_revision_and_prints_the_summary(httpx_mock, tmp_path) -> None:
    notes_file = tmp_path / "CHANGELOG.md"
    notes_file.write_text("## 3.0.0\n- Removes /charges", encoding="utf-8")
    _mock_reads(httpx_mock)
    httpx_mock.add_response(
        url=f"{_HOST}/versions/acme-corp/{_TGT}/fork",
        method="POST",
        json={"id": _NEW, "version_id": "3.0.0", "published": False},
    )
    result = _fork(
        "v2.1.0", "--into", "sandbox", "--to", "v3.0.0",
        "--notes", "Major: removes legacy /charges", "--notes-file", str(notes_file),
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    body = json.loads(_posts(httpx_mock)[0].content)
    assert body == {
        "sourceRevisionId": _V21,
        "versionId": "3.0.0",
        "shortMessage": "Major: removes legacy /charges",
        "changelog": "## 3.0.0\n- Removes /charges",
    }
    assert f"✔ Forked payments-api@2.1.0 → sandbox@3.0.0 ({_NEW})" in result.stdout
    assert "Classes copied:    2" in result.stdout
    assert "Properties copied: 3" in result.stdout
    assert "not copied (2 in the source)" in result.stdout


def test_json_returns_the_new_version_record(httpx_mock) -> None:
    _mock_reads(httpx_mock)
    record = {"id": _NEW, "version_id": "3.0.0", "published": False}
    httpx_mock.add_response(url=f"{_HOST}/versions/acme-corp/{_TGT}/fork", method="POST", json=record)
    result = runner.invoke(
        app,
        ["--json", "versions", "fork", "payments-api", "2.1.0", "--into", "sandbox", "--to", "3.0.0"],
        env=_ENV,
    )
    assert json.loads(result.stdout) == record


def test_dry_run_reports_counts_and_sends_nothing(httpx_mock) -> None:
    _mock_reads(httpx_mock)
    result = _fork("stable", "--into", "sandbox", "--to", "3.0.0", "--dry-run", "--include-tags")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "Would fork payments-api@2.1.0 → sandbox@3.0.0" in result.stdout
    assert "Classes to copy:    2" in result.stdout
    assert "Tags to copy:       stable" in result.stdout
    assert _posts(httpx_mock) == []


def test_dry_run_json(httpx_mock) -> None:
    _mock_reads(httpx_mock)
    result = runner.invoke(
        app,
        ["--json", "versions", "fork", "payments-api", "2.1.0", "--into", "sandbox", "--to", "3.0.0", "--dry-run"],
        env=_ENV,
    )
    payload = json.loads(result.stdout)
    assert (payload["dryRun"], payload["classes"], payload["properties"]) == (True, 2, 3)
    assert (payload["sourcePaths"], payload["pathsCopied"]) == (2, 0)
    assert payload["target"]["versionId"] == "3.0.0"


def test_include_tags_recreates_them_and_reports_a_taken_name(httpx_mock) -> None:
    _mock_reads(httpx_mock)
    httpx_mock.add_response(
        url=f"{_HOST}/versions/acme-corp/{_TGT}/fork", method="POST", json={"id": _NEW, "version_id": "3.0.0"}
    )
    httpx_mock.add_response(
        url=f"{_HOST}/version-tags/acme-corp/{_TGT}", method="POST", status_code=409, json={"detail": "exists"}
    )
    result = _fork("2.1.0", "--into", "sandbox", "--to", "3.0.0", "--include-tags")
    assert result.exit_code == EXIT_SUCCESS, result.output
    tag_post = json.loads(_posts(httpx_mock)[1].content)
    assert tag_post == {"version_id": _NEW, "name": "stable", "message": "GA", "channel": "stable"}
    assert "skipped, name taken: stable" in result.stdout


def test_an_existing_label_in_the_target_is_exit_6_before_forking(httpx_mock) -> None:
    _mock_reads(httpx_mock, target_versions=[{"id": "x", "version_id": "3.0.0"}])
    result = _fork("2.1.0", "--into", "sandbox", "--to", "v3.0.0")
    assert result.exit_code == EXIT_VERSION_EXISTS == 6
    assert "already exists" in result.stderr
    assert _posts(httpx_mock) == []


def test_a_server_version_exists_conflict_is_exit_6(httpx_mock) -> None:
    _mock_reads(httpx_mock)
    httpx_mock.add_response(
        url=f"{_HOST}/versions/acme-corp/{_TGT}/fork",
        method="POST",
        status_code=409,
        json={"detail": {"code": "version_exists", "message": "Version 3.0.0 already exists in this project."}},
    )
    result = _fork("2.1.0", "--into", "sandbox", "--to", "3.0.0")
    assert result.exit_code == EXIT_VERSION_EXISTS


def test_a_lesser_version_is_refused_unless_allowed(httpx_mock) -> None:
    _mock_reads(httpx_mock)
    result = _fork("2.1.0", "--into", "sandbox", "--to", "2.0.0")
    assert result.exit_code == EXIT_USAGE
    assert "--allow-lesser" in result.stderr
    assert _posts(httpx_mock) == []


def test_forking_into_the_same_project_is_refused(httpx_mock) -> None:
    httpx_mock.add_response(
        url=f"{_HOST}/projects/acme-corp/by-slug/payments-api", json={"id": _SRC}, is_reusable=True
    )
    result = _fork("2.1.0", "--into", "payments-api", "--to", "3.0.0")
    assert result.exit_code == EXIT_USAGE
    assert "different project" in result.stderr


def test_an_unknown_source_is_a_usage_error(httpx_mock) -> None:
    _mock_reads(httpx_mock)
    result = _fork("9.9.9", "--into", "sandbox", "--to", "10.0.0")
    assert result.exit_code == EXIT_USAGE
    assert "No version or version tag '9.9.9'" in result.stderr
