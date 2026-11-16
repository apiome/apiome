"""Guardrails for the probe consent migration — ASP-4.1 (#5939).

V386 is where the consent rules stop being habits and become things the database keeps. Each
fragment pins one, so an edit that relaxes it fails here:

* a consent declares ownership, has an approver and an expiry after its approval;
* identities carry the same secret-free CHECKs V211 puts on ``verification_target`` — an ``env`` ref
  is a variable NAME, a ``stored`` ref a UUID — so a pasted token cannot be stored;
* one live consent per target, and a consent is revoked, never edited;
* both tables are tenant-consistent through composite keys;
* a report is write-once, the hosted mock is capped at ``observed``, and only the mock runs without a
  consent;
* write-once rows hold soft references (an ON DELETE SET NULL would be an UPDATE the guard rejects).

There is also a **negative** assertion: no new RBAC resource (``seed_builtin_roles`` is untouched).
"""

from pathlib import Path

_MIGRATION = "apiome-db/scripts/V386__probe_consents_asp_4_1.sql"

_REQUIRED_FRAGMENTS = (
    "ADD CONSTRAINT verification_target_id_tenant_key UNIQUE (id, tenant_id)",
    "CREATE TABLE IF NOT EXISTS verification_target_probe_consents (",
    "CHECK (ownership_declared)",
    "approved_by UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE",
    "expires_at TIMESTAMPTZ NOT NULL",
    "CHECK (expires_at > approved_at)",
    "profiles_allowed <@ ARRAY['passive', 'safe-active', 'payload']::TEXT[]",
    # V211's secret-free reference shapes, for both identities.
    "CHECK (identity_a_kind IS DISTINCT FROM 'env' OR identity_a_ref ~ '^[A-Z_][A-Z0-9_]*$')",
    "CHECK (identity_b_kind IS DISTINCT FROM 'env' OR identity_b_ref ~ '^[A-Z_][A-Z0-9_]*$')",
    "OR identity_a_ref ~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'",
    "OR identity_b_ref ~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'",
    "REFERENCES verification_target (id, tenant_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_verification_target_probe_consents_live",
    "WHERE revoked_at IS NULL;",
    "CREATE TRIGGER trigger_verification_target_probe_consents_guard",
    "may only be revoked, never edited",
    "CREATE TABLE IF NOT EXISTS security_probe_reports (",
    "CHECK (proof_ceiling IN ('observed', 'exploited-in-test'))",
    "CHECK (NOT hosted_mock OR proof_ceiling = 'observed')",
    "CHECK (hosted_mock OR consent_id IS NOT NULL)",
    "CHECK (proof_ceiling = 'exploited-in-test' OR count_exploited_in_test = 0)",
    "REFERENCES verification_run (id, tenant_id)",
    "CREATE TRIGGER trigger_security_probe_reports_immutable",
    "BEFORE UPDATE ON security_probe_reports",
    "EXECUTE FUNCTION mcp_forbid_row_mutation();",
    "CREATE OR REPLACE FUNCTION purge_security_probe_reports",
)

_FORBIDDEN_FRAGMENTS = (
    "seed_builtin_roles",
    "revoked_by UUID REFERENCES",
    "consent_id UUID REFERENCES",
    "ON DELETE SET NULL",
)


def _migration_text() -> str:
    """The migration's SQL, read from the repository root."""
    root = Path(__file__).resolve().parents[2]
    return (root / _MIGRATION).read_text(encoding="utf-8")


def test_the_migration_keeps_every_consent_and_report_rule() -> None:
    text = _migration_text()
    missing = [fragment for fragment in _REQUIRED_FRAGMENTS if fragment not in text]
    assert missing == []


def test_the_migration_adds_no_rbac_resource_and_no_set_null_on_guarded_rows() -> None:
    text = _migration_text()
    sql = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("--"))
    present = [fragment for fragment in _FORBIDDEN_FRAGMENTS if fragment in sql]
    assert present == []


def test_the_migration_version_is_not_shared() -> None:
    scripts = Path(__file__).resolve().parents[2] / "apiome-db" / "scripts"
    v386 = [p.name for p in scripts.glob("V386__*.sql")]
    assert v386 == ["V386__probe_consents_asp_4_1.sql"]
