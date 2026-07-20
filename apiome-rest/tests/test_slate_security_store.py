"""Security control-plane persistence — UXE-3.2 (private-suite#2474).

Exercises :mod:`app.slate_security_store` against a scripted fake connection, following the
``test_slate_cache_store.py`` precedent. No live Postgres: this asserts the SQL these functions
emit and the transaction discipline around it.

Four properties get the most attention, because each fails silently:

* **Every read is tenant-scoped.** A query that forgot ``tenant_id`` would work perfectly in every
  single-tenant test and leak across tenants in production.
* **The policy version is a compare-and-set, not a read-then-write.** Two operators editing rules
  during one incident is the normal case, and the second must be refused rather than merged.
* **Every rule write leaves a revision behind, inside the same transaction.** A change with no
  stored body is a change that cannot be reverted, and a revision written outside the transaction
  would claim a change that rolled back.
* **Redaction is real, not promised.** V188's CHECK constrains only top-level keys.
  :func:`redact_evidence` is what actually stops a cookie, a nested object or a full client
  address from reaching the database.

One detail of the fake is worth stating, because the scripts below depend on it: ``execute``
queues its scripted result and ``fetchone`` takes from the front of that queue, so a statement
that executes without fetching (the revision INSERT) consumes the *next* script slot. The
sequences here are written accordingly.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

import pytest

from app.slate_security_store import (
    EVIDENCE_ALLOWED_KEYS,
    SlateSecurityPolicyConflictError,
    SlateSecurityStoreError,
    append_audit,
    create_exception,
    delete_exception,
    delete_rule,
    ensure_policy,
    get_event,
    get_policy,
    get_rule,
    last_simulated_at,
    list_approvals,
    list_audit,
    list_events,
    list_exceptions,
    list_managed_groups,
    list_revisions,
    list_rules,
    record_approval,
    record_event,
    redact_evidence,
    revert_rule,
    rule_evaluation_context,
    set_managed_group,
    set_presets,
    set_rollout,
    upsert_rule,
)

TENANT = "11111111-1111-1111-1111-111111111111"
SITE = "22222222-2222-2222-2222-222222222222"
ENV = "33333333-3333-3333-3333-333333333333"
RULE = "44444444-4444-4444-4444-444444444444"
EXCEPTION = "55555555-5555-5555-5555-555555555555"
EVENT = "66666666-6666-6666-6666-666666666666"

DIGEST = "sha256:" + "a" * 64
OTHER_DIGEST = "sha256:" + "b" * 64


class FakeCursor:
    """Records every statement and replays scripted results in order."""

    def __init__(self, conn: "FakeConnection") -> None:
        self.conn = conn

    def execute(self, query: str, params: Sequence[Any] = ()) -> None:
        self.conn.statements.append((" ".join(query.split()), tuple(params)))
        self.conn._advance()

    def fetchone(self) -> Optional[Dict[str, Any]]:
        return self.conn._take()

    def fetchall(self) -> List[Dict[str, Any]]:
        value = self.conn._take()
        return value if isinstance(value, list) else ([] if value is None else [value])

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None


class FakeConnection:
    """A psycopg2-shaped connection whose results are scripted per statement."""

    def __init__(self, results: Optional[List[Any]] = None) -> None:
        self.results = list(results or [])
        self.statements: List[tuple] = []
        self.commits = 0
        self.rollbacks = 0
        self._pending: List[Any] = []

    def _advance(self) -> None:
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

    def __init__(self, conn: FakeConnection) -> None:
        self._conn = conn

    def connect(self) -> FakeConnection:
        return self._conn


def db_with(*results: Any) -> tuple[FakeDb, FakeConnection]:
    """Build a fake database whose statements return ``results`` in order."""
    conn = FakeConnection(list(results))
    return FakeDb(conn), conn


def policy_row(**overrides) -> Dict[str, Any]:
    """A security policy row."""
    base = {
        "id": "policy-1",
        "tenant_id": TENANT,
        "site_id": SITE,
        "environment_id": ENV,
        "managed_ruleset": "core",
        "bot_preset": "balanced",
        "rate_preset": "standard",
        "challenge_mode": "managed",
        "preset_overrides": {},
        "managed_off_reason": None,
        "policy_version": 3,
        "edge_attached": False,
        "edge_provider": None,
    }
    base.update(overrides)
    return base


def rule_row(**overrides) -> Dict[str, Any]:
    """A stored security rule row."""
    base = {
        "id": RULE,
        "tenant_id": TENANT,
        "environment_id": ENV,
        "ordinal": 0,
        "enabled": True,
        "label": "Block admin probes",
        "matcher_kind": "prefix",
        "matcher_value": "/admin",
        "matcher_methods": ["GET"],
        "matcher_hosts": [],
        "conditions": [],
        "action": "block",
        "rate_requests": None,
        "rate_window_seconds": None,
        "rollout_mode": "simulate",
        "rollout_percent": 10,
        "expires_at": None,
        "acknowledged_warnings": [],
        "body_digest": DIGEST,
        "revision": 2,
    }
    base.update(overrides)
    return base


def rule_values(**overrides) -> Dict[str, Any]:
    """Column values for a rule write."""
    base = {
        "ordinal": 0,
        "enabled": True,
        "label": "Block admin probes",
        "matcher_kind": "prefix",
        "matcher_value": "/admin",
        "matcher_methods": ["GET"],
        "matcher_hosts": [],
        "action": "block",
        "rate_requests": None,
        "rate_window_seconds": None,
        "rollout_mode": "simulate",
        "rollout_percent": 10,
        "expires_at": None,
        "acknowledged_warnings": [],
        "body_digest": DIGEST,
    }
    base.update(overrides)
    return base


class TestTenantScoping:
    """A query that forgets tenant_id passes every single-tenant test and leaks in production."""

    def test_get_policy_is_tenant_scoped(self) -> None:
        db, conn = db_with(policy_row())
        get_policy(db, tenant_id=TENANT, environment_id=ENV)
        query, params = conn.statements[0]
        assert "tenant_id = %s::uuid" in query
        assert TENANT in params

    def test_list_rules_is_tenant_scoped_and_in_precedence_order(self) -> None:
        db, conn = db_with([])
        list_rules(db, tenant_id=TENANT, environment_id=ENV)
        query, params = conn.statements[0]
        assert "tenant_id = %s::uuid" in query
        assert "ORDER BY ordinal, id" in query
        assert TENANT in params

    def test_get_rule_is_scoped_to_lane_and_tenant(self) -> None:
        db, conn = db_with(rule_row())
        get_rule(db, tenant_id=TENANT, environment_id=ENV, rule_id=RULE)
        query, _ = conn.statements[0]
        assert "environment_id = %s::uuid AND tenant_id = %s::uuid" in query

    def test_list_managed_groups_is_tenant_scoped(self) -> None:
        db, conn = db_with([])
        list_managed_groups(db, tenant_id=TENANT, environment_id=ENV)
        assert "tenant_id = %s::uuid" in conn.statements[0][0]

    def test_list_exceptions_is_tenant_scoped(self) -> None:
        db, conn = db_with([])
        list_exceptions(db, tenant_id=TENANT, environment_id=ENV)
        assert "tenant_id = %s::uuid" in conn.statements[0][0]

    def test_list_events_is_tenant_scoped(self) -> None:
        db, conn = db_with([])
        list_events(db, tenant_id=TENANT, environment_id=ENV)
        assert "tenant_id = %s::uuid" in conn.statements[0][0]

    def test_list_audit_is_tenant_scoped(self) -> None:
        db, conn = db_with([])
        list_audit(db, tenant_id=TENANT, environment_id=ENV)
        assert "tenant_id = %s::uuid" in conn.statements[0][0]

    def test_get_event_is_scoped_to_lane_and_tenant(self) -> None:
        db, conn = db_with(None)
        assert get_event(db, tenant_id=TENANT, environment_id=ENV, event_id=EVENT) is None
        assert "environment_id = %s::uuid AND tenant_id = %s::uuid" in conn.statements[0][0]

    def test_revision_history_is_tenant_scoped_but_not_lane_scoped(self) -> None:
        """A deleted rule's history must stay readable; that is when a revert is most needed."""
        db, conn = db_with([])
        list_revisions(db, tenant_id=TENANT, rule_id=RULE)
        query, _ = conn.statements[0]
        assert "tenant_id = %s::uuid" in query
        assert "environment_id" not in query


