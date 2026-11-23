"""Set-based row writer for source apply — DBP-1.7 (#7190).

:meth:`app.database.Database.apply_source_change_set` turns a reviewed candidate document into
relational rows. Before this module it soft-deleted every class of the revision and re-inserted
every class, class property, path, parameter, response, content and operation, one statement per
row, whatever the size of the edit, after loading the project's whole property library.

Two things changed:

* **Only the difference is written.** :func:`plan_source_apply` compares the document the rows
  render to *now* with the document the candidate's rows *will* render to
  (:func:`app.source_change_apply.regenerate_document`), one class and one path at a time. A class
  or path whose rendering does not change keeps its rows — and so its ids, canvas position,
  comments and links. A changed class is updated in place; a changed path is deleted and
  recreated (its children cascade), as before. After the write the rows render to exactly the
  document the full rewrite would have produced, so the fidelity checks made before the write
  still hold.
* **Every table is one statement.** Ids are assigned on the client
  (:func:`app.db_bulk.new_ids`), so parents and children are written without a ``RETURNING``
  round trip per parent, and each table travels as one ``INSERT … SELECT FROM unnest(…)``
  (:func:`app.db_bulk.bulk_insert_arrays`). Project properties are matched in the database by
  ``properties.data_digest`` (V409) instead of loading the library into Python.

The statement count is the same for 10 classes and for 20,000. Everything runs on the caller's
cursor; committing or rolling back is the caller's job.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, List, Optional, Sequence, Tuple

from .db_bulk import bulk_insert_arrays, new_ids
from .source_change_apply import CanonicalWrites, ClassWrite, PathWrite, parameter_key, path_shared_parameters

__all__ = ["SourceApplyPlan", "plan_source_apply", "write_canonical_rows"]


@dataclass(frozen=True)
class SourceApplyPlan:
    """Which of a revision's rows a source apply may leave alone.

    Attributes:
        keep_classes: Names of classes whose rows already render to the candidate's schema.
        keep_paths: Pathnames whose rows already render to the candidate's path item.
        write_security_schemes: ``False`` when the security scheme rows need no change.
        write_servers: ``False`` when the server rows need no change.
    """

    keep_classes: FrozenSet[str]
    keep_paths: FrozenSet[str]
    write_security_schemes: bool
    write_servers: bool


def _mapping(document: Any, *keys: str) -> Dict[str, Any]:
    """``document[k1][k2]…`` when every step is a dict, else an empty dict."""
    node = document
    for key in keys:
        node = node.get(key) if isinstance(node, dict) else None
    return node if isinstance(node, dict) else {}


def _unchanged(current: Dict[str, Any], planned: Dict[str, Any]) -> FrozenSet[str]:
    """Keys present in both mappings with equal values."""
    return frozenset(key for key, value in planned.items() if key in current and current[key] == value)


def plan_source_apply(current_canonical: Any, regenerated: Any) -> SourceApplyPlan:
    """Decide which rows a source apply can keep.

    Both arguments are documents rendered by the same generator: ``current_canonical`` from the
    revision's rows as they are (before the preservation envelope is merged in), ``regenerated``
    from the rows the candidate will have. Where they agree, rewriting the rows would change
    nothing a reader can see.

    Args:
        current_canonical: The server-generated document for the revision's current rows.
        regenerated: The document predicted for the candidate's rows.

    Returns:
        The plan. With an unreadable ``current_canonical`` nothing is kept (a full rewrite).
    """
    current_servers = current_canonical.get("servers") if isinstance(current_canonical, dict) else None
    planned_servers = regenerated.get("servers") if isinstance(regenerated, dict) else None
    return SourceApplyPlan(
        keep_classes=_unchanged(
            _mapping(current_canonical, "components", "schemas"), _mapping(regenerated, "components", "schemas")
        ),
        keep_paths=_unchanged(_mapping(current_canonical, "paths"), _mapping(regenerated, "paths")),
        write_security_schemes=_mapping(current_canonical, "components", "securitySchemes")
        != _mapping(regenerated, "components", "securitySchemes"),
        write_servers=not isinstance(current_canonical, dict) or current_servers != planned_servers,
    )


def _json_or_null(value: Any) -> Optional[str]:
    """JSON text for a value, ``None`` (SQL NULL) for ``None``."""
    return json.dumps(value) if value is not None else None


def _stable_json(value: Any) -> str:
    """Key-order-independent JSON text, used to recognise equal property definitions."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


