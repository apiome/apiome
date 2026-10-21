"""Copying a version's paths into a new version — #771.

Two layers:

* the pure pieces of :mod:`app.version_path_copy` (the generated SQL, the canvas id rewrite,
  the table order);
* the copy itself against a live Postgres, through ``Database.create_version_push_transaction``
  inside the always-rolled-back ``tx`` fixture: a ``petstore`` revision with two classes, one
  path, two operations and every kind of row under a path, pushed to a new revision with and
  without ``copy_paths``. A schema-drift guard checks that every table and column under
  ``version_path`` is accounted for, so a column added later cannot be dropped silently.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict

import pytest

from app.version_path_copy import (
    CHILD_TABLES,
    MAP_TABLE,
    child_table_sql,
    copy_paths_between_versions,
    remap_canvas_ids,
)
from tests.test_catalog_graph_db import tx  # noqa: F401 - the fixture

# ---------------------------------------------------------------------------------------
# The pure pieces
# ---------------------------------------------------------------------------------------


def test_child_tables_list_parents_before_children():
    seen = {"path"}
    for spec in CHILD_TABLES:
        assert spec.parent[1] in seen, f"{spec.table}: parent {spec.parent[1]} not copied yet"
        for kind in spec.links.values():
            assert kind in seen, f"{spec.table}: link {kind} not copied yet"
        seen.add(spec.kind)


def test_child_table_sql_maps_then_inserts_through_the_map():
    spec = next(s for s in CHILD_TABLES if s.table == "shared_path_response")
    map_sql, insert_sql = child_table_sql(spec)
    assert map_sql.startswith(f"INSERT INTO {MAP_TABLE} (kind, old_id, new_id) SELECT 'shared_response', t.id")
    assert "pm.kind = 'path' AND pm.old_id = t.version_path_id" in map_sql
    assert insert_sql.startswith(
        "INSERT INTO apiome.shared_path_response (id, version_path_id, class_id, status_code, description, data,"
    )
    # The class id is re-pointed when the class was copied, else kept.
    assert "COALESCE((SELECT cm.new_id FROM" in insert_sql
    assert "cm.kind = 'class' AND cm.old_id = t.class_id), t.class_id)" in insert_sql


def test_child_table_sql_joins_a_link_tables_second_parent():
    spec = next(s for s in CHILD_TABLES if s.table == "path_operation_parameter_link")
    _, insert_sql = child_table_sql(spec)
    assert "(id, path_operation_id, shared_path_parameter_id, metadata)" in insert_sql
    assert (
        "JOIN _version_path_copy_map lm0 "
        "ON lm0.kind = 'shared_parameter' AND lm0.old_id = t.shared_path_parameter_id"
    ) in insert_sql


def test_remap_canvas_ids_swaps_copied_ids_only():
    old_path, new_path = str(uuid.uuid4()), str(uuid.uuid4())
    keep = str(uuid.uuid4())
    text = json.dumps({"nodes": [{"id": f"path-node-{old_path.upper()}"}, {"id": keep}]})
    out = json.loads(remap_canvas_ids(text, {old_path: new_path}))
    assert out["nodes"][0]["id"] == f"path-node-{new_path}"
    assert out["nodes"][1]["id"] == keep


# ---------------------------------------------------------------------------------------
# Against a live Postgres
# ---------------------------------------------------------------------------------------


def _one(cursor: Any, sql: str, params: tuple = ()) -> Any:
    cursor.execute(sql, params)
    return cursor.fetchone()


def _seed(cursor: Any) -> Dict[str, Any]:
    """A project with revision 1.0.0: classes Pet + Owner and a fully populated /pets/{petId}."""
    user = _one(cursor, "SELECT id::text AS id FROM apiome.users LIMIT 1")["id"]
    suffix = uuid.uuid4().hex[:10]
    tenant = _one(
        cursor,
        "INSERT INTO apiome.tenants (name, slug) VALUES (%s, %s) RETURNING id::text AS id",
        (f"paths {suffix}", f"paths-{suffix}"),
    )["id"]
    project = _one(
        cursor,
        "INSERT INTO apiome.projects (tenant_id, creator_id, name, slug) "
        "VALUES (%s, %s, %s, %s) RETURNING id::text AS id",
        (tenant, user, "Petstore", f"petstore-{suffix}"),
    )["id"]
    version = _one(
        cursor,
        "INSERT INTO apiome.versions (project_id, creator_id, version_id) "
        "VALUES (%s, %s, '1.0.0') RETURNING id::text AS id",
        (project, user),
    )["id"]
    prop = _one(
        cursor,
        "INSERT INTO apiome.properties (project_id, name, data) "
        "VALUES (%s, 'name', '{\"type\":\"string\"}') RETURNING id::text AS id",
        (project,),
    )["id"]
    classes = {}
    for name in ("Pet", "Owner"):
        classes[name] = _one(
            cursor,
            "INSERT INTO apiome.classes (version_id, name, schema) VALUES (%s, %s, '{}') RETURNING id::text AS id",
            (version, name),
        )["id"]
    path = _one(
        cursor,
        "INSERT INTO apiome.version_path (version_id, pathname, metadata) "
        "VALUES (%s, '/pets/{petId}', %s) RETURNING id::text AS id",
        (version, json.dumps({"summary": "One pet"})),
    )["id"]
    param = _one(
        cursor,
        "INSERT INTO apiome.shared_path_parameter (version_path_id, name, in_location, data) "
        "VALUES (%s, 'petId', 'path', '{\"type\":\"string\"}') RETURNING id::text AS id",
        (path,),
    )["id"]
    body = _one(
        cursor,
        "INSERT INTO apiome.shared_path_request_body (version_path_id, name, description) "
        "VALUES (%s, 'PetBody', 'A pet') RETURNING id::text AS id",
        (path,),
    )["id"]
    cursor.execute(
        "INSERT INTO apiome.shared_path_request_body_content (shared_path_request_body_id, media_type, class_id) "
        "VALUES (%s, 'application/json', %s)",
        (body, classes["Pet"]),
    )
    response = _one(
        cursor,
        "INSERT INTO apiome.shared_path_response (version_path_id, status_code, description, class_id) "
        "VALUES (%s, '200', 'OK', %s) RETURNING id::text AS id",
        (path, classes["Pet"]),
    )["id"]
    cursor.execute(
        "INSERT INTO apiome.shared_path_response_content (shared_path_response_id, media_type, class_id) "
        "VALUES (%s, 'application/json', %s)",
        (response, classes["Pet"]),
    )
    ops = {}
    for method in ("GET", "PUT"):
        ops[method] = _one(
            cursor,
            "INSERT INTO apiome.path_operation (version_path_id, operation, metadata) "
            "VALUES (%s, %s, '{}') RETURNING id::text AS id",
            (path, method),
        )["id"]
        cursor.execute(
            "INSERT INTO apiome.path_operation_description (path_operation_id, summary, operation_id) "
            "VALUES (%s, %s, %s)",
            (ops[method], f"{method} a pet", f"{method.lower()}Pet"),
        )
        cursor.execute(
            "INSERT INTO apiome.path_operation_parameter_link (path_operation_id, shared_path_parameter_id) "
            "VALUES (%s, %s)",
            (ops[method], param),
        )
        cursor.execute(
            "INSERT INTO apiome.path_operation_response_link (path_operation_id, shared_path_response_id) "
            "VALUES (%s, %s)",
            (ops[method], response),
        )
    cursor.execute(
        "INSERT INTO apiome.path_operation_request_body_link (path_operation_id, shared_path_request_body_id) "
        "VALUES (%s, %s)",
        (ops["PUT"], body),
    )
    cursor.execute(
        "INSERT INTO apiome.path_operation_schema (path_operation_id, class_id, property_id, name, data) "
        "VALUES (%s, %s, %s, 'body', '{}')",
        (ops["PUT"], classes["Pet"], prop),
    )
    cursor.execute(
        "INSERT INTO apiome.path_parameter (path_operation_id, name, in_location, data) "
        "VALUES (%s, 'verbose', 'query', '{}')",
        (ops["GET"],),
    )
    legacy_response = _one(
        cursor,
        "INSERT INTO apiome.path_response (path_operation_id, status_code, description) "
        "VALUES (%s, '404', 'Missing') RETURNING id::text AS id",
        (ops["GET"],),
    )["id"]
    content = _one(
        cursor,
        "INSERT INTO apiome.path_response_content (path_response_id, media_type) "
        "VALUES (%s, 'application/json') RETURNING id::text AS id",
        (legacy_response,),
    )["id"]
    cursor.execute(
        "INSERT INTO apiome.path_parameter_schema (path_response_content_id, class_id, property_id, data) "
        "VALUES (%s, %s, %s, '{}')",
        (content, classes["Owner"], prop),
    )
    canvas = {
        "nodes": [
            {"id": f"path-node-{path}"},
            {"id": ops["GET"]},
            {"id": f"class-{classes['Pet']}"},
        ],
        "edges": [{"source": f"path-node-{path}", "target": ops["GET"]}],
    }
    cursor.execute(
        "INSERT INTO apiome.version_path_canvas (version_path_id, canvas) VALUES (%s, %s::jsonb)",
        (path, json.dumps(canvas)),
    )
    return {
        "tenant": tenant, "project": project, "user": user, "version": version,
        "classes": classes, "path": path, "ops": ops,
    }


def _push(db: Any, seed: Dict[str, Any], *, copy_paths: bool, version_id: str = "1.1.0") -> Dict[str, Any]:
    full, copied = db.create_version_push_transaction(
        project_id=seed["project"],
        tenant_id=seed["tenant"],
        creator_id=seed["user"],
        version_id=version_id,
        description="next",
        change_log=None,
        commit_author=None,
        commit_message=None,
        external_ref=None,
        parent_version_id=seed["version"],
        source_version_id=seed["version"],
        branch_row=None,
        client_base_revision_id=seed["version"],
        copy_paths=copy_paths,
    )
    assert copied == 2
    return full


def _count(cursor: Any, sql: str, version: str) -> int:
    return _one(cursor, f"SELECT count(*) AS n FROM ({sql}) q", (version,))["n"]


_UNDER_VERSION = {
    "version_path": "SELECT p.id FROM apiome.version_path p WHERE p.version_id = %s",
    "path_operation": """SELECT o.id FROM apiome.path_operation o
        JOIN apiome.version_path p ON p.id = o.version_path_id WHERE p.version_id = %s""",
    "operation_links": """SELECT l.id FROM apiome.path_operation_parameter_link l
        JOIN apiome.path_operation o ON o.id = l.path_operation_id
        JOIN apiome.version_path p ON p.id = o.version_path_id WHERE p.version_id = %s""",
}


@pytest.mark.requires_db
def test_copy_paths_copies_every_row_and_repoints_classes(tx):  # noqa: F811 - the fixture
    db, cursor = tx
    seed = _seed(cursor)
    full = _push(db, seed, copy_paths=True)
    new = str(full["id"])
    assert full["copied_paths"] == 1
    assert full["copied_operations"] == 2

    new_classes = {
        r["name"]: r["id"]
        for r in (
            cursor.execute("SELECT name, id::text AS id FROM apiome.classes WHERE version_id = %s", (new,))
            or cursor.fetchall()
        )
    }
    path = _one(
        cursor, "SELECT id::text AS id, pathname, metadata FROM apiome.version_path WHERE version_id = %s", (new,)
    )
    assert path["pathname"] == "/pets/{petId}"
    assert path["metadata"] == {"summary": "One pet"}
    assert path["id"] != seed["path"]

    assert _count(cursor, _UNDER_VERSION["path_operation"], new) == 2
    assert _count(cursor, _UNDER_VERSION["operation_links"], new) == 2
    # Links point at the copy's shared parameter, never the source's.
    linked = _one(
        cursor,
        """SELECT sp.version_path_id::text AS path FROM apiome.path_operation_parameter_link l
           JOIN apiome.shared_path_parameter sp ON sp.id = l.shared_path_parameter_id
           JOIN apiome.path_operation o ON o.id = l.path_operation_id
           WHERE o.version_path_id = %s LIMIT 1""",
        (path["id"],),
    )
    assert linked["path"] == path["id"]

    # Every class reference re-points at the new version's class of the same name.
    refs = _one(
        cursor,
        """SELECT
             (SELECT class_id::text FROM apiome.shared_path_response WHERE version_path_id = %(p)s) AS response,
             (SELECT c.class_id::text FROM apiome.shared_path_response_content c
                JOIN apiome.shared_path_response r ON r.id = c.shared_path_response_id
                WHERE r.version_path_id = %(p)s) AS response_content,
             (SELECT c.class_id::text FROM apiome.shared_path_request_body_content c
                JOIN apiome.shared_path_request_body b ON b.id = c.shared_path_request_body_id
                WHERE b.version_path_id = %(p)s) AS body_content,
             (SELECT s.class_id::text FROM apiome.path_operation_schema s
                JOIN apiome.path_operation o ON o.id = s.path_operation_id
                WHERE o.version_path_id = %(p)s) AS op_schema,
             (SELECT ps.class_id::text FROM apiome.path_parameter_schema ps
                JOIN apiome.path_response_content rc ON rc.id = ps.path_response_content_id
                JOIN apiome.path_response pr ON pr.id = rc.path_response_id
                JOIN apiome.path_operation o ON o.id = pr.path_operation_id
                WHERE o.version_path_id = %(p)s) AS param_schema
        """,
        {"p": path["id"]},
    )
    assert refs == {
        "response": new_classes["Pet"],
        "response_content": new_classes["Pet"],
        "body_content": new_classes["Pet"],
        "op_schema": new_classes["Pet"],
        "param_schema": new_classes["Owner"],
    }

    # The canvas follows the copy: path, operation and class ids rewritten.
    canvas = _one(
        cursor, "SELECT canvas FROM apiome.version_path_canvas WHERE version_path_id = %s", (path["id"],)
    )["canvas"]
    text = json.dumps(canvas)
    assert f"path-node-{path['id']}" in text
    assert f"class-{new_classes['Pet']}" in text
    for old in (seed["path"], seed["ops"]["GET"], seed["classes"]["Pet"]):
        assert old not in text

    # The source is untouched.
    assert _count(cursor, _UNDER_VERSION["version_path"], seed["version"]) == 1
    assert _count(cursor, _UNDER_VERSION["path_operation"], seed["version"]) == 2


@pytest.mark.requires_db
def test_without_copy_paths_only_classes_are_copied(tx):  # noqa: F811 - the fixture
    db, cursor = tx
    seed = _seed(cursor)
    full = _push(db, seed, copy_paths=False)
    assert "copied_paths" not in full
    assert _count(cursor, _UNDER_VERSION["version_path"], str(full["id"])) == 0


@pytest.mark.requires_db
def test_copying_a_version_with_no_paths_copies_nothing_more(tx):  # noqa: F811 - the fixture
    db, cursor = tx
    seed = _seed(cursor)
    cursor.execute("DELETE FROM apiome.version_path WHERE version_id = %s", (seed["version"],))
    full = _push(db, seed, copy_paths=True)
    assert full["copied_paths"] == 0
    assert full["copied_operations"] == 0


@pytest.mark.requires_db
def test_two_copies_in_one_transaction_reuse_the_map(tx):  # noqa: F811 - the fixture
    """The temp map is truncated per call, so a second copy in the same transaction is clean."""
    db, cursor = tx
    seed = _seed(cursor)
    first = _push(db, seed, copy_paths=True)
    other = _one(
        cursor,
        "INSERT INTO apiome.versions (project_id, creator_id, version_id) "
        "VALUES (%s, %s, '9.9.9') RETURNING id::text AS id",
        (seed["project"], seed["user"]),
    )["id"]
    db.copy_classes_from_version_for_merge(cursor, str(first["id"]), other)
    assert copy_paths_between_versions(cursor, str(first["id"]), other) == {"paths": 1, "operations": 2}
    assert _count(cursor, _UNDER_VERSION["path_operation"], other) == 2


@pytest.mark.requires_db
def test_every_table_and_column_under_a_path_is_copied(tx):  # noqa: F811 - the fixture
    """Schema-drift guard: a new table or column under version_path must be added to CHILD_TABLES."""
    _, cursor = tx
    cursor.execute(
        """
        WITH RECURSIVE fk AS (
          SELECT c.conrelid::regclass::text AS child, c.confrelid::regclass::text AS parent
          FROM pg_constraint c WHERE c.contype = 'f'
        ), tree AS (
          SELECT child FROM fk WHERE parent = 'apiome.version_path'
          UNION
          SELECT fk.child FROM fk JOIN tree ON fk.parent = tree.child
        )
        SELECT DISTINCT child FROM tree
        """
    )
    under = {r["child"].removeprefix("apiome.") for r in cursor.fetchall()}
    # Workflow steps resolve to an operation by id but belong to Arazzo workflows, not to a path.
    handled = {spec.table for spec in CHILD_TABLES} | {"version_path_canvas", "api_workflow_steps"}
    assert under <= handled, f"not copied: {sorted(under - handled)}"

    for spec in CHILD_TABLES:
        cursor.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = 'apiome' AND table_name = %s",
            (spec.table,),
        )
        columns = {r["column_name"] for r in cursor.fetchall()} - {"id", "created_at", "updated_at"}
        covered = {spec.parent[0], *spec.links, *spec.class_columns, *spec.columns}
        assert columns == covered, f"{spec.table}: {sorted(columns ^ covered)}"
