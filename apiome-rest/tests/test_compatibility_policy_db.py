"""Compatibility policy and transitive lineage against a migrated database — XPC-4.5 (#5749).

The route and guardrail tests replace the database with a mock; this module runs the SQL itself:

* V382's three ``style_guides`` columns, their defaults and check constraints;
* :meth:`Database.update_style_guide_policy_settings` writing them, and
  :meth:`Database.get_assigned_style_guide` resolving them through the GOV-1.4 chain;
* :meth:`Database.list_prior_revisions_for_transitive_check` — published ancestors first, else a
  catalog item's earlier revisions;
* :meth:`Database.get_revision_source_row`.

Everything runs inside one transaction on a dedicated connection that is always rolled back.
Skipped when no migrated database is reachable::

    createdb apiome && node apiome-db/dist/cli.js migrate --database-url "$URL"
    DATABASE_URL="$URL" uv run pytest tests/test_compatibility_policy_db.py -m requires_db
"""

from __future__ import annotations

import uuid
from typing import Any, Iterator, Optional

import psycopg2
import pytest
from psycopg2.extensions import TRANSACTION_STATUS_IDLE
from psycopg2.extras import Json, RealDictCursor

from app.compatibility_policy import policy_from_guide, resolve_policy
from app.config import settings
from app.database import Database

pytestmark = pytest.mark.requires_db


class _NoCommitConnection:
    """A real connection whose commits and rollbacks are swallowed, so one test is one transaction."""

    closed = False

    class _Info:
        transaction_status = TRANSACTION_STATUS_IDLE

    info = _Info()

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def cursor(self, *args: Any, **kwargs: Any) -> Any:
        return self._conn.cursor(*args, **kwargs)

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    @property
    def autocommit(self) -> bool:
        return False

    @autocommit.setter
    def autocommit(self, value: bool) -> None:
        pass


class Seed:
    """A tenant, a user, a project and helpers to add revisions and guides."""

    def __init__(self, db: Database, conn: Any) -> None:
        self.db = db
        self.conn = conn
        suffix = uuid.uuid4().hex[:8]
        self.tenant_id = self._one(
            "INSERT INTO apiome.tenants (name, slug) VALUES (%s, %s) RETURNING id::text AS id",
            (f"Compat {suffix}", f"compat-{suffix}"),
        )
        self.user_id = self._one(
            "INSERT INTO apiome.users (name, email, password) VALUES (%s, %s, 'x') RETURNING id::text AS id",
            ("Ada", f"ada-{suffix}@example.com"),
        )
        self.project_id = self.project("orders-events")

    def _one(self, sql: str, params: tuple) -> str:
        with self.conn.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchone()["id"]

    def project(self, slug: str) -> str:
        return self._one(
            "INSERT INTO apiome.projects (tenant_id, creator_id, name, slug) VALUES (%s, %s, %s, %s) "
            "RETURNING id::text AS id",
            (self.tenant_id, self.user_id, slug, slug),
        )

    def revision(
        self,
        label: str,
        *,
        project_id: Optional[str] = None,
        parent: Optional[str] = None,
        published: bool = False,
        source_format: Optional[str] = None,
        minutes: int = 0,
    ) -> str:
        return self._one(
            """
            INSERT INTO apiome.versions
                (project_id, creator_id, version_id, parent_version_id, published, published_at,
                 source_format, format_metadata, created_at)
            VALUES (%s, %s, %s, %s, %s,
                    CASE WHEN %s THEN TIMESTAMP '2026-11-01' + make_interval(mins => %s) END,
                    %s, %s, TIMESTAMP '2026-11-01' + make_interval(mins => %s))
            RETURNING id::text AS id
            """,
            (
                project_id or self.project_id,
                self.user_id,
                label,
                parent,
                published,
                published,
                minutes,
                source_format,
                Json({"sourceContent": "{}", "sourceLabel": "user.avsc"} if source_format else {}),
                minutes,
            ),
        )

    def guide(self, name: str, *, default: bool = False) -> str:
        return self._one(
            "INSERT INTO apiome.style_guides (tenant_id, name, source, is_default) VALUES (%s, %s, 'custom', %s) "
            "RETURNING id::text AS id",
            (self.tenant_id, name, default),
        )

    def assign_to_project(self, guide_id: str) -> None:
        with self.conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO apiome.style_guide_assignments (guide_id, project_id) VALUES (%s, %s)",
                (guide_id, self.project_id),
            )


@pytest.fixture
def seed() -> Iterator[Seed]:
    """A real :class:`Database` inside one always-rolled-back transaction."""
    try:
        conn = psycopg2.connect(settings.effective_database_url, cursor_factory=RealDictCursor, connect_timeout=3)
    except psycopg2.OperationalError:
        pytest.skip("no database reachable")
    with conn.cursor() as probe:
        probe.execute(
            "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'apiome' "
            "AND table_name = 'style_guides' AND column_name = 'compatibility_mode') AS migrated"
        )
        migrated = probe.fetchone()["migrated"]
    if not migrated:
        conn.close()
        pytest.skip("V382 (compatibility mode policy) is not applied")
    db = Database()
    db.connection = _NoCommitConnection(conn)
    try:
        yield Seed(db, conn)
    finally:
        conn.rollback()
        conn.close()


# ===========================================================================
# V382 and the policy columns
# ===========================================================================