class TestPolicyLifecycle:
    """A lane with no row is a lane running the shipped defaults, not a lane with no policy."""

    def test_an_existing_policy_is_returned_without_writing(self) -> None:
        db, conn = db_with(policy_row())
        result = ensure_policy(
            db, tenant_id=TENANT, site_id=SITE, environment_id=ENV, actor_id=None, actor_name="a"
        )
        assert result["managed_ruleset"] == "core"
        assert conn.commits == 0, "a read must not write"

    def test_a_missing_policy_is_created_with_the_shipped_defaults(self) -> None:
        db, conn = db_with(None, policy_row(policy_version=0))
        result = ensure_policy(
            db, tenant_id=TENANT, site_id=SITE, environment_id=ENV, actor_id=None, actor_name="a"
        )
        assert result["policy_version"] == 0
        insert = conn.statements[1][0]
        assert "INSERT INTO apiome.slate_security_policies" in insert
        assert "'core', 'balanced', 'standard', 'managed'" in insert
        assert conn.commits == 1

    def test_a_concurrent_first_read_re_reads_rather_than_raising(self) -> None:
        db, conn = db_with(None, None, policy_row())
        result = ensure_policy(
            db, tenant_id=TENANT, site_id=SITE, environment_id=ENV, actor_id=None, actor_name="a"
        )
        assert result["managed_ruleset"] == "core"
        assert "ON CONFLICT (environment_id) DO NOTHING" in conn.statements[1][0]

    def test_a_policy_that_cannot_be_read_after_insert_raises(self) -> None:
        db, _ = db_with(None, None, None)
        with pytest.raises(SlateSecurityStoreError) as excinfo:
            ensure_policy(
                db,
                tenant_id=TENANT,
                site_id=SITE,
                environment_id=ENV,
                actor_id=None,
                actor_name="a",
            )
        assert excinfo.value.code == "policy_not_found"

    def test_nothing_this_module_writes_can_attach_an_edge(self) -> None:
        """edge_attached has one honest value, and no statement here sets any other."""
        db, conn = db_with(None, policy_row())
        ensure_policy(
            db, tenant_id=TENANT, site_id=SITE, environment_id=ENV, actor_id=None, actor_name="a"
        )
        assert "edge_attached" not in conn.statements[1][0]


