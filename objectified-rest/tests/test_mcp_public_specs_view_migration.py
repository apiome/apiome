"""Guardrails for MCP public specs view migration and dev fixture (#3004)."""

import os
import re
from pathlib import Path

import pytest

_MIGRATION_FRAGMENTS = (
    "CREATE OR REPLACE VIEW odb.mcp_v_public_specs",
    "p.name AS title",
    "v.version_id AS version",
    "AS tags",
    "FROM odb.versions v",
    "INNER JOIN odb.projects p",
    "version_tags",
    "v.published IS TRUE",
    "v.visibility = 'public'::odb.visibility_type",
    "COMMENT ON VIEW odb.mcp_v_public_specs",
    "COMMENT ON COLUMN odb.mcp_v_public_specs.tags",
    # cross-project tag guard (reviewer feedback)
    "vt.project_id = v.project_id",
    # composite freshness cursor (reviewer feedback)
    "GREATEST",
    "p.updated_at",
)

_FIXTURE_FRAGMENTS = (
    "Dev fixture for odb.mcp_v_public_specs",
    "SELECT count(*) FROM odb.mcp_v_public_specs",
    "00000000-0000-4000-8000-000000000004",
    "INSERT INTO odb.version_tags",
)


def test_migration_defines_mcp_v_public_specs(repo_root: Path) -> None:
    migration = repo_root / "objectified-db" / "scripts" / "V095__mcp_read_model_published_public_schema_r.sql"
    text = migration.read_text()
    missing = [frag for frag in _MIGRATION_FRAGMENTS if frag not in text]
    assert not missing, f"Migration missing expected fragments: {missing}"


def test_migration_tag_subquery_guards_project_id(repo_root: Path) -> None:
    """Tag subquery must filter by both version_id and project_id to avoid cross-project contamination."""
    migration = repo_root / "objectified-db" / "scripts" / "V095__mcp_read_model_published_public_schema_r.sql"
    text = migration.read_text()
    # The WHERE clause inside the lateral must reference project_id scoped to the outer versions alias
    assert re.search(r"vt\.project_id\s*=\s*v\.project_id", text), (
        "Tag subquery must include 'vt.project_id = v.project_id' to prevent cross-project tag associations"
    )


def test_migration_updated_at_is_composite_freshness_cursor(repo_root: Path) -> None:
    """updated_at must advance on project renames and tag mutations, not just revision edits."""
    migration = repo_root / "objectified-db" / "scripts" / "V095__mcp_read_model_published_public_schema_r.sql"
    text = migration.read_text()
    assert re.search(r"GREATEST\s*\(", text, re.IGNORECASE), (
        "updated_at must use GREATEST(...) to combine updated_at from versions, projects, and version_tags"
    )
    assert "p.updated_at" in text, (
        "updated_at must include p.updated_at so project renames advance the freshness cursor"
    )


def test_dev_fixture_documents_public_specs_view(repo_root: Path) -> None:
    fixture = repo_root / "objectified-db" / "fixtures" / "mcp_public_specs_dev.sql"
    text = fixture.read_text()
    missing = [frag for frag in _FIXTURE_FRAGMENTS if frag not in text]
    assert not missing, f"Fixture missing expected fragments: {missing}"


# ---------------------------------------------------------------------------
# Integration tests – skipped when DATABASE_URL is not set in the environment
# ---------------------------------------------------------------------------

_db_url = os.environ.get("DATABASE_URL")
_requires_db = pytest.mark.skipif(
    not _db_url,
    reason="DATABASE_URL not set – skipping live-DB integration tests",
)


@_requires_db
def test_view_exists_and_columns_match_contract(repo_root: Path) -> None:
    """View must exist with the documented column contract and correct filter behaviour."""
    psycopg2 = pytest.importorskip("psycopg2")
    migration = repo_root / "objectified-db" / "scripts" / "V095__mcp_read_model_published_public_schema_r.sql"

    with psycopg2.connect(_db_url) as conn:
        conn.autocommit = False
        with conn.cursor() as cur:
            cur.execute(migration.read_text())

            # Column names must match the documented contract
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'odb' AND table_name = 'mcp_v_public_specs' "
                "ORDER BY ordinal_position"
            )
            cols = [r[0] for r in cur.fetchall()]
            assert cols == ["id", "tenant_id", "project_id", "title", "version", "description", "tags", "updated_at"], (
                f"View column contract changed: {cols}"
            )

        conn.rollback()  # leave the DB clean – this is a read-only check


@_requires_db
def test_fixture_yields_one_visible_row(repo_root: Path) -> None:
    """Loading the dev fixture must produce exactly one row in mcp_v_public_specs."""
    psycopg2 = pytest.importorskip("psycopg2")
    migration = repo_root / "objectified-db" / "scripts" / "V095__mcp_read_model_published_public_schema_r.sql"
    fixture = repo_root / "objectified-db" / "fixtures" / "mcp_public_specs_dev.sql"

    with psycopg2.connect(_db_url) as conn:
        conn.autocommit = False
        with conn.cursor() as cur:
            cur.execute(migration.read_text())
            cur.execute(fixture.read_text())

            cur.execute(
                "SELECT count(*) FROM odb.mcp_v_public_specs "
                "WHERE project_id = '00000000-0000-4000-8000-000000000003'::uuid"
            )
            count = cur.fetchone()[0]
            assert count == 1, (
                f"Expected 1 visible row for fixture project, got {count}. "
                "Check that only the published+public revision appears."
            )

        conn.rollback()  # idempotent – roll back fixture data
