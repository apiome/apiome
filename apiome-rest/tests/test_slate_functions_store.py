"""Function control-plane persistence — UXE-3.3 (private-suite#2475).

Exercises :mod:`app.slate_functions_store` against a scripted fake connection, following the
``test_slate_security_store.py`` precedent. No live Postgres: this asserts the SQL these functions
emit and the transaction discipline around it.

Five properties get the most attention, because each fails silently:

* **Every read is tenant-scoped.** A query that forgot ``tenant_id`` would work perfectly in every
  single-tenant test and leak across tenants in production.
* **The policy version is a compare-and-set, not a read-then-write.** Two operators editing
  functions during one rollout is the normal case, and the second must be refused rather than
  merged.
* **Every function write leaves a revision behind, inside the same transaction.** A change with no
  stored body is a change that cannot be reverted, and a revision written outside the transaction
  would claim a change that rolled back. ``add_version`` is included: promoting new code is a
  change to the function even when nothing else moved.
* **Deny-by-default is the absence of a row.** No statement here writes a ``granted`` flag, and
  revoking is a DELETE, so a write bug can only fail closed.
* **Nothing can claim an execution.** ``source``, ``executed`` and ``edge_attached`` are SQL
  literals with no parameter behind them, so there is no argument by which a caller can record an
  observation or a run.

One detail of the fake is worth stating, because the scripts below depend on it: ``execute``
queues its scripted result and ``fetchone`` takes from the front of that queue, so a statement
that executes without fetching (the revision INSERT) consumes the *next* script slot. The
sequences here are written accordingly.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

import pytest

from app.slate_functions_store import (
    EVIDENCE_ALLOWED_KEYS,
    SlateFunctionPolicyConflictError,
    SlateFunctionStoreError,
    add_version,
    append_audit,
    delete_egress_rule,
    delete_function,
    delete_secret_ref,
    delete_variant,
    ensure_policy,
    function_evaluation_context,
    get_function,
    get_invocation,
    get_policy,
    grant_capability,
    last_simulated_at,
    list_approvals,
    list_audit,
    list_capabilities,
    list_egress_rules,
    list_functions,
    list_invocations,
    list_revisions,
    list_secret_refs,
    list_variants,
    list_versions,
    record_approval,
    record_invocation,
    redact_evidence,
    revert_function,
    revoke_capability,
    set_egress_rule,
    set_policy,
    set_rollout,
    set_secret_ref,
    upsert_function,
    upsert_variant,
)

TENANT = "11111111-1111-1111-1111-111111111111"
SITE = "22222222-2222-2222-2222-222222222222"
ENV = "33333333-3333-3333-3333-333333333333"
FUNCTION = "44444444-4444-4444-4444-444444444444"
VARIANT = "55555555-5555-5555-5555-555555555555"
INVOCATION = "66666666-6666-6666-6666-666666666666"
EGRESS = "77777777-7777-7777-7777-777777777777"
SECRET_REF = "88888888-8888-8888-8888-888888888888"
VERSION = "99999999-9999-9999-9999-999999999999"

DIGEST = "sha256:" + "a" * 64
SOURCE_DIGEST = "sha256:" + "c" * 64


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
    """A function policy row."""
    base = {
        "id": "policy-1",
        "tenant_id": TENANT,
        "site_id": SITE,
        "environment_id": ENV,
        "functions_enabled": True,
        "policy_version": 3,
        "edge_attached": False,
        "edge_provider": None,
        "default_region": "auto",
        "default_residency_class": "in-region-only",
        "default_cpu_ms_limit": 50,
        "default_memory_mb_limit": 128,
        "default_wall_ms_limit": 5000,
        "residency_waiver_reason": None,
    }
    base.update(overrides)
    return base


def function_row(**overrides) -> Dict[str, Any]:
    """A stored function row."""
    base = {
        "id": FUNCTION,
        "tenant_id": TENANT,
        "environment_id": ENV,
        "ordinal": 0,
        "enabled": True,
        "label": "Add locale header",
        "matcher_kind": "prefix",
        "matcher_value": "/guide/",
        "matcher_methods": ["GET"],
        "matcher_hosts": [],
        "runtime": "js-isolate",
        "active_version_id": VERSION,
        "rollout_mode": "simulate",
        "rollout_percent": 10,
        "region": None,
        "residency_class": None,
        "cpu_ms_limit": None,
        "memory_mb_limit": None,
        "wall_ms_limit": None,
        "env_var_names": [],
        "acknowledged_warnings": [],
        "body_digest": DIGEST,
        "revision": 2,
    }
    base.update(overrides)
    return base


def function_values(**overrides) -> Dict[str, Any]:
    """Column values for a function write."""
    base = {
        "ordinal": 0,
        "enabled": True,
        "label": "Add locale header",
        "matcher_kind": "prefix",
        "matcher_value": "/guide/",
        "matcher_methods": ["GET"],
        "matcher_hosts": [],
        "runtime": "js-isolate",
        "active_version_id": VERSION,
        "rollout_mode": "simulate",
        "rollout_percent": 10,
        "region": None,
        "residency_class": None,
        "cpu_ms_limit": None,
        "memory_mb_limit": None,
        "wall_ms_limit": None,
        "env_var_names": [],
        "acknowledged_warnings": [],
        "body_digest": DIGEST,
    }
    base.update(overrides)
    return base


def variant_values(**overrides) -> Dict[str, Any]:
    """Column values for a variant write."""
    base = {
        "ordinal": 0,
        "label": "German readers",
        "audience_kind": "geo",
        "audience_matcher": [{"kind": "country", "equals": "DE"}],
        "fallback_variant": "default",
        "cache_key_effect": "vary-on-dimension",
        "analytics_dimension": "country",
        "privacy_class": "non-personal",
        "consent_basis": "not-required",
        "enabled": True,
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

    def test_list_functions_is_tenant_scoped_and_in_precedence_order(self) -> None:
        db, conn = db_with([])
        list_functions(db, tenant_id=TENANT, environment_id=ENV)
        query, params = conn.statements[0]
        assert "tenant_id = %s::uuid" in query
        assert "ORDER BY ordinal, id" in query
        assert TENANT in params

    def test_get_function_is_scoped_to_lane_and_tenant(self) -> None:
        db, conn = db_with(function_row())
        get_function(db, tenant_id=TENANT, environment_id=ENV, function_id=FUNCTION)
        query, _ = conn.statements[0]
        assert "environment_id = %s::uuid AND tenant_id = %s::uuid" in query

    def test_list_capabilities_is_tenant_scoped(self) -> None:
        db, conn = db_with([])
        list_capabilities(db, tenant_id=TENANT, environment_id=ENV)
        assert "tenant_id = %s::uuid" in conn.statements[0][0]

    def test_list_egress_rules_is_tenant_scoped(self) -> None:
        db, conn = db_with([])
        list_egress_rules(db, tenant_id=TENANT, environment_id=ENV)
        assert "tenant_id = %s::uuid" in conn.statements[0][0]

    def test_list_secret_refs_is_tenant_scoped(self) -> None:
        db, conn = db_with([])
        list_secret_refs(db, tenant_id=TENANT, environment_id=ENV)
        assert "tenant_id = %s::uuid" in conn.statements[0][0]

    def test_list_variants_is_tenant_scoped(self) -> None:
        db, conn = db_with([])
        list_variants(db, tenant_id=TENANT, environment_id=ENV)
        assert "tenant_id = %s::uuid" in conn.statements[0][0]

    def test_list_invocations_is_tenant_scoped(self) -> None:
        db, conn = db_with([])
        list_invocations(db, tenant_id=TENANT, environment_id=ENV)
        assert "tenant_id = %s::uuid" in conn.statements[0][0]

    def test_list_audit_is_tenant_scoped(self) -> None:
        db, conn = db_with([])
        list_audit(db, tenant_id=TENANT, environment_id=ENV)
        assert "tenant_id = %s::uuid" in conn.statements[0][0]

    def test_get_invocation_is_scoped_to_lane_and_tenant(self) -> None:
        db, conn = db_with(None)
        assert (
            get_invocation(
                db, tenant_id=TENANT, environment_id=ENV, invocation_id=INVOCATION
            )
            is None
        )
        assert "environment_id = %s::uuid AND tenant_id = %s::uuid" in conn.statements[0][0]

    def test_revision_history_is_tenant_scoped_but_not_lane_scoped(self) -> None:
        """A deleted function's history must stay readable; that is when a revert is most needed."""
        db, conn = db_with([])
        list_revisions(db, tenant_id=TENANT, function_id=FUNCTION)
        query, _ = conn.statements[0]
        assert "tenant_id = %s::uuid" in query
        assert "environment_id" not in query

    def test_capabilities_can_be_narrowed_to_one_function(self) -> None:
        db, conn = db_with([])
        list_capabilities(
            db, tenant_id=TENANT, environment_id=ENV, function_id=FUNCTION
        )
        query, params = conn.statements[0]
        assert "function_id = %s::uuid" in query
        assert FUNCTION in params


