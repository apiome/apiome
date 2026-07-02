"""Protobuf ``FileDescriptorSet`` → canonical model normalizer — MFI-9.2 (#3765).

Maps the compiled artifact MFI-9.1 produces — a ``google.protobuf.FileDescriptorSet``
(carried on :class:`app.proto_descriptor.CompiledDescriptorSet`) — into a
:class:`~app.canonical_model.CanonicalApi` of paradigm
:attr:`~app.canonical_model.ApiParadigm.RPC`. Like the GraphQL normalizer (and unlike the
OpenAPI/AsyncAPI ones), it consumes a *typed* object rather than a parsed ``dict``: it walks
the descriptor messages the protobuf compiler emitted, so syntax/Editions feature resolution,
import resolution and field numbering are the compiler's job, never a re-parse here.

Everything is keyed by its **package-qualified protobuf coordinate** so two versions diff by
identity (the grammar in ``docs/canonical_model.md``):

* **services → :class:`~app.canonical_model.Service`** keyed ``pkg.Service``; each
* **method → :class:`~app.canonical_model.Operation`** keyed ``pkg.Service.Method`` with
  :attr:`~app.canonical_model.OperationKind.REQUEST_RESPONSE` and a
  :class:`~app.canonical_model.StreamingMode` derived from the method's client/server
  streaming flags (unary → ``NONE``, client-streaming → ``CLIENT``, server-streaming →
  ``SERVER``, both → ``BIDIRECTIONAL``) — the acceptance criterion. The input/output message
  types become the operation's request/response :class:`~app.canonical_model.Message`\\s
  (``pkg.Service.Method#request`` / ``#response``), referencing the mapped
  :class:`~app.canonical_model.Type`\\s by key.
* **messages → :class:`~app.canonical_model.Type`** (``RECORD``) keyed ``pkg.Message`` —
  nested messages/enums carry the parent prefix (``pkg.Outer.Inner``). Each
* **field → :class:`~app.canonical_model.CanonicalField`** keyed ``pkg.Message.field`` keeps
  its **field number** on :attr:`~app.canonical_model.CanonicalField.field_number` so a rename
  reads as a *modify*, not an *add + remove*. A ``oneof`` member records its oneof name in
  ``extras``; the message's ``oneof`` declarations and ``reserved`` ranges/names are kept in
  the type's ``extras`` — preserved, per the acceptance criteria, but excluded from the
  identity hash only insofar as descriptions are (they are real ``extras``, so they *do*
  contribute to the fingerprint). A ``map<K,V>`` field's synthetic ``*Entry`` message is
  surfaced as a :attr:`~app.canonical_model.TypeKind.MAP` type and the field references it
  directly (not as a list of entries).
* **enums → :class:`~app.canonical_model.Type`** (``ENUM``) keyed ``pkg.Enum`` with one
  :class:`~app.canonical_model.EnumValue` per value, preserving the value **number** and
  declaration order.

Only the caller's *target* files are mapped; the imports the compiler pulled in (well-known
types, transitive dependencies — flagged :attr:`~app.proto_descriptor.ProtoFileDescriptor.is_import`)
are skipped, exactly as the GraphQL normalizer skips built-in scalars. A referenced type that
lives in an import (``google.protobuf.Timestamp``, a sibling module's message) therefore
appears as a :class:`~app.canonical_model.TypeRef` by key with no local :class:`Type` — the
same dangling-by-design reference a protobuf ``import`` is.

Because ``extras`` and field numbers are carried verbatim into the fingerprint payload (see
:mod:`app.fingerprint`) while ``raw``/descriptions are stripped, a streaming-flag, field-
number, oneof, reserved or label change flips the stable semantic fingerprint while a
comment-only edit does not. The normalizer is **pure** (no I/O) and finishes with
:func:`app.normalizer.normalize_ordering`, so output is byte-stable regardless of declaration
order. It self-registers under the ``protobuf`` format key (the one
:mod:`app.format_detection` emits).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from google.protobuf import descriptor_pb2

from .canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
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
from .proto_descriptor import CompiledDescriptorSet, read_file_descriptor_set

__all__ = ["ProtoNormalizer"]


# The protobuf format key this normalizer registers under and stamps onto the canonical
# model — the same key :mod:`app.format_detection` emits for ``.proto`` source.
_FORMAT_KEY = "protobuf"

# ``FieldDescriptorProto.type`` (the scalar wire types) → the canonical primitive name used as
# a leaf :class:`TypeRef.name`. These are protobuf primitives, so — like GraphQL's built-in
# scalars — they reference no local :class:`Type`. ``TYPE_GROUP``/``TYPE_MESSAGE``/``TYPE_ENUM``
# are *not* here: those carry a ``type_name`` resolved to a package-qualified type key instead.
_SCALAR_TYPE_NAMES: Dict[int, str] = {
    descriptor_pb2.FieldDescriptorProto.TYPE_DOUBLE: "double",
    descriptor_pb2.FieldDescriptorProto.TYPE_FLOAT: "float",
    descriptor_pb2.FieldDescriptorProto.TYPE_INT64: "int64",
    descriptor_pb2.FieldDescriptorProto.TYPE_UINT64: "uint64",
    descriptor_pb2.FieldDescriptorProto.TYPE_INT32: "int32",
    descriptor_pb2.FieldDescriptorProto.TYPE_FIXED64: "fixed64",
    descriptor_pb2.FieldDescriptorProto.TYPE_FIXED32: "fixed32",
    descriptor_pb2.FieldDescriptorProto.TYPE_BOOL: "bool",
    descriptor_pb2.FieldDescriptorProto.TYPE_STRING: "string",
    descriptor_pb2.FieldDescriptorProto.TYPE_BYTES: "bytes",
    descriptor_pb2.FieldDescriptorProto.TYPE_UINT32: "uint32",
    descriptor_pb2.FieldDescriptorProto.TYPE_SFIXED32: "sfixed32",
    descriptor_pb2.FieldDescriptorProto.TYPE_SFIXED64: "sfixed64",
    descriptor_pb2.FieldDescriptorProto.TYPE_SINT32: "sint32",
    descriptor_pb2.FieldDescriptorProto.TYPE_SINT64: "sint64",
}

# ``FieldDescriptorProto.label`` → the source keyword, kept in a field's ``extras`` so a
# presence change (``required``↔``optional``, scalar↔``repeated``) flips the fingerprint.
_LABEL_NAMES: Dict[int, str] = {
    descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL: "optional",
    descriptor_pb2.FieldDescriptorProto.LABEL_REQUIRED: "required",
    descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED: "repeated",
}


class ProtoNormalizer(Normalizer, register=True):
    """Normalize a compiled protobuf descriptor set into a :class:`CanonicalApi`.

    Self-registers under the ``protobuf`` format key. Consumes the
    :class:`~app.proto_descriptor.CompiledDescriptorSet` MFI-9.1 produces (or a bare
    ``google.protobuf.FileDescriptorSet``/its bytes) and walks the typed descriptor messages —
    services/methods/messages/enums — mapping them onto package-qualified coordinates with
    field numbers and streaming flags preserved.
    """

    format = _FORMAT_KEY
    paradigm = ApiParadigm.RPC

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Normalize a compiled protobuf descriptor set into the canonical RPC model.

        Args:
            source: The compiled descriptor set. Accepted forms, in order of preference:
                a :class:`~app.proto_descriptor.CompiledDescriptorSet` (carries the
                target/import distinction, so imports are skipped); a bare
                ``google.protobuf.FileDescriptorSet`` message (every file treated as a
                target); or the binary ``FileDescriptorSet`` ``bytes`` (parsed via
                :func:`~app.proto_descriptor.read_file_descriptor_set`). Compilation /
                import resolution happen *before* this call (MFI-9.1).
            include_raw: When ``True`` (default) the textual debug form of the descriptor
                set is preserved on :attr:`CanonicalApi.raw` (under ``descriptor_set``) for
                full-fidelity inspection; pass ``False`` to omit it.

        Returns:
            The order-normalized :class:`CanonicalApi` with ``format`` ``protobuf`` and
            ``paradigm`` :attr:`~app.canonical_model.ApiParadigm.RPC`.

        Raises:
            ValueError: If ``source`` is not a recognized descriptor-set form.
        """
        compiled = self._coerce_source(source)
        descriptor_set = compiled.proto
        import_names = {f.name for f in compiled.files if f.is_import}

        # Map only the caller's target files; imports (well-known types, transitive deps) are
        # referenced by key but not re-emitted, mirroring how a protobuf ``import`` works.
        target_protos = [
            file_proto
            for file_proto in descriptor_set.file
            if file_proto.name not in import_names
        ]

        types: List[Type] = []
        services: List[Service] = []
        for file_proto in target_protos:
            package = file_proto.package
            for message in file_proto.message_type:
                self._collect_message_types(message, package, parent_key=None, into=types)
            for enum in file_proto.enum_type:
                types.append(self._enum_type(enum, package, parent_key=None))
            for service in file_proto.service:
                services.append(self._service(service, package))

        api = CanonicalApi(
            paradigm=self.paradigm,
            format=_FORMAT_KEY,
            protocol="grpc",
            identity=self._identity(target_protos),
            services=services,
            types=types,
            raw={"descriptor_set": _descriptor_set_text(descriptor_set)}
            if include_raw
            else None,
        )
        return normalize_ordering(api)

    # --- source coercion ----------------------------------------------------

    @staticmethod
    def _coerce_source(source: Any) -> CompiledDescriptorSet:
        """Coerce an accepted ``source`` form into a :class:`CompiledDescriptorSet`.

        A :class:`CompiledDescriptorSet` is returned as-is (its import flags are honoured).
        A bare ``FileDescriptorSet`` is re-serialized and read back with no ``target_files``,
        so every file counts as a target. ``bytes`` are parsed directly.

        Raises:
            ValueError: If ``source`` is none of those forms.
        """
        if isinstance(source, CompiledDescriptorSet):
            return source
        if isinstance(source, descriptor_pb2.FileDescriptorSet):
            return read_file_descriptor_set(source.SerializeToString())
        if isinstance(source, (bytes, bytearray)):
            return read_file_descriptor_set(bytes(source))
        raise ValueError(
            "Protobuf source must be a CompiledDescriptorSet, a "
            "google.protobuf.FileDescriptorSet, or its serialized bytes "
            "(see app.proto_descriptor.compile_proto_descriptor_set)"
        )

    @staticmethod
    def _identity(target_protos: Sequence[descriptor_pb2.FileDescriptorProto]) -> ApiIdentity:
        """Derive the artifact identity from the target files.

        Uses the first non-empty ``package`` as both the namespace and the human name (a
        protobuf API is identified by its package), falling back to the first target file's
        path, then a generic label, when no file declares a package.
        """
        for file_proto in target_protos:
            if file_proto.package:
                return ApiIdentity(
                    name=file_proto.package, namespace=file_proto.package
                )
        if target_protos:
            return ApiIdentity(name=target_protos[0].name)
        return ApiIdentity(name="Protobuf API")

    # --- services / methods -------------------------------------------------

    def _service(
        self, service: descriptor_pb2.ServiceDescriptorProto, package: str
    ) -> Service:
        """Coerce a ``service`` into a :class:`Service` keyed ``pkg.Service``."""
        service_key = Keys.type(service.name, package or None)
        return Service(
            key=service_key,
            name=service.name,
            operations=[
                self._operation(method, service_key) for method in service.method
            ],
        )

    def _operation(
        self, method: descriptor_pb2.MethodDescriptorProto, service_key: str
    ) -> Operation:
        """Coerce one ``rpc`` method into an :class:`Operation`.

        The streaming flags become the canonical :class:`StreamingMode`; the input/output
        message types become the request/response :class:`Message`\\s, referencing their
        mapped :class:`Type` by package-qualified key.
        """
        op_key = Keys.operation_rpc(service_key, method.name)
        extras: Dict[str, Any] = {}
        idempotency = _idempotency_label(method.options)
        if idempotency is not None:
            extras["idempotency_level"] = idempotency
        return Operation(
            key=op_key,
            name=method.name,
            kind=OperationKind.REQUEST_RESPONSE,
            streaming=_streaming_mode(method),
            deprecated=bool(method.options.deprecated),
            messages=[
                Message(
                    key=Keys.request_message(op_key),
                    role=MessageRole.REQUEST,
                    payload=TypeRef(name=_strip_leading_dot(method.input_type)),
                ),
                Message(
                    key=f"{op_key}#response",
                    role=MessageRole.RESPONSE,
                    payload=TypeRef(name=_strip_leading_dot(method.output_type)),
                ),
            ],
            extras=extras,
        )

    # --- messages → types ---------------------------------------------------

    def _collect_message_types(
        self,
        message: descriptor_pb2.DescriptorProto,
        package: str,
        *,
        parent_key: Optional[str],
        into: List[Type],
    ) -> None:
        """Append the :class:`Type` for ``message`` and recurse into its nested types.

        The type key is the parent-qualified coordinate (``pkg.Outer.Inner``). A synthetic
        ``map<K,V>`` entry message is emitted as a :attr:`TypeKind.MAP` type rather than a
        ``RECORD``; nested enums become their own ``ENUM`` types. Nested types are appended
        to ``into`` (a flat list — the canonical tree of named types is flat).
        """
        type_key = _qualified(parent_key or package or None, message.name)

        if message.options.map_entry:
            into.append(self._map_entry_type(message, type_key))
        else:
            into.append(self._record_type(message, type_key))

        for nested in message.nested_type:
            self._collect_message_types(
                nested, package, parent_key=type_key, into=into
            )
        for nested_enum in message.enum_type:
            into.append(self._enum_type(nested_enum, package, parent_key=type_key))

    def _record_type(
        self, message: descriptor_pb2.DescriptorProto, type_key: str
    ) -> Type:
        """Coerce a (non-map) message into a ``RECORD`` :class:`Type`.

        ``oneof`` declarations (excluding the synthetic wrappers proto3 ``optional`` fields
        generate) and ``reserved`` ranges/names are preserved in the type's ``extras``.
        """
        # ``oneof_index`` on a field points into this list; a synthetic oneof (the wrapper a
        # proto3 ``optional`` field generates) is identified by its lone field's
        # ``proto3_optional`` flag and is *not* surfaced as a real oneof.
        synthetic = {
            field.oneof_index
            for field in message.field
            if field.HasField("oneof_index") and field.proto3_optional
        }
        real_oneofs = [
            oneof.name
            for index, oneof in enumerate(message.oneof_decl)
            if index not in synthetic
        ]

        extras: Dict[str, Any] = {}
        if real_oneofs:
            extras["oneofs"] = real_oneofs
        reserved = _reserved_extras(message)
        extras.update(reserved)

        return Type(
            key=type_key,
            name=message.name,
            kind=TypeKind.RECORD,
            fields=[
                self._field(field, message, type_key, synthetic)
                for field in message.field
            ],
            extras=extras,
        )

    def _map_entry_type(
        self, message: descriptor_pb2.DescriptorProto, type_key: str
    ) -> Type:
        """Coerce a synthetic ``map<K,V>`` entry message into a ``MAP`` :class:`Type`.

        A protobuf map field compiles to a repeated, nested message with ``map_entry`` set
        and exactly two fields — ``key`` (number 1) and ``value`` (number 2). They become the
        :class:`Type`'s :attr:`~app.canonical_model.Type.key_type` /
        :attr:`~app.canonical_model.Type.value_type`, so the referencing field can point at a
        single MAP type instead of a list of entries.
        """
        key_field = next((f for f in message.field if f.number == 1), None)
        value_field = next((f for f in message.field if f.number == 2), None)
        return Type(
            key=type_key,
            name=message.name,
            kind=TypeKind.MAP,
            key_type=_leaf_type_ref(key_field) if key_field is not None else None,
            value_type=_leaf_type_ref(value_field) if value_field is not None else None,
        )

    def _field(
        self,
        field: descriptor_pb2.FieldDescriptorProto,
        message: descriptor_pb2.DescriptorProto,
        type_key: str,
        synthetic_oneofs: set[int],
    ) -> CanonicalField:
        """Coerce one message field into a :class:`CanonicalField`, keeping its field number.

        ``repeated`` fields become a list :class:`TypeRef` (a ``map`` field, whose entry is a
        ``MAP`` type, references that type directly — not as a list). The source ``label``,
        ``proto3_optional`` flag, and real-``oneof`` membership are kept in ``extras`` so a
        presence/grouping change flips the fingerprint; a proto2 ``default`` populates
        :attr:`~app.canonical_model.CanonicalField.default`.
        """
        extras: Dict[str, Any] = {}
        label = _LABEL_NAMES.get(field.label)
        if label is not None:
            extras["label"] = label
        if field.proto3_optional:
            extras["proto3_optional"] = True
        # Real-oneof membership (synthetic proto3-optional wrappers excluded) is identity-
        # bearing: moving a field into/out of a oneof changes the message contract.
        if (
            field.HasField("oneof_index")
            and field.oneof_index not in synthetic_oneofs
            and 0 <= field.oneof_index < len(message.oneof_decl)
        ):
            extras["oneof"] = message.oneof_decl[field.oneof_index].name

        return CanonicalField(
            key=Keys.field(type_key, field.name),
            name=field.name,
            type=_field_type_ref(field),
            field_number=field.number,
            default=field.default_value if field.HasField("default_value") else None,
            deprecated=bool(field.options.deprecated),
            extras=extras,
        )

    # --- enums --------------------------------------------------------------

    def _enum_type(
        self,
        enum: descriptor_pb2.EnumDescriptorProto,
        package: str,
        *,
        parent_key: Optional[str],
    ) -> Type:
        """Coerce an ``enum`` into an ``ENUM`` :class:`Type`, preserving value numbers.

        Enum values keep their declaration order and wire ``value`` (number); ``reserved``
        ranges/names and an ``allow_alias`` option are preserved in ``extras``.
        """
        type_key = _qualified(parent_key or package or None, enum.name)
        values = [
            EnumValue(
                key=Keys.enum_value(type_key, value.name),
                name=value.name,
                value=value.number,
            )
            for value in enum.value
        ]
        extras: Dict[str, Any] = {}
        if enum.options.allow_alias:
            extras["allow_alias"] = True
        extras.update(_reserved_extras(enum))
        return Type(
            key=type_key,
            name=enum.name,
            kind=TypeKind.ENUM,
            enum_values=values,
            extras=extras,
        )


