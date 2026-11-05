"""Guardrails for the export object-storage delivery migration — MFX-38.3 (#4330).

V356 adds the bucket credential vault and the record of every object-storage delivery. Each fragment below
pins a structural promise, so a later edit that relaxes it fails here rather than in production:

* **The only secret column is sealed** — ``encrypted_payload BYTEA`` in the credential table; the run table
  has no column that could hold a key.
* **Credentials are tenant-scoped and uniquely named**, and deleting one keeps its runs.
* **A stored prefix cannot climb out with ``..``**, and every outcome is a status.
"""

from pathlib import Path

_MIGRATION = "apiome-db/scripts/V356__export_object_storage_delivery_4330.sql"

_REQUIRED_FRAGMENTS = (
    "CREATE TABLE IF NOT EXISTS export_storage_credentials (",
    "CREATE TABLE IF NOT EXISTS export_object_storage_delivery_runs (",
    "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE",
    "encrypted_payload BYTEA NOT NULL",
    "access_key_hint VARCHAR(4) NOT NULL",
    "CONSTRAINT export_storage_credentials_name_unique UNIQUE (tenant_id, name)",
    "CHECK (endpoint_url IS NULL OR endpoint_url ~* '^https?://')",
    "credential_id UUID REFERENCES export_storage_credentials(id) ON DELETE SET NULL",
    "key_prefix !~ '(^|/)\\.\\.?(/|$)'",
    "CHECK (status IN ('in_progress', 'delivered', 'failed'))",
    "objects JSONB NOT NULL DEFAULT '[]'::jsonb",
    "manifest_sha256 VARCHAR(64)",
    "CREATE INDEX IF NOT EXISTS idx_export_object_storage_delivery_runs_job",
    "-- Rollback notes",
)


def _migration_text() -> str:
    return (Path(__file__).resolve().parents[2] / _MIGRATION).read_text(encoding="utf-8")


def _columns(table: str) -> list:
    text = _migration_text()
    body = text.split(f"CREATE TABLE IF NOT EXISTS {table} (", 1)[1].split("\n);", 1)[0]
    return [line.strip().split()[0].lower() for line in body.splitlines()
            if line.startswith("    ") and not line.strip().startswith(("--", "CONSTRAINT", "CHECK", "AND", "ON"))]


def test_the_migration_carries_every_structural_promise() -> None:
    text = _migration_text()
    missing = [fragment for fragment in _REQUIRED_FRAGMENTS if fragment not in text]
    assert missing == []


def test_only_the_sealed_payload_could_hold_a_secret() -> None:
    words = ("token", "secret", "password", "access_key_id")
    assert not [c for c in _columns("export_object_storage_delivery_runs") if any(w in c for w in words)]
    assert [c for c in _columns("export_storage_credentials") if any(w in c for w in words)] == []
    assert "encrypted_payload" in _columns("export_storage_credentials")


def test_the_pipeline_s_statuses_match_the_check() -> None:
    from app.export_object_storage_delivery_pipeline import RUN_STATUSES

    text = _migration_text()
    assert all(f"'{status}'" in text for status in RUN_STATUSES)
