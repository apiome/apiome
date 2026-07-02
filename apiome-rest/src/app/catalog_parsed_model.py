"""Project a catalog item's canonical model into a presentation-agnostic parsed view — MFI-25.2 (#4087).

The catalog *item detail* surface (MFI-25.1/25.3) renders the **parsed entities** of an imported
source — GraphQL operations & types, gRPC services & messages, AsyncAPI channels/operations/messages
— with per-field name/type/description. The detail API previously exposed only the aggregate
``summary`` counts (:mod:`app.catalog_detail`), so the UI had no data to render those blocks.

This module closes that gap by deriving a **normalized, paradigm-tagged entity list** from the
canonical model (MFI-EPIC-2). The output is a plain, JSON-ready tree — *entity groups → entities
(name, tag, meta) → fields (name, type, description, required)* — that the ``parsed`` array of
:class:`~app.models.CatalogItemDetailSchema` carries. It is deliberately **presentation-agnostic**:
no colors, ordering hints, or markup — just the parsed structure, so the renderer (MFI-25.3) owns all
styling.

Two entry points:

* :func:`derive_parsed_model` — the pure projection ``CanonicalApi -> [group, …]``. Grouping is
  paradigm-aware (GraphQL/RPC/EVENT each read most naturally as different blocks), but every group is
  the same stable shape. An absent/empty model yields ``[]`` so the caller never has to special-case.
* :func:`derive_catalog_parsed_model` — the item-level convenience that *reconstructs* the canonical
  model from the catalog item's captured source (the same parse+normalize the convert path uses,
  MFI-22.6) and projects it, degrading to ``[]`` on any failure (no captured source, unknown format,
  unparseable text) so a detail read never errors on a missing/broken model.

Kept out of :mod:`app.catalog_detail` (which stays pure and dependency-free) because the projection
needs the canonical model types and the reconstruction needs the import-source adapters.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .canonical_model import (
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Channel,
    EnumValue,
    Operation,
    OperationKind,
    Parameter,
    StreamingMode,
    Type,
    TypeKind,
    TypeRef,
)

__all__ = [
    "derive_parsed_model",
    "derive_catalog_parsed_model",
    "reconstruct_catalog_api",
]


# Human, paradigm-neutral tag for a GraphQL/generic named type, refined by the GraphQL
# ``graphql_type`` extra when present (so an object vs. an input object is distinguishable) and
# otherwise falling back to the structural :class:`TypeKind`.
_TYPE_KIND_TAG: Dict[TypeKind, str] = {
    TypeKind.RECORD: "OBJECT",
    TypeKind.ENUM: "ENUM",
    TypeKind.UNION: "UNION",
    TypeKind.SCALAR: "SCALAR",
    TypeKind.ALIAS: "ALIAS",
    TypeKind.MAP: "MAP",
}

# Event-paradigm operation tag: the pub/sub action verb the mockup shows (send/receive).
_EVENT_OP_TAG: Dict[OperationKind, str] = {
    OperationKind.PUBLISH: "SEND",
    OperationKind.SUBSCRIBE: "RECEIVE",
}


# ---------------------------------------------------------------------------
# Rendering helpers — CanonicalField / Parameter / TypeRef → row dicts
# ---------------------------------------------------------------------------
def _render_type_ref(ref: Optional[TypeRef]) -> str:
    """Render a :class:`TypeRef` as a compact, presentation-agnostic type string.

    Lists nest with ``[...]`` (``TypeRef(item=…)``); a leaf renders its ``name``. Nullability is
    *not* baked into the string — it is surfaced separately as the row's ``required`` flag — so the
    renderer decides how (or whether) to mark optionality. An empty/nameless ref renders ``""``.
    """
    if ref is None:
        return ""
    if ref.item is not None:
        return f"[{_render_type_ref(ref.item)}]"
    return ref.name or ""


def _field_row(field: CanonicalField) -> Dict[str, Any]:
    """Project one record/message :class:`CanonicalField` into a ``{name, type, description, required}`` row.

    ``required`` mirrors the *outer* nullability of the field's type (a non-nullable field is
    required); ``field_number`` (protobuf/Thrift positional identity) is appended to the type string
    when present, matching how a descriptor reads (``string #1``).
    """
    type_str = _render_type_ref(field.type)
    if field.field_number is not None:
        type_str = f"{type_str} #{field.field_number}".strip()
    return {
        "name": field.name,
        "type": type_str,
        "description": field.description,
        "required": not field.type.nullable,
    }


def _param_row(param: Parameter) -> Dict[str, Any]:
    """Project one operation :class:`Parameter` (GraphQL argument / REST param) into a field row.

    Unlike a record field, a parameter carries its own ``required`` flag (a GraphQL argument is
    required when non-null and defaultless), so it is used directly rather than inferred.
    """
    return {
        "name": param.name,
        "type": _render_type_ref(param.type),
        "description": param.description,
        "required": param.required,
    }


def _schema_type(schema: Dict[str, Any]) -> str:
    """Render a JSON-Schema property's type compactly (``string (uuid)`` / ``[integer]`` / ``object``).

    AsyncAPI message payloads are inline JSON Schema (dereferenced), so an event message's field types
    are read here rather than from a named :class:`TypeRef`. Arrays nest with ``[...]``; a ``format``
    hint is shown in parentheses; a union ``type`` list joins with ``|``.
    """
    type_value = schema.get("type")
    if isinstance(type_value, list):
        type_value = "|".join(str(t) for t in type_value)
    if type_value == "array":
        items = schema.get("items")
        return f"[{_schema_type(items if isinstance(items, dict) else {})}]"
    base = type_value or ("object" if isinstance(schema.get("properties"), dict) else "")
    fmt = schema.get("format")
    return f"{base} ({fmt})" if fmt and base else (base or "")


def _schema_fields(schema: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Project a JSON-Schema object's ``properties`` into field rows (``required`` from its list)."""
    if not isinstance(schema, dict):
        return []
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return []
    required = set(schema.get("required") or [])
    rows: List[Dict[str, Any]] = []
    for name, prop in properties.items():
        prop = prop if isinstance(prop, dict) else {}
        rows.append(
            {
                "name": name,
                "type": _schema_type(prop),
                "description": prop.get("description"),
                "required": name in required,
            }
        )
    return rows


def _enum_value_row(value: EnumValue) -> Dict[str, Any]:
    """Project one :class:`EnumValue` into a field row (its wire value shown as the ``type``)."""
    return {
        "name": value.name,
        "type": "" if value.value is None else str(value.value),
        "description": value.description,
        "required": False,
    }


def _entity(name: str, tag: str, meta: Optional[str], fields: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Assemble one entity dict in the stable ``{name, tag, meta, fields}`` shape."""
    return {"name": name, "tag": tag, "meta": meta, "fields": fields}


def _group(title: str, subtitle: Optional[str], entities: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Assemble one group dict, or ``None`` when it has no entities (so empty groups are dropped)."""
    if not entities:
        return None
    return {"title": title, "subtitle": subtitle, "entities": entities}


# ---------------------------------------------------------------------------
# Type projection (shared across paradigms)
# ---------------------------------------------------------------------------
def _type_tag(type_: Type) -> str:
    """Tag a named type — the GraphQL ``graphql_type`` extra when present, else its structural kind."""
    graphql_type = type_.extras.get("graphql_type")
    if isinstance(graphql_type, str) and graphql_type.strip():
        return graphql_type.strip().upper()
    return _TYPE_KIND_TAG.get(type_.kind, type_.kind.value.upper())


def _type_meta(type_: Type) -> Optional[str]:
    """A short count summary for a type: ``N fields`` / ``N values`` / ``N members``, or ``None``."""
    if type_.kind is TypeKind.ENUM:
        return f"{len(type_.enum_values)} values"
    if type_.kind is TypeKind.UNION:
        return f"{len(type_.union_members)} members"
    if type_.fields:
        return f"{len(type_.fields)} fields"
    return None


def _type_fields(type_: Type) -> List[Dict[str, Any]]:
    """The field rows of a type: record fields, enum values, or union member names."""
    if type_.kind is TypeKind.ENUM:
        return [_enum_value_row(v) for v in type_.enum_values]
    if type_.kind is TypeKind.UNION:
        return [{"name": member, "type": "", "description": None, "required": False} for member in type_.union_members]
    return [_field_row(f) for f in type_.fields]


def _type_entity(type_: Type, *, tag_override: Optional[str] = None) -> Dict[str, Any]:
    """Project a named :class:`Type` into an entity (``tag_override`` forces a paradigm-specific tag)."""
    return _entity(
        name=type_.name,
        tag=tag_override or _type_tag(type_),
        meta=_type_meta(type_),
        fields=_type_fields(type_),
    )


def _types_group(
    api: CanonicalApi,
    *,
    title: str,
    subtitle: Optional[str],
    tag_override: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Build a "Types"/"Messages" group from the artifact's named types (``None`` when it has none)."""
    return _group(title, subtitle, [_type_entity(t, tag_override=tag_override) for t in api.types])


# ---------------------------------------------------------------------------
# Operation projection helpers
# ---------------------------------------------------------------------------
def _response_type(operation: Operation) -> Optional[str]:
    """Render the operation's response payload type, if it declares one (GraphQL return type)."""
    for message in operation.messages:
        if message.role.value == "response" and message.payload is not None:
            return _render_type_ref(message.payload)
    return None


def _rpc_signature(operation: Operation) -> str:
    """Render a gRPC method signature — ``(Request) → Response`` with ``stream`` on streaming sides."""
    request = next((m for m in operation.messages if m.role.value == "request"), None)
    response = next((m for m in operation.messages if m.role.value == "response"), None)
    request_name = _render_type_ref(request.payload) if request else ""
    response_name = _render_type_ref(response.payload) if response else ""
    client_stream = operation.streaming in (StreamingMode.CLIENT, StreamingMode.BIDIRECTIONAL)
    server_stream = operation.streaming in (StreamingMode.SERVER, StreamingMode.BIDIRECTIONAL)
    request_part = f"stream {request_name}" if client_stream else request_name
    response_part = f"stream {response_name}" if server_stream else response_name
    return f"({request_part}) → {response_part}"


# ---------------------------------------------------------------------------
# Paradigm-specific group builders
# ---------------------------------------------------------------------------
def _graph_groups(api: CanonicalApi) -> List[Dict[str, Any]]:
    """GraphQL: an *Operations* group (root fields, tagged QUERY/MUTATION/SUBSCRIPTION) + *Types*."""
    operations: List[Dict[str, Any]] = []
    for operation in api.operations():
        return_type = _response_type(operation)
        operations.append(
            _entity(
                name=operation.name,
                tag=operation.kind.value.upper(),
                meta=f"→ {return_type}" if return_type else None,
                fields=[_param_row(p) for p in operation.parameters],
            )
        )
    groups = [
        _group("Operations", "root fields on Query / Mutation / Subscription", operations),
        _types_group(api, title="Types", subtitle="object, input & enum types"),
    ]
    return [g for g in groups if g is not None]


def _rpc_groups(api: CanonicalApi) -> List[Dict[str, Any]]:
    """gRPC: a *Services & methods* group (methods as field rows) + a *Messages* group (protobuf types)."""
    services: List[Dict[str, Any]] = []
    for service in api.services:
        services.append(
            _entity(
                name=service.name,
                tag="SERVICE",
                meta=f"{len(service.operations)} methods",
                fields=[
                    {
                        "name": op.name,
                        "type": _rpc_signature(op),
                        "description": op.description,
                        "required": False,
                    }
                    for op in service.operations
                ],
            )
        )
    groups = [
        _group("Services & methods", "RPCs parsed from the descriptor source", services),
        _types_group(api, title="Messages", subtitle="protobuf messages & enums", tag_override="MESSAGE"),
    ]
    return [g for g in groups if g is not None]


def _channel_entity(channel: Channel) -> Dict[str, Any]:
    """Project an event :class:`Channel` into an entity (address parameters become field rows)."""
    return _entity(
        name=channel.address or channel.name or channel.key,
        tag="CHANNEL",
        meta=channel.protocol,
        fields=[_field_row(p) for p in channel.parameters],
    )


def _event_message_entities(api: CanonicalApi) -> List[Dict[str, Any]]:
    """Collect the unique payload messages carried by event operations, in first-seen order.

    AsyncAPI messages are inline ``payload_schema`` on each operation's :class:`Message`\\s (not named
    ``types``), so the *Messages* block is built from the operations rather than ``api.types``. A
    message referenced by several operations is listed once (keyed by name)."""
    entities: List[Dict[str, Any]] = []
    seen: set = set()
    for operation in api.operations():
        for message in operation.messages:
            name = message.name or message.key
            if name in seen:
                continue
            seen.add(name)
            fields = _schema_fields(message.payload_schema)
            entities.append(
                _entity(
                    name=name,
                    tag="MESSAGE",
                    meta=f"{len(fields)} fields" if fields else None,
                    fields=fields,
                )
            )
    return entities


def _event_groups(api: CanonicalApi) -> List[Dict[str, Any]]:
    """AsyncAPI: *Channels*, *Operations* (SEND/RECEIVE bound to a channel) and *Messages* groups."""
    operations: List[Dict[str, Any]] = []
    for operation in api.operations():
        operations.append(
            _entity(
                name=operation.name,
                tag=_EVENT_OP_TAG.get(operation.kind, operation.kind.value.upper()),
                meta=f"channel: {operation.channel_ref}" if operation.channel_ref else None,
                fields=[_param_row(p) for p in operation.parameters],
            )
        )
    groups = [
        _group("Channels", "event addresses / topics", [_channel_entity(c) for c in api.channels]),
        _group("Operations", "send / receive actions", operations),
        _group("Messages", "payload schemas", _event_message_entities(api)),
    ]
    return [g for g in groups if g is not None]


def _generic_groups(api: CanonicalApi) -> List[Dict[str, Any]]:
    """Fallback (REST / data-schema): an *Operations* group (HTTP verb/route or kind) + *Types*.

    Used for any paradigm without a bespoke builder so the projection never returns an empty list
    for a model that clearly has content — a data-schema artifact (Avro/JSON Schema) with only
    ``types`` still yields a *Types* group.
    """
    operations: List[Dict[str, Any]] = []
    for operation in api.operations():
        tag = (operation.http_method or operation.kind.value).upper()
        return_type = _response_type(operation)
        meta = operation.http_path or (f"→ {return_type}" if return_type else None)
        operations.append(
            _entity(
                name=operation.name,
                tag=tag,
                meta=meta,
                fields=[_param_row(p) for p in operation.parameters],
            )
        )
    groups = [
        _group("Operations", "callable operations", operations),
        _types_group(api, title="Types", subtitle="named types"),
        _group("Channels", "event addresses / topics", [_channel_entity(c) for c in api.channels]),
    ]
    return [g for g in groups if g is not None]


_PARADIGM_BUILDERS = {
    ApiParadigm.GRAPH: _graph_groups,
    ApiParadigm.RPC: _rpc_groups,
    ApiParadigm.EVENT: _event_groups,
}


def derive_parsed_model(api: Optional[CanonicalApi]) -> List[Dict[str, Any]]:
    """Project a canonical model into the catalog detail ``parsed`` entity-group list.

    The output is a stable, presentation-agnostic tree — a list of *groups*, each
    ``{title, subtitle, entities}``; each entity ``{name, tag, meta, fields}``; each field
    ``{name, type, description, required}`` — grouped in the way each paradigm reads most naturally
    (GraphQL by operations/types, gRPC by services/messages, AsyncAPI by channels/operations/
    messages), with a generic operations/types/channels fallback for every other paradigm.

    Args:
        api: The reconstructed canonical model, or ``None``.

    Returns:
        The list of entity groups, or ``[]`` when ``api`` is ``None`` or carries no renderable
        entities (empty groups are dropped, so an absent/empty model degrades cleanly to ``[]``).
    """
    if api is None:
        return []
    builder = _PARADIGM_BUILDERS.get(api.paradigm, _generic_groups)
    return builder(api)


def reconstruct_catalog_api(item: Dict[str, Any]) -> Optional[CanonicalApi]:
    """Reconstruct the canonical model for a catalog item from its captured source, or ``None``.

    Reuses the same parse+normalize the convert path does (MFI-22.6): resolve the source's import
    adapter, ``parse`` the captured raw text into the format's native AST, and ``normalize`` that into
    a :class:`~app.canonical_model.CanonicalApi`. Every failure mode — no captured inline source, no
    resolvable adapter, unparseable text — is swallowed and returns ``None`` so a *read* endpoint
    never errors on a missing or broken model (unlike the convert path, which surfaces these as HTTP
    errors because a conversion cannot proceed without a model).

    Args:
        item: The catalog item row (must carry ``format_metadata`` / ``metadata`` /
            ``source_format`` for a model to be reconstructable).

    Returns:
        The reconstructed canonical model, or ``None`` when it cannot be rebuilt.
    """
    # Imported lazily: the adapter registry pulls in every import-source (Node/protoc-backed) and is
    # far heavier than the pure projection above, which callers use on already-reconstructed models.
    from .catalog_conversion import build_conversion_source

    try:
        return build_conversion_source(item).api
    except Exception:  # noqa: BLE001 — a read must never fail on a missing/broken model
        return None


def derive_catalog_parsed_model(item: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Reconstruct a catalog item's canonical model and project it into the ``parsed`` group list.

    The item-level convenience behind ``GET /v1/catalog/{tenant}/{item}``: it chains
    :func:`reconstruct_catalog_api` and :func:`derive_parsed_model`, so an item with no reconstructable
    model degrades to ``[]`` rather than raising.

    Args:
        item: The catalog item row.

    Returns:
        The parsed entity-group list, or ``[]`` when no model could be reconstructed.
    """
    return derive_parsed_model(reconstruct_catalog_api(item))