# ===========================================================================
# Module-level helpers (pure)
# ===========================================================================


def _streaming_mode(method: descriptor_pb2.MethodDescriptorProto) -> StreamingMode:
    """Map a method's client/server streaming flags to a :class:`StreamingMode`.

    ``(client, server)`` → ``(False, False)`` unary → ``NONE``; ``(True, False)`` →
    ``CLIENT``; ``(False, True)`` → ``SERVER``; ``(True, True)`` → ``BIDIRECTIONAL``. This
    pairing is the MFI-9.2 acceptance criterion.
    """
    client = method.client_streaming
    server = method.server_streaming
    if client and server:
        return StreamingMode.BIDIRECTIONAL
    if client:
        return StreamingMode.CLIENT
    if server:
        return StreamingMode.SERVER
    return StreamingMode.NONE


def _field_type_ref(field: descriptor_pb2.FieldDescriptorProto) -> TypeRef:
    """Build the use-site :class:`TypeRef` for a field, honouring ``repeated``.

    A ``map`` field — a ``repeated`` message whose type is a synthetic ``*Entry`` — is *not*
    wrapped in a list: it references its ``MAP`` type directly (the entry message is emitted as
    a MAP type elsewhere), which is the natural canonical shape for a dictionary. Every other
    ``repeated`` field becomes a list :class:`TypeRef` wrapping the element type. A protobuf
    field element is never null, so list levels are ``nullable=False``; a singular field's
    nullability follows its presence (``required`` → non-null, else nullable).
    """
    leaf = _leaf_type_ref(field)
    if field.label == descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED:
        if _is_map_field(field):
            # The MAP type already models key/value; reference it as a single value.
            return TypeRef(name=leaf.name, nullable=False)
        return TypeRef(item=leaf, nullable=False)
    return leaf


