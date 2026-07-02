"""Async Postgres loaders for revision OpenAPI generation (shared logic with REST ``database`` queries)."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from psycopg.rows import dict_row


async def load_classes_and_properties(
    cur: Any,
    version_id: UUID,
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    await cur.execute(
        """
            SELECT id, version_id, name, description, schema, enabled
            FROM apiome.classes
            WHERE version_id = %s AND deleted_at IS NULL
            ORDER BY name ASC
        """,
        (version_id,),
    )
    classes = list(await cur.fetchall())
    if not classes:
        return [], {}

    class_ids = [c["id"] for c in classes]
    placeholders = ",".join(["%s"] * len(class_ids))
    await cur.execute(
        f"""
            SELECT cp.id, cp.class_id, cp.property_id, cp.name, cp.description, cp.data, cp.parent_id,
                   p.id as property_source_id, p.name as property_source_name, p.data as property_source_data
            FROM apiome.class_properties cp
            LEFT JOIN apiome.properties p ON cp.property_id = p.id
            WHERE cp.class_id IN ({placeholders})
            ORDER BY cp.class_id, cp.parent_id NULLS FIRST, cp.name ASC
        """,
        tuple(class_ids),
    )
    props_rows = await cur.fetchall()
    by_class: dict[str, list[dict[str, Any]]] = {}
    for row in props_rows:
        cid = row["class_id"]
        by_class.setdefault(str(cid), []).append(dict(row))
    all_properties: dict[str, list[dict[str, Any]]] = {}
    for c in classes:
        all_properties[str(c["id"])] = by_class.get(str(c["id"]), [])
    return classes, all_properties


async def load_paths_tree(cur: Any, version_id: UUID) -> list[dict[str, Any]]:
    await cur.execute(
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
    paths_data = await cur.fetchall()
    paths: list[dict[str, Any]] = []

    for path_row in paths_data:
        pr = dict(path_row)
        await cur.execute(
            """
                SELECT id, version_path_id, operation, metadata, created_at, updated_at
                FROM apiome.path_operation
                WHERE version_path_id = %s
                ORDER BY CASE operation
                    WHEN 'GET' THEN 1 WHEN 'POST' THEN 2 WHEN 'PUT' THEN 3
                    WHEN 'PATCH' THEN 4 WHEN 'DELETE' THEN 5 ELSE 6
                END
            """,
            (pr["id"],),
        )
        operations_data = await cur.fetchall()
        operations: list[dict[str, Any]] = []

        for op_row in operations_data:
            op = dict(op_row)
            await cur.execute(
                """
                    SELECT
                        id,
                        summary,
                        description,
                        operation_id,
                        metadata->'tags' as tags,
                        (metadata->>'deprecated')::boolean as deprecated,
                        (metadata->>'x-private')::boolean as x_private,
                        metadata->'external_docs' as external_docs,
                        metadata
                    FROM apiome.path_operation_description
                    WHERE path_operation_id = %s
                    LIMIT 1
                """,
                (op["id"],),
            )
            op_description = await cur.fetchone()

            await cur.execute(
                """
                    SELECT spp.id, spp.name, spp.in_location, spp.summary, spp.description, spp.data
                    FROM apiome.shared_path_parameter spp
                    INNER JOIN apiome.path_operation_parameter_link popl ON spp.id = popl.shared_path_parameter_id
                    WHERE popl.path_operation_id = %s
                    ORDER BY CASE spp.in_location
                        WHEN 'path' THEN 1 WHEN 'query' THEN 2 WHEN 'header' THEN 3 ELSE 4
                    END, spp.name
                """,
                (op["id"],),
            )
            parameters = list(await cur.fetchall())

            await cur.execute(
                """
                    SELECT rb.id, rb.name, rb.description, rb.required,
                        COALESCE(json_agg(json_build_object(
                            'id', rbc.id, 'media_type', rbc.media_type, 'class_id', rbc.class_id,
                            'class_name', c.name, 'inline_schema', rbc.inline_schema,
                            'encoding', rbc.encoding, 'examples', rbc.examples
                        )) FILTER (WHERE rbc.id IS NOT NULL), '[]') as content_types
                    FROM apiome.shared_path_request_body rb
                    INNER JOIN apiome.path_operation_request_body_link link ON rb.id = link.shared_path_request_body_id
                    LEFT JOIN apiome.shared_path_request_body_content rbc ON rb.id = rbc.shared_path_request_body_id
                    LEFT JOIN apiome.classes c ON rbc.class_id = c.id
                    WHERE link.path_operation_id = %s
                    GROUP BY rb.id
                """,
                (op["id"],),
            )
            rb_row = await cur.fetchone()
            request_body = dict(rb_row) if rb_row else None

            await cur.execute(
                """
                    SELECT
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
                                )
                            ) FILTER (WHERE rc.id IS NOT NULL),
                            '[]'
                        ) as content_types
                    FROM apiome.shared_path_response spr
                    INNER JOIN apiome.path_operation_response_link porl ON spr.id = porl.shared_path_response_id
                    LEFT JOIN apiome.classes c ON spr.class_id = c.id
                    LEFT JOIN apiome.shared_path_response_content rc ON spr.id = rc.shared_path_response_id
                    LEFT JOIN apiome.classes rc_class ON rc.class_id = rc_class.id
                    WHERE porl.path_operation_id = %s
                    GROUP BY spr.id, spr.status_code, spr.description, spr.data, spr.class_id, c.name, spr.inline_schema
                    ORDER BY spr.status_code
                """,
                (op["id"],),
            )
            responses = list(await cur.fetchall())

            operations.append(
                {
                    "id": op["id"],
                    "operation": op["operation"],
                    "description": dict(op_description) if op_description else None,
                    "parameters": [dict(p) for p in parameters],
                    "requestBody": request_body,
                    "responses": [dict(r) for r in responses],
                }
            )

        paths.append(
            {
                "id": pr["id"],
                "pathname": pr["pathname"],
                "summary": pr.get("summary"),
                "description": pr.get("description"),
                "operations": operations,
            }
        )

    return paths


async def load_security_scheme_rows(cur: Any, version_id: UUID) -> list[dict[str, Any]]:
    await cur.execute(
        """
            SELECT version_id, scheme_name, scheme_type, param_name, in_location, description
            FROM apiome.version_security_scheme
            WHERE version_id = %s
            ORDER BY scheme_name
        """,
        (version_id,),
    )
    rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def load_server_rows(cur: Any, version_id: UUID) -> list[dict[str, Any]]:
    await cur.execute(
        """
            SELECT id, version_id, name, url, description, sort_order, variables, environment, created_at, updated_at
            FROM apiome.version_server
            WHERE version_id = %s
            ORDER BY sort_order, url
        """,
        (version_id,),
    )
    rows = await cur.fetchall()
    return [dict(r) for r in rows]


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
    """Return classes, properties-by-class-id, paths tree, security rows, server rows."""
    async with conn.cursor(row_factory=dict_row) as cur:
        classes, all_properties = await load_classes_and_properties(cur, revision_id)
        paths_data = await load_paths_tree(cur, revision_id)
        security_rows = await load_security_scheme_rows(cur, revision_id)
        server_rows = await load_server_rows(cur, revision_id)

    # Normalize JSON-like columns to plain dict/list (psycopg may return str for json_agg in some configs)
    def _maybe_parse_json(val: Any) -> Any:
        if isinstance(val, (dict, list)) or val is None:
            return val
        if isinstance(val, str):
            try:
                return json.loads(val)
            except json.JSONDecodeError:
                return val
        return val

    for path in paths_data:
        for op in path["operations"]:
            rb = op.get("requestBody")
            if rb and rb.get("content_types") is not None:
                rb["content_types"] = _maybe_parse_json(rb["content_types"])
            for resp in op.get("responses") or []:
                if resp.get("content_types") is not None:
                    resp["content_types"] = _maybe_parse_json(resp["content_types"])

    norm_classes: list[dict[str, Any]] = []
    for c in classes:
        nc = dict(c)
        nc["id"] = str(nc["id"])
        nc["version_id"] = str(nc["version_id"])
        norm_classes.append(nc)

    return norm_classes, all_properties, paths_data, security_rows, server_rows
