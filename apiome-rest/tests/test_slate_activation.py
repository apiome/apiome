"""Atomic activation and the concurrency guard — APX-3.1 (private-suite#2456).

Acceptance criteria 2 and 4: preview and production routes activate atomically, and
concurrent promotion, failed activation, retention and audit paths are tested.

These tests drive :mod:`app.slate_deployment_store` against a scripted fake connection
rather than a live Postgres. That is a deliberate choice, not a shortcut: what needs pinning
here is the *shape* of the statements the store issues — that the routing switch is one
conditional UPDATE asserting the token, that a zero-row result is recorded as a conflict and
raised rather than retried, and that the evidence commits even when the routing change does
not. A live database would prove the same statements do what PostgreSQL says they do, which
is not the part that regresses.

The one rule the fake cannot express is that a single-row UPDATE is atomic. That is a
PostgreSQL guarantee the schema relies on, and the migration's structural test pins that
routing lives in one row so the guarantee applies.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

import pytest

from app.slate_deployment_store import (
    SlateActivationConflictError,
    activate,
    append_audit,
    find_rollback_target,
    reap_artifacts,
)
from app.slate_releases import ActivationPlan

DIGEST = "sha256:" + "c" * 64


class FakeCursor:
    """Records every statement and replays scripted results in order."""

    def __init__(self, conn: "FakeConnection"):
        self.conn = conn

    def execute(self, query: str, params: Sequence[Any] = ()) -> None:
        self.conn.statements.append((" ".join(query.split()), tuple(params)))
        self.conn._advance(query)

    def fetchone(self) -> Optional[Dict[str, Any]]:
        return self.conn._take()

    def fetchall(self) -> List[Dict[str, Any]]:
        value = self.conn._take()
        return value if isinstance(value, list) else ([] if value is None else [value])

    @property
    def rowcount(self) -> int:
        return self.conn.rowcount

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None


class FakeConnection:
    """A psycopg2-shaped connection whose results are scripted per statement kind."""

    def __init__(self, results: Optional[List[Any]] = None, rowcount: int = 0):
        self.results = list(results or [])
        self.statements: List[tuple] = []
        self.commits = 0
        self.rollbacks = 0
        self.rowcount = rowcount
        self._pending: List[Any] = []

    def _advance(self, query: str) -> None:
        if self.results:
            self._pending.append(self.results.pop(0))

    def _take(self) -> Any:
        return self._pending.pop(0) if self._pending else None

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class FakeDb:
    """Minimal ``_DbLike`` returning one connection."""

    def __init__(self, conn: FakeConnection):
        self._conn = conn

    def connect(self) -> FakeConnection:
        return self._conn


def promotion_plan(**overrides) -> ActivationPlan:
    """A promotion plan replacing rel-0 with rel-1."""
    base = dict(
        action="promotion",
        environment_id="env-1",
        release_id="rel-1",
        artifact_digest=DIGEST,
        replaces_release_id="rel-0",
        expected_routing_version=7,
        invalidated_pages=12,
    )
    return ActivationPlan(**{**base, **overrides})


def statements_matching(conn: FakeConnection, pattern: str) -> List[tuple]:
    """Every recorded statement matching a regex."""
    return [s for s in conn.statements if re.search(pattern, s[0], re.IGNORECASE)]


class TestSuccessfulActivation:
    def conn(self) -> FakeConnection:
        # ledger insert -> id; conditional update -> new routing_version
        return FakeConnection(results=[{"id": "act-1"}, {"routing_version": 8}])

    def test_activation_returns_the_new_routing_version(self):
        conn = self.conn()
        result = activate(
            FakeDb(conn),
            promotion_plan(),
            tenant_id="t-1",
            actor_id="u-1",
            actor_name="Dana",
            actor_kind="user",
        )
        assert result["routingVersion"] == 8
        assert result["activationId"] == "act-1"

    def test_the_routing_switch_is_a_single_conditional_update(self):
        # Criterion 2. One row, one statement, guarded by the token the plan was built on.
        conn = self.conn()
        activate(
            FakeDb(conn),
            promotion_plan(),
            tenant_id="t-1",
            actor_id="u-1",
            actor_name="Dana",
            actor_kind="user",
        )
        switches = statements_matching(conn, r"UPDATE apiome\.slate_environments")
        assert len(switches) == 1
        sql, params = switches[0]
        assert "routing_version = routing_version + 1" in sql
        assert "AND routing_version = %s" in sql
        assert 7 in params

    def test_the_switch_is_tenant_scoped(self):
        conn = self.conn()
        activate(
            FakeDb(conn),
            promotion_plan(),
            tenant_id="t-1",
            actor_id="u-1",
            actor_name="Dana",
            actor_kind="user",
        )
        sql, params = statements_matching(conn, r"UPDATE apiome\.slate_environments")[0]
        assert "tenant_id = %s::uuid" in sql
        assert "t-1" in params

    def test_no_statement_creates_an_artifact(self):
        # Criterion 3: there is no path from activation to a build.
        conn = self.conn()
        activate(
            FakeDb(conn),
            promotion_plan(),
            tenant_id="t-1",
            actor_id="u-1",
            actor_name="Dana",
            actor_kind="user",
        )
        assert statements_matching(conn, r"INSERT INTO apiome\.slate_artifacts") == []

    def test_the_routed_digest_is_recorded_on_the_ledger(self):
        # The ledger alone must evidence that promotion routed existing bytes.
        conn = self.conn()
        activate(
            FakeDb(conn),
            promotion_plan(),
            tenant_id="t-1",
            actor_id="u-1",
            actor_name="Dana",
            actor_kind="user",
        )
        _, params = statements_matching(conn, r"INSERT INTO apiome\.slate_activations")[0]
        assert DIGEST in params

    def test_the_outgoing_release_is_superseded_and_deactivated(self):
        conn = self.conn()
        activate(
            FakeDb(conn),
            promotion_plan(),
            tenant_id="t-1",
            actor_id="u-1",
            actor_name="Dana",
            actor_kind="user",
        )
        supersede = [
            s for s in statements_matching(conn, r"UPDATE apiome\.slate_releases")
            if "superseded" in s[0]
        ]
        assert len(supersede) == 1
        assert "rel-0" in supersede[0][1]

    def test_activation_completed_at_is_not_stamped_at_switch_time(self):
        # The gap between activated_at and activation_completed_at IS the SLO. Setting both
        # here would make every rollout look instantaneous and leave nothing to measure.
        conn = self.conn()
        activate(
            FakeDb(conn),
            promotion_plan(),
            tenant_id="t-1",
            actor_id="u-1",
            actor_name="Dana",
            actor_kind="user",
        )
        activating = [
            s for s in statements_matching(conn, r"UPDATE apiome\.slate_releases")
            if "status = 'active'" in s[0]
        ]
        assert len(activating) == 1
        assert "activation_completed_at" not in activating[0][0]

    def test_an_audit_entry_is_written_in_the_same_transaction(self):
        conn = self.conn()
        activate(
            FakeDb(conn),
            promotion_plan(),
            tenant_id="t-1",
            actor_id="u-1",
            actor_name="Dana",
            actor_kind="user",
        )
        audits = statements_matching(conn, r"INSERT INTO apiome\.slate_release_audit")
        assert len(audits) == 1
        assert conn.commits == 1

    def test_the_audit_entry_says_no_rebuild_occurred(self):
        conn = self.conn()
        activate(
            FakeDb(conn),
            promotion_plan(),
            tenant_id="t-1",
            actor_id="u-1",
            actor_name="Dana",
            actor_kind="user",
        )
        _, params = statements_matching(conn, r"INSERT INTO apiome\.slate_release_audit")[0]
        assert any("without rebuilding" in str(p) for p in params)

    def test_a_first_activation_is_recorded_as_initial_not_promotion(self):
        conn = FakeConnection(results=[{"id": "act-1"}, {"routing_version": 1}])
        activate(
            FakeDb(conn),
            promotion_plan(replaces_release_id=None),
            tenant_id="t-1",
            actor_id="u-1",
            actor_name="Dana",
            actor_kind="user",
        )
        _, params = statements_matching(conn, r"INSERT INTO apiome\.slate_activations")[0]
        assert "initial" in params

    def test_a_rollback_is_recorded_as_rollback(self):
        conn = FakeConnection(results=[{"id": "act-1"}, {"routing_version": 9}])
        activate(
            FakeDb(conn),
            promotion_plan(action="rollback"),
            tenant_id="t-1",
            actor_id="u-1",
            actor_name="Dana",
            actor_kind="user",
        )
        _, params = statements_matching(conn, r"INSERT INTO apiome\.slate_activations")[0]
        assert "rollback" in params

    def test_a_rollback_audit_entry_says_rolled_back(self):
        conn = FakeConnection(results=[{"id": "act-1"}, {"routing_version": 9}])
        activate(
            FakeDb(conn),
            promotion_plan(action="rollback"),
            tenant_id="t-1",
            actor_id="u-1",
            actor_name="Dana",
            actor_kind="user",
        )
        _, params = statements_matching(conn, r"INSERT INTO apiome\.slate_release_audit")[0]
        assert "Rolled back" in params


class TestConcurrentPromotion:
    """Criterion 4: the second of two simultaneous promotions must lose, loudly."""

    def conn(self) -> FakeConnection:
        # ledger insert -> id; conditional update -> NO ROW (another writer won);
        # routing_version probe -> the value that actually won.
        return FakeConnection(results=[{"id": "act-2"}, None, {"routing_version": 9}])

    def activate_losing(self, conn: FakeConnection):
        return activate(
            FakeDb(conn),
            promotion_plan(),
            tenant_id="t-1",
            actor_id="u-2",
            actor_name="Sam",
            actor_kind="user",
        )

    def test_a_lost_race_raises_rather_than_silently_overwriting(self):
        conn = self.conn()
        with pytest.raises(SlateActivationConflictError):
            self.activate_losing(conn)

    def test_the_conflict_reports_both_routing_versions(self):
        conn = self.conn()
        with pytest.raises(SlateActivationConflictError) as exc:
            self.activate_losing(conn)
        assert exc.value.expected_routing_version == 7
        assert exc.value.actual_routing_version == 9

    def test_the_losing_attempt_is_recorded_as_a_conflict(self):
        conn = self.conn()
        with pytest.raises(SlateActivationConflictError):
            self.activate_losing(conn)
        conflicts = [
            s for s in statements_matching(conn, r"UPDATE apiome\.slate_activations")
            if "conflict" in s[0]
        ]
        assert len(conflicts) == 1

    def test_the_evidence_commits_even_though_routing_did_not_change(self):
        # A lost promotion must be reconstructable afterwards, not merely reported at the time.
        conn = self.conn()
        with pytest.raises(SlateActivationConflictError):
            self.activate_losing(conn)
        assert conn.commits == 1
        assert conn.rollbacks == 0

    def test_a_refused_activation_writes_an_audit_entry(self):
        conn = self.conn()
        with pytest.raises(SlateActivationConflictError):
            self.activate_losing(conn)
        audits = statements_matching(conn, r"INSERT INTO apiome\.slate_release_audit")
        assert len(audits) == 1
        assert any("concurrent activation" in str(p) for p in audits[0][1])

    def test_the_loser_never_supersedes_the_release_that_won(self):
        # This is the corruption the token exists to prevent.
        conn = self.conn()
        with pytest.raises(SlateActivationConflictError):
            self.activate_losing(conn)
        supersede = [
            s for s in statements_matching(conn, r"UPDATE apiome\.slate_releases")
            if "superseded" in s[0]
        ]
        assert supersede == []

    def test_the_loser_never_marks_its_own_release_active(self):
        conn = self.conn()
        with pytest.raises(SlateActivationConflictError):
            self.activate_losing(conn)
        activating = [
            s for s in statements_matching(conn, r"UPDATE apiome\.slate_releases")
            if "status = 'active'" in s[0]
        ]
        assert activating == []

    def test_there_is_no_retry_or_last_write_wins_path(self):
        conn = self.conn()
        with pytest.raises(SlateActivationConflictError):
            self.activate_losing(conn)
        switches = statements_matching(conn, r"UPDATE apiome\.slate_environments")
        assert len(switches) == 1

    def test_a_missing_environment_reports_an_unknown_actual_version(self):
        conn = FakeConnection(results=[{"id": "act-3"}, None, None])
        with pytest.raises(SlateActivationConflictError) as exc:
            self.activate_losing(conn)
        assert exc.value.actual_routing_version is None


class TestFailedActivation:
    def test_an_unexpected_failure_rolls_the_whole_transaction_back(self):
        # A failed activation must leave the lane serving exactly what it served before.
        class Exploding(FakeConnection):
            def _advance(self, query: str) -> None:
                if "UPDATE apiome.slate_environments" in query:
                    raise RuntimeError("connection lost mid-activation")
                super()._advance(query)

        conn = Exploding(results=[{"id": "act-4"}, {"routing_version": 8}])
        with pytest.raises(RuntimeError):
            activate(
                FakeDb(conn),
                promotion_plan(),
                tenant_id="t-1",
                actor_id="u-1",
                actor_name="Dana",
                actor_kind="user",
            )
        assert conn.rollbacks == 1
        assert conn.commits == 0


class TestAuditIsAppendOnly:
    def test_append_audit_only_ever_inserts(self):
        conn = FakeConnection()
        append_audit(
            FakeDb(conn),
            tenant_id="t-1",
            release_id="rel-1",
            actor_id="u-1",
            actor_name="Dana",
            actor_kind="user",
            summary="Promotion refused",
            detail="stale-approval",
        )
        assert len(statements_matching(conn, r"INSERT INTO apiome\.slate_release_audit")) == 1
        assert statements_matching(conn, r"UPDATE apiome\.slate_release_audit") == []
        assert statements_matching(conn, r"DELETE FROM apiome\.slate_release_audit") == []

    def test_a_failed_audit_write_rolls_back(self):
        class Exploding(FakeConnection):
            def _advance(self, query: str) -> None:
                raise RuntimeError("write failed")

        conn = Exploding()
        with pytest.raises(RuntimeError):
            append_audit(
                FakeDb(conn),
                tenant_id="t-1",
                release_id="rel-1",
                actor_id=None,
                actor_name="Scheduled build",
                actor_kind="automation",
                summary="Promotion refused",
            )
        assert conn.rollbacks == 1


class TestRollbackTargetSelection:
    def test_only_retained_targets_with_stored_bytes_qualify(self):
        conn = FakeConnection(results=[{"id": "rel-1", "artifact_digest": DIGEST}])
        find_rollback_target(FakeDb(conn), tenant_id="t-1", environment_id="env-1")
        sql, _ = conn.statements[0]
        assert "a.reaped_at IS NULL" in sql
        assert "a.storage_uri IS NOT NULL" in sql

    def test_only_releases_that_once_served_qualify(self):
        conn = FakeConnection(results=[None])
        find_rollback_target(FakeDb(conn), tenant_id="t-1", environment_id="env-1")
        sql, _ = conn.statements[0]
        assert "r.status IN ('superseded', 'rolled-back')" in sql

    def test_the_most_recently_deactivated_release_is_chosen(self):
        conn = FakeConnection(results=[None])
        find_rollback_target(FakeDb(conn), tenant_id="t-1", environment_id="env-1")
        sql, _ = conn.statements[0]
        assert "ORDER BY r.deactivated_at DESC" in sql

    def test_the_lookup_is_tenant_scoped(self):
        conn = FakeConnection(results=[None])
        find_rollback_target(FakeDb(conn), tenant_id="t-1", environment_id="env-1")
        sql, params = conn.statements[0]
        assert "r.tenant_id = %s::uuid" in sql
        assert "t-1" in params


class TestRetentionSweep:
    def test_an_empty_sweep_touches_nothing(self):
        conn = FakeConnection()
        assert reap_artifacts(FakeDb(conn), tenant_id="t-1", release_ids=[]) == 0
        assert conn.statements == []

    def test_reaping_clears_the_bytes_without_deleting_the_row(self):
        # History must keep its digest; ON DELETE RESTRICT would refuse a delete anyway.
        conn = FakeConnection(rowcount=2)
        reap_artifacts(FakeDb(conn), tenant_id="t-1", release_ids=["rel-1", "rel-2"])
        sql, _ = conn.statements[0]
        assert "UPDATE apiome.slate_artifacts" in sql
        assert "reaped_at = %s" in sql
        assert "storage_uri = NULL" in sql
        assert "DELETE" not in sql.upper()

    def test_the_active_release_artifact_is_never_reaped(self):
        conn = FakeConnection(rowcount=0)
        reap_artifacts(FakeDb(conn), tenant_id="t-1", release_ids=["rel-1"])
        sql, _ = conn.statements[0]
        assert "status = 'active'" in sql
        assert "id NOT IN" in sql

    def test_an_already_reaped_artifact_is_skipped(self):
        conn = FakeConnection(rowcount=0)
        reap_artifacts(FakeDb(conn), tenant_id="t-1", release_ids=["rel-1"])
        sql, _ = conn.statements[0]
        assert "reaped_at IS NULL" in sql

    def test_the_sweep_is_tenant_scoped(self):
        conn = FakeConnection(rowcount=1)
        reap_artifacts(FakeDb(conn), tenant_id="t-1", release_ids=["rel-1"])
        sql, params = conn.statements[0]
        assert "tenant_id = %s::uuid" in sql
        assert "t-1" in params

    def test_the_reaped_count_is_returned(self):
        conn = FakeConnection(rowcount=3)
        assert reap_artifacts(FakeDb(conn), tenant_id="t-1", release_ids=["a", "b", "c"]) == 3
