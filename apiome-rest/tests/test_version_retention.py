"""Version retention for live refresh (MFI-31.5, #4402).

Pins the acceptance criteria without a database:

* **History respects the policy** — only refresh-created versions count, the newest ``keep`` stay,
  older ones are soft-deleted with ``pruned_at`` and audited;
* **protected versions survive** — tagged, conversion-source, breaking drift and its baseline,
  locked, and the newest version (the protection SQL is pinned, the plan honours it);
* **diffs handle pruned gaps** — a pruned version answers 410 ``version-pruned`` on the classified
  diff and the version read, and a drift event whose baseline was pruned offers the nearest kept
  earlier version to compare with.

Plus the wiring: the refresh apply hook prunes with the item's ``keep_versions`` after recording
drift, and the refresh API reads and writes ``keepVersions`` (1–1000).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import version_retention as vr
from app.auth import validate_authentication
from app.database import db
from app.main import app

_TENANT = "11111111-1111-4111-8111-111111111111"
_ITEM = "22222222-2222-4222-8222-222222222222"
_WHEN = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)


def _vid(n: int) -> str:
    return f"00000000-0000-4000-8000-{n:012d}"


# --- the plan ---------------------------------------------------------------------------------


def test_the_newest_n_stay_and_older_ones_go():
    versions = [{"id": _vid(n)} for n in range(10, 0, -1)]  # newest first
    assert vr.plan_pruning(versions, 7, set()) == [_vid(3), _vid(2), _vid(1)]


def test_protected_versions_survive_and_do_not_extend_the_n():
    versions = [{"id": _vid(n)} for n in range(10, 0, -1)]
    assert vr.plan_pruning(versions, 7, {_vid(2), _vid(9)}) == [_vid(3), _vid(1)]


def test_keep_is_clamped():
    versions = [{"id": _vid(n)} for n in range(3, 0, -1)]
    assert vr.plan_pruning(versions, 0, set()) == [_vid(2), _vid(1)]  # at least one is kept
    assert vr.plan_pruning(versions, 5000, set()) == []


# --- pruning against a fake database -----------------------------------------------------------


class _Db:
    """Answers the three retention statements and records what it was asked."""

    def __init__(self, refresh_versions: List[str], protected: List[str]) -> None:
        self.refresh_versions = refresh_versions
        self.protected = protected
        self.calls: List[Tuple[str, Any]] = []
        self.audits: List[Dict[str, Any]] = []

    def execute_query(self, sql: str, params: Any = None) -> List[Dict[str, Any]]:
        flat = " ".join(sql.split())
        self.calls.append((flat, params))
        if flat.startswith("SELECT v.id, v.version_id, v.created_at"):
            return [
                {"id": vid, "version_id": f"label-{vid[-2:]}", "created_at": _WHEN} for vid in self.refresh_versions
            ]
        if "FROM apiome.version_tags" in flat:
            return [{"id": vid} for vid in self.protected]
        if flat.startswith("UPDATE apiome.versions v SET deleted_at"):
            return [{"id": vid, "version_id": f"label-{vid[-2:]}"} for vid in params[0]]
        raise AssertionError(flat)

    def insert_workflow_audit(self, tenant_id, project_id, version_id, action, outcome, actor_id, detail=None):
        self.audits.append({"action": action, "project_id": project_id, "actor": actor_id, "detail": detail})


def test_pruning_soft_deletes_the_overflow_and_audits_it():
    fake = _Db([_vid(n) for n in range(6, 0, -1)], protected=[_vid(2)])
    pruned = vr.prune_refresh_versions(fake, tenant_id=_TENANT, project_id=_ITEM, keep=3, actor_id="u-1")
    assert pruned == [_vid(3), _vid(1)]
    select, _ = fake.calls[0]
    assert "v.format_metadata ? 'refreshTrigger'" in select  # only refresh-created versions count
    assert "v.deleted_at IS NULL" in select and "ORDER BY v.created_at DESC" in select
    update, params = fake.calls[-1]
    assert "SET deleted_at = CURRENT_TIMESTAMP, pruned_at = CURRENT_TIMESTAMP" in update
    assert params == ([_vid(3), _vid(1)], _ITEM, _TENANT)
    assert fake.audits == [
        {
            "action": vr.AUDIT_PRUNED,
            "project_id": _ITEM,
            "actor": "u-1",
            "detail": {"keep": 3, "pruned": ["label-03", "label-01"]},
        }
    ]


def test_nothing_happens_within_the_limit():
    fake = _Db([_vid(n) for n in range(3, 0, -1)], protected=[])
    assert vr.prune_refresh_versions(fake, tenant_id=_TENANT, project_id=_ITEM, keep=3) == []
    assert len(fake.calls) == 1 and fake.audits == []


def test_the_protection_sql_covers_every_always_kept_kind():
    fake = _Db([], protected=[])
    vr.protected_version_ids(fake, _ITEM)
    sql, params = fake.calls[0]
    assert "FROM apiome.version_tags t" in sql
    assert "FROM apiome.conversion_provenance c" in sql and "c.source_version_id" in sql
    assert sql.count("e.severity = 'breaking'") == 2  # the breaking version and its baseline
    assert "e.parent_version_id" in sql
    assert "v.revision_locked IS TRUE" in sql
    assert "LIMIT 1" in sql  # the newest version
    assert params == (_ITEM,) * 6


def test_a_retention_failure_never_raises():
    class _Broken:
        def execute_query(self, *a, **k):
            raise RuntimeError("db down")

    assert vr.prune_refresh_versions_safely(_Broken(), tenant_id=_TENANT, project_id=_ITEM, keep=1) == []


# --- pruned gaps -------------------------------------------------------------------------------


class _PrunedDb:
    def __init__(self, row: Dict[str, Any] | None) -> None:
        self.row = row
        self.calls: List[Tuple[str, Any]] = []

    def execute_query(self, sql: str, params: Any = None) -> List[Dict[str, Any]]:
        self.calls.append((" ".join(sql.split()), params))
        return [self.row] if self.row else []


def test_a_pruned_version_raises_410_version_pruned():
    row = {"id": _vid(4), "version_id": "2026-10-01T06:00Z", "project_id": _ITEM, "pruned_at": _WHEN}
    with pytest.raises(HTTPException) as exc:
        vr.raise_if_pruned(_PrunedDb(row), _TENANT, _vid(4))
    assert exc.value.status_code == 410
    assert exc.value.detail["code"] == "version-pruned"
    assert exc.value.detail["versionLabel"] == "2026-10-01T06:00Z"
    assert exc.value.detail["prunedAt"] == _WHEN.isoformat()


def test_a_label_is_looked_up_within_its_project_and_unknown_refs_pass_through():
    fake = _PrunedDb(None)
    vr.raise_if_pruned(fake, _TENANT, "2026-10-01T06:00Z", _ITEM)  # nothing pruned: no raise
    sql, params = fake.calls[0]
    assert "v.project_id = %s::uuid AND v.version_id = %s" in sql and "v.pruned_at IS NOT NULL" in sql
    assert params == (_ITEM, "2026-10-01T06:00Z", _TENANT)
    fake.calls.clear()
    vr.raise_if_pruned(fake, "tenant-1", _vid(1))  # a test tenant id never reaches SQL
    vr.raise_if_pruned(fake, _TENANT, "1.0.0")  # a label without a project cannot be resolved
    assert fake.calls == []


def test_the_nearest_kept_earlier_version_is_the_fallback_baseline():
    fake = _PrunedDb({"id": _vid(2), "version_id": "1.0.0"})
    assert vr.nearest_live_earlier_version(fake, _ITEM, _vid(5)) == {"id": _vid(2), "version_id": "1.0.0"}
    sql, params = fake.calls[0]
    assert "v.deleted_at IS NULL" in sql and "(v.created_at, v.id) < (anchor.created_at, anchor.id)" in sql
    assert params == (_vid(5), _ITEM)


# --- routes ------------------------------------------------------------------------------------

client = TestClient(app)
_AUTH = {"tenant_id": _TENANT, "user_id": "33333333-3333-4333-8333-333333333333", "auth_method": "jwt"}


@pytest.fixture
def auth():
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def _pruned(*args, **kwargs):
    raise HTTPException(status_code=410, detail={"code": "version-pruned", "message": "pruned"})


def test_the_classified_diff_answers_410_for_a_pruned_base(auth):
    with (
        patch("app.classified_diff_routes.db") as mock_db,
        patch("app.classified_diff_routes.raise_if_pruned", side_effect=_pruned),
    ):
        mock_db.user_has_permission.return_value = True
        mock_db.get_project_by_slug.return_value = {"id": _ITEM, "tenant_id": _TENANT, "slug": "orders"}
        mock_db.get_version_by_version_id.return_value = None
        mock_db.get_version_by_id.return_value = None
        r = client.post(
            "/v1/diff/acme/classified",
            json={
                "base": {"project": "orders", "version": _vid(4)},
                "head": {"project": "orders", "version": "latest"},
            },
        )
    assert r.status_code == 410
    assert r.json()["detail"]["code"] == "version-pruned"


def test_the_version_read_answers_410_for_a_pruned_version(auth, monkeypatch):
    monkeypatch.setattr(db, "user_has_permission", lambda *a, **k: True)
    monkeypatch.setattr(db, "get_version_by_id", lambda *a, **k: None)
    calls = []
    monkeypatch.setattr("app.versions_routes.raise_if_pruned", lambda *a: calls.append(a) or _pruned())
    r = client.get(f"/v1/versions/acme/{_ITEM}/{_vid(4)}")
    assert r.status_code == 410, r.text
    assert calls and calls[0][2:] == (_vid(4), _ITEM)


def test_the_drift_api_offers_the_nearest_kept_version_when_the_baseline_was_pruned(monkeypatch):
    from app import catalog_drift_routes as routes

    monkeypatch.setattr(routes, "nearest_live_earlier_version", lambda d, p, v: {"id": _vid(1), "version_id": "1.0.0"})
    event = {
        "id": "e-1",
        "project_id": _ITEM,
        "version_id": _vid(5),
        "parent_version_id": _vid(4),
        "version_label": "2026-10-28T06:00Z",
        "parent_version_label": "2026-10-27T06:00Z",
        "severity": "safe",
        "counts": {},
        "change_count": 0,
        "changes": [],
        "trigger": "sweep",
        "notification": "none",
        "created_at": _WHEN,
    }
    kept = routes._event_out({**event, "parent_deleted": False, "parent_pruned": False})
    assert (kept.parent_version_pruned, kept.compare_base_version_id) == (False, _vid(4))
    pruned = routes._event_out({**event, "parent_deleted": True, "parent_pruned": True})
    assert pruned.parent_version_pruned is True
    assert (pruned.compare_base_version_id, pruned.compare_base_version_label) == (_vid(1), "1.0.0")
    body = pruned.model_dump(by_alias=True)
    assert body["parentVersionPruned"] is True and body["compareBaseVersionId"] == _vid(1)


# --- wiring ------------------------------------------------------------------------------------


def test_the_apply_hook_prunes_after_recording_drift_with_the_items_keep(monkeypatch):
    """A refresh-created version triggers pruning with the row's keep_versions, drift first."""
    from tests.test_catalog_refresh_apply import _SDL_V1, _SDL_V2, _apply, _discover_graphql, _FakeDb, _item, _revision

    order: List[str] = []
    monkeypatch.setattr("app.catalog_drift_service.record_refresh_drift", lambda db_, **kw: order.append("drift"))
    monkeypatch.setattr(
        "app.version_retention.prune_refresh_versions_safely",
        lambda db_, **kw: order.append(f"prune:{kw['keep']}:{kw['project_id']}") or [],
    )

    async def _pipeline(adapter, payload, **kwargs):
        from app.models import SpecImportJobResult, SpecImportJobStatus

        if payload["metadata"].get("options", {}).get("dry_run"):
            from app.import_source_pipeline import run_adapter_import_job

            return await run_adapter_import_job(adapter, payload, **kwargs)
        return SpecImportJobStatus(
            job_id="j",
            state="completed",
            percent=100,
            result=SpecImportJobResult(project_id=_ITEM, project_slug="o", version_id="v", version_record_id="rev-new"),
        )

    result = _discover_graphql(_SDL_V2, monkeypatch)
    monkeypatch.setattr("app.import_source_pipeline.run_adapter_import_job", _pipeline)
    monkeypatch.setattr("app.catalog_revision_change_report.generate_catalog_revision_change_report", lambda **kw: None)
    _apply(_FakeDb(_item(), [_revision(_SDL_V1)]), result, row={"keep_versions": 7})
    assert order[0] == "drift" and order[1].startswith("prune:7:")
