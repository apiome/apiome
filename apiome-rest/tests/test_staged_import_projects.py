"""Projects staged by an import awaiting approval stay out of every project read.

DBP-1.9 (#7192). The UI import wizard commits an import *staged*: the version carries
``import_pending_at`` and, like a project the import created, has ``deleted_at`` set so nothing
shows it until the reviewer accepts (apiome-ui ``lib/db/import-staging.ts``). A read that
includes soft-deleted projects — the Show deleted lists, restore, permanent delete — must not
take such a project for one a user deleted.

This module pins the predicate without a database; ``tests/test_staged_import_projects_db.py``
runs the reads on PostgreSQL.
"""

from __future__ import annotations

from typing import Any, List, Tuple

import pytest

from app.database import Database

PID = "11111111-1111-4111-8111-111111111111"
TID = "22222222-2222-4222-8222-222222222222"

STAGED = (
    "NOT EXISTS (SELECT 1 FROM apiome.versions sv "
    "WHERE sv.project_id = p.id AND sv.import_pending_at IS NOT NULL)"
)


class _RecordingDb(Database):
    """A :class:`Database` that records each query instead of running it."""

    def __init__(self) -> None:
        self.statements: List[Tuple[str, Any]] = []

    def execute_query(self, query: str, params: Any = None, *args: Any, **kwargs: Any) -> list:  # type: ignore[override]
        self.statements.append((" ".join(query.split()), params))
        return []


def test_live_reads_keep_the_plain_soft_delete_filter() -> None:
    assert Database._project_deleted_filter(False) == "AND p.deleted_at IS NULL"


def test_reads_that_include_deleted_projects_leave_staged_ones_out() -> None:
    assert Database._project_deleted_filter(True) == f"AND (p.deleted_at IS NULL OR {STAGED})"


@pytest.mark.parametrize(
    "read",
    [
        lambda db: db.get_projects_for_tenant(TID, include_deleted=True),
        lambda db: db.get_catalog_items_for_tenant(TID, include_deleted=True),
        lambda db: db.get_catalog_item_by_id(PID, TID, include_deleted=True),
        lambda db: db.get_project_by_id(PID, TID, include_deleted=True),
        lambda db: db.get_project_core(PID, TID, include_deleted=True),
    ],
    ids=["projects list", "catalog list", "catalog item", "project", "project core"],
)
def test_every_read_that_can_include_deleted_projects_uses_the_filter(read) -> None:
    db = _RecordingDb()
    read(db)
    [(sql, _params)] = db.statements
    assert f"(p.deleted_at IS NULL OR {STAGED})" in sql


@pytest.mark.parametrize(
    "read",
    [
        lambda db: db.get_projects_for_tenant(TID),
        lambda db: db.get_catalog_items_for_tenant(TID),
        lambda db: db.get_project_by_id(PID, TID),
        lambda db: db.get_project_core(PID, TID),
    ],
    ids=["projects list", "catalog list", "project", "project core"],
)
def test_default_reads_are_unchanged(read) -> None:
    db = _RecordingDb()
    read(db)
    [(sql, _params)] = db.statements
    assert "AND p.deleted_at IS NULL" in sql
    assert "import_pending_at" not in sql
