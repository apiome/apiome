"""Promote AsyncAPI message schemas into designer ``classes`` rows (#2772).

REPO-3.3 maps message payloads/headers onto ``Class`` identities. The MFI tables
store those UUIDs on ``api_messages.extras`` as ``payload_class_id`` /
``headers_class_id`` after :func:`promote_asyncapi_message_classes` runs (before
the relational canonical persist).
"""

from __future__ import annotations

import re
from typing import Any, Dict, Set

from .canonical_model import CanonicalApi, CanonicalField, Message

__all__ = ["promote_asyncapi_message_classes"]

_SAFE_NAME = re.compile(r"[^A-Za-z0-9_]+")


def _safe_class_name(raw: str) -> str:
    """Return a Class-safe identifier derived from ``raw``."""
    cleaned = _SAFE_NAME.sub("_", (raw or "").strip())
    cleaned = cleaned.strip("_") or "Message"
    if cleaned[0].isdigit():
        cleaned = f"Class_{cleaned}"
    return cleaned[:255]


def _unique_name(base: str, used: Set[str]) -> str:
    """Allocate ``base``, ``base_2``, … until unused within this import."""
    name = base
    suffix = 2
    while name in used:
        name = f"{base}_{suffix}"
        suffix += 1
    used.add(name)
    return name


def _headers_schema(headers: list[CanonicalField]) -> Dict[str, Any]:
    """Rebuild a JSON-Schema object from coerced header fields."""
    properties: Dict[str, Any] = {}
    required: list[str] = []
    for field in headers:
        prop: Dict[str, Any] = {}
        if field.type.name:
            prop["type"] = field.type.name
        if field.description:
            prop["description"] = field.description
        if field.default is not None:
            prop["default"] = field.default
        if not field.type.nullable:
            required.append(field.name)
        properties[field.name] = prop or {"type": "string"}
    schema: Dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def promote_asyncapi_message_classes(
    db: Any,
    version_id: str,
    model: CanonicalApi,
) -> CanonicalApi:
    """Create designer Classes for each message payload/headers schema on ``model``.

    Mutates each :class:`Message`'s ``extras`` in place with ``payload_class_id``
    and/or ``headers_class_id`` (UUID strings). Idempotent within a single call
    via an in-memory name set; re-imports create a fresh version's classes.

    Args:
        db: Database handle with :meth:`create_class`.
        version_id: Target ``versions.id`` UUID.
        model: AsyncAPI-normalized canonical model.

    Returns:
        The same ``model`` instance (mutated).
    """
    used: Set[str] = set()
    for operation in model.operations():
        for message in operation.messages:
            _promote_message(db, version_id, message, used)
    return model


def _promote_message(
    db: Any, version_id: str, message: Message, used: Set[str]
) -> None:
    extras = dict(message.extras or {})
    if isinstance(message.payload_schema, dict):
        base = _safe_class_name(message.name or "Payload")
        class_name = _unique_name(base, used)
        row = db.create_class(
            version_id,
            class_name,
            message.payload_schema,
            description=message.description,
        )
        extras["payload_class_id"] = str(row["id"])

    if message.headers:
        base = _safe_class_name(f"{message.name or 'Message'}Headers")
        class_name = _unique_name(base, used)
        row = db.create_class(
            version_id,
            class_name,
            _headers_schema(message.headers),
            description=message.description,
        )
        extras["headers_class_id"] = str(row["id"])

    message.extras = extras
