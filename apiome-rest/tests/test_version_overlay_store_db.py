"""Stored overlay chain storage against a live Postgres — GVM-4.3 (#5878).

What only the real V385 schema can prove:

* rows are write-once: an UPDATE is refused by the trigger;
* insert at a position shifts later rows, delete compacts, replace keeps the position and gives a
  new id — always a dense ``0..n-1`` chain;
* each write appends exactly one ``workflow_audit`` row (replace: one ``version.overlay_replaced``);
* the publish render record upserts and reads back with both fingerprints;
* deleting the revision deletes its chain and render.

Everything runs inside one always-rolled-back transaction. Skipped when no database is reachable
or V385 is not applied.
"""

from __future__ import annotations

import uuid
from collections import Counter
from typing import Any, Dict, Iterator, Tuple

import psycopg2
import pytest
from psycopg2.extras import RealDictCursor

from app import version_overlay_store as store
from app.config import settings
from app.database import Database
from app.export_overlay import ExportOverlayFinding, ExportOverlayReport
from app.version_overlay_chain import ChainRender, document_fingerprint
from tests.test_usage_index_db import _NoCommitConnection

pytestmark = pytest.mark.requires_db


def _overlay(title: str) -> Dict[str, Any]:
    return {
        "overlay": "1.0.0",
        "info": {"title": title, "version": "1"},
        "actions": [{"target": "$.info", "update": {"title": title}}],
    }


@pytest.fixture
def chain(monkeypatch) -> Iterator[Tuple[Any, Dict[str, str]]]:
    """A cursor in a rolled-back transaction, and a tenant/project/draft revision to chain on."""
    try:
        conn = psycopg2.connect(settings.effective_database_url, cursor_factory=RealDictCursor, connect_timeout=3)
    except psycopg2.OperationalError:
        pytest.skip("no database reachable")
    with conn.cursor() as probe:
        probe.execute("SELECT to_regclass('apiome.version_overlays') AS t, (SELECT id FROM apiome.users LIMIT 1) AS u")
        found = probe.fetchone()
    if not found["t"] or not found["u"]:
        conn.close()
        pytest.skip("V385 not applied or no user")
    db = Database()
    db.connection = _NoCommitConnection(conn)
    monkeypatch.setattr(store, "db", db)
    try:
        with conn.cursor() as cursor:
            suffix = uuid.uuid4().hex[:10]
            user = str(found["u"])
            cursor.execute(
                "INSERT INTO apiome.tenants (name, slug) VALUES (%s, %s) RETURNING id::text AS id",
                (f"ov {suffix}", f"ov-{suffix}"),
            )
            tenant = cursor.fetchone()["id"]
            cursor.execute(
                """INSERT INTO apiome.projects (tenant_id, creator_id, name, slug, publishable)
                   VALUES (%s, %s, 'Pets', %s, true) RETURNING id::text AS id""",
                (tenant, user, f"pets-{suffix}"),
            )
            project = cursor.fetchone()["id"]
            cursor.execute(
                """INSERT INTO apiome.versions (project_id, creator_id, version_id, published)
                   VALUES (%s, %s, '1.0.0', false) RETURNING id::text AS id""",
                (project, user),
            )
            version = cursor.fetchone()["id"]
            yield cursor, {"tenant": tenant, "project": project, "version": version, "user": user}
    finally:
        conn.rollback()
        conn.close()


def _add(seed: Dict[str, str], name: str, position=None):
    return store.insert_overlay(
        tenant_id=seed["tenant"],
        project_id=seed["project"],
        version_record_id=seed["version"],
        name=name,
        source="manual",
        document=_overlay(name),
        actor_id=seed["user"],
        position=position,
    )


def _names(seed: Dict[str, str]):
    return [(row.position, row.name) for row in store.list_overlays(seed["tenant"], seed["version"])]


def _audits(cursor, seed) -> list:
    cursor.execute(
        "SELECT action FROM apiome.workflow_audit WHERE version_id = %s ORDER BY created_at, id",
        (seed["version"],),
    )
    return [row["action"] for row in cursor.fetchall()]


