"""Guardrails for the merge-request migration — COL-4.3 (#4527).

V377 adds ``version_branches.draft_of_branch_id`` and ``merge_requests``. Each fragment pins a
promise the REST layer relies on; compared against the SQL with ``--`` comments removed, so prose
cannot satisfy it.
"""

from pathlib import Path

_MIGRATION = "apiome-db/scripts/V377__merge_requests_col_4_3.sql"

_REQUIRED_FRAGMENTS = (
    "ADD COLUMN IF NOT EXISTS draft_of_branch_id UUID REFERENCES version_branches(id) ON DELETE SET NULL",
    "CREATE TABLE IF NOT EXISTS merge_requests (",
    "source_branch_id UUID REFERENCES version_branches(id) ON DELETE SET NULL",
    "target_branch_id UUID REFERENCES version_branches(id) ON DELETE SET NULL",
    "review_id UUID REFERENCES reviews(id) ON DELETE SET NULL",
    "merge_session_id UUID REFERENCES merge_sessions(id) ON DELETE SET NULL",
    "merged_version_id UUID REFERENCES versions(id) ON DELETE SET NULL",
    "CHECK (state IN ('open', 'merged', 'closed'))",
    "CHECK (source_branch_name <> target_branch_name)",
    "CHECK ((state = 'merged') = (merged_at IS NOT NULL))",
    "CHECK ((state = 'closed') = (closed_at IS NOT NULL))",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_merge_requests_open_source_branch "
    "ON merge_requests (source_branch_id) WHERE state = 'open'",
    "ON merge_requests (project_id, state, updated_at DESC)",
)


def test_migration_keeps_its_promises():
    root = Path(__file__).resolve().parents[2]
    sql = " ".join(line.split("--", 1)[0] for line in (root / _MIGRATION).read_text().splitlines())
    sql = " ".join(sql.split())
    missing = [f for f in _REQUIRED_FRAGMENTS if " ".join(f.split()) not in sql]
    assert not missing, missing
