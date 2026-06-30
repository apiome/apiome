"""Normalizer SPI: format → canonical model — MFI-2.3 (#3740).

The canonical model (MFI-2.1, :mod:`app.canonical_model`) is the one
paradigm-agnostic shape every importable API description normalizes into. *This*
module is the contract that turns a parsed source document of some format
(OpenAPI, gRPC/Protobuf, AsyncAPI, GraphQL, Avro, …) into that shape, plus the
shared helpers every format implementation needs so the same work is not written
five times:

* **The SPI** — :class:`Normalizer`, a tiny abstract contract (``format`` +
  ``paradigm`` identity and a single :meth:`Normalizer.normalize` method). Each
  format epic subclasses it and registers the subclass (:func:`register_normalizer`)
  so the import pipeline can look one up by format key (:func:`get_normalizer`).

* **Stable-key assignment** — :class:`Keys`, deterministic builders for the
  ``key`` every canonical entity carries, matching the grammar documented in
  ``docs/canonical_model.md`` (``GET /pets/{id}``, ``GET /pets/{id}#path.id``,
  ``User.email``, …) so two versions diff by identity, not position, and two
  imports of the *same* document produce byte-identical keys.

* **Schema coercion** — :func:`coerce_constraints` and :class:`SchemaCoercer`,
  which map a JSON-Schema fragment (OpenAPI 3.1 schemas *are* JSON Schema, and
  most formats' constraint vocabularies map onto the same keywords) into the
  canonical type model — :class:`~app.canonical_model.TypeRef`,
  :class:`~app.canonical_model.Constraints`, and named
  :class:`~app.canonical_model.Type` definitions. This reuses the JSON-Schema /
  primitives vocabulary already used elsewhere in the service rather than
  inventing a parallel one.

* **Ordering normalization** — :func:`normalize_ordering`, which sorts the
  identity-keyed collections of a :class:`~app.canonical_model.CanonicalApi` into
  a deterministic order so the serialized model (and therefore its fingerprint
  and diff) is stable regardless of the source's declaration order.

A normalizer is **pure** (no network/DB): it takes an already-parsed document and
returns a :class:`~app.canonical_model.CanonicalApi`, which the persistence layer
(MFI-2.2) stores as JSONB. The reference implementation is
:class:`app.openapi_normalizer.OpenApiNormalizer`; see ``docs/normalizer_spi.md``
for how to implement one.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar, Dict, List, Optional, Tuple

from .canonical_model import (
    ApiParadigm,
    CanonicalApi,
    Constraints,
    Type,
    TypeKind,
    TypeRef,
)

__all__ = [
    "Normalizer",
    "register_normalizer",
    "get_normalizer",
    "available_formats",
    "Keys",
    "coerce_constraints",
    "SchemaCoercer",
    "normalize_ordering",
]


# ===========================================================================
# The SPI contract + registry
# ===========================================================================


class Normalizer(ABC):
    """Service-provider contract: parse-tree of one format → :class:`CanonicalApi`.

    A concrete normalizer declares which ``format`` key and which
    :class:`~app.canonical_model.ApiParadigm` it produces, and implements
    :meth:`normalize`. It must be **deterministic and side-effect free** — given
    the same ``source`` it returns an equal model, performs no I/O, and assigns
    every entity a stable :class:`Keys`-style ``key`` so downstream
    fingerprint/diff/lint/browse work uniformly. Implementations should finish by
    returning :func:`normalize_ordering`'s result so output ordering is stable.

    Subclasses are registered with :func:`register_normalizer` (typically via the
    ``register=True`` flag on ``__init_subclass__``) and looked up by ``format``
    with :func:`get_normalizer`.
    """

    #: Source format key this normalizer consumes, e.g. ``"openapi-3.1"``. Used as
    #: the registry key and copied onto :attr:`CanonicalApi.format`.
    format: ClassVar[str] = ""

    #: The canonical paradigm this normalizer emits (copied onto
    #: :attr:`CanonicalApi.paradigm`).
    paradigm: ClassVar[ApiParadigm]

    def __init_subclass__(cls, *, register: bool = False, **kwargs: Any) -> None:
        """Optionally self-register a concrete subclass in the format registry.

        Args:
            register: When ``True``, the subclass is added to the global registry
                under its :attr:`format` key as soon as it is defined, so a format
                epic only needs ``class FooNormalizer(Normalizer, register=True)``.
        """
        super().__init_subclass__(**kwargs)
        if register:
            register_normalizer(cls)

    @abstractmethod
    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Normalize one parsed source document into the canonical model.

        Args:
            source: The already-parsed source document (for OpenAPI/AsyncAPI a
                ``dict``; for other formats whatever that format's parser
                produces). Parsing and ``$ref`` resolution happen *before* this
                call — a normalizer maps an in-memory tree, it does not fetch.
            include_raw: When ``True`` (default) the native source is preserved on
                :attr:`CanonicalApi.raw` for full-fidelity round-tripping and
                per-format lint; pass ``False`` to omit it (e.g. when the raw bag
                is stored separately).

        Returns:
            A fully populated, order-normalized
            :class:`~app.canonical_model.CanonicalApi` whose ``format`` and
            ``paradigm`` equal this normalizer's :attr:`format`/:attr:`paradigm`.
        """
        raise NotImplementedError


