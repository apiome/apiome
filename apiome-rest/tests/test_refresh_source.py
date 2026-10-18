"""The refresh-source protocol and its Git implementation (CDG-1.1, #5952).

The Git path became the first :class:`~app.refresh_source.RefreshSource` without a behaviour
change. These tests pin that with goldens: the job a :class:`GitBranchRefreshSource` asks the
sweep to enqueue for a stale file, and the worker metadata the RAR-4.1 executor builds from that
job, are compared byte for byte with fixtures captured from the pre-protocol code path.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app import repository_refresh_sweep as sweep
from app.models import SpecImportProjectTarget, SpecImportVersionTarget
from app.refresh_source import (
    ERROR_CLASS_AUTH,
    ERROR_CLASS_NOT_FOUND,
    ERROR_CLASS_RATE_LIMITED,
    ERROR_CLASS_UNAVAILABLE,
    ERROR_CLASS_UNEXPECTED,
    FreshnessKey,
    GitBranchRefreshSource,
    RefreshCandidate,
    RefreshSource,
    RefreshSourceError,
    decide_refresh,
    error_class_for_status,
)
from app.repository_file_scan import ScanPass
from app.repository_refresh_executor import build_auto_refresh_import_metadata

_FIXTURES = Path(__file__).parent / "fixtures" / "refresh_source"

_OLD = datetime(2026, 1, 1, tzinfo=timezone.utc)
_NEW = datetime(2026, 2, 1, tzinfo=timezone.utc)


def _candidate_row(path: str, **overrides: Any) -> Dict[str, Any]:
    """A ``list_repository_refresh_candidates`` row for a stale file."""
    row: Dict[str, Any] = {
        "import_spec_id": "spec-1",
        "tenant_id": "t1",
        "repository_id": "repo-1",
        "branch": "main",
        "path": path,
        "project_id": "proj-1",
        "source_kind": "openapi-3",
        "format_override": "swagger",
        "content_type": "application/json",
        "options_json": {"classPrefix": "Api", "selectedSchemas": ["Pet"]},
        "spec_schema_version": 1,
        "created_by": "user-1",
        "last_imported_commit_sha": "aaa",
        "last_imported_committed_at": _OLD,
        "last_imported_blob_sha": "blob-old",
        "remote_commit_sha": "bbb",
        "remote_committed_at": _NEW,
        "remote_blob_sha": "blob-new",
    }
    row.update(overrides)
    return row


class _Db:
    """The two calls the Git source makes."""

    def __init__(self, rows: List[Dict[str, Any]]) -> None:
        self.rows = rows
        self.scanned: List[str] = []

    def list_repository_refresh_candidates(self, repository_id: str, branch: str) -> List[Dict[str, Any]]:
        return list(self.rows)


@pytest.fixture(autouse=True)
def _no_walk(monkeypatch):
    """Replace the GitHub walk; the source reads it from the sweep module at call time."""

    def _fake_scan(db, repo_row, branch):
        db.scanned.append(branch)
        return ScanPass(total_files=1, importable_count=1, completed=True, resumed=False)

    monkeypatch.setattr(sweep, "scan_repository_branch_into_index", _fake_scan)


_REPO = {"id": "repo-1", "tenant_id": "t1"}


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, ERROR_CLASS_AUTH),
        (403, ERROR_CLASS_AUTH),
        (404, ERROR_CLASS_NOT_FOUND),
        (429, ERROR_CLASS_RATE_LIMITED),
        (500, ERROR_CLASS_UNAVAILABLE),
        (503, ERROR_CLASS_UNAVAILABLE),
        (None, ERROR_CLASS_UNAVAILABLE),
        (418, ERROR_CLASS_UNEXPECTED),
    ],
)
def test_error_class_for_status(status, expected):
    assert error_class_for_status(status) == expected


def test_source_error_derives_its_class_and_keeps_an_explicit_one():
    assert RefreshSourceError("x", http_status=401).error_class == ERROR_CLASS_AUTH
    explicit = RefreshSourceError("x", http_status=401, error_class="credentials-unreadable")
    assert explicit.error_class == "credentials-unreadable"
    assert explicit.http_status == 401


def test_git_source_satisfies_the_protocol():
    assert isinstance(GitBranchRefreshSource(_Db([]), _REPO, "main"), RefreshSource)


def test_git_source_rescans_then_lists_candidates():
    db = _Db([_candidate_row("a.json"), _candidate_row("b.json")])
    source = GitBranchRefreshSource(db, _REPO, "main")
    candidates = source.list_candidates()
    assert db.scanned == ["main"]
    assert [c.remote_id for c in candidates] == ["a.json", "b.json"]
    assert candidates[0].revision == "bbb"
    assert candidates[0].updated_at == _NEW


def test_git_source_path_filter_keeps_one_file():
    db = _Db([_candidate_row("a.json"), _candidate_row("b.json")])
    source = GitBranchRefreshSource(db, _REPO, "main", path_filter="b.json")
    assert [c.remote_id for c in source.list_candidates()] == ["b.json"]


def test_git_freshness_key_is_commit_time_and_blob():
    source = GitBranchRefreshSource(_Db([]), _REPO, "main")
    key = source.freshness_key(RefreshCandidate(remote_id="a.json", raw=_candidate_row("a.json")))
    assert key == FreshnessKey(
        remote_updated_at=_NEW, remote_checksum="blob-new", last_updated_at=_OLD, last_checksum="blob-old"
    )


def test_decide_refresh_applies_the_newer_than_gate():
    source = GitBranchRefreshSource(_Db([]), _REPO, "main")
    stale = RefreshCandidate(remote_id="a", raw=_candidate_row("a"))
    same = RefreshCandidate(
        remote_id="b", raw=_candidate_row("b", remote_committed_at=_OLD, remote_blob_sha="blob-old")
    )
    assert decide_refresh(source, stale).should_refresh is True
    assert decide_refresh(source, same).should_refresh is False


def test_git_describe_names_the_repository_and_branch():
    source = GitBranchRefreshSource(_Db([]), _REPO, "main")
    assert source.describe() == {"kind": "git", "repositoryId": "repo-1", "branch": "main"}


def _jsonable(value: Any) -> Any:
    """Round-trip through JSON so timestamps compare as text, as the fixtures store them."""
    return json.loads(json.dumps(value, default=str, sort_keys=True))


def test_git_fetch_job_matches_the_pre_protocol_golden():
    """The enqueued job is exactly what the sweep enqueued before the protocol existed."""
    source = GitBranchRefreshSource(_Db([]), _REPO, "main")
    job = source.fetch(RefreshCandidate(remote_id="a.json", raw=_candidate_row("api/openapi.json")))
    golden = json.loads((_FIXTURES / "git_enqueue_job.json").read_text())
    assert _jsonable(job.fields) == golden


def test_executor_output_from_a_protocol_job_matches_the_golden():
    """RAR-4.1 hydration of a protocol-built job is byte-identical to the pre-protocol output."""
    source = GitBranchRefreshSource(_Db([]), _REPO, "main")
    job_row = dict(source.fetch(RefreshCandidate(remote_id="a", raw=_candidate_row("api/openapi.json"))).fields)
    job_row["id"] = "job-1"
    metadata = build_auto_refresh_import_metadata(
        job_row,
        project=SpecImportProjectTarget(name="Petstore", slug="petstore"),
        version=SpecImportVersionTarget(version_id="1.1.0"),
        existing_project_id="proj-1",
        parent_version_id="ver-1",
    )
    golden = json.loads((_FIXTURES / "git_executor_metadata.json").read_text())
    assert _jsonable(metadata.model_dump(mode="json")) == golden
