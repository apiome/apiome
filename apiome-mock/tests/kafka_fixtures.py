"""AsyncAPI-over-Kafka fixtures for the broker producer tests — XPC-2.2 (#5736)."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from app.asyncapi_normalizer import AsyncApiNormalizer

from apiome_mock.canonical_compiler import CompiledCanonicalSpec, compile_canonical_spec
from apiome_mock.canonical_loader import LoadedCanonicalSpec

#: The Avro schema of ``user/updated``'s payload.
USER_UPDATED_AVRO = {
    "type": "record",
    "name": "UserUpdated",
    "namespace": "com.example.users",
    "fields": [
        {"name": "userId", "type": "string"},
        {"name": "plan", "type": {"type": "enum", "name": "Plan", "symbols": ["FREE", "PRO"]}},
        {"name": "seats", "type": "int"},
        {"name": "nickname", "type": ["null", "string"]},
    ],
}

_DOC: dict[str, Any] = {
    "asyncapi": "3.0.0",
    "info": {"title": "User Events", "version": "1.0.0"},
    "servers": {"prod": {"host": "broker.example.com:9092", "protocol": "kafka"}},
    "channels": {
        "userSignedUp": {
            "address": "user/signedup",
            "bindings": {"kafka": {"partitions": 3}},
            "messages": {
                "UserSignedUp": {
                    "name": "UserSignedUp",
                    "contentType": "application/json",
                    "payload": {
                        "type": "object",
                        "required": ["userId", "email"],
                        "properties": {
                            "userId": {"type": "string"},
                            "email": {"type": "string", "format": "email"},
                        },
                        "additionalProperties": False,
                    },
                    "headers": {
                        "type": "object",
                        "properties": {"traceId": {"type": "string"}},
                    },
                    "bindings": {"kafka": {"key": {"type": "string", "enum": ["user-42"]}}},
                    "examples": [
                        {
                            "name": "ada",
                            "headers": {"traceId": "trace-1"},
                            "payload": {"userId": "u-1", "email": "ada@example.com"},
                        }
                    ],
                }
            },
        },
        "userUpdated": {
            "address": "user/{region}/updated",
            "parameters": {"region": {"enum": ["eu", "us"]}},
            "bindings": {"kafka": {}},
            "messages": {
                "UserUpdated": {
                    "name": "UserUpdated",
                    "schemaFormat": "application/vnd.apache.avro;version=1.9.0",
                    "payload": USER_UPDATED_AVRO,
                }
            },
        },
        "orderPlaced": {
            "address": "orders/{orderId}/placed",
            "parameters": {"orderId": {"description": "No enum, examples or default."}},
            "bindings": {"kafka": {}},
            "messages": {
                "OrderPlaced": {"name": "OrderPlaced", "payload": {"type": "object"}},
            },
        },
        "auditLog": {
            "address": "audit log!",
            "bindings": {"kafka": {}},
            "messages": {"Audit": {"name": "Audit", "payload": {"type": "object"}}},
        },
    },
    "operations": {
        "onUserSignedUp": {
            "action": "receive",
            "channel": {"$ref": "#/channels/userSignedUp"},
            "messages": [{"$ref": "#/channels/userSignedUp/messages/UserSignedUp"}],
        },
        "onUserUpdated": {
            "action": "receive",
            "channel": {"$ref": "#/channels/userUpdated"},
            "messages": [{"$ref": "#/channels/userUpdated/messages/UserUpdated"}],
        },
        "onOrderPlaced": {
            "action": "receive",
            "channel": {"$ref": "#/channels/orderPlaced"},
            "messages": [{"$ref": "#/channels/orderPlaced/messages/OrderPlaced"}],
        },
        "onAudit": {
            "action": "receive",
            "channel": {"$ref": "#/channels/auditLog"},
            "messages": [{"$ref": "#/channels/auditLog/messages/Audit"}],
        },
    },
}


def kafka_doc() -> dict[str, Any]:
    """A fresh copy of the Kafka AsyncAPI document."""
    return copy.deepcopy(_DOC)


def compiled_kafka_spec(
    doc: dict[str, Any] | None = None,
    *,
    mock_settings: Any = None,
    revision_id: UUID | None = None,
) -> CompiledCanonicalSpec:
    """Normalize and compile the document as tenant ``demo`` / project ``events`` / ``1.0.0``."""
    api = AsyncApiNormalizer().normalize(doc or kafka_doc())
    loaded = LoadedCanonicalSpec(
        revision_id=revision_id or uuid4(),
        tenant_slug="demo",
        project_slug="events",
        version_label="1.0.0",
        updated_at=datetime.now(timezone.utc),
        api=api,
        source_format="asyncapi-3",
        mock_settings=mock_settings,
    )
    return compile_canonical_spec(loaded)


def route(compiled: CompiledCanonicalSpec, address_prefix: str) -> Any:
    """The compiled channel whose address starts with ``address_prefix``."""
    return next(r for r in compiled.event_channels if r.address.startswith(address_prefix))