# Format-key → normalizer-class registry. A format epic registers its normalizer
# here so the import pipeline resolves one by the detected format key without
# importing every format module directly.
_REGISTRY: Dict[str, type[Normalizer]] = {}


def register_normalizer(cls: type[Normalizer]) -> type[Normalizer]:
    """Register a concrete normalizer class under its :attr:`Normalizer.format` key.

    Args:
        cls: A concrete :class:`Normalizer` subclass with a non-empty ``format``.

    Returns:
        ``cls`` unchanged, so this can also be used as a class decorator.

    Raises:
        ValueError: If ``cls.format`` is empty, or a *different* class is already
            registered under the same key (re-registering the same class is a
            no-op so module re-import is safe).
    """
    key = cls.format
    if not key:
        raise ValueError(f"{cls.__name__} must set a non-empty `format` to register")
    existing = _REGISTRY.get(key)
    if existing is not None and existing is not cls:
        raise ValueError(
            f"format {key!r} already registered to {existing.__name__}; "
            f"cannot re-register to {cls.__name__}"
        )
    _REGISTRY[key] = cls
    return cls


def get_normalizer(format_key: str) -> Optional[type[Normalizer]]:
    """Return the normalizer class registered for ``format_key``, or ``None``."""
    return _REGISTRY.get(format_key)


def available_formats() -> List[str]:
    """Return the sorted list of format keys that have a registered normalizer."""
    return sorted(_REGISTRY)


# ===========================================================================
# Stable-key assignment
# ===========================================================================


