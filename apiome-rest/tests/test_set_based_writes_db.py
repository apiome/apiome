"""Set-based writes against Postgres — DBP-1.7 (#7190).

The statement budgets (the same count at 10 and at 2,000 classes) live in
``test_query_budgets_db.py``. These tests look at the rows:

* a **one-line source edit writes only the affected rows** — every other class, class property
  and path keeps its row and id (``DBP_SOURCE_EDIT_CLASSES`` sets the size; the nightly scale
  run uses 20,000);
* additions, deletions, renames and path changes applied as a difference leave the revision
  rendering to exactly the candidate;
* project properties are matched by ``properties.data_digest``, whatever key order the
  definition was written with, and never duplicated;
* fork and merge copies carry every property — nested ones with the right parent — and publish
  freezes one schema per class.

They skip when no database with V409 is reachable.
"""

from __future__ import annotations

import copy
import json
import os
from typing import Any, Dict, Iterator, List

import pytest

from app.source_apply_writer import plan_source_apply
from app.source_change_apply import build_canonical_writes
from tests.set_based_fixtures import (
    apply_candidate,
    class_name,
    class_spec,
    drop_project,
    drop_revision_rows,
    edited,
    fork_target_project,
    merged_document,
    new_revision,
)
from tests.test_content_stamp_db import env  # noqa: F401 - the seeded tenant/project/revision

pytestmark = pytest.mark.requires_db

#: Classes in the one-line-edit test. The acceptance criterion names a 20,000-class version.
EDIT_CLASSES = int(os.environ.get("DBP_SOURCE_EDIT_CLASSES", "2000"))


@pytest.fixture
def ctx(env: Dict[str, Any]) -> Iterator[Dict[str, Any]]:  # noqa: F811
    """The seeded revision, with the seed user allowed to apply source edits in the tenant."""
    conn = env["conn"]
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('apiome.idx_properties_project_data_digest') AS idx")
        if not cur.fetchone()["idx"]:
            conn.rollback()
            pytest.skip("V409 (properties.data_digest) not applied")
        cur.execute(
            "INSERT INTO apiome.tenant_administrators (tenant_id, user_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (env["tenant"], env["user"]),
        )
        cur.execute("SELECT slug FROM apiome.tenants WHERE id = %s::uuid", (env["tenant"],))
        env["tenant_slug"] = cur.fetchone()["slug"]
    conn.commit()
    try:
        yield env
    finally:
        drop_revision_rows(conn, [env["project"]])
        with conn.cursor() as cur:
            cur.execute("DELETE FROM apiome.tenant_administrators WHERE tenant_id = %s::uuid", (env["tenant"],))
        conn.commit()


