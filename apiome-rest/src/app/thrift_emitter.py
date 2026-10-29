"""Apache Thrift emitter: canonical model → ``.thrift`` IDL — MFX-14.1.

The inverse of :class:`app.thrift_normalizer.ThriftNormalizer` and an implementation of the
:class:`app.emitter.Emitter` SPI. It walks a :class:`~app.canonical_model.CanonicalApi` and
produces Apache Thrift IDL text:

* ``RECORD`` / ``UNION`` / exception-shaped types → ``struct`` / ``union`` / ``exception``;
* ``ENUM`` → ``enum``;
* ``MAP`` → ``map<K,V>`` fields;
* RPC :class:`~app.canonical_model.Service`\\s → ``service`` blocks with ``throws`` preserved
  from error :class:`~app.canonical_model.Message`\\s when present.

Constructs Thrift cannot carry (HTTP bindings, event channels, validation constraints) are
recorded as :class:`~app.emitter.Loss` entries rather than silently dropped.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple, Union

from pydantic import Field

from .canonical_model import (
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
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
from .emitter import (
    CapabilityProfile,
    EmitOptions,
    EmitResult,
    EmittedFile,
    Emitter,
    LossKind,
    LossTracker,
    Provenance,
    ProvenanceTracker,
)
from .fidelity_rulepack import CapabilityRulePack, FidelityVerdict, _has_any_constraint
from .field_identity_store import FieldNumberAllocator
from .lossiness import LossinessKind, LossinessReport
from .scalar_aliases import THRIFT_SCALAR_FOR_KIND, target_scalar

__all__ = ["THRIFT_RESERVED", "ThriftEmitOptions", "ThriftEmitter", "ThriftFidelityRulePack", "thrift_identifier"]

_THRIFT_BASE_FROM_CANONICAL: Dict[str, str] = {
    "bool": "bool",
    "int8": "byte",
    "i16": "i16",
    "i32": "i32",
    "i64": "i64",
    "double": "double",
    "string": "string",
    "bytes": "binary",
    "uuid": "uuid",
}

_EVENT_OPERATION_KINDS = frozenset({OperationKind.PUBLISH, OperationKind.SUBSCRIBE})


class ThriftFidelityRulePack(CapabilityRulePack):
    """Fidelity rules for Thrift export (MFX-14.2)."""

    target_label = "Thrift"

    def evaluate(self, api: CanonicalApi) -> LossinessReport:
        """Note whether the model came from Thrift (its names are already Thrift identifiers)."""
        self._thrift_source = api.format == "thrift"
        return super().evaluate(api)

    def _renamed(self, name: Optional[str]) -> bool:
        """Whether the writer renames ``name`` (MFX-25.1): not for a Thrift source, whose names are valid."""
        return not getattr(self, "_thrift_source", True) and thrift_identifier(name) != (name or "")

    def root_verdicts(self, api: CanonicalApi) -> List[FidelityVerdict]:
        """Agent descriptors have no Thrift form."""
        if not api.agents:
            return []
        return [FidelityVerdict.drop(
            message=f"{self.target_label} has no agent descriptors; {len(api.agents)} agent(s) are not written",
            target_mapping="agents → dropped",
        )]

    def type_verdict(self, type_: Type) -> FidelityVerdict:
        verdict = super().type_verdict(type_)
        if verdict.kind is LossinessKind.OK and self._renamed(type_.name):
            return FidelityVerdict.approx(
                message=f"{self.target_label} type names are identifiers; {type_.name!r} is written as "
                f"{thrift_identifier(type_.name)!r}",
                target_mapping="type → renamed",
            )
        return verdict

    def operation_verdict(self, operation: Operation) -> FidelityVerdict:
        if (
            operation.kind not in _EVENT_OPERATION_KINDS
            and not (operation.http_method or operation.http_path)
            and self._renamed(operation.name)
        ):
            return FidelityVerdict.approx(
                message=f"{self.target_label} method names are identifiers; {operation.name!r} is written as "
                f"{thrift_identifier(operation.name)!r}",
                target_mapping="method → renamed",
            )
        if operation.kind in _EVENT_OPERATION_KINDS:
            return FidelityVerdict.drop(
                message=f"{self.target_label} has no event vocabulary; "
                f"{operation.kind.value} operation {operation.key!r} is dropped",
                target_mapping="event operation → dropped",
            )
        if operation.http_method or operation.http_path:
            return FidelityVerdict.approx(
                message=f"{self.target_label} has no HTTP binding; reframing "
                f"{operation.key!r} as an RPC method",
                target_mapping="HTTP operation → RPC method",
            )
        return super().operation_verdict(operation)

    def field_verdicts(self, field: CanonicalField) -> List[FidelityVerdict]:
        """The capability verdicts, plus an ``APPROX`` when the writer renames the field (MFX-25.1)."""
        verdicts = super().field_verdicts(field)
        if self._renamed(field.name):
            verdicts.append(FidelityVerdict.approx(
                message=f"{self.target_label} field names are identifiers; {field.name!r} is written as "
                f"{thrift_identifier(field.name)!r}",
                target_mapping="field → renamed",
            ))
        return verdicts

    def field_verdict(self, field: CanonicalField) -> Optional[FidelityVerdict]:
        if _has_any_constraint(field.constraints):
            return FidelityVerdict.approx(
                message=f"{self.target_label} cannot enforce validation constraints; "
                f"{field.key!r} is approximated without facets",
                target_mapping="constraints → dropped",
            )
        return super().field_verdict(field)


class ThriftEmitOptions(EmitOptions):
    """Per-target options for :class:`ThriftEmitter`."""

    include_comments: bool = Field(
        default=True,
        description="Emit brief generated-file header comments.",
    )
    persisted_field_numbers: Dict[str, int] = Field(
        default_factory=dict,
        description="Pre-loaded stable field ids keyed by canonical field key (MFX-25.2).",
    )
    namespaces: Dict[str, str] = Field(
        default_factory=dict,
        description="`namespace` lines to write, language → namespace (`{\"java\": \"com.acme\", \"py\": \"acme\"}`; "
        "`*` for every language). Defaults to a Thrift source's own namespaces, else `py` and the API's namespace.",
    )


class ThriftEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as Apache Thrift IDL."""

    key = "thrift"
    format = "thrift"
    label = "Apache Thrift"
    description = "Export as an Apache Thrift IDL (.thrift) document."
    icon = "network"
    paradigm = ApiParadigm.RPC
    multi_file = False
    options_model = ThriftEmitOptions

    OUTPUT_MEDIA_TYPE = "application/x-thrift"

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        return CapabilityProfile(
            operations=True,
            events=False,
            unions=True,
            nullability=True,
            field_identity=True,
        )

    @classmethod
    def fidelity_rule_pack(cls) -> Optional[type[CapabilityRulePack]]:
        return ThriftFidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[ThriftEmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        options = (
            opts
            if isinstance(opts, ThriftEmitOptions)
            else ThriftEmitOptions.model_validate(opts.model_dump() if opts else {})
        )
        writer = _ThriftWriter(api, options)
        content = writer.render()
        return EmitResult(
            files=[
                EmittedFile(
                    path=writer.output_path,
                    content=content,
                    media_type=self.OUTPUT_MEDIA_TYPE,
                )
            ],
            media_type=self.OUTPUT_MEDIA_TYPE,
            provenance=writer.tracker.records(),
            losses=writer.losses.records(),
            field_identity_assignments=writer.field_identity_assignments,
        )


#: Words the Thrift compiler refuses as identifiers: its own keywords and the reserved words of the
#: languages it generates (``thrifty.ll``). A name that is one of these is written with a ``_`` suffix.
THRIFT_RESERVED = frozenset(
    """
    binary bool byte const cpp_include cpp_type double else enum exception extends false i8 i16 i32 i64
    include list map namespace oneway optional required senum service set slist string struct throws true
    typedef union uuid void xsd_all xsd_attrs xsd_nillable xsd_optional
    BEGIN END __CLASS__ __DIR__ __FILE__ __FUNCTION__ __LINE__ __METHOD__ __NAMESPACE__ abstract alias and
    args as assert begin break case catch class clone continue declare def default del delete do dynamic
    elif elseif elsif end enddeclare endfor endforeach endif endswitch endwhile ensure except exec finally
    float for foreach from function global goto if implements import in inline instanceof interface is
    lambda module native new next nil not or package pass print private protected public raise redo
    rescue retry register return self sizeof static super switch synchronized then this throw transient
    try undef unless unsigned until use var virtual volatile when while with xor yield
    """.split()
)

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def thrift_identifier(name: Optional[str], fallback: str = "_") -> str:
    """A name the Thrift compiler accepts: word characters, not starting with a digit, not reserved.

    Args:
        name: The source name (``com.acme.Order``, ``order-id``, ``class``).
        fallback: Used when nothing of the name survives.

    Returns:
        The identifier (``com_acme_Order``, ``order_id``, ``class_``).
    """
    ident = re.sub(r"[^A-Za-z0-9_]+", "_", name or "").strip("_") or fallback
    if ident[0].isdigit():
        ident = f"_{ident}"
    while ident in THRIFT_RESERVED:
        ident = f"{ident}_"
    return ident


class _Scope:
    """Unique identifiers within one Thrift scope (top-level names, a struct's fields, …)."""

    def __init__(self, taken: Optional[set] = None) -> None:
        self._taken = set(taken or ())

    def claim(self, name: Optional[str], fallback: str = "_") -> str:
        """The identifier for ``name`` in this scope, suffixed ``2``, ``3`` … when already taken."""
        base = thrift_identifier(name, fallback)
        candidate, suffix = base, 2
        while candidate in self._taken:
            candidate, suffix = f"{base}{suffix}", suffix + 1
        self._taken.add(candidate)
        return candidate


class _ThriftWriter:
    """Render a canonical model as Thrift IDL the Thrift compiler accepts (MFX-25.1).

    Every declared name is a valid, unique, non-reserved identifier (renames are reported). Records
    are ``struct``\\s, unions ``union``\\s (a union that only lists its member types gets one optional
    field per member), aliases and named scalars ``typedef``\\s, error types ``exception``\\s, and maps
    ``map<K, V>``. A method takes its request type as ``1: T arg`` — or, when the operation has
    parameters, a synthesized ``<Method>Request`` struct holding them and the body — and returns the
    first success response's type. ``throws`` lists exceptions only.
    """

    def __init__(self, api: CanonicalApi, options: ThriftEmitOptions) -> None:
        self._api = api
        self._options = options
        self._thrift_source = api.format == "thrift"
        self.tracker = ProvenanceTracker()
        self.losses = LossTracker()
        self._types_by_key = {t.key: t for t in api.types}
        self._types_by_name: Dict[str, Type] = {}
        for type_ in api.types:
            self._types_by_name.setdefault(type_.name, type_)
        self.output_path = _output_path(api)
        #: Field ids assigned on this export that were not stored before, for the caller to
        #: persist so the next export reuses them (MFX-25.2).
        self.field_identity_assignments: Dict[str, int] = {}
        self._top = _Scope()
        self._names: Dict[str, str] = {}
        typedefs = api.extras.get("thrift_typedefs") if self._thrift_source else None
        self._source_typedefs: Dict[str, str] = dict(typedefs) if isinstance(typedefs, dict) else {}
        for name in self._source_typedefs:
            self._top.claim(name)
        for type_ in api.types:
            if type_.extras.get("thrift_map"):
                continue
            self._names[type_.key] = self._top.claim(type_.name, "Type")
            if self._names[type_.key] != type_.name and not self._thrift_source:
                self.losses.record(
                    LossKind.INFERRED,
                    "renamed-type",
                    f"Thrift type names are identifiers; {type_.name!r} is written as {self._names[type_.key]!r}.",
                    pointer=type_.key,
                )
        self._service_names = {svc.key: self._top.claim(svc.name, "Service") for svc in api.services}
        self._exceptions = self._exception_types()
        self._request_structs: List[List[str]] = []

    # ------------------------------------------------------------------
    # Document
    # ------------------------------------------------------------------

    def render(self) -> str:
        lines: List[str] = []
        if self._options.include_comments:
            title = self._api.identity.name or "Exported API"
            lines.append(f"// Generated Apache Thrift IDL for {' '.join(str(title).split())}")
            lines.append("")

        namespaces = self._namespaces()
        for lang, name in namespaces:
            lines.append(f"namespace {lang} {name}")
        if namespaces:
            lines.append("")

        includes = self._api.extras.get("thrift_includes") or []
        if isinstance(includes, list):
            for include in includes:
                lines.append(f'include "{include}"')
            if includes:
                lines.append("")

        for name, expr in self._source_typedefs.items():
            lines.append(f"typedef {expr} {name}")
        if self._source_typedefs:
            lines.append("")

        for type_ in self._api.types:
            if type_.extras.get("thrift_map"):
                continue
            rendered = self._render_type(type_)
            if rendered:
                lines.extend(rendered)
                lines.append("")

        services = [self._render_service(service) for service in self._api.services]
        for struct in self._request_structs:
            lines.extend(struct)
            lines.append("")
        for service in services:
            lines.extend(service)
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def _namespaces(self) -> List[Tuple[str, str]]:
        """``(language, namespace)`` pairs: the option, else a Thrift source's own, else the identity's."""
        chosen = self._options.namespaces
        if not chosen:
            own = self._api.extras.get("thrift_namespaces")
            if isinstance(own, dict) and own:
                return sorted((str(lang), str(name)) for lang, name in own.items())
            if self._api.identity.namespace:
                chosen = {"py": self._api.identity.namespace}
        out: List[Tuple[str, str]] = []
        for lang, name in sorted((chosen or {}).items()):
            parts = [thrift_identifier(part) for part in str(name).split(".") if part]
            if parts:
                out.append((lang if lang == "*" else thrift_identifier(lang), ".".join(parts)))
        return out

    # ------------------------------------------------------------------
    # Types
    # ------------------------------------------------------------------

    def _exception_types(self) -> set:
        """Keys of the types written as ``exception``: a Thrift source's own, and — for any other
        source — a record only ever thrown (an error response type used nowhere else)."""
        exceptions = {t.key for t in self._api.types if t.extras.get("thrift_kind") == "exception"}
        if self._thrift_source:
            return exceptions
        thrown: set = set()
        used: set = set()
        for operation in self._api.operations():
            for message in operation.messages:
                key = self._type_key(message.payload)
                if key is None:
                    continue
                (thrown if message.role is MessageRole.ERROR else used).add(key)
        for type_ in self._api.types:
            for field in type_.fields:
                key = self._type_key(field.type)
                if key is not None:
                    used.add(key)
        for key in thrown - used:
            if self._types_by_key[key].kind is TypeKind.RECORD:
                exceptions.add(key)
        return exceptions

    def _type_key(self, ref: Optional[TypeRef]) -> Optional[str]:
        while ref is not None and ref.item is not None:
            ref = ref.item
        if ref is None or not ref.name:
            return None
        if ref.name in self._types_by_key:
            return ref.name
        target = self._types_by_name.get(ref.name)
        return target.key if target is not None else None

    def _render_type(self, type_: Type) -> List[str]:
        thrift_kind = type_.extras.get("thrift_kind")
        if type_.kind is TypeKind.ENUM or thrift_kind == "enum":
            return self._render_enum(type_)
        if type_.kind is TypeKind.UNION or thrift_kind == "union":
            return self._render_struct(type_, keyword="union")
        if thrift_kind == "exception" or type_.key in self._exceptions:
            if thrift_kind != "exception":
                self.losses.record(
                    LossKind.INFERRED,
                    "struct-as-exception",
                    f"{type_.key!r} is only returned as an error, so it is written as a Thrift exception.",
                    pointer=type_.key,
                )
            return self._render_struct(type_, keyword="exception")
        if type_.kind is TypeKind.RECORD:
            return self._render_struct(type_, keyword="struct")
        if type_.kind in (TypeKind.ALIAS, TypeKind.SCALAR):
            return self._render_typedef(type_)
        self.losses.record(
            LossKind.NA,
            "unsupported-type",
            f"Type {type_.key!r} ({type_.kind.value}) has no Thrift representation and is skipped",
            pointer=type_.key,
        )
        return []

    def _render_typedef(self, type_: Type) -> List[str]:
        """An alias as ``typedef <aliased> Name``; a named scalar as a typedef of its base type."""
        if type_.kind is TypeKind.ALIAS and type_.aliased is not None:
            expr = self._render_type_ref(type_.aliased)
        else:
            fmt = type_.constraints.format if type_.constraints is not None else None
            expr = _THRIFT_BASE_FROM_CANONICAL.get(type_.name) or target_scalar(type_.name, THRIFT_SCALAR_FOR_KIND, fmt)
            if expr is None:
                expr = "string"
                self.losses.record(
                    LossKind.INFERRED,
                    "custom-scalar",
                    f"Thrift has no custom scalars; {type_.key!r} is a typedef of string.",
                    pointer=type_.key,
                )
        self.tracker.record(type_.key, Provenance.SOURCE)
        return [f"typedef {expr} {self._names[type_.key]}"]

    def _render_enum(self, type_: Type) -> List[str]:
        lines = [f"enum {self._names[type_.key]} {{"]
        scope = _Scope()
        dropped_values = False
        for value in type_.enum_values:
            name = scope.claim(value.name, "VALUE")
            number = value.value if isinstance(value.value, int) and not isinstance(value.value, bool) else None
            if value.value is not None and number is None:
                dropped_values = True
            lines.append(f"  {name}" + (f" = {number}" if number is not None else "") + ",")
        if dropped_values:
            self.losses.record(
                LossKind.NA,
                "enum-values-dropped",
                f"Thrift enum values are integers; the values of {type_.key!r} are not written (members keep "
                "their names).",
                pointer=type_.key,
            )
        lines.append("}")
        self.tracker.record(type_.key, Provenance.SOURCE)
        return lines

    def _render_struct(self, type_: Type, *, keyword: str) -> List[str]:
        lines = [f"{keyword} {self._names[type_.key]} {{"]
        if keyword == "union" and not type_.fields and type_.union_members:
            return lines + self._union_member_fields(type_) + ["}"]
        # A field without a ``field_number`` (an OpenAPI or JSON Schema source) gets the id stored
        # for it by an earlier export, else the next free id in declaration order, so ids stay
        # unique within the struct (#6278) and stable across re-exports (MFX-25.2).
        allocator = FieldNumberAllocator(type_, persisted=self._options.persisted_field_numbers)
        numbered: List[Tuple[int, CanonicalField]] = []
        for field in type_.fields:
            number, synthesized = allocator.allocate(field)
            if synthesized:
                self.losses.record(
                    LossKind.INFERRED,
                    "synthesized-field-number",
                    f"Field {field.key!r} had no source field id; assigned {number}.",
                    pointer=field.key,
                )
            numbered.append((number, field))
        scope = _Scope()
        for number, field in sorted(numbered, key=lambda pair: pair[0]):
            lines.append(f"  {self._render_field(field, number, scope, in_union=keyword == 'union')},")
        self.field_identity_assignments.update(allocator.new_assignments)
        lines.append("}")
        self.tracker.record(type_.key, Provenance.SOURCE)
        return lines

    def _union_member_fields(self, type_: Type) -> List[str]:
        """A union that lists its member types: one optional field per member, numbered in order."""
        scope = _Scope()
        lines = []
        for number, member in enumerate(type_.union_members, start=1):
            expr = self._render_type_ref(TypeRef(name=member))
            name = scope.claim(member.split(".")[-1][:1].lower() + member.split(".")[-1][1:], "member")
            lines.append(f"  {number}: optional {expr} {name},")
        self.losses.record(
            LossKind.INFERRED,
            "union-member-fields",
            f"The members of union {type_.key!r} are written as one optional field each.",
            pointer=type_.key,
        )
        self.tracker.record(type_.key, Provenance.SOURCE)
        return lines

    def _render_field(self, field: CanonicalField, number: int, scope: _Scope, *, in_union: bool = False) -> str:
        """Render one struct field.

        Args:
            field: The canonical field.
            number: Its Thrift field id — the source's, or one assigned by ``_render_struct``.
            scope: The struct's field names, so each written name is unique.
            in_union: Whether the field belongs to a union (whose fields are never ``required``).

        Returns:
            The field line without its trailing comma, e.g. ``2: optional i64 id``.
        """
        required = field.extras.get("thrift_required")
        if required is None:
            required = not field.type.nullable and not in_union
        modifier = "required " if required else "optional "
        fmt = field.constraints.format if field.constraints is not None else None
        type_expr = self._render_type_ref(field.type, fmt)
        default = field.extras.get("thrift_default")
        default_suffix = f" = {default}" if default else ""
        name = scope.claim(field.name, "field")
        if name != field.name and not self._thrift_source:
            self.losses.record(
                LossKind.INFERRED,
                "renamed-field",
                f"Thrift field names are identifiers; {field.name!r} is written as {name!r}.",
                pointer=field.key,
            )
        if field.field_number is None:
            self.tracker.record(field.key, Provenance.INFERRED, "synthesized field id")
        else:
            self.tracker.record(field.key, Provenance.SOURCE)
        return f"{number}: {modifier}{type_expr} {name}{default_suffix}"

    def _render_type_ref(self, ref: TypeRef, fmt: Optional[str] = None) -> str:
        """Render a type reference as a Thrift type expression.

        Args:
            ref: The reference (a list, a map type, a base type or a named type).
            fmt: The field's ``format`` constraint, which picks the width of a JSON Schema
                ``integer`` or ``number``.

        Returns:
            The Thrift type, e.g. ``list<i64>`` or ``Pet``.
        """
        if ref.item is not None:
            inner = self._render_type_ref(ref.item, fmt)
            if ref.extras.get("thrift_container") == "set":
                return f"set<{inner}>"
            return f"list<{inner}>"
        if not ref.name:
            return "string"
        target = self._types_by_key.get(ref.name) or self._types_by_name.get(ref.name)
        if target is not None and target.kind is TypeKind.MAP:
            key = self._render_type_ref(target.key_type or TypeRef(name="string"))
            value = self._render_type_ref(target.value_type or TypeRef(name="string"))
            return f"map<{key}, {value}>"
        if target is not None and target.key in self._names:
            return self._names[target.key]
        base = _THRIFT_BASE_FROM_CANONICAL.get(ref.name)
        if base is None:
            # Another normalizer's scalar spelling (``integer``, ``boolean``, ``int64``…) (#6278).
            base = target_scalar(ref.name, THRIFT_SCALAR_FOR_KIND, fmt)
        if base == "uuid" and not self._thrift_source:
            # `uuid` is a Thrift 0.21 base type; older compilers reject it (#4151).
            self.losses.record(LossKind.INFERRED, "uuid-as-string",
                               "A uuid is written as a Thrift string (the uuid base type needs Thrift 0.21).")
            return "string"
        if base is not None:
            return base
        if self._thrift_source:
            # A typedef or an included file's qualified type, written as the source spelled it.
            return ref.name
        if ref.name in ("object", "any", "map"):
            return "map<string, string>"
        self.losses.record(
            LossKind.INFERRED,
            "unknown-type",
            f"The type {ref.name!r} is not declared; it is written as a Thrift string.",
        )
        return "string"

    # ------------------------------------------------------------------
    # Services
    # ------------------------------------------------------------------

    def _render_service(self, service: Service) -> List[str]:
        name = self._service_names[service.key]
        extends = service.extras.get("thrift_extends")
        parent = self._service_names.get(extends) if isinstance(extends, str) else None
        lines = [f"service {name}" + (f" extends {parent}" if parent else "") + " {"]
        scope = _Scope()
        for operation in service.operations:
            if operation.kind in _EVENT_OPERATION_KINDS:
                continue
            rendered = self._render_method(operation, scope)
            if rendered:
                lines.append(f"  {rendered},")
        lines.append("}")
        self.tracker.record(service.key, Provenance.SOURCE)
        return lines

    def _render_method(self, operation: Operation, scope: _Scope) -> str:
        name = scope.claim(operation.name, "call")
        if name != operation.name and not self._thrift_source:
            self.losses.record(
                LossKind.INFERRED,
                "renamed-method",
                f"Thrift method names are identifiers; {operation.name!r} is written as {name!r}.",
                pointer=operation.key,
            )
        if operation.streaming is not StreamingMode.NONE:
            self.losses.record(
                LossKind.NA,
                "streaming-dropped",
                f"Thrift has no streaming; {operation.key!r} is written as one call.",
                pointer=operation.key,
            )
        oneway = bool(operation.extras.get("thrift_oneway"))
        prefix = "oneway " if oneway else ""
        response = self._response(operation)
        return_type = "void" if oneway or response is None else self._render_type_ref(response.payload)
        params = self._params(operation, name)
        throws_clause = "" if oneway else self._throws(operation)
        self.tracker.record(operation.key, Provenance.SOURCE)
        return f"{prefix}{return_type} {name}({', '.join(params)}){throws_clause}"

    @staticmethod
    def _response(operation: Operation) -> Optional[Message]:
        """The response a method returns: the first success response with a body, else the first with one."""
        responses = [m for m in operation.messages if m.role is MessageRole.RESPONSE and m.payload is not None]
        success = [m for m in responses if str(m.status_code or m.extras.get("http_status") or "2").startswith("2")]
        return (success or responses or [None])[0]

    def _params(self, operation: Operation, method_name: str) -> List[str]:
        """The method's parameter list (see the class docstring)."""
        request = next((m for m in operation.messages if m.role is MessageRole.REQUEST), None)
        if request is not None and request.extras.get("thrift_parameters"):
            out = []
            for param in request.extras["thrift_parameters"]:
                modifier = "required " if param.get("required") else ""
                out.append(f"{param['id']}: {modifier}{param['type']} {param['name']}")
            return out
        if operation.parameters and not self._thrift_source:
            return [f"1: {self._request_struct(operation, method_name, request)} request"]
        if request is not None and request.payload is not None:
            return [f"1: {self._render_type_ref(request.payload)} arg"]
        return []

    def _request_struct(self, operation: Operation, method_name: str, request: Optional[Message]) -> str:
        """Synthesize ``<Method>Request`` from the operation's parameters and body; return its name."""
        struct_name = self._top.claim(method_name[:1].upper() + method_name[1:] + "Request", "Request")
        scope = _Scope()
        lines = [f"struct {struct_name} {{"]
        number = 0
        for number, param in enumerate(operation.parameters, start=1):
            modifier = "required " if param.required else "optional "
            fmt = param.constraints.format if param.constraints is not None else None
            lines.append(f"  {number}: {modifier}{self._render_type_ref(param.type, fmt)} "
                         f"{scope.claim(param.name, 'param')},")
        if request is not None and request.payload is not None:
            lines.append(f"  {number + 1}: optional {self._render_type_ref(request.payload)} "
                         f"{scope.claim('body')},")
        lines.append("}")
        self._request_structs.append(lines)
        self.losses.record(
            LossKind.INFERRED,
            "request-struct-synthesized",
            f"Thrift methods take positional arguments; the parameters of {operation.key!r} are written as "
            f"the struct {struct_name!r}.",
            pointer=operation.key,
        )
        return struct_name

    def _throws(self, operation: Operation) -> str:
        """``throws (…)`` for the error responses whose type is an exception; the rest are reported."""
        parts: List[str] = []
        scope = _Scope()
        number = 0
        for message in operation.messages:
            if message.role is not MessageRole.ERROR or message.payload is None:
                continue
            key = self._type_key(message.payload)
            if self._thrift_source:
                type_name = message.payload.name.split(".")[-1] if message.payload.name else "Exception"
                type_name = self._names.get(key, type_name) if key else type_name
            elif key is None or key not in self._exceptions:
                self.losses.record(
                    LossKind.NA,
                    "throws-dropped",
                    f"Thrift throws only exceptions; the error response {message.key!r} of {operation.key!r} "
                    "is not written.",
                    pointer=operation.key,
                )
                continue
            else:
                type_name = self._names[key]
            number = int(message.extras.get("thrift_throw_id") or number + 1)
            parts.append(f"{number}: {type_name} {scope.claim(message.name or type_name.lower(), 'error')}")
        return f" throws ({', '.join(parts)})" if parts else ""


def _output_path(api: CanonicalApi) -> str:
    base = api.identity.name or "api"
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", base).strip("_") or "api"
    return f"{safe}.thrift"
