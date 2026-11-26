"""Nothing crosses a tenant, against a live Postgres — PFX-6.1 (#6953).

The migrated schema's own catalog, and the database's answer to a cross-tenant row:

* no Pact table that carries ``tenant_id`` has a single-column foreign key to a tenant-owned row
  (the catalog twin of ``test_pact_tenant_isolation_migration.py``);
* V447's three composite keys refuse a row of one tenant that names a row of another: a webhook
  delivery naming another tenant's webhook, a firing naming another tenant's delivery, a commit status
  naming another tenant's repository — and accept the same row within one tenant;
* removing a repository keeps the commit status and clears only its ``repository_id``;
* a Pact write through its route appends its ``access_audit`` row, on the tenant's hash chain.

Everything runs inside one always-rolled-back transaction (the ``tx`` fixture of
``test_usage_index_db``). Skipped when no database is reachable or V447 is not applied.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Tuple
from unittest.mock import patch

import psycopg2
import pytest
from fastapi.testclient import TestClient
from psycopg2.extras import Json

from app.auth import validate_authentication
from app.main import app
from tests import test_usage_index_db as index_db
from tests.test_pact_tenant_isolation_migration import _EXCEPTIONS, COLUMNS

tx = index_db.tx

pytestmark = pytest.mark.requires_db


@pytest.fixture
def tenants(tx: Tuple[Any, Any]) -> Iterator[Dict[str, Any]]:
    """Two tenants on one transaction; skipped before V447."""
    db, cursor = tx
    cursor.execute("SELECT 1 FROM pg_constraint WHERE conname = 'pact_commit_status_repository_fk'")
    if not cursor.fetchone():
        pytest.skip("V447 not applied")
    yield {"db": db, "cursor": cursor, "a": index_db._tenant(cursor)["tenant"], "b": index_db._tenant(cursor)["tenant"]}


@contextmanager
def _refused(cursor: Any) -> Iterator[None]:
    """Expect a foreign-key violation from the statements inside, keeping the test's transaction."""
    cursor.execute("SAVEPOINT refused")
    with pytest.raises(psycopg2.errors.ForeignKeyViolation):
        yield
    cursor.execute("ROLLBACK TO SAVEPOINT refused")


def _one(cursor: Any, sql: str, params: Tuple[Any, ...]) -> str:
    cursor.execute(sql + " RETURNING id::text AS id", params)
    return cursor.fetchone()["id"]


def _pacticipant(cursor: Any, tenant: str, slug: str) -> str:
    return _one(
        cursor, "INSERT INTO apiome.pacticipant (tenant_id, slug, name) VALUES (%s, %s, %s)", (tenant, slug, slug)
    )


def _webhook(cursor: Any, tenant: str) -> str:
    """A minimal contract webhook of ``tenant`` (every column the table requires)."""
    cursor.execute(
        """
        SELECT column_name, data_type FROM information_schema.columns
        WHERE table_schema = 'apiome' AND table_name = 'pact_webhook'
          AND is_nullable = 'NO' AND column_default IS NULL
        """
    )
    required = {row["column_name"]: row["data_type"] for row in cursor.fetchall()}
    values: Dict[str, Any] = {"tenant_id": tenant}
    defaults = {"request_method": "POST", "request_url": "https://ci.example.com/hook", "description": "hook"}
    for column, kind in required.items():
        if column in values:
            continue
        if column in defaults:
            values[column] = defaults[column]
        elif kind == "ARRAY":
            values[column] = ["contract_published"]
        elif kind in ("jsonb", "json"):
            values[column] = Json({})
        elif kind == "boolean":
            values[column] = True
        elif kind in ("integer", "bigint", "smallint"):
            values[column] = 1
        else:
            values[column] = "x"
    columns = ", ".join(values)
    marks = ", ".join(["%s"] * len(values))
    return _one(cursor, f"INSERT INTO apiome.pact_webhook ({columns}) VALUES ({marks})", tuple(values.values()))


def _delivery(cursor: Any, tenant: str, webhook: Any = None) -> str:
    return _one(
        cursor,
        """INSERT INTO apiome.push_webhook_delivery_events
             (tenant_id, subscription_id, target_url, pact_webhook_id, event_type, payload)
           VALUES (%s, NULL, 'https://ci.example.com/hook', %s, 'pact.contract_published', '{}'::jsonb)""",
        (tenant, webhook),
    )


def _repository(cursor: Any, tenant: str) -> str:
    name = f"acme/{uuid.uuid4().hex[:8]}"
    return _one(
        cursor,
        """INSERT INTO apiome.tenant_repositories (tenant_id, source, provider, clone_url, clone_url_normalized)
           VALUES (%s, 'linked_account', 'github', %s, %s)""",
        (tenant, f"https://github.com/{name}.git", f"https://github.com/{name}.git"),
    )


# ---------------------------------------------------------------------------------------------
# The catalog
# ---------------------------------------------------------------------------------------------


