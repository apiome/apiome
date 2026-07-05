"""Apache Avro emitter: canonical model → ``.avsc`` — MFX-19.1 (#3909).

The inverse of a future Avro normalizer and an implementation of the
:class:`app.emitter.Emitter` SPI. It walks a :class:`~app.canonical_model.CanonicalApi` and
produces one **valid** Avro schema (``.avsc`` JSON) per named type:

* ``RECORD`` → ``record`` with typed, nullable, defaulted fields;
* ``ENUM`` → ``enum`` with sanitized symbols;
* ``UNION`` → an Avro union schema (primitive and/or named member refs);
* ``MAP`` → ``map`` (string keys; Avro has no named map types);
* ``SCALAR`` / ``ALIAS`` → logical primitives or ``fixed`` when extras carry Avro metadata;
* :class:`~app.canonical_model.TypeRef` list nesting → ``array``; nullability → ``["null", T]``.

Dates, timestamps, UUIDs, and decimals map to Avro **logical types**. Field and type names are
sanitized to Avro's ``[A-Za-z_][A-Za-z0-9_]*`` rule.

**Types only.** Operations, channels, and services have no Avro representation — they are omitted
here (MFX-19.2 reports that loss). Emission is pure, deterministic, and validated with
``fastavro.parse_schema``.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple, Union

from fastavro import parse_schema
from pydantic import Field

from .canonical_model import (
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Constraints,
    Type,
    TypeKind,
    TypeRef,
)
from .emitter import (
    CapabilityProfile,
    EmitOptions,
    EmitResult,
    EmittedFile,
    Emitter,
    Provenance,
    ProvenanceTracker,
)

__all__ = ["AvroEmitOptions", "AvroEmitter", "validate_avro_schema"]

# Canonical / JSON-Schema / protobuf scalar names → Avro primitive keywords.
_AVRO_PRIMITIVES = frozenset(
    {"null", "boolean", "int", "long", "float", "double", "bytes", "string"}
)

_CANONICAL_TO_AVRO: Dict[str, str] = {
    "null": "null",
    "boolean": "boolean",
    "bool": "boolean",
    "integer": "int",
    "int": "int",
    "int32": "int",
    "int64": "long",
    "long": "long",
    "number": "double",
    "float": "float",
    "double": "double",
    "string": "string",
    "bytes": "bytes",
}

# JSON-Schema ``format`` values that become Avro logical types on a primitive base.
_FORMAT_LOGICAL_TYPES: Dict[str, Tuple[str, str]] = {
    "date": ("int", "date"),
    "time": ("int", "time-millis"),
    "time-millis": ("int", "time-millis"),
    "time-micros": ("long", "time-micros"),
    "date-time": ("long", "timestamp-millis"),
    "datetime": ("long", "timestamp-millis"),
    "timestamp": ("long", "timestamp-millis"),
    "timestamp-millis": ("long", "timestamp-millis"),
    "timestamp-micros": ("long", "timestamp-micros"),
    "uuid": ("string", "uuid"),
}

_NON_IDENT_RE = re.compile(r"[^A-Za-z0-9_]")


class AvroEmitOptions(EmitOptions):
    """Per-target options for :class:`AvroEmitter` (MFX-1.4)."""

    namespace: Optional[str] = Field(
        default=None,
        description="Override the emitted namespace. Defaults to the model's identity "
        "namespace; useful for a non-Avro source whose model carries none.",
    )


class AvroEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as one ``.avsc`` per named type with provenance.

    Self-registers under ``avro``. Targets the data-schema paradigm; operation-bearing
    APIs export **types only** — services and channels are omitted (MFX-19.2).
    """

    key = "avro"
    format = "avro"
    label = "Apache Avro"
    description = "Export data schemas as Avro .avsc (records, enums, unions, logical types)."
    icon = "database"
    paradigm = ApiParadigm.DATA_SCHEMA
    multi_file = True
    options_model = AvroEmitOptions

    OUTPUT_MEDIA_TYPE = "application/vnd.apache.avro+json"

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        """Avro is types-only: no operations/events; unions and nullability are native."""
        return CapabilityProfile(
            operations=False,
            events=False,
            unions=True,
            nullability=True,
            constraints=False,
            field_identity=False,
        )

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[AvroEmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        """Emit ``api`` as validated ``.avsc`` schemas with per-construct provenance."""
        options = (
            opts
            if isinstance(opts, AvroEmitOptions)
            else AvroEmitOptions.model_validate(opts.model_dump() if opts else {})
        )
        writer = _AvroWriter(api, options)
        files = writer.render()
        return EmitResult(
            files=files,
            media_type=self.OUTPUT_MEDIA_TYPE,
            provenance=writer.tracker.records(),
            losses=[],
        )


class _AvroWriter:
    """One-shot Avro renderer for a single :class:`CanonicalApi`."""

    def __init__(self, api: CanonicalApi, options: AvroEmitOptions) -> None:
        self._api = api
        self._options = options
        self.tracker = ProvenanceTracker()
        self._default_namespace = (
            (options.namespace or api.identity.namespace or "").strip() or None
        )
        self._types_by_key: Dict[str, Type] = {t.key: t for t in api.types}
        self._emittable = [
            t
            for t in api.types
            if t.kind
            in (TypeKind.RECORD, TypeKind.ENUM, TypeKind.UNION, TypeKind.MAP, TypeKind.SCALAR)
        ]

    def render(self) -> List[EmittedFile]:
        """Render every emittable type to a validated ``.avsc`` file entry."""
        ordered = sorted(self._emittable, key=lambda t: t.key)
        schemas_by_key: Dict[str, Any] = {}
        for type_ in ordered:
            schema = self._emit_named_type(type_)
            schemas_by_key[type_.key] = schema
            self.tracker.record(f"/schemas/{type_.key}", Provenance.SOURCE)

        named_schemas: Dict[str, Any] = {}
        for type_ in ordered:
            schema = schemas_by_key[type_.key]
            validate_avro_schema(_as_dict_schema(schema), named_schemas=named_schemas)
            if type_.kind in (TypeKind.RECORD, TypeKind.ENUM, TypeKind.SCALAR):
                qualified = _qualified_name(type_)
                if qualified:
                    named_schemas[qualified] = _as_dict_schema(schema)

        return [
            EmittedFile(
                path=_schema_path(type_),
                content=schemas_by_key[type_.key],
                media_type=AvroEmitter.OUTPUT_MEDIA_TYPE,
            )
            for type_ in ordered
        ]

    def _emit_named_type(self, type_: Type) -> Dict[str, Any]:
        """Emit one named canonical type as an Avro schema dict."""
        if type_.kind is TypeKind.RECORD:
            return self._emit_record(type_)
        if type_.kind is TypeKind.ENUM:
            return self._emit_enum(type_)
        if type_.kind is TypeKind.UNION:
            return self._emit_union_type(type_)
        if type_.kind is TypeKind.MAP:
            return self._emit_map_type(type_)
        return self._emit_scalar_type(type_)

    def _emit_record(self, type_: Type) -> Dict[str, Any]:
        """Emit a RECORD as an Avro ``record`` schema."""
        namespace = _type_namespace(type_, self._default_namespace)
        schema: Dict[str, Any] = {
            "type": "record",
            "name": _sanitize_name(type_.name),
            "fields": [self._emit_field(field, namespace=namespace) for field in type_.fields],
        }
        if namespace:
            schema["namespace"] = namespace
        if type_.description:
            schema["doc"] = type_.description
        return schema

    def _emit_field(self, field: CanonicalField, *, namespace: Optional[str]) -> Dict[str, Any]:
        """Emit one record field with type, optional default, and doc."""
        entry: Dict[str, Any] = {
            "name": _sanitize_name(field.name),
            "type": self._emit_type_ref(field.type, namespace=namespace, field=field),
        }
        if _field_has_default(field):
            entry["default"] = _field_default(field)
        if field.description:
            entry["doc"] = field.description
        return entry

    def _emit_enum(self, type_: Type) -> Dict[str, Any]:
        """Emit an ENUM as an Avro ``enum`` schema."""
        namespace = _type_namespace(type_, self._default_namespace)
        schema: Dict[str, Any] = {
            "type": "enum",
            "name": _sanitize_name(type_.name),
            "symbols": [_sanitize_symbol(ev.name) for ev in type_.enum_values],
        }
        if namespace:
            schema["namespace"] = namespace
        if type_.description:
            schema["doc"] = type_.description
        return schema

    def _emit_union_type(self, type_: Type) -> List[Any]:
        """Emit a UNION type as an Avro union (top-level array schema)."""
        namespace = _type_namespace(type_, self._default_namespace)
        return [
            self._resolve_union_member(member, namespace=namespace)
            for member in type_.union_members
        ]

    def _emit_map_type(self, type_: Type) -> Dict[str, Any]:
        """Emit a MAP type as an Avro ``map`` schema."""
        namespace = _type_namespace(type_, self._default_namespace)
        value_type = (
            self._emit_type_ref(type_.value_type, namespace=namespace)
            if type_.value_type is not None
            else "string"
        )
        schema: Dict[str, Any] = {"type": "map", "values": value_type}
        if type_.description:
            schema["doc"] = type_.description
        return schema

    def _emit_scalar_type(self, type_: Type) -> Dict[str, Any]:
        """Emit a SCALAR as a logical primitive or ``fixed`` type."""
        fixed = _fixed_size(type_)
        if fixed is not None:
            namespace = _type_namespace(type_, self._default_namespace)
            schema: Dict[str, Any] = {
                "type": "fixed",
                "name": _sanitize_name(type_.name),
                "size": fixed,
            }
            if namespace:
                schema["namespace"] = namespace
            if type_.description:
                schema["doc"] = type_.description
            return schema
        logical = _logical_from_constraints(type_.constraints) or _logical_from_extras(type_.extras)
        if logical is not None:
            base, logical_type = logical
            schema = {"type": base, "logicalType": logical_type}
            _attach_decimal_props(schema, type_.constraints, type_.extras)
            if type_.description:
                schema["doc"] = type_.description
            return schema
        return {"type": "string", "doc": type_.description} if type_.description else {"type": "string"}

    def _emit_type_ref(
        self,
        ref: TypeRef,
        *,
        namespace: Optional[str],
        field: Optional[CanonicalField] = None,
    ) -> Any:
        """Emit a use-site :class:`TypeRef` as an Avro type (primitive, array, union, or name)."""
        if ref.is_list():
            inner = ref.item
            items = (
                self._emit_type_ref(inner, namespace=namespace, field=field)
                if inner is not None
                else "string"
            )
            return {"type": "array", "items": items}

        inner = self._resolve_leaf_ref(ref, namespace=namespace, field=field)
        if ref.nullable and inner != "null":
            union: List[Any] = ["null", inner]
            return union
        return inner

    def _resolve_leaf_ref(
        self,
        ref: TypeRef,
        *,
        namespace: Optional[str],
        field: Optional[CanonicalField] = None,
    ) -> Any:
        """Resolve a non-list leaf :class:`TypeRef` to an Avro type fragment."""
        if ref.name is None:
            return "string"

        primitive = _canonical_primitive(ref.name)
        if primitive is not None:
            constraints = field.constraints if field is not None else None
            extras = field.extras if field is not None else {}
            logical = _logical_from_constraints(constraints) or _logical_from_extras(extras)
            if logical is not None:
                base, logical_type = logical
                schema: Dict[str, Any] = {"type": base, "logicalType": logical_type}
                if field is not None:
                    _attach_decimal_props(schema, constraints, extras)
                return schema
            return primitive

        target = self._types_by_key.get(ref.name)
        if target is not None:
            if target.kind is TypeKind.MAP:
                return self._emit_map_type(target)
            if target.kind is TypeKind.UNION:
                return self._emit_union_type(target)
            if target.kind is TypeKind.SCALAR:
                if _fixed_size(target) is not None:
                    return _named_type_reference(target, namespace=namespace)
                return self._emit_scalar_type(target)
            if target.kind is TypeKind.ALIAS and target.aliased is not None:
                return self._emit_type_ref(target.aliased, namespace=namespace, field=field)
            if target.kind in (TypeKind.RECORD, TypeKind.ENUM):
                return _named_type_reference(target, namespace=namespace)

        return _named_type_reference_by_key(ref.name, namespace=namespace)

    def _resolve_union_member(self, member: str, *, namespace: Optional[str]) -> Any:
        """Resolve one UNION member key or primitive name."""
        if member == "null":
            return "null"
        primitive = _canonical_primitive(member)
        if primitive is not None:
            return primitive
        target = self._types_by_key.get(member)
        if target is not None and target.kind in (TypeKind.RECORD, TypeKind.ENUM, TypeKind.SCALAR):
            return _named_type_reference(target, namespace=namespace)
        return _named_type_reference_by_key(member, namespace=namespace)


def _as_dict_schema(schema: Any) -> Dict[str, Any]:
    """Normalize a schema fragment for ``fastavro.parse_schema`` (unions are arrays)."""
    if isinstance(schema, list):
        return schema  # type: ignore[return-value]
    if isinstance(schema, dict):
        return schema
    raise ValueError(f"Unsupported Avro schema fragment: {schema!r}")


def validate_avro_schema(
    schema: Any,
    *,
    named_schemas: Optional[Dict[str, Any]] = None,
) -> Any:
    """Parse and validate an Avro schema dict with ``fastavro``.

    Args:
        schema: Avro schema as a JSON-compatible dict.
        named_schemas: Optional registry of already-parsed named schemas for references.

    Returns:
        The parsed schema dict from ``fastavro``.

    Raises:
        ValueError: When ``fastavro`` rejects the schema.
    """
    registry = dict(named_schemas or {})
    try:
        return parse_schema(schema, named_schemas=registry)  # type: ignore[return-value]
    except Exception as exc:  # fastavro raises several exception types
        raise ValueError(f"Invalid Avro schema: {exc}") from exc


def _schema_path(type_: Type) -> str:
    """Return a deterministic ``.avsc`` path for a named type."""
    simple = _sanitize_name(type_.name) or "schema"
    namespace = _type_namespace(type_, None)
    if namespace:
        return f"{namespace.replace('.', '/')}/{simple}.avsc"
    return f"{simple}.avsc"


def _qualified_name(type_: Type) -> str:
    """Return the Avro-qualified name ``namespace.name`` when a namespace is set."""
    namespace = _type_namespace(type_, None)
    name = _sanitize_name(type_.name)
    return f"{namespace}.{name}" if namespace else name


def _type_namespace(type_: Type, default: Optional[str]) -> Optional[str]:
    """Return the namespace for a type (type-level overrides the emit default)."""
    explicit = (type_.namespace or "").strip()
    if explicit:
        return explicit
    if default:
        return default
    if "." in type_.key:
        return type_.key.rsplit(".", 1)[0]
    return None


def _named_type_reference(type_: Type, *, namespace: Optional[str]) -> str:
    """Return an Avro name reference to a named type, unqualified when namespaces match."""
    simple = _sanitize_name(type_.name)
    type_ns = _type_namespace(type_, namespace)
    if namespace and type_ns == namespace:
        return simple
    if type_ns:
        return f"{type_ns}.{simple}"
    return simple


def _named_type_reference_by_key(key: str, *, namespace: Optional[str]) -> str:
    """Return an Avro name reference from a package-qualified type key."""
    if "." not in key:
        return _sanitize_name(key)
    ref_namespace, simple = key.rsplit(".", 1)
    simple = _sanitize_name(simple)
    if namespace and ref_namespace == namespace:
        return simple
    return f"{ref_namespace}.{simple}"


def _canonical_primitive(name: str) -> Optional[str]:
    """Map a canonical primitive name to an Avro primitive, or ``None``."""
    mapped = _CANONICAL_TO_AVRO.get(name)
    if mapped in _AVRO_PRIMITIVES:
        return mapped
    return None


def _logical_from_constraints(constraints: Optional[Constraints]) -> Optional[Tuple[str, str]]:
    """Derive an Avro logical type from JSON-Schema-style ``format``."""
    if constraints is None or not constraints.format:
        return None
    fmt = constraints.format.strip().lower()
    if fmt == "decimal":
        return "bytes", "decimal"
    return _FORMAT_LOGICAL_TYPES.get(fmt)


def _logical_from_extras(extras: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    """Derive an Avro logical type from format-specific ``extras``."""
    logical = extras.get("logicalType") or extras.get("avro_logical_type")
    if not isinstance(logical, str) or not logical:
        return None
    base = extras.get("avro_type") or extras.get("type")
    if isinstance(base, str) and base in _AVRO_PRIMITIVES:
        return base, logical
    if logical in {"date", "time-millis"}:
        return "int", logical
    if logical in {"time-micros", "timestamp-millis", "timestamp-micros", "local-timestamp-millis"}:
        return "long", logical
    if logical == "uuid":
        return "string", logical
    if logical == "decimal":
        return "bytes", logical
    return "string", logical


def _attach_decimal_props(
    schema: Dict[str, Any],
    constraints: Optional[Constraints],
    extras: Dict[str, Any],
) -> None:
    """Attach ``precision`` and ``scale`` for Avro ``decimal`` logical types."""
    if schema.get("logicalType") != "decimal":
        return
    precision = extras.get("precision") or extras.get("avro_precision")
    scale = extras.get("scale") or extras.get("avro_scale")
    if constraints is not None and constraints.extras:
        precision = precision or constraints.extras.get("precision")
        scale = scale or constraints.extras.get("scale")
    if isinstance(precision, int):
        schema["precision"] = precision
    if isinstance(scale, int):
        schema["scale"] = scale


def _fixed_size(type_: Type) -> Optional[int]:
    """Return a ``fixed`` byte size from type extras, or ``None``."""
    avro_type = type_.extras.get("avro_type") or type_.extras.get("type")
    if avro_type != "fixed":
        return None
    size = type_.extras.get("avro_size") or type_.extras.get("size")
    return int(size) if isinstance(size, int) and size > 0 else None


def _field_has_default(field: CanonicalField) -> bool:
    """Return ``True`` when the source declared a default (including explicit null)."""
    if field.extras.get("has_default"):
        return True
    return field.default is not None


def _field_default(field: CanonicalField) -> Any:
    """Return the Avro field default value."""
    if field.default is not None:
        return field.default
    if field.extras.get("has_default"):
        return None
    return None


def _sanitize_name(name: str) -> str:
    """Coerce ``name`` to a legal Avro identifier (``[A-Za-z_][A-Za-z0-9_]*``)."""
    if not name:
        return "_"
    sanitized = _NON_IDENT_RE.sub("_", name)
    if sanitized[0].isdigit():
        sanitized = f"_{sanitized}"
    return sanitized


def _sanitize_symbol(name: str) -> str:
    """Coerce an enum symbol to a legal Avro enum symbol."""
    return _sanitize_name(name)