class TestPolicyLifecycle:
    """A lane with no row is a lane with functions disabled, not a lane with no policy."""

    def test_an_existing_policy_is_returned_without_writing(self) -> None:
        db, conn = db_with(policy_row())
        result = ensure_policy(
            db,
            tenant_id=TENANT,
            site_id=SITE,
            environment_id=ENV,
            actor_id=None,
            actor_name="a",
            actor_key="a",
        )
        assert result["default_residency_class"] == "in-region-only"
        assert conn.commits == 0, "a read must not write"

    def test_a_missing_policy_is_created_with_the_shipped_defaults(self) -> None:
        db, conn = db_with(None, policy_row(policy_version=0, functions_enabled=False))
        result = ensure_policy(
            db,
            tenant_id=TENANT,
            site_id=SITE,
            environment_id=ENV,
            actor_id=None,
            actor_name="a",
            actor_key="a",
        )
        assert result["policy_version"] == 0
        insert = conn.statements[1][0]
        assert "INSERT INTO apiome.slate_function_policies" in insert
        assert "'auto', 'in-region-only'" in insert
        assert conn.commits == 1

    def test_a_concurrent_first_read_re_reads_rather_than_raising(self) -> None:
        db, conn = db_with(None, None, policy_row())
        result = ensure_policy(
            db,
            tenant_id=TENANT,
            site_id=SITE,
            environment_id=ENV,
            actor_id=None,
            actor_name="a",
            actor_key="a",
        )
        assert result["policy_version"] == 3
        assert "ON CONFLICT (environment_id) DO NOTHING" in conn.statements[1][0]

    def test_a_policy_that_cannot_be_read_after_insert_raises(self) -> None:
        db, _ = db_with(None, None, None)
        with pytest.raises(SlateFunctionStoreError) as excinfo:
            ensure_policy(
                db,
                tenant_id=TENANT,
                site_id=SITE,
                environment_id=ENV,
                actor_id=None,
                actor_name="a",
                actor_key="a",
            )
        assert excinfo.value.code == "policy_not_found"

    def test_nothing_this_module_writes_can_attach_a_runtime(self) -> None:
        """edge_attached has one honest value, and no statement here sets any other."""
        db, conn = db_with(None, policy_row())
        ensure_policy(
            db,
            tenant_id=TENANT,
            site_id=SITE,
            environment_id=ENV,
            actor_id=None,
            actor_name="a",
            actor_key="a",
        )
        assert "edge_attached" not in conn.statements[1][0]

    def test_a_policy_write_never_names_edge_attached_either(self) -> None:
        db, conn = db_with({"policy_version": 4}, policy_row(policy_version=4))
        set_policy(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            functions_enabled=True,
            default_region="eu-west",
            default_residency_class="region-pinned",
            default_cpu_ms_limit=50,
            default_memory_mb_limit=128,
            default_wall_ms_limit=5000,
            residency_waiver_reason=None,
            expected_policy_version=3,
            actor_id=None,
            actor_name="a",
            actor_key="a",
        )
        update = conn.statements[1][0]
        assert "edge_attached" not in update
        assert "region-pinned" in conn.statements[1][1]