def test_no_tenant_carrying_pact_table_has_a_single_column_reference(tenants: Dict[str, Any]) -> None:
    cursor = tenants["cursor"]
    tables = sorted(set(COLUMNS) | {"push_webhook_delivery_events"})
    cursor.execute(
        """
        SELECT c.conrelid::regclass::text AS tbl, a.attname AS col, c.confrelid::regclass::text AS ref
        FROM pg_constraint c
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
        WHERE c.contype = 'f' AND array_length(c.conkey, 1) = 1
          AND c.conrelid::regclass::text = ANY(%s)
          AND c.confrelid::regclass::text NOT IN ('users', 'tenants')
          AND EXISTS (SELECT 1 FROM pg_attribute t
                      WHERE t.attrelid = c.conrelid AND t.attname = 'tenant_id' AND NOT t.attisdropped)
        """,
        (tables,),
    )
    crossing = sorted(
        f"{row['tbl']}.{row['col']} → {row['ref']}"
        for row in cursor.fetchall()
        if (row["tbl"], row["col"]) not in _EXCEPTIONS
    )
    assert crossing == []


# ---------------------------------------------------------------------------------------------
# V447's keys refuse a crossed row
# ---------------------------------------------------------------------------------------------


def test_a_delivery_cannot_fire_another_tenants_webhook(tenants: Dict[str, Any]) -> None:
    cursor, a, b = tenants["cursor"], tenants["a"], tenants["b"]
    theirs = _webhook(cursor, b)
    with _refused(cursor):
        _delivery(cursor, a, theirs)
    assert _delivery(cursor, b, theirs)


def test_a_firing_cannot_name_another_tenants_delivery(tenants: Dict[str, Any]) -> None:
    cursor, a, b = tenants["cursor"], tenants["a"], tenants["b"]
    hook = _webhook(cursor, a)
    consumer, provider = _pacticipant(cursor, a, "billing"), _pacticipant(cursor, a, "ledger")
    firing = """INSERT INTO apiome.pact_triggered_webhook
                  (tenant_id, webhook_id, delivery_event_id, consumer_id, provider_id, event_name)
                VALUES (%s, %s, %s, %s, %s, 'contract_published')"""
    with _refused(cursor):
        _one(cursor, firing, (a, hook, _delivery(cursor, b), consumer, provider))
    assert _one(cursor, firing, (a, hook, _delivery(cursor, a, hook), consumer, provider))


def test_a_commit_status_cannot_name_another_tenants_repository(tenants: Dict[str, Any]) -> None:
    cursor, a, b = tenants["cursor"], tenants["a"], tenants["b"]
    consumer = _pacticipant(cursor, a, "billing")
    provider = _pacticipant(cursor, a, "ledger")
    version = _one(
        cursor, "INSERT INTO apiome.pacticipant_version (pacticipant_id, number) VALUES (%s, '1.0.0')", (consumer,)
    )
    status = """INSERT INTO apiome.pact_commit_status
                  (tenant_id, pacticipant_id, pacticipant_version_id, consumer_id, provider_id, side, context,
                   state, outcome, repository_id)
                VALUES (%s, %s, %s, %s, %s, 'consumer', %s, 'pass', 'dispatched', %s)"""
    with _refused(cursor):
        _one(cursor, status, (a, consumer, version, consumer, provider, "pact/a", _repository(cursor, b)))

    mine = _repository(cursor, a)
    row = _one(cursor, status, (a, consumer, version, consumer, provider, "pact/b", mine))
    # Removing the repository keeps the status and clears only the reference.
    cursor.execute("DELETE FROM apiome.tenant_repositories WHERE id = %s", (mine,))
    cursor.execute("SELECT tenant_id::text AS t, repository_id FROM apiome.pact_commit_status WHERE id = %s", (row,))
    assert cursor.fetchone() == {"t": a, "repository_id": None}


# ---------------------------------------------------------------------------------------------
# A write route appends its audit row
# ---------------------------------------------------------------------------------------------


def test_registering_a_pacticipant_appends_a_chained_audit_row(tenants: Dict[str, Any]) -> None:
    db, cursor, a = tenants["db"], tenants["cursor"], tenants["a"]
    cursor.execute("SELECT id::text AS id FROM apiome.users LIMIT 1")
    user = cursor.fetchone()["id"]
    app.dependency_overrides[validate_authentication] = lambda: {
        "tenant_id": a,
        "user_id": user,
        "auth_method": "jwt",
        "user_email": "dev@example.com",
    }
    try:
        with (
            patch("app.pacticipant_routes.db", db),
            patch("app.pacticipant_routes.enforce_permission", return_value=user),
        ):
            response = TestClient(app).post("/v1/tenants/t/pacticipants", json={"name": "Billing Service"})
    finally:
        app.dependency_overrides.pop(validate_authentication, None)
    assert response.status_code == 201, response.text

    cursor.execute(
        """SELECT action, actor_id::text AS actor, target, source, detail, entry_hash
           FROM apiome.access_audit WHERE tenant_id = %s ORDER BY created_at DESC, id DESC""",
        (a,),
    )
    row = cursor.fetchone()
    assert (row["action"], row["actor"], row["target"], row["source"]) == (
        "pacts.pacticipant.create",
        user,
        "pacticipants",
        "web",
    )
    assert row["detail"]["id"] == response.json()["id"] and row["entry_hash"]