class Keys:
    """Deterministic builders for canonical entity ``key`` strings.

    Centralizing the key grammar (documented in ``docs/canonical_model.md``)
    guarantees every normalizer assigns identical keys for identical source
    constructs — which is the whole point of a *stable* key: a diff lines two
    versions up by identity, and re-importing the same document is a no-op. All
    methods are pure ``staticmethod``s returning the canonical coordinate string.
    """

    # --- REST / OpenAPI -----------------------------------------------------

    @staticmethod
    def operation_http(method: str, path: str) -> str:
        """Operation key for a REST endpoint, e.g. ``GET /pets/{id}``.

        Args:
            method: HTTP verb (case-insensitive; normalized to upper-case).
            path: Route template, e.g. ``/pets/{id}``.
        """
        return f"{method.upper()} {path}"

    @staticmethod
    def parameter(operation_key: str, location: str, name: str) -> str:
        """Parameter key, e.g. ``GET /pets/{id}#path.id``.

        Args:
            operation_key: The owning operation's key.
            location: Parameter location (``path``/``query``/``header``/``cookie``).
            name: Source parameter name.
        """
        return f"{operation_key}#{location}.{name}"

    @staticmethod
    def request_message(operation_key: str) -> str:
        """Request-message key, e.g. ``GET /pets/{id}#request``."""
        return f"{operation_key}#request"

    @staticmethod
    def response_message(operation_key: str, status_code: str) -> str:
        """Response-message key, e.g. ``GET /pets/{id}#response.200``.

        Args:
            operation_key: The owning operation's key.
            status_code: HTTP status (``200``), range (``4XX``), or ``default``.
        """
        return f"{operation_key}#response.{status_code}"

    # --- Types / fields (all paradigms) -------------------------------------

    @staticmethod
    def type(name: str, namespace: Optional[str] = None) -> str:
        """Type key — bare name (``Pet``) or package-qualified (``acme.Pet``).

        Args:
            name: Source type name.
            namespace: Package / namespace / target namespace, if any.
        """
        return f"{namespace}.{name}" if namespace else name

    @staticmethod
    def field(type_key: str, field_name: str) -> str:
        """Field key, e.g. ``Pet.name`` / ``User.email`` (the GraphQL coordinate)."""
        return f"{type_key}.{field_name}"

    @staticmethod
    def enum_value(type_key: str, value_name: str) -> str:
        """Enum-member key, e.g. ``Status.ACTIVE``."""
        return f"{type_key}.{value_name}"

    # --- RPC / GraphQL (provided for format epics) --------------------------

    @staticmethod
    def operation_rpc(service_key: str, method: str) -> str:
        """RPC operation key, e.g. ``acme.PetService.GetPet``."""
        return f"{service_key}.{method}"

    @staticmethod
    def operation_graphql(root_type: str, field_name: str) -> str:
        """GraphQL operation key (a schema coordinate), e.g. ``Query.user``."""
        return f"{root_type}.{field_name}"

    @staticmethod
    def graphql_argument(operation_key: str, name: str) -> str:
        """GraphQL field-argument key, e.g. ``Query.user#arg.id``.

        A GraphQL field's arguments have no HTTP-style location; they are
        carried under an ``#arg.`` segment off the owning operation's coordinate
        (the grammar in ``docs/canonical_model.md``), keeping them distinct from
        REST ``#path.``/``#query.`` parameters while still hanging off the same
        operation key.

        Args:
            operation_key: The owning operation's key, e.g. ``Query.user``.
            name: The argument's source name.
        """
        return f"{operation_key}#arg.{name}"

    @staticmethod
    def graphql_response(operation_key: str) -> str:
        """GraphQL operation response-message key, e.g. ``Query.user#response``.

        A GraphQL field resolves to a single return type; that return type is
        modeled as the operation's lone response :class:`~app.canonical_model.Message`,
        keyed off the operation coordinate so a return-type change is diffable.

        Args:
            operation_key: The owning operation's key, e.g. ``Query.user``.
        """
        return f"{operation_key}#response"

    # --- Event / AsyncAPI (provided for format epics) -----------------------

    @staticmethod
    def channel(address: str) -> str:
        """Channel key — the wire address, e.g. ``user/{userId}/signedup``.

        The channel's address *is* its stable coordinate (it is what a producer
        publishes to / a consumer subscribes from), so two versions of an event
        API diff their channels by address. For AsyncAPI 3 channels that declare an
        ``address`` it is that field; for AsyncAPI 2 channels (whose map key *is*
        the address) it is the map key.

        Args:
            address: The channel's wire address/topic/routing key.
        """
        return address

    @staticmethod
    def operation_event(action: str, address: str, name: Optional[str] = None) -> str:
        """Event-operation key — the operation name, or ``{action} {address}``.

        AsyncAPI 3 names its operations (``onUserSignedUp``), so that name is the
        stable key. AsyncAPI 2 carries operations as ``publish``/``subscribe`` on a
        channel and may name them with an ``operationId``; absent that, the key
        falls back to the action plus the channel address (``publish user/signedup``)
        so it is still stable and unique within the document.

        Args:
            action: The wire action (``send``/``receive`` in v3, ``publish``/
                ``subscribe`` in v2) — used only for the fallback key.
            address: The channel address the operation is bound to.
            name: The operation's own name/``operationId`` when it has one.
        """
        if name:
            return name
        return f"{action} {address}"

    @staticmethod
    def event_message(operation_key: str, message_name: str) -> str:
        """Event-message key, e.g. ``onUserSignedUp#event.UserSignedUp``.

        Args:
            operation_key: The owning operation's key.
            message_name: The message's source name (or a synthesized ordinal name
                when the message is anonymous).
        """
        return f"{operation_key}#event.{message_name}"

    @staticmethod
    def channel_parameter(channel_key: str, name: str) -> str:
        """Channel address-parameter key, e.g. ``user/{userId}/signedup#param.userId``.

        Args:
            channel_key: The owning channel's key.
            name: The address-template parameter name.
        """
        return f"{channel_key}#param.{name}"


