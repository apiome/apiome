"""Set-based loader for a revision's paths and operations — DBP-1.6 (#7189).

The document render, the Studio canvas (``GET /v1/paths/{tenant}/{version}/{path}/full``) and the
source-apply read all need every operation of a revision with its description, parameters,
request body and responses. They used to read them one operation at a time: one query per path
and four per operation (``1 + P + 4·O`` statements; about 3,500 for a 300-path / 800-operation
spec). This module reads the same rows with a fixed number of statements, whatever the size of
the spec:

* :func:`load_paths_for_version` — the paths of a revision plus five set-based reads (operations,
  descriptions, parameters, request bodies, responses): at most **6** statements.
* :func:`load_operations_with_details` — the operations of one path (or of a whole revision) with
  their details: at most **5** statements.

Both return exactly what the per-operation loaders returned: the same columns, the same row
order, and the same ``content_types`` order (see :data:`_CONTENT_ORDER`), so a document generated
from either is byte-identical. The per-operation ``Database`` methods
(:meth:`~app.database.Database.get_operations_for_path` and friends) stay for single-operation
readers.

Callers pass a *fetch* function, so the same code runs on the shared pool
(``db.execute_query``) and on a transaction's cursor (:func:`cursor_fetch`), for example under the
row lock that :meth:`~app.database.Database.apply_source_change_set` holds.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

#: Runs one SQL statement with its parameters and returns the rows as dicts.
Fetch = Callable[[str, Sequence[Any]], List[Dict[str, Any]]]

#: The grouping key each detail query adds to its rows; removed before the rows are returned.
_OP_KEY = "loader_path_operation_id"

#: The order of a request body's or response's content types. The per-operation queries had no
#: ``ORDER BY`` inside ``json_agg``: their plans (an index scan on the parent id, or a sequential
#: scan of a small table) return a parent's content rows in physical (``ctid``) order. The
#: set-based queries may join differently, so they ask for that order explicitly.
_CONTENT_ORDER = "ctid"

_OPERATION_ORDER = """CASE po.operation
                WHEN 'GET' THEN 1 WHEN 'POST' THEN 2 WHEN 'PUT' THEN 3
                WHEN 'PATCH' THEN 4 WHEN 'DELETE' THEN 5 ELSE 6
            END"""


def cursor_fetch(cursor: Any) -> Fetch:
    """A :data:`Fetch` that runs on an open cursor (inside the caller's transaction).

    Args:
        cursor: A dict-row cursor (``RealDictCursor`` or a subclass).

    Returns:
        A function that executes a statement on ``cursor`` and returns all its rows.
    """

    def fetch(query: str, params: Sequence[Any]) -> List[Dict[str, Any]]:
        cursor.execute(query, tuple(params))
        return list(cursor.fetchall() or [])

    return fetch


def _scope(version_id: Optional[str], path_id: Optional[str]) -> Tuple[str, str, Tuple[Any, ...]]:
    """The join, filter and parameters that pick the operations a load covers.

    Args:
        version_id: Every operation of this revision (``versions.id``).
        path_id: Every operation of this path (``version_path.id``).

    Returns:
        ``(join, where, params)`` over the ``apiome.path_operation po`` alias.

    Raises:
        ValueError: Neither or both of ``version_id`` and ``path_id`` were given.
    """
    if (version_id is None) == (path_id is None):
        raise ValueError("give exactly one of version_id or path_id")
    if version_id is not None:
        return (
            "INNER JOIN apiome.version_path vp ON vp.id = po.version_path_id",
            "vp.version_id = %s",
            (version_id,),
        )
    return "", "po.version_path_id = %s", (path_id,)


def _group(rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Group detail rows by their operation, keeping row order and dropping the grouping key."""
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        row = dict(row)
        grouped.setdefault(str(row.pop(_OP_KEY)), []).append(row)
    return grouped


def load_operations_with_details(
    fetch: Fetch,
    *,
    version_id: Optional[str] = None,
    path_id: Optional[str] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """Every operation of a revision or of one path, with its details, in at most five statements.

    Each operation is its ``path_operation`` row (``id``, ``version_path_id``, ``operation``,
    ``metadata``, ``created_at``, ``updated_at``) plus:

    * ``description`` — the ``path_operation_description`` row, or ``None``;
    * ``parameters`` — the linked shared parameters (path, query, header, then the rest; by name);
    * ``requestBody`` — the linked request body with its ``content_types``, or ``None``;
    * ``responses`` — the linked responses with their ``content_types``, by status code.

    Args:
        fetch: Runs one statement (``db.execute_query`` or :func:`cursor_fetch`).
        version_id: Load every operation of this revision. Give this or ``path_id``.
        path_id: Load the operations of this path only.

    Returns:
        ``{version_path_id: [operation, …]}`` with operations in method order (GET, POST, PUT,
        PATCH, DELETE, then any other); a path without operations has no key.

    Raises:
        ValueError: Neither or both of ``version_id`` and ``path_id`` were given.
    """
    join, where, params = _scope(version_id, path_id)
    operations = fetch(
        f"""
            SELECT po.id, po.version_path_id, po.operation, po.metadata, po.created_at, po.updated_at
            FROM apiome.path_operation po
            {join}
            WHERE {where}
            ORDER BY po.version_path_id, {_OPERATION_ORDER}
        """,
        params,
    )
    if not operations:
        return {}

    descriptions = _group(
        fetch(
            f"""
            SELECT pod.path_operation_id AS {_OP_KEY},
                pod.id,
                pod.summary,
                pod.description,
                pod.operation_id,
                pod.metadata->'tags' as tags,
                (pod.metadata->>'deprecated')::boolean as deprecated,
                (pod.metadata->>'x-private')::boolean as x_private,
                pod.metadata->'external_docs' as external_docs,
                pod.metadata
            FROM apiome.path_operation_description pod
            INNER JOIN apiome.path_operation po ON po.id = pod.path_operation_id
            {join}
            WHERE {where}
            """,
            params,
        )
    )
    parameters = _group(
        fetch(
            f"""
            SELECT popl.path_operation_id AS {_OP_KEY},
                spp.id, spp.name, spp.in_location, spp.summary, spp.description, spp.data
            FROM apiome.shared_path_parameter spp
            INNER JOIN apiome.path_operation_parameter_link popl ON spp.id = popl.shared_path_parameter_id
            INNER JOIN apiome.path_operation po ON po.id = popl.path_operation_id
            {join}
            WHERE {where}
            ORDER BY popl.path_operation_id, CASE spp.in_location
                WHEN 'path' THEN 1 WHEN 'query' THEN 2 WHEN 'header' THEN 3 ELSE 4
            END, spp.name
            """,
            params,
        )
    )
    request_bodies = _group(
        fetch(
            f"""
            SELECT link.path_operation_id AS {_OP_KEY},
                rb.id, rb.name, rb.description, rb.required,
                COALESCE(json_agg(json_build_object(
                    'id', rbc.id, 'media_type', rbc.media_type, 'class_id', rbc.class_id,
                    'class_name', c.name, 'inline_schema', rbc.inline_schema,
                    'encoding', rbc.encoding, 'examples', rbc.examples,
                    'item_schema', rbc.item_schema
                ) ORDER BY rbc.{_CONTENT_ORDER}) FILTER (WHERE rbc.id IS NOT NULL), '[]') as content_types
            FROM apiome.shared_path_request_body rb
            INNER JOIN apiome.path_operation_request_body_link link ON rb.id = link.shared_path_request_body_id
            INNER JOIN apiome.path_operation po ON po.id = link.path_operation_id
            {join}
            LEFT JOIN apiome.shared_path_request_body_content rbc ON rb.id = rbc.shared_path_request_body_id
            LEFT JOIN apiome.classes c ON rbc.class_id = c.id
            WHERE {where}
            GROUP BY link.path_operation_id, rb.id
            """,
            params,
        )
    )
    responses = _group(
        fetch(
            f"""
            SELECT porl.path_operation_id AS {_OP_KEY},
                spr.id,
                spr.status_code,
                spr.description,
                spr.data,
                spr.class_id,
                c.name as class_name,
                spr.inline_schema,
                COALESCE(
                    json_agg(
                        json_build_object(
                            'id', rc.id,
                            'media_type', rc.media_type,
                            'class_id', rc.class_id,
                            'class_name', rc_class.name,
                            'inline_schema', rc.inline_schema,
                            'examples', rc.examples,
                            'item_schema', rc.item_schema
                        ) ORDER BY rc.{_CONTENT_ORDER}
                    ) FILTER (WHERE rc.id IS NOT NULL),
                    '[]'
                ) as content_types
            FROM apiome.shared_path_response spr
            INNER JOIN apiome.path_operation_response_link porl ON spr.id = porl.shared_path_response_id
            INNER JOIN apiome.path_operation po ON po.id = porl.path_operation_id
            {join}
            LEFT JOIN apiome.classes c ON spr.class_id = c.id
            LEFT JOIN apiome.shared_path_response_content rc ON spr.id = rc.shared_path_response_id
            LEFT JOIN apiome.classes rc_class ON rc.class_id = rc_class.id
            WHERE {where}
            GROUP BY porl.path_operation_id, spr.id, spr.status_code, spr.description, spr.data,
                     spr.class_id, c.name, spr.inline_schema
            ORDER BY porl.path_operation_id, spr.status_code
            """,
            params,
        )
    )

    by_path: Dict[str, List[Dict[str, Any]]] = {}
    for op in operations:
        op_id = str(op["id"])
        # One description and one request body per operation (UNIQUE(path_operation_id)).
        description = descriptions.get(op_id)
        request_body = request_bodies.get(op_id)
        by_path.setdefault(str(op["version_path_id"]), []).append(
            {
                **op,
                "description": description[0] if description else None,
                "parameters": parameters.get(op_id, []),
                "requestBody": request_body[0] if request_body else None,
                "responses": responses.get(op_id, []),
            }
        )
    return by_path


def load_paths_for_version(fetch: Fetch, version_id: str) -> List[Dict[str, Any]]:
    """A revision's paths with full operation details, in at most six statements.

    The shape the OpenAPI generator (:func:`app.paths_generator.generate_paths_for_openapi`)
    reads: each path is ``{id, pathname, summary, description, operations}`` (by pathname) and
    each operation ``{id, operation, metadata, description, parameters, requestBody,
    responses}``.

    Args:
        fetch: Runs one statement (``db.execute_query`` or :func:`cursor_fetch`).
        version_id: The revision (``versions.id``).

    Returns:
        The paths; empty when the revision has none.
    """
    path_rows = fetch(
        """
            SELECT
                id,
                pathname,
                metadata->>'summary' as summary,
                metadata->>'description' as description
            FROM apiome.version_path
            WHERE version_id = %s
            ORDER BY pathname
        """,
        (version_id,),
    )
    if not path_rows:
        return []
    by_path = load_operations_with_details(fetch, version_id=version_id)
    return [
        {
            "id": path_row["id"],
            "pathname": path_row["pathname"],
            "summary": path_row.get("summary"),
            "description": path_row.get("description"),
            "operations": [
                {
                    "id": op["id"],
                    "operation": op["operation"],
                    # Carries the declared method token of a QUERY / custom-method operation (#7048).
                    "metadata": op.get("metadata"),
                    "description": op["description"],
                    "parameters": op["parameters"],
                    "requestBody": op["requestBody"],
                    "responses": op["responses"],
                }
                for op in by_path.get(str(path_row["id"]), [])
            ],
        }
        for path_row in path_rows
    ]
