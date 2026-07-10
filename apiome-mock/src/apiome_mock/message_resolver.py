"""Resolve canonical event/RPC message payloads for the mock data plane (SIM-4.4)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.canonical_model import CanonicalApi, Message, Type, TypeKind, TypeRef

from apiome_mock.schema_synthesizer import generate_example, validate_value


@dataclass(frozen=True)
class ResolvedMessage:
    """A synthesized mock message payload."""

    body: Any
    media_type: str
    validation_error: str | None = None


def _scalar_json_type(name: str | None) -> dict[str, Any]:
    normalized = (name or "string").lower()
    if normalized in {"int32", "int64", "integer", "sint32", "sint64", "sfixed32", "sfixed64"}:
        return {"type": "integer"}
    if normalized in {"float", "double", "number"}:
        return {"type": "number"}
    if normalized in {"bool", "boolean"}:
        return {"type": "boolean"}
    if normalized == "bytes":
        return {"type": "string", "format": "byte"}
    return {"type": "string"}


def _type_ref_schema(api: CanonicalApi, type_ref: TypeRef) -> dict[str, Any]:
    if type_ref.is_list():
        assert type_ref.item is not None
        return {
            "type": "array",
            "items": _type_ref_schema(api, type_ref.item),
            "minItems": 1,
        }

    if type_ref.name:
        named = api.type_by_key(type_ref.name)
        if named is None:
            for candidate in api.types:
                if candidate.name == type_ref.name or candidate.key.endswith(f".{type_ref.name}"):
                    named = candidate
                    break
        if named is not None:
            return _canonical_type_schema(api, named)

        schema = _scalar_json_type(type_ref.name)
        if not type_ref.nullable:
            schema = dict(schema)
        return schema

    return {"type": "string"}


def _canonical_type_schema(api: CanonicalApi, type_: Type) -> dict[str, Any]:
    if type_.kind is TypeKind.ENUM:
        values = [entry.name for entry in type_.enum_values]
        return {"type": "string", "enum": values or ["UNKNOWN"]}

    if type_.kind is TypeKind.RECORD:
        properties: dict[str, Any] = {}
        required: list[str] = []
        for field in type_.fields:
            properties[field.name] = _type_ref_schema(api, field.type)
            if field.default is not None:
                properties[field.name]["default"] = field.default
            if not field.type.nullable:
                required.append(field.name)
        schema: dict[str, Any] = {"type": "object", "properties": properties}
        if required:
            schema["required"] = required
        return schema

    if type_.kind is TypeKind.MAP:
        return {
            "type": "object",
            "additionalProperties": _type_ref_schema(api, type_.value_type or TypeRef(name="string")),
        }

    if type_.kind is TypeKind.SCALAR:
        return _scalar_json_type(type_.name)

    return {"type": "object"}


def message_schema(api: CanonicalApi, message: Message) -> dict[str, Any]:
    """Return a JSON Schema fragment for a canonical message payload."""
    if isinstance(message.payload_schema, dict) and message.payload_schema:
        return message.payload_schema
    if message.payload is not None:
        return _type_ref_schema(api, message.payload)
    return {"type": "object"}


def resolve_message_body(
    api: CanonicalApi,
    message: Message,
    *,
    seed: int | None = None,
    media_type: str | None = None,
) -> ResolvedMessage:
    """Synthesize a schema-valid payload for a canonical message."""
    schema = message_schema(api, message)
    effective_seed = 0 if seed is None else seed
    body = generate_example(schema, seed=effective_seed, field=message.key)
    error = validate_value(body, schema)
    chosen_media_type = media_type or (message.content_types[0] if message.content_types else "application/json")
    return ResolvedMessage(body=body, media_type=chosen_media_type, validation_error=error)


def encode_message_text(resolved: ResolvedMessage) -> str:
    """Encode a resolved message for WebSocket/SSE transport."""
    if resolved.media_type.endswith("/json") or resolved.media_type == "application/json":
        return json.dumps(resolved.body, separators=(",", ":"), ensure_ascii=False)
    return str(resolved.body)
