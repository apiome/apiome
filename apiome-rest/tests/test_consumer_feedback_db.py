"""COL-4.4 (#4528) against a live Postgres: the SQL behind portal consumer feedback.

The unit tests drive :mod:`app.consumer_feedback_store` over an in-memory fake; these run it over
the real :class:`~app.database.Database` and apiome-db V379, so the new SQL — the published-public
version lookup, the method + path operation lookup, ``origin`` on insert and in the list filter,
``created_by`` scoping and the operation coordinates — is exercised. One rolled-back transaction per
test.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Iterator, Tuple

import psycopg2
import pytest
from psycopg2.extras import RealDictCursor

from app import comment_store, consumer_feedback_store, notification_store
from app.comments import CommentValidationError
from app.config import settings
from app.consumer_feedback import FeedbackCreate
from app.database import Database
from tests.test_catalog_graph_db import _NoCommitConnection

pytestmark = pytest.mark.requires_db


@pytest.fixture
def seeded(monkeypatch) -> Iterator[Tuple[Database, Any, Dict[str, str]]]:
    """A tenant with a published public version holding `GET /pets/{petId}`, plus a reader and a member."""
    try:
        conn = psycopg2.connect(settings.effective_database_url, cursor_factory=RealDictCursor, connect_timeout=3)
    except psycopg2.OperationalError:
        pytest.skip("no database reachable")
    with conn.cursor() as probe:
        probe.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = 'apiome' AND table_name = 'comment_threads' AND column_name = 'origin'"
        )
        if not probe.fetchone():
            conn.close()
            pytest.skip("V379 not applied")
    db = Database()
    db.connection = _NoCommitConnection(conn)
    for module in (comment_store, consumer_feedback_store, notification_store):
        monkeypatch.setattr(module, "db", db)
    suffix = uuid.uuid4().hex[:10]
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO apiome.users (name, email, password, verified) VALUES ('Team', %s, '', true) RETURNING id::text AS id",
                (f"team-{suffix}@example.com",),
            )
            member = cur.fetchone()["id"]
            cur.execute(
                "INSERT INTO apiome.users (name, email, password, verified) VALUES ('Reader', %s, '', true) RETURNING id::text AS id",
                (f"reader-{suffix}@example.com",),
            )
            reader = cur.fetchone()["id"]
            cur.execute(
                "INSERT INTO apiome.tenants (name, slug) VALUES (%s, %s) RETURNING id::text AS id",
                (f"fb {suffix}", f"fb-{suffix}"),
            )
            tenant = cur.fetchone()["id"]
            cur.execute(
                """INSERT INTO apiome.projects (tenant_id, creator_id, name, slug)
                   VALUES (%s, %s, 'Pets', %s) RETURNING id::text AS id""",
                (tenant, member, f"pets-{suffix}"),
            )
            project = cur.fetchone()["id"]
            cur.execute(
                """INSERT INTO apiome.versions (project_id, creator_id, version_id, published, published_at, visibility)
                   VALUES (%s, %s, '1.0.0', true, now(), 'public') RETURNING id::text AS id""",
                (project, member),
            )
            version = cur.fetchone()["id"]
            cur.execute(
                """INSERT INTO apiome.versions (project_id, creator_id, version_id, published, published_at, visibility)
                   VALUES (%s, %s, '1.1.0', true, now(), 'private')""",
                (project, member),
            )
            cur.execute(
                "INSERT INTO apiome.version_path (version_id, pathname) VALUES (%s, '/pets/{petId}') RETURNING id",
                (version,),
            )
            path_id = cur.fetchone()["id"]
            cur.execute(
                "INSERT INTO apiome.path_operation (version_path_id, operation) VALUES (%s, 'get') RETURNING id::text AS id",
                (path_id,),
            )
            operation = cur.fetchone()["id"]
            yield db, cur, {
                "tenant": tenant, "project": project, "project_slug": f"pets-{suffix}",
                "version": version, "operation": operation, "reader": reader, "member": member,
            }
    finally:
        conn.rollback()
        conn.close()


def test_a_reader_opens_lists_and_resolves_feedback(seeded):
    db, cur, ids = seeded
    created = consumer_feedback_store.open_feedback(
        ids["tenant"], ids["project_slug"], "1.0.0",
        FeedbackCreate(target="operation", method="GET", path="/pets/{petId}", body="@Team 404 has no schema"),
        ids["reader"],
    )
    assert created.operation is not None and created.operation.method == "GET"
    cur.execute("SELECT origin, anchor_type, anchor_id::text AS anchor_id, created_by::text AS created_by FROM apiome.comment_threads WHERE id = %s", (created.id,))
    row = cur.fetchone()
    assert row == {"origin": "consumer", "anchor_type": "operation", "anchor_id": ids["operation"], "created_by": ids["reader"]}
    cur.execute("SELECT mentions::text[] AS m FROM apiome.comments WHERE thread_id = %s", (created.id,))
    assert cur.fetchone()["m"] == []

    # The team replies through the internal store; the reader sees it as from_team.
    comment_store.add_comment(ids["tenant"], ids["project"], created.id, "Fixed in 1.0.1", ids["member"])
    (listed,) = consumer_feedback_store.list_feedback(ids["tenant"], ids["project_slug"], "1.0.0", ids["reader"])
    # One transaction shares CURRENT_TIMESTAMP, so compare by body rather than by order.
    assert {c.body: c.from_team for c in listed.comments} == {"@Team 404 has no schema": False, "Fixed in 1.0.1": True}

    # The team's Origin filter finds it; an internal thread is not a reader's.
    internal = db.list_comment_threads(tenant_id=ids["tenant"], project_id=ids["project"], origin="internal")
    consumer = db.list_comment_threads(tenant_id=ids["tenant"], project_id=ids["project"], origin="consumer")
    assert internal == [] and [r["id"] for r in consumer] == [created.id]

    resolved = consumer_feedback_store.set_feedback_status(
        ids["tenant"], ids["project_slug"], "1.0.0", created.id, "resolved", ids["reader"]
    )
    assert resolved.status == "resolved"


def test_a_private_version_and_an_unknown_operation_are_refused(seeded):
    _, _, ids = seeded
    with pytest.raises(CommentValidationError) as exc:
        consumer_feedback_store.list_feedback(ids["tenant"], ids["project_slug"], "1.1.0", ids["reader"])
    assert exc.value.code == "feedback-version-not-found"
    with pytest.raises(CommentValidationError) as exc:
        consumer_feedback_store.open_feedback(
            ids["tenant"], ids["project_slug"], "1.0.0",
            FeedbackCreate(target="operation", method="DELETE", path="/pets/{petId}", body="x"), ids["reader"],
        )
    assert exc.value.code == "feedback-operation-not-found"
