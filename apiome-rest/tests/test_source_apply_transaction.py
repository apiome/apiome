"""The source-apply transaction — DCW-2.3 (private-suite#2360).

Runs ``Database.apply_source_change_set`` against a scripted fake connection
to prove the DCW-0.2 transaction rules without a live database:

* authorization and draft mutability are rechecked **inside** the transaction
  (published revisions, foreign draft locks, and missing versions/permission
  all roll back with zero writes);
* a stale base digest rolls back with the current digest and zero writes;
* a successful apply writes canonical rows, preservation claims, and the
  audit entry on one connection and commits exactly once;
* replaying the recorded change set is an idempotent no-op.
"""

import pytest

from app.database import SourceApplyConflictError, db
from app.preservation_envelope import semantic_fingerprint
from app.source_change_review import change_set_digest

VERSION_ID = "11111111-1111-4111-8111-111111111111"
ACTOR = "22222222-2222-4222-8222-222222222222"

_VERSION_ROW = {
    "id": VERSION_ID,
    "published": False,
    "published_immutable": False,
    "version_id": "1.0.0",
    "metadata": {"oasDialect": "3.1.0"},
    "project_id": "proj-1",
    "project_name": "proj",
    "project_slug": "proj",
    "project_description": None,
    "project_metadata": None,
}


class FakeCursor:
    """Routes queries by distinctive SQL substrings; records every write."""

    def __init__(self, conn):
        self.conn = conn
        self._pending = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        normalized = " ".join(sql.split())
        self.conn.statements.append((normalized, params))
        self._pending = self._route(normalized)

    def fetchone(self):
        return self._pending[0] if self._pending else None

    def fetchall(self):
        return list(self._pending)

    def _route(self, sql):
        conn = self.conn
        if sql.startswith("INSERT INTO apiome.classes"):
            conn.insert_counter += 1
            return [{"id": f"33333333-3333-3333-3333-{conn.insert_counter:012d}"}]
        if sql.startswith("INSERT INTO apiome.properties"):
            conn.insert_counter += 1
            return [{"id": f"44444444-4444-4444-4444-{conn.insert_counter:012d}"}]
        if sql.startswith("INSERT INTO apiome.version_path"):
            conn.insert_counter += 1
            return [{"id": f"55555555-5555-5555-5555-{conn.insert_counter:012d}"}]
        if sql.startswith("INSERT INTO apiome.shared_path_parameter"):
            conn.insert_counter += 1
            return [{"id": f"66666666-6666-6666-6666-{conn.insert_counter:012d}"}]
        if sql.startswith("INSERT INTO apiome.shared_path_response"):
            conn.insert_counter += 1
            return [{"id": f"77777777-7777-7777-7777-{conn.insert_counter:012d}"}]
        if sql.startswith("INSERT INTO apiome.path_operation "):
            conn.insert_counter += 1
            return [{"id": f"88888888-8888-8888-8888-{conn.insert_counter:012d}"}]
        if sql.startswith("INSERT INTO apiome.shared_path_request_body"):
            conn.insert_counter += 1
            return [{"id": f"99999999-9999-9999-9999-{conn.insert_counter:012d}"}]
        if sql.startswith("INSERT INTO apiome.source_change_audit"):
            conn.insert_counter += 1
            return [{"id": f"aaaaaaaa-aaaa-aaaa-aaaa-{conn.insert_counter:012d}"}]
        if sql.startswith("INSERT") or sql.startswith("UPDATE") or sql.startswith("DELETE"):
            return []
        for marker, rows in conn.routes:
            if marker in sql:
                return [dict(r) for r in rows]
        return []


class _FakeConnInfo:
    def __init__(self):
        import psycopg2.extensions

        self.transaction_status = psycopg2.extensions.TRANSACTION_STATUS_IDLE


class FakeConn:
    def __init__(self, routes):
        self.routes = routes
        self.statements = []
        self.commits = 0
        self.rollbacks = 0
        self.autocommit = True
        self.insert_counter = 0
        self.info = _FakeConnInfo()

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    @property
    def writes(self):
        return [
            (sql, params)
            for sql, params in self.statements
            if sql.startswith(("INSERT", "UPDATE", "DELETE"))
        ]