def _rows(ctx: Dict[str, Any], sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    """Run one read and return its rows."""
    with ctx["conn"].cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    ctx["conn"].rollback()
    return rows


def _snapshot(ctx: Dict[str, Any], version: str) -> Dict[str, Any]:
    """Every class, class property and path row of a revision, by id."""
    classes = _rows(
        ctx,
        "SELECT id::text, name, schema->>'description' AS description, updated_at, deleted_at "
        "FROM apiome.classes WHERE version_id = %s::uuid",
        (version,),
    )
    properties = _rows(
        ctx,
        "SELECT cp.id::text, c.name AS class_name FROM apiome.class_properties cp "
        "JOIN apiome.classes c ON c.id = cp.class_id WHERE c.version_id = %s::uuid",
        (version,),
    )
    paths = _rows(
        ctx,
        "SELECT vp.id::text, vp.pathname, "
        "(SELECT array_agg(po.id::text ORDER BY po.id) FROM apiome.path_operation po "
        "WHERE po.version_path_id = vp.id) AS operations "
        "FROM apiome.version_path vp WHERE vp.version_id = %s::uuid",
        (version,),
    )
    return {
        "classes": {row["id"]: row for row in classes},
        "properties": {row["id"]: row["class_name"] for row in properties},
        "paths": {row["id"]: row for row in paths},
    }


def _applied(ctx: Dict[str, Any], version: str, candidate: Dict[str, Any], fingerprint: str) -> Dict[str, Any]:
    """Apply ``candidate`` and check the revision now renders to it."""
    result = apply_candidate(ctx, ctx["db"], version, fingerprint, candidate)
    assert result["applied"] is True
    _document, after = merged_document(ctx, ctx["db"], version)
    assert after == result["resultDigest"]
    return result


# ───────────────────────── source apply: only the difference ─────────────────────────


def test_a_one_line_source_edit_writes_only_the_affected_rows(ctx) -> None:
    db = ctx["db"]
    version = new_revision(ctx, db, "edit", class_spec(EDIT_CLASSES))
    before = _snapshot(ctx, version)
    assert len(before["classes"]) == EDIT_CLASSES
    assert len(before["properties"]) == EDIT_CLASSES * 3
    library_before = _rows(
        ctx, "SELECT count(*) AS n FROM apiome.properties WHERE project_id = %s::uuid", (ctx["project"],)
    )

    target = EDIT_CLASSES // 2
    document, fingerprint = merged_document(ctx, db, version)
    result = _applied(ctx, version, edited(document, target, "Edited in source."), fingerprint)
    assert result["counts"]["total"] == 1

    after = _snapshot(ctx, version)
    # Row counts before and after: nothing was soft-deleted and reinserted.
    assert len(after["classes"]) == EDIT_CLASSES
    assert len(after["properties"]) == EDIT_CLASSES * 3
    assert all(row["deleted_at"] is None for row in after["classes"].values())
    assert set(after["classes"]) == set(before["classes"]), "every class keeps its row"
    touched = [
        row["name"]
        for cid, row in after["classes"].items()
        if row["updated_at"] != before["classes"][cid]["updated_at"]
    ]
    assert touched == [class_name(target)]
    edited_row = next(row for row in after["classes"].values() if row["name"] == class_name(target))
    assert edited_row["description"] == "Edited in source."
    # The edited class's three properties were replaced; all others are the same rows.
    replaced = set(before["properties"]) - set(after["properties"])
    assert {before["properties"][pid] for pid in replaced} == {class_name(target)}
    assert len(replaced) == 3
    assert {after["properties"][pid] for pid in set(after["properties"]) - set(before["properties"])} == {
        class_name(target)
    }
    # Paths (and their operations) were not touched, although one refers to a class.
    assert after["paths"] == before["paths"]
    assert (
        _rows(ctx, "SELECT count(*) AS n FROM apiome.properties WHERE project_id = %s::uuid", (ctx["project"],))
        == library_before
    )


def test_additions_deletions_and_path_changes_apply_as_a_difference(ctx) -> None:
    db = ctx["db"]
    version = new_revision(ctx, db, "mixed", class_spec(12, paths=4))
    before = _snapshot(ctx, version)
    document, fingerprint = merged_document(ctx, db, version)

    candidate = copy.deepcopy(document)
    schemas = candidate["components"]["schemas"]
    del schemas[class_name(11)]  # nothing refers to it
    schemas["Added"] = {
        "type": "object",
        "title": "Added",
        "properties": {"id": {"type": "string"}, "weight": {"type": "number"}},
    }
    schemas[class_name(5)]["properties"]["note"] = {"type": "string", "maxLength": 80}
    paths = candidate["paths"]
    removed_path, changed_path, kept_path = "/things0003/{id}", "/things0001/{id}", "/things0000/{id}"
    del paths[removed_path]
    paths[changed_path]["get"]["summary"] = "Changed summary"
    paths["/added/{id}"] = copy.deepcopy(paths[kept_path])
    for method, operation in paths["/added/{id}"].items():
        operation["operationId"] = f"added{method}"
    _applied(ctx, version, candidate, fingerprint)

    after = _snapshot(ctx, version)
    live = {row["name"]: cid for cid, row in after["classes"].items() if row["deleted_at"] is None}
    was = {row["name"]: cid for cid, row in before["classes"].items()}
    assert set(live) == (set(was) - {class_name(11)}) | {"Added"}
    # The dropped class is soft-deleted (kept for retention), not removed.
    assert after["classes"][was[class_name(11)]]["deleted_at"] is not None
    # Every surviving class — the changed one too — keeps its id.
    assert all(live[name] == was[name] for name in was if name != class_name(11))
    by_path = {row["pathname"]: row for row in after["paths"].values()}
    was_path = {row["pathname"]: row for row in before["paths"].values()}
    assert set(by_path) == (set(was_path) - {removed_path}) | {"/added/{id}"}
    # Untouched paths keep their rows and operations; the changed one was recreated.
    for pathname in ("/things0000/{id}", "/things0002/{id}"):
        assert by_path[pathname] == was_path[pathname]
    assert by_path[changed_path]["id"] != was_path[changed_path]["id"]
    # A recreated path's content still points at the live class.
    refs = _rows(
        ctx,
        "SELECT c.name, c.deleted_at FROM apiome.shared_path_response r "
        "JOIN apiome.shared_path_response_content rc ON rc.shared_path_response_id = r.id "
        "JOIN apiome.classes c ON c.id = rc.class_id WHERE r.version_path_id = %s::uuid",
        (by_path[changed_path]["id"],),
    )
    assert refs and all(row["deleted_at"] is None for row in refs)


def test_a_candidate_that_changes_nothing_relational_writes_no_class_or_path(ctx) -> None:
    """A change the model does not absorb (a vendor key) is a claim; the rows stay as they are."""
    db = ctx["db"]
    version = new_revision(ctx, db, "vendor", class_spec(6))
    before = _snapshot(ctx, version)
    document, fingerprint = merged_document(ctx, db, version)
    candidate = copy.deepcopy(document)
    candidate["x-owner"] = "platform"
    result = _applied(ctx, version, candidate, fingerprint)
    assert result["claimCount"] >= 1
    assert _snapshot(ctx, version) == before


def test_the_plan_keeps_what_already_renders_to_the_candidate(ctx) -> None:
    db = ctx["db"]
    spec = class_spec(5)
    version = new_revision(ctx, db, "plan", spec)
    with ctx["conn"].cursor() as cur:
        row = db._source_apply_version_row(cur, ctx["tenant"], ctx["project"], version)
        _merged, _fp, _claims, canonical = db._cursor_current_merged_document(
            cur, ctx["tenant"], ctx["tenant_slug"], row, "3.1.0", with_canonical=True
        )
    ctx["conn"].rollback()
    plan = plan_source_apply(canonical, canonical)
    assert plan.keep_classes == frozenset(class_name(i) for i in range(5))
    assert len(plan.keep_paths) == 3
    assert plan.write_security_schemes is False and plan.write_servers is False


def test_a_full_rewrite_still_replaces_every_row(ctx) -> None:
    """Without a plan the writer keeps its old contract: soft-delete and recreate."""
    db = ctx["db"]
    spec = class_spec(4)
    version = new_revision(ctx, db, "full", spec)
    before = _snapshot(ctx, version)
    with ctx["conn"].cursor() as cur:
        db._cursor_write_canonical_rows(cur, ctx["project"], version, build_canonical_writes(spec))
    ctx["conn"].commit()
    after = _snapshot(ctx, version)
    live = {cid for cid, row in after["classes"].items() if row["deleted_at"] is None}
    assert len(live) == 4 and not live & set(before["classes"])
    assert all(after["classes"][cid]["deleted_at"] is not None for cid in before["classes"])
    assert not set(after["paths"]) & set(before["paths"])


# ───────────────────────── project properties by digest ─────────────────────────


def test_class_properties_link_to_the_library_property_with_the_same_definition(ctx) -> None:
    db = ctx["db"]
    # Written with another key order than the candidate will use.
    existing = str(
        db.create_property(ctx["project"], "code", None, {"maxLength": 8, "type": "string", "pattern": "^[A-Z]+$"})[
            "id"
        ]
    )
    spec = {
        "openapi": "3.1.0",
        "info": {"title": "Codes", "version": "1.0.0"},
        "paths": {},
        "components": {
            "schemas": {
                name: {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string", "pattern": "^[A-Z]+$", "maxLength": 8},
                        "label": {"type": "string", "minLength": 1},
                    },
                }
                for name in ("Alpha", "Beta", "Gamma")
            }
        },
    }
    version = new_revision(ctx, db, "library", spec)
    links = _rows(
        ctx,
        "SELECT cp.name, cp.property_id::text AS property_id FROM apiome.class_properties cp "
        "JOIN apiome.classes c ON c.id = cp.class_id WHERE c.version_id = %s::uuid AND c.deleted_at IS NULL",
        (version,),
    )
    assert {row["property_id"] for row in links if row["name"] == "code"} == {existing}
    labels = {row["property_id"] for row in links if row["name"] == "label"}
    assert len(labels) == 1 and None not in labels, "one new library property, shared by the three classes"
    library = _rows(
        ctx,
        "SELECT name, data_digest, md5(data::text) AS expected FROM apiome.properties WHERE project_id = %s::uuid",
        (ctx["project"],),
    )
    assert sorted(row["name"] for row in library) == ["code", "label"]
    assert all(row["data_digest"] == row["expected"] for row in library)


