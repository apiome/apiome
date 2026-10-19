"""Schema registry helpers for ``apiome registry`` — CDG-4.5 (#5977).

Pure functions behind the command group: the allowed values the registry accepts, the schema type
a file's extension implies, the table rows the commands print, and the message a refusal carries —
Apiome routes answer ``detail: {code, message}``, the Confluent routes ``{error_code, message}``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

#: Schema types a subject version can hold (Confluent's ``schemaType`` vocabulary).
SCHEMA_TYPES: tuple[str, ...] = ("AVRO", "JSON", "PROTOBUF")

#: Compatibility levels a tenant or subject can be set to.
COMPATIBILITY_LEVELS: tuple[str, ...] = (
    "NONE",
    "BACKWARD",
    "BACKWARD_TRANSITIVE",
    "FORWARD",
    "FORWARD_TRANSITIVE",
    "FULL",
    "FULL_TRANSITIVE",
)

#: Registry modes; ``READONLY`` refuses new versions.
MODES: tuple[str, ...] = ("READWRITE", "READONLY")

#: Subject naming strategies, as stored.
STRATEGIES: tuple[str, ...] = ("topic", "record", "topic_record")

#: The Apiome routes' refusal code for a check Apiome cannot answer yet.
CODE_COMPATIBILITY_RULES_UNAVAILABLE = "compatibility-rules-unavailable"

#: The Confluent error code for a check Apiome cannot answer yet (no XPC-4.x rules).
ERROR_COMPATIBILITY_RULES_UNAVAILABLE = 42290

#: File extension → the schema type it implies.
_EXTENSION_TYPES = {
    ".avsc": "AVRO",
    ".avro": "AVRO",
    ".json": "JSON",
    ".proto": "PROTOBUF",
}


def normalize_choice(
    value: str | None, allowed: tuple[str, ...], *, upper: bool = True
) -> tuple[str | None, bool]:
    """Normalize an optional enumerated option and say whether it is allowed.

    Args:
        value: The option as typed (``None`` when it was not given).
        allowed: The accepted values.
        upper: Compare upper-cased (levels, modes, types); strategies are lower-case.

    Returns:
        ``(canonical value or None, valid)`` — an unset option is valid.
    """
    if value is None:
        return (None, True)
    text = value.strip().upper() if upper else value.strip().lower()
    return (text, text in allowed)


def schema_type_for(path: Path, explicit: str | None) -> str | None:
    """Return the schema type to register a file as.

    Args:
        path: The schema file.
        explicit: ``--type`` as typed, when given (wins over the extension).

    Returns:
        ``AVRO`` / ``JSON`` / ``PROTOBUF``, or ``None`` when neither ``--type`` nor the extension
        says (the caller asks for ``--type``).
    """
    if explicit:
        return explicit.strip().upper()
    return _EXTENSION_TYPES.get(path.suffix.lower())


def subject_rows(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the table rows for ``GET …/schema-registry/subjects``.

    A subject without a level of its own shows the tenant default followed by ``(default)``.

    Args:
        body: The ``{"subjects": [...]}`` response.

    Returns:
        One row per subject: ``name``, ``versions``, ``latest``, ``level``, ``mode``, ``strategy``.
    """
    rows: list[dict[str, Any]] = []
    for subject in body.get("subjects") or []:
        level = subject.get("effectiveCompatibilityLevel") or ""
        if not subject.get("compatibilityLevel"):
            level = f"{level} (default)"
        rows.append(
            {
                "name": subject.get("name", ""),
                "versions": subject.get("versionCount", 0),
                "latest": subject.get("latestVersion") or "",
                "level": level,
                "mode": subject.get("mode", ""),
                "strategy": subject.get("strategy") or "",
            }
        )
    return rows


def version_rows(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the table rows for ``GET …/subjects/{subject}/versions``.

    Args:
        body: The ``{"subject", "versions": [...]}`` response.

    Returns:
        One row per version: ``version``, ``id``, ``type``, ``revision``, ``created``.
    """
    return [
        {
            "version": version.get("version"),
            "id": version.get("id"),
            "type": version.get("schemaType", ""),
            "revision": version.get("versionRecordId", ""),
            "created": version.get("createdAt", ""),
        }
        for version in body.get("versions") or []
    ]


def refusal_message(response: httpx.Response) -> tuple[str, int | str | None]:
    """Return a failed registry call's message and code.

    Args:
        response: The failed response, from an Apiome route (``detail: {code, message}``) or a
            Confluent route (``{error_code, message}``).

    Returns:
        ``(message, code)``; ``code`` is ``None`` when the body carried none.
    """
    try:
        payload = response.json()
    except ValueError:
        return (f"HTTP {response.status_code}: {response.text.strip()}", None)
    if not isinstance(payload, dict):
        return (f"HTTP {response.status_code}", None)
    if isinstance(payload.get("error_code"), int):
        return (str(payload.get("message") or f"HTTP {response.status_code}"), payload["error_code"])
    detail = payload.get("detail")
    if isinstance(detail, dict) and isinstance(detail.get("message"), str):
        return (detail["message"], detail.get("code"))
    if isinstance(detail, str):
        return (detail, None)
    if isinstance(payload.get("message"), str):
        return (payload["message"], payload.get("code"))
    return (f"HTTP {response.status_code}", None)