class TestOptimisticConcurrency:
    """The compare-and-set that makes two operators editing one lane during a rollout safe."""

    def test_a_policy_write_carries_the_expected_version_in_the_where_clause(self) -> None:
        db, conn = db_with({"policy_version": 4}, policy_row(policy_version=4))
        set_policy(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            functions_enabled=True,
            default_region="auto",
            default_residency_class="in-region-only",
            default_cpu_ms_limit=50,
            default_memory_mb_limit=128,
            default_wall_ms_limit=5000,
            residency_waiver_reason=None,
            expected_policy_version=3,
            actor_id=None,
            actor_name="a",
            actor_key="a",
        )
        bump = conn.statements[0]
        assert "policy_version = policy_version + 1" in bump[0]
        assert "WHERE environment_id = %s::uuid AND policy_version = %s" in bump[0]
        assert 3 in bump[1]

    def test_a_stale_expected_version_raises_rather_than_overwriting(self) -> None:
        db, conn = db_with(None, {"policy_version": 9})
        with pytest.raises(SlateFunctionPolicyConflictError) as excinfo:
            set_policy(
                db,
                tenant_id=TENANT,
                environment_id=ENV,
                functions_enabled=False,
                default_region="auto",
                default_residency_class="unrestricted",
                default_cpu_ms_limit=50,
                default_memory_mb_limit=128,
                default_wall_ms_limit=5000,
                residency_waiver_reason="latency",
                expected_policy_version=3,
                actor_id=None,
                actor_name="a",
                actor_key="a",
            )
        assert excinfo.value.expected_policy_version == 3
        assert excinfo.value.actual_policy_version == 9
        assert conn.rollbacks == 1, "a refused edit must leave nothing behind"
        assert conn.commits == 0

    def test_a_conflict_on_a_lane_with_no_policy_reports_no_actual_version(self) -> None:
        db, _ = db_with(None, None)
        with pytest.raises(SlateFunctionPolicyConflictError) as excinfo:
            delete_variant(
                db,
                tenant_id=TENANT,
                environment_id=ENV,
                variant_id=VARIANT,
                expected_policy_version=1,
            )
        assert excinfo.value.actual_policy_version is None

    def test_a_capability_grant_bumps_the_policy_version_first(self) -> None:
        db, conn = db_with({"policy_version": 4}, {"id": "grant-1"})
        grant_capability(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            function_id=FUNCTION,
            capability="geo-read",
            reason="locale banner",
            expires_at=None,
            expected_policy_version=3,
            actor_id=None,
            actor_name="a",
            actor_key="user-1",
        )
        assert "policy_version = policy_version + 1" in conn.statements[0][0]
        assert "INSERT INTO apiome.slate_function_capabilities" in conn.statements[1][0]

    def test_an_egress_write_bumps_the_policy_version_first(self) -> None:
        db, conn = db_with({"policy_version": 4}, {"id": EGRESS})
        set_egress_rule(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            function_id=FUNCTION,
            destination_kind="exact-host",
            destination="api.example.com",
            scheme="https",
            port=None,
            methods=["GET"],
            reason="pricing lookup",
            expires_at=None,
            expected_policy_version=3,
            actor_id=None,
            actor_name="a",
            actor_key="user-1",
        )
        assert "policy_version = policy_version + 1" in conn.statements[0][0]
        assert "INSERT INTO apiome.slate_function_egress_rules" in conn.statements[1][0]

    def test_a_variant_write_bumps_the_policy_version_first(self) -> None:
        db, conn = db_with({"policy_version": 4}, {"id": VARIANT})
        upsert_variant(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            variant_id=None,
            function_id=FUNCTION,
            values=variant_values(),
            expected_policy_version=3,
            actor_id=None,
            actor_name="a",
        )
        assert "policy_version = policy_version + 1" in conn.statements[0][0]
        assert "INSERT INTO apiome.slate_personalization_variants" in conn.statements[1][0]

    def test_a_secret_reference_write_bumps_the_policy_version_first(self) -> None:
        db, conn = db_with({"policy_version": 4}, {"id": SECRET_REF})
        set_secret_ref(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            function_id=FUNCTION,
            secret_name="pricing-api-key",
            alias="PRICING_KEY",
            scope="function",
            expected_policy_version=3,
            actor_id=None,
            actor_name="a",
        )
        assert "policy_version = policy_version + 1" in conn.statements[0][0]
        assert "INSERT INTO apiome.slate_function_secret_refs" in conn.statements[1][0]


