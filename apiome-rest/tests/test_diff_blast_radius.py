"""The blast-radius line on breaking changes of the diff gate — CDG-3.6 (#5971).

Unit tests: the summary and its sentence (``app.diff_blast_radius``), the markdown sub-bullet
(``render_changelog_markdown``) and the ``blastRadius`` flag of ``POST /v1/diff/{t}/classified``,
with the CDG-3.3 traversal replaced by canned answers.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.blast_radius import BlastRadiusRequest
from app.changelog_generator import Changelog, ChangelogEntry, render_changelog_markdown
from app.declared_dependencies import DependencyValidationError
from app.diff_blast_radius import (
    MAX_ANNOTATED_POINTERS,
    BlastRadiusTeam,
    annotate_breaking_changes,
    summarize_blast_radius,
    summary_line,
)
from app.main import app

client = TestClient(app)

REMOVED = "/paths/~1pets~1{id}"


def _consumer(cid: str, team: Optional[str] = None, depth: int = 1) -> Dict[str, Any]:
    owner = {"slug": team, "name": team.title(), "status": "confirmed"} if team else None
    return {"kind": "consumer", "id": cid, "slug": cid, "depth": depth, "owner": owner}


def _answer(direct: List[Dict[str, Any]], transitive: List[Dict[str, Any]] = (), runs: int = 0, truncated=False):
    return {
        "direct": list(direct),
        "transitive": list(transitive),
        "invalidated_evidence": {"verification_runs": [{"run_id": f"r{i}"} for i in range(runs)]},
        "truncated": truncated,
    }


# ---------------------------------------------------------------------------------------------
# The sentence
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "consumers, teams, runs, truncated, expected",
    [
        (
            3,
            ["mobile", "payments"],
            1,
            False,
            "affects 3 consumers across 2 teams (mobile, payments); 1 verification run invalidated",
        ),
        (1, ["payments"], 2, False, "affects 1 consumer across 1 team (payments); 2 verification runs invalidated"),
        (2, [], 0, False, "affects 2 consumers; no verification runs invalidated"),
        (0, [], 0, False, "affects no registered consumers; no verification runs invalidated"),
        (0, [], 3, False, "affects no registered consumers; 3 verification runs invalidated"),
        (
            2000,
            ["a"],
            4,
            True,
            "affects at least 2000 consumers across 1 team (a); at least 4 verification runs invalidated",
        ),
    ],
)
def test_summary_line(consumers, teams, runs, truncated, expected) -> None:
    assert summary_line(consumers, [BlastRadiusTeam(slug=t) for t in teams], runs, truncated=truncated) == expected


def test_summary_counts_distinct_consumers_and_their_teams() -> None:
    answer = _answer(
        [
            _consumer("c1", "payments"),
            _consumer("c2", "mobile"),
            {"kind": "project", "id": "p2", "owner": {"slug": "infra"}},
        ],
        [_consumer("c3", "payments", depth=2), _consumer("c1", "payments", depth=2), _consumer("c4")],
        runs=2,
    )
    summary = summarize_blast_radius(answer)
    assert summary.consumers == 4
    # Only consumers' owners count; the project's team does not.
    assert [team.slug for team in summary.teams] == ["mobile", "payments"]
    assert summary.teams[1].name == "Payments"
    assert summary.verification_runs == 2
    assert summary.line == "affects 4 consumers across 2 teams (mobile, payments); 2 verification runs invalidated"


def test_summary_serializes_with_camel_case() -> None:
    summary = summarize_blast_radius(_answer([_consumer("c1", "payments")], runs=1, truncated=True))
    assert summary.model_dump(by_alias=True) == {
        "consumers": 1,
        "teams": [{"slug": "payments", "name": "Payments"}],
        "verificationRuns": 1,
        "truncated": True,
        "line": "affects at least 1 consumer across 1 team (payments); at least 1 verification run invalidated",
    }


def test_summary_of_an_empty_answer() -> None:
    summary = summarize_blast_radius({})
    assert (summary.consumers, summary.teams, summary.verification_runs) == (0, [], 0)


# ---------------------------------------------------------------------------------------------
# Annotating a diff
# ---------------------------------------------------------------------------------------------


def _change(pointer: str, severity: str = "breaking") -> SimpleNamespace:
    return SimpleNamespace(pointer=pointer, severity=severity)


def test_each_breaking_pointer_is_asked_once_against_the_base() -> None:
    calls: List[BlastRadiusRequest] = []

    def fake(db: Any, tenant_id: str, request: BlastRadiusRequest) -> Dict[str, Any]:
        calls.append(request)
        return _answer([_consumer("c1", "payments")], runs=1)

    changes = [
        _change("/paths/~1a/get"),
        _change("/paths/~1a/get"),
        _change("/paths/~1b/get", "non-breaking"),
        _change("/paths/~1c/get"),
        _change("", "breaking"),
    ]
    with patch("app.diff_blast_radius.blast_radius", side_effect=fake):
        result = annotate_breaking_changes(object(), "tenant-1", "proj-1", "base-rev", changes)
    assert [c.pointers for c in calls] == [("/paths/~1a/get",), ("/paths/~1c/get",)]
    assert {(c.kind, c.entity, c.version) for c in calls} == {("project", "proj-1", "base-rev")}
    assert set(result.by_pointer) == {"/paths/~1a/get", "/paths/~1c/get"}
    assert result.meta().model_dump() == {"annotated": 2, "skipped": 0, "failed": 0, "limit": MAX_ANNOTATED_POINTERS}
    assert result.lines()["/paths/~1a/get"].startswith("affects 1 consumer")


def test_pointers_past_the_bound_are_skipped() -> None:
    changes = [_change(f"/paths/~1p{i}/get") for i in range(5)]
    with patch("app.diff_blast_radius.blast_radius", return_value=_answer([])) as fake:
        result = annotate_breaking_changes(object(), "t", "p", None, changes, limit=3)
    assert fake.call_count == 3 and result.skipped == 2 and len(result.by_pointer) == 3


def test_a_failing_pointer_is_counted_not_raised() -> None:
    def fake(db: Any, tenant_id: str, request: BlastRadiusRequest) -> Dict[str, Any]:
        if request.pointers == ("/paths/~1bad/get",):
            raise DependencyValidationError("graph-invalid", "nope")
        return _answer([])

    with patch("app.diff_blast_radius.blast_radius", side_effect=fake):
        result = annotate_breaking_changes(
            object(), "t", "p", None, [_change("/paths/~1bad/get"), _change("/paths/~1ok/get")]
        )
    assert result.failed == 1 and list(result.by_pointer) == ["/paths/~1ok/get"]


# ---------------------------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------------------------


def _changelog() -> Changelog:
    return Changelog(
        from_version="1.0.0",
        to_version="1.1.0",
        entries=[
            ChangelogEntry(
                severity="breaking",
                path_group="/paths/~1pets",
                pointer="/paths/~1pets/get",
                rule_id="r1",
                summary="Removed.",
            ),
            ChangelogEntry(
                severity="non-breaking",
                path_group="/paths/~1pets",
                pointer="/paths/~1pets/post",
                rule_id="r2",
                summary="Added.",
            ),
        ],
        counts={"total": 2, "breaking": 1, "non-breaking": 1},
    )


def test_markdown_puts_the_line_under_each_breaking_row() -> None:
    md = render_changelog_markdown(
        _changelog(),
        annotations={
            "/paths/~1pets/get": "affects 1 consumer; no verification runs invalidated",
            "/paths/~1pets/post": "never shown",
        },
    )
    lines = md.splitlines()
    row = next(i for i, line in enumerate(lines) if "`/paths/~1pets/get`" in line)
    assert lines[row + 1] == "  - Blast radius: affects 1 consumer; no verification runs invalidated"
    assert "never shown" not in md


def test_markdown_without_annotations_is_unchanged() -> None:
    assert render_changelog_markdown(_changelog()) == render_changelog_markdown(_changelog(), annotations={})
    assert "Blast radius" not in render_changelog_markdown(_changelog())


# ---------------------------------------------------------------------------------------------
# The REST flag
# ---------------------------------------------------------------------------------------------

_PROJECT = {"id": "proj-1", "tenant_id": "tenant-1", "slug": "pets", "description": "d", "metadata": "{}"}
_BASE = {"id": "base-rev", "project_id": "proj-1", "version_id": "1.0.0"}
_HEAD = {"id": "head-rev", "project_id": "proj-1", "version_id": "1.1.0"}
_SPEC = {
    "openapi": "3.1.0",
    "info": {"title": "Pets", "version": "1.0.0"},
    "paths": {
        "/pets": {"get": {"responses": {"200": {"description": "ok"}}}},
        "/pets/{id}": {"get": {"responses": {"200": {"description": "ok"}}}},
    },
}
_HEAD_SPEC = {
    "openapi": "3.1.0",
    "info": {"title": "Pets", "version": "1.1.0"},
    "paths": {
        "/pets": {"get": {"responses": {"200": {"description": "ok"}}, "description": "Lists pets."}},
    },
}


@pytest.fixture
def mock_auth():
    app.dependency_overrides[validate_authentication] = lambda: {
        "tenant_id": "tenant-1",
        "user_id": "user-1",
        "auth_method": "jwt",
    }
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def _call(body_extra: Dict[str, Any], *, accept: str = "application/json", permission=None, answer=None):
    with (
        patch("app.classified_diff_routes.db") as mock_db,
        patch("app.classified_diff_routes.openapi_for_revision", side_effect=[_SPEC, _HEAD_SPEC]),
        patch(
            "app.diff_blast_radius.blast_radius",
            return_value=answer
            or _answer(
                [_consumer("c1", "payments"), _consumer("c2", "mobile")], [_consumer("c3", "payments", 2)], runs=1
            ),
        ) as fake,
    ):
        if permission:
            mock_db.user_has_permission.side_effect = permission
        else:
            mock_db.user_has_permission.return_value = True
        mock_db.get_project_by_slug.return_value = _PROJECT
        mock_db.get_version_by_version_id.side_effect = lambda pid, ver, tid: (
            _BASE if ver == "1.0.0" else _HEAD if ver == "1.1.0" else None
        )
        response = client.post(
            "/v1/diff/acme/classified",
            json={
                "base": {"project": "pets", "version": "1.0.0"},
                "head": {"project": "pets", "version": "1.1.0"},
                **body_extra,
            },
            headers={"Authorization": "Bearer x", "Accept": accept},
        )
    return response, fake


def test_the_flag_annotates_breaking_changes_only(mock_auth) -> None:
    r, fake = _call({"blastRadius": True})
    assert r.status_code == 200, r.text
    data = r.json()
    removed = next(c for c in data["changes"] if c["ruleId"] == "ctg.path_removed")
    assert removed["blastRadius"] == {
        "consumers": 3,
        "teams": [{"slug": "mobile", "name": "Mobile"}, {"slug": "payments", "name": "Payments"}],
        "verificationRuns": 1,
        "truncated": False,
        "line": "affects 3 consumers across 2 teams (mobile, payments); 1 verification run invalidated",
    }
    for change in data["changes"]:
        if change["severity"] != "breaking":
            assert "blastRadius" not in change
    assert data["blastRadius"]["annotated"] >= 1 and data["blastRadius"]["skipped"] == 0
    request = fake.call_args.args[2]
    assert (request.kind, request.entity, request.version) == ("project", "proj-1", "base-rev")


def test_snake_case_flag_is_accepted(mock_auth) -> None:
    r, fake = _call({"blast_radius": True})
    assert r.status_code == 200 and fake.called


def test_without_the_flag_the_response_has_no_blast_radius_keys(mock_auth) -> None:
    r, fake = _call({})
    assert r.status_code == 200, r.text
    data = r.json()
    assert "blastRadius" not in data
    assert all("blastRadius" not in change for change in data["changes"])
    # Fields that are null by design still serialize.
    assert data["consumers"] is None and "before" in data["changes"][0]
    fake.assert_not_called()


def test_the_flag_requires_projects_view(mock_auth) -> None:
    r, fake = _call({"blastRadius": True}, permission=lambda t, u, resource, action: resource != "projects")
    assert r.status_code == 403
    fake.assert_not_called()


def test_markdown_carries_the_line(mock_auth) -> None:
    r, _ = _call({"blastRadius": True}, accept="text/markdown")
    assert r.status_code == 200, r.text
    assert (
        "  - Blast radius: affects 3 consumers across 2 teams (mobile, payments); 1 verification run invalidated"
        in r.text
    )


def test_markdown_says_when_pointers_were_skipped(mock_auth) -> None:
    from app import classified_diff_routes

    original = classified_diff_routes.annotate_breaking_changes

    def bounded(*args: Any, **kwargs: Any):
        return original(*args, limit=0, **kwargs)

    with patch("app.classified_diff_routes.annotate_breaking_changes", side_effect=bounded):
        r, fake = _call({"blastRadius": True}, accept="text/markdown")
    assert r.status_code == 200, r.text
    assert "Blast radius:" not in r.text
    assert "more were not checked" in r.text
    fake.assert_not_called()
