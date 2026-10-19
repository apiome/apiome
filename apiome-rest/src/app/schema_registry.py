"""Schema subject model — pure rules (CDG-4.2, #5974).

A schema registry speaks in **subjects**, integer **schema ids** and **versions**. Apiome keeps the
schema bytes where they already live — a catalog item revision written by the import pipeline — and
V294 adds the registry bookkeeping around it (``schema_subjects``, ``schema_subject_versions``,
``schema_registry_schemas``, ``schema_registry_config``). This module holds the rules that need no
database: the allowed values, subject-name validation, the naming-strategy vocabulary shared with
the Avro emitter (MFX-19.3), which import source reads which schema type, and the fingerprint.

Fingerprint. A schema's identity is the import pipeline's **canonical-model fingerprint**
(:meth:`app.import_source.ImportSource.fingerprint`): the same schema, however its keys are
ordered, yields the same fingerprint, so registering it twice returns the same id. Avro's Parsing
Canonical Form replaces it for Avro once MFI-12.1 (#3782) ships, as a *new* fingerprint kind
(``avro-pcf``) — never silently substituted, so lookups always compare like with like.

:mod:`app.schema_registry_store` reads and writes the rows; :mod:`app.schema_registry_service`
runs registration and attach; :mod:`app.schema_registry_routes` serves them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from .avro_emitter import AvroSubjectNamingStrategy

#: Schema types a subject version can hold (Confluent's ``schemaType`` vocabulary).
SCHEMA_TYPE_AVRO = "AVRO"
SCHEMA_TYPE_JSON = "JSON"
SCHEMA_TYPE_PROTOBUF = "PROTOBUF"
SCHEMA_TYPES: Tuple[str, ...] = (SCHEMA_TYPE_AVRO, SCHEMA_TYPE_JSON, SCHEMA_TYPE_PROTOBUF)

#: Compatibility levels (stored only; verdicts are CDG-4.3). ``None`` on a subject = tenant default.
COMPATIBILITY_LEVELS: Tuple[str, ...] = (
    "NONE",
    "BACKWARD",
    "BACKWARD_TRANSITIVE",
    "FORWARD",
    "FORWARD_TRANSITIVE",
    "FULL",
    "FULL_TRANSITIVE",
)

#: Registry modes. ``READONLY`` refuses new versions.
MODE_READWRITE = "READWRITE"
MODE_READONLY = "READONLY"
MODES: Tuple[str, ...] = (MODE_READWRITE, MODE_READONLY)

#: Subject naming strategies, as stored (V294 CHECK).
STRATEGY_TOPIC = "topic"
STRATEGY_RECORD = "record"
STRATEGY_TOPIC_RECORD = "topic_record"
STRATEGIES: Tuple[str, ...] = (STRATEGY_TOPIC, STRATEGY_RECORD, STRATEGY_TOPIC_RECORD)

#: The fingerprint kind every row carries today (V294 ``fingerprint_kind``).
FINGERPRINT_KIND = "canonical-model"

#: The compatibility level that needs no verdict.
LEVEL_NONE = "NONE"

#: Schema types whose XPC-4.x compatibility rules have shipped (Avro #3785, JSON Schema #5746,
#: Protobuf #5747). None yet: until a type is listed here, a new version under any level but
#: ``NONE`` is refused with ``compatibility-rules-unavailable`` instead of being accepted unchecked.
COMPATIBILITY_RULES_SHIPPED: frozenset = frozenset()

#: Longest subject name (V294 ``VARCHAR(255)``).
SUBJECT_NAME_MAX = 255

#: Stored strategy ↔ the Avro emitter's MFX-19.3 strategy enum.
_STRATEGY_TO_AVRO = {
    STRATEGY_TOPIC: AvroSubjectNamingStrategy.TOPIC_NAME,
    STRATEGY_RECORD: AvroSubjectNamingStrategy.RECORD_NAME,
    STRATEGY_TOPIC_RECORD: AvroSubjectNamingStrategy.TOPIC_RECORD_NAME,
}

#: Schema type → (import source key, file extension the adapter recognizes).
_INTAKE = {
    SCHEMA_TYPE_AVRO: ("avro", ".avsc"),
    SCHEMA_TYPE_JSON: ("json-schema", ".json"),
    SCHEMA_TYPE_PROTOBUF: ("grpc", ".proto"),
}


class SchemaRegistryError(Exception):
    """A registry request that cannot be served, with its HTTP status and machine code.

    Attributes:
        code: Machine-readable reason (``subject-not-found``, ``schema-invalid``, …).
        status_code: The HTTP status the route answers with.
    """

    def __init__(self, code: str, message: str, *, status_code: int = 422) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(message)

    def as_detail(self) -> Dict[str, str]:
        """Return the ``{"code", "message"}`` body an HTTP error carries."""
        return {"code": self.code, "message": str(self)}


@dataclass(frozen=True)
class Fingerprinted:
    """A schema parsed through its import source.

    Attributes:
        schema_type: ``AVRO`` / ``JSON`` / ``PROTOBUF``.
        fingerprint: The canonical-model fingerprint (``sha256:<hex>``).
        adapter_key: The import source that parsed it (``avro`` / ``json-schema`` / ``grpc``).
        filename: The filename the import is labelled with (``<subject><ext>``).
    """

    schema_type: str
    fingerprint: str
    adapter_key: str
    filename: str


def validate_subject_name(name: Any) -> str:
    """Return a subject name ready to store, or raise.

    Args:
        name: The subject name from the path or body.

    Returns:
        The name, unchanged (subject names are case-sensitive and kept verbatim).

    Raises:
        SchemaRegistryError: ``subject-invalid`` (422) for an empty, over-long or control-character name.
    """
    if not isinstance(name, str) or not name.strip():
        raise SchemaRegistryError("subject-invalid", "A subject name is required.")
    if len(name) > SUBJECT_NAME_MAX:
        raise SchemaRegistryError(
            "subject-invalid", f"A subject name is at most {SUBJECT_NAME_MAX} characters."
        )
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in name):
        raise SchemaRegistryError("subject-invalid", "A subject name cannot contain control characters.")
    return name


def normalize_choice(value: Optional[str], allowed: Tuple[str, ...], *, field: str) -> Optional[str]:
    """Validate an optional enumerated value (schema type, level, mode, strategy).

    Args:
        value: The value as sent, or ``None``.
        allowed: The accepted values.
        field: The field name, for the error message.

    Returns:
        The value (``None`` stays ``None``).

    Raises:
        SchemaRegistryError: ``<field>-invalid`` (422) when the value is not one of ``allowed``.
    """
    if value is None:
        return None
    if value not in allowed:
        raise SchemaRegistryError(
            f"{field}-invalid", f"{field} must be one of {', '.join(allowed)}; got {value!r}."
        )
    return value


def strategy_to_avro(strategy: Optional[str]) -> Optional[AvroSubjectNamingStrategy]:
    """Map a stored strategy to the Avro emitter's MFX-19.3 enum (``None`` stays ``None``)."""
    return _STRATEGY_TO_AVRO.get(strategy) if strategy else None