class TestFunctionWritesRecordRevisions:
    """A change with no stored body is a change that cannot be reverted."""

    def test_creating_a_function_records_it_as_revision_one(self) -> None:
        # bump, INSERT function (fetched), revision INSERT (unfetched, consumes the next slot).
        db, conn = db_with({"policy_version": 1}, function_row(revision=1), None)
        written = upsert_function(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            function_id=None,
            values=function_values(),
            expected_policy_version=0,
            actor_id="user-1",
            actor_name="ken@example.com",
        )
        assert written["id"] == FUNCTION
        emitted = [s[0] for s in conn.statements]
        assert any("INSERT INTO apiome.slate_functions" in s for s in emitted)
        revision = next(
            s for s in conn.statements if "slate_function_revisions" in s[0]
        )
        assert "created" in revision[1]
        assert conn.commits == 1

    def test_the_active_version_placeholder_is_cast_to_uuid(self) -> None:
        """A bare UUID column with no foreign key still needs a text parameter told what it is."""
        db, conn = db_with({"policy_version": 1}, function_row(revision=1), None)
        upsert_function(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            function_id=None,
            values=function_values(),
            expected_policy_version=0,
            actor_id=None,
            actor_name="a",
        )
        insert = next(s for s in conn.statements if "INSERT INTO apiome.slate_functions" in s[0])
        assert "active_version_id" in insert[0]
        assert "%s::uuid" in insert[0]

    def test_replacing_a_function_records_the_prior_body_before_mutating(self) -> None:
        prior = function_row(revision=2, rollout_percent=10)
        # bump, SELECT prior, revision INSERT (unfetched — its slot feeds the UPDATE's fetchone).
        db, conn = db_with({"policy_version": 5}, prior, function_row(revision=3), None)
        upsert_function(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            function_id=FUNCTION,
            values=function_values(rollout_percent=50),
            expected_policy_version=4,
            actor_id=None,
            actor_name="a",
        )
        order = [s[0] for s in conn.statements]
        revision_index = next(
            i for i, s in enumerate(order) if "slate_function_revisions" in s
        )
        update_index = next(
            i for i, s in enumerate(order) if "UPDATE apiome.slate_functions" in s
        )
        assert revision_index < update_index, "the prior body must be kept before it is replaced"
        revision_params = conn.statements[revision_index][1]
        assert 2 in revision_params, "the revision recorded is the one being left"
        assert "updated" in revision_params

    def test_disabling_a_function_is_recorded_as_a_disable_not_an_update(self) -> None:
        db, conn = db_with(
            {"policy_version": 5}, function_row(), function_row(enabled=False), None
        )
        upsert_function(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            function_id=FUNCTION,
            values=function_values(enabled=False),
            expected_policy_version=4,
            actor_id=None,
            actor_name="a",
        )
        revision = next(s for s in conn.statements if "slate_function_revisions" in s[0])
        assert "disabled" in revision[1]

    def test_replacing_a_function_that_is_not_on_the_lane_raises_and_rolls_back(self) -> None:
        db, conn = db_with({"policy_version": 5}, None)
        with pytest.raises(SlateFunctionStoreError) as excinfo:
            upsert_function(
                db,
                tenant_id=TENANT,
                environment_id=ENV,
                function_id=FUNCTION,
                values=function_values(),
                expected_policy_version=4,
                actor_id=None,
                actor_name="a",
            )
        assert excinfo.value.code == "function_not_found"
        assert conn.rollbacks == 1
        assert conn.commits == 0
        assert not any("slate_function_revisions" in s[0] for s in conn.statements)

    def test_a_rollout_change_records_the_stage_it_left(self) -> None:
        db, conn = db_with(
            {"policy_version": 5},
            function_row(rollout_percent=10),
            function_row(rollout_percent=100),
            None,
        )
        set_rollout(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            function_id=FUNCTION,
            rollout_mode="enforce",
            rollout_percent=100,
            expected_policy_version=4,
            actor_id=None,
            actor_name="a",
        )
        revision = next(s for s in conn.statements if "slate_function_revisions" in s[0])
        assert "rollout-changed" in revision[1]

    def test_deleting_a_function_keeps_its_body_first(self) -> None:
        db, conn = db_with({"policy_version": 5}, function_row(), None)
        assert delete_function(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            function_id=FUNCTION,
            expected_policy_version=4,
            actor_id=None,
            actor_name="a",
        )
        order = [s[0] for s in conn.statements]
        revision_index = next(
            i for i, s in enumerate(order) if "slate_function_revisions" in s
        )
        delete_index = next(
            i for i, s in enumerate(order) if "DELETE FROM apiome.slate_functions" in s
        )
        assert revision_index < delete_index
        assert "deleted" in conn.statements[revision_index][1]
        assert conn.commits == 1

    def test_deleting_a_function_that_does_not_exist_raises_and_rolls_back(self) -> None:
        db, conn = db_with({"policy_version": 5}, None)
        with pytest.raises(SlateFunctionStoreError) as excinfo:
            delete_function(
                db,
                tenant_id=TENANT,
                environment_id=ENV,
                function_id=FUNCTION,
                expected_policy_version=4,
                actor_id=None,
                actor_name="a",
            )
        assert excinfo.value.code == "function_not_found"
        assert conn.rollbacks == 1

    def test_adding_a_version_records_a_version_added_revision_first(self) -> None:
        """Promoting new code is a change to the function even when nothing else moved."""
        db, conn = db_with(
            {"policy_version": 5}, function_row(revision=2), {"id": VERSION}, None
        )
        add_version(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            function_id=FUNCTION,
            source_digest=SOURCE_DIGEST,
            body={"entrypoint": "index.js"},
            runtime="js-isolate",
            source_bytes=1024,
            source_origin="upload",
            source_ref=None,
            activate=True,
            expected_policy_version=4,
            actor_id=None,
            actor_name="a",
        )
        order = [s[0] for s in conn.statements]
        revision_index = next(
            i for i, s in enumerate(order) if "slate_function_revisions" in s
        )
        version_index = next(
            i for i, s in enumerate(order) if "INSERT INTO apiome.slate_function_versions" in s
        )
        assert revision_index < version_index
        assert "version-added" in conn.statements[revision_index][1]
        assert any("active_version_id = %s::uuid" in s for s in order), "activate moves the pointer"

    def test_a_version_that_is_not_activated_leaves_the_pointer_alone(self) -> None:
        db, conn = db_with(
            {"policy_version": 5}, function_row(revision=2), {"id": VERSION}, None
        )
        add_version(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            function_id=FUNCTION,
            source_digest=SOURCE_DIGEST,
            body={},
            runtime="wasm",
            source_bytes=None,
            source_origin="build",
            source_ref="abc123",
            activate=False,
            expected_policy_version=4,
            actor_id=None,
            actor_name="a",
        )
        assert not any("active_version_id = %s::uuid" in s[0] for s in conn.statements)

    def test_reverting_applies_the_stored_body(self) -> None:
        stored = {
            "id": "rev-1",
            "revision": 1,
            "body": function_row(rollout_percent=0),
            "body_digest": DIGEST,
        }
        db, conn = db_with(
            {"policy_version": 6},
            stored,
            function_row(revision=4),
            function_row(rollout_percent=0),
            None,
        )
        revert_function(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            function_id=FUNCTION,
            revision=1,
            expected_policy_version=5,
            actor_id=None,
            actor_name="a",
        )
        revision = next(
            s
            for s in conn.statements
            if "INSERT INTO apiome.slate_function_revisions" in s[0]
        )
        assert "reverted" in revision[1]
        update = next(s for s in conn.statements if "UPDATE apiome.slate_functions" in s[0])
        assert 0 in update[1], "the stored rollout_percent is what gets applied"

    def test_reverting_to_a_revision_that_does_not_exist_raises(self) -> None:
        db, conn = db_with({"policy_version": 6}, None)
        with pytest.raises(SlateFunctionStoreError) as excinfo:
            revert_function(
                db,
                tenant_id=TENANT,
                environment_id=ENV,
                function_id=FUNCTION,
                revision=9,
                expected_policy_version=5,
                actor_id=None,
                actor_name="a",
            )
        assert excinfo.value.code == "revision_not_found"
        assert conn.rollbacks == 1

    def test_versions_are_newest_first(self) -> None:
        db, conn = db_with([])
        list_versions(db, tenant_id=TENANT, function_id=FUNCTION)
        assert "ORDER BY revision DESC" in conn.statements[0][0]


