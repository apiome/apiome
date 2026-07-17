"""Email canonicalization + case-insensitive uniqueness (OLO-1.1, #4186).

Covers the two guarantees the ticket adds:
  1. The V180 migration makes ``apiome.users.email`` case-insensitively unique and surfaces (never
     auto-merges) pre-existing case-collision duplicates.
  2. The REST layer canonicalizes email on its lookup path so any casing resolves to one account.
"""

from pathlib import Path
from unittest.mock import MagicMock

from app.database import Database, normalize_email

_MIGRATION = "apiome-db/scripts/V180__email_canonicalization_4186.sql"

_REQUIRED_FRAGMENTS = (
    # Audit table that surfaces duplicates for manual resolution.
    "CREATE TABLE IF NOT EXISTS apiome.email_canonicalization_conflicts",
    "action_taken",
    "'kept_active'",
    "'quarantined'",
    # Byte-exact V001 constraint dropped so normalization cannot collide with it.
    "DROP CONSTRAINT IF EXISTS users_email_key",
    # Every row normalized to its canonical form.
    "SET email = lower(trim(email))",
    # Case-insensitive uniqueness for live accounts.
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_email_lower",
    "(lower(email))",
    "WHERE deleted_at IS NULL",
)


def test_migration_present_and_shaped(repo_root: Path) -> None:
    """V180 carries every fragment that backs the acceptance criteria."""
    text = (repo_root / _MIGRATION).read_text()
    missing = [frag for frag in _REQUIRED_FRAGMENTS if frag not in text]
    assert not missing, f"Migration missing expected fragments: {missing}"


def test_migration_does_not_hard_delete_or_merge_users(repo_root: Path) -> None:
    """Existing dupes are surfaced/quarantined, never silently removed or merged away."""
    text = (repo_root / _MIGRATION).read_text().lower()
    assert "delete from apiome.users" not in text


class TestNormalizeEmail:
    """The single canonicalization helper every email path funnels through."""

    def test_lowercases_and_trims(self) -> None:
        assert normalize_email("Ada@Example.com") == "ada@example.com"
        assert normalize_email("  ADA@EXAMPLE.COM  ") == "ada@example.com"

    def test_is_idempotent(self) -> None:
        once = normalize_email("Ada@Example.com")
        assert normalize_email(once) == once


def test_get_user_by_email_is_case_insensitive() -> None:
    """The lookup canonicalizes input and compares against the normalized stored address."""
    db = Database.__new__(Database)  # bypass __init__/connection; we only exercise the query build
    captured: dict = {}

    def _fake_execute_query(query: str, params):
        captured["query"] = query
        captured["params"] = params
        return [{"id": "u1", "name": "Ada", "email": "ada@example.com"}]

    db.execute_query = MagicMock(side_effect=_fake_execute_query)

    result = db.get_user_by_email("  Ada@EXAMPLE.com ")

    assert result == {"id": "u1", "name": "Ada", "email": "ada@example.com"}
    # Compared against the normalized column, with the input canonicalized before binding.
    assert "lower(email) = %s" in captured["query"]
    assert captured["params"] == ("ada@example.com",)