class TestOptimisticConcurrency:
    """The compare-and-set that makes two operators editing one lane during an incident safe."""

    def test_set_presets_carries_the_expected_version_in_the_where_clause(self) -> None:
        db, conn = db_with({"policy_version": 4}, policy_row(managed_ruleset="strict"))
        set_presets(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            managed_ruleset="strict",
            bot_preset="balanced",
            rate_preset="standard",
            challenge_mode="managed",
            preset_overrides={},
            managed_off_reason=None,
            expected_policy_version=3,
            actor_id=None,
            actor_name="a",
        )
        bump = conn.statements[0]
        assert "policy_version = policy_version + 1" in bump[0]
        assert "WHERE environment_id = %s::uuid AND policy_version = %s" in bump[0]
        assert 3 in bump[1]

    def test_a_stale_expected_version_raises_rather_than_overwriting(self) -> None:
        db, conn = db_with(None, {"policy_version": 9})
        with pytest.raises(SlateSecurityPolicyConflictError) as excinfo:
            set_presets(
                db,
                tenant_id=TENANT,
                environment_id=ENV,
                managed_ruleset="off",
                bot_preset="off",
                rate_preset="off",
                challenge_mode="off",
                preset_overrides={},
                managed_off_reason="incident",
                expected_policy_version=3,
                actor_id=None,
                actor_name="a",
            )
        assert excinfo.value.expected_policy_version == 3
        assert excinfo.value.actual_policy_version == 9
        assert conn.rollbacks == 1, "a refused edit must leave nothing behind"
        assert conn.commits == 0

    def test_a_conflict_on_a_lane_with_no_policy_reports_no_actual_version(self) -> None:
        db, _ = db_with(None, None)
        with pytest.raises(SlateSecurityPolicyConflictError) as excinfo:
            delete_exception(
                db,
                tenant_id=TENANT,
                environment_id=ENV,
                exception_id=EXCEPTION,
                expected_policy_version=1,
            )
        assert excinfo.value.actual_policy_version is None

    def test_a_managed_group_change_bumps_the_policy_version_first(self) -> None:
        db, conn = db_with({"policy_version": 4}, {"group_id": "xss", "mode": "log"})
        set_managed_group(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            group_id="xss",
            mode="log",
            reason="trialling",
            expected_policy_version=3,
            actor_id=None,
            actor_name="a",
        )
        assert "policy_version = policy_version + 1" in conn.statements[0][0]
        assert "INSERT INTO apiome.slate_security_managed_groups" in conn.statements[1][0]

    def test_an_exception_write_bumps_the_policy_version_first(self) -> None:
        db, conn = db_with({"policy_version": 4}, {"id": EXCEPTION})
        create_exception(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            subject_kind="managed-group",
            subject_ref="xss",
            matcher_kind="prefix",
            matcher_value="/search",
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
            reason="docs quote markup",
            expected_policy_version=3,
            actor_id=None,
            actor_name="a",
        )
        assert "policy_version = policy_version + 1" in conn.statements[0][0]
        assert "INSERT INTO apiome.slate_security_exceptions" in conn.statements[1][0]