def strategy_from_avro(strategy: AvroSubjectNamingStrategy) -> str:
    """Map the Avro emitter's MFX-19.3 enum to the stored strategy value."""
    for stored, avro in _STRATEGY_TO_AVRO.items():
        if avro is strategy:
            return stored
    raise ValueError(f"unknown Avro subject naming strategy {strategy!r}")


def schema_type_for_format(source_format: Optional[str]) -> Optional[str]:
    """Return the schema type of a catalog revision's ``source_format``, or ``None`` if it has none.

    Args:
        source_format: ``versions.source_format`` (the canonical ``model.format``), e.g. ``avro``,
            ``json-schema``, ``protobuf``.

    Returns:
        ``AVRO`` / ``JSON`` / ``PROTOBUF``, or ``None`` for a format a subject cannot hold.
    """
    fmt = (source_format or "").strip().lower()
    if fmt.startswith("avro") or fmt == "avsc":
        return SCHEMA_TYPE_AVRO
    if fmt.startswith("json-schema") or fmt == "jsonschema":
        return SCHEMA_TYPE_JSON
    if fmt.startswith("protobuf") or fmt == "proto":
        return SCHEMA_TYPE_PROTOBUF
    return None


def intake_for(schema_type: str, subject: str) -> Tuple[str, str]:
    """Return the import source key and the filename an upload of ``schema_type`` is labelled with.

    Args:
        schema_type: ``AVRO`` / ``JSON`` / ``PROTOBUF``.
        subject: The subject name (the filename stem, made filesystem-safe).

    Returns:
        ``(adapter_key, filename)``.
    """
    key, ext = _INTAKE[schema_type]
    stem = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in subject).strip("-.") or "schema"
    return key, f"{stem[:100]}{ext}"