# ===========================================================================
# Schema coercion (JSON-Schema fragment → canonical type model)
# ===========================================================================


# JSON-Schema constraint keyword → :class:`Constraints` attribute. OpenAPI 3.1
# schemas *are* JSON Schema, so these are the draft-2020-12 spellings; the
# coercer also accepts the OpenAPI-3.0 boolean ``exclusiveMinimum/Maximum`` form.
_CONSTRAINT_KEYWORDS: Tuple[Tuple[str, str], ...] = (
    ("minimum", "minimum"),
    ("maximum", "maximum"),
    ("multipleOf", "multiple_of"),
    ("minLength", "min_length"),
    ("maxLength", "max_length"),
    ("pattern", "pattern"),
    ("minItems", "min_items"),
    ("maxItems", "max_items"),
    ("uniqueItems", "unique_items"),
    ("enum", "enum"),
    ("format", "format"),
)

# JSON-Schema scalar ``type`` keywords. Anything not here that lacks
# ``properties``/``items``/composition is treated as a custom scalar by name.
_SCALAR_TYPES = frozenset({"string", "number", "integer", "boolean", "null"})


def coerce_constraints(schema: Dict[str, Any]) -> Optional[Constraints]:
    """Extract the JSON-Schema validation facets of ``schema`` as :class:`Constraints`.

    Reuses the JSON-Schema constraint vocabulary directly (``minLength``,
    ``pattern``, ``format``, …); ``exclusiveMinimum``/``exclusiveMaximum`` are
    accepted in both the JSON-Schema numeric form (draft 2020-12 / OpenAPI 3.1)
    and the OpenAPI-3.0 boolean form (paired with ``minimum``/``maximum``).

    Args:
        schema: A JSON-Schema fragment (a property schema, parameter schema, or
            scalar type definition).

    Returns:
        A :class:`Constraints` holding every recognized facet, or ``None`` when
        the schema carries no constraints (so the canonical field stays clean).
    """
    values: Dict[str, Any] = {}
    for json_key, attr in _CONSTRAINT_KEYWORDS:
        if json_key in schema:
            values[attr] = schema[json_key]

    # exclusiveMinimum/Maximum: numeric (3.1) → value; boolean true (3.0) → the
    # paired minimum/maximum becomes the exclusive bound and the inclusive one
    # is dropped, matching the two specs' semantics.
    for excl_key, incl_key, excl_attr, incl_attr in (
        ("exclusiveMinimum", "minimum", "exclusive_minimum", "minimum"),
        ("exclusiveMaximum", "maximum", "exclusive_maximum", "maximum"),
    ):
        excl = schema.get(excl_key)
        if isinstance(excl, bool):
            if excl and incl_key in schema:
                values[excl_attr] = schema[incl_key]
                values.pop(incl_attr, None)
        elif excl is not None:
            values[excl_attr] = excl

    return Constraints(**values) if values else None


