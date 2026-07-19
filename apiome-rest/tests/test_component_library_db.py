"""Component-library transactions — DCW-3.1 (private-suite#2353).

Runs the ``Database`` component-library methods against a scripted fake
connection to prove the DCW-0.2 transaction rules without a live database:

* lifecycle gates are rechecked **inside** the transaction (missing rows,
  published immutability, the no-unsafe-downgrade rule, in-use blockers,
  published project versions) and every failure rolls back with zero commits;
* a successful mutation writes its rows and the audit ledger entry on one
  connection and commits exactly once;
* republishing a published revision is an idempotent no-op with no writes;
* schema-kind revisions snapshot the pinned Type Registry schema in-tx.
"""

import pytest

from app.component_library import payload_digest
from app.database import ComponentLibraryConflictError, db

COMPONENT_ID = "11111111-1111-4111-8111-111111111111"
REVISION_ID = "22222222-2222-4222-8222-222222222222"
VERSION_ID = "33333333-3333-4333-8333-333333333333"
PROJECT_ID = "44444444-4444-4444-8444-444444444444"
PRIMITIVE_ID = "55555555-5555-4555-8555-555555555555"
ACTOR = "66666666-6666-4666-8666-666666666666"
TENANT = "t1"

_COMPONENT_ROW = {
    "id": COMPONENT_ID,
    "tenant_id": TENANT,
    "name": "PageParam",
    "kind": "parameter",
    "description": None,
    "owner_id": ACTOR,
}

