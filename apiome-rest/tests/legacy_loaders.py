"""The per-row loaders DBP-1.6 (#7189) replaced, kept as the parity reference.

``tests/test_path_operation_loader_db.py`` loads every corpus document with these and with the
set-based loaders, and requires identical output. They are copies of the code on ``main`` before
the change (``openapi_generator._load_paths_for_version``, ``paths_routes.get_path_full`` and
``canonical_persistence.load_canonical_api``); do not use them anywhere else.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.canonical_model import CanonicalApi
from app.canonical_persistence import _DbLike, _fetch_all, load_canonical_tree


def legacy_operations_for_path(db: Any, path_id: str) -> List[Dict[str, Any]]:
    """``get_path_full``'s operations: one query per path and four per operation."""
    operations = []
    for op in db.get_operations_for_path(path_id):
        op_id = op["id"]
        operations.append({
            **op,
            "description": db.get_operation_description(op_id),
            "parameters": db.get_parameters_for_operation(op_id),
            "requestBody": db.get_request_body_for_operation(op_id),
            "responses": db.get_responses_for_operation(op_id),
        })
    return operations


def legacy_paths_for_version(db: Any, version_id: str) -> List[Dict[str, Any]]:
    """``_load_paths_for_version`` before DBP-1.6: ``1 + P + 4·O`` statements."""
    paths: List[Dict[str, Any]] = []
    for path_row in db.get_paths_for_version(version_id):
        operations = []
        for op_row in db.get_operations_for_path(path_row["id"]):
            operations.append({
                "id": op_row["id"],
                "operation": op_row["operation"],
                "metadata": op_row.get("metadata"),
                "description": db.get_operation_description(op_row["id"]),
                "parameters": db.get_parameters_for_operation(op_row["id"]),
                "requestBody": db.get_request_body_for_operation(op_row["id"]),
                "responses": db.get_responses_for_operation(op_row["id"]),
            })
        paths.append({
            "id": path_row["id"],
            "pathname": path_row["pathname"],
            "summary": path_row.get("summary"),
            "description": path_row.get("description"),
            "operations": operations,
        })
    return paths