def test_the_digest_follows_the_definition(ctx) -> None:
    db = ctx["db"]
    prop = str(db.create_property(ctx["project"], "size", None, {"type": "integer"})["id"])
    first = _rows(ctx, "SELECT data_digest FROM apiome.properties WHERE id = %s::uuid", (prop,))[0]["data_digest"]
    with ctx["conn"].cursor() as cur:
        cur.execute(
            "UPDATE apiome.properties SET data = %s::jsonb WHERE id = %s::uuid",
            (json.dumps({"type": "integer", "minimum": 0}), prop),
        )
    ctx["conn"].commit()
    second = _rows(ctx, "SELECT data_digest FROM apiome.properties WHERE id = %s::uuid", (prop,))[0]["data_digest"]
    assert first != second


# ───────────────────────────── fork, merge copy, publish ─────────────────────────────


def _property_tree(ctx: Dict[str, Any], version: str) -> List[tuple]:
    """``(class, parent property, property, library id, data)`` for every class property."""
    rows = _rows(
        ctx,
        "SELECT c.name AS class_name, parent.name AS parent_name, cp.name, cp.property_id::text AS property_id, "
        "cp.data::text AS data FROM apiome.class_properties cp "
        "JOIN apiome.classes c ON c.id = cp.class_id AND c.deleted_at IS NULL "
        "LEFT JOIN apiome.class_properties parent ON parent.id = cp.parent_id "
        "WHERE c.version_id = %s::uuid",
        (version,),
    )
    return sorted(
        (row["class_name"], row["parent_name"] or "", row["name"], row["property_id"] or "", row["data"])
        for row in rows
    )


