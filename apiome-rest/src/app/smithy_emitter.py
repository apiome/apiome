"""Smithy emitter: canonical model → Smithy 2.0 JSON AST and ``.smithy`` IDL — MFX-20.1 (#3914).

The inverse of :class:`app.smithy_normalizer.SmithyNormalizer` and an implementation of the
:class:`app.emitter.Emitter` SPI. The writer builds the model once, as a Smithy **JSON AST**
(every shape keyed by its absolute id, every trait by its absolute id), and renders the ``.smithy``
IDL from that same AST — so the two outputs (option ``output``) always describe one model:

* ``RECORD`` → ``structure``; ``UNION`` → ``union`` (one member per field or member type);
  ``ENUM`` → ``enum`` (``= "value"`` when the wire value differs from the member name); ``MAP`` →
  ``map``; a named list → ``list``; aliases of scalars and named scalars → simple shapes
  (``string AccountId``); an anonymous list → a synthesized ``<Element>List`` shape.
* Nullability → ``@required`` on non-nullable structure members, a field default → ``@default``.
* Constraints → constraint traits on the shapes they may target: ``@length`` (strings, blobs, lists,
  maps), ``@range`` (numbers), ``@pattern`` (strings), ``@uniqueItems`` (lists).
* Descriptions → doc comments (``documentation`` trait); ``deprecated`` → ``@deprecated``; a member
  renamed to a Smithy identifier keeps its wire name with ``@jsonName``.
* Services → ``service`` shapes, operations → ``operation`` shapes. An HTTP operation gets the
  prelude protocol-binding traits — ``@http(method, uri, code)`` with ``@httpLabel`` /
  ``@httpQuery`` / ``@httpHeader`` / ``@httpPayload`` members, ``@readonly`` / ``@idempotent`` from its
  method — and a record only ever returned as an error becomes an ``@error`` structure (with
  ``@httpError`` for an HTTP status) in the operation's ``errors``. Option ``protocol`` adds a
  service protocol trait (``aws.protocols#restJson1``, ``smithy.protocols#rpcv2Cbor``).

What makes the model valid for ``smithy validate``: shape and member names are Smithy identifiers,
unique case-insensitively (shapes also unlike a prelude shape); every member targets a shape;
constraint traits only land on shapes they apply to; a cycle of ``@required`` structure members has
one ``@required`` dropped; GET / HEAD / DELETE operations carry no body; HTTP URIs are well-formed
and unique per method. Whatever cannot be carried is reported as a :class:`~app.emitter.Loss`.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Literal, Optional, Set, Tuple, Union

from pydantic import Field

from .canonical_model import (
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Constraints,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    ParameterLocation,
    Service,
    StreamingMode,
    Type,
    TypeKind,
    TypeRef,
)
from .emitter import (
    CapabilityProfile,
    EmitOptions,
    EmitPreconditionError,
    EmitResult,
    EmittedFile,
    Emitter,
    LossKind,
    LossTracker,
    Provenance,
    ProvenanceTracker,
)
from .fidelity_rulepack import CapabilityRulePack, FidelityVerdict, _has_any_constraint
from .lossiness import LossinessKind, LossinessReport
from .scalar_aliases import SMITHY_SCALAR_FOR_KIND, target_scalar

__all__ = ["SMITHY_PRELUDE", "SmithyEmitOptions", "SmithyEmitter", "SmithyFidelityRulePack", "smithy_identifier"]

#: Prelude shape → its simple-shape keyword. A shape of the model may not take one of these names
#: (an IDL reference ``String`` would then resolve to it instead of the prelude).
SMITHY_PRELUDE: Dict[str, str] = {
    "String": "string",
    "Blob": "blob",
    "Boolean": "boolean",
    "Byte": "byte",
    "Short": "short",
    "Integer": "integer",
    "Long": "long",
    "Float": "float",
    "Double": "double",
    "BigInteger": "bigInteger",
    "BigDecimal": "bigDecimal",
    "Timestamp": "timestamp",
    "Document": "document",
    "Unit": "structure",
}

#: Canonical scalar spellings the shared kind table does not cover.
_EXTRA_SCALARS: Dict[str, str] = {
    "datetime": "Timestamp",
    "date-time": "Timestamp",
    "timestamp": "Timestamp",
    "decimal": "BigDecimal",
    "bigdecimal": "BigDecimal",
    "biginteger": "BigInteger",
    "object": "Document",
    "any": "Document",
    "json": "Document",
    "map": "Document",
    "dict": "Document",
    "document": "Document",
    "void": "Unit",
    "null": "Unit",
}

#: Spellings that are text without loss (formats Smithy has no shape for).
_STRING_LIKE = frozenset({"uuid", "date", "time", "duration", "uri", "url", "email", "char", "hostname", "ipv4",
                          "ipv6"})

_NUMERIC = frozenset({"byte", "short", "integer", "long", "float", "double", "bigInteger", "bigDecimal"})
_INTEGRAL = frozenset({"byte", "short", "integer", "long", "bigInteger"})
_LENGTH_TARGETS = frozenset({"string", "blob", "list", "map"})
#: Shapes ``@httpPayload`` may target (a list, map or number cannot be a payload).
_PAYLOAD_TARGETS = frozenset({"structure", "union", "string", "blob", "enum", "document"})
#: Simple shapes an ``@httpQuery`` / ``@httpHeader`` / ``@httpLabel`` member may target.
_SIMPLE = frozenset({"string", "boolean", "byte", "short", "integer", "long", "float", "double", "bigInteger",
                     "bigDecimal", "timestamp", "enum"})
#: Headers Smithy will not bind (``HttpHeaderTrait`` — they belong to the transport), lower-cased.
_RESERVED_HEADERS = frozenset({
    "authorization", "connection", "content-length", "expect", "host", "max-forwards", "proxy-authenticate",
    "server", "te", "trailer", "transfer-encoding", "upgrade", "user-agent", "www-authenticate", "x-forwarded-for",
})
#: Methods whose request carries no payload (``HttpMethodSemantics``).
_NO_BODY_METHODS = frozenset({"GET", "HEAD", "DELETE", "OPTIONS", "TRACE"})

#: Service protocol traits (option ``protocol``) → their absolute trait id.
_PROTOCOLS = {"restJson1": "aws.protocols#restJson1", "rpcv2Cbor": "smithy.protocols#rpcv2Cbor"}

_EVENT_OPERATION_KINDS = frozenset({OperationKind.PUBLISH, OperationKind.SUBSCRIBE})
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class SmithyFidelityRulePack(CapabilityRulePack):
    """Fidelity rules for Smithy export.

    Beyond the capability defaults, it predicts what the writer renames (a name that is not a Smithy
    identifier, MFX-20.1) and that agent descriptors are not written. A Smithy source's names are already
    identifiers. Trait coverage and protocol-binding gaps are refined by the Smithy fidelity pack (MFX-20.2).
    """

    target_label = "Smithy"

    def evaluate(self, api: CanonicalApi) -> LossinessReport:
        """Note whether the model came from Smithy (its names are already identifiers)."""
        self._smithy_source = api.format == "smithy"
        return super().evaluate(api)

    def _renamed(self, name: Optional[str]) -> bool:
        return not getattr(self, "_smithy_source", True) and smithy_identifier(name) != (name or "")

    def _rename_verdict(self, what: str, name: str) -> FidelityVerdict:
        return FidelityVerdict.approx(
            message=f"{self.target_label} {what} names are identifiers; {name!r} is written as "
            f"{smithy_identifier(name)!r}",
            target_mapping=f"{what} → renamed",
        )

    def root_verdicts(self, api: CanonicalApi) -> List[FidelityVerdict]:
        """Agent descriptors have no Smithy form."""
        if not api.agents:
            return []
        return [FidelityVerdict.drop(
            message=f"{self.target_label} has no agent descriptors; {len(api.agents)} agent(s) are not written",
            target_mapping="agents → dropped",
        )]

    def type_verdict(self, type_: Type) -> FidelityVerdict:
        verdict = super().type_verdict(type_)
        if verdict.kind is LossinessKind.OK and self._renamed(type_.name):
            return self._rename_verdict("shape", type_.name)
        return verdict

    def field_verdicts(self, field: CanonicalField) -> List[FidelityVerdict]:
        """The capability verdicts, plus an ``APPROX`` when the writer renames the member."""
        verdicts = super().field_verdicts(field)
        if self._renamed(field.name):
            verdicts.append(self._rename_verdict("member", field.name))
        return verdicts

    def operation_verdict(self, operation: Operation) -> FidelityVerdict:
        if (
            operation.kind not in _EVENT_OPERATION_KINDS
            and not (operation.http_method or operation.http_path)
            and self._renamed(operation.name)
        ):
            return self._rename_verdict("operation", operation.name)
        if operation.kind in _EVENT_OPERATION_KINDS:
            return FidelityVerdict.drop(
                message=f"{self.target_label} has no event vocabulary; "
                f"{operation.kind.value} operation {operation.key!r} is dropped",
                target_mapping="event operation → dropped",
            )
        if operation.http_method or operation.http_path:
            return FidelityVerdict.approx(
                message=f"{self.target_label} has no HTTP binding; reframing "
                f"{operation.key!r} as an RPC operation",
                target_mapping="HTTP operation → RPC operation",
            )
        return super().operation_verdict(operation)

    def field_verdict(self, field: CanonicalField) -> Optional[FidelityVerdict]:
        if _has_any_constraint(field.constraints):
            return FidelityVerdict.approx(
                message=f"{self.target_label} cannot enforce validation constraints; "
                f"{field.key!r} is approximated without facets",
                target_mapping="constraints → dropped",
            )
        return super().field_verdict(field)


class SmithyEmitOptions(EmitOptions):
    """Per-target options for :class:`SmithyEmitter`."""

    smithy_version: str = Field(default="2.0", description="Smithy `$version` control value.")
    include_comments: bool = Field(
        default=True,
        description="Emit brief generated-file header comments.",
    )
    output: Literal["idl", "json-ast", "both"] = Field(
        default="idl",
        description="`idl` writes `<Name>.smithy`; `json-ast` writes the Smithy JSON AST (`<Name>.json`); `both` "
        "writes the two — two views of one model, not files to load together.",
    )
    protocol: Literal["none", "restJson1", "rpcv2Cbor"] = Field(
        default="none",
        description="Protocol trait applied to each service: `restJson1` (aws.protocols) or `rpcv2Cbor` "
        "(smithy.protocols). Validating either needs its trait package (or `--allow-unknown-traits`).",
    )


class SmithyEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as a Smithy 2.0 model (IDL and / or JSON AST)."""

    key = "smithy"
    format = "smithy"
    label = "Smithy"
    description = "Export as a Smithy 2.0 model (.smithy IDL and / or JSON AST)."
    icon = "hammer"
    paradigm = ApiParadigm.RPC
    multi_file = False
    options_model = SmithyEmitOptions

    OUTPUT_MEDIA_TYPE = "text/plain"
    AST_MEDIA_TYPE = "application/json"

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        return CapabilityProfile(
            operations=True,
            events=False,
            unions=True,
            nullability=True,
            field_identity=False,
        )

    @classmethod
    def fidelity_rule_pack(cls) -> Optional[type[CapabilityRulePack]]:
        return SmithyFidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[SmithyEmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        options = (
            opts
            if isinstance(opts, SmithyEmitOptions)
            else SmithyEmitOptions.model_validate(opts.model_dump() if opts else {})
        )
        writer = _SmithyWriter(api, options)
        writer.build()
        if not writer.has_shapes():
            raise EmitPreconditionError(
                "Smithy export needs at least one type or service to declare; this source has neither."
            )
        files: List[EmittedFile] = []
        if options.output in ("idl", "both"):
            files.append(EmittedFile(path=f"{writer.base_name}.smithy", content=writer.render_idl(),
                                     media_type=self.OUTPUT_MEDIA_TYPE))
        if options.output in ("json-ast", "both"):
            files.append(EmittedFile(path=f"{writer.base_name}.json",
                                     content=json.dumps(writer.ast(), indent=2) + "\n",
                                     media_type=self.AST_MEDIA_TYPE))
        return EmitResult(
            files=files,
            media_type=files[0].media_type,
            provenance=writer.tracker.records(),
            losses=writer.losses.records(),
        )


# ===========================================================================
# Identifiers
# ===========================================================================


def smithy_identifier(name: Optional[str], fallback: str = "Shape") -> str:
    """A Smithy identifier: ASCII letters, digits and ``_``, starting with a letter.

    Args:
        name: The source name (``com.acme.Order``, ``order-id``, ``1st``).
        fallback: Used when nothing of the name survives; must itself be an identifier.

    Returns:
        The identifier (``com_acme_Order``, ``order_id``, ``n1st``).
    """
    ident = re.sub(r"[^A-Za-z0-9_]+", "_", name or "").strip("_") or fallback
    if ident[0].isdigit():
        ident = f"n{ident}"
    return ident


class _Scope:
    """Names declared in one Smithy scope (the namespace's shapes, a shape's members), unique ignoring case."""

    def __init__(self, reserved: Optional[Set[str]] = None) -> None:
        self._taken: Set[str] = {name.lower() for name in reserved or ()}

    def claim(self, name: Optional[str], fallback: str = "Shape") -> str:
        """The identifier for ``name`` here, suffixed ``2``, ``3`` … when already taken."""
        base = smithy_identifier(name, fallback)
        candidate, suffix = base, 2
        while candidate.lower() in self._taken:
            candidate, suffix = f"{base}{suffix}", suffix + 1
        self._taken.add(candidate.lower())
        return candidate


def _capitalized(name: str) -> str:
    return name[:1].upper() + name[1:]


# ===========================================================================
# Writer
# ===========================================================================


class _SmithyWriter:
    """Build the Smithy model as a JSON AST, then render it (see the module docstring)."""

    def __init__(self, api: CanonicalApi, options: SmithyEmitOptions) -> None:
        self._api = api
        self._options = options
        self._smithy_source = api.format == "smithy"
        self.tracker = ProvenanceTracker()
        self.losses = LossTracker()
        self.namespace = _namespace(api)
        self.base_name = _base_name(api)
        self._types_by_key = {t.key: t for t in api.types}
        self._types_by_name: Dict[str, Type] = {}
        for type_ in api.types:
            self._types_by_name.setdefault(type_.name, type_)
        self._shapes_scope = _Scope(set(SMITHY_PRELUDE))
        #: Local shape name → AST shape node, in declaration order.
        self._shapes: Dict[str, Dict[str, Any]] = {}
        #: Local shape name → its Smithy type (``structure``, ``string`` …), known before it is built.
        self._kinds: Dict[str, str] = {}
        self._names: Dict[str, str] = {}
        self._list_shapes: Dict[str, str] = {}
        self._enum_values: Dict[str, Set[str]] = {}

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(self) -> None:
        """Claim every name, then build the type shapes, the operations and the services."""
        for type_ in self._api.types:
            kind = self._shape_kind_of(type_)
            if kind is None:
                continue
            name = self._shapes_scope.claim(type_.name, "Shape")
            self._names[type_.key] = name
            self._kinds[name] = kind
            if name != type_.name:
                self.losses.record(
                    LossKind.INFERRED,
                    "renamed-shape",
                    f"Smithy shape names are identifiers unique (ignoring case) in the namespace and unlike a "
                    f"prelude shape; {type_.name!r} is written as {name!r}.",
                    pointer=type_.key,
                )
        self._service_names = {svc.key: self._shapes_scope.claim(svc.name, "Service") for svc in self._api.services}
        self._errors = self._error_types()

        for type_ in self._api.types:
            if type_.key in self._names:
                self._build_type(type_)
        self._operation_names: Dict[str, str] = {}
        self._http_routes: Set[Tuple[str, str]] = set()
        for service in self._api.services:
            self._build_service(service)
        self._break_required_cycles()

        if self._api.channels:
            self.losses.record(LossKind.NA, "channels-dropped", "Smithy export omits event/channel constructs",
                               pointer="channels")

    def _shape_kind_of(self, type_: Type) -> Optional[str]:
        """The Smithy shape a type becomes, or ``None`` when it is written inline (an alias of a named type)."""
        smithy_kind = type_.extras.get("smithy_kind")
        if smithy_kind == "resource":
            self.losses.record(
                LossKind.NA,
                "resource-dropped",
                f"The Smithy resource {type_.key!r} was imported as a record of its lifecycle bindings, which "
                "cannot be written back; its operations stay on the service.",
                pointer=type_.key,
            )
            return None
        if type_.kind is TypeKind.ENUM or smithy_kind == "enum":
            return "enum" if type_.enum_values else "string"
        if type_.kind is TypeKind.MAP or smithy_kind == "map":
            return "map"
        if type_.kind is TypeKind.UNION:
            return "union" if (type_.fields or type_.union_members) else "document"
        if type_.kind is TypeKind.RECORD:
            return "structure"
        if type_.kind is TypeKind.ALIAS and type_.aliased is not None:
            if type_.aliased.item is not None:
                return "list"
            if self._lookup(type_.aliased.name) is not None:
                return None
            return SMITHY_PRELUDE.get(self._scalar(type_.aliased.name, record=False), "string")
        if type_.kind in (TypeKind.SCALAR, TypeKind.ALIAS):
            return SMITHY_PRELUDE.get(self._scalar(type_.name, record=False), "string")
        self.losses.record(
            LossKind.NA,
            "unsupported-type",
            f"Type {type_.key!r} ({type_.kind.value}) has no Smithy representation and is skipped",
            pointer=type_.key,
        )
        return None

    def _lookup(self, name: Optional[str]) -> Optional[Type]:
        if not name:
            return None
        return self._types_by_key.get(name) or self._types_by_name.get(name)

    def _type_key(self, ref: Optional[TypeRef]) -> Optional[str]:
        target = self._lookup(ref.name) if ref is not None and ref.item is None else None
        return target.key if target is not None else None

    def _error_types(self) -> Set[str]:
        """Keys of the records written as ``@error`` structures: only ever returned as an error."""
        thrown: Set[str] = set()
        used: Set[str] = set()
        for operation in self._api.operations():
            for message in operation.messages:
                key = self._type_key(message.payload)
                if key is not None:
                    (thrown if message.role is MessageRole.ERROR else used).add(key)
            for param in operation.parameters:
                key = self._type_key(param.type)
                if key is not None:
                    used.add(key)
        for type_ in self._api.types:
            refs = [field.type for field in type_.fields] + [type_.aliased, type_.key_type, type_.value_type]
            for ref in refs:
                while ref is not None and ref.item is not None:
                    ref = ref.item
                key = self._type_key(ref)
                if key is not None:
                    used.add(key)
            for member in type_.union_members:
                target = self._lookup(member)
                if target is not None:
                    used.add(target.key)
        return {key for key in thrown - used if self._types_by_key[key].kind is TypeKind.RECORD
                and key in self._names}

    # ------------------------------------------------------------------
    # Type references
    # ------------------------------------------------------------------

    def _target(self, ref: Optional[TypeRef], fmt: Optional[str] = None, *, depth: int = 0) -> str:
        """The shape a reference targets: a local shape name or a prelude shape (``String``).

        Args:
            ref: The canonical reference (a list, a scalar or a named type).
            fmt: The ``format`` constraint, which picks the width of ``integer`` / ``number``.
            depth: Alias-resolution depth (guards an alias cycle).

        Returns:
            The shape name; an anonymous list gets a synthesized ``<Element>List`` shape.
        """
        if ref is None:
            return "Unit"
        if ref.item is not None:
            return self._list_shape(self._target(ref.item, fmt, depth=depth))
        target = self._lookup(ref.name)
        if target is None:
            return self._scalar(ref.name, fmt)
        if target.key in self._names:
            return self._names[target.key]
        if target.kind is TypeKind.ALIAS and target.aliased is not None and depth < 8:
            self.losses.record(
                LossKind.INFERRED,
                "alias-inlined",
                f"Smithy has no alias of a named shape; references to {target.key!r} target its aliased type.",
                pointer=target.key,
            )
            return self._target(target.aliased, fmt, depth=depth + 1)
        return "Document"

    def _scalar(self, name: Optional[str], fmt: Optional[str] = None, *, record: bool = True) -> str:
        """The prelude shape for a canonical scalar spelling; anything unknown is ``String``."""
        if not name:
            return "String"
        if name in SMITHY_PRELUDE:
            return name
        mapped = target_scalar(name, SMITHY_SCALAR_FOR_KIND, fmt) or _EXTRA_SCALARS.get(name.lower())
        if mapped is not None:
            return mapped
        if name.lower() not in _STRING_LIKE and record:
            self.losses.record(LossKind.INFERRED, "unknown-type",
                               f"The type {name!r} has no Smithy equivalent; it is written as a String.")
        return "String"

    def _kind(self, target: str) -> str:
        """The Smithy type of a target shape (``structure``, ``string``, ``list`` …)."""
        return self._kinds.get(target) or SMITHY_PRELUDE.get(target, "string")

    def _list_shape(self, member: str, *, unique: bool = False) -> str:
        """A synthesized ``list`` shape of ``member`` (one per element shape); ``unique`` gives the
        ``@uniqueItems`` variant, ``<Element>Set`` (the trait goes on a list shape, never on a member)."""
        member = "Document" if member == "Unit" else member
        key = f"{member}|set" if unique else member
        name = self._list_shapes.get(key)
        if name is None:
            name = self._shapes_scope.claim(f"{_capitalized(member)}{'Set' if unique else 'List'}", "List")
            self._list_shapes[key] = name
            self._kinds[name] = "list"
            self._shapes[name] = {"type": "list", "member": {"target": member}}
            if unique:
                self._shapes[name]["traits"] = {"uniqueItems": {}}
        return name

    def _unique_target(self, target: str, traits: Dict[str, Any], pointer: str) -> str:
        """Move a member's ``@uniqueItems`` onto the list it targets (a ``<Element>Set``)."""
        if "uniqueItems" not in traits:
            return target
        del traits["uniqueItems"]
        element = self._shapes.get(target, {}).get("member", {}).get("target")
        if element is None or self._kind(element) in ("float", "double", "document", "union"):
            self.losses.record(LossKind.NA, "constraint-dropped",
                               f"Smithy has no unique list of {element or target}; uniqueItems is not written for "
                               f"{pointer!r}.", pointer=pointer)
            return target
        return self._list_shape(element, unique=True)

    # ------------------------------------------------------------------
    # Type shapes
    # ------------------------------------------------------------------

    def _build_type(self, type_: Type) -> None:
        name = self._names[type_.key]
        kind = self._kinds[name]
        traits = self._common_traits(type_.description, type_.deprecated)
        if kind == "enum":
            shape = self._enum_shape(type_)
        elif kind == "list":
            fmt = type_.constraints.format if type_.constraints is not None else None
            member = self._target(type_.aliased.item, fmt)
            shape = {"type": "list", "member": {"target": "Document" if member == "Unit" else member}}
        elif kind == "map":
            shape = self._map_shape(type_)
        elif kind == "structure":
            shape = self._structure_shape(type_, union=False)
            if type_.key in self._errors:
                traits["error"] = "client"
                self.losses.record(
                    LossKind.INFERRED,
                    "structure-as-error",
                    f"{type_.key!r} is only returned as an error, so it is written as an @error structure.",
                    pointer=type_.key,
                )
        elif kind == "union":
            shape = self._structure_shape(type_, union=True)
        else:
            shape = {"type": kind}
            if type_.kind in (TypeKind.UNION, TypeKind.ENUM):
                self.losses.record(
                    LossKind.INFERRED,
                    "empty-shape",
                    f"{type_.key!r} has no members; it is written as a {kind} shape.",
                    pointer=type_.key,
                )
            elif type_.kind is TypeKind.SCALAR and _is_custom_scalar(type_.name):
                self.losses.record(LossKind.INFERRED, "custom-scalar",
                                   f"Smithy has no custom scalars; {type_.key!r} is a string shape.",
                                   pointer=type_.key)
        traits.update(self._constraint_traits(type_.constraints, kind, type_.key))
        if "uniqueItems" in traits and self._kind(shape["member"]["target"]) in ("float", "double", "document",
                                                                                "union"):
            del traits["uniqueItems"]
            self.losses.record(LossKind.NA, "constraint-dropped",
                               f"Smithy has no unique list of {shape['member']['target']}; uniqueItems is not "
                               f"written for {type_.key!r}.", pointer=type_.key)
        if traits:
            shape["traits"] = traits
        self._shapes[name] = shape
        self.tracker.record(type_.key, Provenance.SOURCE)

    def _common_traits(self, description: Optional[str], deprecated: bool) -> Dict[str, Any]:
        traits: Dict[str, Any] = {}
        if description and description.strip():
            traits["documentation"] = description.strip()
        if deprecated:
            traits["deprecated"] = {}
        return traits

    def _enum_shape(self, type_: Type) -> Dict[str, Any]:
        scope = _Scope()
        members: Dict[str, Any] = {}
        values: Set[str] = set()
        for value in type_.enum_values:
            member = scope.claim(value.name, "VALUE")
            wire = value.value if isinstance(value.value, str) else value.name
            node: Dict[str, Any] = {"target": "Unit"}
            traits = self._common_traits(value.description, value.deprecated)
            if wire != member:
                traits["enumValue"] = wire
            if member != value.name:
                self.losses.record(
                    LossKind.INFERRED,
                    "renamed-enum-member",
                    f"Smithy enum members are identifiers; {value.name!r} of {type_.key!r} is written as {member!r} "
                    f"with the value {wire!r}.",
                    pointer=value.key,
                )
            if traits:
                node["traits"] = traits
            members[member] = node
            values.add(wire)
        self._enum_values[self._names[type_.key]] = values
        return {"type": "enum", "members": members}

    def _map_shape(self, type_: Type) -> Dict[str, Any]:
        key = self._target(type_.key_type or TypeRef(name="string"))
        if self._kind(key) not in ("string", "enum"):
            self.losses.record(
                LossKind.INFERRED,
                "map-key-as-string",
                f"Smithy map keys are strings; the key of {type_.key!r} ({key}) is written as a String.",
                pointer=type_.key,
            )
            key = "String"
        value = self._target(type_.value_type or TypeRef(name="Document"))
        return {"type": "map", "key": {"target": key}, "value": {"target": "Document" if value == "Unit" else value}}

    def _ordered_fields(self, type_: Type) -> List[CanonicalField]:
        indexed = list(enumerate(type_.fields))
        indexed.sort(key=lambda pair: (pair[1].field_number is None, pair[1].field_number or 0, pair[0]))
        return [field for _, field in indexed]

    def _structure_shape(self, type_: Type, *, union: bool) -> Dict[str, Any]:
        scope = _Scope()
        members: Dict[str, Any] = {}
        if type_.fields or not union:
            for field in self._ordered_fields(type_):
                name = scope.claim(field.name, "member")
                members[name] = self._member(field, name, union=union)
        else:
            for member in type_.union_members:
                target = self._target(TypeRef(name=member))
                name = scope.claim(target[:1].lower() + target[1:], "member")
                members[name] = {"target": target}
            self.losses.record(
                LossKind.INFERRED,
                "union-member-names",
                f"The members of union {type_.key!r} are named after their shapes.",
                pointer=type_.key,
            )
        _dedupe_json_names(members)
        return {"type": "union" if union else "structure", "members": members}

    def _member(self, field: CanonicalField, name: str, *, union: bool) -> Dict[str, Any]:
        """One structure / union member: its target and traits."""
        fmt = field.constraints.format if field.constraints is not None else None
        target = self._target(field.type, fmt)
        if target == "Unit" and not union:
            # Only a union member may target Unit (``UnitType``): a null-only field holds a document.
            self.losses.record(LossKind.INFERRED, "null-as-document",
                               f"{field.key!r} holds only null; it is written as a Document member.",
                               pointer=field.key)
            target = "Document"
        traits = self._common_traits(field.description, field.deprecated)
        if name != field.name:
            self.losses.record(
                LossKind.INFERRED,
                "renamed-member",
                f"Smithy member names are identifiers unique (ignoring case) in their shape; {field.name!r} is "
                f"written as {name!r} with @jsonName keeping its wire name.",
                pointer=field.key,
            )
            traits["jsonName"] = field.name
        traits.update(self._constraint_traits(field.constraints, self._kind(target), field.key))
        target = self._unique_target(target, traits, field.key)
        self._source_traits(field, traits)
        if not union:
            default = self._default(field, target)
            if default is not _NO_DEFAULT:
                traits["default"] = default
            if not field.type.nullable:
                traits["required"] = {}
        node: Dict[str, Any] = {"target": target}
        if traits:
            node["traits"] = traits
        self.tracker.record(field.key, Provenance.SOURCE)
        return node

    def _source_traits(self, field: CanonicalField, traits: Dict[str, Any]) -> None:
        """A Smithy source's member traits: the importer kept their names only, so the ones that need a
        value (``@length``, ``@pattern`` …) cannot be written back."""
        names = field.extras.get("smithy_traits") if self._smithy_source else None
        for trait in names or []:
            if trait in ("required", "deprecated") or trait in traits:
                if trait == "deprecated":
                    traits["deprecated"] = {}
                continue
            self.losses.record(
                LossKind.NA,
                "trait-value-unknown",
                f"The @{trait} trait of {field.key!r} was imported without its value, so it is not written.",
                pointer=field.key,
            )

    def _default(self, field: CanonicalField, target: str) -> Any:
        """The ``@default`` value for a member, or :data:`_NO_DEFAULT` when there is none it can carry."""
        value = field.default
        if value is None:
            return _NO_DEFAULT
        kind = self._kind(target)
        ok = (
            (kind == "string" and isinstance(value, str))
            or (kind == "enum" and isinstance(value, str) and value in self._enum_values.get(target, set()))
            or (kind == "boolean" and isinstance(value, bool))
            or (kind in _INTEGRAL and isinstance(value, int) and not isinstance(value, bool))
            or (kind in _NUMERIC - _INTEGRAL and isinstance(value, (int, float)) and not isinstance(value, bool))
            or (kind == "list" and value == [])
            or (kind == "map" and value == {})
            or kind == "document"
        )
        if ok:
            return value
        self.losses.record(
            LossKind.NA,
            "default-dropped",
            f"The default {value!r} of {field.key!r} does not fit its Smithy target ({target}); it is not written.",
            pointer=field.key,
        )
        return _NO_DEFAULT

    def _constraint_traits(self, constraints: Optional[Constraints], kind: str, pointer: str) -> Dict[str, Any]:
        """Constraint traits for a shape of ``kind``; constraints that do not apply to it are reported."""
        traits: Dict[str, Any] = {}
        if constraints is None:
            return traits
        dropped: List[str] = []
        length: Dict[str, int] = {}
        low = constraints.min_items if kind in ("list", "map") else constraints.min_length
        high = constraints.max_items if kind in ("list", "map") else constraints.max_length
        if (low is not None or high is not None) and kind in _LENGTH_TARGETS:
            if low is not None:
                length["min"] = int(low)
            if high is not None:
                length["max"] = int(high)
            traits["length"] = length
        elif low is not None or high is not None:
            dropped.append("length")
        if kind in _NUMERIC:
            bounds: Dict[str, Any] = {}
            for key, plain, exclusive, step in (("min", constraints.minimum, constraints.exclusive_minimum, 1),
                                                ("max", constraints.maximum, constraints.exclusive_maximum, -1)):
                if plain is not None:
                    bounds[key] = _number(plain)
                elif exclusive is not None and kind in _INTEGRAL and float(exclusive).is_integer():
                    bounds[key] = int(exclusive) + step
                elif exclusive is not None:
                    bounds[key] = _number(exclusive)
                    dropped.append(f"exclusive {key}imum (written inclusive)")
            if bounds:
                traits["range"] = bounds
        elif any(v is not None for v in (constraints.minimum, constraints.maximum, constraints.exclusive_minimum,
                                         constraints.exclusive_maximum)):
            dropped.append("range")
        if constraints.pattern:
            if kind == "string":
                traits["pattern"] = constraints.pattern
            else:
                dropped.append("pattern")
        if constraints.unique_items:
            if kind == "list":
                traits["uniqueItems"] = {}
            else:
                dropped.append("uniqueItems")
        if constraints.multiple_of is not None:
            dropped.append("multipleOf")
        if constraints.enum:
            dropped.append("enum")
        if dropped:
            self.losses.record(
                LossKind.NA,
                "constraint-dropped",
                f"Smithy has no trait for {', '.join(dropped)} on a {kind}; it is not written for {pointer!r}.",
                pointer=pointer,
            )
        return traits

    def _break_required_cycles(self) -> None:
        """Drop ``@required`` from one member of each cycle of required structure members (``ShapeRecursion``)."""
        state: Dict[str, int] = {}

        def visit(name: str) -> None:
            state[name] = 1
            for member_name, member in self._shapes[name].get("members", {}).items():
                target = member["target"]
                if "required" not in member.get("traits", {}) or self._kinds.get(target) != "structure":
                    continue
                if state.get(target) == 1:
                    del member["traits"]["required"]
                    if not member["traits"]:
                        del member["traits"]
                    self.losses.record(
                        LossKind.INFERRED,
                        "recursive-member-optional",
                        f"Smithy refuses a cycle of required members; {name}.{member_name} is written optional.",
                        pointer=f"{name}.{member_name}",
                    )
                elif target not in state and target in self._shapes:
                    visit(target)
            state[name] = 2

        for name, shape in list(self._shapes.items()):
            if shape["type"] == "structure" and name not in state:
                visit(name)

    # ------------------------------------------------------------------
    # Services and operations
    # ------------------------------------------------------------------

    def _build_service(self, service: Service) -> None:
        name = self._service_names[service.key]
        operations: List[str] = []
        for operation in service.operations:
            built = self._build_operation(operation)
            if built is not None:
                operations.append(built)
        declared = service.extras.get("smithy_operations") if self._smithy_source else None
        if isinstance(declared, list) and sorted(declared) == sorted(operations):
            # A Smithy source lists its operations in its own order (the import sorts them).
            operations = [str(op) for op in declared]
        shape: Dict[str, Any] = {"type": "service"}
        version = service.extras.get("smithy_version") or self._api.version
        if isinstance(version, str) and version:
            shape["version"] = version
        if operations:
            shape["operations"] = [{"target": op} for op in operations]
        traits = self._common_traits(service.description, False)
        if self._options.protocol != "none":
            traits[_PROTOCOLS[self._options.protocol]] = {}
        if traits:
            shape["traits"] = traits
        self._shapes[name] = shape
        self.tracker.record(service.key, Provenance.SOURCE)

    def _build_operation(self, operation: Operation) -> Optional[str]:
        if operation.kind in _EVENT_OPERATION_KINDS:
            self.losses.record(LossKind.NA, "event-operation-dropped",
                               f"Smithy has no events; {operation.kind.value} operation {operation.key!r} is dropped.",
                               pointer=operation.key)
            return None
        name = self._shapes_scope.claim(operation.name, "Operation")
        if name != operation.name:
            self.losses.record(
                LossKind.INFERRED,
                "renamed-operation",
                f"Smithy operation names are shape names; {operation.name!r} is written as {name!r}.",
                pointer=operation.key,
            )
        if operation.streaming is not StreamingMode.NONE:
            self.losses.record(LossKind.NA, "streaming-dropped",
                               f"Smithy event streams are not written; {operation.key!r} is one call.",
                               pointer=operation.key)
        shape: Dict[str, Any] = {"type": "operation"}
        traits = self._common_traits(operation.description, operation.deprecated)
        http = self._http_binding(operation)
        request = next((m for m in operation.messages if m.role is MessageRole.REQUEST), None)
        response = _success_response(operation)
        input_shape, uri = self._input(operation, name, request, http)
        if input_shape:
            shape["input"] = {"target": input_shape}
        output_shape = self._output(operation, name, response, http)
        if output_shape:
            shape["output"] = {"target": output_shape}
        errors = self._operation_errors(operation)
        if errors:
            shape["errors"] = [{"target": error} for error in errors]
        if http is not None:
            method, _, code = http
            traits["http"] = {"method": method, "uri": uri, "code": code}
            if method in ("GET", "HEAD"):
                traits["readonly"] = {}
            elif method in ("PUT", "DELETE"):
                traits["idempotent"] = {}
        if traits:
            shape["traits"] = traits
        self._operation_names[operation.key] = name
        self._shapes[name] = shape
        self.tracker.record(operation.key, Provenance.SOURCE)
        return name

    def _http_binding(self, operation: Operation) -> Optional[Tuple[str, str, int]]:
        """``(method, uri, code)`` for an HTTP operation whose path Smithy can bind, else ``None``."""
        if not operation.http_method or not operation.http_path:
            return None
        method = operation.http_method.upper()
        path = operation.http_path.split("?", 1)[0] or "/"
        segments = path.split("/")[1:]
        valid = path.startswith("/") and re.fullmatch(r"[A-Za-z]+", method) is not None
        for index, segment in enumerate(segments):
            if not valid:
                break
            if "{" in segment or "}" in segment:
                label = re.fullmatch(r"\{([^{}+]+)(\+?)\}", segment)
                valid = label is not None and (not label.group(2) or index == len(segments) - 1)
            elif segment == "" and index != len(segments) - 1:
                valid = False
        route = (method, re.sub(r"\{[^}]*\}", "{}", path))
        if not valid or route in self._http_routes:
            self.losses.record(
                LossKind.NA,
                "http-binding-dropped",
                f"Smithy cannot bind {method} {operation.http_path!r} of {operation.key!r} "
                f"({'a duplicate route' if valid else 'not a Smithy URI pattern'}); it is written without @http.",
                pointer=operation.key,
            )
            return None
        self._http_routes.add(route)
        response = _success_response(operation)
        status = str(response.status_code if response is not None else "") or ""
        code = int(status) if status.isdigit() and 200 <= int(status) <= 299 else 200
        return method, path, code

    def _input(self, operation: Operation, name: str, request: Optional[Message],
               http: Optional[Tuple[str, str, int]]) -> Tuple[Optional[str], Optional[str]]:
        """The operation's input and its HTTP URI.

        Args:
            operation: The canonical operation.
            name: The operation's shape name.
            request: Its request message, if any.
            http: Its ``(method, uri, code)`` binding, if any.

        Returns:
            ``(input shape, uri)``: a structure payload as is, else a synthesized ``<Operation>Input``
            holding the parameters (bound with ``@httpLabel`` / ``@httpQuery`` / ``@httpHeader``) and the
            body; the URI's labels renamed to the members they bind to.
        """
        body = self._target(request.payload) if request is not None and request.payload is not None else None
        labels = re.findall(r"\{([^}+]+)\+?\}", http[1]) if http else []
        if http is not None and http[0] in _NO_BODY_METHODS and body is not None:
            self.losses.record(LossKind.NA, "body-dropped",
                               f"A {http[0]} request carries no body in Smithy; the body of {operation.key!r} is "
                               "not written.", pointer=operation.key)
            body = None
        uri = http[1] if http else None
        if not operation.parameters and not labels and (body is None or self._kind(body) == "structure"):
            return body, uri
        members: Dict[str, Any] = {}
        scope = _Scope()
        bound_names: Set[str] = set()
        for param in operation.parameters:
            member = scope.claim(param.name, "param")
            fmt = param.constraints.format if param.constraints is not None else None
            target = self._target(param.type, fmt)
            traits = self._common_traits(param.description, param.deprecated)
            traits.update(self._constraint_traits(param.constraints, self._kind(target), param.key))
            target = self._unique_target(target, traits, param.key)
            if http is not None:
                binding = self._param_binding(param.location, param.name, target, bound_names, labels)
                if binding is None:
                    self.losses.record(LossKind.NA, "parameter-dropped",
                                       f"Smithy cannot bind the {param.location.value} parameter {param.key!r}; it is "
                                       "not written.", pointer=param.key)
                    continue
                traits.update(binding)
                if "httpLabel" in binding:
                    uri = re.sub(r"\{" + re.escape(param.name) + r"(\+?)\}", "{" + member + r"\1}", uri)
            if param.required or "httpLabel" in traits:
                traits["required"] = {}
            node: Dict[str, Any] = {"target": target}
            if traits:
                node["traits"] = traits
            members[member] = node
        for label in labels:
            if label not in bound_names:
                member = scope.claim(label, "label")
                members[member] = {"target": "String", "traits": {"httpLabel": {}, "required": {}}}
                uri = re.sub(r"\{" + re.escape(label) + r"(\+?)\}", "{" + member + r"\1}", uri)
        if body is not None:
            member = scope.claim("body")
            node = {"target": body}
            if http is not None:
                if self._kind(body) in _PAYLOAD_TARGETS:
                    node["traits"] = {"httpPayload": {}}
                else:
                    self.losses.record(LossKind.INFERRED, "payload-wrapped",
                                       f"Smithy payloads are structures, unions, strings or blobs; the body of "
                                       f"{operation.key!r} is written as the member 'body' of the request document.",
                                       pointer=operation.key)
            members[member] = node
        input_name = self._shapes_scope.claim(f"{_capitalized(name)}Input", "Input")
        self._kinds[input_name] = "structure"
        self._shapes[input_name] = {"type": "structure", "members": members, "traits": {"input": {}}}
        return input_name, uri

    def _param_binding(self, location: ParameterLocation, name: str, target: str, bound: Set[str],
                       labels: List[str]) -> Optional[Dict[str, Any]]:
        """The HTTP binding trait for a parameter, or ``None`` when Smithy cannot bind it."""
        kind = self._kind(target)
        element = self._kinds.get(target) == "list" and self._kind(self._shapes[target]["member"]["target"]) in _SIMPLE
        if location is ParameterLocation.PATH and name in labels and kind in _SIMPLE:
            bound.add(name)
            return {"httpLabel": {}}
        key = (location.value, name.lower())
        if key in bound or not (kind in _SIMPLE or element):
            return None
        if location is ParameterLocation.QUERY:
            bound.add(key)
            return {"httpQuery": name}
        if location is ParameterLocation.HEADER and _bindable_header(name):
            bound.add(key)
            return {"httpHeader": name}
        return None

    def _output(self, operation: Operation, name: str, response: Optional[Message],
                http: Optional[Tuple[str, str, int]]) -> Optional[str]:
        """The operation's output: a structure payload as is, else a synthesized ``<Operation>Output``."""
        if response is None or response.payload is None:
            return None
        body = self._target(response.payload)
        if self._kind(body) == "structure" and not (http is not None and response.headers):
            return body
        member: Dict[str, Any] = {"target": body}
        if http is not None:
            if self._kind(body) in _PAYLOAD_TARGETS:
                member["traits"] = {"httpPayload": {}}
            else:
                self.losses.record(LossKind.INFERRED, "payload-wrapped",
                                   f"The response of {operation.key!r} is written as the member 'body' of the response "
                                   "document.", pointer=operation.key)
        members: Dict[str, Any] = {"body": member}
        scope = _Scope({"body"})
        for header in response.headers if http is not None else []:
            target = self._target(header.type)
            if self._kind(target) not in _SIMPLE or not _bindable_header(header.name):
                continue
            members[scope.claim(header.name, "header")] = {"target": target, "traits": {"httpHeader": header.name}}
        output_name = self._shapes_scope.claim(f"{_capitalized(name)}Output", "Output")
        self._kinds[output_name] = "structure"
        self._shapes[output_name] = {"type": "structure", "members": members, "traits": {"output": {}}}
        return output_name

    def _operation_errors(self, operation: Operation) -> List[str]:
        """The ``@error`` structures of the operation's error responses; any other error is reported."""
        errors: List[str] = []
        for message in operation.messages:
            if message.role is not MessageRole.ERROR or message.payload is None:
                continue
            key = self._type_key(message.payload)
            if key is None or key not in self._errors:
                self.losses.record(LossKind.NA, "error-dropped",
                                   f"Smithy errors are @error structures; the error response {message.key!r} of "
                                   f"{operation.key!r} is not written.", pointer=operation.key)
                continue
            name = self._names[key]
            status = str(message.status_code or "")
            traits = self._shapes[name].setdefault("traits", {})
            if status.isdigit() and 400 <= int(status) <= 599 and "httpError" not in traits:
                traits["error"] = "server" if int(status) >= 500 else "client"
                traits["httpError"] = int(status)
            if name not in errors:
                errors.append(name)
        return errors

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    def has_shapes(self) -> bool:
        """Whether the model declares any shape."""
        return bool(self._shapes)

    def ast(self) -> Dict[str, Any]:
        """The model as a Smithy JSON AST (absolute shape and trait ids)."""
        return {"smithy": "2.0", "shapes": {self._absolute(name): self._ast_shape(shape)
                                           for name, shape in self._shapes.items()}}

    def _absolute(self, name: str) -> str:
        if name in SMITHY_PRELUDE:
            return f"smithy.api#{name}"
        return f"{self.namespace}#{name}"

    def _trait_id(self, name: str) -> str:
        return name if "#" in name else f"smithy.api#{name}"

    def _ast_shape(self, shape: Dict[str, Any]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for key, value in shape.items():
            if key == "traits":
                out[key] = {self._trait_id(name): trait for name, trait in value.items()}
            elif key == "members":
                out[key] = {name: self._ast_ref(member) for name, member in value.items()}
            elif key in ("member", "key", "value", "input", "output"):
                out[key] = self._ast_ref(value)
            elif key in ("operations", "errors"):
                out[key] = [self._ast_ref(item) for item in value]
            else:
                out[key] = value
        return out

    def _ast_ref(self, ref: Dict[str, Any]) -> Dict[str, Any]:
        out: Dict[str, Any] = {"target": self._absolute(ref["target"])}
        if ref.get("traits"):
            out["traits"] = {self._trait_id(name): trait for name, trait in ref["traits"].items()}
        return out

    def render_idl(self) -> str:
        """The model as Smithy IDL."""
        lines: List[str] = []
        if self._options.include_comments:
            title = " ".join(str(self._api.title or self._api.identity.name or "Exported API").split())
            lines += [f"// Generated Smithy IDL for {title}", ""]
        version = self._api.extras.get("smithy_version") if self._smithy_source else None
        lines += [f'$version: "{version or self._options.smithy_version}"', "", f"namespace {self.namespace}", ""]
        if self._options.protocol != "none":
            lines += [f"use {_PROTOCOLS[self._options.protocol]}", ""]
        for name, shape in self._shapes.items():
            lines.extend(self._render_shape(name, shape))
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def _render_traits(self, traits: Dict[str, Any], indent: str) -> List[str]:
        """Doc comments, then one ``@trait`` per line — ``@required`` last (the IDL reader reads a member's
        traits line by line)."""
        lines: List[str] = []
        doc = traits.get("documentation")
        if isinstance(doc, str):
            lines += [f"{indent}/// {line}".rstrip() for line in doc.splitlines()]
        ordered = [name for name in traits if name not in ("documentation", "required", "enumValue")]
        if "required" in traits:
            ordered.append("required")
        local_shapes = set(self._shapes)
        for name in ordered:
            local = name.split("#")[-1]
            if "#" not in name and local in local_shapes:
                # A shape of the model named like the trait would capture the relative reference.
                local = f"smithy.api#{local}"
            value = traits[name]
            lines.append(f"{indent}@{local}" if value == {} else f"{indent}@{local}({_node(value, top=True)})")
        return lines

    def _render_shape(self, name: str, shape: Dict[str, Any]) -> List[str]:
        kind = shape["type"]
        lines = self._render_traits(shape.get("traits", {}), "")
        if kind == "service":
            lines.append(f"service {name} {{")
            if "version" in shape:
                lines.append(f"    version: {json.dumps(shape['version'])}")
            if shape.get("operations"):
                lines.append(f"    operations: [{', '.join(op['target'] for op in shape['operations'])}]")
            lines.append("}")
        elif kind == "operation":
            lines.append(f"operation {name} {{")
            for key in ("input", "output"):
                if key in shape:
                    lines.append(f"    {key}: {shape[key]['target']}")
            if shape.get("errors"):
                lines.append(f"    errors: [{', '.join(error['target'] for error in shape['errors'])}]")
            lines.append("}")
        elif kind in ("structure", "union"):
            lines.append(f"{kind} {name} {{")
            for index, (member, node) in enumerate(shape["members"].items()):
                if index:
                    lines.append("")
                lines.extend(self._render_traits(node.get("traits", {}), "    "))
                lines.append(f"    {member}: {node['target']}")
            lines.append("}")
        elif kind == "enum":
            lines.append(f"enum {name} {{")
            for member, node in shape["members"].items():
                traits = node.get("traits", {})
                lines.extend(self._render_traits(traits, "    "))
                value = traits.get("enumValue")
                lines.append(f"    {member}" + (f" = {json.dumps(value)}" if value is not None else ""))
            lines.append("}")
        elif kind == "list":
            lines += [f"list {name} {{", f"    member: {shape['member']['target']}", "}"]
        elif kind == "map":
            lines += [f"map {name} {{", f"    key: {shape['key']['target']}", f"    value: {shape['value']['target']}",
                      "}"]
        else:
            lines.append(f"{kind} {name}")
        return lines


#: Marks "no default" (``None`` is a valid ``@default`` for a document).
_NO_DEFAULT = object()


def _bindable_header(name: str) -> bool:
    """Whether ``@httpHeader`` may bind a header of this name (a token, not a transport header)."""
    return bool(re.fullmatch(r"[A-Za-z0-9!#$%&'*+.^_`|~-]+", name)) and name.lower() not in _RESERVED_HEADERS


def _dedupe_json_names(members: Dict[str, Any]) -> None:
    """Drop a ``@jsonName`` that would give two members one wire name (``JsonName``: a source that repeats a
    field name renames the repeats, and they cannot all keep it)."""
    seen: Set[str] = set()
    for name, member in members.items():
        traits = member.get("traits", {})
        wire = traits.get("jsonName", name)
        if wire.lower() in seen and "jsonName" in traits:
            del traits["jsonName"]
            if not traits:
                member.pop("traits")
            wire = name
        seen.add(wire.lower())


def _is_custom_scalar(name: str) -> bool:
    """Whether a named scalar has no Smithy shape of its own (it is written as a ``string``)."""
    lowered = name.lower()
    known = target_scalar(name, SMITHY_SCALAR_FOR_KIND) or _EXTRA_SCALARS.get(lowered) or name in SMITHY_PRELUDE
    return not known and lowered not in _STRING_LIKE


def _number(value: float) -> Union[int, float]:
    return int(value) if float(value).is_integer() else value


def _node(value: Any, *, top: bool = False) -> str:
    """A trait value in IDL node syntax; a structure at the top is written ``key: value, …``."""
    if isinstance(value, dict):
        parts = ", ".join(f"{key if _IDENT_RE.match(key) else json.dumps(key)}: {_node(item)}"
                          for key, item in value.items())
        return parts if top and value else "{" + parts + "}"
    if isinstance(value, list):
        return "[" + ", ".join(_node(item) for item in value) + "]"
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return repr(value)
    return json.dumps(str(value))


def _success_response(operation: Operation) -> Optional[Message]:
    """The response an operation returns: the first success response with a body, else the first with one."""
    responses = [m for m in operation.messages if m.role is MessageRole.RESPONSE and m.payload is not None]
    success = [m for m in responses if str(m.status_code or m.extras.get("http_status") or "2").startswith("2")]
    return (success or responses or [None])[0]


def _namespace(api: CanonicalApi) -> str:
    """A Smithy namespace: identifiers joined by ``.`` (a URI's scheme is dropped)."""
    raw = api.extras.get("smithy_namespace") if api.format == "smithy" else None
    raw = raw or api.identity.namespace or api.identity.name or "example"
    raw = re.sub(r"^[A-Za-z][A-Za-z0-9+.-]*://", "", str(raw))
    parts = [smithy_identifier(part, "ns") for part in re.split(r"::|[./:\\#]+", raw) if part.strip()]
    return ".".join(parts) or "example"


def _base_name(api: CanonicalApi) -> str:
    base = api.services[0].name if api.services else (api.identity.name or "model")
    return re.sub(r"[^A-Za-z0-9_]+", "_", base).strip("_") or "model"
