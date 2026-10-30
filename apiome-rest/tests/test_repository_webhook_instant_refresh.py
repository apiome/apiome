"""Webhook-instant refresh (RAR-6.3, #3540).

The acceptance criteria, each pinned without a network or a database:

* **a push touching a tracked spec triggers a refresh within seconds** — the delivery carries
  the files its commits touched, the dispatcher picks the tracked ones, and the route runs the
  refresh as a background task straight after answering the provider (no sweep tick to wait for);
* **only affected files refresh; gates still apply** — the refresh is limited to the pushed
  tracked paths, and still goes through the freshness comparator, the tenant quota, the refresh
  lock, the kill switch, the per-repository opt-out and the auto-pause;
* **falls back to the cadence if webhooks are unavailable** — a delivery with no usable file list
  (Bitbucket, a force push, a truncated commit list) refreshes nothing at once but leaves the
  repository due, as does any refresh that cannot run; only a completed refresh advances the
  cadence anchor. With no webhook at all the sweep is unchanged.

The scan walker is patched (as in ``test_repository_manual_refresh.py``); the dispatcher fake is
the REPO-4.3 suite's, extended with the tracked-paths read.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from test_repository_webhook_dispatch import _SECRET, _fake_decrypt, _push, _signed
from test_repository_webhook_dispatch import FakeDb as DispatchFakeDb

import app.repository_refresh_sweep as sweep
from app import repository_webhook_refresh as instant
from app.main import app
from app.repository_file_scan import ScanPass
from app.repository_webhook_dispatch import (
    OUTCOME_ENQUEUED,
    WEBHOOK_ACCEPTED_ACTION,
    WebhookIngestResult,
    ingest_webhook_delivery,
)
from app.repository_webhook_ingest import (
    GITHUB_PUSH_COMMIT_LIMIT,
    changed_paths_from_commits,
    parse_webhook_event,
)
from app.repository_webhook_refresh import (
    INSTANT_REFRESH_AUDIT_ACTION,
    REASON_LOCK_HELD,
    REASON_NOT_POLLABLE,
    REASON_QUOTA_EXHAUSTED,
    REASON_REFRESH_DISABLED,
    REASON_REFRESH_FAILED,
    REASON_REPOSITORY_MISSING,
    InstantRefreshResult,
    refresh_pushed_files,
    tracked_changed_paths,
)

_TENANT = "550e8400-e29b-41d4-a716-446655440000"
_REPO_ID = "880e8400-e29b-41d4-a716-446655440003"
_REPO = "octocat/hello-world"
_NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
_OLDER = (_NOW - timedelta(days=2)).isoformat()
_NEWER = (_NOW - timedelta(minutes=1)).isoformat()


def _commits(*changes: Dict[str, List[str]]) -> List[Dict[str, Any]]:
    return [{"id": f"c{i}", **change} for i, change in enumerate(changes)]


def _github_push(commits: Any = None, **extra: Any) -> Dict[str, Any]:
    payload = _push()
    if commits is not None:
        payload["commits"] = commits
    payload.update(extra)
    return payload


# ===========================================================================
# Which files a push changed
# ===========================================================================


def test_the_changed_files_are_every_path_the_commits_touched() -> None:
    commits = _commits(
        {"added": ["specs/new.yaml"], "modified": ["api/openapi.yaml"], "removed": []},
        {"added": [], "modified": ["api/openapi.yaml", "/README.md"], "removed": ["old.yaml"]},
    )
    assert changed_paths_from_commits(commits) == ("README.md", "api/openapi.yaml", "old.yaml", "specs/new.yaml")


@pytest.mark.parametrize("commits", [None, "x", [{"modified": "api/openapi.yaml"}]])
def test_a_missing_or_malformed_commit_list_is_unknown(commits) -> None:
    assert changed_paths_from_commits(commits) is None


def test_an_incomplete_list_is_unknown_and_an_empty_one_is_no_change() -> None:
    assert changed_paths_from_commits(_commits({"modified": ["a.yaml"]}), complete=False) is None
    assert changed_paths_from_commits([]) == ()


def test_a_github_push_carries_its_changed_files() -> None:
    payload = _github_push(_commits({"modified": ["api/openapi.yaml"]}))
    event = parse_webhook_event("github", "push", payload)
    assert event.changed_paths == ("api/openapi.yaml",)


def test_a_force_push_or_a_full_commit_list_is_unknown() -> None:
    forced = _github_push(_commits({"modified": ["api/openapi.yaml"]}), forced=True)
    assert parse_webhook_event("github", "push", forced).changed_paths is None
    capped = _github_push(_commits(*[{"modified": ["a.yaml"]}] * GITHUB_PUSH_COMMIT_LIMIT))
    assert parse_webhook_event("github", "push", capped).changed_paths is None


def test_a_gitlab_push_is_unknown_when_it_lists_fewer_commits_than_it_had() -> None:
    payload = {
        "object_kind": "push",
        "ref": "refs/heads/main",
        "after": "a" * 40,
        "project": {"path_with_namespace": _REPO},
        "commits": _commits({"modified": ["api/openapi.yaml"]}),
        "total_commits_count": 1,
    }
    assert parse_webhook_event("gitlab", "Push Hook", payload).changed_paths == ("api/openapi.yaml",)
    payload["total_commits_count"] = 25
    assert parse_webhook_event("gitlab", "Push Hook", payload).changed_paths is None


def test_a_bitbucket_push_lists_no_files() -> None:
    payload = {
        "repository": {"full_name": _REPO},
        "push": {"changes": [{"new": {"type": "branch", "name": "main", "target": {"hash": "a" * 40}}}]},
    }
    assert parse_webhook_event("bitbucket", "repo:push", payload).changed_paths is None


# ===========================================================================
# The dispatch decision
# ===========================================================================


class _TrackedDb(DispatchFakeDb):
    """The REPO-4.3 dispatcher fake, with tracked paths on ``main``."""

    def __init__(self, tracked_paths: Optional[List[str]] = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.tracked_paths = tracked_paths if tracked_paths is not None else ["api/openapi.yaml", "specs/orders.yaml"]

    def list_repository_import_spec_paths(self, repository_id, branch):
        return list(self.tracked_paths) if branch == "main" else []


def _deliver(db: DispatchFakeDb, payload: Dict[str, Any]) -> WebhookIngestResult:
    body, headers = _signed(payload)
    return ingest_webhook_delivery(db, provider="github", raw_body=body, headers=headers)


def test_a_push_touching_a_tracked_spec_names_it_for_an_instant_refresh() -> None:
    db = _TrackedDb()
    result = _deliver(db, _github_push(_commits({"modified": ["api/openapi.yaml", "src/main.py"]})))

    assert result.outcome == OUTCOME_ENQUEUED
    assert result.instant_refresh_paths == ("api/openapi.yaml",)
    assert (result.tenant_id, result.repository_id, result.branch) == (_TENANT, _REPO_ID, "main")
    # The repository is still made due, so the sweep is the fallback.
    assert db.polls_due == [_REPO_ID]
    audit = next(a for a in db.audits if a["action"] == WEBHOOK_ACCEPTED_ACTION)
    assert audit["detail"]["instantRefreshFiles"] == 1


def test_a_push_touching_no_tracked_spec_refreshes_nothing_at_once() -> None:
    result = _deliver(_TrackedDb(), _github_push(_commits({"modified": ["src/main.py"]})))
    assert result.instant_refresh_paths == ()


def test_a_push_without_a_file_list_falls_back_to_the_cadence() -> None:
    db = _TrackedDb()
    result = _deliver(db, _github_push())
    assert result.instant_refresh_paths == () and result.poll_due is True
    assert db.polls_due == [_REPO_ID]


def test_a_repository_that_cannot_be_polled_gets_no_instant_refresh() -> None:
    result = _deliver(_TrackedDb(pollable=False), _github_push(_commits({"modified": ["api/openapi.yaml"]})))
    assert result.instant_refresh_paths == ()


def test_tracked_changed_paths_intersects_with_the_tracked_files() -> None:
    db = _TrackedDb()
    assert tracked_changed_paths(db, _REPO_ID, "main", None) is None
    assert tracked_changed_paths(db, _REPO_ID, "main", []) == ()
    assert tracked_changed_paths(db, _REPO_ID, "main", ["specs/orders.yaml", "x", "api/openapi.yaml"]) == (
        "api/openapi.yaml",
        "specs/orders.yaml",
    )


# ===========================================================================
# The instant refresh
# ===========================================================================


def _candidate(path: str, *, newer: bool) -> Dict[str, Any]:
    """A refresh candidate row, newer than its last import or not."""
    return {
        "import_spec_id": f"spec-{path}",
        "tenant_id": _TENANT,
        "repository_id": _REPO_ID,
        "branch": "main",
        "path": path,
        "project_id": "p1",
        "source_kind": "openapi-3",
        "format_override": None,
        "content_type": "application/yaml",
        "options_json": {"naming_convention": "camelCase"},
        "spec_schema_version": 1,
        "created_by": "u1",
        "last_imported_commit_sha": "old",
        "last_imported_committed_at": _OLDER,
        "last_imported_blob_sha": "blob-old",
        "remote_commit_sha": "new" if newer else "old",
        "remote_committed_at": _NEWER if newer else _OLDER,
        "remote_blob_sha": "blob-new" if newer else "blob-old",
    }


class _RefreshDb:
    """The ``Database`` surface the instant refresh touches."""

    def __init__(self, *, repo: Optional[Dict[str, Any]] = None, candidates=None, lock_free: bool = True) -> None:
        self.repo = repo if repo is not None else {
            "id": _REPO_ID, "tenant_id": _TENANT, "provider": "github",
            "auto_refresh_enabled": True, "refresh_paused_at": None,
        }
        self.candidates = candidates if candidates is not None else [
            _candidate("api/openapi.yaml", newer=True),
            _candidate("specs/orders.yaml", newer=True),
            _candidate("specs/stable.yaml", newer=False),
        ]
        self.lock_free = lock_free
        self.enqueued: List[Dict[str, Any]] = []
        self.scanned: List[str] = []
        self.refreshed: List[str] = []
        self.locks: List[str] = []
        self.audits: List[Dict[str, Any]] = []

    def get_tenant_repository(self, tenant_id, repository_id):
        return dict(self.repo) if self.repo else None

    def list_repository_refresh_candidates(self, repository_id, branch):
        return list(self.candidates)

    def enqueue_repository_refresh_job(self, **kwargs):
        self.enqueued.append(kwargs)
        return {"id": f"job-{kwargs['path']}", **kwargs}

    def try_acquire_repository_refresh_lock(self, repository_id):
        if self.lock_free:
            self.locks.append("acquired")
        return self.lock_free

    def release_repository_refresh_lock(self, repository_id):
        self.locks.append("released")

    def mark_repository_refreshed(self, repository_id):
        self.refreshed.append(repository_id)
        return True

    def insert_workflow_audit(self, tenant_id, project_id, version_id, action, outcome, actor, detail):
        self.audits.append({"action": action, "outcome": outcome, "detail": detail})


@pytest.fixture(autouse=True)
def _secret_recovers(monkeypatch):
    """Decrypt the dispatcher fake's ciphertext to the known secret, as the REPO-4.3 suite does."""
    monkeypatch.setattr(
        "app.repository_webhook_subscriptions.decrypt_signing_secret",
        _fake_decrypt({b"ciphertext": _SECRET}),
    )


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Replace the branch walk, the quota and the telemetry with in-memory stand-ins."""

    def _fake_scan(db, repo_row, branch):
        db.scanned.append(branch)
        return ScanPass(total_files=3, importable_count=3, completed=True, resumed=False)

    monkeypatch.setattr(sweep, "scan_repository_branch_into_index", _fake_scan)
    monkeypatch.setattr("app.repository_refresh_quota.load_tenant_refresh_quota_tracker", lambda db: None)
    monkeypatch.setattr(sweep, "_record_poll_telemetry", lambda *a, **k: None)
    monkeypatch.setattr("app.config.settings.refresh_enabled", True)


def _refresh(db: _RefreshDb, paths=("api/openapi.yaml",)) -> InstantRefreshResult:
    return refresh_pushed_files(db, tenant_id=_TENANT, repository_id=_REPO_ID, branch="main", paths=paths)


def test_only_the_pushed_files_are_refreshed() -> None:
    """RAR-6.3 acceptance: specs/orders.yaml is newer too, but the push did not touch it."""
    db = _RefreshDb()
    result = _refresh(db)

    assert result == InstantRefreshResult(ran=True, enqueued=1, skipped=0, deferred=0)
    assert [job["path"] for job in db.enqueued] == ["api/openapi.yaml"]
    assert db.enqueued[0]["options_json"] == {"naming_convention": "camelCase"}  # the stored spec rides along
    assert db.scanned == ["main"]


def test_the_freshness_gate_still_applies() -> None:
    db = _RefreshDb()
    result = _refresh(db, paths=("specs/stable.yaml",))
    assert (result.ran, result.enqueued, result.skipped) == (True, 0, 1)
    assert db.enqueued == []


def test_a_completed_refresh_advances_the_anchor_and_releases_the_lock() -> None:
    db = _RefreshDb()
    _refresh(db)
    assert db.refreshed == [_REPO_ID]
    assert db.locks == ["acquired", "released"]
    [audit] = db.audits
    assert audit["action"] == INSTANT_REFRESH_AUDIT_ACTION and audit["outcome"] == "success"
    assert audit["detail"]["paths"] == ["api/openapi.yaml"] and audit["detail"]["enqueued"] == 1


@pytest.mark.parametrize(
    ("setup", "reason"),
    [
        (lambda db, mp: mp.setattr("app.config.settings.refresh_enabled", False), REASON_REFRESH_DISABLED),
        (lambda db, mp: setattr(db, "repo", {}), REASON_REPOSITORY_MISSING),
        (lambda db, mp: db.repo.update(auto_refresh_enabled=False), REASON_NOT_POLLABLE),
        (lambda db, mp: db.repo.update(refresh_paused_at="2026-10-29T00:00:00Z"), REASON_NOT_POLLABLE),
        (lambda db, mp: setattr(db, "lock_free", False), REASON_LOCK_HELD),
    ],
)
def test_a_refresh_that_cannot_run_leaves_the_repository_due(monkeypatch, setup, reason) -> None:
    db = _RefreshDb()
    setup(db, monkeypatch)
    result = _refresh(db)
    assert result == InstantRefreshResult(ran=False, reason=reason)
    assert db.enqueued == [] and db.refreshed == [] and db.scanned == []
    assert db.audits[0]["outcome"] == "skipped" and db.audits[0]["detail"]["reason"] == reason


def test_an_exhausted_quota_leaves_the_repository_due(monkeypatch) -> None:
    class _Spent:
        def is_exhausted(self, tenant_id):
            return True

    monkeypatch.setattr("app.repository_refresh_quota.load_tenant_refresh_quota_tracker", lambda db: _Spent())
    db = _RefreshDb()
    assert _refresh(db).reason == REASON_QUOTA_EXHAUSTED
    assert db.enqueued == [] and db.refreshed == []


def test_the_quota_bounds_the_refresh_and_deferred_files_keep_the_repository_due(monkeypatch) -> None:
    class _OneLeft:
        consumed = 0

        def is_exhausted(self, tenant_id):
            return False

        def remaining(self, tenant_id):
            return 1

        def consume(self, tenant_id, jobs):
            _OneLeft.consumed += jobs

    monkeypatch.setattr("app.repository_refresh_quota.load_tenant_refresh_quota_tracker", lambda db: _OneLeft())
    db = _RefreshDb()
    result = _refresh(db, paths=("api/openapi.yaml", "specs/orders.yaml"))
    assert (result.enqueued, result.deferred) == (1, 1)
    assert _OneLeft.consumed == 1
    assert db.refreshed == []  # the deferred file is the sweep's
    assert db.locks == ["acquired", "released"]


def test_a_failed_rescan_leaves_the_repository_due_and_releases_the_lock(monkeypatch) -> None:
    def _boom(db, repo_row, branch):
        raise RuntimeError("GitHub said no")

    monkeypatch.setattr(sweep, "scan_repository_branch_into_index", _boom)
    db = _RefreshDb()
    result = _refresh(db)
    assert result == InstantRefreshResult(ran=False, reason=REASON_REFRESH_FAILED)
    assert db.refreshed == [] and db.locks == ["acquired", "released"]


def test_no_paths_is_a_no_op() -> None:
    db = _RefreshDb()
    assert _refresh(db, paths=()) == InstantRefreshResult(ran=True)
    assert db.locks == [] and db.audits == []


def test_the_background_task_uses_and_closes_its_own_connection(monkeypatch) -> None:
    db = _RefreshDb()
    closed: List[bool] = []
    db.close = lambda: closed.append(True)  # type: ignore[attr-defined]
    monkeypatch.setattr("app.database.Database", lambda: db)
    instant.run_instant_refresh(tenant_id=_TENANT, repository_id=_REPO_ID, branch="main", paths=("api/openapi.yaml",))
    assert [job["path"] for job in db.enqueued] == ["api/openapi.yaml"] and closed == [True]


# ===========================================================================
# The route runs it right after answering
# ===========================================================================

client = TestClient(app)


def _post() -> Any:
    body, headers = _signed(_github_push(_commits({"modified": ["api/openapi.yaml"]})))
    return client.post("/v1/repositories/webhook/github", content=body, headers={**headers,
                                                                                "Content-Type": "application/json"})


def test_the_route_schedules_the_instant_refresh_after_the_reply() -> None:
    ran: List[Dict[str, Any]] = []
    result = WebhookIngestResult(
        outcome=OUTCOME_ENQUEUED, jobs_enqueued=1, repository_id=_REPO_ID, tenant_id=_TENANT, branch="main",
        poll_due=True, instant_refresh_paths=("api/openapi.yaml",),
    )
    with patch("app.repository_webhook_routes.ingest_webhook_delivery", return_value=result), patch(
        "app.repository_webhook_routes.run_instant_refresh", side_effect=lambda **kw: ran.append(kw)
    ):
        response = _post()

    assert response.status_code == 200
    # The receipt stays thin: it does not say which tracked files the push touched.
    assert response.json() == {"accepted": True, "outcome": "enqueued", "reason": None, "jobsEnqueued": 1}
    assert ran == [{"tenant_id": _TENANT, "repository_id": _REPO_ID, "branch": "main", "paths": ("api/openapi.yaml",)}]


def test_the_route_schedules_nothing_without_tracked_changes() -> None:
    ran: List[Dict[str, Any]] = []
    result = WebhookIngestResult(outcome=OUTCOME_ENQUEUED, repository_id=_REPO_ID, tenant_id=_TENANT, branch="main")
    with patch("app.repository_webhook_routes.ingest_webhook_delivery", return_value=result), patch(
        "app.repository_webhook_routes.run_instant_refresh", side_effect=lambda **kw: ran.append(kw)
    ):
        assert _post().status_code == 200
    assert ran == []
