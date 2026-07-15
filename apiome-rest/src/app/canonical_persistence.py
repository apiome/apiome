"""Persist / reload :class:`~app.canonical_model.CanonicalApi` into MFI-2.2 tables (#2772).

V135 created the relational home for the canonical tree
(``api_artifacts`` → services/operations/messages, channels, types/fields). Until this
module, adapters only stored source bytes on ``versions.format_metadata``; nothing wrote
the queryable rows. These helpers fill that gap:

* :func:`dump_canonical_tree` / :func:`load_canonical_tree` — pure nested-dict codecs used
  by tests and by the SQL layer (lossless against ``CanonicalApi`` equality);
* :func:`persist_canonical_api` — soft-deletes any live artifact for the version, then
  inserts the full tree;
* :func:`load_canonical_api` — reads the live artifact for a version back into a model.

Message fields that are not first-class columns (today: ``required``) ride in
``api_messages.extras`` under reserved keys so reload reconstructs the Pydantic model.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Protocol, Sequence

from .canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Channel,
    EnumValue,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Parameter,
    Server,
    Service,
    StreamingMode,
    Type,
    TypeKind,
    TypeRef,
)

__all__ = [
    "dump_canonical_tree",
    "load_canonical_tree",
    "persist_canonical_api",
    "load_canonical_api",
]

# Reserved extras keys used when a Pydantic field has no dedicated column.
_MSG_REQUIRED_KEY = "_canonical_required"


class _DbLike(Protocol):
    """Minimal database surface used by :func:`persist_canonical_api` / :func:`load_canonical_api`."""

    def connect(self) -> Any: ...


def _json(value: Any) -> Any:
    """Return a JSON-serializable value (psycopg2 needs plain dict/list for JSONB)."""
    if value is None:
        return None
    return json.loads(json.dumps(value, default=str))


def _dump_model(obj: Any) -> Any:
    """Dump a Pydantic model (or list thereof) with JSON-compatible enums."""
    if obj is None:
        return None
    if isinstance(obj, list):
        return [_dump_model(item) for item in obj]
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    return obj


def dump_canonical_tree(model: CanonicalApi) -> Dict[str, Any]:
    """Serialize ``model`` into a nested dict tree ready for SQL inserts / tests.

    Args:
        model: The canonical API to encode.

    Returns:
        A JSON-ready dict with ``artifact``, ``services`` (each with nested ``operations``
        and ``messages``), ``channels``, and ``types`` (each with nested ``fields``).
    """
    services: List[Dict[str, Any]] = []
    for svc_ord, service in enumerate(model.services):
        operations: List[Dict[str, Any]] = []
        for op_ord, operation in enumerate(service.operations):
            messages: List[Dict[str, Any]] = []
            for msg_ord, message in enumerate(operation.messages):
                extras = dict(message.extras or {})
                if message.required:
                    extras[_MSG_REQUIRED_KEY] = True
                messages.append(
                    {
                        "key": message.key,
                        "role": message.role.value,
                        "name": message.name,
                        "payload": _dump_model(message.payload),
                        "payload_schema": _json(message.payload_schema),
                        "headers": _dump_model(message.headers),
                        "content_types": list(message.content_types or []),
                        "status_code": message.status_code,
                        "description": message.description,
                        "ordinal": msg_ord,
                        "extras": extras,
                    }
                )
            operations.append(
                {
                    "key": operation.key,
                    "name": operation.name,
                    "kind": operation.kind.value,
                    "streaming": operation.streaming.value,
                    "http_method": operation.http_method,
                    "http_path": operation.http_path,
                    "channel_ref": operation.channel_ref,
                    "description": operation.description,
                    "deprecated": operation.deprecated,
                    "parameters": _dump_model(operation.parameters),
                    "tags": list(operation.tags or []),
                    "ordinal": op_ord,
                    "extras": dict(operation.extras or {}),
                    "messages": messages,
                }
            )
        services.append(
            {
                "key": service.key,
                "name": service.name,
                "description": service.description,
                "ordinal": svc_ord,
                "extras": dict(service.extras or {}),
                "operations": operations,
            }
        )

    channels: List[Dict[str, Any]] = []
    for ch_ord, channel in enumerate(model.channels):
        channels.append(
            {
                "key": channel.key,
                "address": channel.address,
                "name": channel.name,
                "description": channel.description,
                "protocol": channel.protocol,
                "parameters": _dump_model(channel.parameters),
                "bindings": _json(channel.bindings) or {},
                "ordinal": ch_ord,
                "extras": dict(channel.extras or {}),
            }
        )

    types: List[Dict[str, Any]] = []
    for ty_ord, type_ in enumerate(model.types):
        fields: List[Dict[str, Any]] = []
        for f_ord, field in enumerate(type_.fields):
            fields.append(
                {
                    "key": field.key,
                    "name": field.name,
                    "type_ref": _dump_model(field.type),
                    "field_number": field.field_number,
                    "default_value": _json(field.default),
                    "constraints": _dump_model(field.constraints),
                    "description": field.description,
                    "deprecated": field.deprecated,
                    "ordinal": f_ord,
                    "extras": dict(field.extras or {}),
                }
            )
        types.append(
            {
                "key": type_.key,
                "name": type_.name,
                "kind": type_.kind.value,
                "namespace": type_.namespace,
                "description": type_.description,
                "deprecated": type_.deprecated,
                "enum_values": _dump_model(type_.enum_values) or [],
                "union_members": list(type_.union_members or []),
                "aliased": _dump_model(type_.aliased),
                "key_type": _dump_model(type_.key_type),
                "value_type": _dump_model(type_.value_type),
                "constraints": _dump_model(type_.constraints),
                "ordinal": ty_ord,
                "extras": dict(type_.extras or {}),
                "fields": fields,
            }
        )

    return {
        "artifact": {
            "schema_version": model.schema_version,
            "paradigm": model.paradigm.value,
            "format": model.format,
            "protocol": model.protocol,
            "identity_name": model.identity.name,
            "identity_namespace": model.identity.namespace,
            "identity_id": model.identity.id,
            "source_version": model.version,
            "title": model.title,
            "description": model.description,
            "servers": _dump_model(model.servers) or [],
            "extras": dict(model.extras or {}),
            "raw": _json(model.raw),
        },
        "services": services,
        "channels": channels,
        "types": types,
    }


def _validate_list(model_cls: Any, items: Any) -> List[Any]:
    if not isinstance(items, list):
        return []
    return [model_cls.model_validate(item) for item in items]


def load_canonical_tree(tree: Dict[str, Any]) -> CanonicalApi:
    """Rebuild a :class:`CanonicalApi` from a :func:`dump_canonical_tree` payload.

    Args:
        tree: Nested dict produced by :func:`dump_canonical_tree` or assembled from SQL rows.

    Returns:
        The reconstructed canonical model.
    """
    art = tree["artifact"]
    services: List[Service] = []
    for svc in tree.get("services") or []:
        operations: List[Operation] = []
        for op in svc.get("operations") or []:
            messages: List[Message] = []
            for msg in op.get("messages") or []:
                extras = dict(msg.get("extras") or {})
                required = bool(extras.pop(_MSG_REQUIRED_KEY, False))
                payload_raw = msg.get("payload")
                messages.append(
                    Message(
                        key=msg["key"],
                        role=MessageRole(msg["role"]),
                        name=msg.get("name"),
                        payload=(
                            TypeRef.model_validate(payload_raw)
                            if isinstance(payload_raw, dict)
                            else None
                        ),
                        payload_schema=msg.get("payload_schema"),
                        headers=_validate_list(CanonicalField, msg.get("headers")),
                        content_types=list(msg.get("content_types") or []),
                        required=required,
                        status_code=msg.get("status_code"),
                        description=msg.get("description"),
                        extras=extras,
                    )
                )
            operations.append(
                Operation(
                    key=op["key"],
                    name=op["name"],
                    kind=OperationKind(op["kind"]),
                    streaming=StreamingMode(op.get("streaming") or "none"),
                    http_method=op.get("http_method"),
                    http_path=op.get("http_path"),
                    channel_ref=op.get("channel_ref"),
                    description=op.get("description"),
                    deprecated=bool(op.get("deprecated")),
                    parameters=_validate_list(Parameter, op.get("parameters")),
                    messages=messages,
                    tags=list(op.get("tags") or []),
                    extras=dict(op.get("extras") or {}),
                )
            )
        services.append(
            Service(
                key=svc["key"],
                name=svc["name"],
                description=svc.get("description"),
                operations=operations,
                extras=dict(svc.get("extras") or {}),
            )
        )

    channels: List[Channel] = []
    for ch in tree.get("channels") or []:
        channels.append(
            Channel(
                key=ch["key"],
                address=ch["address"],
                name=ch.get("name"),
                description=ch.get("description"),
                protocol=ch.get("protocol"),
                parameters=_validate_list(CanonicalField, ch.get("parameters")),
                bindings=dict(ch.get("bindings") or {}),
                extras=dict(ch.get("extras") or {}),
            )
        )

    types: List[Type] = []
    for ty in tree.get("types") or []:
        fields = [
            CanonicalField(
                key=f["key"],
                name=f["name"],
                type=TypeRef.model_validate(f["type_ref"]),
                field_number=f.get("field_number"),
                default=f.get("default_value"),
                constraints=f.get("constraints"),
                description=f.get("description"),
                deprecated=bool(f.get("deprecated")),
                extras=dict(f.get("extras") or {}),
            )
            for f in ty.get("fields") or []
        ]
        # Constraints may arrive as dict from JSONB.
        constraints = ty.get("constraints")
        if isinstance(constraints, dict):
            from .canonical_model import Constraints

            constraints = Constraints.model_validate(constraints)
        aliased = ty.get("aliased")
        if isinstance(aliased, dict):
            aliased = TypeRef.model_validate(aliased)
        key_type = ty.get("key_type")
        if isinstance(key_type, dict):
            key_type = TypeRef.model_validate(key_type)
        value_type = ty.get("value_type")
        if isinstance(value_type, dict):
            value_type = TypeRef.model_validate(value_type)
        for i, field in enumerate(fields):
            c = field.constraints
            if isinstance(c, dict):
                from .canonical_model import Constraints

                fields[i] = field.model_copy(
                    update={"constraints": Constraints.model_validate(c)}
                )
        types.append(
            Type(
                key=ty["key"],
                name=ty["name"],
                kind=TypeKind(ty["kind"]),
                namespace=ty.get("namespace"),
                description=ty.get("description"),
                deprecated=bool(ty.get("deprecated")),
                fields=fields,
                enum_values=_validate_list(EnumValue, ty.get("enum_values")),
                union_members=list(ty.get("union_members") or []),
                aliased=aliased,
                key_type=key_type,
                value_type=value_type,
                constraints=constraints,
                extras=dict(ty.get("extras") or {}),
            )
        )

    return CanonicalApi(
        schema_version=int(art.get("schema_version") or 1),
        paradigm=ApiParadigm(art["paradigm"]),
        format=art["format"],
        protocol=art.get("protocol"),
        identity=ApiIdentity(
            name=art["identity_name"],
            namespace=art.get("identity_namespace"),
            id=art.get("identity_id"),
        ),
        version=art.get("source_version"),
        title=art.get("title"),
        description=art.get("description"),
        servers=_validate_list(Server, art.get("servers")),
        services=services,
        channels=channels,
        types=types,
        raw=art.get("raw"),
        extras=dict(art.get("extras") or {}),
    )


def _soft_delete_live_artifact(cursor: Any, *, tenant_id: str, version_id: str) -> None:
    """Soft-delete the live artifact and all descendant rows for ``version_id``."""
    cursor.execute(
        """
        SELECT id FROM apiome.api_artifacts
        WHERE tenant_id = %s::uuid AND version_id = %s::uuid AND deleted_at IS NULL
        """,
        (tenant_id, version_id),
    )
    row = cursor.fetchone()
    if not row:
        return
    artifact_id = row["id"] if isinstance(row, dict) else row[0]

    cursor.execute(
        """
        UPDATE apiome.api_messages SET deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
        WHERE version_id = %s::uuid AND deleted_at IS NULL
        """,
        (version_id,),
    )
    cursor.execute(
        """
        UPDATE apiome.api_operations SET deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
        WHERE version_id = %s::uuid AND deleted_at IS NULL
        """,
        (version_id,),
    )
    cursor.execute(
        """
        UPDATE apiome.api_fields SET deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
        WHERE version_id = %s::uuid AND deleted_at IS NULL
        """,
        (version_id,),
    )
    cursor.execute(
        """
        UPDATE apiome.api_types SET deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
        WHERE artifact_id = %s::uuid AND deleted_at IS NULL
        """,
        (artifact_id,),
    )
    cursor.execute(
        """
        UPDATE apiome.api_channels SET deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
        WHERE artifact_id = %s::uuid AND deleted_at IS NULL
        """,
        (artifact_id,),
    )
    cursor.execute(
        """
        UPDATE apiome.api_services SET deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
        WHERE artifact_id = %s::uuid AND deleted_at IS NULL
        """,
        (artifact_id,),
    )
    cursor.execute(
        """
        UPDATE apiome.api_artifacts SET deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
        WHERE id = %s::uuid AND deleted_at IS NULL
        """,
        (artifact_id,),
    )


def _insert_tree(
    cursor: Any,
    *,
    tenant_id: str,
    creator_id: str,
    version_id: str,
    tree: Dict[str, Any],
) -> str:
    """Insert a dumped tree; return the new artifact id."""
    art = tree["artifact"]
    cursor.execute(
        """
        INSERT INTO apiome.api_artifacts (
            tenant_id, version_id, creator_id, schema_version, paradigm, format, protocol,
            identity_name, identity_namespace, identity_id, source_version, title, description,
            servers, extras, raw
        ) VALUES (
            %s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s,
            %s::jsonb, %s::jsonb, %s::jsonb
        )
        RETURNING id
        """,
        (
            tenant_id,
            version_id,
            creator_id,
            art["schema_version"],
            art["paradigm"],
            art["format"],
            art.get("protocol"),
            art["identity_name"],
            art.get("identity_namespace"),
            art.get("identity_id"),
            art.get("source_version"),
            art.get("title"),
            art.get("description"),
            json.dumps(art.get("servers") or []),
            json.dumps(art.get("extras") or {}),
            json.dumps(art.get("raw")) if art.get("raw") is not None else None,
        ),
    )
    artifact_row = cursor.fetchone()
    artifact_id = str(artifact_row["id"] if isinstance(artifact_row, dict) else artifact_row[0])

    for svc in tree.get("services") or []:
        cursor.execute(
            """
            INSERT INTO apiome.api_services (
                tenant_id, version_id, artifact_id, key, name, description, ordinal, extras
            ) VALUES (%s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s, %s::jsonb)
            RETURNING id
            """,
            (
                tenant_id,
                version_id,
                artifact_id,
                svc["key"],
                svc["name"],
                svc.get("description"),
                svc.get("ordinal") or 0,
                json.dumps(svc.get("extras") or {}),
            ),
        )
        service_row = cursor.fetchone()
        service_id = str(service_row["id"] if isinstance(service_row, dict) else service_row[0])

        for op in svc.get("operations") or []:
            cursor.execute(
                """
                INSERT INTO apiome.api_operations (
                    tenant_id, version_id, service_id, key, name, kind, streaming,
                    http_method, http_path, channel_ref, description, deprecated,
                    parameters, tags, ordinal, extras
                ) VALUES (
                    %s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s::jsonb, %s::jsonb, %s, %s::jsonb
                )
                RETURNING id
                """,
                (
                    tenant_id,
                    version_id,
                    service_id,
                    op["key"],
                    op["name"],
                    op["kind"],
                    op.get("streaming") or "none",
                    op.get("http_method"),
                    op.get("http_path"),
                    op.get("channel_ref"),
                    op.get("description"),
                    bool(op.get("deprecated")),
                    json.dumps(op.get("parameters") or []),
                    json.dumps(op.get("tags") or []),
                    op.get("ordinal") or 0,
                    json.dumps(op.get("extras") or {}),
                ),
            )
            op_row = cursor.fetchone()
            operation_id = str(op_row["id"] if isinstance(op_row, dict) else op_row[0])

            for msg in op.get("messages") or []:
                cursor.execute(
                    """
                    INSERT INTO apiome.api_messages (
                        tenant_id, version_id, operation_id, key, role, name,
                        payload, payload_schema, headers, content_types,
                        status_code, description, ordinal, extras
                    ) VALUES (
                        %s::uuid, %s::uuid, %s::uuid, %s, %s, %s,
                        %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb,
                        %s, %s, %s, %s::jsonb
                    )
                    """,
                    (
                        tenant_id,
                        version_id,
                        operation_id,
                        msg["key"],
                        msg["role"],
                        msg.get("name"),
                        json.dumps(msg["payload"]) if msg.get("payload") is not None else None,
                        json.dumps(msg["payload_schema"])
                        if msg.get("payload_schema") is not None
                        else None,
                        json.dumps(msg.get("headers") or []),
                        json.dumps(msg.get("content_types") or []),
                        msg.get("status_code"),
                        msg.get("description"),
                        msg.get("ordinal") or 0,
                        json.dumps(msg.get("extras") or {}),
                    ),
                )

    for ch in tree.get("channels") or []:
        cursor.execute(
            """
            INSERT INTO apiome.api_channels (
                tenant_id, version_id, artifact_id, key, address, name, description,
                protocol, parameters, bindings, ordinal, extras
            ) VALUES (
                %s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s,
                %s, %s::jsonb, %s::jsonb, %s, %s::jsonb
            )
            """,
            (
                tenant_id,
                version_id,
                artifact_id,
                ch["key"],
                ch["address"],
                ch.get("name"),
                ch.get("description"),
                ch.get("protocol"),
                json.dumps(ch.get("parameters") or []),
                json.dumps(ch.get("bindings") or {}),
                ch.get("ordinal") or 0,
                json.dumps(ch.get("extras") or {}),
            ),
        )

    for ty in tree.get("types") or []:
        cursor.execute(
            """
            INSERT INTO apiome.api_types (
                tenant_id, version_id, artifact_id, key, name, kind, namespace,
                description, deprecated, enum_values, union_members, aliased,
                key_type, value_type, constraints, ordinal, extras
            ) VALUES (
                %s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s,
                %s, %s, %s::jsonb, %s::jsonb, %s::jsonb,
                %s::jsonb, %s::jsonb, %s::jsonb, %s, %s::jsonb
            )
            RETURNING id
            """,
            (
                tenant_id,
                version_id,
                artifact_id,
                ty["key"],
                ty["name"],
                ty["kind"],
                ty.get("namespace"),
                ty.get("description"),
                bool(ty.get("deprecated")),
                json.dumps(ty.get("enum_values") or []),
                json.dumps(ty.get("union_members") or []),
                json.dumps(ty["aliased"]) if ty.get("aliased") is not None else None,
                json.dumps(ty["key_type"]) if ty.get("key_type") is not None else None,
                json.dumps(ty["value_type"]) if ty.get("value_type") is not None else None,
                json.dumps(ty["constraints"]) if ty.get("constraints") is not None else None,
                ty.get("ordinal") or 0,
                json.dumps(ty.get("extras") or {}),
            ),
        )
        type_row = cursor.fetchone()
        type_id = str(type_row["id"] if isinstance(type_row, dict) else type_row[0])
        for field in ty.get("fields") or []:
            cursor.execute(
                """
                INSERT INTO apiome.api_fields (
                    tenant_id, version_id, type_id, key, name, type_ref, field_number,
                    default_value, constraints, description, deprecated, ordinal, extras
                ) VALUES (
                    %s::uuid, %s::uuid, %s::uuid, %s, %s, %s::jsonb, %s,
                    %s::jsonb, %s::jsonb, %s, %s, %s, %s::jsonb
                )
                """,
                (
                    tenant_id,
                    version_id,
                    type_id,
                    field["key"],
                    field["name"],
                    json.dumps(field["type_ref"]),
                    field.get("field_number"),
                    json.dumps(field["default_value"])
                    if field.get("default_value") is not None
                    else None,
                    json.dumps(field["constraints"])
                    if field.get("constraints") is not None
                    else None,
                    field.get("description"),
                    bool(field.get("deprecated")),
                    field.get("ordinal") or 0,
                    json.dumps(field.get("extras") or {}),
                ),
            )

    return artifact_id


def persist_canonical_api(
    db: _DbLike,
    *,
    tenant_id: str,
    creator_id: str,
    version_id: str,
    model: CanonicalApi,
) -> str:
    """Soft-delete any live artifact for ``version_id`` and insert ``model``.

    Args:
        db: Database handle exposing :meth:`connect`.
        tenant_id: Owning tenant UUID.
        creator_id: User who produced the artifact (required by ``api_artifacts``).
        version_id: Target ``versions.id`` UUID (not the display version string).
        model: Normalized canonical API to persist.

    Returns:
        The new ``api_artifacts.id`` as a string.
    """
    tree = dump_canonical_tree(model)
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            _soft_delete_live_artifact(cursor, tenant_id=tenant_id, version_id=version_id)
            artifact_id = _insert_tree(
                cursor,
                tenant_id=tenant_id,
                creator_id=creator_id,
                version_id=version_id,
                tree=tree,
            )
        conn.commit()
        return artifact_id
    except Exception:
        conn.rollback()
        raise


def _as_dict(row: Any) -> Dict[str, Any]:
    if isinstance(row, dict):
        return dict(row)
    return dict(row)


def _fetch_all(cursor: Any, query: str, params: Sequence[Any]) -> List[Dict[str, Any]]:
    cursor.execute(query, params)
    rows = cursor.fetchall() or []
    return [_as_dict(r) for r in rows]


def load_canonical_api(
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
            }
        conn.commit()
        return load_canonical_tree(tree)
    except Exception:
        conn.rollback()
        raise
