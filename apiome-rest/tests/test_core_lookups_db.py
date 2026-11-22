"""Lean version / project lookups, one-statement writes and RETURNING re-reads, against Postgres.

DBP-1.5 (#7188). ``tests/test_core_lookups.py`` pins the SQL shape without a database; this module
runs the same methods on a migrated database:

* ``get_version_core`` / ``get_project_core`` agree with the full lookups on every column they
  return, and refuse other tenants and soft-deleted rows exactly as the full lookups do.
* ``update_class`` / ``delete_class`` / ``update_path`` / ``delete_path`` / ``update_operation`` /
  ``delete_operation`` run one statement and never touch another tenant's row.
* The MCP category / note / collection writes return the same row their detail read returns.

Skips when no database with V403 is reachable (see ``tests/test_content_stamp_db.py``).
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Iterator

import pytest

from app.statement_stats import CountingDictCursor, capture
from tests.test_content_stamp_db import env as stamp_env  # noqa: F401 - the seeded tenant/project/revision

pytestmark = pytest.mark.requires_db


@pytest.fixture
def ctx(stamp_env: Dict[str, Any]) -> Iterator[Dict[str, Any]]:  # noqa: F811
    """The seeded revision plus a second tenant, a class, a path and an operation; statements count."""
    conn = stamp_env["conn"]
    conn.cursor_factory = CountingDictCursor
    db = stamp_env["db"]
    suffix = uuid.uuid4().hex[:10]
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO apiome.tenants (name, slug) VALUES (%s, %s) RETURNING id::text AS id",
            (f"other {suffix}", f"other-{suffix}"),
        )
        stamp_env["other_tenant"] = cur.fetchone()["id"]
    conn.commit()
    stamp_env["class"] = str(db.create_class(stamp_env["version"], "Pet", {"type": "object"})["id"])
    stamp_env["path"] = str(db.create_path(stamp_env["version"], "/pets")["id"])
    stamp_env["operation"] = str(db.create_operation(stamp_env["path"], "get")["id"])
    try:
        yield stamp_env
    finally:
        conn.rollback()
        with conn.cursor() as cur:
            for table in (
                "mcp_endpoint_notes",
                "mcp_collection_members",
                "mcp_collections",
                "mcp_endpoints",
                "mcp_categories",
            ):
                cur.execute(
                    f"DELETE FROM apiome.{table} WHERE tenant_id = ANY(%s::uuid[])",
                    ([stamp_env["tenant"], stamp_env["other_tenant"]],),
                )
            cur.execute("DELETE FROM apiome.tenants WHERE id = %s::uuid", (stamp_env["other_tenant"],))
        conn.commit()


def _count(call) -> tuple:
    """Run ``call``; return ``(result, statements_run)``."""
    with capture() as stats:
        result = call()
    return result, stats.count


# ───────────────────────────── core lookups ─────────────────────────────


def test_get_version_core_matches_the_full_lookup_on_its_columns(ctx) -> None:
    db = ctx["db"]
    full = db.get_version_by_id(ctx["version"], ctx["tenant"])
    core, statements = _count(lambda: db.get_version_core(ctx["version"], ctx["tenant"]))
    assert statements == 1
    assert core is not None and full is not None
    assert str(core["tenant_id"]) == ctx["tenant"]
    for key, value in core.items():
        if key != "tenant_id":
            assert full[key] == value, key
    # The heavy columns stay on the full lookup only.
    for key in (
        "metadata",
        "mock_settings",
        "change_log",
        "security_score",
        "creator_name",
        "fork_source_project_name",
    ):
        assert key in full and key not in core


def test_get_project_core_matches_the_full_lookup_on_its_columns(ctx) -> None:
    db = ctx["db"]
    full = db.get_project_by_id(ctx["project"], ctx["tenant"])
    core, statements = _count(lambda: db.get_project_core(ctx["project"], ctx["tenant"]))
    assert statements == 1
    assert core is not None and full is not None
    for key, value in core.items():
        assert full[key] == value, key
    for key in ("metadata", "versions_count", "quality_score", "quality_grade", "creator_name"):
        assert key in full and key not in core


def test_core_lookups_refuse_another_tenant_like_the_full_lookups(ctx) -> None:
    db = ctx["db"]
    other = ctx["other_tenant"]
    assert db.get_version_by_id(ctx["version"], other) is None
    assert db.get_version_core(ctx["version"], other) is None
    assert db.get_project_by_id(ctx["project"], other) is None
    assert db.get_project_core(ctx["project"], other) is None


def test_core_lookups_hide_soft_deleted_rows_like_the_full_lookups(ctx) -> None:
    db, conn = ctx["db"], ctx["conn"]
    with conn.cursor() as cur:
        cur.execute("UPDATE apiome.projects SET deleted_at = now() WHERE id = %s::uuid", (ctx["project"],))
    conn.commit()
    assert db.get_version_core(ctx["version"], ctx["tenant"]) is None  # its project is archived
    assert db.get_version_by_id(ctx["version"], ctx["tenant"]) is None
    assert db.get_project_core(ctx["project"], ctx["tenant"]) is None
    archived = db.get_project_core(ctx["project"], ctx["tenant"], include_deleted=True)
    assert archived is not None and archived["deleted_at"] is not None
    with conn.cursor() as cur:
        cur.execute("UPDATE apiome.projects SET deleted_at = NULL WHERE id = %s::uuid", (ctx["project"],))
        cur.execute("UPDATE apiome.versions SET deleted_at = now() WHERE id = %s::uuid", (ctx["version"],))
    conn.commit()
    assert db.get_version_core(ctx["version"], ctx["tenant"]) is None
    assert db.get_version_by_id(ctx["version"], ctx["tenant"]) is None


# ───────────────────────────── one-statement writes ─────────────────────────────


@pytest.mark.parametrize(
    ("update", "key", "fields", "getter"),
    [
        ("update_class", "class", {"name": "Dog"}, "get_class_by_id"),
        ("update_path", "path", {"pathname": "/dogs"}, "get_path_by_id"),
        ("update_operation", "operation", {"operation": "put"}, "get_operation_by_id"),
    ],
)
def test_an_update_is_one_statement_and_tenant_guarded(ctx, update, key, fields, getter) -> None:
    db = ctx["db"]
    before = getattr(db, getter)(ctx[key], ctx["tenant"])
    refused, statements = _count(lambda: getattr(db, update)(ctx[key], ctx["other_tenant"], fields))
    assert refused is None and statements == 1
    assert getattr(db, getter)(ctx[key], ctx["tenant"]) == before
    updated, statements = _count(lambda: getattr(db, update)(ctx[key], ctx["tenant"], fields))
    assert statements == 1
    assert str(updated["id"]) == ctx[key]
    stored = getattr(db, getter)(ctx[key], ctx["tenant"])
    for field in stored:
        assert updated[field] == stored[field], field
    # Nothing to set: the current row, read once.
    current, statements = _count(lambda: getattr(db, update)(ctx[key], ctx["tenant"], {}))
    assert statements == 1 and str(current["id"]) == ctx[key]


@pytest.mark.parametrize(
    ("delete", "key", "getter"),
    [
        ("delete_operation", "operation", "get_operation_by_id"),
        ("delete_path", "path", "get_path_by_id"),
        ("delete_class", "class", "get_class_by_id"),
    ],
)
def test_a_delete_is_one_statement_and_tenant_guarded(ctx, delete, key, getter) -> None:
    db = ctx["db"]
    refused, statements = _count(lambda: getattr(db, delete)(ctx[key], ctx["other_tenant"]))
    assert refused is False and statements == 1
    assert getattr(db, getter)(ctx[key], ctx["tenant"]) is not None
    deleted, statements = _count(lambda: getattr(db, delete)(ctx[key], ctx["tenant"]))
    assert deleted is True and statements == 1
    assert getattr(db, getter)(ctx[key], ctx["tenant"]) is None
    again, _ = _count(lambda: getattr(db, delete)(ctx[key], ctx["tenant"]))
    assert again is False


def test_a_class_rename_onto_a_taken_name_still_raises(ctx) -> None:
    """The route maps the unique violation to 409; the folded UPDATE must still raise it."""
    db = ctx["db"]
    db.create_class(ctx["version"], "Owner", {"type": "object"})
    with pytest.raises(Exception, match="(?i)unique"):
        db.update_class(ctx["class"], ctx["tenant"], {"name": "Owner"})
    ctx["conn"].rollback()


def test_update_project_is_one_statement_with_or_without_a_precondition(ctx) -> None:
    db = ctx["db"]
    current = db.get_project_core(ctx["project"], ctx["tenant"])
    updated, statements = _count(
        lambda: db.update_project(
            ctx["project"], ctx["tenant"], {"name": "Orders 2"}, expected_updated_at=current["updated_at"]
        )
    )
    assert statements == 1 and updated["name"] == "Orders 2"
    from app.database import ProjectUpdateConflict

    with pytest.raises(ProjectUpdateConflict) as exc:
        db.update_project(
            ctx["project"], ctx["tenant"], {"name": "Orders 3"}, expected_updated_at=current["updated_at"]
        )
    assert exc.value.current_updated_at == updated["updated_at"]
    assert db.get_project_core(ctx["project"], ctx["tenant"])["name"] == "Orders 2"
    assert db.update_project(ctx["project"], ctx["other_tenant"], {"name": "x"}) is None


# ───────────────────────────── RETURNING instead of re-reads ─────────────────────────────


def test_mcp_category_writes_return_the_detail_row(ctx) -> None:
    db = ctx["db"]
    created, statements = _count(
        lambda: db.create_mcp_category(
            ctx["tenant"], ctx["user"], slug="pets", label="Pets", description=None, sort_order=3
        )
    )
    assert statements == 1
    assert created == db.get_mcp_category(ctx["tenant"], "pets")
    assert created["builtin"] is False and created["endpoint_count"] == 0
    updated, statements = _count(lambda: db.update_mcp_category(ctx["tenant"], "pets", {"label": "Pets!"}))
    assert statements == 1
    assert updated == db.get_mcp_category(ctx["tenant"], "pets")
    assert db.update_mcp_category(ctx["other_tenant"], "pets", {"label": "x"}) is None


def _endpoint(ctx) -> str:
    with ctx["conn"].cursor() as cur:
        cur.execute(
            "INSERT INTO apiome.mcp_endpoints (tenant_id, creator_id, name, slug, endpoint_url, transport) "
            "VALUES (%s, %s, 'Pets MCP', %s, 'https://mcp.example.com/pets', 'streamable_http') "
            "RETURNING id::text AS id",
            (ctx["tenant"], ctx["user"], f"pets-{uuid.uuid4().hex[:6]}"),
        )
        endpoint = cur.fetchone()["id"]
    ctx["conn"].commit()
    return endpoint


def test_mcp_endpoint_note_writes_return_the_detail_row(ctx) -> None:
    db = ctx["db"]
    endpoint = _endpoint(ctx)
    created, statements = _count(
        lambda: db.create_mcp_endpoint_note(ctx["tenant"], endpoint, ctx["user"], body="first")
    )
    assert statements == 1
    assert created == db.get_mcp_endpoint_note(ctx["tenant"], endpoint, str(created["id"]))
    assert created["created_by_name"] is not None or created["created_by_email"] is not None
    updated, statements = _count(
        lambda: db.update_mcp_endpoint_note(ctx["tenant"], endpoint, str(created["id"]), ctx["user"], body="second")
    )
    assert statements == 1
    assert updated == db.get_mcp_endpoint_note(ctx["tenant"], endpoint, str(created["id"]))
    assert updated["body"] == "second"
    assert db.update_mcp_endpoint_note(ctx["other_tenant"], endpoint, str(created["id"]), ctx["user"], body="x") is None


def test_mcp_collection_writes_return_the_detail_row(ctx) -> None:
    db = ctx["db"]
    endpoint = _endpoint(ctx)
    created = db.create_mcp_collection(
        ctx["tenant"],
        ctx["user"],
        name="Pets",
        slug="pets",
        description=None,
        is_published=False,
        endpoint_ids=[endpoint],
    )
    assert created == db.get_mcp_collection(ctx["tenant"], str(created["id"]))
    assert created["member_count"] == 1
    updated, statements = _count(lambda: db.update_mcp_collection(ctx["tenant"], str(created["id"]), name="Pets 2"))
    assert statements == 1
    assert updated == db.get_mcp_collection(ctx["tenant"], str(created["id"]))
    assert db.update_mcp_collection(ctx["other_tenant"], str(created["id"]), name="x") is None


def test_delete_class_property_is_one_statement_and_tenant_guarded(ctx) -> None:
    db = ctx["db"]
    prop = db.add_property_to_class(ctx["class"], None, "owner", None, {"$ref": "#/components/schemas/Owner"})
    prop_id = str(prop["id"])
    refused, statements = _count(lambda: db.delete_class_property(prop_id, ctx["class"], ctx["other_tenant"]))
    assert refused is False and statements == 1
    wrong_class = db.create_class(ctx["version"], "Other", {"type": "object"})
    assert db.delete_class_property(prop_id, str(wrong_class["id"]), ctx["tenant"]) is False
    deleted, statements = _count(lambda: db.delete_class_property(prop_id, ctx["class"], ctx["tenant"]))
    assert deleted is True and statements == 1
    with ctx["conn"].cursor() as cur:
        cur.execute("SELECT 1 FROM apiome.class_properties WHERE id = %s::uuid", (prop_id,))
        assert cur.fetchone() is None
    ctx["conn"].commit()
