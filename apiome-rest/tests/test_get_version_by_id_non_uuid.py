"""Regression: a non-UUID version identifier must not reach SQL.

A version *string* (e.g. '0.0.1') sent to a route that expects the version record
UUID used to flow into ``WHERE v.id = %s`` and raise psycopg2
InvalidTextRepresentation, surfacing as an unhandled 500. It must short-circuit to
None instead, so the route's existing "not found" handling returns a clean 404.
"""

from __future__ import annotations

import pytest

from app.database import Database

_VALID_TENANT = "11111111-1111-4111-8111-111111111111"


@pytest.mark.parametrize("bad_id", ["0.0.1", "1.0.0", "not-a-uuid", "", "abc123"])
def test_non_uuid_version_id_returns_none_without_querying(bad_id):
    db = Database()

    def _boom(*args, **kwargs):  # execute_query must never be reached for a bad id
        raise AssertionError("execute_query should not run for a non-UUID version id")

    db.execute_query = _boom  # type: ignore[method-assign]
    assert db.get_version_by_id(bad_id, _VALID_TENANT) is None