# ───────────────────────────────────── classes ─────────────────────────────────────


def _write_classes(
    cursor: Any,
    project_id: str,
    version_id: str,
    classes: Sequence[ClassWrite],
    plan: Optional[SourceApplyPlan],
) -> Dict[str, str]:
    """Bring the revision's classes in line with ``classes``.

    Without a plan every live class is soft-deleted and every candidate class inserted. With a
    plan: live classes the candidate drops are soft-deleted (retention parity with
    ``delete_class``), kept classes are untouched, changed ones are updated in place with their
    properties replaced, new ones are inserted.

    Returns:
        ``{class name: class id}`` for every class the candidate has.
    """
    live: Dict[str, str] = {}
    if plan is None:
        cursor.execute(
            """
            UPDATE apiome.classes
            SET deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE version_id = %s AND deleted_at IS NULL
            """,
            (version_id,),
        )
    else:
        cursor.execute(
            "SELECT id, name FROM apiome.classes WHERE version_id = %s AND deleted_at IS NULL",
            (version_id,),
        )
        live = {row["name"]: str(row["id"]) for row in cursor.fetchall()}
        wanted = {class_write.name for class_write in classes}
        dropped = [class_id for name, class_id in live.items() if name not in wanted]
        if dropped:
            cursor.execute(
                """
                UPDATE apiome.classes
                SET deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE id = ANY(%s::uuid[]) AND deleted_at IS NULL
                """,
                (dropped,),
            )

    keep = plan.keep_classes if plan is not None else frozenset()
    class_ids: Dict[str, str] = {}
    changed: List[ClassWrite] = []
    added: List[ClassWrite] = []
    for class_write in classes:
        if class_write.name in live:
            class_ids[class_write.name] = live[class_write.name]
            if class_write.name not in keep:
                changed.append(class_write)
        else:
            added.append(class_write)
    for class_write, class_id in zip(added, new_ids(len(added))):
        class_ids[class_write.name] = class_id

    if changed:
        changed_ids = [class_ids[class_write.name] for class_write in changed]
        cursor.execute(
            """
            UPDATE apiome.classes c
            SET description = v.description, schema = v.schema, enabled = TRUE,
                updated_at = CURRENT_TIMESTAMP
            FROM unnest(%s::uuid[], %s::text[], %s::jsonb[]) AS v(id, description, schema)
            WHERE c.id = v.id
            """,
            (
                changed_ids,
                [class_write.description for class_write in changed],
                [json.dumps(class_write.schema_fields) for class_write in changed],
            ),
        )
        cursor.execute("DELETE FROM apiome.class_properties WHERE class_id = ANY(%s::uuid[])", (changed_ids,))
    bulk_insert_arrays(
        cursor,
        "apiome.classes",
        [
            ("id", "uuid"),
            ("version_id", "uuid"),
            ("name", "text"),
            ("description", "text"),
            ("schema", "jsonb"),
            ("enabled", "boolean"),
        ],
        [
            (
                class_ids[class_write.name],
                version_id,
                class_write.name,
                class_write.description,
                json.dumps(class_write.schema_fields),
                True,
            )
            for class_write in added
        ],
    )
    _write_class_properties(cursor, project_id, changed + added, class_ids)
    return class_ids


