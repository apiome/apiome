"""``Database.document_store_usage`` against Postgres — COA-5.9 (#7085).

The usage summary reads ``apiome.document_objects`` (V403) across every tenant, so this test
compares the totals before and after inserting rows for a throwaway tenant id. Skips when no
database with V403 is reachable; the rows it writes are removed afterwards.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import psycopg2
import pytest
from psycopg2.extras import RealDictCursor

from app.config import settings
from app.database import Database

pytestmark = pytest.mark.requires_db


@pytest.fixture
def database():
    """A :class:`Database` on a committing connection, and a throwaway tenant id."""
    try:
        conn = psycopg2.connect(settings.effective_database_url, cursor_factory=RealDictCursor, connect_timeout=3)
    except psycopg2.OperationalError:
        pytest.skip("no database reachable")
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('apiome.document_objects') AS t")
        found = cur.fetchone()["t"]
    conn.commit()
    if not found:
        conn.close()
        pytest.skip("V403 not applied")
    db = Database()
    db.connection = conn
    tenant = f"usage-{uuid.uuid4().hex[:12]}"
    try:
        yield db, conn, tenant
    finally:
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM apiome.document_objects WHERE tenant_id = %s", (tenant,))
        conn.commit()
        conn.close()


def _totals(rows, backend):
    return next((row for row in rows if row["backend"] == backend), None) or {
        "objects": 0,
        "bytes": 0,
        "verified_objects": 0,
        "last_verified_at": None,
    }


def test_usage_counts_objects_bytes_and_verification_per_backend(database):
    db, conn, tenant = database
    before = _totals(db.document_store_usage(), "filesystem")
    verified = datetime(2099, 1, 1, tzinfo=timezone.utc)
    with conn.cursor() as cur:
        for index, (size, stamp) in enumerate(((100, None), (250, verified))):
            sha = f"{index:064x}"
            cur.execute(
                """
                INSERT INTO apiome.document_objects
                    (tenant_id, sha256, size_bytes, backend, storage_key, verified_at)
                VALUES (%s, %s, %s, 'filesystem', %s, %s)
                """,
                (tenant, sha, size, f"tenants/{tenant}/objects/sha256/{sha[:2]}/{sha}", stamp),
            )
    conn.commit()

    after = _totals(db.document_store_usage(), "filesystem")
    assert after["objects"] - before["objects"] == 2
    assert after["bytes"] - before["bytes"] == 350
    assert after["verified_objects"] - before["verified_objects"] == 1
    assert after["last_verified_at"] == verified
