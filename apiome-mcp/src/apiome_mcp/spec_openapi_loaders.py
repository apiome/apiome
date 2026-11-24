"""Set-based Postgres loaders for revision OpenAPI generation — DBP-1.22 (#7205).

The spec tools (and apiome-mock, which imports this module) build a revision's OpenAPI document
from its normalized rows. The loader used to read them one operation at a time — one statement per
path and four per operation, about 2,300 round trips for a 300-path / 500-operation spec — and its
class-property read used one placeholder per class. This module reads the same rows with a fixed
number of statements, whatever the size of the spec (the async twin of apiome-rest's DBP-1.6
loader, :mod:`app.path_operation_loader`):

==========================  ==========================================================  ==========
What                        Statements                                                  At most
==========================  ==========================================================  ==========
:func:`load_openapi_inputs` classes, properties, paths, operations, descriptions,       **11**
(the full document)         parameters, request bodies, responses, security schemes,
                            servers, component pins
``part="operations"``       paths, operations, descriptions                             **3**
``part="components"``       classes, properties, security schemes, component pins       **4**
==========================  ==========================================================  ==========

Each statement is keyed by the revision id (``versions.id``); none takes a list of ids, so the
statement text never changes with the size of the spec.

The rows are the ones the per-operation loader returned: the same columns, the same row order,
and — for a request body's or response's ``content_types`` — the order the per-operation queries
produced in practice (see :data:`_CONTENT_ORDER`), so a document generated from either is
identical (``tests/test_spec_openapi_loaders_db.py`` compares them on a seeded database).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

from psycopg.rows import dict_row

__all__ = [
    "OpenApiInputs",
    "OpenApiPart",
    "fetch_openapi_generation_inputs_async",
    "load_classes_and_properties",
    "load_component_pin_rows",
    "load_openapi_inputs",
    "load_paths_tree",
    "load_security_scheme_rows",
    "load_server_rows",
]

#: Which rows a caller needs: the whole document, only what the operation index reads, or only what
#: the ``components`` section reads.
OpenApiPart = Literal["document", "operations", "components"]

#: The grouping key each detail query adds to its rows; removed before the rows are returned.
_OP_KEY = "loader_path_operation_id"

#: The order of a request body's or response's content types. The per-operation queries had no
#: ``ORDER BY`` inside ``json_agg``: their plans returned a parent's content rows in physical
#: (``ctid``) order. The set-based queries may join differently, so they ask for that order.
_CONTENT_ORDER = "ctid"

#: Joins ``apiome.path_operation po`` to its revision; every operation-level query filters on it.
_OPERATIONS_OF_VERSION = "INNER JOIN apiome.version_path vp ON vp.id = po.version_path_id"

#: Every property of a revision's live classes. Keyed by the revision, not by a list of class ids:
#: one statement text for any class count (the ``IN`` list it replaces had one placeholder per
#: class and failed above 65,535 of them).
CLASS_PROPERTIES_SQL = """
    SELECT cp.id, cp.class_id, cp.property_id, cp.name, cp.description, cp.data, cp.parent_id,
           p.id as property_source_id, p.name as property_source_name, p.data as property_source_data
    FROM apiome.class_properties cp
    INNER JOIN apiome.classes c ON c.id = cp.class_id
    LEFT JOIN apiome.properties p ON cp.property_id = p.id
    WHERE c.version_id = %s AND c.deleted_at IS NULL
    ORDER BY cp.class_id, cp.parent_id NULLS FIRST, cp.name ASC
"""

_PATHS_SQL = """
    SELECT
        id,
        pathname,
        metadata->>'summary' as summary,
        metadata->>'description' as description
    FROM apiome.version_path
    WHERE version_id = %s
    ORDER BY pathname
"""

_OPERATIONS_SQL = f"""
    SELECT po.id, po.version_path_id, po.operation
    FROM apiome.path_operation po
    {_OPERATIONS_OF_VERSION}
    WHERE vp.version_id = %s
    ORDER BY po.version_path_id, CASE po.operation
        WHEN 'GET' THEN 1 WHEN 'POST' THEN 2 WHEN 'PUT' THEN 3
        WHEN 'PATCH' THEN 4 WHEN 'DELETE' THEN 5 ELSE 6
    END
"""

_DESCRIPTIONS_SQL = f"""
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
    {_OPERATIONS_OF_VERSION}
    WHERE vp.version_id = %s
