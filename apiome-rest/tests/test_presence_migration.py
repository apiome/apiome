"""Guardrails for the presence and soft-lock migration — COL-4.1 (#4525).

V375 adds ``project_presence`` and ``element_locks``. Each fragment pins a promise the REST layer
relies on: liveness is a lease, one holder per element, and rows go with their owners. Compared
against the SQL with ``--`` comments removed, so prose cannot satisfy it.
"""

from pathlib import Path

_MIGRATION = "apiome-db/scripts/V375__project_presence_soft_locks_col_4_1.sql"

_REQUIRED_FRAGMENTS = (
    "CREATE TABLE IF NOT EXISTS project_presence (",
    "CREATE TABLE IF NOT EXISTS element_locks (",
    "project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE",
    "user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE",
    "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE",
    # A tab is one row; an element has one holder.
    "PRIMARY KEY (project_id, session_id)",
    "PRIMARY KEY (project_id, element_key)",
    # Liveness is a lease.
    "last_seen_at TIMESTAMP WITH TIME ZONE NOT NULL",
    "expires_at TIMESTAMP WITH TIME ZONE NOT NULL",
    "CHECK ((takeover_session_id IS NULL) = (takeover_requested_at IS NULL))",
    "takeover_user_id UUID REFERENCES users(id) ON DELETE SET NULL",
    "ON element_locks (expires_at)",
)


def _sql() -> str:
    root = Path(__file__).resolve().parents[2]
    lines = (root / _MIGRATION).read_text().splitlines()
    return "\n".join(line.split("--", 1)[0] for line in lines)


def test_migration_keeps_its_promises():
    sql = " ".join(_sql().split())
    missing = [fragment for fragment in _REQUIRED_FRAGMENTS if " ".join(fragment.split()) not in sql]
    assert not missing, missing