def _routes(
    *,
    version=_VERSION_ROW,
    lock_rows=(),
    admin_rows=({"ok": 1},),
    audit_rows=(),
):
    return [
        ("FROM apiome.versions v", [version] if version else []),
        ("FROM apiome.version_draft_lock", list(lock_rows)),
        ("FROM apiome.tenant_administrators", list(admin_rows)),
        ("FROM apiome.source_change_audit", list(audit_rows)),
        ("FROM apiome.classes", []),
        ("FROM apiome.class_properties", []),
        ("FROM apiome.version_security_scheme", []),
        ("FROM apiome.version_server", []),
        ("FROM apiome.version_path", []),
        ("FROM apiome.version_preservation_claims", []),
        ("FROM apiome.properties", []),
        ("FROM apiome.tenant_user_roles", []),
        ("FROM apiome.tenant_users", []),
        ("FROM apiome.roles r", []),
    ]


def _current_digest(conn_routes):
    """The digest of the (empty) revision, learned via a stale-base probe."""
    conn = FakeConn(conn_routes)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(db, "connect", lambda: conn)
        with pytest.raises(SourceApplyConflictError) as exc:
            db.apply_source_change_set(
                "t1",
                "tn",
                "proj",
                VERSION_ID,
                actor_id=ACTOR,
                candidate_document=_candidate(),
                source_format="json",
                source_digest="sha256:src",
                base_digest="sha256:wrong",
                change_set_digest_value="sha256:cs",
                dialect="3.1.0",
            )
    assert exc.value.code == "stale_base"
    return exc.value.payload["currentDigest"]


def _candidate():
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "proj API",
            "version": "1.0.0",
            "description": "No description provided",
        },
        "paths": {},
        "components": {"schemas": {"Pet": {"type": "object", "title": "Pet"}}},
    }


def _apply(conn, *, base_digest, cs_digest, candidate=None, actor=ACTOR, monkeypatch):
    monkeypatch.setattr(db, "connect", lambda: conn)
    return db.apply_source_change_set(
        "t1",
        "tn",
        "proj",
        VERSION_ID,
        actor_id=actor,
        candidate_document=candidate or _candidate(),
        source_format="json",
        source_digest="sha256:src",
        base_digest=base_digest,
        change_set_digest_value=cs_digest,
        dialect="3.1.0",
    )


class TestInTransactionRechecks:
    def test_missing_version_rolls_back_with_zero_writes(self, monkeypatch):
        conn = FakeConn(_routes(version=None))
        with pytest.raises(SourceApplyConflictError) as exc:
            _apply(conn, base_digest="x", cs_digest="y", monkeypatch=monkeypatch)
        assert exc.value.code == "version_not_found"
        assert conn.writes == [] and conn.commits == 0 and conn.rollbacks >= 1

    def test_published_version_rolls_back_with_zero_writes(self, monkeypatch):
        published = dict(_VERSION_ROW, published=True)
        conn = FakeConn(_routes(version=published))
        with pytest.raises(SourceApplyConflictError) as exc:
            _apply(conn, base_digest="x", cs_digest="y", monkeypatch=monkeypatch)
        assert exc.value.code == "published_version"
        assert conn.writes == [] and conn.commits == 0

    def test_foreign_draft_lock_rolls_back_and_names_holder(self, monkeypatch):
        conn = FakeConn(_routes(lock_rows=[{"owner_user_id": "user-b"}]))
        with pytest.raises(SourceApplyConflictError) as exc:
            _apply(conn, base_digest="x", cs_digest="y", monkeypatch=monkeypatch)
        assert exc.value.code == "draft_lock_conflict"
        assert exc.value.payload == {"ownerUserId": "user-b"}
        assert conn.writes == [] and conn.commits == 0

    def test_own_draft_lock_does_not_block(self, monkeypatch):
        conn = FakeConn(_routes(lock_rows=[{"owner_user_id": ACTOR}]))
        with pytest.raises(SourceApplyConflictError) as exc:
            _apply(conn, base_digest="x", cs_digest="y", monkeypatch=monkeypatch)
        # Proceeds past the lock to the stale-base check.
        assert exc.value.code == "stale_base"

    def test_no_permission_rolls_back_with_zero_writes(self, monkeypatch):
        conn = FakeConn(_routes(admin_rows=[]))
        with pytest.raises(SourceApplyConflictError) as exc:
            _apply(conn, base_digest="x", cs_digest="y", monkeypatch=monkeypatch)
        assert exc.value.code == "permission_denied"
        assert conn.writes == [] and conn.commits == 0


