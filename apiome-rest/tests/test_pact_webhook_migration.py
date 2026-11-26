"""Guardrails for the contract-webhook migration — PFX-1.9 (#6922).

V436 is where the ticket's rules stop being habits and become things the database keeps. Each
fragment below pins one, so a later edit that relaxes it fails here:

* a webhook's secrets exist only as ciphertext, with the names of what is sealed;
* events are the closed list :data:`app.pact_webhook.EVENT_NAMES`, methods :data:`METHODS`;
* nothing crosses a tenant, and a firing goes with its webhook;
* a firing is a row of the shared push-webhook delivery queue, and each attempt can keep a log.
"""

from pathlib import Path

import pytest

from app.pact_webhook import EVENT_NAMES, METHODS, TARGET_GITHUB, TARGET_HTTP

_MIGRATION = "apiome-db/scripts/V436__pact_webhooks_6922.sql"

_REQUIRED_FRAGMENTS = (
    # The migrator runs every script on one connection; this one sets its own path.
    "SET search_path TO apiome, public;",
    "CREATE TABLE IF NOT EXISTS pact_webhook (",
    "CREATE TABLE IF NOT EXISTS pact_triggered_webhook (",
    "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE",
    # Secrets: ciphertext and key version together, and named.
    "secret_ciphertext BYTEA",
    "CHECK ((secret_ciphertext IS NULL) = (key_version IS NULL))",
    "CHECK ((cardinality(secret_fields) = 0) = (secret_ciphertext IS NULL))",
    # Where a webhook may go, as far as the database can say.
    "CHECK (request_url ~* '^https?://[^[:space:]]+$' AND length(request_url) <= 2048)",
    # Nothing crosses a tenant.
    "CONSTRAINT pact_webhook_id_tenant_key UNIQUE (id, tenant_id)",
    "FOREIGN KEY (consumer_id, tenant_id)",
    "FOREIGN KEY (provider_id, tenant_id)",
    "REFERENCES pacticipant (id, tenant_id) ON DELETE CASCADE",
    "FOREIGN KEY (webhook_id, tenant_id)",
    "REFERENCES pact_webhook (id, tenant_id) ON DELETE CASCADE",
    # A firing is a queued delivery of the shared worker, and goes with its webhook.
    "ADD COLUMN IF NOT EXISTS pact_webhook_id UUID REFERENCES pact_webhook(id) ON DELETE CASCADE",
    "REFERENCES push_webhook_delivery_events(id) ON DELETE CASCADE",
    "CONSTRAINT pact_triggered_webhook_delivery_key UNIQUE (delivery_event_id)",
    # The per-attempt execution log.
    "ADD COLUMN IF NOT EXISTS execution_log TEXT",
    # Every reference that cascades is indexed (V418's rule).
    "CREATE INDEX IF NOT EXISTS idx_push_webhook_delivery_events_pact_webhook",
    "CREATE INDEX IF NOT EXISTS idx_pact_triggered_webhook_pair",
    "CREATE INDEX IF NOT EXISTS idx_pact_triggered_webhook_webhook",
    "CREATE INDEX IF NOT EXISTS idx_pact_triggered_webhook_consumer",
    "CREATE INDEX IF NOT EXISTS idx_pact_webhook_consumer",
    "CREATE INDEX IF NOT EXISTS idx_pact_webhook_provider",
)


@pytest.fixture
def migration(repo_root: Path) -> str:
    """The migration's text."""
    return (repo_root / _MIGRATION).read_text()


def test_migration_declares_the_webhook_rules(migration: str) -> None:
    missing = [fragment for fragment in _REQUIRED_FRAGMENTS if fragment not in migration]
    assert not missing, f"Migration missing expected fragments: {missing}"


def _event_list(sql: str) -> list:
    """The event names of the last ``pact_webhook_events_check`` a migration declares."""
    block = sql.split("pact_webhook_events_check")[-1].split("]::text[]")[0]
    return sorted(part.strip(" '\n") for part in block.split("ARRAY[")[1].split(","))


def test_the_event_list_was_the_broker_seven_and_v448_matches_the_code(migration: str, repo_root: Path) -> None:
    """V436 declared the Pact Broker's six plus the branch event; V448 (PFX-6.2) widened it to the code's."""
    original = _event_list(migration)
    assert len(original) == 7 and set(original) <= set(EVENT_NAMES)
    widened = (repo_root / "apiome-db/scripts/V448__pact_stale_remediation_6954.sql").read_text()
    assert _event_list(widened) == sorted(EVENT_NAMES)


def test_the_methods_and_target_kinds_match_the_code(migration: str) -> None:
    methods = ", ".join(f"'{method}'" for method in METHODS)
    assert f"CHECK (request_method IN ({methods}))" in migration
    assert f"CHECK (target_kind IN ('{TARGET_HTTP}', '{TARGET_GITHUB}'))" in migration


def test_no_column_could_hold_a_secret_in_the_clear(migration: str) -> None:
    table = migration.split("CREATE TABLE IF NOT EXISTS pact_webhook (")[1].split(");")[0]
    for column in ("password", "signing_secret", "token"):
        assert f"\n    {column} " not in table and f"request_{column} " not in table
