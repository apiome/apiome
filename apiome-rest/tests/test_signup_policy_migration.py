"""Guardrails for the sign-up policy migration (V274, SGN-1.4, #5653).

DB-free: asserts the migration's shape — the singleton policy table, its mode enum guard, and the
append-only audit ledger the REST surface writes in the same transaction.
"""

from pathlib import Path

import pytest

_MIGRATION = "V274__signup_policy_sgn_1_4.sql"


@pytest.fixture
def migration_text(repo_root: Path) -> str:
    path = repo_root / "apiome-db" / "scripts" / _MIGRATION
    assert path.exists(), f"Migration {_MIGRATION} not found at {path}"
    return path.read_text()


def test_creates_the_singleton_policy_table(migration_text: str) -> None:
    assert "CREATE TABLE IF NOT EXISTS apiome.signup_policy (" in migration_text
    assert "singleton BOOLEAN PRIMARY KEY DEFAULT TRUE" in migration_text
    assert "CONSTRAINT signup_policy_singleton_check CHECK (singleton)" in migration_text


def test_guards_the_mode_vocabulary(migration_text: str) -> None:
    assert "CHECK (mode IN ('open', 'invite_only', 'closed'))" in migration_text


def test_domain_list_defaults_empty_and_is_bounded(migration_text: str) -> None:
    assert "allowed_email_domains TEXT[] NOT NULL DEFAULT '{}'::text[]" in migration_text
    assert "cardinality(allowed_email_domains) <= 200" in migration_text


def test_creates_the_audit_ledger(migration_text: str) -> None:
    assert "CREATE TABLE IF NOT EXISTS apiome.signup_policy_audit (" in migration_text
    assert "CHECK (action IN ('updated', 'cleared'))" in migration_text
    assert "before_policy JSONB" in migration_text
    assert "after_policy JSONB" in migration_text


def test_is_not_tenant_scoped(migration_text: str) -> None:
    assert "tenant_id UUID" not in migration_text
    assert "REFERENCES apiome.tenants" not in migration_text


def test_seeds_no_row_so_env_keeps_governing(migration_text: str) -> None:
    assert "INSERT INTO apiome.signup_policy" not in migration_text


def test_documents_the_rollback(migration_text: str) -> None:
    assert "DROP TABLE IF EXISTS apiome.signup_policy CASCADE" in migration_text
    assert "DROP TABLE IF EXISTS apiome.signup_policy_audit" in migration_text