class TestOptimisticConcurrency:
    def test_stale_base_reports_current_digest_and_writes_nothing(self, monkeypatch):
        conn = FakeConn(_routes())
        with pytest.raises(SourceApplyConflictError) as exc:
            _apply(conn, base_digest="sha256:old", cs_digest="y", monkeypatch=monkeypatch)
        assert exc.value.code == "stale_base"
        assert exc.value.payload["currentDigest"]
        assert conn.writes == [] and conn.commits == 0

    def test_change_set_mismatch_rejected(self, monkeypatch):
        base = _current_digest(_routes())
        conn = FakeConn(_routes())
        with pytest.raises(SourceApplyConflictError) as exc:
            _apply(conn, base_digest=base, cs_digest="sha256:not-it", monkeypatch=monkeypatch)
        assert exc.value.code == "change_set_mismatch"
        assert conn.writes == [] and conn.commits == 0


class TestApplyAndReplay:
    def _digests(self):
        base = _current_digest(_routes())
        candidate_fp = semantic_fingerprint(_candidate()).fingerprint
        return base, change_set_digest(base, candidate_fp)

    def test_success_commits_rows_claims_and_audit_together(self, monkeypatch):
        base, cs = self._digests()
        conn = FakeConn(_routes())
        result = _apply(conn, base_digest=base, cs_digest=cs, monkeypatch=monkeypatch)
        assert result["applied"] is True
        assert result["resultDigest"]
        assert result["auditId"]
        assert conn.commits == 1
        write_sql = [sql for sql, _ in conn.writes]
        assert any(sql.startswith("INSERT INTO apiome.classes") for sql in write_sql)
        assert any(
            sql.startswith("INSERT INTO apiome.source_change_audit") for sql in write_sql
        )
        # Claims soft-delete runs even when no new claims are inserted.
        assert any(
            sql.startswith("UPDATE apiome.version_preservation_claims") for sql in write_sql
        )
        # Everything ran on the one scripted connection: atomic by construction.
        assert conn.rollbacks == 0

    def test_replaying_the_applied_change_set_is_idempotent(self, monkeypatch):
        base, cs = self._digests()
        conn = FakeConn(_routes())
        result = _apply(conn, base_digest=base, cs_digest=cs, monkeypatch=monkeypatch)
        replay_routes = _routes(
            audit_rows=[
                {
                    "id": result["auditId"],
                    "change_set_digest": cs,
                    "result_digest": _current_digest(_routes()),
                }
            ]
        )
        # The revision still fingerprints to the recorded result (scripted
        # state is unchanged), so the replay is a no-op success.
        conn2 = FakeConn(replay_routes)
        replay = _apply(conn2, base_digest=base, cs_digest=cs, monkeypatch=monkeypatch)
        assert replay["applied"] is False
        assert replay["alreadyApplied"] is True
        assert conn2.writes == [] and conn2.commits == 0

    def test_no_changes_is_a_no_op(self, monkeypatch):
        base = _current_digest(_routes())
        empty_candidate = {
            "openapi": "3.1.0",
            "info": {
                "title": "proj API",
                "version": "1.0.0",
                "description": "No description provided",
            },
            "paths": {},
            "components": {"schemas": {}},
        }
        candidate_fp = semantic_fingerprint(empty_candidate).fingerprint
        conn = FakeConn(_routes())
        result = _apply(
            conn,
            base_digest=base,
            cs_digest=change_set_digest(base, candidate_fp),
            candidate=empty_candidate,
            monkeypatch=monkeypatch,
        )
        assert result["applied"] is False
        assert result.get("noChanges") is True
        assert conn.writes == [] and conn.commits == 0