class TestRuleWritesRecordRevisions:
    """A change with no stored body is a change that cannot be reverted."""

    def test_creating_a_rule_records_it_as_revision_one(self) -> None:
        # bump, INSERT rule (fetched), revision INSERT (unfetched, consumes the next slot).
        db, conn = db_with({"policy_version": 1}, rule_row(revision=1), None)
        written = upsert_rule(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            rule_id=None,
            values=rule_values(),
            conditions=[],
            expected_policy_version=0,
            actor_id="user-1",
            actor_name="ken@example.com",
        )
        assert written["id"] == RULE
        emitted = [s[0] for s in conn.statements]
        assert any("INSERT INTO apiome.slate_security_rules" in s for s in emitted)
        revision = next(
            s for s in conn.statements if "slate_security_rule_revisions" in s[0]
        )
        assert "created" in revision[1]
        assert conn.commits == 1

    def test_replacing_a_rule_records_the_prior_body_before_mutating(self) -> None:
        prior = rule_row(revision=2, rollout_percent=10)
        # bump, SELECT prior, revision INSERT (unfetched — its slot feeds the UPDATE's fetchone).
        db, conn = db_with({"policy_version": 5}, prior, rule_row(revision=3), None)
        upsert_rule(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            rule_id=RULE,
            values=rule_values(rollout_percent=50),
            conditions=[],
            expected_policy_version=4,
            actor_id=None,
            actor_name="a",
        )
        order = [s[0] for s in conn.statements]
        revision_index = next(
            i for i, s in enumerate(order) if "slate_security_rule_revisions" in s
        )
        update_index = next(
            i for i, s in enumerate(order) if "UPDATE apiome.slate_security_rules" in s
        )
        assert revision_index < update_index, "the prior body must be kept before it is replaced"
        revision_params = conn.statements[revision_index][1]
        assert 2 in revision_params, "the revision recorded is the one being left"
        assert "updated" in revision_params

    def test_disabling_a_rule_is_recorded_as_a_disable_not_an_update(self) -> None:
        db, conn = db_with({"policy_version": 5}, rule_row(), rule_row(enabled=False), None)
        upsert_rule(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            rule_id=RULE,
            values=rule_values(enabled=False),
            conditions=[],
            expected_policy_version=4,
            actor_id=None,
            actor_name="a",
        )
        revision = next(s for s in conn.statements if "slate_security_rule_revisions" in s[0])
        assert "disabled" in revision[1]

    def test_replacing_a_rule_that_is_not_on_the_lane_raises_and_rolls_back(self) -> None:
        db, conn = db_with({"policy_version": 5}, None)
        with pytest.raises(SlateSecurityStoreError) as excinfo:
            upsert_rule(
                db,
                tenant_id=TENANT,
                environment_id=ENV,
                rule_id=RULE,
                values=rule_values(),
                conditions=[],
                expected_policy_version=4,
                actor_id=None,
                actor_name="a",
            )
        assert excinfo.value.code == "rule_not_found"
        assert conn.rollbacks == 1
        assert conn.commits == 0
        assert not any("slate_security_rule_revisions" in s[0] for s in conn.statements)

    def test_a_rollout_change_records_the_stage_it_left(self) -> None:
        db, conn = db_with(
            {"policy_version": 5}, rule_row(rollout_percent=10), rule_row(rollout_percent=100), None
        )
        set_rollout(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            rule_id=RULE,
            rollout_mode="enforce",
            rollout_percent=100,
            expected_policy_version=4,
            actor_id=None,
            actor_name="a",
        )
        revision = next(s for s in conn.statements if "slate_security_rule_revisions" in s[0])
        assert "rollout-changed" in revision[1]

    def test_deleting_a_rule_keeps_its_body_first(self) -> None:
        db, conn = db_with({"policy_version": 5}, rule_row(), None)
        assert delete_rule(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            rule_id=RULE,
            expected_policy_version=4,
            actor_id=None,
            actor_name="a",
        )
        order = [s[0] for s in conn.statements]
        revision_index = next(
            i for i, s in enumerate(order) if "slate_security_rule_revisions" in s
        )
        delete_index = next(
            i for i, s in enumerate(order) if "DELETE FROM apiome.slate_security_rules" in s
        )
        assert revision_index < delete_index
        assert "deleted" in conn.statements[revision_index][1]
        assert conn.commits == 1

    def test_deleting_a_rule_that_does_not_exist_raises_and_rolls_back(self) -> None:
        db, conn = db_with({"policy_version": 5}, None)
        with pytest.raises(SlateSecurityStoreError) as excinfo:
            delete_rule(
                db,
                tenant_id=TENANT,
                environment_id=ENV,
                rule_id=RULE,
                expected_policy_version=4,
                actor_id=None,
                actor_name="a",
            )
        assert excinfo.value.code == "rule_not_found"
        assert conn.rollbacks == 1

    def test_reverting_applies_the_stored_body(self) -> None:
        stored = {"id": "rev-1", "revision": 1, "body": rule_row(rollout_percent=0), "body_digest": DIGEST}
        db, conn = db_with(
            {"policy_version": 6}, stored, rule_row(revision=4), rule_row(rollout_percent=0), None
        )
        revert_rule(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            rule_id=RULE,
            revision=1,
            expected_policy_version=5,
            actor_id=None,
            actor_name="a",
        )
        revision = next(s for s in conn.statements if "INSERT INTO apiome.slate_security_rule_revisions" in s[0])
        assert "reverted" in revision[1]
        update = next(s for s in conn.statements if "UPDATE apiome.slate_security_rules" in s[0])
        assert 0 in update[1], "the stored rollout_percent is what gets applied"

    def test_reverting_to_a_revision_that_does_not_exist_raises(self) -> None:
        db, conn = db_with({"policy_version": 6}, None)
        with pytest.raises(SlateSecurityStoreError) as excinfo:
            revert_rule(
                db,
                tenant_id=TENANT,
                environment_id=ENV,
                rule_id=RULE,
                revision=9,
                expected_policy_version=5,
                actor_id=None,
                actor_name="a",
            )
        assert excinfo.value.code == "revision_not_found"
        assert conn.rollbacks == 1