def _leaf_type_ref(field: descriptor_pb2.FieldDescriptorProto) -> TypeRef:
    """Build the leaf (non-list) :class:`TypeRef` naming a field's type.

    A scalar field resolves to its protobuf primitive name (``int64``/``string``/…); a
    message/enum/group field resolves to the package-qualified key of its ``type_name`` (the
    leading ``.`` the compiler emits is stripped). ``nullable`` is ``False`` for a proto2
    ``required`` field and ``True`` otherwise (optional/singular fields carry presence or a
    zero default).
    """
    nullable = field.label != descriptor_pb2.FieldDescriptorProto.LABEL_REQUIRED
    scalar = _SCALAR_TYPE_NAMES.get(field.type)
    if scalar is not None:
        return TypeRef(name=scalar, nullable=nullable)
    # TYPE_MESSAGE / TYPE_ENUM / TYPE_GROUP carry a resolved, fully-qualified type_name.
    return TypeRef(name=_strip_leading_dot(field.type_name), nullable=nullable)


def _is_map_field(field: descriptor_pb2.FieldDescriptorProto) -> bool:
    """Heuristically identify a ``map<K,V>`` field by its compiled shape.

    A map field is a ``repeated`` message whose type name ends in the ``Entry`` suffix the
    compiler synthesizes (``<FieldNameCamelCase>Entry``). The definitive signal — the entry
    message's ``map_entry`` option — lives on the type, not the use site, so this name-based
    check is what a use-site has; the entry type itself is independently classified MAP by
    :meth:`ProtoNormalizer._collect_message_types`.
    """
    return (
        field.type == descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE
        and field.label == descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED
        and field.type_name.endswith("Entry")
    )


