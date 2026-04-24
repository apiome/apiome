"""REPO-1.1 / #2753: round-trip coverage for repository connector tables."""

from pathlib import Path
import uuid

import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor
import pytest

from app.config import settings


def _migration_path() -> Path:
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "objectified-db" / "scripts" / "20260423-230000-repository-connector.sql"


@pytest.fixture()
def repository_schema():
    """Create an isolated schema, apply migration, and clean it up after each test."""
    schema = f"odb_repo_test_{uuid.uuid4().hex[:8]}"
    migration = _migration_path()
    migration_sql = migration.read_text()
    try:
        conn = psycopg2.connect(settings.effective_database_url)
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"PostgreSQL unavailable for repository round-trip tests: {exc}")
    conn.autocommit = False

    transformed_sql = migration_sql.replace(
        "SET search_path TO odb, public;",
        f"SET search_path TO {schema}, public;",
    ).replace("odb.", f"{schema}.")

    with conn.cursor() as cur:
        cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        cur.execute(
            sql.SQL(
                """
                CREATE TABLE {} (
                    id UUID PRIMARY KEY
                );
                """
            ).format(sql.Identifier(schema, "tenants"))
        )
        cur.execute(
            sql.SQL(
                """
                CREATE TABLE {} (
                    id UUID PRIMARY KEY,
                    tenant_id UUID NOT NULL REFERENCES {}(id)
                );
                """
            ).format(sql.Identifier(schema, "projects"), sql.Identifier(schema, "tenants"))
        )
        cur.execute(
            sql.SQL(
                """
                CREATE TABLE {} (
                    id UUID PRIMARY KEY
                );
                """
            ).format(sql.Identifier(schema, "users"))
        )
        cur.execute(
            sql.SQL(
                """
                CREATE TABLE {} (
                    id UUID PRIMARY KEY,
                    user_id UUID NOT NULL REFERENCES {}(id)
                );
                """
            ).format(sql.Identifier(schema, "external_auth_providers"), sql.Identifier(schema, "users"))
        )
        cur.execute(transformed_sql)
    conn.commit()

    try:
        yield conn, schema
    finally:
        conn.rollback()
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))
        conn.close()


@pytest.fixture()
def base_refs(repository_schema):
    conn, schema = repository_schema
    tenant_id = "00000000-0000-0000-0000-000000000111"
    project_id = "00000000-0000-0000-0000-000000000222"
    user_id = "00000000-0000-0000-0000-000000000333"
    linked_account_id = "00000000-0000-0000-0000-000000000444"
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("INSERT INTO {} (id) VALUES (%s)").format(sql.Identifier(schema, "tenants")),
            (tenant_id,),
        )
        cur.execute(
            sql.SQL("INSERT INTO {} (id, tenant_id) VALUES (%s, %s)").format(
                sql.Identifier(schema, "projects")
            ),
            (project_id, tenant_id),
        )
        cur.execute(
            sql.SQL("INSERT INTO {} (id) VALUES (%s)").format(sql.Identifier(schema, "users")),
            (user_id,),
        )
        cur.execute(
            sql.SQL("INSERT INTO {} (id, user_id) VALUES (%s, %s)").format(
                sql.Identifier(schema, "external_auth_providers")
            ),
            (linked_account_id, user_id),
        )
    conn.commit()
    return {
        "tenant_id": tenant_id,
        "project_id": project_id,
        "user_id": user_id,
        "linked_account_id": linked_account_id,
    }