class TestRuleHistoryReconstruction:
    """``simulated_at`` and ``previous_rollout_percent`` are facts about history, not about a body.

    The pure module reads both and is query-free by design, so they are reconstructed here. A
    client able to assert ``simulated_at`` could promote a blocking rule straight to enforcing,
    which is the lockout the ``enforce-without-simulation`` refusal exists to prevent.
    """

    def test_a_simulate_revision_in_history_is_found(self) -> None:
        moment = datetime(2026, 7, 1, tzinfo=timezone.utc)
        db, conn = db_with({"at": moment})
        assert last_simulated_at(db, tenant_id=TENANT, rule_id=RULE) == moment
        query, _ = conn.statements[0]
        assert "body ->> 'rollout_mode' = 'simulate'" in query

    def test_a_rule_that_never_simulated_reports_none(self) -> None:
        db, _ = db_with(None)
        assert last_simulated_at(db, tenant_id=TENANT, rule_id=RULE) is None

    def test_the_context_reports_both_facts_for_an_existing_rule(self) -> None:
        moment = datetime(2026, 7, 1, tzinfo=timezone.utc)
        db, _ = db_with({"at": moment}, rule_row(rollout_percent=25))
        context = rule_evaluation_context(
            db, tenant_id=TENANT, environment_id=ENV, rule_id=RULE
        )
        assert context["simulated_at"] == moment
        assert context["previous_rollout_percent"] == 25

    def test_a_create_has_no_history_so_both_facts_are_absent(self) -> None:
        """Which is why a create that asks to enforce immediately is refused."""
        db, conn = db_with()
        context = rule_evaluation_context(
            db, tenant_id=TENANT, environment_id=ENV, rule_id=None
        )
        assert context == {"simulated_at": None, "previous_rollout_percent": None}
        assert conn.statements == [], "a rule that does not exist needs no query"

    def test_a_deleted_rule_falls_back_to_its_newest_revision(self) -> None:
        db, _ = db_with(
            {"at": datetime(2026, 7, 1, tzinfo=timezone.utc)},
            None,
            [{"body": {"rollout_percent": 40}}],
        )
        context = rule_evaluation_context(
            db, tenant_id=TENANT, environment_id=ENV, rule_id=RULE
        )
        assert context["previous_rollout_percent"] == 40