def _reserved_extras(
    message: descriptor_pb2.DescriptorProto | descriptor_pb2.EnumDescriptorProto,
) -> Dict[str, Any]:
    """Return ``reserved`` ranges/names as ``extras`` entries, or ``{}`` when none.

    A message's reserved ranges are ``[start, end)`` half-open; an enum's are inclusive. Both
    are preserved verbatim (as ``[start, end]`` pairs) so a reservation change — which protects
    a retired field/value number — flips the fingerprint, per the acceptance criteria.
    """
    extras: Dict[str, Any] = {}
    ranges = [[r.start, r.end] for r in message.reserved_range]
    if ranges:
        extras["reserved_ranges"] = ranges
    names = list(message.reserved_name)
    if names:
        extras["reserved_names"] = names
    return extras


def _idempotency_label(options: descriptor_pb2.MethodOptions) -> Optional[str]:
    """Return a method's ``idempotency_level`` as a short label, or ``None`` when default.

    ``NO_SIDE_EFFECTS`` / ``IDEMPOTENT`` are returned lower-cased; the
    ``IDEMPOTENCY_UNKNOWN`` default is ``None`` so it does not clutter ``extras``.
    """
    level = options.idempotency_level
    enum = descriptor_pb2.MethodOptions
    if level == enum.NO_SIDE_EFFECTS:
        return "no_side_effects"
    if level == enum.IDEMPOTENT:
        return "idempotent"
    return None


def _qualified(prefix: Optional[str], name: str) -> str:
    """Join a package/parent ``prefix`` and a ``name`` into a dotted coordinate.

    ``("acme.user", "User")`` → ``"acme.user.User"``; a falsy prefix yields the bare name.
    Reuses :meth:`app.normalizer.Keys.type`'s grammar so message/enum/nested keys match the
    documented protobuf coordinate.
    """
    return Keys.type(name, prefix or None)


def _strip_leading_dot(type_name: str) -> str:
    """Strip the leading ``.`` the compiler puts on fully-qualified ``type_name``s.

    ``.acme.user.User`` → ``acme.user.User`` so the reference matches the package-qualified
    :class:`Type.key` the message mapping assigns. A name without a leading dot is returned
    unchanged.
    """
    return type_name[1:] if type_name.startswith(".") else type_name


def _descriptor_set_text(descriptor_set: descriptor_pb2.FileDescriptorSet) -> str:
    """Render a descriptor set to its protobuf text form for the ``raw`` bag.

    The text form is human-readable and stable, suitable for full-fidelity inspection and
    per-format lint; it is stripped from the fingerprint with the rest of ``raw``.
    """
    return str(descriptor_set)