@pytest.fixture()
def repository_row(repository_schema, base_refs):
    conn, schema = repository_schema
    repository_id = "00000000-0000-0000-0000-000000000555"
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            sql.SQL(
                """
                INSERT INTO {} (
                    id, tenant_id, project_id, provider, provider_repo_id, owner, name,
                    default_branch, visibility, html_url, clone_url, description, status, created_by
                )
                VALUES (
                    %s, %s, %s, 'github', %s, %s, %s,
                    %s, 'private', %s, %s, %s, 'active', %s
                )
                RETURNING id, tenant_id, project_id, provider, provider_repo_id, owner, name,
                          default_branch, visibility, status, created_by;
                """
            ).format(sql.Identifier(schema, "repository")),
            (
                repository_id,
                base_refs["tenant_id"],
                base_refs["project_id"],
                "987654321",
                "octocat",
                "hello-world",
                "main",
                "https://github.com/octocat/hello-world",
                "git@github.com:octocat/hello-world.git",
                "fixture repository",
                base_refs["user_id"],
            ),
        )
        inserted = cur.fetchone()
        cur.execute(
            sql.SQL(
                """
                SELECT id, tenant_id, project_id, provider, provider_repo_id, owner, name,
                       default_branch, visibility, status, created_by
                FROM {}
                WHERE id = %s;
                """
            ).format(sql.Identifier(schema, "repository")),
            (repository_id,),
        )
        selected = cur.fetchone()
    conn.commit()
    assert inserted == selected
    return selected


@pytest.fixture()
def repository_branch_row(repository_schema, repository_row):
    conn, schema = repository_schema
    branch_id = "00000000-0000-0000-0000-000000000666"
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            sql.SQL(
                """
                INSERT INTO {} (
                    id, repository_id, branch, subpath_glob, is_tracked, last_known_sha, poll_interval_sec
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id, repository_id, branch, subpath_glob, is_tracked, last_known_sha, poll_interval_sec;
                """
            ).format(sql.Identifier(schema, "repository_branch")),
            (
                branch_id,
                repository_row["id"],
                "main",
                "apis/**/*.yaml",
                True,
                "abc123",
                3600,
            ),
        )
        inserted = cur.fetchone()
        cur.execute(
            sql.SQL(
                """
                SELECT id, repository_id, branch, subpath_glob, is_tracked, last_known_sha, poll_interval_sec
                FROM {}
                WHERE id = %s;
                """
            ).format(sql.Identifier(schema, "repository_branch")),
            (branch_id,),
        )
        selected = cur.fetchone()
    conn.commit()
    assert inserted == selected
    return selected


@pytest.fixture()
def repository_credential_ref_row(repository_schema, repository_row, base_refs):
    conn, schema = repository_schema
    ref_id = "00000000-0000-0000-0000-000000000777"
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            sql.SQL(
                """
                INSERT INTO {} (id, repository_id, linked_account_id, scopes)
                VALUES (%s, %s, %s, %s::text[])
                RETURNING id, repository_id, linked_account_id, scopes;
                """
            ).format(sql.Identifier(schema, "repository_credential_ref")),
            (
                ref_id,
                repository_row["id"],
                base_refs["linked_account_id"],
                ["repo", "read:org"],
            ),
        )
        inserted = cur.fetchone()
        cur.execute(
            sql.SQL(
                """
                SELECT id, repository_id, linked_account_id, scopes
                FROM {}
                WHERE id = %s;
                """
            ).format(sql.Identifier(schema, "repository_credential_ref")),
            (ref_id,),
        )
        selected = cur.fetchone()
    conn.commit()
    assert inserted == selected
    return selected


def test_repository_round_trip(repository_row):
    assert repository_row["provider"] == "github"
    assert repository_row["owner"] == "octocat"
    assert repository_row["name"] == "hello-world"


def test_repository_branch_round_trip(repository_branch_row):
    assert repository_branch_row["branch"] == "main"
    assert repository_branch_row["subpath_glob"] == "apis/**/*.yaml"
    assert repository_branch_row["poll_interval_sec"] == 3600


def test_repository_credential_ref_round_trip(repository_credential_ref_row):
    assert repository_credential_ref_row["scopes"] == ["repo", "read:org"]


def test_provider_enum_is_github_only(repository_schema):
    conn, schema = repository_schema
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT e.enumlabel
            FROM pg_enum e
            JOIN pg_type t ON t.oid = e.enumtypid
            JOIN pg_namespace n ON n.oid = t.typnamespace
            WHERE t.typname = 'repository_provider'
              AND n.nspname = %s
            ORDER BY e.enumsortorder;
            """,
            (schema,),
        )
        labels = [row[0] for row in cur.fetchall()]
    assert labels == ["github"]

