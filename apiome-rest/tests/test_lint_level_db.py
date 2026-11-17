"""Maturity levels on policy evaluations against a migrated database — GVM-1.2 (#5855).

The service and route tests mock the database; this module runs the SQL itself:

* V391's ``lint_policy_evaluations.maturity_level`` column, written by
  :meth:`Database.record_lint_policy_evaluation_row` and read back by the latest-evaluation reads;
* re-recording unchanged inputs returns the stored row (same id, ``reused``), while a changed
  finding decision or maturity result appends a new row;
* the end-to-end path: a laddered pack evaluated by
  :func:`app.lint_policy_service.build_lint_policy_response` twice yields one evaluation id.

Everything runs inside one transaction on a dedicated connection that is always rolled back.
Skipped when no migrated database is reachable::

    createdb apiome && node apiome-db/dist/cli.js migrate --database-url "$URL"
    DATABASE_URL="$URL" uv run pytest tests/test_lint_level_db.py -m requires_db
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Iterator
from unittest.mock import patch

import psycopg2
import pytest
from psycopg2.extensions import TRANSACTION_STATUS_IDLE
from psycopg2.extras import Json, RealDictCursor

from app.config import settings
from app.database import Database
from app.lint_evidence import SUBJECT_CATALOG_REVISION

pytestmark = pytest.mark.requires_db

LADDER = {
    "name": "Maturity",
    "levels": [
        {
            "key": "bronze",
            "label": "Bronze",
            "rules": [{"ruleId": "naming.schema-pascal-case", "maxSeverity": "warning"}],
            "axes": [],
            "evidence": [],
            "waiversSatisfy": True,
        }
    ],
}


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
    """A tenant, project, revision and a laddered policy pack."""

    def __init__(self, db: Database, conn: Any) -> None:
        self.db = db
        self.conn = conn
        suffix = uuid.uuid4().hex[:8]
        self.tenant_id = self._one(
            "INSERT INTO apiome.tenants (name, slug) VALUES (%s, %s) RETURNING id::text AS id",
            (f"Level {suffix}", f"level-{suffix}"),
        )
        self.user_id = self._one(
            "INSERT INTO apiome.users (name, email, password) VALUES (%s, %s, 'x') RETURNING id::text AS id",
            ("Ada", f"ada-{suffix}@example.com"),
        )
        self.project_id = self._one(
            "INSERT INTO apiome.projects (tenant_id, creator_id, name, slug) VALUES (%s, %s, 'p', 'p') "
            "RETURNING id::text AS id",
            (self.tenant_id, self.user_id),
        )
        self.version_id = self._one(
            "INSERT INTO apiome.versions (project_id, creator_id, version_id) VALUES (%s, %s, '1.0.0') "
            "RETURNING id::text AS id",
            (self.project_id, self.user_id),
        )
        guide_id = self._one(
            "INSERT INTO apiome.style_guides (tenant_id, name, source) VALUES (%s, 'G', 'custom') "
            "RETURNING id::text AS id",
            (self.tenant_id,),
        )
        self.pack = db.insert_style_guide_policy_version(
            guide_id=guide_id,
            tenant_id=self.tenant_id,
            rules_snapshot=[],
            axis_gates={},
            required_coverage=["quality"],
            ci_outcomes={},
            content_fingerprint="packfp",
            ladder=LADDER,
        )

    def _one(self, sql: str, params: tuple) -> str:
        with self.conn.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchone()["id"]

    def row(self, **over: Any) -> Dict[str, Any]:
        row = {
            "subject_type": SUBJECT_CATALOG_REVISION,
            "version_record_id": self.version_id,
            "mcp_version_id": None,
            "policy_version_id": str(self.pack["id"]),
            "policy_content_fingerprint": "packfp",
            "evidence_run_id": None,
            "axis_evaluation_id": None,
            "evidence_fingerprint": "ef",
            "passed": True,
            "gate_results": {"maturity": {"level": "bronze"}},
            "finding_decisions": [],
            "maturity_level": "bronze",
        }
        row.update(over)
        return row


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
            "AND table_name = 'lint_policy_evaluations' AND column_name = 'maturity_level') AS migrated"
        )
        migrated = probe.fetchone()["migrated"]
    if not migrated:
        conn.close()
        pytest.skip("V391 (maturity level) is not applied")
    db = Database()
    db.connection = _NoCommitConnection(conn)
    try:
        with patch("app.database.db", db), patch("app.lint_policy_service.db", db):
            yield Seed(db, conn)
    finally:
        conn.rollback()
        conn.close()


def test_the_level_is_stored_in_its_column_and_read_back(seed: Seed) -> None:
    stored = seed.db.record_lint_policy_evaluation_row(seed.row())
    assert stored["reused"] is False
    latest = seed.db.get_latest_lint_policy_evaluation_for_version(seed.version_id, seed.tenant_id)
    assert latest["id"] == stored["id"]
    assert latest["maturity_level"] == "bronze"
    assert latest["gate_results"]["maturity"]["level"] == "bronze"


def test_unchanged_inputs_return_the_same_evaluation(seed: Seed) -> None:
    first = seed.db.record_lint_policy_evaluation_row(seed.row())
    second = seed.db.record_lint_policy_evaluation_row(seed.row())
    assert second["id"] == first["id"]
    assert second["reused"] is True
    assert seed.db.record_lint_policy_evaluation(seed.row()) == str(first["id"])


def test_a_changed_decision_or_result_appends_a_new_evaluation(seed: Seed) -> None:
    first = seed.db.record_lint_policy_evaluation_row(seed.row())
    waived = seed.db.record_lint_policy_evaluation_row(
        seed.row(finding_decisions=[{"source_fingerprint": "f1", "effective_state": "waived"}])
    )
    below = seed.db.record_lint_policy_evaluation_row(
        seed.row(gate_results={"maturity": {"level": None}}, maturity_level=None)
    )
    assert len({first["id"], waived["id"], below["id"]}) == 3


def test_a_laddered_pack_evaluated_twice_has_one_evaluation_id(seed: Seed) -> None:
    from app.lint_policy_service import build_lint_policy_response, level_response

    def evaluate():
        return build_lint_policy_response(
            tenant_id=seed.tenant_id,
            subject_type=SUBJECT_CATALOG_REVISION,
            subject_id=seed.version_id,
            project_id=seed.project_id,
            policy_version=seed.pack,
            findings=[
                {"rule_id": "naming.schema-pascal-case", "severity": "warning", "source_fingerprint": "f1"}
            ],
            axes=None,
            evidence_run_id=None,
            axis_evaluation_id=None,
            evidence_fingerprint="ef",
            decisions=[],
        )

    first, second = level_response(evaluate()), level_response(evaluate())
    assert first.evaluation_id is not None
    assert second.evaluation_id == first.evaluation_id
    assert second.evaluated_at == first.evaluated_at
    assert first.level == "bronze"
    with seed.conn.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) AS n, max(maturity_level) AS level FROM apiome.lint_policy_evaluations "
            "WHERE version_record_id = %s",
            (seed.version_id,),
        )
        row = cursor.fetchone()
    assert (row["n"], row["level"]) == (1, "bronze")


def test_existing_rows_without_a_level_stay_readable(seed: Seed) -> None:
    with seed.conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO apiome.lint_policy_evaluations (subject_type, version_record_id, policy_version_id, "
            "policy_content_fingerprint, passed, gate_results) VALUES ('catalog_revision', %s, %s, 'old', true, %s)",
            (seed.version_id, str(seed.pack["id"]), Json({})),
        )
    latest = seed.db.get_latest_lint_policy_evaluation_for_version(seed.version_id, seed.tenant_id)
    assert latest["maturity_level"] is None
