"""Guardrails for the issuer-aware provider vocabulary migration (V198, OLO-9.1, #4984).

DB-free: asserts the migration widens both controlled provider vocabularies — the OLO-2.2 identity
vocabulary (``external_auth_providers.provider``) and the OLO-8.2 config vocabulary
(``auth_provider_config.provider_id``) — to accept the OLO-9.3–9.7 issuer-based provider slugs
ahead of their launch, so those tickets need no migration of their own. The existing slugs must
remain accepted (no identity or config row is invalidated).
"""

from pathlib import Path

import pytest

_MIGRATION = "V198__auth_provider_vocabulary_4984.sql"

# Slugs already accepted before this migration (V010/V181 identity + V196 config) that must survive.
_EXISTING_SLUGS = ("github", "gitlab", "azure", "google", "aws")
# The upcoming issuer-based providers this migration must newly admit (issue scope).
_UPCOMING_SLUGS = ("okta", "keycloak", "auth0", "oidc", "atlassian", "bitbucket")


@pytest.fixture
def migration_text(repo_root: Path) -> str:
    path = repo_root / "apiome-db" / "scripts" / _MIGRATION
    assert path.exists(), f"Migration {_MIGRATION} not found at {path}"
    return path.read_text()


def test_widens_both_provider_check_constraints(migration_text: str) -> None:
    """Both provider CHECK constraints are re-created (idempotently) by the migration."""
    # Identity vocabulary (external_auth_providers.provider, V181 CHECK).
    assert "DROP CONSTRAINT IF EXISTS external_auth_providers_provider_supported_ck" in migration_text
    assert "ADD CONSTRAINT external_auth_providers_provider_supported_ck" in migration_text
    # Config vocabulary (auth_provider_config.provider_id, V196 CHECK).
    assert "DROP CONSTRAINT IF EXISTS auth_provider_config_provider_id_check" in migration_text
    assert "ADD CONSTRAINT auth_provider_config_provider_id_check" in migration_text


def test_accepts_existing_and_upcoming_slugs(migration_text: str) -> None:
    """Every existing slug stays accepted and each upcoming issuer-based slug is admitted."""
    for slug in _EXISTING_SLUGS + _UPCOMING_SLUGS:
        assert f"'{slug}'" in migration_text, f"vocabulary migration omits slug {slug!r}"