def fingerprint_schema(schema_type: str, schema: str, subject: str) -> Fingerprinted:
    """Parse ``schema`` through its import source and fingerprint the canonical model.

    The same intake a catalog import runs (``avro_import_source`` / ``jsonschema_import_source`` /
    the Protobuf ``grpc`` source), so a schema the registry accepts is one the catalog can hold.

    Args:
        schema_type: ``AVRO`` / ``JSON`` / ``PROTOBUF``.
        schema: The schema text.
        subject: The subject name (labels the parse for error messages).

    Returns:
        The :class:`Fingerprinted` schema.

    Raises:
        SchemaRegistryError: ``schema-invalid`` (422) when the import source rejects the text, or
            ``schema-type-unavailable`` (422) when its intake cannot run in this deployment.
    """
    from .import_source import ImportSourceError, get_import_source, load_builtin_import_sources

    if not isinstance(schema, str) or not schema.strip():
        raise SchemaRegistryError("schema-invalid", "The schema is empty.")
    load_builtin_import_sources()
    key, filename = intake_for(schema_type, subject)
    adapter = get_import_source(key)
    if adapter is None:
        raise SchemaRegistryError(
            "schema-type-unavailable", f"{schema_type} schemas cannot be read in this deployment."
        )
    try:
        model = adapter.normalize(adapter.parse(schema, source_label=filename))
    except ImportSourceError as exc:
        raise SchemaRegistryError("schema-invalid", f"Invalid {schema_type} schema: {exc}") from exc
    return Fingerprinted(
        schema_type=schema_type,
        fingerprint=adapter.fingerprint(model),
        adapter_key=adapter.key,
        filename=filename,
    )


def effective_mode(subject_mode: Optional[str], tenant_mode: Optional[str]) -> str:
    """Return the mode a write must respect: ``READONLY`` when either the tenant or subject says so.

    Args:
        subject_mode: The subject's mode, or ``None`` for a subject that does not exist yet.
        tenant_mode: The tenant default mode.

    Returns:
        ``READONLY`` or ``READWRITE``.
    """
    if MODE_READONLY in (subject_mode, tenant_mode):
        return MODE_READONLY
    return MODE_READWRITE


def compatibility_rules_available(schema_type: str) -> bool:
    """Return whether XPC-4.x compatibility rules exist for ``schema_type`` (CDG-4.3)."""
    return schema_type in COMPATIBILITY_RULES_SHIPPED


def require_verdict_possible(level: str, schema_type: str, has_live_versions: bool) -> None:
    """Refuse a check that would need a compatibility verdict Apiome cannot compute yet.

    No silent success (CDG-4.3): a level other than ``NONE`` against a subject that already has
    versions needs a verdict, and until XPC-4.x ships rules for the schema type there is none to
    give. A first version needs no verdict — there is nothing to compare it with.

    Args:
        level: The subject's effective compatibility level.
        schema_type: ``AVRO`` / ``JSON`` / ``PROTOBUF``.
        has_live_versions: Whether the subject already holds a live version.

    Raises:
        SchemaRegistryError: ``compatibility-rules-unavailable`` (422).
    """
    if level == LEVEL_NONE or not has_live_versions:
        return
    if not compatibility_rules_available(schema_type):
        raise SchemaRegistryError(
            "compatibility-rules-unavailable",
            f"Compatibility level {level} needs {schema_type} compatibility rules, which Apiome does "
            "not have yet (XPC-4.x). Set the subject's compatibility level to NONE to register "
            "without a check.",
        )
    # Unreachable until a type is added to COMPATIBILITY_RULES_SHIPPED with its XPC-4.x engine.
    raise SchemaRegistryError(
        "compatibility-rules-unavailable", f"No {schema_type} compatibility engine is wired in."
    )


def registrable_schema_types() -> Tuple[str, ...]:
    """Return the schema types this deployment can read (Protobuf needs the bundled ``buf``)."""
    from .proto_descriptor import BUF_TOOL_KEY
    from .toolchain_runner import is_tool_available

    return tuple(t for t in SCHEMA_TYPES if t != SCHEMA_TYPE_PROTOBUF or is_tool_available(BUF_TOOL_KEY))