def _nest(ctx: Dict[str, Any], version: str, class_index: int) -> None:
    """Give one class a property with a child and a grandchild (as the class editor can)."""
    library = str(ctx["db"].create_property(ctx["project"], f"nested{class_index}", None, {"type": "object"})["id"])
    with ctx["conn"].cursor() as cur:
        cur.execute(
            "SELECT id FROM apiome.classes WHERE version_id = %s::uuid AND name = %s AND deleted_at IS NULL",
            (version, class_name(class_index)),
        )
        class_id = cur.fetchone()["id"]
        parent = None
        for name in ("address", "geo", "lat"):
            cur.execute(
                "INSERT INTO apiome.class_properties (class_id, property_id, name, data, parent_id) "
                "VALUES (%s, %s::uuid, %s, %s::jsonb, %s) RETURNING id",
                (class_id, library, name, json.dumps({"type": "object", "x-level": name}), parent),
            )
            parent = cur.fetchone()["id"]
    ctx["conn"].commit()


def test_a_merge_copy_carries_nested_properties_with_their_parents(ctx) -> None:
    db = ctx["db"]
    source = new_revision(ctx, db, "merge-source", class_spec(8))
    _nest(ctx, source, 2)
    _nest(ctx, source, 6)
    target = new_revision(ctx, db, "merge-target")
    with ctx["conn"].cursor() as cur:
        assert db.copy_classes_from_version_for_merge(cur, source, target) == 8
    ctx["conn"].commit()
    copied = _property_tree(ctx, target)
    assert copied == _property_tree(ctx, source)
    assert (class_name(2), "geo", "lat") in {row[:3] for row in copied}
    # The copies are new rows: no property id is shared between the two revisions.
    ids = _rows(
        ctx,
        "SELECT cp.id FROM apiome.class_properties cp JOIN apiome.classes c ON c.id = cp.class_id "
        "WHERE c.version_id = ANY(%s::uuid[])",
        ([source, target],),
    )
    assert len({row["id"] for row in ids}) == 2 * (8 * 3 + 6)