class TestFunctionHistoryReconstruction:
    """``simulated_at`` and ``previous_rollout_percent`` are facts about history, not about a body.

    The pure module reads both and is query-free by design, so they are reconstructed here. A
    client able to assert ``simulated_at`` could promote code straight into the request path,
    which is the lockout the ``enforce-without-simulation`` refusal exists to prevent.
    """

    def test_a_simulate_revision_in_history_is_found(self) -> None:
        moment = datetime(2026, 7, 1, tzinfo=timezone.utc)
        db, conn = db_with({"at": moment})
        assert last_simulated_at(db, tenant_id=TENANT, function_id=FUNCTION) == moment
        query, _ = conn.statements[0]
        assert "body ->> 'rollout_mode' = 'simulate'" in query

    def test_a_function_that_never_simulated_reports_none(self) -> None:
        db, _ = db_with(None)
        assert last_simulated_at(db, tenant_id=TENANT, function_id=FUNCTION) is None

    def test_the_context_reports_both_facts_for_an_existing_function(self) -> None:
        moment = datetime(2026, 7, 1, tzinfo=timezone.utc)
        db, _ = db_with({"at": moment}, function_row(rollout_percent=25))
        context = function_evaluation_context(
            db, tenant_id=TENANT, environment_id=ENV, function_id=FUNCTION
        )
        assert context["simulated_at"] == moment
        assert context["previous_rollout_percent"] == 25

    def test_a_create_has_no_history_so_both_facts_are_absent(self) -> None:
        """Which is why a create that asks to enforce immediately is refused."""
        db, conn = db_with()
        context = function_evaluation_context(
            db, tenant_id=TENANT, environment_id=ENV, function_id=None
        )
        assert context == {"simulated_at": None, "previous_rollout_percent": None}
        assert conn.statements == [], "a function that does not exist needs no query"

    def test_a_deleted_function_falls_back_to_its_newest_revision(self) -> None:
        db, _ = db_with(
            {"at": datetime(2026, 7, 1, tzinfo=timezone.utc)},
            None,
            [{"body": {"rollout_percent": 40}}],
        )
        context = function_evaluation_context(
            db, tenant_id=TENANT, environment_id=ENV, function_id=FUNCTION
        )
        assert context["previous_rollout_percent"] == 40


