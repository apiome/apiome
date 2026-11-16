"""Guardrails for the stored overlay chain migration — GVM-4.3 (#5878).

V385 adds ``version_overlays`` and ``version_overlay_renders``. Each fragment pins a structural
promise, so a later edit that relaxes it fails here rather than in production:

* rows are write-once (an UPDATE trigger refuses every update);
* one overlay per position per revision, deferrable so positions can be compacted in one transaction;
* the chain and its render go with their revision (``ON DELETE CASCADE``);
* the ``source`` vocabulary matches the application.
"""

from pathlib import Path

from app.version_overlay_chain import OVERLAY_SOURCES

_MIGRATION = "apiome-db/scripts/V385__version_overlays_gvm_4_3.sql"

_REQUIRED_FRAGMENTS = (
    "CREATE TABLE IF NOT EXISTS version_overlays (",
    "version_record_id UUID NOT NULL REFERENCES versions(id) ON DELETE CASCADE",
    "position INTEGER NOT NULL CHECK (position >= 0)",
    "document JSONB NOT NULL CHECK (jsonb_typeof(document) = 'object')",
    "content_fingerprint VARCHAR(71) NOT NULL CHECK (content_fingerprint LIKE 'sha256:%')",
    "CONSTRAINT version_overlays_position_uq UNIQUE (version_record_id, position)",
    "DEFERRABLE INITIALLY IMMEDIATE",
    "BEFORE UPDATE ON version_overlays",
    "CREATE TABLE IF NOT EXISTS version_overlay_renders (",
    "version_record_id UUID PRIMARY KEY REFERENCES versions(id) ON DELETE CASCADE",
    "source_fingerprint VARCHAR(71) NOT NULL",
    "resolved_fingerprint VARCHAR(71) NOT NULL",
)


def _migration_sql() -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / _MIGRATION).read_text(encoding="utf-8")


def test_v385_pins_the_write_once_and_ordering_rules():
    sql = _migration_sql()
    missing = [fragment for fragment in _REQUIRED_FRAGMENTS if fragment not in sql]
    assert missing == []


def test_v385_is_the_only_migration_with_its_version():
    scripts = Path(__file__).resolve().parents[2] / "apiome-db" / "scripts"
    assert [path.name for path in scripts.glob("V385__*.sql")] == [Path(_MIGRATION).name]


def test_sources_match_the_application():
    sql = _migration_sql()
    expected = ", ".join(f"'{source}'" for source in OVERLAY_SOURCES)
    assert f"CHECK (source IN ({expected}))" in sql


def test_the_store_defers_the_position_constraint_it_declares():
    store = (Path(__file__).resolve().parents[1] / "src" / "app" / "version_overlay_store.py").read_text()
    assert "SET CONSTRAINTS apiome.version_overlays_position_uq DEFERRED" in store