"""

_PARAMETERS_SQL = f"""
    SELECT popl.path_operation_id AS {_OP_KEY},
        spp.id, spp.name, spp.in_location, spp.summary, spp.description, spp.data
    FROM apiome.shared_path_parameter spp
    INNER JOIN apiome.path_operation_parameter_link popl ON spp.id = popl.shared_path_parameter_id
    INNER JOIN apiome.path_operation po ON po.id = popl.path_operation_id
    {_OPERATIONS_OF_VERSION}
    WHERE vp.version_id = %s
    ORDER BY popl.path_operation_id, CASE spp.in_location
        WHEN 'path' THEN 1 WHEN 'query' THEN 2 WHEN 'header' THEN 3 ELSE 4
    END, spp.name
"""

_REQUEST_BODIES_SQL = f"""
    SELECT link.path_operation_id AS {_OP_KEY},
        rb.id, rb.name, rb.description, rb.required,
        COALESCE(json_agg(json_build_object(
            'id', rbc.id, 'media_type', rbc.media_type, 'class_id', rbc.class_id,
            'class_name', c.name, 'inline_schema', rbc.inline_schema,
            'encoding', rbc.encoding, 'examples', rbc.examples
        ) ORDER BY rbc.{_CONTENT_ORDER}) FILTER (WHERE rbc.id IS NOT NULL), '[]') as content_types
    FROM apiome.shared_path_request_body rb
    INNER JOIN apiome.path_operation_request_body_link link ON rb.id = link.shared_path_request_body_id
    INNER JOIN apiome.path_operation po ON po.id = link.path_operation_id
    {_OPERATIONS_OF_VERSION}
    LEFT JOIN apiome.shared_path_request_body_content rbc ON rb.id = rbc.shared_path_request_body_id
    LEFT JOIN apiome.classes c ON rbc.class_id = c.id
    WHERE vp.version_id = %s
    GROUP BY link.path_operation_id, rb.id
"""

_RESPONSES_SQL = f"""
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
                    'examples', rc.examples
                ) ORDER BY rc.{_CONTENT_ORDER}
            ) FILTER (WHERE rc.id IS NOT NULL),
            '[]'
        ) as content_types
    FROM apiome.shared_path_response spr
    INNER JOIN apiome.path_operation_response_link porl ON spr.id = porl.shared_path_response_id
    INNER JOIN apiome.path_operation po ON po.id = porl.path_operation_id
    {_OPERATIONS_OF_VERSION}
    LEFT JOIN apiome.classes c ON spr.class_id = c.id
    LEFT JOIN apiome.shared_path_response_content rc ON spr.id = rc.shared_path_response_id
    LEFT JOIN apiome.classes rc_class ON rc.class_id = rc_class.id
    WHERE vp.version_id = %s
    GROUP BY porl.path_operation_id, spr.id, spr.status_code, spr.description, spr.data,
             spr.class_id, c.name, spr.inline_schema
    ORDER BY porl.path_operation_id, spr.status_code
