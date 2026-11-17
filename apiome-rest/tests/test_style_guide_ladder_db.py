"""Maturity ladders against a migrated database — GVM-1.1 (#5854).

The route and service tests mock the database; this module runs the SQL itself:

* V390's ``style_guide_ladders`` table — one ladder per guide, the ``levels`` array CHECK;
* :meth:`Database.upsert_style_guide_ladder` / :meth:`Database.get_style_guide_ladder`,
  including the tenant guard;
* the ``ladder`` column on revisions and policy packs, written by the real snapshot writers
  (:func:`app.style_guide_revisions.record_guide_revision` and
  :func:`app.lint_policy_service.snapshot_style_guide_policy`), and the ``ladder_changed``
  change kind.

Everything runs inside one transaction on a dedicated connection that is always rolled back.
Skipped when no migrated database is reachable::

    createdb apiome && node apiome-db/dist/cli.js migrate --database-url "$URL"
    DATABASE_URL="$URL" uv run pytest tests/test_style_guide_ladder_db.py -m requires_db
"""

from __future__ import annotations

import uuid
from typing import Any, Iterator
from unittest.mock import patch

import psycopg2
import pytest
from psycopg2.extensions import TRANSACTION_STATUS_IDLE
from psycopg2.extras import Json, RealDictCursor

from app.config import settings
from app.database import Database
from app.style_guide_ladder import ladder_content_fingerprint

pytestmark = pytest.mark.requires_db

LEVELS = [
    {
        "key": "bronze",
        "label": "Bronze",
        "rules": [{"ruleId": "naming.schema-pascal-case", "maxSeverity": "warning"}],
        "axes": [],
        "evidence": [],
        "waiversSatisfy": True,
    }
]


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
    """A tenant and helpers to add guides."""

    def __init__(self, db: Database, conn: Any) -> None:
        self.db = db
        self.conn = conn
        suffix = uuid.uuid4().hex[:8]
        self.tenant_id = self._one(
            "INSERT INTO apiome.tenants (name, slug) VALUES (%s, %s) RETURNING id::text AS id",
            (f"Ladder {suffix}", f"ladder-{suffix}"),
        )

    def _one(self, sql: str, params: tuple) -> str:
        with self.conn.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchone()["id"]

    def guide(self, name: str, tenant_id: str = "") -> str:
        return self._one(
            "INSERT INTO apiome.style_guides (tenant_id, name, source) VALUES (%s, %s, 'custom') "
            "RETURNING id::text AS id",
            (tenant_id or self.tenant_id, name),
        )

    def save(self, guide_id: str, levels=None, name: str = "Maturity"):
        ladder = {"name": name, "levels": levels or LEVELS}
        return self.db.upsert_style_guide_ladder(
            guide_id=guide_id,
            tenant_id=self.tenant_id,
            name=name,
            levels=ladder["levels"],
            content_fingerprint=ladder_content_fingerprint(ladder),
        )


@pytest.fixture
def seed() -> Iterator[Seed]:
    """A real :class:`Database` inside one always-rolled-back transaction."""
    try:
        conn = psycopg2.connect(settings.effective_database_url, cursor_factory=RealDictCursor, connect_timeout=3)
    except psycopg2.OperationalError:
        pytest.skip("no database reachable")
    with conn.cursor() as probe:
        probe.execute("SELECT to_regclass('apiome.style_guide_ladders') IS NOT NULL AS migrated")
        migrated = probe.fetchone()["migrated"]
    if not migrated:
        conn.close()
        pytest.skip("V390 (style-guide ladders) is not applied")
    db = Database()
    db.connection = _NoCommitConnection(conn)
    try:
        # The snapshot writers import the module-level singleton; point it at this transaction.
        with patch("app.database.db", db), patch("app.lint_policy_service.db", db):
            yield Seed(db, conn)
    finally:
        conn.rollback()
        conn.close()


