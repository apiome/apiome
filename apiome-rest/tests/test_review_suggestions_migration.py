"""Guardrails for the suggested-changes migration — COL-4.2 (#4526).

V376 adds ``review_suggestions``. Each fragment pins a promise the REST layer relies on; compared
against the SQL with ``--`` comments removed, so prose cannot satisfy it.
"""

from pathlib import Path

_MIGRATION = "apiome-db/scripts/V376__review_suggestions_col_4_2.sql"

_REQUIRED_FRAGMENTS = (
    "CREATE TABLE IF NOT EXISTS review_suggestions (",
    "review_id UUID NOT NULL REFERENCES reviews(id) ON DELETE CASCADE",
    "version_id UUID NOT NULL REFERENCES versions(id) ON DELETE CASCADE",
    "author_id UUID REFERENCES users(id) ON DELETE SET NULL",
    "CHECK (target_type IN ('class', 'property'))",
    "base JSONB NOT NULL",
    "proposed JSONB NOT NULL",
    "jsonb_typeof(patch) = 'array' AND jsonb_array_length(patch) BETWEEN 1 AND 50",
    "CHECK (status IN ('open', 'applied', 'rejected', 'stale'))",
    "CHECK ((status = 'open') = (decided_at IS NULL))",
    "conflict_paths TEXT[] NOT NULL",
    "ON review_suggestions (review_id, status, created_at)",
)


def test_migration_keeps_its_promises():
    root = Path(__file__).resolve().parents[2]
    sql = " ".join(line.split("--", 1)[0] for line in (root / _MIGRATION).read_text().splitlines())
    sql = " ".join(sql.split())
    missing = [f for f in _REQUIRED_FRAGMENTS if " ".join(f.split()) not in sql]
    assert not missing, missing
