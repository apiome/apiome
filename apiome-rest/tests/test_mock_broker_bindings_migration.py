"""Guardrails for the mock broker bindings migration — XPC-2.1 (#5735).

V372 adds ``mock_broker_bindings``. Each fragment pins a structural promise so a later edit that
relaxes it fails here rather than in production:

* ``credential_ciphertext BYTEA`` plus ``key_version``, and a CHECK that keeps them together with
  ``sasl_mechanism``: "encrypted at rest" is a schema fact, and there is no plaintext column.
* The bootstrap is a bounded, shape-checked ``host:port`` list; the protocol and mechanism lists
  match the application's.
* One binding per (version, protocol); deleting the version or the tenant deletes its bindings.

And negatively: no new RBAC resource (the API reuses ``versions``), no plaintext column.
"""

import re
from pathlib import Path

_MIGRATION = "apiome-db/scripts/V372__mock_broker_bindings_xpc_2_1.sql"

_REQUIRED_FRAGMENTS = (
    "SET search_path TO apiome, public;",
    "CREATE TABLE IF NOT EXISTS mock_broker_bindings (",
    "id UUID PRIMARY KEY DEFAULT uuid_generate_v4()",
    "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE",
    "version_id UUID NOT NULL REFERENCES versions(id) ON DELETE CASCADE",
    "CHECK (protocol IN ('kafka', 'mqtt', 'amqp'))",
    "bootstrap TEXT[] NOT NULL",
    "CHECK (cardinality(bootstrap) BETWEEN 1 AND 16)",
    "tls_enabled BOOLEAN NOT NULL DEFAULT false",
    "tls_verify BOOLEAN NOT NULL DEFAULT true",
    "CHECK (sasl_mechanism IN ('PLAIN', 'SCRAM-SHA-256', 'SCRAM-SHA-512'))",
    "credential_ciphertext BYTEA,",
    "CHECK (key_version >= 1)",
    "(sasl_mechanism IS NULL AND credential_ciphertext IS NULL AND key_version IS NULL)",
    "client_id_prefix VARCHAR(64) NOT NULL DEFAULT 'apiome-mock'",
    "rotated_by UUID REFERENCES users(id) ON DELETE SET NULL",
    "rotated_at TIMESTAMPTZ",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_mock_broker_bindings_version_protocol",
    "ON mock_broker_bindings (version_id, protocol)",
)


def _sql(repo_root: Path) -> str:
    return (repo_root / _MIGRATION).read_text(encoding="utf-8")


def _ddl(repo_root: Path) -> str:
    """The migration's statements only: comments and ``COMMENT ON`` prose removed."""
    sql = re.sub(r"--[^\n]*", "", _sql(repo_root))
    return re.sub(r"COMMENT ON .*?;", "", sql, flags=re.DOTALL)


def test_migration_carries_every_structural_promise(repo_root: Path) -> None:
    sql = _sql(repo_root)
    assert [fragment for fragment in _REQUIRED_FRAGMENTS if fragment not in sql] == []


def test_no_column_could_hold_a_plaintext_credential(repo_root: Path) -> None:
    lowered = _ddl(repo_root).lower()
    for column in ("password", "username", "secret", "plaintext", "fingerprint", "token"):
        assert column not in lowered, column


def test_the_lists_match_the_application(repo_root: Path) -> None:
    from app.mock_broker_bindings import PROTOCOL_KAFKA, PROTOCOLS_RESERVED, SASL_MECHANISMS

    sql = _sql(repo_root)
    protocols = ", ".join(f"'{p}'" for p in (PROTOCOL_KAFKA, *PROTOCOLS_RESERVED))
    assert f"CHECK (protocol IN ({protocols}))" in sql
    mechanisms = ", ".join(f"'{m}'" for m in SASL_MECHANISMS)
    assert f"CHECK (sasl_mechanism IN ({mechanisms}))" in sql


def test_no_new_rbac_resource(repo_root: Path) -> None:
    lowered = _ddl(repo_root).lower()
    assert "role_permissions" not in lowered
    assert "seed_builtin_roles" not in lowered
