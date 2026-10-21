"""Copy a version's paths into another version of the same project (#771).

New version → **Copy from version** always copies the classes; with ``copyPaths`` it copies the
paths too. A path is a tree of rows under ``apiome.version_path`` — operations, their
descriptions, parameters, request bodies, responses, the shared (path-level) parameters,
request bodies and responses they link to, and the Studio canvas — and several of those rows
point at a class by id. So a copy has to:

1. give every copied row a new id, keeping a map ``(kind, old_id) → new_id``;
2. re-point each parent / link column through that map;
3. re-point each ``class_id`` at the same-named class in the target version (the classes are
   copied first, by name). A class id with no counterpart — a reference to a class that was
   deleted from the source — is kept as it was, so the copy mirrors the source exactly;
4. rewrite the canvas JSON, whose node and edge ids embed path and operation ids.

The map lives in a temporary table dropped at commit, so every step is one set-based
``INSERT … SELECT`` regardless of how many paths the version has. Everything runs on the
caller's cursor, inside the caller's transaction: a failure rolls back the whole push.

``property_id`` columns are left alone — properties are a project-level library, shared by
every version of the project.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Sequence, Tuple

#: The temporary id map. ``ON COMMIT DROP`` cleans it up; a rollback discards it with the rest.
MAP_TABLE = "_version_path_copy_map"

_UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


@dataclass(frozen=True)
class ChildTable:
    """One table under ``version_path``, copied row for row.

    Attributes:
        table: Table name in the ``apiome`` schema.
        kind: The map kind its own rows are recorded under.
        parent: ``(column, kind)`` — the column pointing at the parent row, and the parent's kind.
        columns: Columns copied verbatim.
        links: ``column → kind`` for further id columns re-pointed through the map (a link
            table's second parent). An unmapped link drops the row.
        class_columns: Columns holding a class id, re-pointed to the target's same-named class.
    """

    table: str
    kind: str
    parent: Tuple[str, str]
    columns: Tuple[str, ...]
    links: Mapping[str, str] = field(default_factory=dict)
    class_columns: Tuple[str, ...] = ()


#: Every table under a path, parents before children.
CHILD_TABLES: Tuple[ChildTable, ...] = (
    ChildTable(
        "shared_path_parameter", "shared_parameter", ("version_path_id", "path"),
        ("name", "in_location", "summary", "description", "data"),
    ),
    ChildTable(
        "shared_path_request_body", "shared_request_body", ("version_path_id", "path"),
        ("name", "description", "required"),
    ),
    ChildTable(
        "shared_path_request_body_content", "shared_request_body_content",
        ("shared_path_request_body_id", "shared_request_body"),
        ("media_type", "inline_schema", "encoding", "examples"),
        class_columns=("class_id",),
    ),
    ChildTable(
        "shared_path_response", "shared_response", ("version_path_id", "path"),
        ("status_code", "description", "data", "inline_schema", "schema_mode"),
        class_columns=("class_id",),
    ),
    ChildTable(
        "shared_path_response_content", "shared_response_content",
        ("shared_path_response_id", "shared_response"),
        ("media_type", "inline_schema", "examples"),
        class_columns=("class_id",),
    ),
    ChildTable("path_operation", "operation", ("version_path_id", "path"), ("operation", "metadata")),
    ChildTable(
        "path_operation_description", "operation_description", ("path_operation_id", "operation"),
        ("summary", "description", "operation_id", "metadata"),
    ),
    ChildTable(
        "path_operation_parameter_link", "parameter_link", ("path_operation_id", "operation"),
        ("metadata",), links={"shared_path_parameter_id": "shared_parameter"},
    ),
    ChildTable(
        "path_operation_request_body_link", "request_body_link", ("path_operation_id", "operation"),
        ("metadata",), links={"shared_path_request_body_id": "shared_request_body"},
    ),
    ChildTable(
        "path_operation_response_link", "response_link", ("path_operation_id", "operation"),
        ("metadata",), links={"shared_path_response_id": "shared_response"},
    ),
    ChildTable(
        "path_operation_schema", "operation_schema", ("path_operation_id", "operation"),
        ("property_id", "name", "description", "data"),
        class_columns=("class_id",),
    ),
    ChildTable(
        "path_parameter", "parameter", ("path_operation_id", "operation"),
        ("name", "in_location", "summary", "description", "metadata", "data"),
    ),
    ChildTable(
        "path_response", "response", ("path_operation_id", "operation"),
        ("status_code", "description", "metadata"),
    ),
    ChildTable("path_response_content", "response_content", ("path_response_id", "response"), ("media_type",)),
    ChildTable(
        "path_parameter_schema", "parameter_schema", ("path_response_content_id", "response_content"),
        ("property_id", "data"),
        class_columns=("class_id",),
    ),
)


def _class_expr(column: str) -> str:
    """SQL for ``t.<column>`` re-pointed at the target's same-named class, else unchanged."""
    return (
        f"COALESCE((SELECT cm.new_id FROM {MAP_TABLE} cm "
        f"WHERE cm.kind = 'class' AND cm.old_id = t.{column}), t.{column})"
    )


def child_table_sql(spec: ChildTable) -> Tuple[str, str]:
    """The two statements that copy one child table.

    Args:
        spec: The table.

    Returns:
        ``(map_sql, insert_sql)``: the first records a new id for every row whose parent was
        copied; the second inserts the copies. Neither takes parameters.
    """
    parent_col, parent_kind = spec.parent
    map_sql = (
        f"INSERT INTO {MAP_TABLE} (kind, old_id, new_id) "
        f"SELECT '{spec.kind}', t.id, apiome.uuid_generate_v4() "
        f"FROM apiome.{spec.table} t "
        f"JOIN {MAP_TABLE} pm ON pm.kind = '{parent_kind}' AND pm.old_id = t.{parent_col}"
    )
    target_cols = ["id", parent_col, *spec.links.keys(), *spec.class_columns, *spec.columns]
    select_exprs = [
        "me.new_id",
        "pm.new_id",
        *(f"lm{i}.new_id" for i in range(len(spec.links))),
        *(_class_expr(col) for col in spec.class_columns),
        *(f"t.{col}" for col in spec.columns),
    ]
    link_joins = " ".join(
        f"JOIN {MAP_TABLE} lm{i} ON lm{i}.kind = '{kind}' AND lm{i}.old_id = t.{col}"
        for i, (col, kind) in enumerate(spec.links.items())
    )
    insert_sql = (
        f"INSERT INTO apiome.{spec.table} ({', '.join(target_cols)}) "
        f"SELECT {', '.join(select_exprs)} "
        f"FROM apiome.{spec.table} t "
        f"JOIN {MAP_TABLE} me ON me.kind = '{spec.kind}' AND me.old_id = t.id "
        f"JOIN {MAP_TABLE} pm ON pm.kind = '{parent_kind}' AND pm.old_id = t.{parent_col} "
        f"{link_joins}"
    ).strip()
    return map_sql, insert_sql


def remap_canvas_ids(canvas_text: str, id_map: Mapping[str, str]) -> str:
    """Rewrite every UUID in a canvas document that the copy gave a new id.

    Node ids such as ``path-node-<path id>`` and edge ids embed row ids, and class nodes carry
    class ids; each is swapped for its copy. A UUID with no copy (a property) is left as it is.

    Args:
        canvas_text: The canvas JSON as text.
        id_map: Old id → new id, lower-case.

    Returns:
        The rewritten text.
    """
    return _UUID_RE.sub(lambda m: id_map.get(m.group(0).lower(), m.group(0)), canvas_text)


def copy_paths_between_versions(cursor: Any, source_version_id: str, target_version_id: str) -> Dict[str, int]:
    """Copy every path of one version into another, inside the caller's transaction.

    Call it **after** the classes have been copied into the target, so class references can
    be re-pointed by name.

    Args:
        cursor: An open cursor (``RealDictCursor``) on the push transaction.
        source_version_id: The version copied from.
        target_version_id: The new version copied into.

    Returns:
        ``{"paths": n, "operations": m}`` — how many paths and operations were copied.
    """
    cursor.execute(
        f"CREATE TEMP TABLE IF NOT EXISTS {MAP_TABLE} "
        "(kind text NOT NULL, old_id uuid NOT NULL, new_id uuid NOT NULL, PRIMARY KEY (kind, old_id)) "
        "ON COMMIT DROP"
    )
    cursor.execute(f"TRUNCATE {MAP_TABLE}")

    cursor.execute(
        f"""
        INSERT INTO {MAP_TABLE} (kind, old_id, new_id)
        SELECT 'class', s.id, d.id
        FROM apiome.classes s
        JOIN apiome.classes d
          ON d.version_id = %s AND d.name = s.name AND d.deleted_at IS NULL
        WHERE s.version_id = %s AND s.deleted_at IS NULL
        ON CONFLICT (kind, old_id) DO NOTHING
        """,
        (target_version_id, source_version_id),
    )
    cursor.execute(
        f"""
        INSERT INTO {MAP_TABLE} (kind, old_id, new_id)
        SELECT 'path', p.id, apiome.uuid_generate_v4()
        FROM apiome.version_path p
        WHERE p.version_id = %s
        """,
        (source_version_id,),
    )
    cursor.execute(
        f"""
        INSERT INTO apiome.version_path (id, version_id, pathname, metadata, domain_id)
        SELECT m.new_id, %s, p.pathname, p.metadata, p.domain_id
        FROM apiome.version_path p
        JOIN {MAP_TABLE} m ON m.kind = 'path' AND m.old_id = p.id
        """,
        (target_version_id,),
    )
    path_count = cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0
    if path_count == 0:
        return {"paths": 0, "operations": 0}

    operation_count = 0
    for spec in CHILD_TABLES:
        map_sql, insert_sql = child_table_sql(spec)
        cursor.execute(map_sql)
        cursor.execute(insert_sql)
        if spec.table == "path_operation":
            operation_count = max(cursor.rowcount or 0, 0)

    _copy_canvases(cursor)
    return {"paths": path_count, "operations": operation_count}


def _copy_canvases(cursor: Any) -> None:
    """Copy each copied path's Studio canvas, with its embedded ids rewritten."""
    cursor.execute(
        f"""
        SELECT m.new_id::text AS new_path_id, c.canvas::text AS canvas
        FROM apiome.version_path_canvas c
        JOIN {MAP_TABLE} m ON m.kind = 'path' AND m.old_id = c.version_path_id
        """
    )
    canvases: Sequence[Mapping[str, Any]] = cursor.fetchall()
    if not canvases:
        return
    cursor.execute(f"SELECT old_id::text AS old_id, new_id::text AS new_id FROM {MAP_TABLE}")
    id_map = {str(r["old_id"]).lower(): str(r["new_id"]) for r in cursor.fetchall()}
    for row in canvases:
        canvas = remap_canvas_ids(str(row["canvas"]), id_map)
        # Validate before writing: a canvas is JSON, and the rewrite only swaps UUID strings.
        json.loads(canvas)
        cursor.execute(
            "INSERT INTO apiome.version_path_canvas (version_path_id, canvas) VALUES (%s, %s::jsonb)",
            (row["new_path_id"], canvas),
        )
