"""Export history & audit ledger — MFX-46.1 (#4379).

Pinned here, against the acceptance criteria:

* **Filterable history with per-run verdicts** — a finished job becomes one ledger row carrying the
  actor, source@version → target, preserved %, the validation / lint verdicts and the delivery decision
  (a multi-target job's weakest target's); the listing filters on source, target, actor, outcome,
  delivery channel, validation verdict, decision and date, and attaches every delivery with a
  normalized outcome.
* **Detail renders stored reports** — the reports are kept per target and returned as they were.
* **Tenant-scoped** — every read needs ``projects:view`` and the caller's own tenant; the SQL always
  scopes by tenant id.
* The job engine records each finished job **once**, with its actor and source name, and never lets the
  ledger disturb the export; the retention sweep prunes the ledger (see ``test_async_job_retention_sweep``).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.database import Database
from app.export_run_ledger import (
    actor_from_auth,
    build_ledger_row,
    deliveries_by_job,
    delivery_outcome,
    record_export_run,
    run_detail,
    run_summary,
)
from app.main import app
from app.permissions import Action, Resource

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_USER = "22222222-2222-4222-8222-222222222222"
_AUTH = {"tenant_id": _TENANT, "user_id": _USER, "auth_method": "jwt", "user_email": "ada@example.com"}
_CREATED = datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc)
_FINISHED = datetime(2026, 11, 5, 9, 1, tzinfo=timezone.utc)


def _envelope(tier: str, preserved: int) -> Dict[str, Any]:
    return {"summary": {"tier": tier, "preserved_percent": preserved}, "report": {"items": []}}


def _gate(decision: str, *reasons: Dict[str, Any]) -> Dict[str, Any]:
    return {"decision": decision, "reasons": list(reasons)}


def _reason(dimension: str, severity: str) -> Dict[str, Any]:
    return {"dimension": dimension, "severity": severity, "code": "X", "message": "m"}


def _row(**overrides: Any) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = dict(
        tenant_id=_TENANT,
        job_id="job-1",
        state="completed",
        request={"artifact": "proj-1", "target": "protobuf", "dry_run": False, "options": {"package": "acme"}},
        result={
            "artifact": "proj-1", "version_record_id": "rev-1", "version_label": "1.4.0", "target": "protobuf",
            "options": {"package": "acme.v1"},
            "fidelity": _envelope("lossy", 64),
            "validation": {"verdict": "valid"},
            "delivery": _gate("allow_with_warning", _reason("lint", "warning")),
        },
        error=None,
        artifact_name="Petstore",
        actor=(_USER, "ada@example.com"),
        created_at=_CREATED,
        finished_at=_FINISHED,
    )
    kwargs.update(overrides)
    return build_ledger_row(**kwargs)


# ===========================================================================
# The actor
# ===========================================================================


def test_the_actor_is_the_authenticated_user_with_a_label_that_is_never_empty() -> None:
    assert actor_from_auth(_AUTH) == (_USER, "ada@example.com")
    assert actor_from_auth({"user_id": _USER, "name": "Ada"}) == (_USER, "Ada")
    assert actor_from_auth(None) == (None, "Unknown")
    assert actor_from_auth({}) == (None, "Unknown")


def test_an_api_key_with_no_user_is_never_attributed_to_someone_else() -> None:
    # Unlike authorship elsewhere, there is no fall back to a tenant admin.
    assert actor_from_auth({"auth_method": "api_key", "tenant_id": _TENANT}) == (None, "API key")
    assert actor_from_auth({"auth_method": "api_key", "api_key_name": "ci"}) == (None, "API key ci")


# ===========================================================================
# The row
# ===========================================================================


def test_a_completed_job_records_who_exported_what_where_and_with_how_much_loss() -> None:
    row = _row()
    assert row["artifact_id"] == "proj-1" and row["artifact_name"] == "Petstore"
    assert (row["version_record_id"], row["version_label"]) == ("rev-1", "1.4.0")
    assert row["target"] == "protobuf"
    assert (row["actor_id"], row["actor_label"]) == (_USER, "ada@example.com")
    assert (row["preserved_percent"], row["fidelity_tier"]) == (64, "lossy")
    assert row["validation_verdict"] == "valid"
    assert row["lint_verdict"] == "warn"
    assert row["delivery_decision"] == "allow_with_warning"
    assert row["state"] == "completed" and row["dry_run"] is False
    # The options the job ran with (the resolved ones, over the submitted ones) — for a re-run.
    assert row["options"] == {"package": "acme.v1"}
    assert row["created_at"] == _CREATED and row["finished_at"] == _FINISHED


def test_the_reports_are_kept_per_target() -> None:
    row = _row()
    assert row["fidelity"] == [{"target": "protobuf", "envelope": _envelope("lossy", 64)}]
    assert row["validation"] == [{"target": "protobuf", "report": {"verdict": "valid"}}]
    assert row["delivery_gate"][0]["report"]["decision"] == "allow_with_warning"


@pytest.mark.parametrize(("reasons", "expected"), [
    ((), "pass"),
    ((_reason("validation", "blocking"),), "pass"),
    ((_reason("lint", "info"),), "pass"),
    ((_reason("lint", "warning"),), "warn"),
    ((_reason("lint", "warning"), _reason("lint", "blocking")), "block"),
])
def test_the_lint_verdict_is_the_gate_s_worst_lint_reason(reasons: tuple, expected: str) -> None:
    row = _row(result={"target": "protobuf", "delivery": _gate("allow", *reasons)})
    assert row["lint_verdict"] == expected


def test_a_multi_target_job_is_headlined_by_its_weakest_target() -> None:
    result = {
        "artifact": "proj-1", "version_label": "2.0.0",
        "fidelity_rollup": {"tier": "lossy", "min_preserved_percent": 41},
        "targets": [
            {"target": "openapi-3.1", "fidelity": _envelope("lossless", 100), "validation": {"verdict": "valid"},
             "delivery": _gate("allow")},
            {"target": "protobuf", "fidelity": _envelope("lossy", 41), "validation": {"verdict": "invalid"},
             "delivery": _gate("block", _reason("lint", "blocking"))},
            {"target": "graphql", "fidelity": _envelope("lossy", 77), "validation": {"verdict": "skipped"},
             "delivery": _gate("allow_with_warning")},
        ],
    }
    row = _row(request={"artifact": "proj-1", "targets": [{"target": "openapi-3.1"}, {"target": "protobuf"},
                                                          {"target": "graphql"}]}, result=result)
    assert row["target"] == "openapi-3.1,protobuf,graphql"
    assert (row["preserved_percent"], row["fidelity_tier"]) == (41, "lossy")
    assert row["validation_verdict"] == "invalid"
    assert row["delivery_decision"] == "block"
    assert row["lint_verdict"] == "block"
    assert [r["target"] for r in row["fidelity"]] == ["openapi-3.1", "protobuf", "graphql"]


def test_a_failed_job_records_its_error_and_no_numbers() -> None:
    row = _row(state="failed", result=None, error={"code": "SOURCE_LOAD_FAILED", "message": "No such revision"},
               artifact_name=None)
    assert row["state"] == "failed"
    assert (row["error_code"], row["error_message"]) == ("SOURCE_LOAD_FAILED", "No such revision")
    assert row["preserved_percent"] is None and row["validation_verdict"] is None
    assert row["fidelity"] is None and row["validation"] is None and row["delivery_gate"] is None
    # The submitted options still come along, for a re-run.
    assert row["options"] == {"package": "acme"}


def test_a_dry_run_has_a_fidelity_report_and_nothing_to_validate() -> None:
    row = _row(request={"artifact": "proj-1", "target": "protobuf", "dry_run": True},
               result={"target": "protobuf", "fidelity": _envelope("lossy", 64)})
    assert row["dry_run"] is True and row["preserved_percent"] == 64
    assert row["validation_verdict"] is None and row["lint_verdict"] is None and row["delivery_decision"] is None


def test_recording_never_raises() -> None:
    with patch("app.database.db.insert_export_run", side_effect=RuntimeError("down")):
        assert record_export_run(_row()) is False
    with patch("app.database.db.insert_export_run", return_value=True) as insert:
        assert record_export_run(_row()) is True
    assert insert.call_args.args[0]["job_id"] == "job-1"


# ===========================================================================
# Deliveries and the detail
# ===========================================================================


@pytest.mark.parametrize(("channel", "status", "outcome"), [
    ("git", "opened", "delivered"),
    ("git", "up_to_date", "delivered"),
    ("git", "committed", "delivered"),
    ("git", "in_progress", "in_progress"),
    ("git", "failed", "failed"),
    ("webhook", "retrying", "in_progress"),
    ("webhook", "delivered", "delivered"),
    ("object-storage", "delivered", "delivered"),
    ("object-storage", "failed", "failed"),
])
def test_each_channel_s_status_normalizes_to_an_outcome(channel: str, status: str, outcome: str) -> None:
    assert delivery_outcome(channel, status) == outcome


def test_deliveries_group_by_job_in_order() -> None:
    grouped = deliveries_by_job([
        {"job_id": "a", "channel": "git", "status": "opened", "destination": "acme/specs"},
        {"job_id": "b", "channel": "webhook", "status": "failed", "error_code": "export-webhook-http-500"},
        {"job_id": "a", "channel": "object-storage", "status": "delivered", "destination": "specs-bucket"},
    ])
    assert [(d.channel, d.outcome, d.destination) for d in grouped["a"]] == [
        ("git", "delivered", "acme/specs"), ("object-storage", "delivered", "specs-bucket")]
    assert grouped["b"][0].error_code == "export-webhook-http-500"


def _stored(**overrides: Any) -> Dict[str, Any]:
    row = _row()
    row.update(actor_id=_USER, created_at=_CREATED, finished_at=_FINISHED, **overrides)
    return row


def test_the_detail_regroups_the_stored_reports_per_target() -> None:
    detail = run_detail(_stored(), deliveries_by_job([{"job_id": "job-1", "channel": "git", "status": "opened"}])
                        ["job-1"])
    assert [r.target for r in detail.reports] == ["protobuf"]
    report = detail.reports[0]
    assert report.fidelity == _envelope("lossy", 64)
    assert report.validation == {"verdict": "valid"}
    assert report.delivery_gate["decision"] == "allow_with_warning"
    assert detail.deliveries[0].outcome == "delivered"
    summary = run_summary(_stored())
    assert "reports" not in summary.model_dump() and summary.preserved_percent == 64


# ===========================================================================
# The job engine records each finished job once
# ===========================================================================


def test_a_finished_job_is_recorded_once_with_its_actor_and_source_name() -> None:
    from app.canonical_model import ApiIdentity, ApiParadigm, CanonicalApi, CanonicalField, Type, TypeKind, TypeRef
    from app.export_job_engine import ExportJobStartRequest, _jobs, get_export_job_status, schedule_export_job
    from app.export_source import ExportSource

    api = CanonicalApi(
        paradigm=ApiParadigm.DATA_SCHEMA, format="json-schema", identity=ApiIdentity(name="shop"), title="Shop API",
        types=[Type(key="Order", name="Order", kind=TypeKind.RECORD,
                    fields=[CanonicalField(key="Order.id", name="id", type=TypeRef(name="string"))])],
    )
    source = ExportSource(api=api, artifact_id="proj-1", version_record_id="rev-1", version_label="1.0.0")
    recorded: List[Dict[str, Any]] = []

    async def scenario() -> str:
        request = ExportJobStartRequest(artifact="proj-1", target="openapi", dry_run=True)
        accepted = await schedule_export_job("acme", _TENANT, request, auth_data=_AUTH)
        for _ in range(400):
            status = await get_export_job_status("acme", accepted.job_id)
            if status.state in ("completed", "failed", "canceled"):
                break
            await asyncio.sleep(0.01)
        for _ in range(100):  # the terminal mirror runs just after the terminal publish
            if recorded:
                break
            await asyncio.sleep(0.01)
        return accepted.job_id

    with patch("app.export_job_engine.load_export_source", return_value=source), \
            patch("app.database.db.upsert_async_job"), \
            patch("app.database.db.insert_export_run", side_effect=lambda row: recorded.append(row) or True):
        job_id = asyncio.run(scenario())
        _jobs.clear()

    assert len(recorded) == 1
    row = recorded[0]
    assert row["job_id"] == job_id and row["tenant_id"] == _TENANT
    assert (row["actor_id"], row["actor_label"]) == (_USER, "ada@example.com")
    assert row["artifact_name"] == "Shop API" and row["state"] == "completed" and row["dry_run"] is True
    assert row["version_label"] == "1.0.0" and row["preserved_percent"] is not None


# ===========================================================================
# The routes: tenant-scoped, projects:view
# ===========================================================================


@pytest.fixture
def _authed():
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    yield
    app.dependency_overrides.clear()


def _ledger_row(job_id: str = "job-1") -> Dict[str, Any]:
    return _stored(job_id=job_id)


def test_the_listing_filters_needs_projects_view_and_attaches_deliveries(_authed: None) -> None:
    with patch("app.export_run_routes.enforce_permission") as guard, \
            patch("app.export_run_routes.db.get_tenant_row_by_slug", return_value={"id": _TENANT}), \
            patch("app.export_run_routes.db.list_export_runs",
                  return_value={"runs": [_ledger_row()], "total": 1, "limit": 20, "offset": 0}) as listing, \
            patch("app.export_run_routes.db.list_export_run_deliveries",
                  return_value=[{"job_id": "job-1", "channel": "git", "status": "opened",
                                 "destination": "acme/specs"}]) as deliveries:
        response = client.get(
            "/v1/export/acme/runs",
            params={"artifact": "proj-1", "target": "protobuf", "actor": _USER, "state": "completed",
                    "channel": "git", "validation": "valid", "decision": "allow", "limit": 20,
                    "finished_after": "2026-11-01T00:00:00Z"},
        )
    assert response.status_code == 200, response.text
    assert [call.args[2:] for call in guard.call_args_list] == [(Resource.PROJECTS, Action.VIEW)]
    kwargs = listing.call_args.kwargs
    assert listing.call_args.args == (_TENANT,)
    assert (kwargs["artifact_id"], kwargs["target"], kwargs["actor_id"], kwargs["state"], kwargs["channel"],
            kwargs["validation_verdict"], kwargs["delivery_decision"], kwargs["limit"]) == (
        "proj-1", "protobuf", _USER, "completed", "git", "valid", "allow", 20)
    assert kwargs["finished_after"].year == 2026
    deliveries.assert_called_once_with(_TENANT, ["job-1"])
    body = response.json()
    assert body["total"] == 1
    run = body["runs"][0]
    assert (run["artifact_name"], run["version_label"], run["target"], run["actor_label"]) == (
        "Petstore", "1.4.0", "protobuf", "ada@example.com")
    assert (run["preserved_percent"], run["validation_verdict"], run["lint_verdict"], run["delivery_decision"]) == (
        64, "valid", "warn", "allow_with_warning")
    assert run["deliveries"] == [{"channel": "git", "status": "opened", "outcome": "delivered",
                                  "destination": "acme/specs", "error_code": None, "started_at": None,
                                  "finished_at": None}]
    assert "reports" not in run and "fidelity" not in run


def test_an_unknown_filter_value_is_refused(_authed: None) -> None:
    with patch("app.export_run_routes.enforce_permission"), \
            patch("app.export_run_routes.db.get_tenant_row_by_slug", return_value={"id": _TENANT}):
        assert client.get("/v1/export/acme/runs", params={"channel": "ftp"}).status_code == 422
        assert client.get("/v1/export/acme/runs", params={"decision": "maybe"}).status_code == 422


def test_another_tenant_s_history_is_not_found(_authed: None) -> None:
    with patch("app.export_run_routes.enforce_permission"), \
            patch("app.export_run_routes.db.get_tenant_row_by_slug", return_value={"id": "someone-else"}), \
            patch("app.export_run_routes.db.list_export_runs") as listing, \
            patch("app.export_run_routes.db.get_export_run") as get:
        assert client.get("/v1/export/other/runs").status_code == 404
        assert client.get("/v1/export/other/runs/job-1").status_code == 404
        assert client.get("/v1/export/other/runs/actors").status_code == 404
    listing.assert_not_called()
    get.assert_not_called()


def test_the_detail_returns_the_stored_reports(_authed: None) -> None:
    with patch("app.export_run_routes.enforce_permission"), \
            patch("app.export_run_routes.db.get_tenant_row_by_slug", return_value={"id": _TENANT}), \
            patch("app.export_run_routes.db.get_export_run", return_value=_ledger_row()) as get, \
            patch("app.export_run_routes.db.list_export_run_deliveries", return_value=[]):
        response = client.get("/v1/export/acme/runs/job-1")
        missing_patch = patch("app.export_run_routes.db.get_export_run", return_value=None)
        with missing_patch:
            missing = client.get("/v1/export/acme/runs/nope")
    assert response.status_code == 200
    get.assert_called_once_with(_TENANT, "job-1")
    report = response.json()["reports"][0]
    assert report["target"] == "protobuf" and report["fidelity"]["summary"]["preserved_percent"] == 64
    assert report["validation"] == {"verdict": "valid"}
    assert missing.status_code == 404


def test_the_actors_list_feeds_the_filter(_authed: None) -> None:
    with patch("app.export_run_routes.enforce_permission"), \
            patch("app.export_run_routes.db.get_tenant_row_by_slug", return_value={"id": _TENANT}), \
            patch("app.export_run_routes.db.list_export_run_actors",
                  return_value=[{"actor_id": _USER, "actor_label": "ada@example.com"}]):
        response = client.get("/v1/export/acme/runs/actors")
    assert response.json() == {"actors": [{"actor_id": _USER, "actor_label": "ada@example.com"}]}


# ===========================================================================
# The SQL: always tenant-scoped
# ===========================================================================


class _Recording(Database):
    """A Database whose queries are recorded instead of run."""

    def __init__(self) -> None:  # noqa: D107 - no connection
        self.queries: List[tuple] = []

    def execute_query(self, query: str, params: tuple = None) -> List[Dict[str, Any]]:  # type: ignore[override]
        self.queries.append((" ".join(query.split()), params))
        return [{"total": 0}] if "COUNT(*)" in query else []


def test_every_listing_query_is_scoped_to_the_tenant_and_parameterized() -> None:
    database = _Recording()
    page = database.list_export_runs(_TENANT, artifact_id="proj-1", target="protobuf", actor_id=_USER,
                                     state="failed", channel="git", validation_verdict="invalid",
                                     delivery_decision="block", limit=500, offset=-3)
    assert page == {"runs": [], "total": 0, "limit": 200, "offset": 0}
    count_sql, params = database.queries[0]
    assert count_sql.startswith("SELECT COUNT(*)::int AS total FROM apiome.export_run_ledger l WHERE l.tenant_id")
    assert params == (_TENANT, "proj-1", "failed", "invalid", "block", "protobuf", _USER)
    assert "string_to_array(l.target, ',')" in count_sql
    assert "EXISTS (SELECT 1 FROM apiome.export_git_delivery_runs d" in count_sql
    list_sql, list_params = database.queries[1]
    assert "ORDER BY l.finished_at DESC, l.job_id DESC" in list_sql and list_params[-2:] == (200, 0)


def test_never_delivered_means_no_run_in_any_channel() -> None:
    database = _Recording()
    database.list_export_runs(_TENANT, channel="none")
    sql = database.queries[0][0]
    for table in ("export_git_delivery_runs", "export_webhook_delivery_runs", "export_object_storage_delivery_runs"):
        assert f"NOT EXISTS (SELECT 1 FROM apiome.{table} d" in sql


@pytest.mark.parametrize("kwargs", [{"channel": "ftp"}, {"actor_id": "not-a-uuid"}])
def test_an_impossible_filter_matches_nothing_without_querying(kwargs: Dict[str, Any]) -> None:
    database = _Recording()
    assert database.list_export_runs(_TENANT, **kwargs)["runs"] == []
    assert database.queries == []


def test_a_non_uuid_tenant_reads_nothing() -> None:
    database = _Recording()
    assert database.list_export_runs("acme")["runs"] == []
    assert database.get_export_run("acme", "job-1") is None
    assert database.list_export_run_deliveries("acme", ["job-1"]) == []
    assert database.list_export_run_actors("acme") == []
    assert database.insert_export_run({"tenant_id": "acme"}) is False
    assert database.queries == []


def test_the_detail_and_deliveries_are_scoped_to_the_tenant() -> None:
    database = _Recording()
    database.get_export_run(_TENANT, "job-1")
    database.list_export_run_deliveries(_TENANT, ["job-1", "job-2"])
    detail_sql, detail_params = database.queries[0]
    assert "WHERE l.tenant_id = %s::uuid AND l.job_id = %s" in detail_sql and detail_params == (_TENANT, "job-1")
    deliveries_sql, deliveries_params = database.queries[1]
    assert deliveries_sql.count("tenant_id = %s::uuid AND job_id = ANY(%s)") == 3
    assert deliveries_params == (_TENANT, ["job-1", "job-2"]) * 3


def test_the_insert_writes_each_job_once_with_json_reports() -> None:
    database = _Recording()
    database.insert_export_run(_row())
    sql, params = database.queries[0]
    assert "ON CONFLICT (job_id) DO NOTHING" in sql
    assert params[0] == "job-1" and params[1] == _TENANT and params[7] == _USER
    assert '"envelope"' in params[19]  # the fidelity reports, as JSON text


# ===========================================================================
# The migration
# ===========================================================================


def test_the_migration_keeps_history_per_tenant_and_outlives_the_account() -> None:
    scripts = Path(__file__).resolve().parents[2] / "apiome-db" / "scripts"
    text = (scripts / "V360__export_run_ledger_4379.sql").read_text()
    for fragment in (
        "CREATE TABLE IF NOT EXISTS export_run_ledger (",
        "job_id VARCHAR(64) PRIMARY KEY",
        "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE",
        "actor_id UUID REFERENCES users(id) ON DELETE SET NULL",
        "actor_label VARCHAR(320) NOT NULL DEFAULT 'Unknown'",
        "CHECK (state IN ('completed', 'failed', 'canceled'))",
        "CHECK (lint_verdict IS NULL OR lint_verdict IN ('pass', 'warn', 'block'))",
        "ON export_run_ledger (tenant_id, finished_at DESC, job_id DESC)",
        "-- Rollback notes",
    ):
        assert fragment in text, fragment