def test_a_guide_has_no_ladder_until_one_is_saved(seed: Seed) -> None:
    guide_id = seed.guide("Payments")
    assert seed.db.get_style_guide_ladder(guide_id, seed.tenant_id) is None

    row = seed.save(guide_id)
    assert row["levels"] == LEVELS
    assert seed.db.get_style_guide_ladder(guide_id, seed.tenant_id)["name"] == "Maturity"


def test_saving_again_replaces_the_one_ladder(seed: Seed) -> None:
    guide_id = seed.guide("Payments")
    first = seed.save(guide_id)
    second = seed.save(guide_id, levels=LEVELS + [{**LEVELS[0], "key": "silver", "label": "Silver"}], name="V2")

    assert second["id"] == first["id"]
    assert [lv["key"] for lv in second["levels"]] == ["bronze", "silver"]
    assert second["content_fingerprint"] != first["content_fingerprint"]
    with seed.conn.cursor() as cursor:
        cursor.execute("SELECT count(*) AS n FROM apiome.style_guide_ladders WHERE guide_id = %s", (guide_id,))
        assert cursor.fetchone()["n"] == 1


def test_a_guide_of_another_tenant_writes_nothing(seed: Seed) -> None:
    other = seed._one(
        "INSERT INTO apiome.tenants (name, slug) VALUES ('Other', %s) RETURNING id::text AS id",
        (f"other-{uuid.uuid4().hex[:8]}",),
    )
    foreign = seed.guide("Foreign", tenant_id=other)
    assert seed.save(foreign) is None
    assert seed.db.get_style_guide_ladder(foreign, other) is None


def test_levels_must_be_an_array(seed: Seed) -> None:
    guide_id = seed.guide("Payments")
    with seed.conn.cursor() as cursor:
        cursor.execute("SAVEPOINT bad_levels")
        with pytest.raises(psycopg2.errors.CheckViolation):
            cursor.execute(
                "INSERT INTO apiome.style_guide_ladders (guide_id, tenant_id, name, levels, content_fingerprint) "
                "VALUES (%s, %s, 'L', %s, 'f')",
                (guide_id, seed.tenant_id, Json({"bronze": {}})),
            )
        cursor.execute("ROLLBACK TO SAVEPOINT bad_levels")


def test_the_revision_and_the_policy_pack_freeze_the_ladder(seed: Seed) -> None:
    from app.lint_policy_service import snapshot_style_guide_policy
    from app.style_guide_revisions import CHANGE_LADDER_CHANGED, ensure_guide_revision, record_guide_revision

    guide_id = seed.guide("Payments")
    before_rev = ensure_guide_revision(guide_id, seed.tenant_id)
    before_pack = snapshot_style_guide_policy(guide_id, seed.tenant_id)
    assert before_rev["ladder"] is None
    assert before_pack["ladder"] is None

    seed.save(guide_id)
    after_rev = record_guide_revision(guide_id, seed.tenant_id, change_kind=CHANGE_LADDER_CHANGED)
    after_pack = snapshot_style_guide_policy(guide_id, seed.tenant_id)

    assert after_rev["change_kind"] == "ladder_changed"
    assert after_rev["revision_number"] == before_rev["revision_number"] + 1
    assert after_rev["ladder"] == {"name": "Maturity", "levels": LEVELS}
    assert after_rev["snapshot_fingerprint"] != before_rev["snapshot_fingerprint"]
    # The rule-content fingerprint (what lint runs pin by) does not move on a ladder change.
    assert after_rev["content_fingerprint"] == before_rev["content_fingerprint"]

    assert after_pack["ladder"] == {"name": "Maturity", "levels": LEVELS}
    assert after_pack["content_fingerprint"] != before_pack["content_fingerprint"]


def test_deleting_the_guide_deletes_its_ladder(seed: Seed) -> None:
    guide_id = seed.guide("Payments")
    seed.save(guide_id)
    with seed.conn.cursor() as cursor:
        cursor.execute("DELETE FROM apiome.style_guides WHERE id = %s", (guide_id,))
        cursor.execute("SELECT count(*) AS n FROM apiome.style_guide_ladders WHERE guide_id = %s", (guide_id,))
        assert cursor.fetchone()["n"] == 0
