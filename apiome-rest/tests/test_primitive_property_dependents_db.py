"""The "Used by properties" reverse index against a live Postgres (#3477).

:meth:`Database.get_property_bindings_for_primitive` is the reverse lookup over
``class_properties.primitive_id``. What only the real schema can prove:

* the caller sees only properties in their own tenant's projects, even for a shared system type;
* soft-deleted classes, versions and projects drop out;
* a system type also lists properties bound to another per-tenant system copy with the same
  ``$id``, while a tenant type lists only properties bound to its own row.

Everything runs inside one transaction on a dedicated connection that is always rolled back, so the
database is left exactly as it was found. Skipped when no database is reachable.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, Iterator, Optional, Tuple

import psycopg2
import pytest
from psycopg2.extensions import TRANSACTION_STATUS_IDLE
from psycopg2.extras import RealDictCursor

from app.config import settings
from app.database import Database

pytestmark = pytest.mark.requires_db

_STRING_ID = "https://api.apiome.dev/types/std/v0/primitives/string-3477"


class _NoCommitConnection:
    """A real connection whose commits and rollbacks are swallowed, so one test is one transaction."""

    closed = False

    class _Info:
        transaction_status = TRANSACTION_STATUS_IDLE

    info = _Info()

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def cursor(self, *args: Any, **kwargs: Any) -> Any:
        return self._conn.cursor(*args, **kwargs)

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    @property
    def autocommit(self) -> bool:
        return False

    @autocommit.setter
    def autocommit(self, value: bool) -> None:
        pass


@pytest.fixture
def tx() -> Iterator[Tuple[Database, Any]]:
    """A :class:`Database` and a raw cursor over one always-rolled-back transaction."""
    try:
        conn = psycopg2.connect(
            settings.effective_database_url, cursor_factory=RealDictCursor, connect_timeout=3
        )
    except psycopg2.OperationalError:
        pytest.skip("no database reachable")
    with conn.cursor() as probe:
        probe.execute(
            """SELECT EXISTS (
                   SELECT 1 FROM information_schema.columns
                   WHERE table_schema = 'apiome' AND table_name = 'class_properties'
                     AND column_name = 'primitive_id') AS bound,
                   (SELECT id FROM apiome.users LIMIT 1) AS u"""
        )
        found = probe.fetchone()
    if not found["bound"] or not found["u"]:
        conn.close()
        pytest.skip("V112 not applied or no user to own the seed projects")
    db = Database()
    db.connection = _NoCommitConnection(conn)
    try:
        with conn.cursor() as cursor:
            yield db, cursor
    finally:
        conn.rollback()
        conn.close()


def _one(cursor: Any, sql: str, params: tuple) -> str:
    """Run an ``INSERT … RETURNING id::text AS id`` and return the id."""
    cursor.execute(sql, params)
    return cursor.fetchone()["id"]


def _tenant(cursor: Any, label: str) -> str:
    suffix = uuid.uuid4().hex[:10]
    return _one(
        cursor,
        "INSERT INTO apiome.tenants (name, slug) VALUES (%s, %s) RETURNING id::text AS id",
        (f"{label} {suffix}", f"{label}-{suffix}"),
    )


def _primitive(
    cursor: Any, tenant: str, name: str, *, is_system: bool, schema_id: Optional[str]
) -> str:
    return _one(
        cursor,
        """INSERT INTO apiome.primitives (tenant_id, name, category, schema, is_system, namespace, schema_id)
           VALUES (%s, %s, 'string', %s::jsonb, %s, %s, %s) RETURNING id::text AS id""",
        (
            tenant,
            name,
            json.dumps({"type": "string"}),
            is_system,
            "std/v0/primitives-3477" if is_system else None,
            schema_id,
        ),
    )


def _bound_property(
    cursor: Any,
    tenant: str,
    primitive: str,
    *,
    class_name: str,
    prop: str,
    deleted: Optional[str] = None,
) -> str:
    """A project → version → class → property chain whose property binds ``primitive``.

    ``deleted`` soft-deletes one link of the chain: ``project``, ``version`` or ``class``.
    """
    cursor.execute("SELECT id::text AS id FROM apiome.users LIMIT 1")
    user = cursor.fetchone()["id"]
    project = _one(
        cursor,
        """INSERT INTO apiome.projects (tenant_id, creator_id, name, slug, deleted_at)
           VALUES (%s, %s, %s, %s, CASE WHEN %s THEN CURRENT_TIMESTAMP END) RETURNING id::text AS id""",
        (tenant, user, f"Project {class_name}", f"p-{uuid.uuid4().hex[:10]}", deleted == "project"),
    )
    version = _one(
        cursor,
        """INSERT INTO apiome.versions (project_id, creator_id, version_id, deleted_at)
           VALUES (%s, %s, '1.0.0', CASE WHEN %s THEN CURRENT_TIMESTAMP END) RETURNING id::text AS id""",
        (project, user, deleted == "version"),
    )
    klass = _one(
        cursor,
        """INSERT INTO apiome.classes (version_id, name, schema, deleted_at)
           VALUES (%s, %s, '{}'::jsonb, CASE WHEN %s THEN CURRENT_TIMESTAMP END) RETURNING id::text AS id""",
        (version, class_name, deleted == "class"),
    )
    return _one(
        cursor,
        """INSERT INTO apiome.class_properties (class_id, name, data, primitive_id, primitive_ref)
           VALUES (%s, %s, '{}'::jsonb, %s, 'std/v0/primitives/string') RETURNING id::text AS id""",
        (klass, prop, primitive),
    )


@pytest.fixture
def seeded(tx: Tuple[Database, Any]) -> Dict[str, Any]:
    """Two tenants, each with its own copy of one system type and one tenant type of its own."""
    db, cursor = tx
    mine, theirs = _tenant(cursor, "mine"), _tenant(cursor, "theirs")
    my_system = _primitive(cursor, mine, "string", is_system=True, schema_id=_STRING_ID)
    their_system = _primitive(cursor, theirs, "string", is_system=True, schema_id=_STRING_ID)
    my_sku = _primitive(cursor, mine, "sku", is_system=False, schema_id=None)
    return {
        "db": db,
        "cursor": cursor,
        "mine": mine,
        "theirs": theirs,
        "my_system": my_system,
        "their_system": their_system,
        "my_sku": my_sku,
    }


def _names(rows: Any) -> list:
    return [(row["class_name"], row["property_name"]) for row in rows]


def test_lists_the_callers_bound_properties_with_their_location(seeded):
    cursor = seeded["cursor"]
    _bound_property(cursor, seeded["mine"], seeded["my_system"], class_name="Customer", prop="email")

    rows = seeded["db"].get_property_bindings_for_primitive(
        seeded["my_system"], seeded["mine"], is_system=True, schema_id=_STRING_ID
    )

    assert _names(rows) == [("Customer", "email")]
    assert rows[0]["version_label"] == "1.0.0"
    assert rows[0]["project_name"] == "Project Customer"
    assert rows[0]["primitive_ref"] == "std/v0/primitives/string"


def test_never_lists_another_tenants_properties(seeded):
    cursor = seeded["cursor"]
    _bound_property(cursor, seeded["theirs"], seeded["their_system"], class_name="Secret", prop="x")
    _bound_property(cursor, seeded["theirs"], seeded["my_system"], class_name="Leak", prop="y")

    rows = seeded["db"].get_property_bindings_for_primitive(
        seeded["my_system"], seeded["mine"], is_system=True, schema_id=_STRING_ID
    )

    assert rows == []


def test_a_system_type_includes_bindings_to_its_other_copies(seeded):
    cursor = seeded["cursor"]
    _bound_property(cursor, seeded["mine"], seeded["their_system"], class_name="Order", prop="note")

    rows = seeded["db"].get_property_bindings_for_primitive(
        seeded["my_system"], seeded["mine"], is_system=True, schema_id=_STRING_ID
    )

    assert _names(rows) == [("Order", "note")]


def test_a_tenant_type_lists_only_its_own_row(seeded):
    cursor = seeded["cursor"]
    _bound_property(cursor, seeded["mine"], seeded["my_sku"], class_name="Item", prop="sku")
    _bound_property(cursor, seeded["mine"], seeded["my_system"], class_name="Item2", prop="name")

    rows = seeded["db"].get_property_bindings_for_primitive(
        seeded["my_sku"], seeded["mine"], is_system=False, schema_id=None
    )

    assert _names(rows) == [("Item", "sku")]


@pytest.mark.parametrize("deleted", ["project", "version", "class"])
def test_soft_deleted_links_drop_out(seeded, deleted):
    cursor = seeded["cursor"]
    _bound_property(
        cursor, seeded["mine"], seeded["my_system"], class_name="Gone", prop="p", deleted=deleted
    )

    rows = seeded["db"].get_property_bindings_for_primitive(
        seeded["my_system"], seeded["mine"], is_system=True, schema_id=_STRING_ID
    )

    assert rows == []