def _resolve_library_properties(cursor: Any, project_id: str, wanted: Dict[str, Tuple[str, Optional[str], str]]) -> Dict[str, str]:
    """Find or create the project property for each distinct property definition.

    Args:
        cursor: The transaction cursor.
        project_id: The project whose property library is used.
        wanted: ``{signature: (name, description, data_json)}`` — one entry per distinct ``data``;
            the name and description are those of the first class property that carries it.

    Returns:
        ``{signature: properties.id}``. Existing rows are matched by ``data_digest`` (and by
        ``data`` itself, so a digest collision cannot link the wrong property); the oldest match
        wins. Missing definitions are inserted in one statement.
    """
    if not wanted:
        return {}
    signatures = list(wanted)
    cursor.execute(
        """
        SELECT w.ord,
               (SELECT p.id FROM apiome.properties p
                WHERE p.project_id = %s::uuid
                  AND p.data_digest = md5(w.data::text)
                  AND p.data = w.data
                ORDER BY p.created_at, p.id
                LIMIT 1) AS id
        FROM unnest(%s::int[], %s::jsonb[]) AS w(ord, data)
        """,
        (project_id, list(range(len(signatures))), [wanted[signature][2] for signature in signatures]),
    )
    found: Dict[str, str] = {}
    for row in cursor.fetchall():
        if row["id"] is not None:
            found[signatures[int(row["ord"])]] = str(row["id"])
    missing = [signature for signature in signatures if signature not in found]
    for signature, property_id in zip(missing, new_ids(len(missing))):
        found[signature] = property_id
    bulk_insert_arrays(
        cursor,
        "apiome.properties",
        [("id", "uuid"), ("project_id", "uuid"), ("name", "text"), ("description", "text"), ("data", "jsonb")],
        [(found[signature], project_id, wanted[signature][0], wanted[signature][1], wanted[signature][2]) for signature in missing],
    )
    return found


def _write_class_properties(
    cursor: Any, project_id: str, classes: Sequence[ClassWrite], class_ids: Dict[str, str]
) -> None:
    """Insert the top-level properties of ``classes`` (which have none yet).

    A reference property (``$ref``, or an array of ``$ref``) keeps a NULL library link; every
    other property links to the project property with the same ``data``.
    """
    wanted: Dict[str, Tuple[str, Optional[str], str]] = {}
    for class_write in classes:
        for prop in class_write.properties:
            if not prop.is_reference:
                wanted.setdefault(_stable_json(prop.data), (prop.name, prop.description, json.dumps(prop.data)))
    library = _resolve_library_properties(cursor, project_id, wanted)
    bulk_insert_arrays(
        cursor,
        "apiome.class_properties",
        [("class_id", "uuid"), ("property_id", "uuid"), ("name", "text"), ("description", "text"), ("data", "jsonb")],
        [
            (
                class_ids[class_write.name],
                None if prop.is_reference else library[_stable_json(prop.data)],
                prop.name,
                prop.description,
                json.dumps(prop.data),
            )
            for class_write in classes
            for prop in class_write.properties
        ],
    )


# ────────────────────────────────────── paths ──────────────────────────────────────