"""


async def _fetch(cur: Any, query: str, params: Sequence[Any]) -> list[dict[str, Any]]:
    """Run one statement on ``cur`` and return its rows as plain dicts."""
    await cur.execute(query, tuple(params))
    return [dict(row) for row in await cur.fetchall()]


def _group(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group detail rows by their operation, keeping row order and dropping the grouping key."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.pop(_OP_KEY)), []).append(row)
    return grouped


async def load_classes_and_properties(
    cur: Any,
    version_id: UUID,
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    """A revision's live classes and their properties, in at most two statements.

    Args:
        cur: An open dict-row cursor.
        version_id: The revision (``versions.id``).

    Returns:
        ``(classes, properties)``: the class rows by name, and ``{str(class id): [property, …]}``
        with an entry (possibly empty) for every class; properties are ordered parents first, then
        by name.
    """
    classes = await _fetch(
        cur,
        """
            SELECT id, version_id, name, description, schema, enabled
            FROM apiome.classes
            WHERE version_id = %s AND deleted_at IS NULL
            ORDER BY name ASC
        """,
        (version_id,),
    )
    if not classes:
        return [], {}

    props_rows = await _fetch(cur, CLASS_PROPERTIES_SQL, (version_id,))
    by_class: dict[str, list[dict[str, Any]]] = {}
    for row in props_rows:
        by_class.setdefault(str(row["class_id"]), []).append(row)
    return classes, {str(c["id"]): by_class.get(str(c["id"]), []) for c in classes}


async def load_paths_tree(cur: Any, version_id: UUID, *, details: bool = True) -> list[dict[str, Any]]:
    """A revision's paths with their operations, in at most six statements (three without details).

    The shape :func:`app.paths_generator.generate_paths_for_openapi` reads: each path is
    ``{id, pathname, summary, description, operations}`` (by pathname) and each operation
    ``{id, operation, description, parameters, requestBody, responses}`` in method order (GET,
    POST, PUT, PATCH, DELETE, then any other).

    Args:
        cur: An open dict-row cursor.
        version_id: The revision (``versions.id``).
        details: When False, skip parameters, request bodies and responses (each operation gets
            ``[]`` / ``None`` / ``[]``). Enough for the operation index, which reads only the
            path, method and description.

    Returns:
        The paths; empty when the revision has none.
    """
    path_rows = await _fetch(cur, _PATHS_SQL, (version_id,))
    if not path_rows:
        return []

    params = (version_id,)
    operations = await _fetch(cur, _OPERATIONS_SQL, params)
    descriptions: dict[str, list[dict[str, Any]]] = {}
    parameters: dict[str, list[dict[str, Any]]] = {}
    request_bodies: dict[str, list[dict[str, Any]]] = {}
    responses: dict[str, list[dict[str, Any]]] = {}
    if operations:
        descriptions = _group(await _fetch(cur, _DESCRIPTIONS_SQL, params))
        if details:
            parameters = _group(await _fetch(cur, _PARAMETERS_SQL, params))
            request_bodies = _group(await _fetch(cur, _REQUEST_BODIES_SQL, params))
            responses = _group(await _fetch(cur, _RESPONSES_SQL, params))

    by_path: dict[str, list[dict[str, Any]]] = {}
    for op in operations:
        op_id = str(op["id"])
        # One description and one request body per operation (UNIQUE(path_operation_id)).
        description = descriptions.get(op_id)
        request_body = request_bodies.get(op_id)
        by_path.setdefault(str(op["version_path_id"]), []).append(
            {
                "id": op["id"],
                "operation": op["operation"],
                "description": description[0] if description else None,
                "parameters": parameters.get(op_id, []),
                "requestBody": request_body[0] if request_body else None,
                "responses": responses.get(op_id, []),
            }
        )

    return [
        {
            "id": path_row["id"],
            "pathname": path_row["pathname"],
            "summary": path_row.get("summary"),
            "description": path_row.get("description"),
            "operations": by_path.get(str(path_row["id"]), []),
        }
        for path_row in path_rows
    ]


async def load_security_scheme_rows(cur: Any, version_id: UUID) -> list[dict[str, Any]]:
    """A revision's security schemes by name (one statement)."""
    return await _fetch(
        cur,
        """
            SELECT version_id, scheme_name, scheme_type, param_name, in_location, description
            FROM apiome.version_security_scheme
            WHERE version_id = %s
            ORDER BY scheme_name
        """,
        (version_id,),
    )


async def load_server_rows(cur: Any, version_id: UUID) -> list[dict[str, Any]]:
    """A revision's servers in ``sort_order`` (one statement)."""
    return await _fetch(
        cur,
        """
            SELECT id, version_id, name, url, description, sort_order, variables, environment, created_at, updated_at
            FROM apiome.version_server
            WHERE version_id = %s
            ORDER BY sort_order, url
        """,
        (version_id,),
    )


async def load_component_pin_rows(cur: Any, version_id: UUID) -> list[dict[str, Any]]:
    """The materializer's rows for a revision's live component pins (one statement).

    The statement of apiome-rest's ``Database.get_materializable_pins_for_version``. Passing the
    rows to :func:`app.openapi_generator.generate_openapi_spec` keeps it from reading them itself
    through apiome-rest's own synchronous connection.
    """
    return await _fetch(
        cur,
        """
            SELECT c.kind, c.name AS component_name, p.local_name,
                   r.revision, r.canonical_payload AS payload,
                   c.id AS component_id, r.id AS revision_id
            FROM apiome.version_component_pins p
            JOIN apiome.operational_component_revisions r
              ON p.component_revision_id = r.id
            JOIN apiome.operational_components c ON r.component_id = c.id
            WHERE p.version_id = %s AND p.deleted_at IS NULL
        """,
        (version_id,),
    )


def _maybe_parse_json(val: Any) -> Any:
    """``val`` parsed when it is a JSON string (psycopg may return ``json_agg`` as text)."""
    if isinstance(val, str):
        try:
            return json.loads(val)
        except json.JSONDecodeError:
            return val
    return val


