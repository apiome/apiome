"""Guardrails for the auth-events audit table migration (OLO-1.6, #4191)."""

from pathlib import Path

_REQUIRED_FRAGMENTS = (
    "CREATE TABLE IF NOT EXISTS auth_events",
    "event_type VARCHAR(32) NOT NULL",
    "user_id UUID REFERENCES users(id) ON DELETE SET NULL",
    "user_label",
    "provider VARCHAR(32)",
    "outcome VARCHAR(16) NOT NULL",
    "error_code",
    "ip_hash",
    "user_agent_hash",
    "detail JSONB",
    "prev_hash",
    "entry_hash",
    "auth_events_outcome_check CHECK (outcome IN ('success', 'failure'))",
    "idx_auth_events_user_created_at",
    "idx_auth_events_created_at",
    "idx_auth_events_event_type",
)


def test_migration_creates_auth_events_table(repo_root: Path) -> None:
    migration = repo_root / "apiome-db" / "scripts" / "V193__auth_events_4191.sql"
    text = migration.read_text()
    missing = [frag for frag in _REQUIRED_FRAGMENTS if frag not in text]
    assert not missing, f"Migration missing expected fragments: {missing}"
