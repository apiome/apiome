"""Guardrails for the upstream auth vault migration — AGX-2.2 (#4534).

V268 adds ``upstream_credentials`` (the sealed secret a toolset presents upstream) and
``upstream_credential_uses`` (the metadata-only use ledger). Each fragment below pins a structural
promise so a later edit that relaxes it fails here rather than in production:

* ``encrypted_secret BYTEA`` plus ``key_version``: "encrypted at rest" is a *schema* fact, and
  there is no column a plaintext secret could be written to.
* The server-URL CHECK: https-only, no userinfo, query or fragment, so a binding can't be
  stored that the application would refuse.
* The placement CHECK: ``in``/``name`` exist exactly for ``apiKey``, and the name keeps to the RFC
  9110 token grammar.
* One credential per (tenant, toolset, server URL).
* The use ledger is write-once, has no secret column, and outlives its credential (no FK on
  ``credential_id``).

Two **negative** assertions as well: the migration seeds no RBAC resource (the API reuses
``api_keys``), and ``toolset_id`` has no foreign key yet (``agent_toolsets`` is AGX-1.2, #4530).
"""

import re
from pathlib import Path

_MIGRATION = "apiome-db/scripts/V268__upstream_credentials_agx_2_2.sql"

_REQUIRED_FRAGMENTS = (
    "CREATE TABLE IF NOT EXISTS upstream_credentials (",
    "CREATE TABLE IF NOT EXISTS upstream_credential_uses (",
    "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE",
    # Rule 1: ciphertext only, and the key that sealed it.
    "encrypted_secret BYTEA NOT NULL",
    "key_version INTEGER NOT NULL",
    "CHECK (key_version >= 1)",
    # Rule 2: the binding, its shape, and its uniqueness.
    "toolset_id UUID NOT NULL,",
    "server_url TEXT NOT NULL",
    "CHECK (server_url ~ '^https://[^/?#@[:space:]]+(/[^?#[:space:]]*)?$')",
    "CHECK (char_length(server_url) <= 2048)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_upstream_credentials_binding",
    "ON upstream_credentials (tenant_id, toolset_id, server_url)",
    # Rule 3: the kinds, and the placement only an apiKey has.
    "CHECK (kind IN ('apiKey', 'bearer', 'basic'))",
    "AND api_key_in IN ('header', 'query')",
    "AND api_key_name ~ '^[!#$%&''*+.^_`|~0-9A-Za-z-]+$'",
    "OR (kind <> 'apiKey' AND api_key_in IS NULL AND api_key_name IS NULL)",
    # Rule 4: rotation is tracked on the row.
    "rotated_at TIMESTAMPTZ",
    "rotated_by UUID REFERENCES users(id) ON DELETE SET NULL",
    # Rule 5: the use ledger — metadata only, write-once, bounded.
    "credential_id UUID NOT NULL,",
    "CHECK (outcome IN ('injected', 'unavailable'))",
    "CREATE INDEX IF NOT EXISTS idx_upstream_credential_uses_credential",
    "ON upstream_credential_uses (credential_id, used_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_upstream_credential_uses_tenant",
    "BEFORE UPDATE ON upstream_credential_uses",
    "EXECUTE FUNCTION mcp_forbid_row_mutation()",
    "CREATE OR REPLACE FUNCTION purge_upstream_credential_uses(p_retention_days INTEGER DEFAULT 90)",
)


def _sql(repo_root: Path) -> str:
    return (repo_root / _MIGRATION).read_text(encoding="utf-8")


def _ddl(repo_root: Path) -> str:
    """The migration's statements only: ``--`` comments and ``COMMENT ON`` prose removed.

    The negative assertions below are about columns, and the prose that explains the design
    naturally mentions the words they look for ("no plaintext column", "never a secret").
    """
    sql = re.sub(r"--[^\n]*", "", _sql(repo_root))
    return re.sub(r"COMMENT ON .*?;", "", sql, flags=re.DOTALL)


def test_migration_carries_every_structural_promise(repo_root: Path) -> None:
    sql = _sql(repo_root)
    missing = [fragment for fragment in _REQUIRED_FRAGMENTS if fragment not in sql]
    assert missing == []


def test_no_column_could_hold_a_plaintext_secret(repo_root: Path) -> None:
    lowered = _ddl(repo_root).lower()
    for column in (
        "secret text",
        "secret varchar",
        "token text",
        "password text",
        "username text",
        "plaintext",
        "secret_metadata",
        "fingerprint",
    ):
        assert column not in lowered, column


def test_the_use_ledger_has_no_request_or_secret_columns(repo_root: Path) -> None:
    sql = _ddl(repo_root)
    uses = sql[sql.index("CREATE TABLE IF NOT EXISTS upstream_credential_uses") :]
    uses = uses[: uses.index(");")]
    for column in ("encrypted", "secret", "url", "header", "body", "detail"):
        assert column not in uses.lower(), column


def test_toolset_and_credential_ids_have_no_foreign_key_yet(repo_root: Path) -> None:
    sql = _ddl(repo_root)
    assert "REFERENCES agent_toolsets" not in sql
    assert "credential_id UUID NOT NULL REFERENCES" not in sql
    assert "toolset_id UUID NOT NULL REFERENCES" not in sql


def test_no_new_rbac_resource(repo_root: Path) -> None:
    lowered = _ddl(repo_root).lower()
    assert "seed_builtin_roles" not in lowered
    assert "role_permissions" not in lowered