def _normalize_paths(paths_data: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Parse the ``content_types`` JSON of every request body and response, in place."""
    for path in paths_data:
        for op in path["operations"]:
            rb = op.get("requestBody")
            if rb and rb.get("content_types") is not None:
                rb["content_types"] = _maybe_parse_json(rb["content_types"])
            for resp in op.get("responses") or []:
                if resp.get("content_types") is not None:
                    resp["content_types"] = _maybe_parse_json(resp["content_types"])
    return paths_data


def _normalize_classes(classes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Class rows with ``id`` and ``version_id`` as strings (the generator keys properties by them)."""
    return [{**c, "id": str(c["id"]), "version_id": str(c["version_id"])} for c in classes]


@dataclass(frozen=True)
class OpenApiInputs:
    """The rows :func:`app.openapi_generator.generate_openapi_spec` builds a document from.

    Attributes:
        classes: Live class rows, by name; ``id`` and ``version_id`` are strings.
        all_properties: ``{class id: [property row, …]}``.
        paths_data: The paths tree (:func:`load_paths_tree`).
        security_scheme_rows: ``version_security_scheme`` rows, by name.
        server_rows: ``version_server`` rows, in order.
        component_pin_rows: The revision's materializable component pins.
    """

    classes: list[dict[str, Any]] = field(default_factory=list)
    all_properties: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    paths_data: list[dict[str, Any]] = field(default_factory=list)
    security_scheme_rows: list[dict[str, Any]] = field(default_factory=list)
    server_rows: list[dict[str, Any]] = field(default_factory=list)
    component_pin_rows: list[dict[str, Any]] = field(default_factory=list)

    def generator_kwargs(self) -> dict[str, Any]:
        """Keyword arguments for ``generate_openapi_spec`` after its three leading slugs.

        Every row set is passed explicitly (an empty list, never ``None``), so the generator runs
        no query of its own.
        """
        return {
            "classes": self.classes,
            "all_properties": self.all_properties,
            "paths_data": self.paths_data,
            "security_scheme_rows": self.security_scheme_rows,
            "server_rows": self.server_rows,
            "component_pin_rows": self.component_pin_rows,
        }


async def load_openapi_inputs(conn: Any, revision_id: UUID, *, part: OpenApiPart = "document") -> OpenApiInputs:
    """Read what one part of a revision's OpenAPI document is generated from.

    Args:
        conn: An open async connection.
        revision_id: The revision (``versions.id``).
        part: ``"document"`` reads everything (at most 11 statements); ``"operations"`` reads the
            paths, operations and their descriptions (at most 3), which is all the operation index
            (path, method, ``operationId``, summary, tags) depends on; ``"components"`` reads the
            classes, properties, security schemes and component pins (at most 4), which is all the
            ``components`` section depends on.

    Returns:
        The inputs; row sets the part does not need are empty.
    """
    classes: list[dict[str, Any]] = []
    all_properties: dict[str, list[dict[str, Any]]] = {}
    paths_data: list[dict[str, Any]] = []
    security_rows: list[dict[str, Any]] = []
    server_rows: list[dict[str, Any]] = []
    pin_rows: list[dict[str, Any]] = []
    async with conn.cursor(row_factory=dict_row) as cur:
        if part != "operations":
            classes, all_properties = await load_classes_and_properties(cur, revision_id)
        if part != "components":
            paths_data = await load_paths_tree(cur, revision_id, details=part == "document")
        if part != "operations":
            security_rows = await load_security_scheme_rows(cur, revision_id)
            pin_rows = await load_component_pin_rows(cur, revision_id)
        if part == "document":
            server_rows = await load_server_rows(cur, revision_id)
    return OpenApiInputs(
        classes=_normalize_classes(classes),
        all_properties=all_properties,
        paths_data=_normalize_paths(paths_data),
        security_scheme_rows=security_rows,
        server_rows=server_rows,
        component_pin_rows=pin_rows,
    )


async def fetch_openapi_generation_inputs_async(
    conn: Any,
    revision_id: UUID,
) -> tuple[
    list[dict[str, Any]],
    dict[str, list[dict[str, Any]]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """Return classes, properties-by-class-id, paths tree, security rows, server rows.

    The five-tuple apiome-mock unpacks; at most 10 statements (no component pins — a caller that
    wants the generator to run no query of its own uses :func:`load_openapi_inputs`).
    """
    async with conn.cursor(row_factory=dict_row) as cur:
        classes, all_properties = await load_classes_and_properties(cur, revision_id)
        paths_data = await load_paths_tree(cur, revision_id)
        security_rows = await load_security_scheme_rows(cur, revision_id)
        server_rows = await load_server_rows(cur, revision_id)
    return _normalize_classes(classes), all_properties, _normalize_paths(paths_data), security_rows, server_rows