class SchemaCoercer:
    """Map JSON-Schema fragments into the canonical type model.

    A coercer is created once per artifact with the components/definitions map it
    can resolve ``$ref``s against and the JSON-Pointer prefix those refs use
    (``#/components/schemas`` for OpenAPI). It exposes two operations:

    * :meth:`type_ref` — coerce a schema at a *use site* (a property type, a
      parameter type, a response payload) into a :class:`TypeRef`, capturing list
      nesting and nullability exactly.
    * :meth:`named_type` — coerce a *named* schema into a :class:`Type`
      (RECORD/ENUM/UNION/MAP/SCALAR/ALIAS), recursing into its members.

    Named ``$ref`` targets are emitted as their own :class:`Type` with the bare
    ref name as key; the caller collects them from :attr:`emitted_types`. The
    coercer never resolves a ``$ref`` inline — it records the referenced key so
    the model stays a flat, self-referential tree (as the persistence layer
    expects).
    """

    def __init__(
        self,
        components: Optional[Dict[str, Any]] = None,
        ref_prefix: str = "#/components/schemas/",
    ) -> None:
        """Create a coercer.

        Args:
            components: Map of named schema name → schema, used only to drive
                :meth:`named_types_from_components`; ``$ref`` resolution itself is
                by name and does not require this map.
            ref_prefix: The JSON-Pointer prefix a local ``$ref`` uses, so the
                referenced type name can be recovered (the segment after it).
        """
        self.components = components or {}
        self.ref_prefix = ref_prefix
        #: Synthesized named types discovered while coercing use sites (inline
        #: enums become named types so they are diffable). Keyed by type key.
        self.emitted_types: Dict[str, Type] = {}

    # --- use-site coercion --------------------------------------------------

    def ref_name(self, ref: str) -> str:
        """Recover the type key from a ``$ref`` string (the last pointer segment)."""
        if ref.startswith(self.ref_prefix):
            return ref[len(self.ref_prefix) :]
        # Fall back to the final path segment for foreign/remote refs.
        return ref.rstrip("/").rsplit("/", 1)[-1]

    @staticmethod
    def _nullability(schema: Dict[str, Any], *, required: bool) -> bool:
        """Decide a use-site's ``nullable`` from the schema and required-ness.

        A use site is nullable when the schema marks it nullable — OpenAPI 3.0
        ``nullable: true`` or OpenAPI 3.1 ``"null"`` in a ``type`` array — or when
        the member is optional (not in its parent's ``required`` list). A required,
        non-nullable member yields ``nullable=False``.
        """
        if schema.get("nullable") is True:
            return True
        type_ = schema.get("type")
        if isinstance(type_, list) and "null" in type_:
            return True
        return not required

    @staticmethod
    def _primary_type(schema: Dict[str, Any]) -> Optional[str]:
        """Return the non-null scalar/array ``type`` of a schema, if single-valued.

        Collapses the OpenAPI-3.1 ``["string", "null"]`` form to ``"string"``.
        """
        type_ = schema.get("type")
        if isinstance(type_, list):
            non_null = [t for t in type_ if t != "null"]
            return non_null[0] if non_null else None
        return type_

    def type_ref(self, schema: Dict[str, Any], *, required: bool = True) -> TypeRef:
        """Coerce a schema *at a use site* into a :class:`TypeRef`.

        Handles ``$ref`` (→ named reference), ``type: array`` (→ a list wrapping
        the coerced ``items``), the OpenAPI-3.1 nullable-via-``["T","null"]`` form,
        and bare scalars. Unrecognized shapes (bare ``oneOf``/``anyOf`` at a use
        site, or a typeless schema) yield a permissive ``TypeRef`` with no
        ``name``; the original fragment is preserved by the caller's ``extras``.

        Args:
            schema: The use-site schema fragment.
            required: Whether the owning member is required, which (with the
                schema's own nullability markers) determines ``nullable``.

        Returns:
            A :class:`TypeRef` whose ``nullable`` reflects *this* level only, so
            nested-list/nullability fidelity is exact.
        """
        nullable = self._nullability(schema, required=required)

        ref = schema.get("$ref")
        if isinstance(ref, str):
            return TypeRef(name=self.ref_name(ref), nullable=nullable)

        primary = self._primary_type(schema)
        if primary == "array":
            items = schema.get("items")
            inner = (
                self.type_ref(items, required=True)
                if isinstance(items, dict)
                else TypeRef()  # tuple/typeless items → permissive leaf
            )
            return TypeRef(item=inner, nullable=nullable)

        if primary in _SCALAR_TYPES and primary is not None:
            return TypeRef(name=primary, nullable=nullable)

        # Typeless schema (e.g. a free-form object or a use-site oneOf): leave the
        # name unset; the use site's `extras` retains the raw schema for fidelity.
        return TypeRef(nullable=nullable)

    # --- named-type coercion ------------------------------------------------

    def named_types_from_components(self) -> List[Type]:
        """Coerce every entry of the configured ``components`` map into a :class:`Type`.

        Returns:
            One :class:`Type` per named schema, plus any types synthesized while
            recursing (collected from :attr:`emitted_types`). Returned in the
            components' declaration order; the caller is expected to run
            :func:`normalize_ordering` for a deterministic final order.
        """
        types: List[Type] = []
        for name, schema in self.components.items():
            if isinstance(schema, dict):
                types.append(self.named_type(name, schema))
        # Append synthesized types not already present by key.
        present = {t.key for t in types}
        for key, type_ in self.emitted_types.items():
            if key not in present:
                types.append(type_)
        return types

    def named_type(self, name: str, schema: Dict[str, Any]) -> Type:
        """Coerce a *named* schema into a canonical :class:`Type`.

        The resulting :attr:`Type.kind` is inferred from the schema shape:

        * ``oneOf``/``anyOf`` → :attr:`TypeKind.UNION` (members by ref key);
        * ``enum`` on a scalar → :attr:`TypeKind.ENUM`;
        * ``type: object`` / ``properties`` → :attr:`TypeKind.RECORD`, or
          :attr:`TypeKind.MAP` when it is a free-form ``additionalProperties``
          object with no declared ``properties``;
        * ``type: array`` → :attr:`TypeKind.ALIAS` to the list ``TypeRef``;
        * anything else (a constrained scalar) → :attr:`TypeKind.SCALAR`.

        Args:
            name: The type's source name (also its stable key, via :meth:`Keys.type`).
            schema: The named schema fragment.

        Returns:
            The coerced :class:`Type`. Member fields/values recurse through
            :meth:`type_ref`, so nested ``$ref``s become references by key.
        """
        from .canonical_model import EnumValue  # local: avoid cycle

        key = Keys.type(name)
        description = schema.get("description")
        deprecated = bool(schema.get("deprecated", False))
        composition = schema.get("oneOf") or schema.get("anyOf")

        # UNION — oneOf/anyOf of (mostly) named refs.
        if isinstance(composition, list) and composition:
            members = [
                self.ref_name(m["$ref"])
                for m in composition
                if isinstance(m, dict) and isinstance(m.get("$ref"), str)
            ]
            return Type(
                key=key,
                name=name,
                kind=TypeKind.UNION,
                description=description,
                deprecated=deprecated,
                union_members=members,
            )

        primary = self._primary_type(schema)

        # ENUM — an enumerated scalar.
        if "enum" in schema and primary in _SCALAR_TYPES:
            values = [
                EnumValue(key=Keys.enum_value(key, str(v)), name=str(v), value=v)
                for v in schema["enum"]
            ]
            return Type(
                key=key,
                name=name,
                kind=TypeKind.ENUM,
                description=description,
                deprecated=deprecated,
                enum_values=values,
            )

        properties = schema.get("properties")
        additional = schema.get("additionalProperties")

        # RECORD — an object with declared properties.
        if primary == "object" or isinstance(properties, dict):
            if not properties and isinstance(additional, dict):
                # MAP — free-form object keyed by string with a uniform value type.
                return Type(
                    key=key,
                    name=name,
                    kind=TypeKind.MAP,
                    description=description,
                    deprecated=deprecated,
                    key_type=TypeRef(name="string", nullable=False),
                    value_type=self.type_ref(additional, required=True),
                )
            required = set(schema.get("required", []) or [])
            fields = [
                self._field(key, prop_name, prop_schema, prop_name in required)
                for prop_name, prop_schema in (properties or {}).items()
                if isinstance(prop_schema, dict)
            ]
            return Type(
                key=key,
                name=name,
                kind=TypeKind.RECORD,
                description=description,
                deprecated=deprecated,
                fields=fields,
            )

        # ALIAS — a named array type defers to its element via a list TypeRef.
        if primary == "array":
            return Type(
                key=key,
                name=name,
                kind=TypeKind.ALIAS,
                description=description,
                deprecated=deprecated,
                aliased=self.type_ref(schema, required=True),
            )

        # SCALAR — a leaf, possibly with constraints (pattern/format/…).
        return Type(
            key=key,
            name=name,
            kind=TypeKind.SCALAR,
            description=description,
            deprecated=deprecated,
            constraints=coerce_constraints(schema),
        )

    def _field(
        self, type_key: str, name: str, schema: Dict[str, Any], required: bool
    ) -> Any:
        """Coerce one object property into a :class:`CanonicalField`."""
        from .canonical_model import CanonicalField  # local: avoid cycle

        return CanonicalField(
            key=Keys.field(type_key, name),
            name=name,
            type=self.type_ref(schema, required=required),
            default=schema.get("default"),
            constraints=coerce_constraints(schema),
            description=schema.get("description"),
            deprecated=bool(schema.get("deprecated", False)),
        )


