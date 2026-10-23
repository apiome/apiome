"""Guardrails for the email verification token migration (V313, SGN-1.1, #5650).

DB-free: asserts the migration's shape — hashed, single-use, expiring tokens owned by a user.
"""

from pathlib import Path

import pytest

_MIGRATION = "V313__email_verification_token_sgn_1_1.sql"


@pytest.fixture
def migration_text(repo_root: Path) -> str:
    path = repo_root / "apiome-db" / "scripts" / _MIGRATION
    assert path.exists(), f"Migration {_MIGRATION} not found at {path}"
    return path.read_text()


def test_creates_the_token_table(migration_text: str) -> None:
    assert "CREATE TABLE IF NOT EXISTS apiome.email_verification_token (" in migration_text


def test_tokens_belong_to_a_user_and_go_with_it(migration_text: str) -> None:
    assert "user_id UUID NOT NULL REFERENCES apiome.users(id) ON DELETE CASCADE" in migration_text


def test_stores_only_the_hash(migration_text: str) -> None:
    assert "token_hash CHAR(64) NOT NULL" in migration_text
    assert "CHECK (token_hash ~ '^[0-9a-f]{64}$')" in migration_text
    assert "ON apiome.email_verification_token (token_hash)" in migration_text
    assert "CREATE UNIQUE INDEX IF NOT EXISTS email_verification_token_hash_uq" in migration_text
    # No plaintext token column.
    assert "token TEXT" not in migration_text
    assert "token VARCHAR" not in migration_text


def test_is_single_use_and_expiring(migration_text: str) -> None:
    assert "expires_at TIMESTAMPTZ NOT NULL" in migration_text
    assert "used_at TIMESTAMPTZ," in migration_text


def test_is_not_tenant_scoped(migration_text: str) -> None:
    assert "tenant_id" not in migration_text