class TestApprovals:
    """Dual control is looked up two ways, because the two failures need different actions."""

    def test_approvals_can_be_narrowed_to_one_subject(self) -> None:
        db, conn = db_with([])
        list_approvals(db, tenant_id=TENANT, environment_id=ENV, subject_id=RULE)
        query, params = conn.statements[0]
        assert "subject_id = %s" in query
        assert RULE in params

    def test_approvals_can_be_narrowed_to_one_approved_body(self) -> None:
        db, conn = db_with([])
        list_approvals(db, tenant_id=TENANT, environment_id=ENV, digest=DIGEST)
        query, params = conn.statements[0]
        assert "digest = %s" in query
        assert DIGEST in params

    def test_an_approval_records_both_identity_keys(self) -> None:
        db, conn = db_with({"id": "approval-1"})
        record_approval(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            subject_kind="rule",
            subject_id=RULE,
            digest=DIGEST,
            author_actor_id="user-1",
            author_actor_name="ken@example.com",
            author_actor_key="user-1",
            approver_actor_id="user-2",
            approver_actor_name="sam@example.com",
            approver_actor_key="user-2",
            note="looks right",
        )
        query, params = conn.statements[0]
        assert "INSERT INTO apiome.slate_security_approvals" in query
        assert "user-1" in params and "user-2" in params
        assert DIGEST in params


class TestEventHonesty:
    """Nothing was observed and nothing was stopped, and there is no argument that says otherwise."""

    def test_an_event_is_written_as_a_simulation_that_stopped_nothing(self) -> None:
        db, conn = db_with({"id": EVENT})
        record_event(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            rule_kind="rule",
            rule_ref=RULE,
            rule_label="Block admin probes",
            route="/admin",
            method="GET",
            release_id=None,
            region=None,
            action="would-block",
            evidence={"path": "/admin"},
        )
        query, params = conn.statements[0]
        assert "'policy-simulation'" in query
        assert "FALSE, FALSE" in query, "mitigated and edge_attached are literals, not parameters"
        assert "edge-observed" not in query
        assert "would-block" in params

    def test_retention_defaults_to_thirty_days_after_the_event(self) -> None:
        db, conn = db_with({"id": EVENT})
        record_event(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            rule_kind="rule",
            rule_ref=RULE,
            rule_label="r",
            route="/admin",
            method="GET",
            release_id=None,
            region=None,
            action="logged",
            evidence={},
        )
        params = conn.statements[0][1]
        moments = [p for p in params if isinstance(p, datetime)]
        assert len(moments) == 2
        at, retain_until = moments
        assert retain_until - at == timedelta(days=30)

    def test_the_store_redacts_rather_than_trusting_the_caller(self) -> None:
        db, conn = db_with({"id": EVENT})
        record_event(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            rule_kind="rule",
            rule_ref=RULE,
            rule_label="r",
            route="/admin",
            method="GET",
            release_id=None,
            region=None,
            action="logged",
            evidence={"cookie": "session=abc", "path": "/admin"},
        )
        encoded = next(p for p in conn.statements[0][1] if isinstance(p, str) and p.startswith("{"))
        assert "session=abc" not in encoded
        assert "cookie" not in encoded
        assert "/admin" in encoded

    def test_events_can_be_filtered_on_every_designer_dimension(self) -> None:
        db, conn = db_with([])
        list_events(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            rule_ref="xss",
            action="would-block",
            route="/admin",
            release_id="77777777-7777-7777-7777-777777777777",
            region="eu-west",
            source="policy-simulation",
        )
        query, params = conn.statements[0]
        for column in ("rule_ref", "action", "route", "release_id", "region", "source"):
            assert f"{column} = %s" in query
        assert "release_id = %s::uuid" in query
        assert "eu-west" in params


