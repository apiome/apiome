"""Guardrails for the cleanup migration — PFX-1.11 (#6924).

V437 turns deletes into stamps, frees a deleted name for reuse, keeps versions immutable except
for the stamp, and adds labels. Each fragment pins one of those rules, so a later edit that relaxes
one fails here. The REST vocabulary and the database's must also agree.
"""

from pathlib import Path

import pytest

from app.pact_cleanup_store import AUDIT_ACTIONS
from app.pacticipant import DELETE_CAUSES, MAX_REASON_LENGTH

_MIGRATION = "apiome-db/scripts/V437__pact_cleanup_6924.sql"

_REQUIRED_FRAGMENTS = (
    "SET search_path TO apiome, public;",
    # Soft delete on both tables.
    "ALTER TABLE pacticipant\n    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP WITH TIME ZONE",
    "ALTER TABLE pacticipant_version\n    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP WITH TIME ZONE",
    "ADD COLUMN IF NOT EXISTS delete_cause VARCHAR(16)",
    # A name and a number are taken only while live.
    "ALTER TABLE pacticipant DROP CONSTRAINT IF EXISTS pacticipant_tenant_slug_key;",
    "ON pacticipant (tenant_id, slug)\n    WHERE deleted_at IS NULL;",
    "ALTER TABLE pacticipant_version DROP CONSTRAINT IF EXISTS pacticipant_version_number_key;",
    "ON pacticipant_version (pacticipant_id, number)\n    WHERE deleted_at IS NULL;",
    # A stamp always says why.
    "delete_cause IS NOT NULL",
    "delete_cause IN ('version', 'pacticipant', 'retention')",
    # The purge reads stamped rows by time.
    "CREATE INDEX IF NOT EXISTS idx_pacticipant_version_deleted",
    # Versions still never mutate, except the stamp.
    "CREATE OR REPLACE FUNCTION apiome.pacticipant_version_immutable()",
    "'delete_reason', 'delete_cause'];",
    "USING ERRCODE = 'restrict_violation';",
    # Labels: once per pacticipant, never across a tenant.
    "CREATE TABLE IF NOT EXISTS pacticipant_label (",
    "CONSTRAINT pacticipant_label_pkey PRIMARY KEY (pacticipant_id, name)",
    "REFERENCES pacticipant (id, tenant_id) ON DELETE CASCADE",
)


@pytest.fixture(scope="module")
def migration() -> str:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / _MIGRATION
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")
    pytest.skip("apiome-db is not checked out next to apiome-rest")


@pytest.mark.parametrize("fragment", _REQUIRED_FRAGMENTS)
def test_the_migration_keeps_each_rule(migration: str, fragment: str) -> None:
    assert fragment in migration


def test_the_causes_and_the_reason_limit_agree_with_the_rest_api(migration: str) -> None:
    for cause in DELETE_CAUSES:
        assert f"'{cause}'" in migration
    assert f"length(delete_reason) <= {MAX_REASON_LENGTH}" in migration


def test_the_audit_actions_are_namespaced() -> None:
    assert all(action.startswith("pacts.") for action in AUDIT_ACTIONS)
    assert len(set(AUDIT_ACTIONS)) == len(AUDIT_ACTIONS)


def test_no_existing_row_is_rewritten(migration: str) -> None:
    # Online: the migration adds columns, swaps two constraints for partial indexes and adds a table.
    body = "\n".join(line for line in migration.splitlines() if not line.lstrip().startswith("--"))
    assert "UPDATE apiome.pacticipant" not in body and "DELETE FROM" not in body
