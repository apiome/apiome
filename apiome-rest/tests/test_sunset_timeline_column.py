"""The sunset timeline reads the stored sunset column (DBP-1.15, #7198).

V422 adds ``versions.sunset_at``, a stored generated column holding the first non-empty of
``metadata.sunsetAt``, ``sunsetDate`` and ``sunset_date`` — the order
``app.revision_deprecation`` reads them in. ``list_sunset_timeline_entries`` tests that column
instead of extracting the legacy keys from ``metadata`` for every revision of the tenant. The
deprecation tests are unchanged, and the query is still tenant-scoped.
"""

from __future__ import annotations

import re
from unittest.mock import patch

from app.database import db
from app.revision_deprecation import _SUNSET_ALIAS_KEYS

TENANT = "11111111-1111-4111-8111-111111111111"


def _flat(sql: str) -> str:
    """Collapse whitespace so assertions read the statement as one line."""
    return re.sub(r"\s+", " ", sql).strip()


def _timeline_sql() -> str:
    """The statement ``list_sunset_timeline_entries`` sends."""
    with patch.object(db, "execute_query", return_value=[]) as query:
        db.list_sunset_timeline_entries(TENANT)
    return _flat(query.call_args.args[0])


def test_the_sunset_test_reads_the_stored_column() -> None:
    sql = _timeline_sql()
    assert "OR v.sunset_at IS NOT NULL" in sql
    assert "metadata->>'sunsetDate'" not in sql
    assert "metadata->>'sunset_date'" not in sql


def test_deprecated_revisions_still_match_without_a_sunset() -> None:
    sql = _timeline_sql()
    assert "COALESCE(v.metadata->>'deprecated', '') IN ('true', '1', 'True', 'yes')" in sql
    assert """(v.metadata @> '{"deprecated": true}'::jsonb)""" in sql


def test_the_column_reads_the_spellings_revision_deprecation_reads() -> None:
    # V422's generated expression lists the keys in this order (apiome-db
    # test/home-dashboard-columns.test.ts pins it there).
    assert _SUNSET_ALIAS_KEYS == ("sunsetAt", "sunsetDate", "sunset_date")


def test_the_query_stays_tenant_scoped() -> None:
    with patch.object(db, "execute_query", return_value=[]) as query:
        db.list_sunset_timeline_entries(TENANT, "p1")
    sql, params = query.call_args.args
    assert "WHERE p.tenant_id = %s" in _flat(sql)
    assert params == (TENANT, "p1")
