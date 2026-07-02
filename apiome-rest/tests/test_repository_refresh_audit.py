"""Refresh-cycle audit recording tests (RAR-5.3, #3534).

Deterministic, DB-free fixtures over ``app.repository_refresh_audit`` using a fake
``Database`` that captures the ``insert_workflow_audit`` call. Covers the first
acceptance criterion — *each refresh writes an audit entry with trigger, decision,
outcome, and change-report link* — plus the outcome derivation, the
column/detail outcome split, lineage capture for per-repo/per-file query, and
enum-type guarding.
"""

import pytest

from app.repository_refresh_audit import (
    REFRESH_CYCLE_ACTION,
    RefreshOutcome,
    RefreshTrigger,
    build_refresh_cycle_detail,
    derive_outcome,
    record_refresh_cycle,
)


class FakeDB:
    """Captures the single ``insert_workflow_audit`` positional call."""

    def __init__(self):
        self.calls = []

    def insert_workflow_audit(
        self, tenant_id, project_id, version_id, action, outcome, actor_id, detail
    ):
        self.calls.append(
            {
                "tenant_id": tenant_id,
                "project_id": project_id,
                "version_id": version_id,
                "action": action,
                "outcome": outcome,
                "actor_id": actor_id,
                "detail": detail,
            }
        )


# ---------------------------------------------------------------- derive_outcome


def test_derive_outcome_failed_dominates():
    # Failure dominates even if other flags are set.
    assert (
        derive_outcome(failed=True, diverged=True, version_created=True)
        is RefreshOutcome.FAILED
    )


def test_derive_outcome_diverged_over_version():
    assert (
        derive_outcome(failed=False, diverged=True, version_created=True)
        is RefreshOutcome.DIVERGED
    )


def test_derive_outcome_new_version():
    assert (
        derive_outcome(failed=False, diverged=False, version_created=True)
        is RefreshOutcome.NEW_VERSION
    )


def test_derive_outcome_unchanged_noop():
    assert (
        derive_outcome(failed=False, diverged=False, version_created=False)
        is RefreshOutcome.UNCHANGED
    )


# ------------------------------------------------------- build_refresh_cycle_detail


def test_detail_always_carries_lineage_trigger_outcome():
    detail = build_refresh_cycle_detail(
        trigger=RefreshTrigger.SCHEDULED,
        outcome=RefreshOutcome.UNCHANGED,
        repository_id="r1",
        branch="main",
        path="openapi/petstore.yaml",
    )
    assert detail == {
        "trigger": "scheduled",
        "outcome": "unchanged",
        "repositoryId": "r1",
        "branch": "main",
        "path": "openapi/petstore.yaml",
    }


def test_detail_includes_links_when_present():
    detail = build_refresh_cycle_detail(
        trigger=RefreshTrigger.MANUAL,
        outcome=RefreshOutcome.NEW_VERSION,
        repository_id="r1",
        branch="main",
        path="api.yaml",
        decision="newer-content",
        version_id="v2",
        parent_version_id="v1",
        change_report_id="cr9",
        source_commit_sha="abc123",
    )
    assert detail["decision"] == "newer-content"
    assert detail["versionId"] == "v2"
    assert detail["parentVersionId"] == "v1"
    assert detail["changeReportId"] == "cr9"
    assert detail["sourceCommitSha"] == "abc123"


def test_detail_omits_blank_optionals():
    detail = build_refresh_cycle_detail(
        trigger=RefreshTrigger.SCHEDULED,
        outcome=RefreshOutcome.UNCHANGED,
        repository_id="r1",
        branch="main",
        path="api.yaml",
        version_id="   ",
        change_report_id=None,
        error="",
    )
    assert "versionId" not in detail
    assert "changeReportId" not in detail
    assert "error" not in detail


def test_detail_extra_does_not_override_reserved_keys():
    detail = build_refresh_cycle_detail(
        trigger=RefreshTrigger.WEBHOOK,
        outcome=RefreshOutcome.NEW_VERSION,
        repository_id="r1",
        branch="main",
        path="api.yaml",
        extra={"trigger": "spoof", "deliveryId": "d1"},
    )
    assert detail["trigger"] == "webhook"  # reserved key wins
    assert detail["deliveryId"] == "d1"  # genuinely extra context kept


# --------------------------------------------------------------- record_refresh_cycle


def test_record_writes_audit_with_all_facets():
    db = FakeDB()
    detail = record_refresh_cycle(
        db,
        tenant_id="t1",
        repository_id="r1",
        branch="main",
        path="openapi/petstore.yaml",
        trigger=RefreshTrigger.SCHEDULED,
        outcome=RefreshOutcome.NEW_VERSION,
        project_id="p1",
        version_id="v2",
        parent_version_id="v1",
        change_report_id="cr9",
        decision="newer-content",
        source_commit_sha="abc123",
        actor_id="u1",
    )
    assert len(db.calls) == 1
    call = db.calls[0]
    assert call["tenant_id"] == "t1"
    assert call["project_id"] == "p1"
    assert call["version_id"] == "v2"
    assert call["action"] == REFRESH_CYCLE_ACTION
    assert call["actor_id"] == "u1"
    # New-version is a *successful* cycle at the column level.
    assert call["outcome"] == "success"
    # Acceptance: trigger, decision, outcome, and change-report link all recorded.
    assert call["detail"]["trigger"] == "scheduled"
    assert call["detail"]["decision"] == "newer-content"
    assert call["detail"]["outcome"] == "new-version"
    assert call["detail"]["changeReportId"] == "cr9"
    # Lineage keys present for per-repo/per-file query.
    assert call["detail"]["repositoryId"] == "r1"
    assert call["detail"]["path"] == "openapi/petstore.yaml"
    assert detail is call["detail"]