class TestRedaction:
    """V188's CHECK is the backstop. This is the mechanism, and it has to be stronger."""

    def test_a_cookie_never_survives(self) -> None:
        assert redact_evidence({"cookie": "session=abc"}) == {}

    def test_an_authorization_header_never_survives(self) -> None:
        assert redact_evidence({"authorization": "Bearer abc", "Cookie": "x=1"}) == {}

    def test_an_allowed_key_is_kept(self) -> None:
        assert redact_evidence({"path": "/docs", "method": "GET"}) == {
            "path": "/docs",
            "method": "GET",
        }

    def test_a_nested_object_under_an_allowed_key_is_dropped(self) -> None:
        """The DB CHECK constrains only top-level keys, so this is the smuggling route."""
        assert redact_evidence({"userAgent": {"cookie": "session=abc"}}) == {}

    def test_a_list_under_an_allowed_key_is_dropped(self) -> None:
        assert redact_evidence({"query": ["a", "b"]}) == {}

    def test_every_surviving_value_is_a_string(self) -> None:
        redacted = redact_evidence({"statusCode": 403, "botClass": "automated"})
        assert redacted == {"statusCode": "403", "botClass": "automated"}
        assert all(isinstance(v, str) for v in redacted.values())

    def test_free_text_is_bounded(self) -> None:
        redacted = redact_evidence({"userAgent": "u" * 5000, "matchedFragment": "m" * 5000})
        assert len(redacted["userAgent"]) == 256
        assert len(redacted["matchedFragment"]) == 256

    def test_an_ipv4_address_is_reduced_to_a_network(self) -> None:
        assert redact_evidence({"clientIpPrefix": "203.0.113.42"}) == {
            "clientIpPrefix": "203.0.113.0/24"
        }

    def test_an_ipv6_address_is_reduced_to_a_forty_eight(self) -> None:
        redacted = redact_evidence({"clientIpPrefix": "2001:db8:1234:5678::1"})
        assert redacted["clientIpPrefix"] == "2001:db8:1234::/48"

    def test_a_prefix_narrower_than_ours_is_generalized_to_ours(self) -> None:
        """A /28 identifies far fewer people than a /24, so it is widened rather than kept."""
        assert redact_evidence({"clientIpPrefix": "203.0.113.0/28"}) == {
            "clientIpPrefix": "203.0.113.0/24"
        }

    def test_a_broader_prefix_the_caller_chose_is_left_alone(self) -> None:
        """Generalizing further than we require is the caller's to do; narrowing it is not ours."""
        assert redact_evidence({"clientIpPrefix": "203.0.0.0/16"}) == {
            "clientIpPrefix": "203.0.0.0/16"
        }

    def test_an_address_arriving_under_another_key_is_still_reduced(self) -> None:
        redacted = redact_evidence({"matchedFragment": "198.51.100.7"})
        assert redacted["matchedFragment"] == "198.51.100.0/24"

    def test_a_value_that_is_not_an_address_is_not_stored_as_one(self) -> None:
        assert redact_evidence({"clientIpPrefix": "not-an-address"}) == {}

    def test_no_key_outside_the_allowlist_can_appear(self) -> None:
        redacted = redact_evidence(
            {key: "x" for key in EVIDENCE_ALLOWED_KEYS} | {"secret": "x", "set-cookie": "y"}
        )
        assert set(redacted) <= set(EVIDENCE_ALLOWED_KEYS)
        assert "secret" not in redacted


class TestAudit:
    """Who read the record of who disabled the WAF is part of that record."""

    def test_an_audit_entry_names_its_subject(self) -> None:
        db, conn = db_with(None)
        append_audit(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            actor_id=None,
            actor_name="ken@example.com",
            actor_kind="user",
            subject_kind="policy",
            subject_id=None,
            summary="Managed ruleset disabled",
            detail="incident 42",
        )
        query, params = conn.statements[0]
        assert "INSERT INTO apiome.slate_security_audit" in query
        assert "Managed ruleset disabled" in params
        assert conn.commits == 1

    def test_an_export_is_itself_an_audited_subject(self) -> None:
        db, conn = db_with(None)
        append_audit(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            actor_id=None,
            actor_name="auditor@example.com",
            actor_kind="user",
            subject_kind="export",
            subject_id=None,
            summary="Security audit exported",
        )
        assert "export" in conn.statements[0][1]

    def test_the_audit_trail_is_newest_first(self) -> None:
        db, conn = db_with([])
        list_audit(db, tenant_id=TENANT, environment_id=ENV)
        assert "ORDER BY at DESC" in conn.statements[0][0]
