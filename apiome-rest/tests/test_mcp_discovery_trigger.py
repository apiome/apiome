"""Tests for the manual MCP discovery trigger + async job (V2-MCP-17.2 / MCAT-3.2, #3664).

Three layers, all DB-free:

* **Routes** — ``POST/GET .../endpoints/{id}/discover`` behaviour, tenant scoping, dedup
  signalling, and 404/422/401 edges (``trigger_discovery`` is patched so no task runs).
* **Engine** — the diff (``compute_version_change_rows``, which delegates to the canonical
  ``diff_surfaces`` engine), version persistence outcomes (first run / unchanged / changed),
  and the end-to-end job driver via an injected discovery runner (no network).
* **DB layer** — the discovery-job enqueue/dedup and version-persistence SQL against a
  fake cursor/connection, mirroring the doubles used by ``test_mcp_catalog_routes``.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app import mcp_credentials, mcp_discovery_engine
from app.auth import validate_authentication
from app.database import Database, format_mcp_version_tag
from app.main import app
from app.mcp_client import (
    DiscoveryListings,
    DiscoverySurface,
    InitializeResult,
    ServerInfo,
)

client = TestClient(app)

_JWT_T1 = {"tenant_id": "t1", "user_id": "user-1", "auth_method": "jwt"}
_NOW = datetime(2026, 6, 26, 12, 0, 0, tzinfo=timezone.utc)
_EP_UUID = "11111111-1111-1111-1111-111111111111"
_JOB_UUID = "22222222-2222-2222-2222-222222222222"

_ENDPOINT_ROW = {
    "id": _EP_UUID,
    "tenant_id": "t1",
    "name": "Acme Weather",
    "slug": "acme-weather",
    "endpoint_url": "https://mcp.acme.example/mcp",
    "transport": "streamable_http",
}

_JOB_ROW = {
    "id": _JOB_UUID,
    "endpoint_id": _EP_UUID,
    "tenant_id": "t1",
    "state": "queued",
    "trigger": "manual",
    "started_at": None,
    "finished_at": None,
    "error": None,
    "result": {},
    "created_at": _NOW,
}


@pytest.fixture(autouse=True)
def _default_auth():
    app.dependency_overrides[validate_authentication] = lambda: _JWT_T1
    yield
    app.dependency_overrides.pop(validate_authentication, None)


# ---------------------------------------------------------------------------
# Surface builders (reuse the real normalize types, like test_mcp_normalize)
# ---------------------------------------------------------------------------


def _tool(name: str, *, desc: str = "d") -> dict:
    return {"name": name, "description": desc, "inputSchema": {"type": "object"}}


def _surface(tools) -> DiscoverySurface:
    init = InitializeResult(
        protocol_version="2025-06-18",
        server_info=ServerInfo(name="srv", title="Srv", version="1.0"),
        capabilities={"tools": {}},
        instructions="be helpful",
        raw={},
    )
    listings = DiscoveryListings(tools=list(tools))
    return DiscoverySurface.from_discovery(init, listings)


# ===========================================================================
# ROUTES
# ===========================================================================


def _async_return(value):
    async def _fake(*_a, **_k):
        return value

    return _fake


def test_discover_trigger_returns_202_and_job():
    with patch("app.mcp_catalog_routes.db") as mdb, patch(
        "app.mcp_catalog_routes.trigger_discovery", _async_return((_JOB_ROW, False))
    ):
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        r = client.post(f"/v1/mcp/acme/endpoints/{_EP_UUID}/discover")
    assert r.status_code == 202
    body = r.json()
    assert body["success"] is True
    assert body["deduplicated"] is False
    assert body["job"]["id"] == _JOB_UUID
    assert body["job"]["state"] == "queued"
    assert body["job"]["trigger"] == "manual"


def test_discover_trigger_signals_deduplication():
    """A coalesced (already-active) job is returned with deduplicated=True."""
    running = {**_JOB_ROW, "state": "running"}
    with patch("app.mcp_catalog_routes.db") as mdb, patch(
        "app.mcp_catalog_routes.trigger_discovery", _async_return((running, True))
    ):
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        r = client.post(f"/v1/mcp/acme/endpoints/{_EP_UUID}/discover")
    assert r.status_code == 202
    assert r.json()["deduplicated"] is True
    assert r.json()["job"]["state"] == "running"


def test_discover_trigger_endpoint_not_found_404():
    with patch("app.mcp_catalog_routes.db") as mdb, patch(
        "app.mcp_catalog_routes.trigger_discovery"
    ) as mtrig:
        mdb.get_mcp_endpoint.return_value = None
        r = client.post(f"/v1/mcp/acme/endpoints/{_EP_UUID}/discover")
    assert r.status_code == 404
    mtrig.assert_not_called()


def test_discover_trigger_scoped_to_token_tenant():
    with patch("app.mcp_catalog_routes.db") as mdb, patch(
        "app.mcp_catalog_routes.trigger_discovery", _async_return((_JOB_ROW, False))
    ):
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        client.post(f"/v1/mcp/other-slug/endpoints/{_EP_UUID}/discover")
        mdb.get_mcp_endpoint.assert_called_once_with("t1", _EP_UUID)


def test_discover_trigger_rejects_non_uuid_422():
    with patch("app.mcp_catalog_routes.db") as mdb:
        r = client.post("/v1/mcp/acme/endpoints/not-a-uuid/discover")
    assert r.status_code == 422
    mdb.get_mcp_endpoint.assert_not_called()


def test_discover_trigger_requires_authentication():
    app.dependency_overrides.pop(validate_authentication, None)
    r = client.post(f"/v1/mcp/acme/endpoints/{_EP_UUID}/discover")
    assert r.status_code == 401


def test_get_discovery_job_ok():
    job = {**_JOB_ROW, "state": "completed", "result": {"version_id": "ver-1"}}
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_discovery_job.return_value = job
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP_UUID}/discover/{_JOB_UUID}")
    assert r.status_code == 200
    body = r.json()
    assert body["job"]["state"] == "completed"
    assert body["job"]["result"]["version_id"] == "ver-1"
    mdb.get_mcp_discovery_job.assert_called_once_with("t1", _JOB_UUID)


def test_get_discovery_job_endpoint_mismatch_404():
    """A job that belongs to a different endpoint is not reachable under this one."""
    job = {**_JOB_ROW, "endpoint_id": "99999999-9999-9999-9999-999999999999"}
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_discovery_job.return_value = job
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP_UUID}/discover/{_JOB_UUID}")
    assert r.status_code == 404


def test_get_discovery_job_not_found_404():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_discovery_job.return_value = None
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP_UUID}/discover/{_JOB_UUID}")
    assert r.status_code == 404


def test_list_discovery_jobs_ok():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.list_mcp_discovery_jobs.return_value = [_JOB_ROW]
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP_UUID}/discover")
    assert r.status_code == 200
    assert len(r.json()["jobs"]) == 1
    mdb.list_mcp_discovery_jobs.assert_called_once_with("t1", _EP_UUID)


def test_list_discovery_jobs_endpoint_not_found_404():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = None
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP_UUID}/discover")
    assert r.status_code == 404


# ===========================================================================
# ENGINE — diff (wired to the canonical diff_surfaces engine, MCAT-4.2)
# ===========================================================================


def _version_row(surface: DiscoverySurface, *, version_id: str = "ver-prev", version_seq: int = 1) -> dict:
    """A ``mcp_endpoint_versions`` row mirroring ``surface`` (as the store would hold it).

    Carries the surface-level identity columns from :meth:`DiscoverySurface.to_version_row`
    so the engine can reconstruct the prior surface and diff against it without any phantom
    server-metadata change.
    """
    version_row = surface.to_version_row()
    return {
        "id": version_id,
        "version_seq": version_seq,
        "version_tag": f"2026-06-26T12:0{version_seq}Z",
        **version_row,
    }


def _db_with_previous(surface: DiscoverySurface, *, version_id: str = "ver-prev") -> MagicMock:
    """A ``db`` double whose previous snapshot is ``surface`` (rows + version row)."""
    mdb = MagicMock()
    mdb.get_mcp_capability_items.return_value = surface.to_capability_rows(version_id)
    return mdb


def test_diff_first_run_marks_all_added():
    surface = _surface([_tool("alpha"), _tool("bravo")])
    changes = mcp_discovery_engine.compute_version_change_rows(None, surface)
    assert {c["change_type"] for c in changes} == {"added"}
    assert {c["item_name"] for c in changes} == {"alpha", "bravo"}
    # The first version has no prior surface: every change is a capability addition and the
    # synthetic "server metadata changed from null" rows are suppressed.
    assert all(c["item_type"] == "tool" for c in changes)
    # Additions carry the new item projection under "after" only.
    assert all("after" in c["detail"] and "before" not in c["detail"] for c in changes)


def test_diff_detects_added_removed_modified():
    prev_surface = _surface(
        [_tool("alpha", desc="d"), _tool("bravo", desc="old"), _tool("charlie")]
    )
    surface = _surface([_tool("alpha", desc="d"), _tool("bravo", desc="new"), _tool("delta")])
    mdb = _db_with_previous(prev_surface, version_id="ver-prev")
    with patch.object(mcp_discovery_engine, "db", mdb):
        changes = mcp_discovery_engine.compute_version_change_rows(
            _version_row(prev_surface), surface
        )
    mdb.get_mcp_capability_items.assert_called_once_with("ver-prev")
    by_name = {c["item_name"]: c for c in changes}
    assert "alpha" not in by_name  # unchanged → no row
    assert by_name["bravo"]["change_type"] == "modified"
    assert by_name["bravo"]["detail"]["before"]["description"] == "old"
    assert by_name["bravo"]["detail"]["after"]["description"] == "new"
    assert by_name["charlie"]["change_type"] == "removed"
    assert "before" in by_name["charlie"]["detail"]
    assert by_name["delta"]["change_type"] == "added"


def test_diff_no_change_returns_empty():
    surface = _surface([_tool("alpha")])
    mdb = _db_with_previous(surface)
    with patch.object(mcp_discovery_engine, "db", mdb):
        changes = mcp_discovery_engine.compute_version_change_rows(_version_row(surface), surface)
    assert changes == []


def test_diff_captures_server_metadata_change():
    """A server-version bump with identical capabilities is recorded as a server change.

    This is new with MCAT-4.3's switch to the semantic ``diff_surfaces`` engine: the prior
    raw-item diff saw only capability items and would have missed it.
    """
    prev_surface = _surface([_tool("alpha")])
    bumped = InitializeResult(
        protocol_version="2025-06-18",
        server_info=ServerInfo(name="srv", title="Srv", version="2.0"),  # was 1.0
        capabilities={"tools": {}},
        instructions="be helpful",
        raw={},
    )
    surface = DiscoverySurface.from_discovery(bumped, DiscoveryListings(tools=[_tool("alpha")]))
    mdb = _db_with_previous(prev_surface)
    with patch.object(mcp_discovery_engine, "db", mdb):
        changes = mcp_discovery_engine.compute_version_change_rows(
            _version_row(prev_surface), surface
        )
    server_rows = [c for c in changes if c["item_type"] == "server"]
    assert [c["item_name"] for c in server_rows] == ["server_version"]
    assert server_rows[0]["change_type"] == "modified"
    assert server_rows[0]["detail"]["before"] == "1.0"
    assert server_rows[0]["detail"]["after"] == "2.0"


# ===========================================================================
# ENGINE — persistence outcomes
# ===========================================================================


def test_persist_first_run_creates_version_one():
    surface = _surface([_tool("alpha")])
    mdb = MagicMock()
    mdb.get_latest_mcp_endpoint_version.return_value = None
    mdb.record_mcp_discovery_version.return_value = {
        "version_id": "ver-1",
        "version_seq": 1,
        "version_tag": "2026-06-26T12:00Z",
    }
    with patch.object(mcp_discovery_engine, "db", mdb):
        result = mcp_discovery_engine._persist_outcome(
            _JOB_UUID, _ENDPOINT_ROW, surface, _NOW
        )
    assert result["changed"] is True
    assert result["version_id"] == "ver-1"
    assert result["version_seq"] == 1
    # The date/time tag from the persisted snapshot is surfaced on the job result (#3671).
    assert result["version_tag"] == "2026-06-26T12:00Z"
    # Per-kind capability counts ride along so the import UI can summarize the discovery.
    assert result["counts"] == {
        "tool": 1,
        "resource": 0,
        "resource_template": 0,
        "prompt": 0,
        "total": 1,
    }
    # First run: every item is an "added" change.
    kwargs = mdb.record_mcp_discovery_version.call_args.kwargs
    assert kwargs["change_rows"][0]["change_type"] == "added"
    mdb.finish_mcp_discovery_job.assert_called_once()
    assert mdb.finish_mcp_discovery_job.call_args.args[1] == "completed"


def test_persist_unchanged_makes_no_new_version():
    surface = _surface([_tool("alpha")])
    fp = surface.fingerprint()
    mdb = MagicMock()
    mdb.get_latest_mcp_endpoint_version.return_value = {
        "id": "ver-7",
        "version_seq": 7,
        "version_tag": "2026-06-26T11:07Z",
        "surface_fingerprint": fp,
    }
    with patch.object(mcp_discovery_engine, "db", mdb):
        result = mcp_discovery_engine._persist_outcome(
            _JOB_UUID, _ENDPOINT_ROW, surface, _NOW
        )
    assert result["changed"] is False
    assert result["version_id"] == "ver-7"
    # Unchanged: the existing snapshot's tag is echoed (no new version, no new tag).
    assert result["version_tag"] == "2026-06-26T11:07Z"
    # The summary counts reflect the (unchanged) surface that was re-discovered.
    assert result["counts"]["tool"] == 1
    assert result["counts"]["total"] == 1
    mdb.record_mcp_discovery_version.assert_not_called()
    mdb.touch_mcp_endpoint_discovery.assert_called_once()
    assert mdb.touch_mcp_endpoint_discovery.call_args.kwargs["status"] == "unchanged"


def test_persist_changed_diffs_against_previous_items():
    prev_surface = _surface([_tool("alpha")])
    surface = _surface([_tool("alpha"), _tool("bravo")])
    mdb = _db_with_previous(prev_surface, version_id="ver-1")
    mdb.get_latest_mcp_endpoint_version.return_value = _version_row(
        prev_surface, version_id="ver-1", version_seq=1
    )
    mdb.record_mcp_discovery_version.return_value = {"version_id": "ver-2", "version_seq": 2}
    with patch.object(mcp_discovery_engine, "db", mdb):
        result = mcp_discovery_engine._persist_outcome(
            _JOB_UUID, _ENDPOINT_ROW, surface, _NOW
        )
    assert result["changed"] is True
    assert result["version_seq"] == 2
    mdb.get_mcp_capability_items.assert_called_once_with("ver-1")
    change_rows = mdb.record_mcp_discovery_version.call_args.kwargs["change_rows"]
    # Only "bravo" is new relative to the previous snapshot (server metadata unchanged).
    assert [c["item_name"] for c in change_rows] == ["bravo"]


def test_persist_records_per_kind_counts_for_summary():
    """A mixed surface tallies each capability kind on the result for the import-summary UI."""
    init = InitializeResult(
        protocol_version="2025-06-18",
        server_info=ServerInfo(name="srv", title="Srv", version="1.0"),
        capabilities={"tools": {}, "resources": {}, "prompts": {}},
        instructions="be helpful",
        raw={},
    )
    listings = DiscoveryListings(
        tools=[_tool("alpha"), _tool("bravo")],
        resources=[{"uri": "file:///r1"}],
        resource_templates=[{"uriTemplate": "file:///{path}"}],
        prompts=[{"name": "p1"}, {"name": "p2"}, {"name": "p3"}],
    )
    surface = DiscoverySurface.from_discovery(init, listings)
    mdb = MagicMock()
    mdb.get_latest_mcp_endpoint_version.return_value = None
    mdb.record_mcp_discovery_version.return_value = {
        "version_id": "ver-1",
        "version_seq": 1,
        "version_tag": "2026-06-26T12:00Z",
    }
    with patch.object(mcp_discovery_engine, "db", mdb):
        result = mcp_discovery_engine._persist_outcome(
            _JOB_UUID, _ENDPOINT_ROW, surface, _NOW
        )
    assert result["counts"] == {
        "tool": 2,
        "resource": 1,
        "resource_template": 1,
        "prompt": 3,
        "total": 7,
    }


# ===========================================================================
# ENGINE — score auto-capture on a new version (V2-MCP-21.4, #3685)
# ===========================================================================


def test_persist_captures_quality_score_for_new_version():
    """A changed surface persists a version AND auto-captures its lint score (best-effort)."""
    surface = _surface([_tool("alpha")])
    mdb = MagicMock()
    mdb.get_latest_mcp_endpoint_version.return_value = None
    mdb.record_mcp_discovery_version.return_value = {
        "version_id": "ver-1",
        "version_seq": 1,
        "version_tag": "2026-06-26T12:00Z",
    }
    with patch.object(mcp_discovery_engine, "db", mdb):
        mcp_discovery_engine._persist_outcome(_JOB_UUID, _ENDPOINT_ROW, surface, _NOW)
    mdb.set_mcp_version_score.assert_called_once()
    call = mdb.set_mcp_version_score.call_args
    assert call.args[0] == "ver-1"
    # A real score/grade/fingerprint computed from the surface is persisted for drill-down.
    assert isinstance(call.kwargs["score"], int)
    assert call.kwargs["grade"] in {"A", "B", "C", "D", "F"}
    assert isinstance(call.kwargs["report"], dict)
    assert call.kwargs["report_fingerprint"]


def test_persist_unchanged_does_not_capture_a_score():
    """No new version means no re-score: the unchanged path must not touch the score table."""
    surface = _surface([_tool("alpha")])
    mdb = MagicMock()
    mdb.get_latest_mcp_endpoint_version.return_value = {
        "id": "ver-7",
        "version_seq": 7,
        "version_tag": "2026-06-26T11:07Z",
        "surface_fingerprint": surface.fingerprint(),
    }
    with patch.object(mcp_discovery_engine, "db", mdb):
        mcp_discovery_engine._persist_outcome(_JOB_UUID, _ENDPOINT_ROW, surface, _NOW)
    mdb.set_mcp_version_score.assert_not_called()


def test_score_capture_is_best_effort_and_never_breaks_discovery():
    """A failure while scoring/persisting must not propagate out of the committed discovery."""
    surface = _surface([_tool("alpha")])
    mdb = MagicMock()
    mdb.get_latest_mcp_endpoint_version.return_value = None
    mdb.record_mcp_discovery_version.return_value = {
        "version_id": "ver-1",
        "version_seq": 1,
        "version_tag": "2026-06-26T12:00Z",
    }
    mdb.set_mcp_version_score.side_effect = RuntimeError("scores table down")
    with patch.object(mcp_discovery_engine, "db", mdb):
        result = mcp_discovery_engine._persist_outcome(
            _JOB_UUID, _ENDPOINT_ROW, surface, _NOW
        )
    # The version was still recorded and the job still completes despite the scoring failure.
    assert result["changed"] is True
    assert result["version_id"] == "ver-1"
    mdb.finish_mcp_discovery_job.assert_called_once()


def test_capture_helper_persists_score_directly():
    """The capture helper scores the in-hand surface and upserts it without DB reconstruction."""
    surface = _surface([_tool("alpha")])
    mdb = MagicMock()
    with patch.object(mcp_discovery_engine, "db", mdb):
        mcp_discovery_engine._capture_mcp_version_score("ver-9", surface)
    mdb.set_mcp_version_score.assert_called_once()
    assert mdb.set_mcp_version_score.call_args.args[0] == "ver-9"


# ===========================================================================
# ENGINE — end-to-end job driver
# ===========================================================================


def _install_runner(monkeypatch, surface=None, exc=None):
    async def _runner(_endpoint, _headers):
        if exc is not None:
            raise exc
        return surface

    monkeypatch.setattr(mcp_discovery_engine, "_discovery_runner", _runner)
    monkeypatch.setattr(
        mcp_discovery_engine, "load_endpoint_auth_headers", lambda _eid: {}
    )


async def test_drive_job_happy_path_completes(monkeypatch):
    surface = _surface([_tool("alpha")])
    _install_runner(monkeypatch, surface=surface)
    mdb = MagicMock()
    mdb.mark_mcp_discovery_job_running.return_value = {**_JOB_ROW, "state": "running"}
    mdb.get_latest_mcp_endpoint_version.return_value = None
    mdb.record_mcp_discovery_version.return_value = {"version_id": "ver-1", "version_seq": 1}
    monkeypatch.setattr(mcp_discovery_engine, "db", mdb)

    await mcp_discovery_engine._drive_discovery_job(_JOB_UUID, _ENDPOINT_ROW)

    mdb.mark_mcp_discovery_job_running.assert_called_once_with(_JOB_UUID)
    finish = mdb.finish_mcp_discovery_job.call_args
    assert finish.args[0] == _JOB_UUID
    assert finish.args[1] == "completed"
    assert finish.kwargs["result"]["version_id"] == "ver-1"


async def test_drive_job_classifies_client_failure(monkeypatch):
    _install_runner(monkeypatch, exc=RuntimeError("boom"))
    mdb = MagicMock()
    mdb.mark_mcp_discovery_job_running.return_value = {**_JOB_ROW, "state": "running"}
    mdb.record_mcp_discovery_failure.return_value = {
        "consecutive_failures": 1,
        "backoff_seconds": 60.0,
        "quarantined": False,
        "newly_quarantined": False,
    }
    monkeypatch.setattr(mcp_discovery_engine, "db", mdb)

    await mcp_discovery_engine._drive_discovery_job(_JOB_UUID, _ENDPOINT_ROW)

    mdb.record_mcp_discovery_version.assert_not_called()
    # Failures now accumulate backoff/quarantine state via record_mcp_discovery_failure, and
    # last_discovery_status carries the specific error code (here the unknown-exception bucket).
    mdb.record_mcp_discovery_failure.assert_called_once()
    assert mdb.record_mcp_discovery_failure.call_args.kwargs["status"] == "unknown"
    finish = mdb.finish_mcp_discovery_job.call_args
    assert finish.args[1] == "failed"
    assert "error" in finish.kwargs["result"]


async def test_drive_job_skips_when_not_queued(monkeypatch):
    """If the job is no longer queued (already started/gone), the run does nothing."""
    ran = {"called": False}

    async def _runner(_endpoint, _headers):
        ran["called"] = True
        return _surface([])

    monkeypatch.setattr(mcp_discovery_engine, "_discovery_runner", _runner)
    mdb = MagicMock()
    mdb.mark_mcp_discovery_job_running.return_value = None
    monkeypatch.setattr(mcp_discovery_engine, "db", mdb)

    await mcp_discovery_engine._drive_discovery_job(_JOB_UUID, _ENDPOINT_ROW)

    assert ran["called"] is False
    mdb.finish_mcp_discovery_job.assert_not_called()


async def test_trigger_discovery_dedup_does_not_spawn_task(monkeypatch):
    mdb = MagicMock()
    mdb.enqueue_mcp_discovery_job.return_value = {"job": _JOB_ROW, "deduplicated": True}
    monkeypatch.setattr(mcp_discovery_engine, "db", mdb)
    spawned = []
    monkeypatch.setattr(
        mcp_discovery_engine.asyncio, "create_task", lambda coro: spawned.append(coro)
    )

    job, deduplicated = await mcp_discovery_engine.trigger_discovery("t1", _ENDPOINT_ROW)

    assert deduplicated is True
    assert job["id"] == _JOB_UUID
    assert spawned == []  # no run started for a coalesced request


async def test_trigger_discovery_new_spawns_task(monkeypatch):
    mdb = MagicMock()
    mdb.enqueue_mcp_discovery_job.return_value = {"job": _JOB_ROW, "deduplicated": False}
    monkeypatch.setattr(mcp_discovery_engine, "db", mdb)
    spawned = []

    def _capture(coro):
        coro.close()  # we are only asserting a task was scheduled; don't run it
        spawned.append(True)

    monkeypatch.setattr(mcp_discovery_engine.asyncio, "create_task", _capture)

    _job, deduplicated = await mcp_discovery_engine.trigger_discovery("t1", _ENDPOINT_ROW)

    assert deduplicated is False
    assert spawned == [True]


# ===========================================================================
# CREDENTIALS (Epic-6 seam)
# ===========================================================================


def test_auth_headers_none_when_no_credential():
    assert mcp_credentials._headers_for_credential(None) == {}


def test_auth_headers_empty_for_auth_type_none():
    assert mcp_credentials._headers_for_credential({"auth_type": "none"}) == {}


def test_auth_headers_empty_for_undecryptable_secret():
    """A configured secret we cannot decrypt yet yields no headers (no fabrication)."""
    assert mcp_credentials._headers_for_credential({"auth_type": "bearer"}) == {}


def test_load_auth_headers_swallows_db_error(monkeypatch):
    mdb = MagicMock()
    mdb.get_mcp_endpoint_credentials.side_effect = RuntimeError("db down")
    monkeypatch.setattr(mcp_credentials, "db", mdb)
    assert mcp_credentials.load_endpoint_auth_headers(_EP_UUID) == {}


# ===========================================================================
# DB LAYER — enqueue/dedup + version persistence (fake cursor/connection)
# ===========================================================================


class _FakeCursor:
    """Cursor double serving a queue of fetchone results and recording statements."""

    def __init__(self, fetchone_results=None, fetchall_rows=None):
        self._fetchone_results = list(fetchone_results or [])
        self._fetchall_rows = fetchall_rows or []
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        if self._fetchone_results:
            return self._fetchone_results.pop(0)
        return None

    def fetchall(self):
        return self._fetchall_rows


class _FakeInfo:
    transaction_status = 0  # psycopg2 TRANSACTION_STATUS_IDLE


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False
        self.rolled_back = False
        self.autocommit = True
        self.info = _FakeInfo()

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def test_enqueue_job_creates_new_when_none_active(monkeypatch):
    new_row = {**_JOB_ROW}
    # dedup check finds no active job (None), then the INSERT returns the new row.
    cur = _FakeCursor(fetchone_results=[None, new_row])
    conn = _FakeConn(cur)
    db = Database()
    monkeypatch.setattr(db, "connect", lambda: conn)

    out = db.enqueue_mcp_discovery_job(_EP_UUID, "t1", "manual")

    assert out["deduplicated"] is False
    assert out["job"]["id"] == _JOB_UUID
    # An advisory lock is taken before the dedup check.
    assert "pg_advisory_xact_lock" in cur.executed[0][0]
    # The INSERT carries the manual trigger.
    assert any("INSERT INTO apiome.mcp_discovery_jobs" in sql for sql, _ in cur.executed)
    assert conn.committed is True


def test_enqueue_job_dedups_to_active(monkeypatch):
    active = {**_JOB_ROW, "state": "running"}
    # dedup check finds an already-active job on the first (and only) fetch.
    cur = _FakeCursor(fetchone_results=[active])
    conn = _FakeConn(cur)
    db = Database()
    monkeypatch.setattr(db, "connect", lambda: conn)

    out = db.enqueue_mcp_discovery_job(_EP_UUID, "t1", "manual")

    assert out["deduplicated"] is True
    assert out["job"]["state"] == "running"
    # No INSERT when an active job already exists.
    assert not any("INSERT INTO apiome.mcp_discovery_jobs" in sql for sql, _ in cur.executed)


def test_record_version_assigns_next_seq_and_updates_endpoint(monkeypatch):
    surface = _surface([_tool("alpha")])
    # fetchone queue: next_seq → version_tag collision check (no collision) → INSERT RETURNING id.
    cur = _FakeCursor(fetchone_results=[{"next_seq": 1}, None, {"id": "ver-1"}])
    conn = _FakeConn(cur)
    db = Database()
    monkeypatch.setattr(db, "connect", lambda: conn)

    out = db.record_mcp_discovery_version(
        _EP_UUID,
        version_row=surface.to_version_row(),
        capability_rows=surface.to_capability_rows(None),
        change_rows=[
            {"change_type": "added", "item_type": "tool", "item_name": "alpha", "detail": {}}
        ],
        discovered_at=_NOW,
    )

    # The snapshot is tagged with the minute-precision UTC discovery time (#3671).
    assert out == {"version_id": "ver-1", "version_seq": 1, "version_tag": "2026-06-26T12:00Z"}
    sqls = " ".join(sql for sql, _ in cur.executed)
    assert "INSERT INTO apiome.mcp_endpoint_versions" in sqls
    assert "INSERT INTO apiome.mcp_capability_items" in sqls
    assert "INSERT INTO apiome.mcp_version_changes" in sqls
    assert "UPDATE apiome.mcp_endpoints" in sqls
    # The tag is one of the columns/params carried on the version INSERT.
    insert_sql, insert_params = next(
        (sql, params)
        for sql, params in cur.executed
        if "INSERT INTO apiome.mcp_endpoint_versions" in sql
    )
    assert "version_tag" in insert_sql
    assert "2026-06-26T12:00Z" in insert_params


def test_record_version_disambiguates_same_minute_tag_collision(monkeypatch):
    """A second snapshot in the same minute gets a ``-N`` suffix on its date/time tag."""
    surface = _surface([_tool("alpha")])
    # The first collision probe finds an existing row (truthy), the second probe is clear (None).
    cur = _FakeCursor(
        fetchone_results=[{"next_seq": 2}, {"exists": 1}, None, {"id": "ver-2"}]
    )
    conn = _FakeConn(cur)
    db = Database()
    monkeypatch.setattr(db, "connect", lambda: conn)

    out = db.record_mcp_discovery_version(
        _EP_UUID,
        version_row=surface.to_version_row(),
        capability_rows=surface.to_capability_rows(None),
        change_rows=[],
        discovered_at=_NOW,
    )

    assert out["version_tag"] == "2026-06-26T12:00Z-2"
    # Two collision probes were issued against mcp_endpoint_versions before the INSERT.
    probes = [
        params
        for sql, params in cur.executed
        if "SELECT 1 FROM apiome.mcp_endpoint_versions" in sql
    ]
    assert [p[1] for p in probes] == ["2026-06-26T12:00Z", "2026-06-26T12:00Z-2"]
    assert conn.committed is True


def test_set_mcp_version_score_upserts_on_version(monkeypatch):
    """The score upsert targets mcp_version_scores keyed by version, moving scored_at on conflict."""
    cur = _FakeCursor(fetchall_rows=[{"id": "score-1"}])
    conn = _FakeConn(cur)
    db = Database()
    monkeypatch.setattr(db, "connect", lambda: conn)

    ok = db.set_mcp_version_score(
        "ver-1",
        score=87,
        grade="B",
        report={"score": 87, "grade": "B", "findings": []},
        report_fingerprint="fp-abc",
    )

    assert ok is True
    sql, params = cur.executed[0]
    assert "INSERT INTO apiome.mcp_version_scores" in sql
    assert "ON CONFLICT (version_id) DO UPDATE" in sql
    assert "scored_at = CURRENT_TIMESTAMP" in sql
    # version_id, score, grade are passed through; the report is JSONB-wrapped.
    assert params[0] == "ver-1"
    assert params[1] == 87
    assert params[2] == "B"
    assert params[4] == "fp-abc"


def test_set_mcp_version_score_defaults_report_to_empty_object(monkeypatch):
    """A None report is stored as an empty JSONB object (matching the column default)."""
    cur = _FakeCursor(fetchall_rows=[{"id": "score-2"}])
    conn = _FakeConn(cur)
    db = Database()
    monkeypatch.setattr(db, "connect", lambda: conn)

    ok = db.set_mcp_version_score("ver-2", score=None, grade=None)

    assert ok is True
    _, params = cur.executed[0]
    # The 4th positional bind is the JSONB report; an omitted report becomes {} (not NULL).
    assert params[3].adapted == {}


def test_finish_job_writes_terminal_state(monkeypatch):
    cur = _FakeCursor(fetchone_results=[{**_JOB_ROW, "state": "completed"}])
    conn = _FakeConn(cur)
    db = Database()
    monkeypatch.setattr(db, "connect", lambda: conn)

    db.finish_mcp_discovery_job(_JOB_UUID, "completed", result={"version_id": "ver-1"})

    sql, params = cur.executed[0]
    assert "finished_at = CURRENT_TIMESTAMP" in sql
    assert params[0] == "completed"
    assert conn.committed is True


# ===========================================================================
# DB LAYER — date/time version tag formatting (MCAT-4.4, #3671)
# ===========================================================================


def test_format_version_tag_minute_precision_utc():
    """An aware UTC datetime renders as a compact minute-precision ISO label."""
    assert format_mcp_version_tag(_NOW) == "2026-06-26T12:00Z"
    assert (
        format_mcp_version_tag(datetime(2026, 6, 26, 14, 3, 47, tzinfo=timezone.utc))
        == "2026-06-26T14:03Z"
    )


def test_format_version_tag_converts_to_utc():
    """A non-UTC aware datetime is normalized to UTC before formatting."""
    eastern = timezone(timedelta(hours=-4))
    # 10:03 at UTC-4 is 14:03 UTC.
    local = datetime(2026, 6, 26, 10, 3, 0, tzinfo=eastern)
    assert format_mcp_version_tag(local) == "2026-06-26T14:03Z"


def test_format_version_tag_assumes_utc_for_naive():
    """A naive datetime is treated as already-UTC (matches the SQL backfill assumption)."""
    naive = datetime(2026, 6, 26, 14, 3, 0)
    assert format_mcp_version_tag(naive) == "2026-06-26T14:03Z"
