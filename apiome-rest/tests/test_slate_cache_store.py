"""Cache control-plane persistence — UXE-3.1 (private-suite#2473).

Exercises :mod:`app.slate_cache_store` against a scripted fake connection, following the
``test_slate_activation.py`` precedent. No live Postgres: this asserts the SQL these functions
emit and the transaction discipline around it.

Three properties get the most attention, because each fails silently:

* **Every read is tenant-scoped.** A query that forgot ``tenant_id`` would work perfectly in
  every single-tenant test and leak across tenants in production.
* **The policy version is a compare-and-set, not a read-then-write.** The conditional UPDATE
  must carry the expected version in its WHERE clause, and matching zero rows must raise rather
  than fall through.
* **A failed write rolls back.** A rule written without its tags, or a tag set replaced without
  its rule, would be a silently wrong purge scope later.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import pytest

from app.slate_cache_store import (
    SlateCachePolicyConflictError,
    SlateCacheStoreError,
    append_audit,
    delete_rule,
    ensure_policy,
    get_policy,
    list_audit,
    list_purges,
    list_rules,
    record_purge,
    record_trace,
    routes_for_host,
    routes_for_release,
    rules_for_tag,
    set_preset,
    upsert_rule,
)

TENANT = "11111111-1111-1111-1111-111111111111"
SITE = "22222222-2222-2222-2222-222222222222"
ENV = "33333333-3333-3333-3333-333333333333"
RULE = "44444444-4444-4444-4444-444444444444"


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
    """A cache policy row."""
    base = {
        "id": "policy-1",
        "tenant_id": TENANT,
        "site_id": SITE,
        "environment_id": ENV,
        "preset": "standard",
        "preset_expires_at": None,
        "preset_overrides": {},
        "policy_version": 3,
        "edge_attached": False,
        "edge_provider": None,
    }
    base.update(overrides)
    return base


def rule_values(**overrides) -> Dict[str, Any]:
    """Column values for a rule write."""
    base = {
        "ordinal": 0,
        "enabled": True,
        "label": "Docs",
        "matcher_kind": "prefix",
        "matcher_value": "/docs",
        "matcher_methods": ["GET"],
        "matcher_hosts": [],
        "eligibility": "cacheable",
        "browser_ttl_seconds": 0,
        "edge_ttl_seconds": 60,
        "stale_while_revalidate_seconds": 0,
        "stale_if_error_seconds": 0,
        "cache_key_base": "host-url",
        "vary_query_mode": "none",
        "vary_query_keys": [],
        "vary_headers": [],
        "vary_cookies": [],
        "expires_at": None,
        "acknowledged_warnings": [],
        "bypass_conditions": [],
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

    def test_list_rules_is_tenant_scoped(self) -> None:
        db, conn = db_with([])
        list_rules(db, tenant_id=TENANT, environment_id=ENV)
        query, params = conn.statements[0]
        assert "r.tenant_id = %s::uuid" in query
        assert TENANT in params

    def test_list_purges_is_tenant_scoped(self) -> None:
        db, conn = db_with([])
        list_purges(db, tenant_id=TENANT, environment_id=ENV)
        assert "tenant_id = %s::uuid" in conn.statements[0][0]

    def test_list_audit_is_tenant_scoped(self) -> None:
        db, conn = db_with([])
        list_audit(db, tenant_id=TENANT, environment_id=ENV)
        assert "tenant_id = %s::uuid" in conn.statements[0][0]

    def test_rules_for_tag_is_tenant_scoped(self) -> None:
        db, conn = db_with([])
        rules_for_tag(db, tenant_id=TENANT, environment_id=ENV, tag="nav")
        assert "r.tenant_id = %s::uuid" in conn.statements[0][0]

    def test_routes_for_host_confirms_the_host_is_on_this_lane(self) -> None:
        db, conn = db_with(None)
        assert routes_for_host(
            db, tenant_id=TENANT, environment_id=ENV, host="other.example.com", release_id="rel-1"
        ) == []
        query, params = conn.statements[0]
        assert "slate_domains" in query
        assert TENANT in params

    def test_a_host_is_matched_case_insensitively(self) -> None:
        db, conn = db_with(None)
        routes_for_host(
            db, tenant_id=TENANT, environment_id=ENV, host="Docs.Example.COM", release_id=None
        )
        assert "docs.example.com" in conn.statements[0][1]


class TestPolicyLifecycle:
    """A lane with no row is a lane serving the safe default, not a lane with no policy."""

    def test_an_existing_policy_is_returned_without_writing(self) -> None:
        db, conn = db_with(policy_row())
        result = ensure_policy(
            db, tenant_id=TENANT, site_id=SITE, environment_id=ENV, actor_id=None, actor_name="a"
        )
        assert result["preset"] == "standard"
        assert conn.commits == 0, "a read must not write"

    def test_a_missing_policy_is_created_as_standard(self) -> None:
        db, conn = db_with(None, policy_row(policy_version=0))
        result = ensure_policy(
            db, tenant_id=TENANT, site_id=SITE, environment_id=ENV, actor_id=None, actor_name="a"
        )
        assert result["policy_version"] == 0
        insert = conn.statements[1][0]
        assert "INSERT INTO apiome.slate_cache_policies" in insert
        assert "'standard'" in insert
        assert conn.commits == 1

    def test_a_concurrent_first_read_re_reads_rather_than_raising(self) -> None:
        """Both callers wanted the same default; both should get it."""
        db, conn = db_with(None, None, policy_row())
        result = ensure_policy(
            db, tenant_id=TENANT, site_id=SITE, environment_id=ENV, actor_id=None, actor_name="a"
        )
        assert result["preset"] == "standard"
        assert "ON CONFLICT (environment_id) DO NOTHING" in conn.statements[1][0]

    def test_a_policy_that_cannot_be_read_after_insert_raises(self) -> None:
        db, _ = db_with(None, None, None)
        with pytest.raises(SlateCacheStoreError) as excinfo:
            ensure_policy(
                db, tenant_id=TENANT, site_id=SITE, environment_id=ENV, actor_id=None, actor_name="a"
            )
        assert excinfo.value.code == "policy_not_found"


class TestOptimisticConcurrency:
    """The compare-and-set that makes two operators editing one lane safe."""

    def test_set_preset_carries_the_expected_version_in_the_where_clause(self) -> None:
        db, conn = db_with({"policy_version": 4}, policy_row(preset="aggressive"))
        set_preset(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            preset="aggressive",
            preset_expires_at=None,
            overrides={},
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
        with pytest.raises(SlateCachePolicyConflictError) as excinfo:
            set_preset(
                db,
                tenant_id=TENANT,
                environment_id=ENV,
                preset="bypass",
                preset_expires_at=None,
                overrides={},
                expected_policy_version=3,
                actor_id=None,
                actor_name="a",
            )
        assert excinfo.value.expected_policy_version == 3
        assert excinfo.value.actual_policy_version == 9
        assert conn.rollbacks == 1, "a refused edit must leave nothing behind"
        assert conn.commits == 0

    def test_a_conflict_reports_the_actual_version_so_the_ui_can_re_read(self) -> None:
        db, _ = db_with(None, None)
        with pytest.raises(SlateCachePolicyConflictError) as excinfo:
            delete_rule(
                db,
                tenant_id=TENANT,
                environment_id=ENV,
                rule_id=RULE,
                expected_policy_version=1,
            )
        assert excinfo.value.actual_policy_version is None

    def test_every_rule_write_bumps_the_policy_version_first(self) -> None:
        """The guard has to run before the write it guards, inside one transaction."""
        db, conn = db_with({"policy_version": 4}, {"id": RULE}, None)
        upsert_rule(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            rule_id=None,
            values=rule_values(),
            tags=[],
            expected_policy_version=3,
            actor_id=None,
            actor_name="a",
        )
        assert "policy_version = policy_version + 1" in conn.statements[0][0]
        assert "INSERT INTO apiome.slate_cache_rules" in conn.statements[1][0]


class TestRuleWrites:
    """Rules and their tags are one unit; a partial write is a wrong purge scope later."""

    def test_creating_a_rule_inserts_it_with_its_actor(self) -> None:
        db, conn = db_with({"policy_version": 1}, {"id": RULE}, None)
        written = upsert_rule(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            rule_id=None,
            values=rule_values(),
            tags=["nav"],
            expected_policy_version=0,
            actor_id="user-1",
            actor_name="ken@example.com",
        )
        insert = conn.statements[1]
        assert "INSERT INTO apiome.slate_cache_rules" in insert[0]
        assert "ken@example.com" in insert[1]
        assert written["tags"] == ["nav"]

    def test_replacing_a_rule_is_scoped_to_the_lane_and_tenant(self) -> None:
        db, conn = db_with({"policy_version": 2}, {"id": RULE}, None)
        upsert_rule(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            rule_id=RULE,
            values=rule_values(),
            tags=[],
            expected_policy_version=1,
            actor_id=None,
            actor_name="a",
        )
        update = conn.statements[1][0]
        assert "UPDATE apiome.slate_cache_rules" in update
        assert "environment_id = %s::uuid AND tenant_id = %s::uuid" in update

    def test_replacing_a_rule_that_is_not_on_the_lane_raises_and_rolls_back(self) -> None:
        db, conn = db_with({"policy_version": 2}, None)
        with pytest.raises(SlateCacheStoreError) as excinfo:
            upsert_rule(
                db,
                tenant_id=TENANT,
                environment_id=ENV,
                rule_id=RULE,
                values=rule_values(),
                tags=[],
                expected_policy_version=1,
                actor_id=None,
                actor_name="a",
            )
        assert excinfo.value.code == "rule_not_found"
        assert conn.rollbacks == 1
        assert conn.commits == 0

    def test_tags_are_replaced_wholesale_not_diffed(self) -> None:
        """A stale tag left behind would silently widen a later purge-by-tag."""
        db, conn = db_with({"policy_version": 2}, {"id": RULE}, None)
        upsert_rule(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            rule_id=RULE,
            values=rule_values(),
            tags=["b", "a", "a"],
            expected_policy_version=1,
            actor_id=None,
            actor_name="a",
        )
        emitted = [s[0] for s in conn.statements]
        assert any("DELETE FROM apiome.slate_cache_rule_tags" in s for s in emitted)
        inserted = [s[1][1] for s in conn.statements if "slate_cache_rule_tags" in s[0] and "INSERT" in s[0]]
        assert inserted == ["a", "b"], "tags are deduplicated and ordered"

    def test_deleting_a_rule_that_does_not_exist_raises(self) -> None:
        db, conn = db_with({"policy_version": 2}, None)
        with pytest.raises(SlateCacheStoreError) as excinfo:
            delete_rule(
                db,
                tenant_id=TENANT,
                environment_id=ENV,
                rule_id=RULE,
                expected_policy_version=1,
            )
        assert excinfo.value.code == "rule_not_found"
        assert conn.rollbacks == 1

    def test_deleting_a_rule_commits_once(self) -> None:
        db, conn = db_with({"policy_version": 2}, {"id": RULE})
        assert delete_rule(
            db, tenant_id=TENANT, environment_id=ENV, rule_id=RULE, expected_policy_version=1
        )
        assert conn.commits == 1


class TestEvidence:
    """Traces and purges are records; the honesty rules live on the purge row."""

    def test_a_trace_records_its_digest_and_policy_version(self) -> None:
        db, conn = db_with({"id": "trace-1"})
        record_trace(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            actor_id=None,
            actor_name="a",
            actor_kind="user",
            release_id="rel-1",
            request={"path": "/docs"},
            policy_version=3,
            rules_digest="sha256:" + "a" * 64,
            winning_rule_id=RULE,
            verdict={"eligibility": "cacheable"},
        )
        query, params = conn.statements[0]
        assert "INSERT INTO apiome.slate_cache_traces" in query
        assert "sha256:" + "a" * 64 in params
        assert 3 in params

    def test_a_purge_snapshots_edge_attached_as_false(self) -> None:
        """Attaching a delivery tier later must not make old records look like flushes."""
        db, conn = db_with({"id": "purge-1"})
        record_purge(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            actor_id=None,
            actor_name="a",
            actor_kind="user",
            scope_kind="prefix",
            scope_value="/docs",
            release_id="rel-1",
            reason="stale nav",
            estimated_objects=12,
            estimate_basis="changed-pages",
            sample_routes=["/docs/a"],
            dry_run=False,
            outcome="recorded",
            refusal_reason=None,
            edge_attached=False,
        )
        params = conn.statements[0][1]
        assert False in params
        assert "recorded" in params
        assert "dispatched" not in params

    def test_a_refused_purge_is_still_recorded_with_its_reason(self) -> None:
        db, conn = db_with({"id": "purge-2"})
        record_purge(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            actor_id=None,
            actor_name="a",
            actor_kind="user",
            scope_kind="prefix",
            scope_value="/nope",
            release_id=None,
            reason="incident",
            estimated_objects=0,
            estimate_basis="none",
            sample_routes=[],
            dry_run=False,
            outcome="refused",
            refusal_reason="purge-scope-empty",
            edge_attached=False,
        )
        params = conn.statements[0][1]
        assert "refused" in params
        assert "purge-scope-empty" in params

    def test_purge_history_can_be_filtered_by_scope_kind(self) -> None:
        db, conn = db_with([])
        list_purges(db, tenant_id=TENANT, environment_id=ENV, scope_kind="host")
        query, params = conn.statements[0]
        assert "scope_kind = %s" in query
        assert "host" in params

    def test_purge_history_is_newest_first(self) -> None:
        db, conn = db_with([])
        list_purges(db, tenant_id=TENANT, environment_id=ENV)
        assert "ORDER BY at DESC" in conn.statements[0][0]

    def test_an_audit_entry_names_its_subject(self) -> None:
        db, conn = db_with(None)
        append_audit(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            actor_id=None,
            actor_name="ken@example.com",
            actor_kind="user",
            subject_kind="purge",
            subject_id="purge-1",
            summary="Purged by prefix",
            detail="12 objects",
        )
        query, params = conn.statements[0]
        assert "INSERT INTO apiome.slate_cache_audit" in query
        assert "purge" in params
        assert "Purged by prefix" in params
        assert conn.commits == 1

    def test_routes_for_a_release_come_from_the_changed_pages_table(self) -> None:
        db, conn = db_with([{"route": "/a"}, {"route": "/b"}])
        assert routes_for_release(db, release_id="rel-1") == ["/a", "/b"]
        assert "slate_release_changed_pages" in conn.statements[0][0]
