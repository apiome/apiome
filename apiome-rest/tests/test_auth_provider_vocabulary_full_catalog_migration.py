"""Guardrails for the full-catalog provider vocabulary widen (V395, OLO-9.16, #5029).

DB-free: asserts the migration re-creates both provider CHECK constraints idempotently, admits
every Better Auth catalog slug the OLO-9.17–9.49 provider tickets need, keeps every slug accepted
before it (so no identity or config row is invalidated), and keeps the enterprise SSO identity
kind that V312 added to the identity CHECK.
"""

import re
from pathlib import Path

import pytest

_MIGRATION = "V395__auth_provider_vocabulary_full_catalog_5029.sql"

_IDENTITY_CHECK = "external_auth_providers_provider_supported_ck"
_CONFIG_CHECK = "auth_provider_config_provider_id_check"

# Slugs accepted before this migration (V198, V202–V204) that must survive.
_PRIOR_SLUGS = (
    "github",
    "gitlab",
    "azure",
    "google",
    "aws",
    "gcp",
    "bitbucket",
    "okta",
    "keycloak",
    "auth0",
    "oidc",
    "atlassian",
    "line",
    "vk",
    "wechat",
)

# The 30 remaining Better Auth catalog slugs this migration newly admits (OLO-9.17–9.49, less
# line / vk / wechat, which shipped with their own migrations).
_CATALOG_SLUGS = (
    "slack",
    "linkedin",
    "discord",
    "salesforce",
    "notion",
    "figma",
    "linear",
    "dropbox",
    "zoom",
    "huggingface",
    "vercel",
    "railway",
    "hubspot",
    "apple",
    "facebook",
    "twitter",
    "reddit",
    "spotify",
    "twitch",
    "tiktok",
    "roblox",
    "kick",
    "kakao",
    "naver",
    "yandex",
    "paypal",
    "polar",
    "patreon",
    "gumroad",
    "paybin",
)


@pytest.fixture
def migration_text(repo_root: Path) -> str:
    """The migration's SQL text."""
    path = repo_root / "apiome-db" / "scripts" / _MIGRATION
    assert path.exists(), f"Migration {_MIGRATION} not found at {path}"
    return path.read_text()


def _check_block(sql: str, constraint: str) -> str:
    """Return the ``ADD CONSTRAINT <constraint> … ;`` statement from the migration."""
    start = sql.index(f"ADD CONSTRAINT {constraint}")
    return sql[start : sql.index(";", start)]


def _vocabulary(sql: str, constraint: str) -> list[str]:
    """Return the slugs a constraint's ``IN (…)`` list admits, in file order."""
    return re.findall(r"'([a-z0-9_]+)'", _check_block(sql, constraint))


def test_widens_both_provider_check_constraints_idempotently(migration_text: str) -> None:
    """Each CHECK is dropped if present and re-added, so a second run is a no-op."""
    for constraint in (_IDENTITY_CHECK, _CONFIG_CHECK):
        drop = migration_text.index(f"DROP CONSTRAINT IF EXISTS {constraint}")
        add = migration_text.index(f"ADD CONSTRAINT {constraint}")
        assert drop < add, f"{constraint} must be dropped before it is re-added"
        assert migration_text.count(f"ADD CONSTRAINT {constraint}") == 1


@pytest.mark.parametrize("constraint", [_IDENTITY_CHECK, _CONFIG_CHECK])
def test_admits_the_full_catalog_and_keeps_prior_slugs(migration_text: str, constraint: str) -> None:
    """Both vocabularies are exactly the prior slugs plus the 30 catalog slugs, with no repeats."""
    slugs = _vocabulary(migration_text, constraint)
    assert len(slugs) == len(set(slugs)), f"{constraint} lists a slug twice"
    assert set(slugs) == set(_PRIOR_SLUGS) | set(_CATALOG_SLUGS)


def test_both_vocabularies_are_the_same_set(migration_text: str) -> None:
    """A provider that can store config can store an identity, and the reverse."""
    assert _vocabulary(migration_text, _IDENTITY_CHECK) == _vocabulary(migration_text, _CONFIG_CHECK)


def test_identity_check_keeps_the_sso_identity_kind(migration_text: str) -> None:
    """V312's ``sso:<slug>`` identity kind survives; the config table never accepts it."""
    pattern = "OR provider ~ '^sso:[a-z0-9][a-z0-9-]{1,27}$'"
    assert pattern in _check_block(migration_text, _IDENTITY_CHECK)
    assert "sso:" not in _check_block(migration_text, _CONFIG_CHECK)


def test_slugs_fit_the_identity_and_config_columns(migration_text: str) -> None:
    """Slugs are short lowercase ids — Better Auth's own provider ids."""
    for slug in _vocabulary(migration_text, _IDENTITY_CHECK):
        assert re.fullmatch(r"[a-z0-9]{2,32}", slug), slug