def test_the_chain_stays_dense_through_insert_replace_and_delete(chain):
    cursor, seed = chain
    a = _add(seed, "a")
    _add(seed, "c")
    _add(seed, "b", position=1)
    assert _names(seed) == [(0, "a"), (1, "b"), (2, "c")]
    assert a.content_fingerprint == document_fingerprint(_overlay("a"))

    replaced = store.replace_overlay(
        tenant_id=seed["tenant"],
        project_id=seed["project"],
        version_record_id=seed["version"],
        overlay_id=a.id,
        name="a2",
        source="export-studio",
        document=_overlay("a2"),
        actor_id=seed["user"],
    )
    assert replaced.id != a.id and replaced.position == 0
    assert _names(seed) == [(0, "a2"), (1, "b"), (2, "c")]

    middle = store.list_overlays(seed["tenant"], seed["version"])[1]
    assert store.delete_overlay(
        tenant_id=seed["tenant"],
        project_id=seed["project"],
        version_record_id=seed["version"],
        overlay_id=middle.id,
        actor_id=seed["user"],
    )
    assert _names(seed) == [(0, "a2"), (1, "c")]
    # One audit row per write (rows of one transaction share created_at, so compare counts).
    assert Counter(_audits(cursor, seed)) == Counter(
        {"version.overlay_added": 3, "version.overlay_replaced": 1, "version.overlay_removed": 1}
    )


def test_an_unknown_id_or_another_tenant_finds_nothing(chain):
    _cursor, seed = chain
    row = _add(seed, "a")
    other_tenant = str(uuid.uuid4())
    assert store.list_overlays(other_tenant, seed["version"]) == []
    assert not store.delete_overlay(
        tenant_id=other_tenant,
        project_id=seed["project"],
        version_record_id=seed["version"],
        overlay_id=row.id,
        actor_id=None,
    )
    assert (
        store.replace_overlay(
            tenant_id=seed["tenant"],
            project_id=seed["project"],
            version_record_id=seed["version"],
            overlay_id=str(uuid.uuid4()),
            name="x",
            source="manual",
            document=_overlay("x"),
            actor_id=None,
        )
        is None
    )


def test_rows_are_write_once(chain):
    cursor, seed = chain
    row = _add(seed, "a")
    cursor.execute("SAVEPOINT before_update")
    with pytest.raises(psycopg2.Error):
        cursor.execute("UPDATE apiome.version_overlays SET name = 'changed' WHERE id = %s", (row.id,))
    cursor.execute("ROLLBACK TO SAVEPOINT before_update")


def test_the_render_record_upserts_and_reads_back(chain):
    cursor, seed = chain
    finding = ExportOverlayFinding(
        rule="overlay.unmatched-target", severity="warning", overlay="stored:a", action_index=0, message="m"
    )
    for resolved in ("sha256:first", "sha256:second"):
        store.record_render(
            tenant_id=seed["tenant"],
            project_id=seed["project"],
            version_record_id=seed["version"],
            render=ChainRender(
                source_fingerprint="sha256:source",
                resolved_fingerprint=resolved,
                overlay_fingerprints=[{"id": "x", "name": "a", "position": 0, "contentFingerprint": "sha256:o"}],
                report=ExportOverlayReport(applied=["stored:a"], findings=[finding], changes=1, truncated=False),
            ),
            actor_id=seed["user"],
        )
    render = store.get_render(seed["tenant"], seed["version"])
    assert render["source_fingerprint"] == "sha256:source"
    assert render["resolved_fingerprint"] == "sha256:second"
    assert render["findings"][0]["rule"] == "overlay.unmatched-target"
    assert render["changes"] == 1
    assert _audits(cursor, seed).count("version.overlay_rendered") == 2


def test_deleting_the_revision_deletes_its_chain_and_render(chain):
    cursor, seed = chain
    _add(seed, "a")
    store.record_render(
        tenant_id=seed["tenant"],
        project_id=seed["project"],
        version_record_id=seed["version"],
        render=ChainRender(source_fingerprint="sha256:s", resolved_fingerprint="sha256:r"),
        actor_id=None,
    )
    cursor.execute("DELETE FROM apiome.workflow_audit WHERE version_id = %s", (seed["version"],))
    cursor.execute("DELETE FROM apiome.versions WHERE id = %s", (seed["version"],))
    cursor.execute("SELECT count(*) AS n FROM apiome.version_overlays WHERE version_record_id = %s", (seed["version"],))
    assert cursor.fetchone()["n"] == 0
    assert store.get_render(seed["tenant"], seed["version"]) is None
