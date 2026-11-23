"""Shared builders for the set-based write tests — DBP-1.7 (#7190).

Used by ``test_query_budgets_db.py`` (statement budgets at 10 and 2,000 classes) and
``test_set_based_writes_db.py`` (the rows themselves).
"""

from __future__ import annotations

import copy
from typing import Any, Dict, Sequence, Tuple

from app.preservation_envelope import semantic_fingerprint
from app.source_change_apply import build_canonical_writes
from app.source_change_review import change_set_digest

#: The OAS dialect the test revisions are applied under.
DIALECT = "3.1.0"


def class_name(index: int) -> str:
    """The name of the ``index``-th class of :func:`class_spec`."""
    return f"Thing{index:05d}"


def class_spec(classes: int, paths: int = 3) -> Dict[str, Any]:
    """An OpenAPI document with ``classes`` schemas and ``paths`` paths.

    Every class has three properties: ``id`` and ``name`` (the same definition in every class, so
    they share one project property each) and ``parent`` (a ``$ref`` to the first class). Each
    path has a GET and a POST whose content refers to a class.
    """
    schemas: Dict[str, Any] = {}
    for i in range(classes):
        schemas[class_name(i)] = {
            "type": "object",
            "description": f"Thing number {i}.",
            "properties": {
                "id": {"type": "string"},
                "name": {"type": "string"},
                "parent": {"$ref": f"#/components/schemas/{class_name(0)}"},
            },
        }
    header = {"X-Request-Id": {"schema": {"type": "string"}}}
    path_items: Dict[str, Any] = {}
    for i in range(paths):
        ref = {"schema": {"$ref": f"#/components/schemas/{class_name(i % classes)}"}}
        responses = {
            "200": {"description": "OK", "headers": header, "content": {"application/json": ref}},
            "404": {"description": "Missing", "headers": header, "content": {"application/json": {"schema": {"type": "object"}}}},
        }
        parameters = [{"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}]
        path_items[f"/things{i:04d}/{{id}}"] = {
            "get": {"operationId": f"get{i}", "summary": f"Get {i}", "parameters": parameters, "responses": responses},
            "post": {
                "operationId": f"post{i}",
                "summary": f"Post {i}",
                "parameters": parameters,
                "requestBody": {"content": {"application/json": ref}},
                "responses": responses,
            },
        }
    return {
        "openapi": "3.1.0",
        "info": {"title": "Things", "version": "1.0.0"},
        "components": {"schemas": schemas},
        "paths": path_items,
    }


def new_revision(ctx: Dict[str, Any], db: Any, label: str, spec: Dict[str, Any] | None = None) -> str:
    """A new revision of the seeded project, holding ``spec``'s rows when given.

    Returns:
        The revision's ``versions.id``.
    """
    version = str(db.create_version(ctx["project"], ctx["user"], label)["id"])
    if spec is not None:
        with ctx["conn"].cursor() as cur:
            db._cursor_write_canonical_rows(cur, ctx["project"], version, build_canonical_writes(spec))
        ctx["conn"].commit()
    return version


def merged_document(ctx: Dict[str, Any], db: Any, version: str) -> Tuple[Dict[str, Any], str]:
    """The revision's current merged document and its fingerprint (what a source editor opens)."""
    with ctx["conn"].cursor() as cur:
        row = db._source_apply_version_row(cur, ctx["tenant"], ctx["project"], version)
        merged, fingerprint, _claims = db._cursor_current_merged_document(
            cur, ctx["tenant"], ctx["tenant_slug"], row, DIALECT
        )
    ctx["conn"].rollback()
    return merged, fingerprint


def apply_candidate(ctx: Dict[str, Any], db: Any, version: str, base_digest: str, candidate: Dict[str, Any]) -> Dict[str, Any]:
    """Apply ``candidate`` to ``version`` the way the review endpoint's caller would."""
    candidate_digest = semantic_fingerprint(candidate).fingerprint
    return db.apply_source_change_set(
        ctx["tenant"],
        ctx["tenant_slug"],
        ctx["project"],
        version,
        actor_id=ctx["user"],
        candidate_document=candidate,
        source_format="json",
        source_digest="sha256:test",
        base_digest=base_digest,
        change_set_digest_value=change_set_digest(base_digest, candidate_digest),
        dialect=DIALECT,
    )


def edited(document: Dict[str, Any], class_index: int, description: str) -> Dict[str, Any]:
    """A copy of ``document`` with one class's description changed — a one-line source edit."""
    candidate = copy.deepcopy(document)
    candidate["components"]["schemas"][class_name(class_index)]["description"] = description
    return candidate


def drop_revision_rows(conn: Any, projects: Sequence[str]) -> None:
    """Delete what the ``env`` fixture's teardown cannot: rows that would block deleting the revisions.

    Paths go before classes (deleting a class nulls its content rows' ``class_id``, which the
    content checks refuse); a source apply's audit, edit log and claims reference the revision.
    """
    conn.rollback()
    with conn.cursor() as cur:
        for table in (
            "version_path",
            "version_source_edits",
            "source_change_audit",
            "version_preservation_claims",
        ):
            cur.execute(
                f"DELETE FROM apiome.{table} WHERE version_id IN "
                "(SELECT id FROM apiome.versions WHERE project_id = ANY(%s::uuid[]))",
                (list(projects),),
            )
    conn.commit()


def fork_target_project(ctx: Dict[str, Any]) -> str:
    """A second project in the seeded tenant, to fork into. Drop it with :func:`drop_project`."""
    with ctx["conn"].cursor() as cur:
        cur.execute(
            "INSERT INTO apiome.projects (tenant_id, creator_id, name, slug) "
            "VALUES (%s, %s, 'Fork target', %s) RETURNING id::text AS id",
            (ctx["tenant"], ctx["user"], f"fork-{ctx['project'][:8]}"),
        )
        project = cur.fetchone()["id"]
    ctx["conn"].commit()
    return project


def drop_project(conn: Any, project: str) -> None:
    """Remove a project made by :func:`fork_target_project` and everything under it."""
    drop_revision_rows(conn, [project])
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM apiome.versions WHERE project_id = %s::uuid", (project,))
        versions = [r["id"] for r in cur.fetchall()]
        cur.execute("DELETE FROM apiome.classes WHERE version_id = ANY(%s::uuid[])", (versions,))
        cur.execute("DELETE FROM apiome.versions WHERE project_id = %s::uuid", (project,))
        cur.execute("DELETE FROM apiome.properties WHERE project_id = %s::uuid", (project,))
        cur.execute("DELETE FROM apiome.projects WHERE id = %s::uuid", (project,))
    conn.commit()
