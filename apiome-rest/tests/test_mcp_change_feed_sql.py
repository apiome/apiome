"""The public MCP change-feed reads pick the newest snapshots before joining changes (DBP-1.16, #7199).

Both feeds return at most ``limit`` change rows. They used to join and sort the whole change
history to find them; they now choose the newest ``limit`` snapshots that recorded a change and
join only those. That the rows are identical was checked against the old statements on the scale
database; these tests pin the statement shape.
"""

from __future__ import annotations

from typing import Any, List, Tuple
from unittest.mock import patch

from app.database import Database

ENDPOINT = "11111111-1111-1111-1111-111111111111"


def _capture(call) -> Tuple[str, Tuple[Any, ...]]:
    """Run ``call`` with ``execute_query`` recorded; return the one statement and its parameters."""
    seen: List[Tuple[str, Tuple[Any, ...]]] = []

    def record(self, query, params=None, *args, **kwargs):
        seen.append((" ".join(str(query).split()), tuple(params or ())))
        return []

    with patch.object(Database, "execute_query", record):
        call(Database.__new__(Database))
    assert len(seen) == 1, "a feed read is one statement"
    return seen[0]


def test_the_endpoint_feed_picks_the_newest_snapshots_with_changes_first():
    sql, params = _capture(lambda db: db.get_public_mcp_endpoint_changes(ENDPOINT, limit=50))
    newest, outer = sql.split(") SELECT", 1)
    assert newest.startswith("WITH newest AS ( SELECT v.id, v.version_seq")
    assert "FROM apiome.mcp_endpoint_versions v WHERE v.endpoint_id = %s::uuid" in newest
    assert "AND EXISTS ( SELECT 1 FROM apiome.mcp_version_changes x WHERE x.version_id = v.id )" in newest
    assert newest.rstrip().endswith("ORDER BY v.version_seq DESC LIMIT %s")
    # Changes are joined to those snapshots only, then ordered and limited as before.
    assert "FROM newest v JOIN apiome.mcp_version_changes c ON c.version_id = v.id" in outer
    assert "ORDER BY v.version_seq DESC, CASE c.item_type" in outer
    assert outer.rstrip().endswith("c.item_name ASC LIMIT %s")
    assert params == (ENDPOINT, 50, 50)


def test_the_endpoint_feed_keeps_its_row_shape():
    sql, _ = _capture(lambda db: db.get_public_mcp_endpoint_changes(ENDPOINT))
    for column in (
        "c.version_id",
        "c.change_type",
        "c.item_type",
        "c.item_name",
        "c.detail",
        "c.created_at",
        "v.version_seq",
        "v.version_tag",
        "v.discovered_at",
        "v.created_at AS version_created_at",
    ):
        assert column in sql.split("FROM newest v")[0]


def test_the_catalog_feed_picks_the_newest_public_snapshots_with_changes_first():
    sql, params = _capture(lambda db: db.get_public_catalog_changes("acme", limit=25))
    newest, outer = sql.split(") SELECT", 1)
    # The public gate is applied where the snapshots are chosen, so nothing private is ever joined.
    assert "e.published IS TRUE" in newest and "e.visibility = 'public'::apiome.visibility_type" in newest
    assert "e.enabled IS TRUE" in newest and "e.deleted_at IS NULL" in newest and "t.deleted_at IS NULL" in newest
    assert "AND t.slug = %s" in newest
    assert "AND EXISTS ( SELECT 1 FROM apiome.mcp_version_changes x WHERE x.version_id = v.id )" in newest
    # Snapshots are ranked in the feed's own order, which is total over snapshots.
    assert newest.rstrip().endswith(
        "ORDER BY COALESCE(v.discovered_at, v.created_at) DESC, e.slug ASC, v.version_seq DESC LIMIT %s"
    )
    assert "FROM newest v JOIN apiome.mcp_version_changes c ON c.version_id = v.id" in outer
    assert (
        "ORDER BY COALESCE(v.discovered_at, v.created_at) DESC, "
        "v.endpoint_slug ASC, v.version_seq DESC, CASE c.item_type" in outer
    )
    assert outer.rstrip().endswith("LIMIT %s")
    assert params == ("acme", 25, 25)
    # No table but the chosen snapshots and their changes is read by the outer query.
    assert "apiome.mcp_endpoints" not in outer and "apiome.tenants" not in outer


def test_the_catalog_feed_keeps_its_row_shape():
    sql, _ = _capture(lambda db: db.get_public_catalog_changes("acme"))
    head = sql.split(") SELECT", 1)[1].split("FROM newest v")[0]
    for column in (
        "v.endpoint_id",
        "v.endpoint_name",
        "v.endpoint_slug",
        "c.version_id",
        "c.change_type",
        "c.item_type",
        "c.item_name",
        "c.detail",
        "c.created_at",
        "v.version_seq",
        "v.version_tag",
        "v.discovered_at",
        "v.created_at AS version_created_at",
    ):
        assert column in head