class TestDenyByDefault:
    """The row is the grant. There is no boolean anywhere here to get the wrong way round."""

    def test_a_capability_grant_writes_no_granted_flag(self) -> None:
        db, conn = db_with({"policy_version": 4}, {"id": "grant-1"})
        grant_capability(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            function_id=FUNCTION,
            capability="secret-read",
            reason="vendor integration",
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
            expected_policy_version=3,
            actor_id=None,
            actor_name="a",
            actor_key="user-1",
        )
        insert = conn.statements[1][0]
        assert "granted " not in insert and "granted," not in insert
        assert "granted_by_actor_key" in insert, "who widened the privilege is recorded"

    def test_revoking_a_capability_is_a_delete_not_an_update(self) -> None:
        db, conn = db_with({"policy_version": 4}, {"id": "grant-1"})
        assert revoke_capability(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            function_id=FUNCTION,
            capability="secret-read",
            expected_policy_version=3,
        )
        revoke = conn.statements[1][0]
        assert revoke.startswith("DELETE FROM apiome.slate_function_capabilities")
        assert "UPDATE" not in revoke

    def test_revoking_a_capability_that_was_never_granted_raises(self) -> None:
        db, conn = db_with({"policy_version": 4}, None)
        with pytest.raises(SlateFunctionStoreError) as excinfo:
            revoke_capability(
                db,
                tenant_id=TENANT,
                environment_id=ENV,
                function_id=FUNCTION,
                capability="kv-write",
                expected_policy_version=3,
            )
        assert excinfo.value.code == "capability_not_found"
        assert conn.rollbacks == 1

    def test_withdrawing_an_egress_allowance_is_a_delete(self) -> None:
        db, conn = db_with({"policy_version": 4}, {"id": EGRESS})
        assert delete_egress_rule(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            function_id=FUNCTION,
            rule_id=EGRESS,
            expected_policy_version=3,
        )
        assert conn.statements[1][0].startswith(
            "DELETE FROM apiome.slate_function_egress_rules"
        )

    def test_an_egress_rule_has_no_wildcard_kind_to_write(self) -> None:
        """The narrowness of the destination is the whole allowlist; there is no 'any'."""
        db, conn = db_with({"policy_version": 4}, {"id": EGRESS})
        set_egress_rule(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            function_id=FUNCTION,
            destination_kind="host-suffix",
            destination="example.com",
            scheme="https",
            port=443,
            methods=[],
            reason="vendor API",
            expires_at=None,
            expected_policy_version=3,
            actor_id=None,
            actor_name="a",
            actor_key="user-1",
        )
        params = conn.statements[1][1]
        assert "host-suffix" in params
        assert "any" not in params and "*" not in params


class TestSecretsAreReferencesOnly:
    """The strongest claim in this module is one it makes by having no column to break."""

    def test_a_secret_reference_write_carries_a_name_an_alias_and_a_scope(self) -> None:
        db, conn = db_with({"policy_version": 4}, {"id": SECRET_REF})
        set_secret_ref(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            function_id=FUNCTION,
            secret_name="pricing-api-key",
            alias="PRICING_KEY",
            scope="function",
            expected_policy_version=3,
            actor_id=None,
            actor_name="a",
        )
        query, params = conn.statements[1]
        assert "secret_name" in query and "alias" in query and "scope" in query
        assert "value" not in query, "there is no column able to hold secret material"
        assert "pricing-api-key" in params and "PRICING_KEY" in params

    def test_withdrawing_a_reference_is_scoped_to_its_function(self) -> None:
        db, conn = db_with({"policy_version": 4}, {"id": SECRET_REF})
        assert delete_secret_ref(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            function_id=FUNCTION,
            ref_id=SECRET_REF,
            expected_policy_version=3,
        )
        query, _ = conn.statements[1]
        assert "function_id = %s::uuid" in query
        assert "tenant_id = %s::uuid" in query

    def test_withdrawing_a_reference_that_is_not_there_raises(self) -> None:
        db, conn = db_with({"policy_version": 4}, None)
        with pytest.raises(SlateFunctionStoreError) as excinfo:
            delete_secret_ref(
                db,
                tenant_id=TENANT,
                environment_id=ENV,
                function_id=FUNCTION,
                ref_id=SECRET_REF,
                expected_policy_version=3,
            )
        assert excinfo.value.code == "secret_ref_not_found"