def test_copying_one_class_carries_its_nested_properties(ctx) -> None:
    db = ctx["db"]
    source = new_revision(ctx, db, "single-source", class_spec(3))
    _nest(ctx, source, 1)
    target = new_revision(ctx, db, "single-target")
    with ctx["conn"].cursor() as cur:
        assert db.copy_single_class_between_versions_for_merge(cur, source, target, class_name(1))["success"]
    ctx["conn"].commit()
    assert _property_tree(ctx, target) == [row for row in _property_tree(ctx, source) if row[0] == class_name(1)]


def test_a_fork_copies_classes_and_their_top_level_properties(ctx) -> None:
    db = ctx["db"]
    source = new_revision(ctx, db, "fork-source", class_spec(9))
    _nest(ctx, source, 4)
    fork_project = fork_target_project(ctx)
    try:
        fork = db.create_forked_version(fork_project, ctx["tenant"], ctx["user"], "1.0.0", None, None, source, None)
        assert fork["success"] is True and fork["copied_count"] == 9
        forked = str(fork["version"]["id"])
        top_level = [row for row in _property_tree(ctx, source) if row[1] == ""]
        assert _property_tree(ctx, forked) == top_level
        assert db.copy_classes_from_version(source, new_revision(ctx, db, "plain-copy"))["copied_count"] == 9
    finally:
        drop_project(ctx["conn"], fork_project)


def test_publish_freezes_one_schema_per_class_and_republish_updates_it(ctx) -> None:
    db = ctx["db"]
    version = new_revision(ctx, db, "publish", class_spec(7))
    assert db.publish_version(version, ctx["tenant"], ctx["user"])["published"] is True
    frozen = _rows(
        ctx,
        "SELECT c.name, s.id::text AS id, s.schema FROM apiome.class_schema s "
        "JOIN apiome.classes c ON c.id = s.class_id WHERE s.version_id = %s::uuid",
        (version,),
    )
    assert sorted(row["name"] for row in frozen) == [class_name(i) for i in range(7)]
    assert all(set(row["schema"]["properties"]) == {"id", "name", "parent"} for row in frozen)
    # Publishing again upserts the same rows (data records refer to them by id).
    with ctx["conn"].cursor() as cur:
        cur.execute(
            "UPDATE apiome.classes SET description = 'Changed' WHERE version_id = %s::uuid AND name = %s",
            (version, class_name(0)),
        )
    ctx["conn"].commit()
    db.publish_version(version, ctx["tenant"], ctx["user"])
    again = _rows(ctx, "SELECT id::text AS id FROM apiome.class_schema WHERE version_id = %s::uuid", (version,))
    assert {row["id"] for row in again} == {row["id"] for row in frozen}


def test_freezing_a_version_with_no_classes_writes_nothing(ctx) -> None:
    db = ctx["db"]
    version = new_revision(ctx, db, "empty")
    assert db.freeze_version_schema(version, ctx["tenant"], ctx["user"]) is not None
    assert (
        _rows(ctx, "SELECT count(*) AS n FROM apiome.class_schema WHERE version_id = %s::uuid", (version,))[0]["n"] == 0
    )
