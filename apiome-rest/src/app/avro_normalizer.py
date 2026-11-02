"""Avro → canonical model normalizer — MFI-19.2, Avro IDL added by FMT-3.5 (#5430).

Maps a parsed :class:`~app.avro_parser.AvroDocument` into a
:class:`~app.canonical_model.CanonicalApi`.

Avro has two surfaces and only one of them can describe an interface. A ``.avsc``
document — and an IDL file that declares types without a protocol — is a pure schema
bundle and normalizes to :attr:`~app.canonical_model.ApiParadigm.DATA_SCHEMA`, exactly
as it always has. An IDL **protocol that declares messages** describes callable
operations, so it normalizes to :attr:`~app.canonical_model.ApiParadigm.RPC` with one
:class:`~app.canonical_model.Service` and one
:class:`~app.canonical_model.Operation` per message.

Everything the IDL surface contributes is additive and omitted when absent.

MFI-12.2 (#3783) completes the mapping of Avro 1.12's data constructs on both surfaces:
every logical type of the specification (:mod:`app.avro_logical_types`), honoured only
when valid and also when it sits behind a nullable union; unions of named references,
primitives written as objects and maps; and the evolution metadata — enum ``default``,
``aliases`` and a field's ``order`` — which a ``.avsc`` import now keeps as well.
User-defined annotation properties remain IDL-only.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple

from .avro_fingerprint import fingerprint_types
from .avro_hygiene import check_avro_document
from .avro_logical_types import ResolvedLogicalType, resolve_logical_type
from .avro_parser import AvroDocument, AvroNamedSchema
from .canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Constraints,
    EnumValue,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Service,
    StreamingMode,
    Type,
    TypeKind,
    TypeRef,
)
from .normalizer import Keys, Normalizer, normalize_ordering

__all__ = ["AvroNormalizer"]

_FORMAT_KEY = "avro"

#: Avro schema keywords that are part of the format's own grammar. Anything else on a
#: type or field is a user-defined *property* (what an IDL ``@annotation`` compiles to),
#: preserved in canonical ``extras`` so the IDL emitter can write it back.
_AVRO_SCHEMA_KEYWORDS = frozenset(
    {
        "type",
        "name",
        "namespace",
        "doc",
        "aliases",
        "fields",
        "symbols",
        "size",
        "values",
        "items",
        "logicalType",
        "precision",
        "scale",
        "default",
        "order",
    }
)

#: Declaration keywords that name a type (``error`` is IDL's spelling of a record that
#: an RPC message may throw; it carries the same shape).
_NAMED_TYPE_KEYWORDS = frozenset({"record", "error", "enum", "fixed"})

_AVRO_TO_CANONICAL: Dict[str, str] = {
    "null": "null",
    "boolean": "bool",
    "int": "integer",
    "long": "int64",
    "float": "float",
    "double": "double",
    "bytes": "bytes",
    "string": "string",
}

#: Canonical formats whose values are written as text everywhere else, so a primitive
#: Avro field carrying one is referenced as ``string`` (its Avro base type and logical
#: type stay in ``extras`` for the emitters).
_TEXTUAL_FORMATS = frozenset({"date", "date-time", "time", "uuid"})


def _type_key(name: str, namespace: Optional[str]) -> str:
    return Keys.type(name, namespace)


def _qualified_name(name: str, namespace: Optional[str]) -> str:
    return f"{namespace}.{name}" if namespace else name


def _resolve_named_key(name: str, namespace: Optional[str], known: frozenset[str]) -> str:
    if name in known:
        return name
    if "." in name:
        return name
    qualified = _qualified_name(name, namespace)
    if qualified in known:
        return qualified
    return _type_key(name, namespace)


def _type_ref_from_avro(
    schema: Any,
    *,
    namespace: Optional[str],
    known_types: frozenset[str],
    union_types: Dict[str, Type],
) -> TypeRef:
    if isinstance(schema, list):
        branches = list(schema)
        nullable = "null" in branches
        non_null = [branch for branch in branches if branch != "null"]
        if len(non_null) == 1:
            inner = _type_ref_from_avro(
                non_null[0],
                namespace=namespace,
                known_types=known_types,
                union_types=union_types,
            )
            return TypeRef(
                name=inner.name,
                item=inner.item,
                nullable=nullable if nullable else False,
            )
        members: List[str] = []
        for branch in branches:
            if branch == "null":
                members.append("null")
                continue
            # Every branch resolves the way a field type does (MFI-12.2): a primitive, a
            # primitive written as an object (``{"type": "long", "logicalType": ...}``),
            # a named type declared inline *or referenced by name*, or a map.
            branch_ref = _type_ref_from_avro(
                branch,
                namespace=namespace,
                known_types=known_types,
                union_types=union_types,
            )
            members.append(branch_ref.name if branch_ref.name is not None else "string")
        # The canonical union member list holds type *keys*, so an anonymous array branch
        # (``array<bytes>``) has no key and degrades to its scalar approximation. Two
        # branches can therefore collide, and Avro forbids repeating an unnamed branch —
        # so the duplicate is collapsed rather than emitted as an invalid union.
        members = list(dict.fromkeys(members))
        union_key = _type_key("Union_" + "_".join(m.replace(".", "_") for m in members), namespace)
        if union_key not in union_types:
            union_types[union_key] = Type(
                key=union_key,
                name=union_key.rsplit(".", 1)[-1],
                kind=TypeKind.UNION,
                namespace=namespace,
                union_members=members,
                extras={"avro_kind": "union"},
            )
        return TypeRef(name=union_key, nullable=nullable if nullable else False)

    if isinstance(schema, str):
        mapped = _AVRO_TO_CANONICAL.get(schema)
        if mapped:
            return TypeRef(name=mapped, nullable=False)
        return TypeRef(name=_resolve_named_key(schema, namespace, known_types), nullable=False)

    if not isinstance(schema, dict):
        return TypeRef(name="string", nullable=False)

    schema_type = schema.get("type")

    if schema_type == "array":
        return TypeRef(
            item=_type_ref_from_avro(
                schema.get("items"),
                namespace=namespace,
                known_types=known_types,
                union_types=union_types,
            ),
            nullable=False,
        )

    if schema_type == "map":
        values = schema.get("values", "string")
        value_ref = _type_ref_from_avro(
            values,
            namespace=namespace,
            known_types=known_types,
            union_types=union_types,
        )
        # A value written as a name keeps the key it always had (``Map_long``); a value
        # written as a schema object is named after the canonical type it resolves to,
        # so the key never embeds the object's text.
        value_slug = values if isinstance(values, str) else _ref_slug(value_ref, union_types)
        map_key = _type_key(f"Map_{value_slug}".replace(".", "_"), namespace)
        if map_key not in union_types:
            union_types[map_key] = Type(
                key=map_key,
                name=map_key.rsplit(".", 1)[-1],
                kind=TypeKind.MAP,
                namespace=namespace,
                value_type=value_ref,
                extras={"avro_kind": "map"},
            )
        return TypeRef(name=map_key, nullable=False)

    if schema_type in _NAMED_TYPE_KEYWORDS:
        name = schema.get("name")
        if isinstance(name, str):
            return TypeRef(
                name=_resolve_named_key(name, schema.get("namespace") or namespace, known_types),
                nullable=False,
            )

    if schema_type in _AVRO_TO_CANONICAL:
        return TypeRef(name=_AVRO_TO_CANONICAL[schema_type], nullable=False)

    if isinstance(schema_type, str) and schema_type:
        # An annotated *reference* — ``@logicalType("duration") Digest`` compiles to
        # ``{"type": "Digest", "logicalType": "duration"}``. The reference is the type;
        # reading it as an unknown keyword would silently degrade it to a bare string.
        return TypeRef(
            name=_resolve_named_key(schema_type, namespace, known_types), nullable=False
        )

    return TypeRef(name="string", nullable=False)


def _ref_slug(ref: TypeRef, synthetic: Mapping[str, Type]) -> str:
    """Return a key-safe name for an anonymous type reference.

    Args:
        ref: The reference a map's ``values`` schema object resolved to.
        synthetic: The synthetic UNION/MAP types collected so far. They share the
            enclosing namespace, so one is named by its local name
            (``Union_null_double``); any other type keeps its full key.

    Returns:
        The slug, for example ``array_Union_null_double``.
    """
    if ref.item is not None:
        return f"array_{_ref_slug(ref.item, synthetic)}"
    if ref.name in synthetic:
        return synthetic[ref.name].name
    return ref.name or "string"


def _nullable_branch(schema: Any) -> Any:
    """Return the one non-null branch of a ``["null", X]`` union, else ``schema`` itself.

    The canonical model carries that union as a nullable reference to ``X``, so whatever
    ``X`` declares — a logical type above all — belongs to the field just as if the
    field's type were ``X``.
    """
    if isinstance(schema, list):
        non_null = [branch for branch in schema if branch != "null"]
        if len(non_null) == 1:
            return non_null[0]
    return schema


def _logical_constraints(logical: Optional[ResolvedLogicalType]) -> Optional[Constraints]:
    """Return the canonical constraints a resolved logical type contributes, if any."""
    if logical is None or logical.format is None:
        return None
    return Constraints(format=logical.format)


def _field_constraints_and_extras(field_type: Any) -> Tuple[Optional[ResolvedLogicalType], Dict[str, Any]]:
    """Read the logical type a field's type expression declares.

    Args:
        field_type: The field's Avro ``type`` — looked through when it is a nullable
            union, so ``["null", {"type": "long", "logicalType": "timestamp-millis"}]``
            is a nullable timestamp, not a bare ``long``.

    Returns:
        The resolved logical type (``None`` when there is none) and the ``extras`` that
        record it.
    """
    logical = resolve_logical_type(_nullable_branch(field_type))
    if logical is None:
        return None, {}
    return logical, logical.extras()


def _custom_properties(*schemas: Any) -> Dict[str, Any]:
    """Collect the non-grammar properties carried by one or more schema fragments.

    Avro IDL annotations (``@order`` and ``@aliases`` aside) compile to user-defined
    properties on the declaration they precede. They are meaningless to the canonical
    model but must survive it, or an IDL round-trip silently drops them.

    Args:
        *schemas: Schema fragments to read — a field dict and, when it has one, the
            dict its ``type`` expression is, since an annotation can land on either.

    Returns:
        The merged property map, empty when there is nothing custom. Later fragments
        win on a key collision.
    """
    properties: Dict[str, Any] = {}
    for schema in schemas:
        if not isinstance(schema, dict):
            continue
        for key, value in schema.items():
            if key not in _AVRO_SCHEMA_KEYWORDS:
                properties[key] = value
    return properties


def _canonical_field(
    field_schema: Dict[str, Any],
    *,
    type_key: str,
    namespace: Optional[str],
    known_types: frozenset[str],
    union_types: Dict[str, Type],
    field_number: int,
    capture_properties: bool = False,
) -> CanonicalField:
    name = str(field_schema.get("name"))
    field_type = field_schema.get("type")
    type_ref = _type_ref_from_avro(
        field_type,
        namespace=namespace,
        known_types=known_types,
        union_types=union_types,
    )
    logical, logical_extras = _field_constraints_and_extras(field_type)
    constraints = _logical_constraints(logical)
    if (
        logical is not None
        and logical.format in _TEXTUAL_FORMATS
        and logical.base in _AVRO_TO_CANONICAL
    ):
        # A primitive carrying a textual logical type is a string everywhere else. A
        # ``fixed`` uuid keeps its reference to the fixed type, which is what it is.
        type_ref = TypeRef(name="string", nullable=type_ref.nullable, item=type_ref.item)
    default = field_schema.get("default") if "default" in field_schema else None
    extras: Dict[str, Any] = dict(logical_extras)
    if "default" in field_schema:
        extras["has_default"] = True
    # Sort order and aliases are evolution-load-bearing on both surfaces (an alias is
    # how a reader matches a renamed field), so ``.avsc`` keeps them too (MFI-12.2).
    order = field_schema.get("order")
    if isinstance(order, str) and order:
        extras["avro_order"] = order
    aliases = field_schema.get("aliases")
    if isinstance(aliases, list) and aliases:
        extras["avro_aliases"] = list(aliases)
    if capture_properties:
        properties = _custom_properties(field_schema, field_type)
        if properties:
            extras["avro_properties"] = properties
    return CanonicalField(
        key=Keys.field(type_key, name),
        name=name,
        type=type_ref,
        field_number=field_number,
        default=default,
        constraints=constraints,
        description=field_schema.get("doc") if isinstance(field_schema.get("doc"), str) else None,
        extras=extras,
    )


def _canonical_type(
    named: AvroNamedSchema,
    *,
    known_types: frozenset[str],
    union_types: Dict[str, Type],
    capture_properties: bool = False,
) -> Type:
    """Map one named Avro schema to its canonical :class:`Type`.

    Args:
        named: The parsed named schema.
        known_types: Qualified names of every type the document declares, used to
            resolve unqualified references.
        union_types: Accumulator for the synthetic UNION/MAP types Avro's anonymous
            constructs need; mutated in place.
        capture_properties: Whether to preserve user-defined annotation properties
            (what an IDL ``@annotation`` compiles to) in ``extras``. Off for ``.avsc``;
            ``aliases``, ``order`` and an enum ``default`` are kept on both surfaces.

    Returns:
        The canonical type.
    """
    schema = named.schema
    type_key = _type_key(named.name, named.namespace)
    schema_type = schema.get("type")
    description = schema.get("doc") if isinstance(schema.get("doc"), str) else None
    decoration = _type_decoration(schema, include_properties=capture_properties)

    if schema_type == "enum":
        symbols = schema.get("symbols") or []
        extras: Dict[str, Any] = {"avro_kind": "enum", **decoration}
        default_symbol = schema.get("default")
        # The symbol a reader falls back to for one it does not know — what makes adding
        # a symbol forward compatible — so it is kept on both surfaces (MFI-12.2).
        if isinstance(default_symbol, str) and default_symbol:
            extras["avro_enum_default"] = default_symbol
        return Type(
            key=type_key,
            name=named.name,
            kind=TypeKind.ENUM,
            namespace=named.namespace,
            description=description,
            enum_values=[
                EnumValue(key=Keys.enum_value(type_key, symbol), name=str(symbol), value=index)
                for index, symbol in enumerate(symbols)
            ],
            extras=extras,
        )

    if schema_type == "fixed":
        # A named ``fixed`` may itself carry the logical type (``decimal``, ``uuid``,
        # ``duration``), which then holds wherever the type is referenced by name.
        logical = resolve_logical_type(schema)
        return Type(
            key=type_key,
            name=named.name,
            kind=TypeKind.SCALAR,
            namespace=named.namespace,
            description=description,
            constraints=_logical_constraints(logical),
            extras={
                "avro_kind": "fixed",
                **(logical.extras() if logical is not None else {}),
                "avro_type": "fixed",
                "avro_size": schema.get("size"),
                **decoration,
            },
        )

    fields = [
        _canonical_field(
            field,
            type_key=type_key,
            namespace=named.namespace,
            known_types=known_types,
            union_types=union_types,
            field_number=index + 1,
            capture_properties=capture_properties,
        )
        for index, field in enumerate(schema.get("fields") or [])
        if isinstance(field, dict) and field.get("name")
    ]
    # ``error`` is IDL's spelling of a record an RPC message may throw. It normalizes to a
    # RECORD like any other; the distinction is kept in extras so the IDL emitter can
    # write ``error`` back rather than downgrading every fault type to a plain record.
    kind_marker = "error" if schema_type == "error" else "record"
    return Type(
        key=type_key,
        name=named.name,
        kind=TypeKind.RECORD,
        namespace=named.namespace,
        description=description,
        fields=fields,
        extras={"avro_kind": kind_marker, **decoration},
    )


def _type_decoration(schema: Mapping[str, Any], *, include_properties: bool) -> Dict[str, Any]:
    """Return the decoration of a named type declaration.

    Args:
        schema: The named type's Avro schema dict.
        include_properties: Whether to collect user-defined properties too — on for
            IDL, where they are ``@annotations``; ``aliases`` are always collected.

    Returns:
        ``extras`` additions for the type's ``aliases`` and (when asked) user-defined
        properties; empty when it carries neither.
    """
    decoration: Dict[str, Any] = {}
    aliases = schema.get("aliases")
    if isinstance(aliases, list) and aliases:
        decoration["avro_aliases"] = list(aliases)
    if include_properties:
        properties = _custom_properties(schema)
        if properties:
            decoration["avro_properties"] = properties
    return decoration


def _message_operation(
    message: Any,
    *,
    service_key: str,
    namespace: Optional[str],
    known_types: frozenset[str],
    union_types: Dict[str, Type],
) -> Operation:
    """Map one IDL ``message`` declaration to a canonical RPC :class:`Operation`.

    Avro RPC parameters are positional and named, which the canonical model has no
    direct construct for (:class:`~app.canonical_model.Parameter` is the REST-ish
    path/query/header axis). They are therefore carried as one REQUEST
    :class:`~app.canonical_model.Message`: its ``payload`` points at the single
    parameter's type when there is exactly one — the common request-object shape —
    and its ``extras`` always record the full positional signature verbatim, so the
    IDL emitter can write the parameter list back exactly as declared.

    Args:
        message: The parsed :class:`~app.avro_idl_parser.AvroIdlMessage`.
        service_key: Key of the protocol's canonical service.
        namespace: The protocol namespace, for resolving unqualified type names.
        known_types: Qualified names of the document's declared types.
        union_types: Accumulator for synthetic UNION/MAP types; mutated in place.

    Returns:
        The canonical operation, with request/response/error messages attached.
    """
    op_key = Keys.operation_rpc(service_key, message.name)
    messages: List[Message] = []

    if message.request:
        parameters = [
            {
                "name": parameter.name,
                "type": parameter.type,
                **({"default": parameter.default} if parameter.has_default else {}),
                **({"has_default": True} if parameter.has_default else {}),
            }
            for parameter in message.request
        ]
        payload: Optional[TypeRef] = None
        if len(message.request) == 1:
            payload = _type_ref_from_avro(
                message.request[0].type,
                namespace=namespace,
                known_types=known_types,
                union_types=union_types,
            )
        else:
            for parameter in message.request:
                # Still walk every parameter so anonymous unions/maps in a multi-argument
                # signature become declared types rather than dangling references.
                _type_ref_from_avro(
                    parameter.type,
                    namespace=namespace,
                    known_types=known_types,
                    union_types=union_types,
                )
        messages.append(
            Message(
                key=Keys.request_message(op_key),
                role=MessageRole.REQUEST,
                payload=payload,
                required=True,
                extras={"avro_parameters": parameters},
            )
        )

    if message.response != "null":
        messages.append(
            Message(
                key=f"{op_key}#response",
                role=MessageRole.RESPONSE,
                payload=_type_ref_from_avro(
                    message.response,
                    namespace=namespace,
                    known_types=known_types,
                    union_types=union_types,
                ),
            )
        )

    for error_name in message.errors:
        error_key = _resolve_named_key(error_name, namespace, known_types)
        messages.append(
            Message(
                key=f"{op_key}#error.{error_name}",
                role=MessageRole.ERROR,
                name=error_name.rsplit(".", 1)[-1],
                payload=TypeRef(name=error_key),
            )
        )

    extras: Dict[str, Any] = {}
    properties = {
        key: value for key, value in dict(message.properties).items() if key != "namespace"
    }
    if properties:
        extras["avro_properties"] = properties
    return Operation(
        key=op_key,
        name=message.name,
        kind=OperationKind.ONE_WAY if message.oneway else OperationKind.REQUEST_RESPONSE,
        streaming=StreamingMode.NONE,
        description=message.doc,
        messages=messages,
        extras=extras,
    )


def _protocol_service(
    protocol: Any,
    *,
    known_types: frozenset[str],
    union_types: Dict[str, Type],
) -> Service:
    """Build the single canonical :class:`Service` an IDL protocol describes."""
    service_key = _type_key(protocol.name, protocol.namespace)
    return Service(
        key=service_key,
        name=protocol.name,
        description=protocol.doc,
        operations=[
            _message_operation(
                message,
                service_key=service_key,
                namespace=protocol.namespace,
                known_types=known_types,
                union_types=union_types,
            )
            for message in protocol.messages
        ],
    )


class AvroNormalizer(Normalizer, register=True):
    """Normalize a parsed Avro document into a :class:`CanonicalApi`.

    Registered under ``avro`` for both of Avro's surfaces: the ``.avsc`` JSON schema and
    the ``.avdl`` IDL source (FMT-3.5). The declared :attr:`paradigm` is the *default*
    one — a schema bundle — and the emitted model overrides it to
    :attr:`~app.canonical_model.ApiParadigm.RPC` for an IDL protocol that declares
    messages, because that document really does describe callable operations.
    """

    format = _FORMAT_KEY
    paradigm = ApiParadigm.DATA_SCHEMA

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Map a parsed Avro document to the canonical model.

        Args:
            source: The :class:`~app.avro_parser.AvroDocument` either Avro reader produced.
            include_raw: Whether to keep the source text on ``raw``.

        Returns:
            The canonical model: ``data_schema`` for ``.avsc`` and schema-only IDL,
            ``rpc`` for an IDL protocol with messages.

        Raises:
            ValueError: When ``source`` is not an :class:`~app.avro_parser.AvroDocument`.
        """
        if not isinstance(source, AvroDocument):
            raise ValueError("Avro source must be an AvroDocument (see app.avro_parser.parse_avro)")

        from_idl = source.syntax == "avdl"
        known_types = frozenset(
            _qualified_name(named.name, named.namespace) for named in source.types
        )
        union_types: Dict[str, Type] = {}
        types: List[Type] = [
            _canonical_type(
                named,
                known_types=known_types,
                union_types=union_types,
                capture_properties=from_idl,
            )
            for named in source.types
        ]

        protocol = source.protocol
        services: List[Service] = []
        if protocol is not None and protocol.messages:
            services.append(
                _protocol_service(
                    protocol, known_types=known_types, union_types=union_types
                )
            )
        # Synthetic union/map types are collected while walking fields *and* message
        # signatures, so they are appended only once both have been walked.
        types.extend(union_types.values())

        root = source.root
        extras: Dict[str, Any] = {"avro_root": _qualified_name(root.name, root.namespace)}
        if from_idl:
            extras["avro_syntax"] = source.syntax
        if protocol is not None:
            extras["avro_protocol"] = _qualified_name(protocol.name, protocol.namespace)
            if protocol.properties:
                extras["avro_protocol_properties"] = dict(protocol.properties)
        # MFI-12.1: Parsing Canonical Form hashes and the semantic hash of every named type,
        # keyed by full name; the document's own are its root's (``avro_root``). The semantic
        # hashes flip on a doc-only edit, so they are kept out of the version fingerprint
        # (``app.fingerprint.UNHASHED_EXTRAS``) and a doc-only edit mints no version.
        type_fingerprints = fingerprint_types(source)
        extras["avro_pcf"] = {fp.name: fp.pcf_dict() for fp in type_fingerprints}
        extras["avro_semantic_hashes"] = {fp.name: fp.semantic_sha256 for fp in type_fingerprints}
        # MFI-12.5: hygiene issues read from the schema as written (union order, defaults,
        # aliases, docs the canonical form does not keep). Omitted when clean, so a clean
        # schema's model is unchanged.
        hygiene, hygiene_total = check_avro_document(source)
        if hygiene_total:
            extras["avro_lint_issues"] = [issue.as_dict() for issue in hygiene]
            extras["avro_lint_issue_count"] = hygiene_total

        identity_name = protocol.name if protocol is not None else root.name
        identity_namespace = (
            protocol.namespace if protocol is not None else root.namespace
        )
        root_doc = root.schema.get("doc") if isinstance(root.schema.get("doc"), str) else None
        description = (
            (protocol.doc if protocol is not None else None) or source.doc or root_doc
        )

        api = CanonicalApi(
            paradigm=ApiParadigm.RPC if services else self.paradigm,
            format=self.format,
            identity=ApiIdentity(name=identity_name, namespace=identity_namespace),
            title=identity_name,
            description=description,
            services=services,
            types=types,
            raw={"avro": source.raw} if include_raw else None,
            extras=extras,
        )
        return normalize_ordering(api)