class TestVariants:
    """Everything §29.5 requires shown together is written together, in one statement."""

    def test_a_variant_write_sets_every_decisive_field_at_once(self) -> None:
        db, conn = db_with({"policy_version": 4}, {"id": VARIANT})
        upsert_variant(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            variant_id=None,
            function_id=FUNCTION,
            values=variant_values(),
            expected_policy_version=3,
            actor_id=None,
            actor_name="a",
        )
        query, params = conn.statements[1]
        for column in (
            "audience_kind",
            "audience_matcher",
            "fallback_variant",
            "cache_key_effect",
            "analytics_dimension",
            "privacy_class",
            "consent_basis",
        ):
            assert column in query, f"{column} must not be written separately"
        assert "default" in params

    def test_replacing_a_variant_that_is_not_on_the_lane_raises(self) -> None:
        db, conn = db_with({"policy_version": 4}, None)
        with pytest.raises(SlateFunctionStoreError) as excinfo:
            upsert_variant(
                db,
                tenant_id=TENANT,
                environment_id=ENV,
                variant_id=VARIANT,
                function_id=FUNCTION,
                values=variant_values(),
                expected_policy_version=3,
                actor_id=None,
                actor_name="a",
            )
        assert excinfo.value.code == "variant_not_found"
        assert conn.rollbacks == 1

    def test_removing_a_variant_that_is_not_on_the_lane_raises(self) -> None:
        db, _ = db_with({"policy_version": 4}, None)
        with pytest.raises(SlateFunctionStoreError) as excinfo:
            delete_variant(
                db,
                tenant_id=TENANT,
                environment_id=ENV,
                variant_id=VARIANT,
                expected_policy_version=3,
            )
        assert excinfo.value.code == "variant_not_found"


class TestApprovals:
    """Dual control is looked up two ways, because the two failures need different actions."""

    def test_approvals_can_be_narrowed_to_one_subject(self) -> None:
        db, conn = db_with([])
        list_approvals(db, tenant_id=TENANT, environment_id=ENV, subject_id=FUNCTION)
        query, params = conn.statements[0]
        assert "subject_id = %s" in query
        assert FUNCTION in params

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
            subject_kind="function",
            subject_id=FUNCTION,
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
        assert "INSERT INTO apiome.slate_function_approvals" in query
        assert "user-1" in params and "user-2" in params
        assert DIGEST in params


class TestInvocationHonesty:
    """Nothing was observed and nothing ran, and there is no argument that says otherwise."""

    def test_an_invocation_is_written_as_a_simulation_that_executed_nothing(self) -> None:
        db, conn = db_with({"id": INVOCATION})
        record_invocation(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            function_ref=FUNCTION,
            function_label="Add locale header",
            route="/guide/intro",
            method="GET",
            release_id=None,
            region=None,
            variant_ref=None,
            outcome="would-run",
            denial_reason=None,
            evidence={"path": "/guide/intro"},
        )
        query, params = conn.statements[0]
        assert "'policy-simulation'" in query
        assert "FALSE, FALSE" in query, "executed and edge_attached are literals, not parameters"
        assert "edge-observed" not in query
        assert "would-run" in params

    def test_no_argument_can_make_a_record_claim_an_execution(self) -> None:
        """The honesty enforcement point: the dishonest values are not reachable from any call."""
        with pytest.raises(TypeError):
            record_invocation(  # type: ignore[call-arg]
                db_with({"id": INVOCATION})[0],
                tenant_id=TENANT,
                environment_id=ENV,
                function_ref=FUNCTION,
                function_label="f",
                route="/",
                method="GET",
                release_id=None,
                region=None,
                variant_ref=None,
                outcome="ran",
                denial_reason=None,
                evidence={},
                executed=True,
            )
        with pytest.raises(TypeError):
            record_invocation(  # type: ignore[call-arg]
                db_with({"id": INVOCATION})[0],
                tenant_id=TENANT,
                environment_id=ENV,
                function_ref=FUNCTION,
                function_label="f",
                route="/",
                method="GET",
                release_id=None,
                region=None,
                variant_ref=None,
                outcome="ran",
                denial_reason=None,
                evidence={},
                source="edge-observed",
            )

    def test_even_an_outcome_of_ran_is_written_against_executed_false(self) -> None:
        """The outcome column is a parameter; the execution claim is not, and V189 CHECKs both."""
        db, conn = db_with({"id": INVOCATION})
        record_invocation(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            function_ref=FUNCTION,
            function_label="f",
            route="/",
            method="GET",
            release_id=None,
            region=None,
            variant_ref=None,
            outcome="ran",
            denial_reason=None,
            evidence={},
        )
        query, params = conn.statements[0]
        assert "ran" in params
        assert "FALSE, FALSE" in query
        assert "TRUE" not in query

    def test_no_resource_measurement_is_invented(self) -> None:
        """A simulation consumed no CPU; a zero would be a measurement, and NULL is the truth."""
        db, conn = db_with({"id": INVOCATION})
        record_invocation(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            function_ref=FUNCTION,
            function_label="f",
            route="/",
            method="GET",
            release_id=None,
            region=None,
            variant_ref=None,
            outcome="would-run",
            denial_reason=None,
            evidence={},
        )
        query, _ = conn.statements[0]
        assert "cpu_ms" not in query
        assert "wall_ms" not in query
        assert "memory_peak_mb" not in query

    def test_retention_defaults_to_thirty_days_after_the_invocation(self) -> None:
        db, conn = db_with({"id": INVOCATION})
        record_invocation(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            function_ref=FUNCTION,
            function_label="f",
            route="/",
            method="GET",
            release_id=None,
            region=None,
            variant_ref=None,
            outcome="skipped",
            denial_reason=None,
            evidence={},
        )
        params = conn.statements[0][1]
        moments = [p for p in params if isinstance(p, datetime)]
        assert len(moments) == 2
        at, retain_until = moments
        assert retain_until - at == timedelta(days=30)

    def test_the_store_redacts_rather_than_trusting_the_caller(self) -> None:
        db, conn = db_with({"id": INVOCATION})
        record_invocation(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            function_ref=FUNCTION,
            function_label="f",
            route="/guide",
            method="GET",
            release_id=None,
            region=None,
            variant_ref=None,
            outcome="would-run",
            denial_reason=None,
            evidence={"cookie": "session=abc", "path": "/guide"},
        )
        encoded = next(
            p for p in conn.statements[0][1] if isinstance(p, str) and p.startswith("{")
        )
        assert "session=abc" not in encoded
        assert "cookie" not in encoded
        assert "/guide" in encoded

    def test_invocations_can_be_filtered_on_every_designer_dimension(self) -> None:
        db, conn = db_with([])
        list_invocations(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            function_ref=FUNCTION,
            outcome="capability-denied",
            route="/guide",
            release_id="12121212-1212-1212-1212-121212121212",
            region="eu-west",
            variant_ref=VARIANT,
            source="policy-simulation",
        )
        query, params = conn.statements[0]
        for column in (
            "function_ref",
            "outcome",
            "route",
            "release_id",
            "region",
            "variant_ref",
            "source",
        ):
            assert f"{column} = %s" in query
        assert "release_id = %s::uuid" in query
        assert "eu-west" in params


