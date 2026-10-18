"""Guardrails for the owner-routing migration — CDG-2.3 (#5962).

V286 widens the inbox vocabulary by constraint swap, keeps unowned findings, throttles routed events
per team/entity/type, and lets a webhook delivery target a URL with no subscription (a team's chat).
"""

from pathlib import Path

_MIGRATION = "apiome-db/scripts/V286__owner_routing_cdg_2_3.sql"

_FRAGMENTS = (
    "ALTER TABLE notifications DROP CONSTRAINT IF EXISTS notifications_type_check;",
    "ADD CONSTRAINT notifications_type_check",
    "'owner_finding', 'owner_breaking_change', 'owner_verification_drift', 'owner_gate_blocked',",
    "'owner_trust_drift', 'owner_shadow_api', 'owner_sync_failed'",
    "CREATE TABLE IF NOT EXISTS unowned_findings (",
    "CONSTRAINT unowned_findings_entity_type_key UNIQUE (tenant_id, entity_kind, entity_id, finding_type)",
    "occurrences INTEGER NOT NULL DEFAULT 1",
    "CREATE TABLE IF NOT EXISTS owner_notification_throttle (",
    "CONSTRAINT uq_owner_notification_throttle UNIQUE (team_id, entity_kind, entity_id, finding_type)",
    "ALTER COLUMN subscription_id DROP NOT NULL;",
    "ADD COLUMN IF NOT EXISTS target_url TEXT",
    "ADD COLUMN IF NOT EXISTS team_id UUID REFERENCES teams(id) ON DELETE CASCADE",
    "CHECK (subscription_id IS NOT NULL OR (target_url IS NOT NULL AND target_url ~* '^https?://'))",
)


def test_migration_declares_the_routing_rules(repo_root: Path) -> None:
    text = (repo_root / _MIGRATION).read_text()
    missing = [fragment for fragment in _FRAGMENTS if fragment not in text]
    assert not missing, f"Migration missing expected fragments: {missing}"


def test_the_inbox_and_the_report_agree_with_the_rest_vocabulary(repo_root: Path) -> None:
    from app.notifications import OWNER_NOTIFICATION_TYPES
    from app.unowned_findings_routes import FindingType

    text = (repo_root / _MIGRATION).read_text()
    for name in OWNER_NOTIFICATION_TYPES:
        assert text.count(f"'{name}'") >= 2, name  # the inbox CHECK and the report CHECK
    assert set(FindingType.__args__) == set(OWNER_NOTIFICATION_TYPES)