def legacy_load_canonical_api(
    db: _DbLike,
    *,
    tenant_id: str,
    version_id: str,
) -> Optional[CanonicalApi]:
    """Load the live canonical artifact for ``version_id``, or ``None`` if absent.

    Args:
        db: Database handle exposing :meth:`connect`.
        tenant_id: Owning tenant UUID.
        version_id: Target ``versions.id`` UUID.

    Returns:
        The reconstructed :class:`CanonicalApi`, or ``None`` when no live artifact exists.
    """
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            arts = _fetch_all(
                cursor,
                """
                SELECT * FROM apiome.api_artifacts
                WHERE tenant_id = %s::uuid AND version_id = %s::uuid AND deleted_at IS NULL
                LIMIT 1
                """,
                (tenant_id, version_id),
            )
            if not arts:
                conn.commit()
                return None
            art = arts[0]
            artifact_id = str(art["id"])

            services_rows = _fetch_all(
                cursor,
                """
                SELECT * FROM apiome.api_services
                WHERE artifact_id = %s::uuid AND deleted_at IS NULL
                ORDER BY ordinal ASC, key ASC
                """,
                (artifact_id,),
            )
            services: List[Dict[str, Any]] = []
            for svc in services_rows:
                service_id = str(svc["id"])
                op_rows = _fetch_all(
                    cursor,
                    """
                    SELECT * FROM apiome.api_operations
                    WHERE service_id = %s::uuid AND deleted_at IS NULL
                    ORDER BY ordinal ASC, key ASC
                    """,
                    (service_id,),
                )
                operations: List[Dict[str, Any]] = []
                for op in op_rows:
                    operation_id = str(op["id"])
                    msg_rows = _fetch_all(
                        cursor,
                        """
                        SELECT * FROM apiome.api_messages
                        WHERE operation_id = %s::uuid AND deleted_at IS NULL
                        ORDER BY ordinal ASC, key ASC
                        """,
                        (operation_id,),
                    )
                    operations.append(
                        {
                            "key": op["key"],
                            "name": op["name"],
                            "kind": op["kind"],
                            "streaming": op["streaming"],
                            "http_method": op.get("http_method"),
                            "http_path": op.get("http_path"),
                            "channel_ref": op.get("channel_ref"),
                            "description": op.get("description"),
                            "deprecated": op.get("deprecated"),
                            "parameters": op.get("parameters") or [],
                            "tags": op.get("tags") or [],
                            "ordinal": op.get("ordinal") or 0,
                            "extras": op.get("extras") or {},
                            "messages": [
                                {
                                    "key": m["key"],
                                    "role": m["role"],
                                    "name": m.get("name"),
                                    "payload": m.get("payload"),
                                    "payload_schema": m.get("payload_schema"),
                                    "headers": m.get("headers") or [],
                                    "content_types": m.get("content_types") or [],
                                    "status_code": m.get("status_code"),
                                    "description": m.get("description"),
                                    "ordinal": m.get("ordinal") or 0,
                                    "extras": m.get("extras") or {},
                                }
                                for m in msg_rows
                            ],
                        }
                    )
                services.append(
                    {
                        "key": svc["key"],
                        "name": svc["name"],
                        "description": svc.get("description"),
                        "ordinal": svc.get("ordinal") or 0,
                        "extras": svc.get("extras") or {},
                        "operations": operations,
                    }
                )

            channel_rows = _fetch_all(
                cursor,
                """
                SELECT * FROM apiome.api_channels
                WHERE artifact_id = %s::uuid AND deleted_at IS NULL
                ORDER BY ordinal ASC, key ASC
                """,
                (artifact_id,),
            )
            channels = [
                {
                    "key": ch["key"],
                    "address": ch["address"],
                    "name": ch.get("name"),
                    "description": ch.get("description"),
                    "protocol": ch.get("protocol"),
                    "parameters": ch.get("parameters") or [],
                    "bindings": ch.get("bindings") or {},
                    "ordinal": ch.get("ordinal") or 0,
                    "extras": ch.get("extras") or {},
                }
                for ch in channel_rows
            ]

            type_rows = _fetch_all(
                cursor,
                """
                SELECT * FROM apiome.api_types
                WHERE artifact_id = %s::uuid AND deleted_at IS NULL
                ORDER BY ordinal ASC, key ASC
                """,
                (artifact_id,),
            )
            types: List[Dict[str, Any]] = []
            for ty in type_rows:
                type_id = str(ty["id"])
                field_rows = _fetch_all(
                    cursor,
                    """
                    SELECT * FROM apiome.api_fields
                    WHERE type_id = %s::uuid AND deleted_at IS NULL
                    ORDER BY ordinal ASC, key ASC
                    """,
                    (type_id,),
                )
                types.append(
                    {
                        "key": ty["key"],
                        "name": ty["name"],
                        "kind": ty["kind"],
                        "namespace": ty.get("namespace"),
                        "description": ty.get("description"),
                        "deprecated": ty.get("deprecated"),
                        "enum_values": ty.get("enum_values") or [],
                        "union_members": ty.get("union_members") or [],
                        "aliased": ty.get("aliased"),
                        "key_type": ty.get("key_type"),
                        "value_type": ty.get("value_type"),
                        "constraints": ty.get("constraints"),
                        "ordinal": ty.get("ordinal") or 0,
                        "extras": ty.get("extras") or {},
                        "fields": [
                            {
                                "key": f["key"],
                                "name": f["name"],
                                "type_ref": f["type_ref"],
                                "field_number": f.get("field_number"),
                                "default_value": f.get("default_value"),
                                "constraints": f.get("constraints"),
                                "description": f.get("description"),
                                "deprecated": f.get("deprecated"),
                                "ordinal": f.get("ordinal") or 0,
                                "extras": f.get("extras") or {},
                            }
                            for f in field_rows
                        ],
                    }
                )

            agent_rows = _fetch_all(
                cursor,
                """
                SELECT * FROM apiome.api_agent_descriptors
                WHERE artifact_id = %s::uuid AND deleted_at IS NULL
                ORDER BY ordinal ASC, key ASC
                """,
                (artifact_id,),
            )
            agents: List[Dict[str, Any]] = []
            for ag in agent_rows:
                skill_rows = _fetch_all(
                    cursor,
                    """
                    SELECT * FROM apiome.api_agent_skills
                    WHERE agent_id = %s::uuid AND deleted_at IS NULL
                    ORDER BY ordinal ASC, key ASC
                    """,
                    (str(ag["id"]),),
                )
                agents.append(
                    {
                        **{k: ag.get(k) for k in (
                            "key", "name", "description", "url", "protocol", "protocol_version",
                            "provider", "capabilities", "default_input_modes",
                            "default_output_modes", "security_schemes", "security",
                            "service_ref", "ordinal", "extras",
                        )},
                        "version": ag.get("agent_version"),
                        "skills": [
                            {k: sk.get(k) for k in (
                                "key", "skill_id", "name", "description", "tags", "examples",
                                "input_modes", "output_modes", "security", "operation_ref",
                                "ordinal", "extras",
                            )}
                            for sk in skill_rows
                        ],
                    }
                )

            tree = {
                "artifact": {
                    "schema_version": art["schema_version"],
                    "paradigm": art["paradigm"],
                    "format": art["format"],
                    "protocol": art.get("protocol"),
                    "identity_name": art["identity_name"],
                    "identity_namespace": art.get("identity_namespace"),
                    "identity_id": art.get("identity_id"),
                    "source_version": art.get("source_version"),
                    "title": art.get("title"),
                    "description": art.get("description"),
                    "servers": art.get("servers") or [],
                    "extras": art.get("extras") or {},
                    "raw": art.get("raw"),
                },
                "services": services,
                "channels": channels,
                "types": types,
                "agents": agents,
            }
        conn.commit()
        return load_canonical_tree(tree)
    except Exception:
        conn.rollback()
        raise
