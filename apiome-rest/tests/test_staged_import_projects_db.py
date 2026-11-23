"""Staged imports are invisible to the project reads, against Postgres (DBP-1.9, #7192).

``tests/test_staged_import_projects.py`` pins the predicate; here a project and its version are
put in the staged state the UI import writes (``deleted_at`` set on both, ``import_pending_at`` on
the version) and every read that can include deleted projects is checked against a project a
user really deleted.

Skips when no database with V411 is reachable.
"""

from __future__ import annotations

from typing import Any, Dict, Iterator

import pytest

from tests.test_content_stamp_db import env as stamp_env  # noqa: F401 - the seeded tenant/project/revision

pytestmark = pytest.mark.requires_db


@pytest.fixture
def staged(stamp_env: Dict[str, Any]) -> Iterator[Dict[str, Any]]:  # noqa: F811
    """The seeded project staged by an import, plus a second project a user soft-deleted."""
    conn = stamp_env["conn"]
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_schema = 'apiome' "
            "AND table_name = 'versions' AND column_name = 'import_pending_at'"
        )
        if not cur.fetchone():
            conn.commit()
            pytest.skip("V411 not applied")
        cur.execute(
            "UPDATE apiome.versions SET deleted_at = CURRENT_TIMESTAMP, import_pending_at = CURRENT_TIMESTAMP "
            "WHERE id = %s::uuid",
            (stamp_env["version"],),
        )
        cur.execute(
            "UPDATE apiome.projects SET deleted_at = CURRENT_TIMESTAMP WHERE id = %s::uuid",
            (stamp_env["project"],),
        )
        cur.execute(
            "INSERT INTO apiome.projects (tenant_id, creator_id, name, slug, deleted_at) "
            "VALUES (%s, %s, 'Trashed', %s, CURRENT_TIMESTAMP) RETURNING id::text AS id",
            (stamp_env["tenant"], stamp_env["user"], f"trashed-{stamp_env['project'][:8]}"),
        )
        stamp_env["trashed"] = cur.fetchone()["id"]
    conn.commit()
    yield stamp_env


def test_show_deleted_lists_a_deleted_project_but_not_a_staged_one(staged) -> None:
    db, tenant = staged["db"], staged["tenant"]
    listed = {str(row["id"]) for row in db.get_projects_for_tenant(tenant, include_deleted=True)}
    assert staged["trashed"] in listed
    assert staged["project"] not in listed
    assert db.get_projects_for_tenant(tenant) == []


def test_a_staged_project_cannot_be_looked_up_for_restore_or_purge(staged) -> None:
    db, tenant = staged["db"], staged["tenant"]
    assert db.get_project_core(staged["project"], tenant, include_deleted=True) is None
    assert db.get_project_by_id(staged["project"], tenant, include_deleted=True) is None
    assert db.get_project_core(staged["trashed"], tenant, include_deleted=True) is not None


def test_an_accepted_import_reads_like_any_project(staged) -> None:
    db, tenant, conn = staged["db"], staged["tenant"], staged["conn"]
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE apiome.versions SET deleted_at = NULL, import_pending_at = NULL WHERE id = %s::uuid",
            (staged["version"],),
        )
        cur.execute("UPDATE apiome.projects SET deleted_at = NULL WHERE id = %s::uuid", (staged["project"],))
    conn.commit()
    assert [str(row["id"]) for row in db.get_projects_for_tenant(tenant)] == [staged["project"]]
    assert db.get_project_core(staged["project"], tenant) is not None


def test_a_live_project_with_a_staged_new_version_stays_listed(staged) -> None:
    db, tenant, conn = staged["db"], staged["tenant"], staged["conn"]
    with conn.cursor() as cur:
        cur.execute("UPDATE apiome.projects SET deleted_at = NULL WHERE id = %s::uuid", (staged["project"],))
    conn.commit()
    listed = {str(row["id"]) for row in db.get_projects_for_tenant(tenant, include_deleted=True)}
    assert staged["project"] in listed
    # The staged version itself is not a live revision of the project.
    assert db.get_version_core(staged["version"], tenant) is None
