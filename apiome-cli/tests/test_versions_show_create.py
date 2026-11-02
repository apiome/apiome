"""``apiome versions show`` and ``apiome versions create`` (CLI 4.2 #3209 / 4.3 #3210, ported by #3177).

The rules (:mod:`apiome_cli.version_show`, :mod:`apiome_cli.version_create`) and both commands
against a mocked REST API.

``show`` resolves the version by label, UUID or version tag (saying which label a tag matched),
counts classes and paths with what changed against the previous published version, summarizes the
server's compatibility findings (skipped when there is no previous version or the server fails),
reports whether the schema is frozen, and prints absolute spec URLs; ``--json`` adds
``compatibility_summary`` and ``spec_urls`` to the version record.

``create`` cuts a draft: ``--version`` must be a plain release not already taken (exit 6),
``--notes`` / ``--notes-file`` are exclusive, classes are copied from ``--base`` or the latest
published version (or none with ``--empty``), and the request names the project's head as
``baseRevisionId`` (branch tip, or newest revision); a ``409 STALE_HEAD`` exits 1 with a re-run hint.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apiome_cli.exit_codes import (
    EXIT_ERROR,
    EXIT_SUCCESS,
    EXIT_USAGE,
    EXIT_VERSION_EXISTS,
)
from apiome_cli.main import app
from apiome_cli.version_create import (
    CreateError,
    VersionExists,
    build_body,
    check_label,
    default_base,
    expected_head,
    load_body,
    read_notes,
    stale_head_message,
)
from apiome_cli.version_show import (
    Delta,
    class_delta,
    compatibility_summary,
    path_delta,
    previous_version,
    render_show,
    spec_urls,
    state,
    tags_for,
)

runner = CliRunner()

_ENV = {
    "APIOME_API_KEY": "obj_test_key",
    "APIOME_BASE_URL": "http://localhost:8000",
    "APIOME_TENANT_ID": "acme-corp",
}
_HOST = "http://localhost:8000/v1"
_PRJ = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_V20 = "11111111-1111-4111-8111-111111111111"
_V21 = "22222222-2222-4222-8222-222222222222"
_V22 = "33333333-3333-4333-8333-333333333333"
_NEW = "99999999-9999-4999-8999-999999999999"

_VERSIONS = [
    {"id": _V22, "version_id": "2.2.0", "created_at": "2026-10-03T00:00:00Z", "published": False},
    {"id": _V21, "version_id": "2.1.0", "created_at": "2026-10-02T00:00:00Z", "published": True},
    {"id": _V20, "version_id": "2.0.0", "created_at": "2026-10-01T00:00:00Z", "published": True},
]
_TAGS = [
    {"id": "t1", "name": "stable", "version_id": _V21},
    {"id": "t2", "name": "latest", "version_id": _V21},
    {"id": "t3", "name": "old", "version_id": _V20},
]
_V21_RECORD = {
    "id": _V21,
    "project_id": _PRJ,
    "version_id": "2.1.0",
    "published": True,
    "published_at": "2026-10-04T12:42:00Z",
    "created_at": "2026-10-02T00:00:00Z",
    "creator_email": "kenji@example.com",
    "shortMessage": "Adds /refunds",
    "project_name": "Payments API",
    "project_slug": "payments-api",
}
_V20_CLASSES = [
    {"id": "c1", "name": "Charge", "properties": [{"id": "p1", "name": "amount", "data": {"type": "integer"}}]},
    {"id": "c2", "name": "Legacy", "properties": []},
]
_V21_CLASSES = [
    {"id": "c3", "name": "Charge", "properties": [{"id": "p2", "name": "amount", "data": {"type": "number"}}]},
    {"id": "c4", "name": "Refund", "properties": []},
]
_V20_PATHS = [{"id": "x1", "pathname": "/charges", "summary": "Charges"}]
_V21_PATHS = [{"id": "x2", "pathname": "/charges", "summary": "Charges"}, {"id": "x3", "pathname": "/refunds"}]


def _mock_show(httpx_mock, *, compat_status: int = 200) -> None:
    routes = {
        f"{_HOST}/projects/acme-corp/by-slug/payments-api": {"id": _PRJ},
        f"{_HOST}/versions/acme-corp/{_PRJ}": _VERSIONS,
        f"{_HOST}/version-tags/acme-corp/{_PRJ}": _TAGS,
        f"{_HOST}/versions/acme-corp/{_PRJ}/{_V21}": _V21_RECORD,
        f"{_HOST}/classes/acme-corp/version/{_V21}/with-properties-tags": _V21_CLASSES,
        f"{_HOST}/classes/acme-corp/version/{_V20}/with-properties-tags": _V20_CLASSES,
        f"{_HOST}/paths/acme-corp/{_V21}": _V21_PATHS,
        f"{_HOST}/paths/acme-corp/{_V20}": _V20_PATHS,
        f"{_HOST}/versions/acme-corp/{_PRJ}/{_V21}/freeze-schema": {"frozen": True},
    }
    for url, payload in routes.items():
        httpx_mock.add_response(url=url, method="GET", json=payload, is_optional=True, is_reusable=True)
    httpx_mock.add_response(
        url=f"{_HOST}/versions/acme-corp/{_PRJ}/compatibility",
        method="POST",
        status_code=compat_status,
        json={"findings": [{"category": "breaking"}, {"category": "safe"}, {"category": "safe"}]}
        if compat_status == 200
        else {"detail": "boom"},
        is_optional=True,
    )


def _show(*args: str):
    return runner.invoke(app, ["versions", "show", "payments-api", *args], env=_ENV)


def _json_show(*args: str):
    return runner.invoke(app, ["--json", "versions", "show", "payments-api", *args], env=_ENV)


# --- show: the rules ---------------------------------------------------------------------------


def test_previous_version_prefers_the_latest_older_published_one() -> None:
    assert previous_version(_VERSIONS, _VERSIONS[0])["id"] == _V21
    assert previous_version(_VERSIONS, _VERSIONS[1])["id"] == _V20
    assert previous_version(_VERSIONS, _VERSIONS[2]) is None
    drafts = [{**v, "published": False} for v in _VERSIONS]
    assert previous_version(drafts, drafts[0])["id"] == _V21


def test_class_and_path_deltas_ignore_ids_and_count_changes() -> None:
    assert class_delta(_V21_CLASSES, _V20_CLASSES) == Delta(total=2, added=1, removed=1, modified=1)
    assert path_delta(_V21_PATHS, _V20_PATHS) == Delta(total=2, added=1, removed=0, modified=0)
    assert class_delta(_V21_CLASSES, None) == Delta(total=2)


def test_compatibility_summary_counts_by_severity_or_says_why_it_was_skipped() -> None:
    base = {"version_id": "2.0.0"}
    report = {"findings": [{"category": "breaking"}, {"category": "unknown"}, {"category": "safe"}]}
    assert compatibility_summary(report, base) == {
        "base": "2.0.0", "breaking": 1, "warnings": 1, "info": 1, "skipped": None,
    }
    assert compatibility_summary(None, None)["skipped"] == "no previous version"
    assert "could not" in compatibility_summary(None, base)["skipped"]


def test_spec_urls_are_absolute_on_the_configured_server() -> None:
    urls = spec_urls("https://api.example.com/", "acme", "payments-api", "2.1.0")
    assert urls == {
        "openapi": "https://api.example.com/v1/schema/acme/payments-api/2.1.0",
        "swagger": "https://api.example.com/v1/swagger/acme/payments-api/2.1.0",
        "arazzo": "https://api.example.com/v1/arazzo/acme/payments-api/2.1.0",
        "jsonSchema": "https://api.example.com/v1/json/acme/payments-api/2.1.0",
    }


def test_state_and_tags() -> None:
    assert state({"published": True}) == "published"
    assert state({"published": False, "unpublishedAt": "2026-10-01"}) == "unpublished"
    assert state({}) == "draft"
    assert tags_for(_TAGS, _V21) == ["stable", "latest"]


def test_render_show_without_a_previous_version_prints_plain_counts() -> None:
    text = render_show(
        project_name="P",
        version={"version_id": "1.0.0"},
        tags=[],
        frozen=None,
        classes=Delta(total=3),
        paths=Delta(total=1),
        compatibility=compatibility_summary(None, None),
        urls={},
    )
    assert "Classes:      3" in text
    assert "not compared (no previous version)" in text
    assert "Frozen:       unknown" in text


# --- show: the command -------------------------------------------------------------------------


@pytest.mark.parametrize("ref", ["2.1.0", "v2.1.0", _V21])
def test_show_resolves_a_label_or_uuid(httpx_mock, ref: str) -> None:
    _mock_show(httpx_mock)
    result = _show(ref)
    assert result.exit_code == EXIT_SUCCESS, result.output
    out = result.output
    assert "Payments API v2.1.0  ★ stable, latest" in out
    assert "State:        published" in out
    assert "Created:      2026-10-02 00:00 by kenji@example.com" in out
    assert "Frozen:       yes" in out
    assert "Notes:        Adds /refunds" in out
    assert "Classes:      2     (1 added, 1 removed, 1 modified vs 2.0.0)" in out
    assert "Paths:        2     (1 added, 0 removed, 0 modified vs 2.0.0)" in out
    assert "Compatibility:1 breaking, 0 warnings, 2 info vs 2.0.0" in out
    assert "OpenAPI 3.1   →  http://localhost:8000/v1/schema/acme-corp/payments-api/2.1.0" in out


def test_show_by_tag_says_which_label_it_matched(httpx_mock) -> None:
    _mock_show(httpx_mock)
    result = _show("stable")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "(tag 'stable' → 2.1.0)" in result.output


def test_show_json_adds_the_summary_and_urls(httpx_mock) -> None:
    _mock_show(httpx_mock)
    result = _json_show("stable")
    assert result.exit_code == EXIT_SUCCESS, result.output
    document = json.loads(result.output)
    assert document["id"] == _V21
    assert document["matchedBy"] == "tag"
    assert document["frozen"] is True
    assert document["compatibility_summary"]["breaking"] == 1
    assert document["spec_urls"]["arazzo"].endswith("/v1/arazzo/acme-corp/payments-api/2.1.0")
    assert document["classes"] == {"total": 2, "added": 1, "removed": 1, "modified": 1}


def test_show_survives_a_failing_compatibility_call(httpx_mock) -> None:
    _mock_show(httpx_mock, compat_status=500)
    result = _show("2.1.0")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "not compared (the server could not compare the versions)" in result.output


def test_show_an_unknown_version_is_a_usage_error(httpx_mock) -> None:
    _mock_show(httpx_mock)
    result = _show("9.9.9")
    assert result.exit_code == EXIT_USAGE
    assert "No version or version tag '9.9.9'" in result.output


# --- create: the rules -------------------------------------------------------------------------


def test_check_label_normalizes_and_refuses_prereleases_and_taken_labels() -> None:
    assert check_label("v3.0.0", _VERSIONS) == "3.0.0"
    with pytest.raises(CreateError, match="pre-release"):
        check_label("2.2.0-rc.1", _VERSIONS)
    with pytest.raises(VersionExists, match="2.1.0 already exists"):
        check_label("2.1.0", _VERSIONS)


def test_read_notes(tmp_path: Path) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("# 3.0.0\n\n- café\n", encoding="utf-8")
    assert read_notes("Short note", None) == ("Short note", None)
    assert read_notes(None, changelog) == (None, "# 3.0.0\n\n- café\n")
    assert read_notes(None, None) == (None, None)
    with pytest.raises(CreateError, match="not both"):
        read_notes("x", changelog)
    binary = tmp_path / "b.md"
    binary.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(CreateError, match="not UTF-8"):
        read_notes(None, binary)


def test_load_body(tmp_path: Path) -> None:
    good = tmp_path / "v.json"
    good.write_text('{"author": "ci", "externalRef": "PR-7"}', encoding="utf-8")
    assert load_body(good) == {"author": "ci", "externalRef": "PR-7"}
    assert load_body(None) == {}
    bad = tmp_path / "bad.json"
    bad.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(CreateError, match="JSON object"):
        load_body(bad)


def test_expected_head_follows_the_server_rule() -> None:
    assert expected_head(_VERSIONS, [], None) == _V22
    assert expected_head([], [], None) is None
    one = [{"name": "main", "tip_version_id": _V21}]
    assert expected_head(_VERSIONS, one, None) == _V21
    two = one + [{"name": "next", "tip_version_id": _V22}]
    assert expected_head(_VERSIONS, two, "next") == _V22
    with pytest.raises(CreateError, match="pass --branch"):
        expected_head(_VERSIONS, two, None)
    with pytest.raises(CreateError, match="No branch 'nope'"):
        expected_head(_VERSIONS, two, "nope")


def test_default_base_is_the_latest_published_version() -> None:
    assert default_base(_VERSIONS)["id"] == _V21
    assert default_base([{**v, "published": False} for v in _VERSIONS]) is None


def test_build_body_lets_flags_win_over_the_file() -> None:
    body = build_body(
        from_file={"version_id": "0.0.1", "author": "ci", "baseRevisionId": "stale"},
        label="3.0.0",
        head=_V22,
        short_message="note",
        changelog=None,
        source_id=_V21,
        copy_paths=True,
        branch=None,
    )
    assert body == {
        "version_id": "3.0.0",
        "author": "ci",
        "baseRevisionId": _V22,
        "shortMessage": "note",
        "source_version_id": _V21,
        "copyPaths": True,
    }
    assert build_body(
        from_file={}, label="0.1.0", head=None, short_message=None, changelog=None,
        source_id=None, copy_paths=True, branch="main",
    ) == {"version_id": "0.1.0", "baseRevisionId": "", "branchName": "main"}


def test_stale_head_message_names_the_new_head() -> None:
    assert "moved to 2.3.0" in stale_head_message({"currentHead": {"versionId": "2.3.0"}})


# --- create: the command -----------------------------------------------------------------------


def _mock_create_reads(httpx_mock, *, branches=()) -> None:
    routes = {
        f"{_HOST}/projects/acme-corp/by-slug/payments-api": {"id": _PRJ},
        f"{_HOST}/versions/acme-corp/{_PRJ}": _VERSIONS,
        f"{_HOST}/version-tags/acme-corp/{_PRJ}": _TAGS,
        f"{_HOST}/versions/acme-corp/{_PRJ}/version-branches": list(branches),
    }
    for url, payload in routes.items():
        httpx_mock.add_response(url=url, method="GET", json=payload, is_optional=True, is_reusable=True)


def _create(*args: str, json_mode: bool = False):
    prefix = ["--json"] if json_mode else []
    return runner.invoke(app, [*prefix, "versions", "create", "payments-api", *args], env=_ENV)


def _posted(httpx_mock) -> dict:
    (request,) = [r for r in httpx_mock.get_requests() if r.method == "POST"]
    return json.loads(request.content)


def test_create_copies_the_latest_published_version_and_names_the_head(httpx_mock) -> None:
    _mock_create_reads(httpx_mock)
    httpx_mock.add_response(
        url=f"{_HOST}/versions/acme-corp/{_PRJ}",
        method="POST",
        json={"id": _NEW, "version_id": "3.0.0", "copied_classes": 4, "published": False},
    )
    result = _create("--version", "v3.0.0", "--notes", "Adds idempotency keys")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "Created draft 3.0.0" in result.output
    assert "copied 4 classes from v2.1.0" in result.output
    assert _posted(httpx_mock) == {
        "version_id": "3.0.0",
        "baseRevisionId": _V22,
        "shortMessage": "Adds idempotency keys",
        "source_version_id": _V21,
    }


def test_create_from_a_tagged_base_with_a_changelog_on_a_branch(httpx_mock, tmp_path: Path) -> None:
    notes = tmp_path / "CHANGELOG.md"
    notes.write_text("# 3.0.0", encoding="utf-8")
    _mock_create_reads(httpx_mock, branches=[{"name": "main", "tip_version_id": _V21}, {"name": "next", "tip_version_id": _V22}])
    httpx_mock.add_response(url=f"{_HOST}/versions/acme-corp/{_PRJ}", method="POST", json={"id": _NEW})
    result = _create(
        "--version", "3.0.0", "--notes-file", str(notes), "--base", "old", "--copy-paths", "--branch", "next",
        json_mode=True,
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert json.loads(result.output) == {"id": _NEW}
    assert _posted(httpx_mock) == {
        "version_id": "3.0.0",
        "baseRevisionId": _V22,
        "changelog": "# 3.0.0",
        "source_version_id": _V20,
        "copyPaths": True,
        "branchName": "next",
    }


def test_create_empty_copies_nothing(httpx_mock) -> None:
    _mock_create_reads(httpx_mock)
    httpx_mock.add_response(url=f"{_HOST}/versions/acme-corp/{_PRJ}", method="POST", json={"id": _NEW})
    result = _create("--version", "3.0.0", "--empty")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "source_version_id" not in _posted(httpx_mock)


def test_create_a_taken_label_is_exit_6_before_any_write(httpx_mock) -> None:
    _mock_create_reads(httpx_mock)
    result = _create("--version", "2.1.0")
    assert result.exit_code == EXIT_VERSION_EXISTS
    assert "already exists" in result.output
    assert not [r for r in httpx_mock.get_requests() if r.method == "POST"]


@pytest.mark.parametrize(
    "args,message",
    [
        (["--version", "3.0.0-rc.1"], "pre-release"),
        (["--version", "3.0.0", "--empty", "--base", "2.1.0"], "--base or --empty"),
        (["--version", "3.0.0", "--empty", "--copy-paths"], "--copy-paths needs a base"),
        (["--version", "3.0.0", "--base", "nope"], "No version or version tag 'nope'"),
    ],
)
def test_create_refuses_bad_arguments(httpx_mock, args, message) -> None:
    _mock_create_reads(httpx_mock)
    result = _create(*args)
    assert result.exit_code == EXIT_USAGE
    assert message in result.output


def test_create_reports_a_head_that_moved(httpx_mock) -> None:
    _mock_create_reads(httpx_mock)
    httpx_mock.add_response(
        url=f"{_HOST}/versions/acme-corp/{_PRJ}",
        method="POST",
        status_code=409,
        json={"detail": {"code": "STALE_HEAD", "currentHead": {"versionId": "2.3.0"}}},
    )
    result = _create("--version", "3.0.0")
    assert result.exit_code == EXIT_ERROR
    assert "moved to 2.3.0" in result.output
    assert "re-run" in result.output