# ===========================================================================
# Ordering normalization
# ===========================================================================


def normalize_ordering(api: CanonicalApi) -> CanonicalApi:
    """Return ``api`` with its identity-keyed collections sorted deterministically.

    Sorting the collections whose order is *not* semantically meaningful — they
    are keyed by a stable ``key`` — makes the serialized model (and therefore its
    fingerprint and diff) invariant to the source's declaration order: two
    imports of the same API, however the source orders its paths/schemas, produce
    byte-identical output. Collections whose order *is* meaningful are left as-is:

    * ``enum_values`` (protobuf/IDL ordinal can be load-bearing),
    * ``union_members`` (Avro union resolution order),
    * ``Server.variables`` and a server's enum lists,
    * the contents of ``raw``/``extras`` (opaque fidelity bags).

    The sort is non-mutating: a deep copy is returned so the caller's input is
    untouched.

    Args:
        api: The canonical model to order.

    Returns:
        A new :class:`CanonicalApi` with services, operations, parameters,
        messages, message headers, channels, types, and type fields sorted by
        ``key`` (channels and types stable-sorted by ``key``).
    """
    ordered = api.model_copy(deep=True)

    ordered.services.sort(key=lambda s: s.key)
    for service in ordered.services:
        service.operations.sort(key=lambda o: o.key)
        for op in service.operations:
            op.parameters.sort(key=lambda p: p.key)
            op.messages.sort(key=lambda m: m.key)
            for msg in op.messages:
                msg.headers.sort(key=lambda h: h.key)

    ordered.channels.sort(key=lambda c: c.key)
    for channel in ordered.channels:
        channel.parameters.sort(key=lambda p: p.key)

    ordered.types.sort(key=lambda t: t.key)
    for type_ in ordered.types:
        type_.fields.sort(key=lambda f: f.key)

    return ordered