def _write_paths(
    cursor: Any,
    version_id: str,
    paths: Sequence[PathWrite],
    class_ids: Dict[str, str],
    plan: Optional[SourceApplyPlan],
) -> None:
    """Delete the paths that change or go away and recreate the candidate's version of them.

    Children (parameters, responses, contents, operations, request bodies, links) cascade from
    ``version_path`` on delete and are inserted one table at a time.
    """
    keep = sorted(plan.keep_paths) if plan is not None else []
    cursor.execute(
        "DELETE FROM apiome.version_path WHERE version_id = %s AND NOT (pathname = ANY(%s::text[]))",
        (version_id, keep),
    )
    kept = set(keep)
    written = [path for path in paths if path.pathname not in kept]
    path_ids = new_ids(len(written))

    path_rows: List[Tuple[Any, ...]] = []
    parameter_rows: List[Tuple[Any, ...]] = []
    response_rows: List[Tuple[Any, ...]] = []
    response_content_rows: List[Tuple[Any, ...]] = []
    operation_rows: List[Tuple[Any, ...]] = []
    description_rows: List[Tuple[Any, ...]] = []
    parameter_link_rows: List[Tuple[Any, ...]] = []
    request_body_rows: List[Tuple[Any, ...]] = []
    request_body_content_rows: List[Tuple[Any, ...]] = []
    request_body_link_rows: List[Tuple[Any, ...]] = []
    response_link_rows: List[Tuple[Any, ...]] = []

    def class_id_for(name: Optional[str]) -> Optional[str]:
        return class_ids.get(name) if name else None

    for path, version_path_id in zip(written, path_ids):
        metadata: Dict[str, Any] = {}
        if path.summary is not None:
            metadata["summary"] = path.summary
        if path.description is not None:
            metadata["description"] = path.description
        path_rows.append((version_path_id, version_id, path.pathname, json.dumps(metadata) if metadata else None))

        shared = path_shared_parameters(path)
        parameter_ids = dict(zip(shared.keys(), new_ids(len(shared))))
        for key, parameter in shared.items():
            parameter_rows.append(
                (
                    parameter_ids[key],
                    version_path_id,
                    parameter.name,
                    parameter.in_location,
                    parameter.summary,
                    parameter.description,
                    json.dumps(parameter.data),
                )
            )

        response_ids: Dict[str, str] = {}
        for response, response_id in zip(path.responses, new_ids(len(path.responses))):
            if response.data:
                data_value: Optional[str] = json.dumps(response.data)
            elif not response.contents:
                data_value = json.dumps({})
            else:
                data_value = None
            response_ids[response.status_code] = response_id
            response_rows.append(
                (response_id, version_path_id, response.status_code, response.description, data_value, "object")
            )
            for content in response.contents:
                response_content_rows.append(
                    (
                        response_id,
                        content.media_type,
                        class_id_for(content.ref_class_name),
                        _json_or_null(content.inline_schema),
                        _json_or_null(content.examples),
                    )
                )

        for op, operation_id in zip(path.operations, new_ids(len(path.operations))):
            operation_rows.append((operation_id, version_path_id, op.method.upper(), "{}"))
            description_rows.append(
                (
                    operation_id,
                    op.summary,
                    op.description,
                    op.operation_id,
                    json.dumps(op.description_metadata) if op.description_metadata else None,
                )
            )
            for parameter in op.parameters:
                shared_id = parameter_ids.get(parameter_key(parameter))
                if shared_id:
                    parameter_link_rows.append((operation_id, shared_id))
            if op.request_body is not None:
                request_body_id = new_ids(1)[0]
                request_body_rows.append(
                    (
                        request_body_id,
                        version_path_id,
                        op.request_body.name,
                        op.request_body.description,
                        op.request_body.required,
                    )
                )
                for content in op.request_body.contents:
                    request_body_content_rows.append(
                        (
                            request_body_id,
                            content.media_type,
                            class_id_for(content.ref_class_name),
                            _json_or_null(content.inline_schema),
                            _json_or_null(content.encoding),
                            _json_or_null(content.examples),
                        )
                    )
                request_body_link_rows.append((operation_id, request_body_id))
            for status in op.response_status_codes:
                response_id = response_ids.get(status)
                if response_id:
                    response_link_rows.append((operation_id, response_id))

    bulk_insert_arrays(
        cursor,
        "apiome.version_path",
        [("id", "uuid"), ("version_id", "uuid"), ("pathname", "text"), ("metadata", "jsonb")],
        path_rows,
    )
    bulk_insert_arrays(
        cursor,
        "apiome.shared_path_parameter",
        [
            ("id", "uuid"),
            ("version_path_id", "uuid"),
            ("name", "text"),
            ("in_location", "text"),
            ("summary", "text"),
            ("description", "text"),
            ("data", "jsonb"),
        ],
        parameter_rows,
    )
    bulk_insert_arrays(
        cursor,
        "apiome.shared_path_response",
        [
            ("id", "uuid"),
            ("version_path_id", "uuid"),
            ("status_code", "text"),
            ("description", "text"),
            ("data", "jsonb"),
            ("schema_mode", "text"),
        ],
        response_rows,
    )
    bulk_insert_arrays(
        cursor,
        "apiome.shared_path_response_content",
        [
            ("shared_path_response_id", "uuid"),
            ("media_type", "text"),
            ("class_id", "uuid"),
            ("inline_schema", "jsonb"),
            ("examples", "jsonb"),
        ],
        response_content_rows,
    )
    bulk_insert_arrays(
        cursor,
        "apiome.path_operation",
        [("id", "uuid"), ("version_path_id", "uuid"), ("operation", "text"), ("metadata", "jsonb")],
        operation_rows,
    )
    bulk_insert_arrays(
        cursor,
        "apiome.path_operation_description",
        [
            ("path_operation_id", "uuid"),
            ("summary", "text"),
            ("description", "text"),
            ("operation_id", "text"),
            ("metadata", "jsonb"),
        ],
        description_rows,
    )
    bulk_insert_arrays(
        cursor,
        "apiome.path_operation_parameter_link",
        [("path_operation_id", "uuid"), ("shared_path_parameter_id", "uuid")],
        parameter_link_rows,
        on_conflict="ON CONFLICT (path_operation_id, shared_path_parameter_id) DO NOTHING",
    )
    bulk_insert_arrays(
        cursor,
        "apiome.shared_path_request_body",
        [
            ("id", "uuid"),
            ("version_path_id", "uuid"),
            ("name", "text"),
            ("description", "text"),
            ("required", "boolean"),
        ],
        request_body_rows,
    )
    bulk_insert_arrays(
        cursor,
        "apiome.shared_path_request_body_content",
        [
            ("shared_path_request_body_id", "uuid"),
            ("media_type", "text"),
            ("class_id", "uuid"),
            ("inline_schema", "jsonb"),
            ("encoding", "jsonb"),
            ("examples", "jsonb"),
        ],
        request_body_content_rows,
    )
    bulk_insert_arrays(
        cursor,
        "apiome.path_operation_request_body_link",
        [("path_operation_id", "uuid"), ("shared_path_request_body_id", "uuid")],
        request_body_link_rows,
    )
    bulk_insert_arrays(
        cursor,
        "apiome.path_operation_response_link",
        [("path_operation_id", "uuid"), ("shared_path_response_id", "uuid")],
        response_link_rows,
        on_conflict="ON CONFLICT (path_operation_id, shared_path_response_id) DO NOTHING",
    )


