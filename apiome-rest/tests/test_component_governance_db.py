"""Component governance transactions — DCW-3.4 (private-suite#2364).

Runs the governance ``Database`` methods against the scripted fake connection of the DCW-3.1
tests: every gate is rechecked inside the transaction and a refusal rolls back with zero
commits; a success writes its rows and the audit entry on one connection and commits once;
published revisions are never updated; tenant scoping is on every statement.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.component_governance import plan_bulk_upgrade, upgrade_confirmation_token
from app.database import ComponentLibraryConflictError, db
from tests.test_component_library_db import FakeConn

TENANT = "t1"
COMPONENT_ID = "11111111-1111-4111-8111-111111111111"
REVISION_ID = "22222222-2222-4222-8222-222222222222"
TARGET_ID = "33333333-3333-4333-8333-333333333333"
ACTOR = "66666666-6666-4666-8666-666666666666"
DIGEST = "sha256:aaa"
POLICY = {"approvalStages": [{"name": "Platform", "requiredApprovals": 1}]}
SUNSET = datetime(2027, 1, 1, tzinfo=timezone.utc)

_DRAFT = {
    "id": REVISION_ID,
    "component_id": COMPONENT_ID,
    "revision": "1.1.0",
    "state": "draft",
    "payload_digest": DIGEST,
    "component_name": "PageParam",
    "kind": "parameter",
}
_PUBLISHED = dict(_DRAFT, revision="1.0.0", state="published")
_TARGET = dict(_DRAFT, id=TARGET_ID, revision="2.0.0", state="published", payload_digest="sha256:t")

_CONSUMERS = [
    {
        "pin_id": "p1",
        "local_name": None,
        "version_id": "v1",
        "version_label": "1.0",
        "published": False,
        "project_id": "proj1",
        "project_name": "Orders",
        "revision_id": REVISION_ID,
        "revision": "1.0.0",
    },
    {
        "pin_id": "p2",
        "local_name": "Page",
        "version_id": "v2",
        "version_label": "2.0",
        "published": True,
        "project_id": "proj2",
        "project_name": "Billing",
        "revision_id": REVISION_ID,
        "revision": "1.0.0",
    },
]


class RevisionRoutedConn(FakeConn):
    """FakeConn whose revision lookups answer per revision id (subject vs target)."""

    def __init__(self, routes, revisions):
        super().__init__(routes)
        self.revisions = revisions

    def cursor(self):
        cursor = super().cursor()
        original = cursor._route
        conn = self

        def route(sql):
            if "WHERE r.id = %s::uuid AND r.component_id = %s::uuid" in sql:
                return []  # resolved in execute below with the params
            if sql.startswith("INSERT INTO apiome.component_revision_approvals"):
                return [{"id": "approval-1"}]
            if sql.startswith("INSERT INTO apiome.component_revision_deprecations"):
                return [{"id": "dep-1"}]
            return original(sql)

        def execute(sql, params=None):
            normalized = " ".join(sql.split())
            conn.statements.append((normalized, params))
            if "WHERE r.id = %s::uuid AND r.component_id = %s::uuid" in normalized:
                row = conn.revisions.get(params[0])
                cursor._pending = [dict(row)] if row else []
            else:
                cursor._pending = route(normalized)

        cursor.execute = execute
        return cursor


def _connect(monkeypatch, routes=(), revisions=None):
    conn = RevisionRoutedConn(list(routes), revisions or {})
    monkeypatch.setattr(db, "connect", lambda: conn)
    return conn


def _audit_rows(conn):
    return [
        params
        for sql, params in conn.writes
        if sql.startswith("INSERT INTO apiome.component_library_audit")
    ]


def _no_revision_updates(conn):
    return not any(
        sql.startswith("UPDATE apiome.operational_component_revisions") for sql, _ in conn.writes
    )


class TestRecordApproval:
    def _record(self, **overrides):
        args = dict(
            stage_index=0,
            stage_name="Platform",
            decision="approve",
            note=None,
            expected_digest=DIGEST,
            actor_id=ACTOR,
            policy=POLICY,
        )
        args.update(overrides)
        return db.record_component_revision_approval(TENANT, COMPONENT_ID, REVISION_ID, **args)

    def test_success_commits_once_with_audit(self, monkeypatch):
        conn = _connect(monkeypatch, revisions={REVISION_ID: _DRAFT})
        assert self._record() == {"approvalId": "approval-1"}
        assert conn.commits == 1
        audit = _audit_rows(conn)
        assert len(audit) == 1
        assert audit[0][5] == "revision.approval"
        detail = audit[0][6].adapted
        assert detail["decision"] == "approve"
        assert detail["policy"] == POLICY
        assert detail["newRevision"] == "1.1.0"

    def test_missing_revision_rolls_back(self, monkeypatch):
        conn = _connect(monkeypatch)
        with pytest.raises(ComponentLibraryConflictError) as excinfo:
            self._record()
        assert excinfo.value.code == "revision_not_found"
        assert conn.commits == 0 and conn.writes == []

    def test_published_revision_takes_no_decisions(self, monkeypatch):
        conn = _connect(monkeypatch, revisions={REVISION_ID: _PUBLISHED})
        with pytest.raises(ComponentLibraryConflictError) as excinfo:
            self._record()
        assert excinfo.value.code == "published_immutable"
        assert conn.commits == 0 and conn.writes == []

    def test_edited_draft_is_stale(self, monkeypatch):
        conn = _connect(monkeypatch, revisions={REVISION_ID: dict(_DRAFT, payload_digest="sha256:new")})
        with pytest.raises(ComponentLibraryConflictError) as excinfo:
            self._record()
        assert excinfo.value.code == "approval_stale"
        assert conn.commits == 0

    def test_duplicate_decision_rolls_back(self, monkeypatch):
        conn = _connect(
            monkeypatch,
            routes=[("SELECT id FROM apiome.component_revision_approvals", [{"id": "x"}])],
            revisions={REVISION_ID: _DRAFT},
        )
        with pytest.raises(ComponentLibraryConflictError) as excinfo:
            self._record()
        assert excinfo.value.code == "duplicate_decision"
        assert conn.commits == 0 and conn.writes == []


class TestPublishWithApproval:
    def test_stale_digest_refuses_publish(self, monkeypatch):
        conn = _connect(monkeypatch, revisions={REVISION_ID: _DRAFT})
        with pytest.raises(ComponentLibraryConflictError) as excinfo:
            db.publish_component_revision(
                TENANT, COMPONENT_ID, REVISION_ID, ACTOR, expected_digest="sha256:other"
            )
        assert excinfo.value.code == "approval_stale"
        assert conn.commits == 0 and conn.writes == []

    def test_publish_records_policy_and_decision(self, monkeypatch):
        conn = _connect(monkeypatch, revisions={REVISION_ID: _DRAFT})
        approval = {"policy": POLICY, "status": "satisfied", "stages": [{"index": 0}]}
        db.publish_component_revision(
            TENANT, COMPONENT_ID, REVISION_ID, ACTOR, expected_digest=DIGEST, approval=approval
        )
        assert conn.commits == 1
        detail = _audit_rows(conn)[0][6].adapted
        assert detail["policy"] == POLICY
        assert detail["decision"] == "published"
        assert detail["approval"]["status"] == "satisfied"


class TestDeprecation:
    def _schedule(self, replacement=None):
        return db.schedule_component_deprecation(
            TENANT,
            COMPONENT_ID,
            REVISION_ID,
            sunset_at=SUNSET,
            replacement_revision_id=replacement,
            migration_guide="Move to 2.0.0",
            policy={"noticeDays": 30},
            actor_id=ACTOR,
        )

    def test_schedule_lists_affected_projects_and_never_touches_the_revision(self, monkeypatch):
        conn = _connect(
            monkeypatch,
            routes=[("FROM apiome.version_component_pins p", _CONSUMERS)],
            revisions={REVISION_ID: _PUBLISHED, TARGET_ID: _TARGET},
        )
        result = self._schedule(TARGET_ID)
        assert result["deprecationId"] == "dep-1"
        assert result["replacementRevision"] == "2.0.0"
        assert [row["project_name"] for row in result["affected"]] == ["Orders", "Billing"]
        assert conn.commits == 1
        assert _no_revision_updates(conn)
        detail = _audit_rows(conn)[0][6].adapted
        assert detail["oldRevision"] == "1.0.0" and detail["newRevision"] == "2.0.0"
        assert [p["projectId"] for p in detail["affectedProjects"]] == ["proj1", "proj2"]
        assert detail["affectedProjects"][1]["published"] is True

    def test_only_published_revisions_are_deprecated(self, monkeypatch):
        conn = _connect(monkeypatch, revisions={REVISION_ID: _DRAFT})
        with pytest.raises(ComponentLibraryConflictError) as excinfo:
            self._schedule()
        assert excinfo.value.code == "revision_not_published"
        assert conn.commits == 0 and conn.writes == []

    @pytest.mark.parametrize(
        "replacement",
        [dict(_TARGET, state="draft"), dict(_TARGET, revision="0.9.0"), None],
    )
    def test_replacement_must_be_published_and_higher(self, monkeypatch, replacement):
        revisions = {REVISION_ID: _PUBLISHED}
        if replacement:
            revisions[TARGET_ID] = replacement
        conn = _connect(monkeypatch, revisions=revisions)
        with pytest.raises(ComponentLibraryConflictError) as excinfo:
            self._schedule(TARGET_ID)
        assert excinfo.value.code == "replacement_invalid"
        assert conn.commits == 0

    def test_one_live_deprecation_per_revision(self, monkeypatch):
        conn = _connect(
            monkeypatch,
            routes=[("SELECT id FROM apiome.component_revision_deprecations", [{"id": "old"}])],
            revisions={REVISION_ID: _PUBLISHED},
        )
        with pytest.raises(ComponentLibraryConflictError) as excinfo:
            self._schedule()
        assert excinfo.value.code == "deprecation_exists"
        assert conn.commits == 0 and conn.writes == []

    def test_cancel(self, monkeypatch):
        conn = _connect(
            monkeypatch,
            routes=[
                (
                    "FROM apiome.component_revision_deprecations d",
                    [{"id": "dep-1", "revision_id": REVISION_ID, "revision": "1.0.0",
                      "component_name": "PageParam"}],
                )
            ],
        )
        assert db.cancel_component_deprecation(
            TENANT, COMPONENT_ID, "dep-1", policy={}, actor_id=ACTOR
        ) == {"cancelled": True}
        assert conn.commits == 1
        assert _audit_rows(conn)[0][5] == "deprecation.cancel"

    def test_cancel_missing_rolls_back(self, monkeypatch):
        conn = _connect(monkeypatch)
        with pytest.raises(ComponentLibraryConflictError) as excinfo:
            db.cancel_component_deprecation(TENANT, COMPONENT_ID, "dep-1", policy={}, actor_id=ACTOR)
        assert excinfo.value.code == "deprecation_not_found"
        assert conn.commits == 0


class TestSunsetBlocksNewPins:
    def test_pin_to_sunset_revision_is_refused(self, monkeypatch):
        conn = FakeConn(
            [
                ("FROM apiome.versions v", [{"id": "v1", "published": False}]),
                ("WHERE r.id = %s::uuid AND r.tenant_id = %s",
                 [{"id": REVISION_ID, "state": "published", "revision": "1.0.0",
                   "component_name": "PageParam", "kind": "parameter"}]),
                ("FROM apiome.component_revision_deprecations", [{"?column?": 1}]),
            ]
        )
        monkeypatch.setattr(db, "connect", lambda: conn)
        with pytest.raises(ComponentLibraryConflictError) as excinfo:
            db.create_version_component_pin(
                TENANT, "proj1", "v1", component_revision_id=REVISION_ID, local_name=None,
                actor_id=ACTOR,
            )
        assert excinfo.value.code == "revision_sunset"
        assert conn.commits == 0 and conn.writes == []


class TestBulkUpgrade:
    def _token(self, consumers=_CONSUMERS):
        return upgrade_confirmation_token(
            COMPONENT_ID, TARGET_ID, plan_bulk_upgrade(consumers, TARGET_ID)
        )

    def _routes(self, consumers=_CONSUMERS, version_published=False):
        return [
            ("FROM apiome.version_component_pins p JOIN apiome.operational_component_revisions r "
             "ON p.component_revision_id = r.id JOIN apiome.versions v", consumers),
            ("SELECT published FROM apiome.versions", [{"published": version_published}]),
        ]

    def _run(self, pin_ids, token):
        return db.execute_component_bulk_upgrade(
            TENANT, COMPONENT_ID, TARGET_ID, pin_ids, confirmation_token=token, policy=POLICY,
            actor_id=ACTOR,
        )

    def test_upgrade_replaces_draft_pins_and_audits_each(self, monkeypatch):
        conn = _connect(monkeypatch, self._routes(), {TARGET_ID: _TARGET})
        result = self._run(["p1"], self._token())
        assert result["targetRevision"] == "2.0.0"
        assert [u["pinId"] for u in result["upgraded"]] == ["p1"]
        assert conn.commits == 1
        soft_deletes = [sql for sql, _ in conn.writes if "SET deleted_at" in sql]
        inserts = [p for sql, p in conn.writes if sql.startswith("INSERT INTO apiome.version_component_pins")]
        assert len(soft_deletes) == 1 and len(inserts) == 1
        assert inserts[0][2] == TARGET_ID
        actions = [row[5] for row in _audit_rows(conn)]
        assert actions == ["pin.upgrade", "upgrade.bulk"]
        bulk = _audit_rows(conn)[1][6].adapted
        assert bulk["oldRevision"] == ["1.0.0"] and bulk["newRevision"] == "2.0.0"
        assert bulk["affectedProjects"][0]["projectName"] == "Orders"
        assert _no_revision_updates(conn)

    def test_stale_token_rolls_back(self, monkeypatch):
        conn = _connect(monkeypatch, self._routes(), {TARGET_ID: _TARGET})
        with pytest.raises(ComponentLibraryConflictError) as excinfo:
            self._run(["p1"], "sha256:previewed-something-else")
        assert excinfo.value.code == "upgrade_plan_stale"
        assert conn.commits == 0 and conn.writes == []

    def test_published_version_pins_are_never_upgraded(self, monkeypatch):
        conn = _connect(monkeypatch, self._routes(), {TARGET_ID: _TARGET})
        with pytest.raises(ComponentLibraryConflictError) as excinfo:
            self._run(["p1", "p2"], self._token())
        assert excinfo.value.code == "upgrade_pin_ineligible"
        assert excinfo.value.payload["pinIds"] == ["p2"]
        assert conn.commits == 0 and conn.writes == []

    def test_version_published_after_lock_is_stale(self, monkeypatch):
        conn = _connect(monkeypatch, self._routes(version_published=True), {TARGET_ID: _TARGET})
        with pytest.raises(ComponentLibraryConflictError) as excinfo:
            self._run(["p1"], self._token())
        assert excinfo.value.code == "upgrade_plan_stale"
        assert conn.commits == 0

    def test_target_must_be_published_and_not_sunset(self, monkeypatch):
        conn = _connect(monkeypatch, revisions={TARGET_ID: dict(_TARGET, state="draft")})
        with pytest.raises(ComponentLibraryConflictError) as excinfo:
            self._run(["p1"], self._token())
        assert excinfo.value.code == "revision_not_published"
        conn = _connect(
            monkeypatch,
            routes=[("FROM apiome.component_revision_deprecations", [{"?column?": 1}])],
            revisions={TARGET_ID: _TARGET},
        )
        with pytest.raises(ComponentLibraryConflictError) as excinfo:
            self._run(["p1"], self._token())
        assert excinfo.value.code == "revision_sunset"
        assert conn.commits == 0


class TestTenantScoping:
    def test_reads_are_tenant_scoped(self, monkeypatch):
        captured = []
        monkeypatch.setattr(
            db, "execute_query", lambda sql, params=None: captured.append((sql, params)) or []
        )
        db.list_component_revision_approvals(TENANT, REVISION_ID)
        db.list_component_deprecations(TENANT, COMPONENT_ID)
        db.get_component_consumers(TENANT, COMPONENT_ID, [REVISION_ID])
        db.list_component_library_audit(
            TENANT, since=SUNSET - timedelta(days=1), until=SUNSET, component_id=COMPONENT_ID
        )
        for sql, params in captured:
            assert "tenant_id = %s" in sql
            assert params[0] == TENANT
        audit_sql, audit_params = captured[-1]
        assert "a.created_at >= %s" in audit_sql and "a.created_at < %s" in audit_sql
        assert audit_params[-1] == 10000
