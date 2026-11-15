"""Guardrails for the portal reader identity migration — PCX-1.1 (#5889).

V378 adds ``portal_memberships``, ``portal_magic_links`` and ``portal_reader_sessions``. Each
fragment below pins a promise :mod:`app.portal_auth_store` relies on — one membership per tenant and
user, hashed secrets only, burn-once tokens, revocation stamps — and the vocabularies must match
:mod:`app.portal_auth`. The comparison runs against the SQL with ``--`` comments removed, so prose
cannot satisfy it. The apiome-db sibling is ``test/portal-reader-identity.test.ts``.
"""

from pathlib import Path

_MIGRATION = "apiome-db/scripts/V378__portal_reader_identity_pcx_1_1.sql"

_REQUIRED_FRAGMENTS = (
    "CREATE TABLE IF NOT EXISTS portal_memberships (",
    "CREATE TABLE IF NOT EXISTS portal_magic_links (",
    "CREATE TABLE IF NOT EXISTS portal_reader_sessions (",
    "user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE",
    "CONSTRAINT portal_memberships_tenant_user_unique UNIQUE (tenant_id, user_id)",
    "CHECK ((status = 'revoked') = (revoked_at IS NOT NULL))",
    "CONSTRAINT portal_magic_links_lookup_prefix_unique UNIQUE",
    "consumed_at TIMESTAMP WITH TIME ZONE",
    "expires_at TIMESTAMP WITH TIME ZONE NOT NULL",
    "token_hash CHAR(64) NOT NULL",
    "CONSTRAINT portal_reader_sessions_token_hash_unique UNIQUE",
    "user_agent_family VARCHAR(32)",
)

#: A reader membership is not a workspace membership and adds no RBAC.
_FORBIDDEN_FRAGMENTS = ("tenant_users", "role_permissions", "CREATE TYPE")


def _statements() -> str:
    """The migration's executable text, ``--`` comments removed, read from the repository root."""
    root = Path(__file__).resolve().parents[2]
    sql = (root / _MIGRATION).read_text(encoding="utf-8")
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def test_migration_keeps_every_structural_promise():
    statements = _statements()
    missing = [fragment for fragment in _REQUIRED_FRAGMENTS if fragment not in statements]
    assert not missing, f"V378 no longer keeps: {missing}"


def test_migration_grants_no_workspace_access():
    statements = _statements()
    present = [fragment for fragment in _FORBIDDEN_FRAGMENTS if fragment in statements]
    assert not present, f"V378 took on a second job: {present}"


def test_vocabularies_match_the_rest_models():
    from app.portal_auth import MEMBERSHIP_ACTIVE, MEMBERSHIP_INVITED, MEMBERSHIP_REVOKED, SOURCE_MAGIC_LINK

    statements = _statements()
    assert (
        f"CHECK (status IN ('{MEMBERSHIP_INVITED}', '{MEMBERSHIP_ACTIVE}', '{MEMBERSHIP_REVOKED}'))"
        in statements
    )
    assert f"'{SOURCE_MAGIC_LINK}'" in statements


def test_the_migration_version_is_unique():
    scripts = Path(__file__).resolve().parents[2] / "apiome-db" / "scripts"
    versions = [path.name.split("__", 1)[0] for path in scripts.glob("V*__*.sql")]
    assert versions.count("V378") == 1


def test_the_sql_repository_only_verifies_password_less_accounts():
    """Pre-hijacking guard (security review): the verify UPDATE must exclude accounts holding a password."""
    import inspect

    from app.portal_auth_store import SqlPortalAuthRepository

    source = inspect.getsource(SqlPortalAuthRepository.mark_user_verified)
    assert "COALESCE(u.password, '') = ''" in source
    assert 'a."providerId" = \'credential\'' in source
    assert "COALESCE(a.password, '') <> ''" in source