# ─────────────────────────────── security schemes, servers ───────────────────────────────


def _write_security_schemes(cursor: Any, version_id: str, writes: CanonicalWrites) -> None:
    """Delete and recreate the revision's security scheme rows."""
    cursor.execute("DELETE FROM apiome.version_security_scheme WHERE version_id = %s", (version_id,))
    bulk_insert_arrays(
        cursor,
        "apiome.version_security_scheme",
        [
            ("version_id", "uuid"),
            ("scheme_name", "text"),
            ("scheme_type", "text"),
            ("in_location", "text"),
            ("param_name", "text"),
            ("description", "text"),
            ("data", "jsonb"),
        ],
        [
            (version_id, scheme.scheme_name, scheme.scheme_type, scheme.in_location, scheme.param_name, scheme.description, "{}")
            for scheme in writes.security_schemes
        ],
    )


def _write_servers(cursor: Any, version_id: str, writes: CanonicalWrites) -> None:
    """Delete and recreate the revision's server rows."""
    cursor.execute("DELETE FROM apiome.version_server WHERE version_id = %s", (version_id,))
    bulk_insert_arrays(
        cursor,
        "apiome.version_server",
        [
            ("version_id", "uuid"),
            ("url", "text"),
            ("description", "text"),
            ("sort_order", "integer"),
            ("variables", "jsonb"),
        ],
        [
            (version_id, server.url, server.description, server.sort_order, _json_or_null(server.variables))
            for server in writes.servers
        ],
    )


def write_canonical_rows(
    cursor: Any,
    project_id: str,
    version_id: str,
    writes: CanonicalWrites,
    plan: Optional[SourceApplyPlan] = None,
) -> None:
    """Write a candidate's rows for one revision, on the caller's transaction.

    Args:
        cursor: The transaction cursor (dict rows).
        project_id: The revision's project (owner of the property library).
        version_id: The revision's record id.
        writes: The candidate's write plan (:func:`app.source_change_apply.build_canonical_writes`).
        plan: What may be kept (:func:`plan_source_apply`). ``None`` rewrites everything: every
            live class is soft-deleted and reinserted, every path, security scheme and server is
            deleted and recreated.

    The number of statements depends on which tables have rows to write, never on how many.
    """
    class_ids = _write_classes(cursor, project_id, version_id, writes.classes, plan)
    _write_paths(cursor, version_id, writes.paths, class_ids, plan)
    if plan is None or plan.write_security_schemes:
        _write_security_schemes(cursor, version_id, writes)
    if plan is None or plan.write_servers:
        _write_servers(cursor, version_id, writes)