class TestRedaction:
    """V189's CHECK is the backstop. This is the mechanism, and it has to be stronger."""

    def test_a_cookie_never_survives(self) -> None:
        assert redact_evidence({"cookie": "session=abc"}) == {}

    def test_an_authorization_header_never_survives(self) -> None:
        assert redact_evidence({"authorization": "Bearer abc", "Cookie": "x=1"}) == {}

    def test_an_allowed_key_is_kept(self) -> None:
        assert redact_evidence({"path": "/docs", "method": "GET"}) == {
            "path": "/docs",
            "method": "GET",
        }

    def test_a_nested_object_under_an_allowed_key_is_dropped_not_stringified(self) -> None:
        """The DB CHECK constrains only top-level keys, so this is the smuggling route.

        Rendering the object as text would satisfy the CHECK perfectly and carry the payload
        into the database under a permitted name, which is precisely what must not happen.
        """
        redacted = redact_evidence({"userAgent": {"cookie": "session=abc"}})
        assert redacted == {}
        assert "session=abc" not in str(redacted)

    def test_a_nested_object_under_the_variant_key_is_also_dropped(self) -> None:
        redacted = redact_evidence({"variant": {"authorization": "Bearer abc"}, "path": "/x"})
        assert redacted == {"path": "/x"}
        assert "Bearer" not in str(redacted)

    def test_a_list_under_an_allowed_key_is_dropped(self) -> None:
        assert redact_evidence({"query": ["a", "b"]}) == {}

    def test_a_deeply_nested_structure_is_dropped_whole(self) -> None:
        payload = {"denialReason": {"inner": {"cookie": "session=abc"}}}
        assert redact_evidence(payload) == {}

    def test_every_surviving_value_is_a_string(self) -> None:
        redacted = redact_evidence({"statusCode": 403, "outcome": "would-run"})
        assert redacted == {"statusCode": "403", "outcome": "would-run"}
        assert all(isinstance(v, str) for v in redacted.values())

    def test_free_text_is_bounded(self) -> None:
        redacted = redact_evidence({"userAgent": "u" * 5000, "denialReason": "d" * 5000})
        assert len(redacted["userAgent"]) == 256
        assert len(redacted["denialReason"]) == 256

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
        redacted = redact_evidence({"denialReason": "198.51.100.7"})
        assert redacted["denialReason"] == "198.51.100.0/24"

    def test_a_value_that_is_not_an_address_is_not_stored_as_one(self) -> None:
        assert redact_evidence({"clientIpPrefix": "not-an-address"}) == {}

    def test_no_key_outside_the_allowlist_can_appear(self) -> None:
        redacted = redact_evidence(
            {key: "x" for key in EVIDENCE_ALLOWED_KEYS} | {"secret": "x", "set-cookie": "y"}
        )
        assert set(redacted) <= set(EVIDENCE_ALLOWED_KEYS)
        assert "secret" not in redacted

    def test_the_allowlist_matches_the_migrations_check_array(self) -> None:
        assert EVIDENCE_ALLOWED_KEYS == (
            "method",
            "path",
            "query",
            "userAgent",
            "country",
            "region",
            "clientIpPrefix",
            "variant",
            "outcome",
            "statusCode",
            "denialReason",
            "cpuMs",
            "wallMs",
        )


class TestAudit:
    """Who read the record of who let a function read secrets is part of that record."""

    def test_an_audit_entry_names_its_subject(self) -> None:
        db, conn = db_with(None)
        append_audit(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            actor_id=None,
            actor_name="ken@example.com",
            actor_kind="user",
            subject_kind="capability",
            subject_id=FUNCTION,
            summary="Capability secret-read granted",
            detail="vendor integration",
        )
        query, params = conn.statements[0]
        assert "INSERT INTO apiome.slate_function_audit" in query
        assert "Capability secret-read granted" in params
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
            summary="Function audit exported",
        )
        assert "export" in conn.statements[0][1]

    def test_the_audit_trail_is_newest_first(self) -> None:
        db, conn = db_with([])
        list_audit(db, tenant_id=TENANT, environment_id=ENV)
        assert "ORDER BY at DESC" in conn.statements[0][0]
