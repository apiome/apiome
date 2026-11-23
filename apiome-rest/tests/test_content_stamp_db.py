"""Revision content stamp and document object tables against Postgres — COA-5.2 (#7078).

V403 adds ``versions.content_stamp``, bumped by one trigger function on every normalized table of
a revision, plus the ``document_objects`` / ``version_documents`` metadata tables. These tests run
against a real database (they skip when none with V403 is reachable) and pin the acceptance
criteria:

* every edit through the REST DB layer bumps the stamp **exactly once per transaction**, however
  many rows and tables the transaction writes; reads, no-op updates, canvas-only updates and
  bookkeeping columns do not bump it;
* editing a project library property bumps every revision whose schema uses it;
* a rolled-back savepoint undoes its bump; deleting a revision with all its rows still works;
* **coverage guard:** every table that references ``versions`` or a covered table either carries
  the ``trg_content_stamp_*`` triggers or is listed in :data:`NOT_RENDERED` with the reason — adding a
  new normalized table without the trigger fails here;
* the column was added without rewriting ``versions``;
* the document metadata tables enforce their roles, provenance and identity.

Unlike most ``*_db.py`` suites these tests **commit** (the stamp is per transaction, so a single
rolled-back transaction cannot show it); the fixture deletes everything it created.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Dict, Iterator, List

import psycopg2
import pytest
from psycopg2.extras import RealDictCursor

from app.config import settings
from app.database import Database

#: The Flyway migrations (apiome-db/scripts), read for statements whose effect a later migration hides.
REPO_SCRIPTS = Path(__file__).resolve().parents[2] / "apiome-db" / "scripts"

#: Tables that reference a revision (or one of its covered rows) but are not part of its rendered
#: content, so writes to them must not bump the stamp. Each needs a reason; a table that renders
#: into the revision's documents belongs in V403's trigger list instead.
NOT_RENDERED: Dict[str, str] = {
    # derived from the content, or the document metadata itself
    "version_documents": "document metadata (COA-5.2) — derived, never an input",
    "version_spec_snapshots": "frozen snapshot of a rendered document",
    "version_import_snapshots": "captured import source, not the normalized model",
    "version_overlay_renders": "render cache of an overlay",
    "version_content_counts": "Home's count rollup (DBP-1.15) — derived from the content, keyed by its stamp",
    "version_overlays": "applied on top of the rendered document, not part of the revision's model",
    "version_entity_sources": "per-entity source provenance",
    "version_source_edits": "source workspace edit log",
    "version_preservation_claims": "round-trip preservation bookkeeping",
    "preservation_audit": "audit",
    "source_change_audit": "audit",
    "conversion_provenance": "conversion lineage",
    "data_record": "data records stored against a class schema, not the schema",
    "data_snapshot": "data snapshots stored against a class schema, not the schema",
    # workspace organisation and canvas furniture
    "canvas_layouts": "canvas layout",
    "tenant_canvas_layout_defaults": "canvas layout",
    "user_canvas_layout_defaults": "canvas layout",
    "groups": "canvas groups",
    "group_classes": "canvas group membership",
    "version_path_canvas": "per-path canvas",
    "domains": "workspace folders (domain_id writes on classes/paths are covered there)",
    # lifecycle, branching and collaboration
    "version_branches": "branch pointers",
    "version_tags": "tag pointers",
    "version_draft_lock": "draft lock",
    "version_changelogs": "published changelog",
    "change_reports": "publication change report",
    "merge_requests": "merge request",
    "merge_sessions": "merge session",
    "migration_plans": "migration plan between revisions",
    "comment_threads": "comments",
    "reviews": "reviews",
    "review_suggestions": "review suggestions",
    "notifications": "notifications",
    "draft_repository_bindings": "repository binding",
    "draft_sync_plans": "repository sync plan",
    "project_repository_sources": "repository source pointers",
    "project_federation_merges": "federation merge record",
    "tenant_repository_imports": "repository import record",
    "catalog_drift_events": "drift events",
    # evaluations and runs over the revision
    "lint_axis_evaluations": "lint result",
    "lint_evidence_runs": "lint result",
    "lint_policy_evaluations": "lint result",
    "verification_policy_evaluations": "verification result",
    "api_check_suite_runs": "check-suite run",
    "provider_check_runs": "provider check run",
    "quality_rank_observations": "quality observation",
    "payload_analysis": "payload analysis",
    "sunset_still_used_alert": "usage alert",
    "usage_sdk_beacon_daily": "usage rollup",
    "mcp_access_audit": "audit",
    # consumers of the revision
    "consumer_contract": "consumer contract against the revision",
    "agent_toolsets": "agent toolset built from the revision",
    "mock_instances": "mock runtime",
    "mock_broker_bindings": "mock runtime",
    "mock_capture_exchange": "mock traffic capture",
    "schema_registry_schemas": "schema registry publication",
    "schema_subject_versions": "schema registry publication",
    "sdk_git_delivery_runs": "SDK delivery run",
    "sdk_publish_runs": "SDK publish run",
    "sdk_regen_runs": "SDK regeneration run",
}


@pytest.fixture
def env() -> Iterator[Dict[str, Any]]:
    """A committing connection, a :class:`Database` on it, and a seeded tenant/project/revision.

    Yields a dict with ``conn``, ``db``, ``tenant``, ``project``, ``user`` and ``version`` (a
    ``versions.id``). Everything created under the tenant is deleted afterwards.
    """
    try:
        conn = psycopg2.connect(settings.effective_database_url, cursor_factory=RealDictCursor, connect_timeout=3)
    except psycopg2.OperationalError:
        pytest.skip("no database reachable")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT to_regproc('apiome.bump_version_content_stamp') AS f, "
            "(SELECT id::text FROM apiome.users LIMIT 1) AS u"
        )
        found = cur.fetchone()
    conn.commit()
    if not found["f"] or not found["u"]:
        conn.close()
        pytest.skip("V403 not applied or no user to own the seed project")

    suffix = uuid.uuid4().hex[:10]
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO apiome.tenants (name, slug) VALUES (%s, %s) RETURNING id::text AS id",
            (f"stamp {suffix}", f"stamp-{suffix}"),
        )
        tenant = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO apiome.projects (tenant_id, creator_id, name, slug) "
            "VALUES (%s, %s, 'Orders', %s) RETURNING id::text AS id",
            (tenant, found["u"], f"orders-{suffix}"),
        )
        project = cur.fetchone()["id"]
    conn.commit()

    db = Database()
    db.connection = conn
    ctx: Dict[str, Any] = {"conn": conn, "db": db, "tenant": tenant, "project": project, "user": found["u"]}
    ctx["version"] = str(db.create_version(project, found["u"], "1.0.0")["id"])
    try:
        yield ctx
    finally:
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM apiome.versions WHERE project_id = %s::uuid", (project,))
            versions = [r["id"] for r in cur.fetchall()]
            cur.execute("DELETE FROM apiome.classes WHERE version_id = ANY(%s::uuid[])", (versions,))
            cur.execute("DELETE FROM apiome.versions WHERE project_id = %s::uuid", (project,))
            cur.execute("DELETE FROM apiome.properties WHERE project_id = %s::uuid", (project,))
            cur.execute("DELETE FROM apiome.projects WHERE id = %s::uuid", (project,))
            cur.execute("DELETE FROM apiome.tenants WHERE id = %s::uuid", (tenant,))
        conn.commit()
        conn.close()


def _stamp(ctx: Dict[str, Any], version: str | None = None) -> int:
    """The committed content stamp of ``version`` (default: the seeded revision)."""
    value = ctx["db"].get_version_content_stamp(version or ctx["version"])
    assert value is not None
    return value


def _one(ctx: Dict[str, Any], sql: str, params: tuple = ()) -> Dict[str, Any]:
    """Run one statement in its own committed transaction and return its first row."""
    with ctx["conn"].cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone() if cur.description else {}
    ctx["conn"].commit()
    return row


def _library_property(ctx: Dict[str, Any], name: str = "id") -> str:
    return str(ctx["db"].create_property(ctx["project"], name, None, {"type": "string"})["id"])


# ───────────────────────────── once per transaction ─────────────────────────────


def test_a_new_revision_starts_at_zero(env) -> None:
    assert _stamp(env) == 0


def test_every_rest_edit_bumps_the_stamp_exactly_once(env) -> None:
    db, version = env["db"], env["version"]
    prop = _library_property(env)
    edits = [
        (
            "create class",
            lambda: env.setdefault("cls", str(db.create_class(version, "Order", {"type": "object"})["id"])),
        ),
        ("update class", lambda: db.update_class(env["cls"], env["tenant"], {"description": "An order."})),
        ("add property", lambda: db.add_property_to_class(env["cls"], prop, "id", None, {"type": "string"})),
        ("create path", lambda: env.setdefault("path", str(db.create_path(version, "/orders")["id"]))),
        ("create operation", lambda: db.create_operation(env["path"], "get")),
        ("update revision", lambda: db.update_version(version, env["tenant"], {"description": "Orders API"})),
        ("delete class", lambda: db.delete_class(env["cls"], env["tenant"])),
    ]
    for label, edit in edits:
        before = _stamp(env)
        edit()
        assert _stamp(env) == before + 1, label


def test_one_transaction_over_many_tables_bumps_once(env) -> None:
    conn, version = env["conn"], env["version"]
    prop = _library_property(env)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO apiome.classes (version_id, name, schema) VALUES (%s, 'Order', '{}') RETURNING id",
            (version,),
        )
        cls = cur.fetchone()["id"]
        for name in ("id", "total", "status"):
            cur.execute(
                "INSERT INTO apiome.class_properties (class_id, property_id, name, data) VALUES (%s, %s, %s, '{}')",
                (cls, prop, name),
            )
        cur.execute(
            "INSERT INTO apiome.version_path (version_id, pathname) VALUES (%s, '/orders') RETURNING id", (version,)
        )
        path = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO apiome.path_operation (version_path_id, operation) VALUES (%s, 'get') RETURNING id", (path,)
        )
        op = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO apiome.path_response (path_operation_id, status_code) VALUES (%s, '200') RETURNING id", (op,)
        )
        resp = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO apiome.path_response_content (path_response_id, media_type) VALUES (%s, 'application/json')",
            (resp,),
        )
        cur.execute(
            "INSERT INTO apiome.version_server (version_id, url) VALUES (%s, 'https://api.example.com')", (version,)
        )
        cur.execute(
            "INSERT INTO apiome.version_security_scheme (version_id, scheme_name) VALUES (%s, 'bearer')", (version,)
        )
        cur.execute("UPDATE apiome.versions SET description = 'Orders' WHERE id = %s", (version,))
        # Inside the transaction the stamp has moved exactly once already.
        cur.execute("SELECT content_stamp FROM apiome.versions WHERE id = %s", (version,))
        assert cur.fetchone()["content_stamp"] == 1
    conn.commit()
    assert _stamp(env) == 1


def test_the_revision_row_bumping_first_still_counts_once(env) -> None:
    conn, version = env["conn"], env["version"]
    with conn.cursor() as cur:
        cur.execute("UPDATE apiome.versions SET change_log = 'first' WHERE id = %s", (version,))
        cur.execute("UPDATE apiome.versions SET change_log = 'second' WHERE id = %s", (version,))
        cur.execute("INSERT INTO apiome.version_path (version_id, pathname) VALUES (%s, '/a')", (version,))
    conn.commit()
    assert _stamp(env) == 1


def test_two_transactions_bump_twice(env) -> None:
    _one(env, "INSERT INTO apiome.version_path (version_id, pathname) VALUES (%s, '/a')", (env["version"],))
    _one(env, "INSERT INTO apiome.version_path (version_id, pathname) VALUES (%s, '/b')", (env["version"],))
    assert _stamp(env) == 2


# ───────────────────────────── what does not bump ─────────────────────────────


def test_reads_do_not_bump(env, monkeypatch) -> None:
    db, version = env["db"], env["version"]
    cls = str(db.create_class(version, "Order", {"type": "object"})["id"])
    db.create_path(version, "/orders")
    before = _stamp(env)

    db.get_version_by_id(version, env["tenant"])
    db.get_classes_for_version(version)
    db.get_class_by_id(cls, env["tenant"])
    db.get_paths_for_version(version)
    db.get_servers_for_version(version)
    import app.database as database_module
    from app.openapi_generator import generate_openapi_spec

    monkeypatch.setattr(database_module, "db", db)
    generate_openapi_spec("t", "orders", "1.0.0", db.get_classes_for_version(version), {}, version_db_id=version)

    assert _stamp(env) == before


def test_no_op_and_canvas_only_updates_do_not_bump(env) -> None:
    db, version = env["db"], env["version"]
    cls = str(db.create_class(version, "Order", {"type": "object"})["id"])
    before = _stamp(env)
    _one(env, "UPDATE apiome.classes SET name = name WHERE id = %s", (cls,))
    _one(env, "UPDATE apiome.classes SET updated_at = now() WHERE id = %s", (cls,))
    db.update_class(cls, env["tenant"], {"canvas_metadata": {"x": 10, "y": 20}})
    _one(env, "UPDATE apiome.versions SET description = description WHERE id = %s", (version,))
    assert _stamp(env) == before


def test_bookkeeping_columns_on_the_revision_do_not_bump(env) -> None:
    _one(
        env,
        "UPDATE apiome.versions SET quality_score = 80, quality_grade = 'B', updated_at = now() WHERE id = %s",
        (env["version"],),
    )
    assert _stamp(env) == 0


def test_bookkeeping_on_a_revision_with_generated_values_does_not_bump(env) -> None:
    """V422's generated lint count and sunset date are not content (DBP-1.15, #7198).

    In a BEFORE trigger NEW does not yet carry recomputed generated values, so unless the trigger
    ignores them a revision that has a lint count or a sunset date bumps on every bookkeeping write.
    """
    _one(
        env,
        "UPDATE apiome.versions SET quality_report = '{\"severity_counts\": {\"error\": 3}}'::jsonb "
        "WHERE id = %s",
        (env["version"],),
    )
    row = _one(env, "SELECT lint_error_count FROM apiome.versions WHERE id = %s", (env["version"],))
    assert row["lint_error_count"] == 3
    assert _stamp(env) == 0
    _one(env, "UPDATE apiome.versions SET metadata = metadata || '{\"sunsetAt\": \"2027-01-01\"}'::jsonb WHERE id = %s",
         (env["version"],))
    after_metadata = _stamp(env)
    assert after_metadata == 1  # metadata is content
    _one(
        env,
        "UPDATE apiome.versions SET quality_score = 70, updated_at = now() WHERE id = %s",
        (env["version"],),
    )
    assert _stamp(env) == after_metadata


# ───────────────────────────── publish counts (V424) ─────────────────────────────


def _counts(ctx: Dict[str, Any]) -> tuple:
    """The stored ``(operation_count, schema_count)`` of the seeded revision."""
    row = _one(ctx, "SELECT operation_count, schema_count FROM apiome.versions WHERE id = %s", (ctx["version"],))
    return row["operation_count"], row["schema_count"]


def _content(ctx: Dict[str, Any]) -> None:
    """Give the seeded revision two live classes, one deleted class and three operations."""
    db, version = ctx["db"], ctx["version"]
    for name in ("Order", "Customer", "Gone"):
        ctx[name] = str(db.create_class(version, name, {"type": "object"})["id"])
    db.delete_class(ctx["Gone"], ctx["tenant"])
    orders = str(db.create_path(version, "/orders")["id"])
    for method in ("get", "post"):
        db.create_operation(orders, method)
    db.create_operation(str(db.create_path(version, "/customers")["id"]), "get")


def _publish(ctx: Dict[str, Any]) -> None:
    """Publish the seeded revision with the statement shape both writers use."""
    _one(
        ctx,
        "UPDATE apiome.versions SET published = true, published_at = CURRENT_TIMESTAMP, "
        "visibility = 'public' WHERE id = %s",
        (ctx["version"],),
    )


def _requires_v424(ctx: Dict[str, Any]) -> None:
    found = _one(ctx, "SELECT to_regproc('apiome.set_version_publish_counts') AS f")
    if not found["f"]:
        pytest.skip("V424 not applied")


def test_a_draft_has_no_stored_counts(env) -> None:
    """Counts are recorded at publish (DBP-1.16, #7199); a draft's are NULL and readers count."""
    _requires_v424(env)
    _content(env)
    assert _counts(env) == (None, None)


def test_publishing_records_the_operation_and_live_schema_counts(env) -> None:
    _requires_v424(env)
    _content(env)
    _publish(env)
    # Three operations; two live classes (the deleted one is not counted).
    assert _counts(env) == (3, 2)


def test_publishing_an_empty_revision_records_zeros_not_nulls(env) -> None:
    _requires_v424(env)
    _publish(env)
    assert _counts(env) == (0, 0)


def test_recording_the_counts_is_not_a_content_change(env) -> None:
    """The two columns are in the stamp function's non-content list, so a backfill cannot bump."""
    _requires_v424(env)
    before = _stamp(env)
    _one(env, "UPDATE apiome.versions SET operation_count = 7, schema_count = 9 WHERE id = %s", (env["version"],))
    assert _stamp(env) == before
    _one(env, "UPDATE apiome.versions SET operation_count = NULL, schema_count = NULL WHERE id = %s", (env["version"],))
    assert _stamp(env) == before


def test_a_class_path_or_operation_write_clears_the_counts(env) -> None:
    """A published revision edited afterwards is counted by readers again, never shown stale."""
    _requires_v424(env)
    db, version = env["db"], env["version"]
    _content(env)
    writes = [
        ("create class", lambda: db.create_class(version, "Invoice", {"type": "object"})),
        ("delete class", lambda: db.delete_class(env["Order"], env["tenant"])),
        ("create path", lambda: env.setdefault("extra", str(db.create_path(version, "/invoices")["id"]))),
        ("create operation", lambda: db.create_operation(env["extra"], "get")),
    ]
    for label, write in writes:
        _publish(env)
        assert None not in _counts(env), label
        write()
        assert _counts(env) == (None, None), label


def test_other_content_writes_keep_the_counts(env) -> None:
    """Only the three counted tables clear them: a schema capture or a property edit does not."""
    _requires_v424(env)
    db = env["db"]
    _content(env)
    prop = _library_property(env)
    _publish(env)
    recorded = _counts(env)
    stamp = _stamp(env)

    db.add_property_to_class(env["Order"], prop, "id", None, {"type": "string"})
    _one(
        env,
        "INSERT INTO apiome.class_schema (version_id, class_id, schema) VALUES (%s, %s, '{}'::jsonb)",
        (env["version"], env["Customer"]),
    )
    _one(env, "UPDATE apiome.versions SET description = 'Orders API' WHERE id = %s", (env["version"],))
    assert _stamp(env) > stamp, "these are content writes: the stamp moves"
    assert _counts(env) == recorded, "but the operation and schema counts are unchanged"


def test_republishing_fills_cleared_counts_and_unpublishing_clears_them(env) -> None:
    _requires_v424(env)
    db, version = env["db"], env["version"]
    _content(env)
    _publish(env)
    db.create_class(version, "Invoice", {"type": "object"})
    assert _counts(env) == (None, None)
    _publish(env)  # published → published, with the counts missing
    assert _counts(env) == (3, 3)
    _one(env, "UPDATE apiome.versions SET published = false, published_at = NULL WHERE id = %s", (version,))
    assert _counts(env) == (None, None)


def test_a_write_after_publish_in_the_same_transaction_clears_the_counts(env) -> None:
    """Publish then edit in one transaction: the edit still clears what the publish recorded."""
    _requires_v424(env)
    _content(env)
    conn = env["conn"]
    with conn.cursor() as cur:
        cur.execute("UPDATE apiome.versions SET published = true WHERE id = %s", (env["version"],))
        cur.execute(
            "INSERT INTO apiome.classes (version_id, name, schema) VALUES (%s, 'Late', '{}'::jsonb)",
            (env["version"],),
        )
    conn.commit()
    assert _counts(env) == (None, None)


def test_writes_to_unrendered_tables_do_not_bump(env) -> None:
    _one(
        env,
        "INSERT INTO apiome.groups (version_id, name) VALUES (%s, 'Billing')",
        (env["version"],),
    )
    assert _stamp(env) == 0


# ───────────────────────────── fan-out, savepoints, deletes ─────────────────────────────


def test_editing_a_library_property_bumps_every_revision_using_it(env) -> None:
    db = env["db"]
    prop = _library_property(env)
    other = str(db.create_version(env["project"], env["user"], "2.0.0")["id"])
    unrelated = str(db.create_version(env["project"], env["user"], "3.0.0")["id"])
    for version in (env["version"], other):
        cls = str(db.create_class(version, "Order", {"type": "object"})["id"])
        db.add_property_to_class(cls, prop, "id", None, {"type": "string"})
    before = {v: _stamp(env, v) for v in (env["version"], other, unrelated)}

    db.update_property(prop, env["project"], {"description": "Order id"})

    assert _stamp(env, env["version"]) == before[env["version"]] + 1
    assert _stamp(env, other) == before[other] + 1
    assert _stamp(env, unrelated) == before[unrelated]


def test_moving_a_row_between_revisions_bumps_both(env) -> None:
    db = env["db"]
    other = str(db.create_version(env["project"], env["user"], "2.0.0")["id"])
    path = str(db.create_path(env["version"], "/orders")["id"])
    before = (_stamp(env), _stamp(env, other))
    _one(env, "UPDATE apiome.version_path SET version_id = %s WHERE id = %s", (other, path))
    assert (_stamp(env), _stamp(env, other)) == (before[0] + 1, before[1] + 1)


def test_a_rolled_back_savepoint_undoes_its_bump(env) -> None:
    conn, version = env["conn"], env["version"]
    with conn.cursor() as cur:
        cur.execute("SAVEPOINT s")
        cur.execute("INSERT INTO apiome.version_path (version_id, pathname) VALUES (%s, '/a')", (version,))
        cur.execute("ROLLBACK TO SAVEPOINT s")
        cur.execute("SELECT content_stamp FROM apiome.versions WHERE id = %s", (version,))
        assert cur.fetchone()["content_stamp"] == 0
        cur.execute("INSERT INTO apiome.version_path (version_id, pathname) VALUES (%s, '/b')", (version,))
    conn.commit()
    assert _stamp(env) == 1


def test_deleting_a_revision_with_its_rows_still_works(env) -> None:
    db, version = env["db"], env["version"]
    cls = str(db.create_class(version, "Order", {"type": "object"})["id"])
    db.add_property_to_class(cls, _library_property(env), "id", None, {"type": "string"})
    path = str(db.create_path(version, "/orders")["id"])
    db.create_operation(path, "get")
    with env["conn"].cursor() as cur:
        cur.execute("DELETE FROM apiome.classes WHERE version_id = %s", (version,))
        cur.execute("DELETE FROM apiome.versions WHERE id = %s RETURNING id", (version,))
        assert cur.fetchone() is not None
    env["conn"].commit()
    assert db.get_version_content_stamp(version) is None


def _three_revisions(ctx: Dict[str, Any]) -> List[str]:
    db = ctx["db"]
    extra = [str(db.create_version(ctx["project"], ctx["user"], v)["id"]) for v in ("2.0.0", "3.0.0")]
    return [ctx["version"], *extra]


def test_one_multi_row_statement_over_many_revisions_bumps_each_once(env) -> None:
    """DBP-1.19 (#7202): INSERT, UPDATE and DELETE statements touching rows of three revisions."""
    versions = _three_revisions(env)
    before = [_stamp(env, v) for v in versions]
    _one(
        env,
        "INSERT INTO apiome.classes (version_id, name, schema) "
        "SELECT v, n, '{\"type\": \"object\"}'::jsonb FROM unnest(%s::uuid[]) v, "
        "unnest(ARRAY['A', 'B']) n",
        (versions,),
    )
    after_insert = [_stamp(env, v) for v in versions]
    assert after_insert == [b + 1 for b in before]

    _one(env, "UPDATE apiome.classes SET description = 'x' WHERE version_id = ANY(%s::uuid[])", (versions,))
    after_update = [_stamp(env, v) for v in versions]
    assert after_update == [b + 1 for b in after_insert]

    _one(env, "DELETE FROM apiome.classes WHERE version_id = ANY(%s::uuid[])", (versions,))
    assert [_stamp(env, v) for v in versions] == [b + 1 for b in after_update]


def test_a_statement_bumps_only_the_revisions_whose_rows_really_changed(env) -> None:
    versions = _three_revisions(env)
    for v in versions:
        env["db"].create_class(v, "Order", {"type": "object"})
    before = [_stamp(env, v) for v in versions]
    # Every row gets a new updated_at, but only the middle revision's description changes.
    _one(
        env,
        "UPDATE apiome.classes SET updated_at = now() + interval '1 minute', "
        "description = CASE WHEN version_id = %s THEN 'changed' ELSE description END "
        "WHERE version_id = ANY(%s::uuid[])",
        (versions[1], versions),
    )
    assert [_stamp(env, v) for v in versions] == [before[0], before[1] + 1, before[2]]


def test_an_updated_at_only_statement_over_many_rows_does_not_bump(env) -> None:
    versions = _three_revisions(env)
    for v in versions:
        env["db"].create_class(v, "Order", {"type": "object"})
    before = [_stamp(env, v) for v in versions]
    _one(env, "UPDATE apiome.classes SET updated_at = now() + interval '1 hour' WHERE version_id = ANY(%s::uuid[])", (versions,))
    assert [_stamp(env, v) for v in versions] == before


def test_a_statement_that_matches_no_rows_does_not_bump(env) -> None:
    before = _stamp(env)
    _one(env, "UPDATE apiome.classes SET description = 'x' WHERE false")
    _one(env, "DELETE FROM apiome.classes WHERE false")
    assert _stamp(env) == before


def test_the_marks_hold_across_statements_in_one_transaction(env) -> None:
    versions = _three_revisions(env)
    before = [_stamp(env, v) for v in versions]
    with env["conn"].cursor() as cur:
        for _ in range(2):
            cur.execute(
                "INSERT INTO apiome.classes (version_id, name, schema) "
                "SELECT v, gen_random_uuid()::text, '{}'::jsonb FROM unnest(%s::uuid[]) v",
                (versions,),
            )
        cur.execute("SELECT current_setting('apiome.content_stamp_bumped') AS marks")
        marks = cur.fetchone()["marks"]
    env["conn"].commit()
    assert all(v in marks for v in versions)
    assert [_stamp(env, v) for v in versions] == [b + 1 for b in before]


# ───────────────────────────── coverage guard ─────────────────────────────


def _rows(ctx: Dict[str, Any], sql: str) -> List[Dict[str, Any]]:
    with ctx["conn"].cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()
    ctx["conn"].commit()
    return rows


def test_every_table_referencing_revision_content_is_covered_or_exempt(env) -> None:
    covered = {
        r["t"]
        for r in _rows(
            env,
            "SELECT c.relname AS t FROM pg_trigger g JOIN pg_class c ON c.oid = g.tgrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'apiome' AND g.tgname IN ('trg_content_stamp', 'trg_content_stamp_insert')",
        )
    }
    references = _rows(
        env,
        "SELECT DISTINCT src.relname AS t, dst.relname AS target FROM pg_constraint k "
        "JOIN pg_class src ON src.oid = k.conrelid JOIN pg_class dst ON dst.oid = k.confrelid "
        "JOIN pg_namespace n ON n.oid = src.relnamespace "
        "WHERE k.contype = 'f' AND n.nspname = 'apiome'",
    )
    referencing = {r["t"] for r in references if r["target"] in covered}
    unclassified = sorted(referencing - covered - set(NOT_RENDERED) - {"versions"})
    assert not unclassified, (
        "These tables reference a revision's content but neither carry trg_content_stamp nor are "
        f"listed in NOT_RENDERED: {unclassified}. Add a trigger in a migration (see V403) or an "
        "exemption with its reason."
    )
    stale = sorted(set(NOT_RENDERED) & covered)
    assert not stale, f"Covered tables still listed as not rendered: {stale}"


def test_every_content_stamp_trigger_uses_the_one_function(env) -> None:
    """The revision row keeps its row trigger; every other table has one statement-level trigger
    per event with the matching transition table (DBP-1.19, #7202)."""
    rows = _rows(
        env,
        "SELECT c.relname AS t, g.tgname AS name, p.proname AS fn, g.tgnargs AS nargs, "
        "g.tgtype AS tgtype, g.tgoldtable AS old_table, g.tgnewtable AS new_table "
        "FROM pg_trigger g JOIN pg_class c ON c.oid = g.tgrelid JOIN pg_proc p ON p.oid = g.tgfoid "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'apiome' AND g.tgname LIKE 'trg\\_content\\_stamp%'",
    )
    assert {r["fn"] for r in rows} == {"bump_version_content_stamp"}
    row_level, before, ins, dele, upd = 1, 2, 4, 8, 16
    by_table: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        by_table.setdefault(r["t"], {})[r["name"]] = r
    versions = by_table.pop("versions")
    assert set(versions) == {"trg_content_stamp"}
    assert versions["trg_content_stamp"]["nargs"] == 0
    assert versions["trg_content_stamp"]["tgtype"] == row_level | before | upd
    for table, triggers in by_table.items():
        assert set(triggers) == {
            "trg_content_stamp_insert",
            "trg_content_stamp_update",
            "trg_content_stamp_delete",
        }, table
        for name, event, old_table, new_table in (
            ("trg_content_stamp_insert", ins, None, "new_rows"),
            ("trg_content_stamp_update", upd, "old_rows", "new_rows"),
            ("trg_content_stamp_delete", dele, "old_rows", None),
        ):
            r = triggers[name]
            assert r["nargs"] == 1, (table, name)
            assert r["tgtype"] == event, (table, name)  # statement-level: no row bit, AFTER
            assert (r["old_table"], r["new_table"]) == (old_table, new_table), (table, name)
    for table in (
        "classes",
        "class_properties",
        "properties",
        "version_path",
        "path_operation",
        "version_server",
        "version_security_scheme",
        "version_component_pins",
    ):
        assert table in by_table, table


def test_every_resolver_query_is_valid(env) -> None:
    rows = _rows(
        env,
        "SELECT DISTINCT c.relname AS t, encode(g.tgargs, 'escape') AS arg FROM pg_trigger g "
        "JOIN pg_class c ON c.oid = g.tgrelid WHERE g.tgname = 'trg_content_stamp_insert'",
    )
    assert rows
    for r in rows:
        resolver = r["arg"].split("\\000")[0]
        if resolver.isidentifier():
            template = f"SELECT r.{resolver} FROM {{rows}} r"
        else:
            template = resolver
        empty = f"(SELECT * FROM apiome.{r['t']} WHERE false)"
        with env["conn"].cursor() as cur:
            cur.execute(template.replace("{rows}", empty))
            assert cur.fetchall() == [], r["t"]
        env["conn"].rollback()


def test_every_update_filter_is_valid(env) -> None:
    """The primary-key / changed-column predicates build and plan for every stamped table."""
    rows = _rows(
        env,
        "SELECT DISTINCT c.oid::regclass::text AS rel, c.relname AS t FROM pg_trigger g "
        "JOIN pg_class c ON c.oid = g.tgrelid WHERE g.tgname = 'trg_content_stamp_update'",
    )
    assert rows
    for r in rows:
        with env["conn"].cursor() as cur:
            cur.execute("SELECT key_match, any_diff FROM apiome.content_stamp_row_filters(%s::regclass)", (r["rel"],))
            f = cur.fetchone()
            cur.execute(
                f"SELECT count(*) AS n FROM {r['rel']} n JOIN {r['rel']} o ON {f['key_match']} "
                f"WHERE {f['any_diff']} AND false"
            )
        env["conn"].rollback()
        assert "updated_at" not in f["any_diff"], r["t"]


# ───────────────────────────── online migration and document tables ─────────────────────────────


def test_the_stamp_column_was_added_without_a_rewrite(env) -> None:
    """V403 added the stamp online: a constant default, so PostgreSQL stored it in the catalog.

    The catalog flag that showed it (``pg_attribute.atthasmissing``) is cleared by any later table
    rewrite, and V422 (DBP-1.15, #7198) rewrites ``versions`` on purpose to store its generated
    columns, so the statement itself is checked; the column's type and nullability still are.
    """
    row = _rows(
        env,
        "SELECT format_type(a.atttypid, a.atttypmod) AS type, a.attnotnull AS nn "
        "FROM pg_attribute a WHERE a.attrelid = 'apiome.versions'::regclass AND a.attname = 'content_stamp'",
    )[0]
    assert row["type"] == "bigint" and row["nn"] is True
    v403 = (REPO_SCRIPTS / "V403__document_objects_content_stamp_7078.sql").read_text(encoding="utf-8")
    assert "ADD COLUMN IF NOT EXISTS content_stamp bigint NOT NULL DEFAULT 0;" in v403


def _object(ctx: Dict[str, Any], sha: str = "a" * 64) -> str:
    return _one(
        ctx,
        "INSERT INTO apiome.document_objects (tenant_id, sha256, size_bytes, media_type, backend, storage_key) "
        "VALUES (%s, %s, 10, 'application/json', 'db', %s) RETURNING id::text AS id",
        (ctx["tenant"], sha, f"tenants/{ctx['tenant']}/objects/sha256/{sha[:2]}/{sha}"),
    )["id"]


def _refused(ctx: Dict[str, Any], sql: str, params: tuple) -> None:
    with ctx["conn"].cursor() as cur:
        with pytest.raises(psycopg2.IntegrityError):
            cur.execute(sql, params)
    ctx["conn"].rollback()


_VD = (
    "INSERT INTO apiome.version_documents "
    "(version_id, role, object_id, part_path, content_stamp, generator, generator_version) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s)"
)


def test_document_objects_are_unique_per_tenant_and_digest(env) -> None:
    obj = _object(env)
    try:
        _refused(
            env,
            "INSERT INTO apiome.document_objects (tenant_id, sha256, size_bytes, backend, storage_key) "
            "VALUES (%s, %s, 1, 'db', 'k')",
            (env["tenant"], "a" * 64),
        )
        _refused(
            env,
            "INSERT INTO apiome.document_objects (tenant_id, sha256, size_bytes, backend, storage_key) "
            "VALUES (%s, %s, 1, 'ftp', 'k')",
            (env["tenant"], "b" * 64),
        )
    finally:
        _one(env, "DELETE FROM apiome.document_objects WHERE id = %s", (obj,))


def test_version_documents_enforce_roles_and_provenance(env) -> None:
    version, obj = env["version"], _object(env)
    try:
        # A fileset: the manifest as the original plus one row per part.
        _one(env, _VD, (version, "original", obj, None, None, None, None))
        _one(env, _VD, (version, "original_part", obj, "workflows/pay.arazzo.yaml", None, None, None))
        _one(env, _VD, (version, "original_part", obj, "openapi/pay.yaml", None, None, None))
        _one(env, _VD, (version, "rendered_openapi", obj, None, 3, "openapi_generator", "1.0.0"))
        _one(env, _VD, (version, "rendered_openapi", obj, None, 4, "openapi_generator", "1.0.0"))

        _refused(env, _VD, (version, "original", obj, None, None, None, None))  # one original
        _refused(env, _VD, (version, "original_part", obj, None, None, None, None))  # part needs a path
        _refused(env, _VD, (version, "original", obj, "x.yaml", None, None, None))  # only parts have one
        _refused(env, _VD, (version, "rendered_canonical", obj, None, None, "g", "1"))  # needs a stamp
        _refused(env, _VD, (version, "rendered_openapi", obj, None, 3, "openapi_generator", "1.0.0"))
        _refused(env, _VD, (version, "draft", obj, None, None, None, None))
        # Document metadata is derived: writing it never bumps the stamp.
        assert _stamp(env) == 0
    finally:
        _one(env, "DELETE FROM apiome.version_documents WHERE version_id = %s", (version,))
        _one(env, "DELETE FROM apiome.document_objects WHERE id = %s", (obj,))