def test_record_failed_cycle_maps_column_to_failure():
    db = FakeDB()
    record_refresh_cycle(
        db,
        tenant_id="t1",
        repository_id="r1",
        branch="main",
        path="api.yaml",
        trigger=RefreshTrigger.MANUAL,
        outcome=RefreshOutcome.FAILED,
        error="boom",
        actor_id="u1",
    )
    call = db.calls[0]
    assert call["outcome"] == "failure"
    assert call["detail"]["outcome"] == "failed"
    assert call["detail"]["error"] == "boom"
    # No version produced on a failed cycle.
    assert call["version_id"] is None


def test_record_diverged_cycle_is_success_column_diverged_detail():
    db = FakeDB()
    record_refresh_cycle(
        db,
        tenant_id="t1",
        repository_id="r1",
        branch="main",
        path="api.yaml",
        trigger=RefreshTrigger.SCHEDULED,
        outcome=RefreshOutcome.DIVERGED,
    )
    call = db.calls[0]
    # A held divergence is a successful, non-failed cycle.
    assert call["outcome"] == "success"
    assert call["detail"]["outcome"] == "diverged"
    # System (scheduled) refresh has no actor.
    assert call["actor_id"] is None


@pytest.mark.parametrize("bad_trigger", ["scheduled", 1, None])
def test_record_rejects_non_enum_trigger(bad_trigger):
    db = FakeDB()
    with pytest.raises(TypeError):
        record_refresh_cycle(
            db,
            tenant_id="t1",
            repository_id="r1",
            branch="main",
            path="api.yaml",
            trigger=bad_trigger,
            outcome=RefreshOutcome.UNCHANGED,
        )
    assert db.calls == []


def test_record_rejects_non_enum_outcome():
    db = FakeDB()
    with pytest.raises(TypeError):
        record_refresh_cycle(
            db,
            tenant_id="t1",
            repository_id="r1",
            branch="main",
            path="api.yaml",
            trigger=RefreshTrigger.MANUAL,
            outcome="new-version",
        )
    assert db.calls == []


def test_enum_wire_codes_are_stable():
    assert [t.value for t in RefreshTrigger] == ["scheduled", "manual", "webhook"]
    assert [o.value for o in RefreshOutcome] == [
        "new-version",
        "unchanged",
        "diverged",
        "failed",
    ]


# ----------------------------------------------- DAO: queryable per repo and per file


def _db_capturing():
    """A ``Database`` whose ``execute_query`` records the SQL + params and returns []."""
    from app.database import Database

    db = Database()
    captured = {}

    def fake_execute_query(query, params=None):
        captured["query"] = query
        captured["params"] = params
        return []

    db.execute_query = fake_execute_query  # type: ignore[method-assign]
    return db, captured


def test_search_filters_action_tenant_and_lineage():
    db, captured = _db_capturing()
    db.search_repository_refresh_audit(
        "t1", repository_id="r1", path="api.yaml", branch="main"
    )
    q = captured["query"]
    params = captured["params"]
    # Scoped to the dedicated refresh-cycle action and the tenant.
    assert "wa.action = %s" in q
    assert "wa.tenant_id = %s" in q
    assert REFRESH_CYCLE_ACTION in params
    assert "t1" in params
    # Per-repo and per-file query via the JSONB lineage keys.
    assert "wa.detail->>'repositoryId' = %s" in q
    assert "wa.detail->>'path' = %s" in q
    assert "wa.detail->>'branch' = %s" in q
    assert "r1" in params and "api.yaml" in params and "main" in params
    # Newest first, paginated.
    assert "ORDER BY wa.created_at DESC" in q
    assert "LIMIT %s OFFSET %s" in q


def test_search_omits_unset_filters():
    db, captured = _db_capturing()
    db.search_repository_refresh_audit("t1", repository_id="r1")
    q = captured["query"]
    assert "wa.detail->>'repositoryId' = %s" in q
    assert "wa.detail->>'path'" not in q
    assert "wa.detail->>'branch'" not in q
    assert "wa.detail->>'trigger'" not in q
    assert "wa.detail->>'outcome'" not in q


def test_count_uses_same_filter_and_returns_int():
    from app.database import Database

    db = Database()

    def fake_execute_query(query, params=None):
        assert "COUNT(*)" in query
        assert "wa.detail->>'path' = %s" in query
        return [{"cnt": 7}]

    db.execute_query = fake_execute_query  # type: ignore[method-assign]
    assert (
        db.count_repository_refresh_audit("t1", repository_id="r1", path="api.yaml") == 7
    )