def test_a_new_guide_gets_the_documented_defaults(seed: Seed) -> None:
    guide_id = seed.guide("Defaults")
    row = seed.db.get_style_guide_by_id(guide_id, seed.tenant_id)
    assert (row["compatibility_mode"], row["compatibility_transitive"], row["protobuf_breaking_category"]) == (
        "BACKWARD",
        False,
        "WIRE_JSON",
    )


def test_the_check_constraints_refuse_unknown_values(seed: Seed) -> None:
    guide_id = seed.guide("Strict")
    for column, value in (("compatibility_mode", "SIDEWAYS"), ("protobuf_breaking_category", "BYTES")):
        with seed.conn.cursor() as cursor:
            cursor.execute("SAVEPOINT bad_value")
            with pytest.raises(psycopg2.errors.CheckViolation):
                cursor.execute(f"UPDATE apiome.style_guides SET {column} = %s WHERE id = %s", (value, guide_id))
            cursor.execute("ROLLBACK TO SAVEPOINT bad_value")


def test_update_writes_and_leaves_alone(seed: Seed) -> None:
    guide_id = seed.guide("Events")
    updated = seed.db.update_style_guide_policy_settings(
        guide_id,
        seed.tenant_id,
        compatibility_mode="FULL",
        compatibility_transitive=True,
        protobuf_breaking_category="FILE",
    )
    assert (updated["compatibility_mode"], updated["compatibility_transitive"], updated["protobuf_breaking_category"]) == (
        "FULL",
        True,
        "FILE",
    )
    untouched = seed.db.update_style_guide_policy_settings(guide_id, seed.tenant_id, breaking_publish_policy="block")
    assert (untouched["compatibility_mode"], untouched["compatibility_transitive"]) == ("FULL", True)
    switched_off = seed.db.update_style_guide_policy_settings(guide_id, seed.tenant_id, compatibility_transitive=False)
    assert switched_off["compatibility_transitive"] is False


def test_the_policy_resolves_through_the_guide_chain(seed: Seed) -> None:
    tenant_default = seed.guide("Tenant default", default=True)
    seed.db.update_style_guide_policy_settings(tenant_default, seed.tenant_id, compatibility_mode="FORWARD")
    assert resolve_policy(seed.db, seed.tenant_id, seed.project_id).mode == "FORWARD"

    project_guide = seed.guide("Project guide")
    seed.db.update_style_guide_policy_settings(
        project_guide, seed.tenant_id, compatibility_mode="FULL", compatibility_transitive=True
    )
    seed.assign_to_project(project_guide)
    policy = resolve_policy(seed.db, seed.tenant_id, seed.project_id)
    assert (policy.mode, policy.transitive, policy.category) == ("FULL", True, "WIRE_JSON")
    assert policy_from_guide(seed.db.get_assigned_style_guide(seed.tenant_id, seed.project_id)).mode_name == (
        "FULL_TRANSITIVE"
    )


# ===========================================================================
# The transitive lineage
# ===========================================================================


def test_published_ancestors_come_newest_first(seed: Seed) -> None:
    v1 = seed.revision("1.0.0", published=True, minutes=1)
    v2 = seed.revision("2.0.0", parent=v1, published=True, minutes=2)
    draft = seed.revision("2.0.1-draft", parent=v2, minutes=3)
    v3 = seed.revision("3.0.0", parent=draft, published=True, minutes=4)
    head = seed.revision("3.1.0", parent=v3, minutes=5)

    rows = seed.db.list_prior_revisions_for_transitive_check(seed.project_id, seed.tenant_id, v3)
    assert [r["version_id"] for r in rows] == ["2.0.0", "1.0.0"]  # the unpublished draft is skipped
    assert all(r["id"] != v3 for r in rows)
    assert [r["version_id"] for r in seed.db.list_prior_revisions_for_transitive_check(
        seed.project_id, seed.tenant_id, v3, limit=1
    )] == ["2.0.0"]
    assert seed.db.list_prior_revisions_for_transitive_check(seed.project_id, seed.tenant_id, v1) == []
    assert head  # the head is never its own predecessor


def test_a_catalog_item_falls_back_to_its_earlier_revisions(seed: Seed) -> None:
    item = seed.project("user-schema")
    r1 = seed.revision("1", project_id=item, minutes=1)
    r2 = seed.revision("2", project_id=item, minutes=2)
    r3 = seed.revision("3", project_id=item, minutes=3)
    seed.revision("4", project_id=item, minutes=4)

    rows = seed.db.list_prior_revisions_for_transitive_check(item, seed.tenant_id, r3)
    assert [r["id"] for r in rows] == [r2, r1]


def test_the_lineage_ignores_other_projects_and_bad_ids(seed: Seed) -> None:
    other = seed.project("other")
    seed.revision("0.9.0", project_id=other, published=True, minutes=0)
    v1 = seed.revision("1.0.0", minutes=1)
    assert seed.db.list_prior_revisions_for_transitive_check(seed.project_id, seed.tenant_id, v1) == []
    assert seed.db.list_prior_revisions_for_transitive_check(seed.project_id, seed.tenant_id, "not-a-uuid") == []


def test_the_source_row_carries_the_format_and_captured_source(seed: Seed) -> None:
    revision = seed.revision("1", source_format="avro")
    row = seed.db.get_revision_source_row(revision, seed.tenant_id)
    assert row["source_format"] == "avro"
    assert row["project_id"] == seed.project_id
    assert row["format_metadata"]["sourceLabel"] == "user.avsc"
    assert seed.db.get_revision_source_row(revision, str(uuid.uuid4())) is None
    assert seed.db.get_revision_source_row("nope", seed.tenant_id) is None