_DRAFT_REVISION_ROW = {
    "id": REVISION_ID,
    "component_id": COMPONENT_ID,
    "revision": "1.1.0",
    "state": "draft",
    "schema_primitive_id": None,
    "component_name": "PageParam",
    "kind": "parameter",
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
        if sql.startswith("INSERT INTO apiome.operational_components"):
            conn.insert_counter += 1
            return [{"id": f"77777777-7777-4777-8777-{conn.insert_counter:012d}"}]
        if sql.startswith("INSERT INTO apiome.operational_component_revisions"):
            conn.insert_counter += 1
            return [{"id": f"88888888-8888-4888-8888-{conn.insert_counter:012d}"}]
        if sql.startswith("INSERT INTO apiome.version_component_pins"):
            conn.insert_counter += 1
            return [{"id": f"99999999-9999-4999-8999-{conn.insert_counter:012d}"}]
        if sql.startswith(("INSERT", "UPDATE", "DELETE")):
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


# Markers, most specific first — FakeCursor matches by substring in order.
def _routes(
    *,
    revision_row=_DRAFT_REVISION_ROW,
    published_revisions=(),
    component_row=_COMPONENT_ROW,
    duplicate_component_rows=(),
    duplicate_revision_rows=(),
    version_row=None,
    pin_revision_row=None,
    duplicate_pin_rows=(),
    pin_row=None,
    pin_count_rows=({"pin_count": 0},),
    primitive_rows=(),
):
    return [
        # The revision row joined to its component (component-scoped WHERE).
        ("WHERE r.id = %s::uuid AND r.component_id = %s::uuid",
         [revision_row] if revision_row else []),
        # The pin target revision (tenant-scoped WHERE, no component filter).
        ("WHERE r.id = %s::uuid AND r.tenant_id = %s",
         [pin_revision_row] if pin_revision_row else []),
        ("SELECT revision FROM apiome.operational_component_revisions",
         list(published_revisions)),
        ("SELECT id FROM apiome.operational_component_revisions",
         list(duplicate_revision_rows)),
        ("SELECT id FROM apiome.operational_components",
         list(duplicate_component_rows)),
        ("FROM apiome.operational_components c", [component_row] if component_row else []),
        ("FROM apiome.versions v", [version_row] if version_row else []),
        ("SELECT id FROM apiome.version_component_pins", list(duplicate_pin_rows)),
        ("SELECT id, component_revision_id FROM apiome.version_component_pins",
         [pin_row] if pin_row else []),
        ("FROM apiome.version_component_pins", list(pin_count_rows)),
        ("FROM apiome.primitives", list(primitive_rows)),
    ]


def _connect(monkeypatch, routes):
    conn = FakeConn(routes)
    monkeypatch.setattr(db, "connect", lambda: conn)
    return conn


class TestPublish:
    def test_publish_commits_once_with_audit(self, monkeypatch):
        conn = _connect(
            monkeypatch,
            _routes(published_revisions=[{"revision": "1.0.0"}]),
        )
        result = db.publish_component_revision(TENANT, COMPONENT_ID, REVISION_ID, ACTOR)
        assert result == {
            "published": True,
            "alreadyPublished": False,
            "revision": "1.1.0",
        }
        assert conn.commits == 1
        update_sqls = [sql for sql, _ in conn.writes if sql.startswith("UPDATE")]
        assert any("state = 'published'" in sql for sql in update_sqls)
        assert any(
            sql.startswith("INSERT INTO apiome.component_library_audit")
            for sql, _ in conn.writes
        )

    def test_downgrade_rolls_back_with_head(self, monkeypatch):
        row = dict(_DRAFT_REVISION_ROW, revision="0.9.0")
        conn = _connect(
            monkeypatch,
            _routes(revision_row=row, published_revisions=[{"revision": "1.0.0"}]),
        )
        with pytest.raises(ComponentLibraryConflictError) as excinfo:
            db.publish_component_revision(TENANT, COMPONENT_ID, REVISION_ID, ACTOR)
        assert excinfo.value.code == "revision_downgrade"
        assert excinfo.value.payload["headRevision"] == "1.0.0"
        assert conn.commits == 0
        assert conn.rollbacks >= 1
        assert conn.writes == []

    def test_equal_revision_is_also_a_downgrade(self, monkeypatch):
        row = dict(_DRAFT_REVISION_ROW, revision="1.0.0")
        conn = _connect(
            monkeypatch,
            _routes(revision_row=row, published_revisions=[{"revision": "1.0.0"}]),
        )
        with pytest.raises(ComponentLibraryConflictError) as excinfo:
            db.publish_component_revision(TENANT, COMPONENT_ID, REVISION_ID, ACTOR)
        assert excinfo.value.code == "revision_downgrade"
        assert conn.writes == []

    def test_republish_is_idempotent_noop(self, monkeypatch):
        row = dict(_DRAFT_REVISION_ROW, state="published")
        conn = _connect(monkeypatch, _routes(revision_row=row))
        result = db.publish_component_revision(TENANT, COMPONENT_ID, REVISION_ID, ACTOR)
        assert result["alreadyPublished"] is True
        assert conn.commits == 0
        assert conn.writes == []

    def test_missing_revision_rolls_back(self, monkeypatch):
        conn = _connect(monkeypatch, _routes(revision_row=None))
        with pytest.raises(ComponentLibraryConflictError) as excinfo:
            db.publish_component_revision(TENANT, COMPONENT_ID, REVISION_ID, ACTOR)
        assert excinfo.value.code == "revision_not_found"
        assert conn.commits == 0
        assert conn.writes == []


class TestImmutabilityAndDeletion:
    def test_update_published_revision_rolls_back(self, monkeypatch):
        row = dict(_DRAFT_REVISION_ROW, state="published")
        conn = _connect(monkeypatch, _routes(revision_row=row))
        with pytest.raises(ComponentLibraryConflictError) as excinfo:
            db.update_component_revision(
                TENANT,
                COMPONENT_ID,
                REVISION_ID,
                payload={"name": "page", "in": "query"},
                payload_digest="sha256:x",
                schema_primitive_id=None,
                actor_id=ACTOR,
            )
        assert excinfo.value.code == "published_immutable"
        assert conn.commits == 0
        assert conn.writes == []

    def test_delete_component_in_use_rolls_back(self, monkeypatch):
        conn = _connect(monkeypatch, _routes(pin_count_rows=[{"pin_count": 2}]))
        with pytest.raises(ComponentLibraryConflictError) as excinfo:
            db.delete_operational_component(TENANT, COMPONENT_ID, ACTOR)
        assert excinfo.value.code == "component_in_use"
        assert excinfo.value.payload["pinCount"] == 2
        assert conn.commits == 0
        assert conn.writes == []

    def test_delete_unused_component_commits_once(self, monkeypatch):
        conn = _connect(monkeypatch, _routes())
        assert db.delete_operational_component(TENANT, COMPONENT_ID, ACTOR) == {
            "deleted": True
        }
        assert conn.commits == 1
        assert any(
            sql.startswith("UPDATE apiome.operational_components") for sql, _ in conn.writes
        )

    def test_delete_published_revision_rolls_back(self, monkeypatch):
        row = dict(_DRAFT_REVISION_ROW, state="published")
        conn = _connect(monkeypatch, _routes(revision_row=row))
        with pytest.raises(ComponentLibraryConflictError) as excinfo:
            db.delete_component_revision(TENANT, COMPONENT_ID, REVISION_ID, ACTOR)
        assert excinfo.value.code == "published_immutable"
        assert conn.writes == []

    def test_delete_pinned_revision_rolls_back(self, monkeypatch):
        conn = _connect(monkeypatch, _routes(pin_count_rows=[{"pin_count": 1}]))
        with pytest.raises(ComponentLibraryConflictError) as excinfo:
            db.delete_component_revision(TENANT, COMPONENT_ID, REVISION_ID, ACTOR)
        assert excinfo.value.code == "revision_in_use"
        assert conn.commits == 0
        assert conn.writes == []


class TestPins:
    _PUBLISHED_PIN_REVISION = {
        "id": REVISION_ID,
        "state": "published",
        "revision": "1.0.0",
        "component_name": "PageParam",
        "kind": "parameter",
    }

    def test_pin_on_published_version_rolls_back(self, monkeypatch):
        conn = _connect(
            monkeypatch,
            _routes(version_row={"id": VERSION_ID, "published": True}),
        )
        with pytest.raises(ComponentLibraryConflictError) as excinfo:
            db.create_version_component_pin(
                TENANT,
                PROJECT_ID,
                VERSION_ID,
                component_revision_id=REVISION_ID,
                local_name=None,
                actor_id=ACTOR,
            )
        assert excinfo.value.code == "published_version"
        assert conn.commits == 0
        assert conn.writes == []

    def test_pin_unpublished_revision_rolls_back(self, monkeypatch):
        conn = _connect(
            monkeypatch,
            _routes(
                version_row={"id": VERSION_ID, "published": False},
                pin_revision_row=dict(self._PUBLISHED_PIN_REVISION, state="draft"),
            ),
        )
        with pytest.raises(ComponentLibraryConflictError) as excinfo:
            db.create_version_component_pin(
                TENANT,
                PROJECT_ID,
                VERSION_ID,
                component_revision_id=REVISION_ID,
                local_name=None,
                actor_id=ACTOR,
            )
        assert excinfo.value.code == "revision_not_published"
        assert conn.writes == []

    def test_cross_tenant_revision_reads_as_not_found(self, monkeypatch):
        conn = _connect(
            monkeypatch,
            _routes(
                version_row={"id": VERSION_ID, "published": False},
                pin_revision_row=None,
            ),
        )
        with pytest.raises(ComponentLibraryConflictError) as excinfo:
            db.create_version_component_pin(
                TENANT,
                PROJECT_ID,
                VERSION_ID,
                component_revision_id=REVISION_ID,
                local_name=None,
                actor_id=ACTOR,
            )
        assert excinfo.value.code == "revision_not_found"
        assert conn.writes == []

    def test_pin_success_commits_once_with_audit(self, monkeypatch):
        conn = _connect(
            monkeypatch,
            _routes(
                version_row={"id": VERSION_ID, "published": False},
                pin_revision_row=self._PUBLISHED_PIN_REVISION,
            ),
        )
        result = db.create_version_component_pin(
            TENANT,
            PROJECT_ID,
            VERSION_ID,
            component_revision_id=REVISION_ID,
            local_name="Page",
            actor_id=ACTOR,
        )
        assert result["pinId"]
        assert conn.commits == 1
        assert any(
            sql.startswith("INSERT INTO apiome.version_component_pins")
            for sql, _ in conn.writes
        )
        assert any(
            sql.startswith("INSERT INTO apiome.component_library_audit")
            for sql, _ in conn.writes
        )

    def test_unpin_missing_pin_rolls_back(self, monkeypatch):
        conn = _connect(
            monkeypatch,
            _routes(
                version_row={"id": VERSION_ID, "published": False},
                pin_row=None,
            ),
        )
        with pytest.raises(ComponentLibraryConflictError) as excinfo:
            db.delete_version_component_pin(
                TENANT, PROJECT_ID, VERSION_ID, "pin-1", ACTOR
            )
        assert excinfo.value.code == "pin_not_found"
        assert conn.commits == 0
        assert conn.writes == []


class TestSchemaSnapshot:
    def test_schema_revision_snapshots_the_pinned_registry_schema(self, monkeypatch):
        component = dict(_COMPONENT_ROW, kind="schema", name="Money")
        snapshot = {"type": "string", "pattern": "^\\d+\\.\\d{2}$"}
        conn = _connect(
            monkeypatch,
            _routes(
                component_row=component,
                primitive_rows=[{"id": PRIMITIVE_ID, "schema": snapshot}],
            ),
        )
        result = db.create_component_revision(
            TENANT,
            COMPONENT_ID,
            revision="1.0.0",
            payload={"ignored": True},
            payload_digest="sha256:ignored",
            schema_primitive_id=PRIMITIVE_ID,
            actor_id=ACTOR,
        )
        assert result["revisionId"]
        assert conn.commits == 1
        insert = next(
            params
            for sql, params in conn.writes
            if sql.startswith("INSERT INTO apiome.operational_component_revisions")
        )
        # The stored payload and digest are the snapshot's, not the caller's.
        stored_payload = next(p for p in insert if hasattr(p, "adapted"))
        assert stored_payload.adapted == snapshot
        assert payload_digest(snapshot) in insert

    def test_schema_revision_without_pin_rolls_back(self, monkeypatch):
        component = dict(_COMPONENT_ROW, kind="schema", name="Money")
        conn = _connect(monkeypatch, _routes(component_row=component))
        with pytest.raises(ComponentLibraryConflictError) as excinfo:
            db.create_component_revision(
                TENANT,
                COMPONENT_ID,
                revision="1.0.0",
                payload={},
                payload_digest="sha256:x",
                schema_primitive_id=None,
                actor_id=ACTOR,
            )
        assert excinfo.value.code == "schema_ref_required"
        assert conn.writes == []

    def test_schema_revision_with_missing_registry_entry_rolls_back(self, monkeypatch):
        component = dict(_COMPONENT_ROW, kind="schema", name="Money")
        conn = _connect(
            monkeypatch, _routes(component_row=component, primitive_rows=[])
        )
        with pytest.raises(ComponentLibraryConflictError) as excinfo:
            db.create_component_revision(
                TENANT,
                COMPONENT_ID,
                revision="1.0.0",
                payload={},
                payload_digest="sha256:x",
                schema_primitive_id=PRIMITIVE_ID,
                actor_id=ACTOR,
            )
        assert excinfo.value.code == "schema_ref_not_found"
        assert conn.writes == []


class TestTenantScopedSql:
    def test_every_lifecycle_statement_is_tenant_scoped(self, monkeypatch):
        conn = _connect(
            monkeypatch,
            _routes(published_revisions=[{"revision": "1.0.0"}]),
        )
        db.publish_component_revision(TENANT, COMPONENT_ID, REVISION_ID, ACTOR)
        select_sql = conn.statements[0][0]
        assert "r.tenant_id = %s" in select_sql
        assert TENANT in conn.statements[0][1]
