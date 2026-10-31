"""OMG IDL 4.2 emitter (CORBA / DDS): canonical model → ``.idl`` — MFX-24.1, rebuilt for MFX-28.1 (#4168).

The inverse of :class:`app.corbaidl_normalizer.CorbaIdlNormalizer` and an implementation of the
:class:`app.emitter.Emitter` SPI. The written document parses under a reference IDL compiler
(omniidl for the CORBA building blocks, Eclipse Cyclone DDS ``idlc`` for the annotated data types):

* ``RECORD`` → ``struct``; ``UNION`` → a discriminated ``union`` switched on a synthesized
  ``<Union>Kind`` enum (one case per member); ``ENUM`` → ``enum``; aliases and named scalars →
  ``typedef``; ``MAP`` → ``typedef sequence<<Map>Entry>``; lists → ``sequence<T>``;
* a nullable field → ``@optional`` (IDL 4.2 annotation);
* RPC :class:`~app.canonical_model.Service`\\s → ``interface``\\s whose operations take their
  parameters and body as ``in`` arguments, return the first success response, and ``raises`` the
  error responses that are exceptions (records only ever returned as errors);
* the API namespace → nested ``module``\\s (``com.acme.orders`` → ``module com { module acme { … }}``).

Two profiles (:attr:`CorbaIdlEmitOptions.profile`): ``corba`` (the default) writes interfaces and
exceptions; ``dds`` writes the topic-friendly data-type subset — no interfaces or exceptions, no
recursive members — and marks identifier fields ``@key``.

What makes the output compile: every declared name is a valid identifier, unique in its scope and
not an IDL keyword — compared case-insensitively, as IDL does (renames are reported); every type
reference is fully scoped (``::com::acme::Order``), so a member named ``order`` never clashes with a
use of ``Order``; definitions are ordered so each is declared before it is used, with forward
declarations for self-recursive types; anonymous sequences in operation signatures become typedefs;
an empty struct gets a placeholder member. Constructs IDL cannot carry are reported as
:class:`~app.emitter.Loss` entries rather than silently dropped.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Literal, Mapping, Optional, Set, Tuple, Union

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
from .constraint_text import constraint_comment
from .corbaidl_parser import parse_corbaidl
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
from .fidelity_rulepack import CapabilityRulePack, FidelityVerdict
from .lossiness import LossinessKind, LossinessReport, LossinessSeverity
from .scalar_aliases import OMG_IDL_SCALAR_FOR_KIND, target_scalar

__all__ = [
    "OMG_IDL_KEYWORDS",
    "CorbaIdlEmitOptions",
    "CorbaIdlEmitter",
    "CorbaIdlFidelityRulePack",
    "idl_identifier",
    "validate_corbaidl_document",
]

#: The keywords of the OMG IDL 4.2 building blocks the writer targets (§7.2.4: core data types,
#: interfaces, value types, extended data types), lower-cased. IDL compares identifiers with keywords
#: case-insensitively, so ``Module`` and ``STRING`` are refused as well. The component and connector
#: building blocks' keywords (``component``, ``home``, ``finder``, ``port`` …) are left out: neither
#: reference compiler (omniidl, Cyclone DDS ``idlc``) reserves them, and they are common type names.
OMG_IDL_KEYWORDS = frozenset(
    """
    abstract any attribute bitfield bitmask bitset boolean case char const context custom default double
    exception enum factory false fixed float in inout interface local long map module native object octet
    oneway out private public raises readonly sequence short string struct supports switch true truncatable
    typedef union unsigned valuebase valuetype void wchar wstring int8 uint8 int16 int32 int64 uint16 uint32
    uint64
    """.split()
)

#: Canonical scalar spellings that are text in every IDL mapping (no loss to report).
_STRING_LIKE = frozenset(
    {
        "uuid", "date", "date-time", "datetime", "time", "timestamp", "duration", "uri", "url", "email",
        "char", "wchar", "wstring", "decimal", "ipv4", "ipv6", "hostname",
    }
)

#: Canonical names of free-form values, written as JSON text.
_FREE_FORM = frozenset({"any", "object", "json", "map", "dict", "struct"})

#: Wide character types and the narrow type the DDS profile writes for each (DDS toolchains such as
#: Cyclone DDS ``idlc`` read no wide characters).
_WIDE_TYPES = {"wstring": "string", "wchar": "char"}

def is_http_operation(operation: Operation) -> bool:
    """Whether ``operation`` has an HTTP binding (a method or a path) that IDL has no place for."""
    return bool(operation.http_method or operation.http_path)


_EVENT_OPERATION_KINDS = frozenset({OperationKind.PUBLISH, OperationKind.SUBSCRIBE})

#: Words that are part of a type expression in a CORBA source's own spelling, never type names.
_EXPR_WORDS = frozenset(
    {"sequence", "unsigned", "long", "short", "string", "wstring", "char", "wchar", "octet", "boolean",
     "float", "double", "any", "Object", "void", "fixed"}
)


class CorbaIdlFidelityRulePack(CapabilityRulePack):
    """Fidelity rules for OMG IDL export — renames (MFX-28.1), profile-dependent losses (MFX-28.2, #4169).

    The pack lays the model out with the IDL writer for the export's ``profile`` (``corba`` or ``dds``,
    :meth:`apply_options`), so it predicts exactly what the export writes:

    * **constraints** — a ``max_length`` on a string member is written ``string<N>`` and a ``max_items``
      on a list ``sequence<T, N>``: represented, nothing reported; every other constraint is written as a
      ``// constraints: …`` comment above the member, typedef or operation (``APPROX``);
    * **HTTP semantics** — under ``corba`` an HTTP operation is an IDL operation (``APPROX``) and its
      method, path, status codes and parameter locations are a ``DROP``; under ``dds`` no interface is
      written, so every operation is a ``DROP``;
    * **event channels** — under ``dds`` a channel is a DDS topic: its payload type is declared and the
      topic named in a comment (``APPROX``); under ``corba`` it is a ``DROP``; event operations are a
      ``DROP`` under both;
    * **maps** — written as a sequence of ``<Map>Entry`` key/value structs, IDL 4.2 ``map`` being
      unsupported by CORBA compilers (``APPROX``);
    * **unions** — discriminated on a synthesized ``<Union>Kind`` enum, the canonical model carrying
      no discriminator (``SYNTH``);
    * renames of types, members and operations (``APPROX``) and agent descriptors (``DROP``).

    A CORBA source's names are already identifiers and it carries no constraints, so nothing of it is
    predicted renamed or commented.
    """

    target_label = "CORBA IDL"

    def apply_options(self, options: Mapping[str, Any]) -> None:
        """Compute the report for the export's options (invalid options fall back to the defaults)."""
        try:
            self._options = CorbaIdlEmitOptions.model_validate(dict(options))
        except ValueError:
            self._options = CorbaIdlEmitOptions()

    def evaluate(self, api: CanonicalApi) -> LossinessReport:
        """Lay the model out with the writer for the chosen profile, then walk it."""
        self._corba_source = api.format == "corbaidl"
        options = getattr(self, "_options", None) or CorbaIdlEmitOptions()
        self._dds = options.profile == "dds"
        self._writer = _CorbaIdlWriter(api, options)
        try:
            self._writer.render()
        except EmitPreconditionError:
            pass  # nothing to declare is refused at export; the walk still reports each construct
        interfaces = self._writer.interface_names()
        # The reader keys everything under the dotted module path (or, with none, the first interface).
        self._namespace = ".".join(self._writer.module_path) or next(iter(interfaces.values()), "CorbaIdl")
        self._interfaces = {} if self._dds else interfaces
        self._service_of = {op.key: svc.key for svc in api.services for op in svc.operations}
        self._source_keys = (
            {t.key for t in api.types} | {s.key for s in api.services} | {o.key for o in api.operations()}
        )
        return super().evaluate(api)

    # -- keys a re-import gives back ----------------------------------------------

    def _key(self, name: str) -> str:
        """The key the CORBA IDL reader gives a declaration named ``name``."""
        return f"{self._namespace}.{name}"

    def _type_key(self, type_: Type) -> Optional[str]:
        """A declared record / enum / alias's re-import key (maps and unions do not come back as types)."""
        written = self._writer.type_names.get(type_.key)
        if written is None or type_.kind in (TypeKind.MAP, TypeKind.UNION, TypeKind.SCALAR, TypeKind.ALIAS):
            return None
        return self._key(written)

    def _service_key(self, service_key: str) -> Optional[str]:
        interface = self._interfaces.get(service_key)
        return self._key(interface) if interface else None

    def _operation_key(self, operation: Operation) -> Optional[str]:
        service = self._service_key(self._service_of.get(operation.key, ""))
        name = self._writer.operation_names.get(operation.key)
        return f"{service}.{name}" if service and name else None

    def _rekeyed(self, old: str, new: Optional[str], noun: str) -> Optional[FidelityVerdict]:
        """A ``DROP`` under ``old`` when a re-import keys the construct as ``new``."""
        if self._corba_source or new is None or new == old:
            return None
        return FidelityVerdict.drop(
            message=f"{self.target_label} declares a {noun} in module {self._namespace!r}; {old!r} reads back as "
            f"{new!r}",
            severity=LossinessSeverity.INFO,
            target_mapping=f"{noun} → {new}",
        )

    def synthesized_verdicts(self, api: CanonicalApi) -> List[Tuple[str, FidelityVerdict]]:
        """The keys a re-import creates: module-scoped types, interfaces and operations, entry structs and
        discriminator enums."""
        if self._corba_source:
            return []
        out: List[Tuple[str, FidelityVerdict]] = []

        def add(key: Optional[str], message: str, mapping: str) -> None:
            if key and key not in self._source_keys and all(key != k for k, _ in out):
                out.append((key, FidelityVerdict.synth(
                    message=f"{self.target_label}: {message}", severity=LossinessSeverity.INFO, target_mapping=mapping,
                )))

        for type_ in api.types:
            add(self._type_key(type_), f"{type_.key!r} is declared in module {self._namespace!r}", "type")
            if type_.key in self._writer.entry_names:
                add(self._key(self._writer.entry_names[type_.key]),
                    f"the map {type_.key!r} is written with a key/value entry struct", "map → entry struct")
            if type_.key in self._writer.kind_names:
                add(self._key(self._writer.kind_names[type_.key]),
                    f"the union {type_.key!r} is switched on a generated discriminator enum", "union → discriminator")
        for service in api.services:
            add(self._service_key(service.key), f"service {service.name!r} is an interface", "service → interface")
            for operation in service.operations:
                add(self._operation_key(operation), f"{operation.key!r} is an operation of its interface",
                    "operation → IDL operation")
        return out

    def service_verdicts(self, service: Any) -> List[FidelityVerdict]:
        if self._corba_source:
            return []
        if self._dds:
            return [FidelityVerdict.drop(
                message=f"{self.target_label} (DDS) writes data types only; service {service.name!r} is not written",
                target_mapping="service → dropped (DDS profile)",
            )]
        rekeyed = self._rekeyed(service.key, self._service_key(service.key), "interface")
        return [rekeyed] if rekeyed else []

    def _renamed(self, name: Optional[str]) -> bool:
        """Whether the writer renames ``name``: not for a CORBA source, whose names are valid."""
        return not getattr(self, "_corba_source", True) and idl_identifier(name) != (name or "")

    def _rename_verdict(self, what: str, name: str) -> FidelityVerdict:
        return FidelityVerdict.approx(
            message=f"{self.target_label} {what} names are identifiers; {name!r} is written as "
            f"{idl_identifier(name)!r}",
            target_mapping=f"{what} → renamed",
        )

    def root_verdicts(self, api: CanonicalApi) -> List[FidelityVerdict]:
        """Agent descriptors, and a non-CORBA source's document envelope."""
        verdicts: List[FidelityVerdict] = []
        if api.agents:
            verdicts.append(FidelityVerdict.drop(
                message=f"{self.target_label} has no agent descriptors; {len(api.agents)} agent(s) are not written",
                target_mapping="agents → dropped",
            ))
        if not self._corba_source:
            verdicts.append(FidelityVerdict.drop(
                message=f"{self.target_label} has no document title, version, description or servers; the API is "
                f"written as module {self._namespace!r} and reads back as an RPC API",
                severity=LossinessSeverity.INFO,
                target_mapping="document → IDL module",
            ))
        return verdicts

    # -- channels and operations ----------------------------------------------

    def channel_verdict(self, channel: Any) -> FidelityVerdict:
        """A DDS topic under the ``dds`` profile; dropped under ``corba``."""
        if self._dds:
            payload = self._writer.topics.get(channel.key)
            return FidelityVerdict.approx(
                message=f"{self.target_label} (DDS): {channel.key!r} is a topic created at run time"
                + (f" with the type {payload}" if payload else ", no payload type is known")
                + "; IDL declares the type, and the topic name is written as a comment",
                target_mapping="channel → DDS topic",
            )
        return FidelityVerdict.drop(
            message=f"{self.target_label} has no event channels; {channel.key!r} is not written (the DDS profile "
            "writes it as a topic)",
            target_mapping="channel → dropped",
        )

    def operation_verdicts(self, operation: Operation) -> List[FidelityVerdict]:
        """The operation, its HTTP binding and streaming — or, under ``dds``, a ``DROP``."""
        if operation.kind in _EVENT_OPERATION_KINDS:
            return [FidelityVerdict.drop(
                message=f"{self.target_label} has no event vocabulary; {operation.kind.value} operation "
                f"{operation.key!r} is dropped" + (" (its channel is a DDS topic)" if self._dds else ""),
                target_mapping="event operation → dropped",
            )]
        if self._dds:
            return [FidelityVerdict.drop(
                message=f"{self.target_label} (DDS) writes data types only; {operation.key!r} is not written",
                target_mapping="operation → dropped (DDS profile)",
            )]
        verdicts = [self.operation_verdict(operation)]
        if is_http_operation(operation) and not self._corba_source:
            verdicts.append(FidelityVerdict.drop(
                message=f"{self.target_label} has no HTTP binding; the method, path, status codes and parameter "
                f"locations of {operation.key!r} are not written",
                target_mapping="HTTP binding → dropped",
            ))
        if operation.streaming is not StreamingMode.NONE:
            verdicts.append(FidelityVerdict.drop(
                message=f"{self.target_label} operations do not stream; {operation.key!r} is written as one call",
                target_mapping="stream → single call",
            ))
        rekeyed = self._rekeyed(operation.key, self._operation_key(operation), "operation")
        if rekeyed:
            verdicts.append(rekeyed)
        commented = [key for key in (p.key for p in operation.parameters) if key in self._writer.commented]
        if commented:
            verdicts.append(FidelityVerdict.approx(
                message=f"{self.target_label} has no validation; the parameter constraints of {operation.key!r} "
                "are written as a comment above it, not enforced",
                target_mapping="constraints → comment",
            ))
        return verdicts

    def operation_verdict(self, operation: Operation) -> FidelityVerdict:
        if is_http_operation(operation):
            return FidelityVerdict.approx(
                message=f"{self.target_label} has no HTTP binding; {operation.key!r} is written as an IDL operation",
                target_mapping="HTTP operation → IDL operation",
            )
        if self._renamed(operation.name):
            return self._rename_verdict("operation", operation.name)
        verdict = super().operation_verdict(operation)
        if verdict.kind is LossinessKind.OK and not self._corba_source:
            return FidelityVerdict.approx(
                message=f"{self.target_label}: {operation.key!r} is written as an IDL operation — `in` arguments, the "
                "first success response as its return type, and only exception types raised",
                severity=LossinessSeverity.INFO,
                target_mapping="operation → IDL operation",
            )
        return verdict

    # -- types and fields ---------------------------------------------------------

    def type_verdicts(self, type_: Type) -> List[FidelityVerdict]:
        """The type's verdict, a union's synthesized discriminator, and a typedef's constraint comment."""
        verdicts = [self.type_verdict(type_)]
        if type_.kind is TypeKind.UNION:
            verdicts.append(FidelityVerdict.synth(
                message=f"{self.target_label} unions are discriminated; {type_.key!r} is switched on a "
                f"synthesized {self._writer._names.get(type_.key, type_.name)}Kind enum, one case per member",
                severity=LossinessSeverity.INFO,
                target_mapping="union → discriminated union",
            ))
        if type_.key in self._writer.commented:
            verdicts.append(self._comment_verdict(type_.key))
        if type_.kind is TypeKind.MAP and not self._corba_source:
            verdicts.append(FidelityVerdict.drop(
                message=f"{self.target_label}: the map {type_.key!r} is a typedef of its entry sequence, so it is "
                "not a type of its own when read back",
                severity=LossinessSeverity.INFO,
                target_mapping="map declaration → typedef",
            ))
        rekeyed = self._rekeyed(type_.key, self._type_key(type_), "type")
        if rekeyed:
            verdicts.append(rekeyed)
        return verdicts

    def type_verdict(self, type_: Type) -> FidelityVerdict:
        if type_.kind is TypeKind.MAP:
            return FidelityVerdict.approx(
                message=f"{self.target_label} has no portable map (IDL 4.2 `map` is not read by CORBA compilers); "
                f"{type_.key!r} is written as a sequence of key/value entry structs",
                target_mapping="map → sequence<Entry>",
            )
        if type_.kind is TypeKind.SCALAR and type_.constraints is not None:
            # A named scalar's constraints are the typedef's comment (type_verdicts), not a separate loss.
            verdict = FidelityVerdict.ok(message=f"scalar carried to {self.target_label} as a typedef")
        else:
            verdict = super().type_verdict(type_)
        if verdict.kind is LossinessKind.OK and self._renamed(type_.name):
            return self._rename_verdict("type", type_.name)
        re_read = type_.kind in (TypeKind.RECORD, TypeKind.ENUM)
        if verdict.kind is LossinessKind.OK and not self._corba_source and re_read:
            return FidelityVerdict.approx(
                message=f"{self.target_label}: {type_.key!r} is written as an IDL "
                f"{'enum' if type_.kind is TypeKind.ENUM else 'struct'} — members in order, IDL types, "
                "and no descriptions",
                severity=LossinessSeverity.INFO,
                target_mapping=f"{type_.kind.value} → IDL {'enum' if type_.kind is TypeKind.ENUM else 'struct'}",
            )
        return verdict

    def field_verdicts(self, field: CanonicalField) -> List[FidelityVerdict]:
        """The capability verdicts, plus an ``APPROX`` when the writer renames the member."""
        verdicts = super().field_verdicts(field)
        if self._renamed(field.name):
            verdicts.append(self._rename_verdict("member", field.name))
        return verdicts

    def _constraints_verdict(self, field: CanonicalField) -> Optional[FidelityVerdict]:
        """A bound is represented (nothing to report); anything else is the member's comment."""
        if field.key in self._writer.commented:
            return self._comment_verdict(field.key)
        return None

    def _comment_verdict(self, key: str) -> FidelityVerdict:
        bounds = sorted(self._writer.bounded.get(key, ()))
        written_as = f" ({', '.join(bounds)} is written as an IDL bound)" if bounds else ""
        return FidelityVerdict.approx(
            message=f"{self.target_label} has no validation; the constraints of {key!r} are written as a comment "
            f"({self._writer.commented[key]}), not enforced{written_as}",
            target_mapping="constraints → comment",
        )


class CorbaIdlEmitOptions(EmitOptions):
    """Per-target options for :class:`CorbaIdlEmitter`."""

    include_comments: bool = Field(
        default=True,
        description="Emit brief generated-file header comments.",
    )
    profile: Literal["corba", "dds"] = Field(
        default="corba",
        description="`corba` writes interfaces and exceptions; `dds` writes the topic-friendly data-type "
        "subset (no interfaces, exceptions or recursive members) with `@key` on identifier fields.",
    )
    module: Optional[str] = Field(
        default=None,
        description="Module path to write the definitions in (`acme::orders` or `acme.orders`). Defaults to "
        "a CORBA source's own module, else the API namespace, else the API name.",
    )
    key_fields: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="DDS profile: the `@key` fields per type name (`{\"Order\": [\"id\"]}`). A type not "
        "listed keys its identifier field — `id`, `<type>Id` or `<type>_id`.",
    )


class CorbaIdlEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as an OMG IDL 4.2 ``.idl`` document (CORBA or DDS profile)."""

    key = "corbaidl"
    format = "corbaidl"
    label = "CORBA IDL"
    description = "Export as an OMG IDL 4.2 definition (.idl) for CORBA or DDS."
    icon = "network"
    paradigm = ApiParadigm.RPC
    multi_file = False
    options_model = CorbaIdlEmitOptions

    OUTPUT_MEDIA_TYPE = "text/plain"

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        # MFX-28.2: unions are written as discriminated unions and nullable members as ``@optional``,
        # so both are carried; IDL has no field ids, so a source's field numbers are dropped.
        return CapabilityProfile(
            operations=True,
            events=False,
            unions=True,
            nullability=True,
            field_identity=False,
        )

    @classmethod
    def fidelity_rule_pack(cls) -> type[CapabilityRulePack]:
        return CorbaIdlFidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[CorbaIdlEmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        options = (
            opts
            if isinstance(opts, CorbaIdlEmitOptions)
            else CorbaIdlEmitOptions.model_validate(opts.model_dump() if opts else {})
        )
        writer = _CorbaIdlWriter(api, options)
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
        )


# ===========================================================================
# Identifiers
# ===========================================================================


def idl_identifier(name: Optional[str], fallback: str = "x") -> str:
    """A name an IDL compiler accepts: ASCII letters, digits and ``_``, starting with a letter, no keyword.

    A leading ``_`` is dropped (in IDL it escapes a keyword rather than being part of the name), a
    leading digit gets an ``n`` prefix, and a keyword (compared case-insensitively) a ``_`` suffix.

    Args:
        name: The source name (``com.acme.Order``, ``order-id``, ``module``).
        fallback: Used when nothing of the name survives; must itself be a valid identifier.

    Returns:
        The identifier (``com_acme_Order``, ``order_id``, ``module_``).
    """
    ident = re.sub(r"[^A-Za-z0-9_]+", "_", name or "").strip("_") or fallback
    if ident[0].isdigit():
        ident = f"n{ident}"
    while ident.lower() in OMG_IDL_KEYWORDS:
        ident = f"{ident}_"
    return ident


class _Scope:
    """Identifiers declared in one IDL scope, unique case-insensitively (a module, a struct, …)."""

    def __init__(self, enclosing: Optional[str] = None) -> None:
        # A member may not be named like its enclosing scope either (``struct S { long s; }`` is refused).
        self._taken: Set[str] = {enclosing.lower()} if enclosing else set()

    def taken(self, name: str) -> bool:
        """Whether ``name`` (compared case-insensitively) is already declared here."""
        return name.lower() in self._taken

    def claim(self, name: Optional[str], fallback: str = "x") -> str:
        """The identifier for ``name`` in this scope, suffixed ``2``, ``3`` … when already taken."""
        base = idl_identifier(name, fallback)
        candidate, suffix = base, 2
        while self.taken(candidate):
            candidate, suffix = f"{base}{suffix}", suffix + 1
        self._taken.add(candidate.lower())
        return candidate


def _sequence(inner: str, bound: Optional[int] = None) -> str:
    """``sequence<inner>`` — with a space before a closing ``>`` so ``>>`` never lexes as a shift."""
    bound_part = f", {bound}" if bound is not None else ""
    return f"sequence<{inner}{bound_part}{' ' if inner.endswith('>') else ''}>"


# ===========================================================================
# Writer
# ===========================================================================

_IN_PROGRESS = "in-progress"
_DONE = "done"
_SKIPPED = "skipped"


class _CorbaIdlWriter:
    """Render a canonical model as OMG IDL that a reference IDL compiler accepts (MFX-28.1).

    Types are declared on demand, depth first: a definition's dependencies are written before it, so
    the document never uses a type before its declaration. A reference back to a type still being
    defined is recursion — legal in IDL only through a sequence inside that type's own definition,
    so the type is forward-declared there; a direct self-reference becomes a one-element bounded
    sequence, and mutual recursion (or any recursion in the DDS profile) drops the member.
    """

    def __init__(self, api: CanonicalApi, options: CorbaIdlEmitOptions) -> None:
        self._api = api
        self._options = options
        self._dds = options.profile == "dds"
        self._corba_source = api.format == "corbaidl"
        self.tracker = ProvenanceTracker()
        self.losses = LossTracker()
        self.output_path = _output_path(api)

        self._types_by_key = {t.key: t for t in api.types}
        self._types_by_name: Dict[str, Type] = {}
        for type_ in api.types:
            self._types_by_name.setdefault(type_.name, type_)

        self._module_path = self._resolve_module_path()
        self._prefix = "::" + "".join(f"{segment}::" for segment in self._module_path)
        self._top = _Scope(self._module_path[-1] if self._module_path else None)

        # A CORBA source's typedefs are written back as it spelled them.
        typedefs = api.extras.get("corbaidl_typedefs") if self._corba_source else None
        self._source_typedefs: Dict[str, str] = dict(typedefs) if isinstance(typedefs, dict) else {}
        self._typedef_names = {name: self._top.claim(name, "Alias") for name in sorted(self._source_typedefs)}

        # Every type's name is claimed up front, so names do not depend on declaration order.
        self._names: Dict[str, str] = {}
        for type_ in api.types:
            self._names[type_.key] = self._top.claim(type_.name, "Type")
            if self._names[type_.key] != type_.name:
                self.losses.record(
                    LossKind.INFERRED,
                    "renamed-type",
                    f"IDL type names are identifiers unique in their module; {type_.name!r} is written as "
                    f"{self._names[type_.key]!r}.",
                    pointer=type_.key,
                )
        self._interfaces = self._interface_sources()
        self._interface_names = [self._top.claim(name, "Interface") for name, _ in self._interfaces]
        self._exceptions = set() if self._dds else self._exception_types()

        self._state: Dict[str, str] = {}
        self._stack: List[str] = []
        self._forward: List[str] = []
        self._definitions: List[List[str]] = []
        self._sequence_typedefs: Dict[str, str] = {}
        #: Construct key → the constraint attributes written as an IDL bound (``string<N>``,
        #: ``sequence<T, N>``) — represented, not lost (MFX-28.2).
        self.bounded: Dict[str, Set[str]] = {}
        #: Construct key → the ``constraints: …`` text written as a comment above it (MFX-28.2).
        self.commented: Dict[str, str] = {}
        #: Channel key → the payload type its DDS topic is written for (DDS profile, MFX-28.2).
        self.topics: Dict[str, Optional[str]] = {}
        self._op_comments: List[str] = []
        #: Operation key → the IDL operation name written (the pack predicts re-import keys, MFX-28.2).
        self.operation_names: Dict[str, str] = {}
        #: Map type key → its ``<Map>Entry`` struct; union type key → its ``<Union>Kind`` enum.
        self.entry_names: Dict[str, str] = {}
        self.kind_names: Dict[str, str] = {}

    @property
    def module_path(self) -> List[str]:
        """The module path the definitions are written in (outermost first)."""
        return list(self._module_path)

    @property
    def type_names(self) -> Dict[str, str]:
        """Type key → the name the type is declared under."""
        return dict(self._names)

    def interface_names(self) -> Dict[str, str]:
        """Service key → the interface it is written as (canonical services only)."""
        return {
            source.key: name
            for (_, source), name in zip(self._interfaces, self._interface_names)
            if isinstance(source, Service)
        }

    # ------------------------------------------------------------------
    # Document
    # ------------------------------------------------------------------

    def render(self) -> str:
        """The whole ``.idl`` document."""
        for name in sorted(self._source_typedefs):
            self._declare_source_typedef(name)
        for type_ in self._api.types:
            self._declare(type_)

        if self._dds:
            for name, _ in self._interfaces:
                self.losses.record(
                    LossKind.NA,
                    "interface-dropped",
                    f"The DDS profile writes data types only; interface {name!r} is not written.",
                    pointer=name,
                )
        else:
            for (_, source), name in zip(self._interfaces, self._interface_names):
                self._definitions.append(self._render_interface(name, source))

        for channel in self._api.channels:
            if self._dds:
                self._definitions.append(self._render_topic(channel))
            else:
                self.losses.record(
                    LossKind.NA,
                    "channels-dropped",
                    f"CORBA IDL has no event channels; {channel.key!r} is not written (the DDS profile writes it "
                    "as a topic).",
                    pointer=channel.key,
                )

        if not self._definitions:
            if self._dds:
                raise EmitPreconditionError(
                    "OMG IDL export with the DDS profile needs at least one data type (a record, union, enum "
                    "or alias); this source has none."
                )
            raise EmitPreconditionError(
                "OMG IDL export needs at least one type or service to declare; this source has neither."
            )

        body: List[str] = list(self._forward)
        if self._forward:
            body.append("")
        for definition in self._definitions:
            body.extend(definition)
            body.append("")
        while body and not body[-1]:
            body.pop()

        lines: List[str] = []
        if self._options.include_comments:
            title = " ".join(str(self._api.identity.name or "Exported API").split())
            profile = "DDS" if self._dds else "CORBA"
            lines.append(f"// Generated OMG IDL 4.2 ({profile} profile) for {title}")
            lines.append("")
        indent = ""
        for segment in self._module_path:
            lines.append(f"{indent}module {segment} {{")
            indent += "  "
        lines.extend(f"{indent}{line}" if line else "" for line in body)
        for depth in range(len(self._module_path) - 1, -1, -1):
            lines.append(f"{'  ' * depth}}};")
        return "\n".join(lines).rstrip() + "\n"

    def _resolve_module_path(self) -> List[str]:
        """The module path: the option, a CORBA source's own module (or none), the namespace, the name."""
        if self._options.module:
            raw = self._options.module
        elif self._corba_source:
            module = self._api.extras.get("corbaidl_module")
            if not isinstance(module, str) or not module:
                return []
            raw = module
        else:
            raw = self._api.identity.namespace or self._api.identity.name or "Api"
        raw = re.sub(r"^[A-Za-z][A-Za-z0-9+.-]*://", "", str(raw))
        path: List[str] = []
        for part in re.split(r"::|[./:\\]+", raw):
            if not part.strip():
                continue
            # A module may not be named like the module enclosing it.
            path.append(_Scope(path[-1] if path else None).claim(part, "Module"))
        path = path or ["Api"]
        # Nor may a definition be named like its module: rename the module rather than the type
        # (a ``Product`` API whose main type is ``Product`` is written in ``module ProductModule``).
        typedefs = self._api.extras.get("corbaidl_typedefs") if self._corba_source else None
        declared = [t.name for t in self._api.types] + [name for name, _ in self._interface_sources()]
        declared += list(typedefs) if isinstance(typedefs, dict) else []
        taken = {idl_identifier(name).lower() for name in declared}
        if path[-1].lower() in taken:
            scope = _Scope(path[-2] if len(path) > 1 else None)
            for name in taken:
                scope.claim(name)
            renamed = scope.claim(f"{path[-1]}Module")
            self.losses.record(
                LossKind.INFERRED,
                "renamed-module",
                f"An IDL definition may not be named like its module; module {path[-1]!r} is written as {renamed!r}.",
            )
            path[-1] = renamed
        return path

    def _scoped(self, name: str) -> str:
        """The fully scoped name of a definition in the module (``::com::acme::Order``)."""
        return f"{self._prefix}{name}"

    # ------------------------------------------------------------------
    # Types
    # ------------------------------------------------------------------

    def _exception_types(self) -> Set[str]:
        """Keys of the types written as ``exception``: a CORBA source's own, and — for any other
        source — a record only ever returned as an error (IDL exceptions cannot be used as types)."""
        exceptions = {t.key for t in self._api.types if t.extras.get("corbaidl_kind") == "exception"}
        if self._corba_source:
            return exceptions
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
            for ref in [field.type for field in type_.fields] + [type_.aliased, type_.key_type, type_.value_type]:
                key = self._type_key(ref)
                if key is not None:
                    used.add(key)
            for member in type_.union_members:
                key = self._type_key(TypeRef(name=member))
                if key is not None:
                    used.add(key)
        for key in thrown - used:
            if self._types_by_key[key].kind is TypeKind.RECORD:
                exceptions.add(key)
        return exceptions

    def _lookup(self, name: Optional[str]) -> Optional[Type]:
        """The declared type a reference names (by key, else by name)."""
        if not name:
            return None
        return self._types_by_key.get(name) or self._types_by_name.get(name)

    def _type_key(self, ref: Optional[TypeRef]) -> Optional[str]:
        while ref is not None and ref.item is not None:
            ref = ref.item
        target = self._lookup(ref.name) if ref is not None else None
        return target.key if target is not None else None

    def _declare(self, type_: Type) -> None:
        """Write ``type_`` (and, first, everything it uses) unless it is written or being written."""
        if type_.key in self._state:
            return
        self._state[type_.key] = _IN_PROGRESS
        corba_kind = type_.extras.get("corbaidl_kind")
        if type_.kind is TypeKind.ENUM or corba_kind == "enum":
            lines = self._render_enum(type_)
        elif type_.key in self._exceptions:
            if corba_kind != "exception":
                self.losses.record(
                    LossKind.INFERRED,
                    "struct-as-exception",
                    f"{type_.key!r} is only returned as an error, so it is written as an IDL exception.",
                    pointer=type_.key,
                )
            lines = self._render_struct(type_, keyword="exception")
        elif type_.kind is TypeKind.UNION:
            lines = self._render_union(type_)
        elif type_.kind is TypeKind.RECORD:
            lines = self._render_struct(type_, keyword="struct")
        elif type_.kind in (TypeKind.ALIAS, TypeKind.SCALAR):
            lines = self._render_typedef(type_)
        elif type_.kind is TypeKind.MAP:
            lines = self._render_map(type_)
        else:
            self.losses.record(
                LossKind.NA,
                "unsupported-type",
                f"Type {type_.key!r} ({type_.kind.value}) has no OMG IDL representation and is skipped",
                pointer=type_.key,
            )
            self._state[type_.key] = _SKIPPED
            return
        self._definitions.append(lines)
        self._state[type_.key] = _DONE
        self.tracker.record(type_.key, Provenance.SOURCE)

    def _forward_declare(self, type_: Type) -> None:
        line = f"{'union' if type_.kind is TypeKind.UNION else 'struct'} {self._names[type_.key]};"
        if line not in self._forward:
            self._forward.append(line)

    def _render_enum(self, type_: Type) -> List[str]:
        """``enum`` — enumerators live in the module's scope, so a clash is prefixed with the enum's name."""
        name = self._names[type_.key]
        enumerators: List[str] = []
        renumbered = False
        for index, value in enumerate(type_.enum_values):
            candidate = idl_identifier(value.name, "VALUE")
            if self._top.taken(candidate):
                candidate = f"{name}_{candidate}"
            enumerator = self._top.claim(candidate, "VALUE")
            if enumerator != value.name:
                self.losses.record(
                    LossKind.INFERRED,
                    "renamed-enumerator",
                    f"IDL enumerators are identifiers unique in their module; {value.name!r} of {type_.key!r} "
                    f"is written as {enumerator!r}.",
                    pointer=value.key,
                )
            if isinstance(value.value, (int, float)) and not isinstance(value.value, bool) and value.value != index:
                renumbered = True
            enumerators.append(enumerator)
        if renumbered:
            self.losses.record(
                LossKind.NA,
                "enum-values-dropped",
                f"IDL enumerators are ordinal; the values of {type_.key!r} are not written (members keep their "
                "names and order).",
                pointer=type_.key,
            )
        if not enumerators:
            enumerators.append(self._top.claim(f"{name}_UNKNOWN"))
            self.losses.record(
                LossKind.INFERRED,
                "empty-enum-placeholder",
                f"An IDL enum needs an enumerator; {type_.key!r} has none, so {enumerators[0]!r} is written.",
                pointer=type_.key,
            )
        return [f"enum {name} {{"] + [f"  {item}," for item in enumerators[:-1]] + [f"  {enumerators[-1]}", "};"]

    def _ordered_fields(self, type_: Type) -> List[CanonicalField]:
        """The fields in declaration order: by field number where the source has one."""
        indexed = list(enumerate(type_.fields))
        indexed.sort(key=lambda pair: (pair[1].field_number is None, pair[1].field_number or 0, pair[0]))
        return [field for _, field in indexed]

    def _render_struct(self, type_: Type, *, keyword: str) -> List[str]:
        """``struct`` / ``exception`` with ``@optional`` (and, in the DDS profile, ``@key``) members."""
        name = self._names[type_.key]
        keys = self._key_fields(type_) if self._dds and keyword == "struct" else set()
        scope = _Scope(name)
        members: List[str] = []
        self._stack.append(type_.key)
        for field in self._ordered_fields(type_):
            expr = self._member_expr(field)
            if expr is None:
                continue
            expr = self._bounded(expr, field)
            members.extend(self._comment_lines(field.constraints, field.key, "  "))
            member = self._member_name(scope, field)
            annotations = []
            if field.name in keys and not expr.startswith("sequence<"):
                annotations.append("@key")
            elif field.type.nullable and keyword == "struct":
                annotations.append("@optional")
            members.append(f"  {''.join(a + ' ' for a in annotations)}{expr} {member};")
            self.tracker.record(field.key, Provenance.SOURCE)
        self._stack.pop()
        if not members and keyword == "struct":
            members.append(f"  octet {scope.claim('reserved')};")
            self.losses.record(
                LossKind.INFERRED,
                "empty-struct-placeholder",
                f"An IDL struct needs a member; {type_.key!r} has none, so an octet placeholder is written.",
                pointer=type_.key,
            )
        return [f"{keyword} {name} {{"] + members + ["};"]

    def _key_fields(self, type_: Type) -> Set[str]:
        """The field names marked ``@key`` (DDS profile): the option's, else the identifier field."""
        explicit = self._options.key_fields.get(type_.name)
        names = {field.name for field in type_.fields}
        if explicit is not None:
            for missing in sorted(set(explicit) - names):
                self.losses.record(
                    LossKind.NA,
                    "key-field-missing",
                    f"Key field {missing!r} is not a field of {type_.key!r}; it is not marked @key.",
                    pointer=type_.key,
                )
            return set(explicit) & names
        lowered = type_.name.lower()
        identifiers = {"id", f"{lowered}id", f"{lowered}_id"}
        return {field.name for field in type_.fields if field.name.lower() in identifiers}

    def _member_name(self, scope: _Scope, field: CanonicalField) -> str:
        member = scope.claim(field.name, "field")
        if member != field.name:
            self.losses.record(
                LossKind.INFERRED,
                "renamed-field",
                f"IDL member names are identifiers unique (case-insensitively) in their type; {field.name!r} "
                f"is written as {member!r}.",
                pointer=field.key,
            )
        return member

    def _member_expr(self, field: CanonicalField) -> Optional[str]:
        """A member's type expression, or ``None`` when the member cannot be written (recursion)."""
        type_expr = field.extras.get("corbaidl_type_expr")
        if self._corba_source and isinstance(type_expr, str) and type_expr:
            return self._source_expr(type_expr)
        fmt = field.constraints.format if field.constraints is not None else None
        expr = self._expr(field.type, fmt)
        if expr is None:
            self.losses.record(
                LossKind.NA,
                "recursive-member-dropped",
                f"IDL allows recursion only through a sequence inside the type's own definition"
                f"{' and the DDS profile writes none' if self._dds else ''}; {field.key!r} is not written.",
                pointer=field.key,
            )
        return expr

    def _render_union(self, type_: Type) -> List[str]:
        """A discriminated ``union`` switched on a synthesized ``<Union>Kind`` enum, one case per member."""
        name = self._names[type_.key]
        branches: List[Tuple[str, Optional[str], str]] = []
        self._stack.append(type_.key)
        if type_.fields:
            for field in self._ordered_fields(type_):
                expr = self._member_expr(field)
                branches.append((field.name, self._bounded(expr, field) if expr else expr, field.key))
        else:
            for member in type_.union_members:
                short = member.split(".")[-1]
                target = self._lookup(member)
                label = self._names[target.key] if target is not None else short
                expr = self._expr(TypeRef(name=member))
                if expr is None:
                    self.losses.record(
                        LossKind.NA,
                        "recursive-member-dropped",
                        f"IDL allows recursion only through a sequence inside the type's own definition; member "
                        f"{member!r} of {type_.key!r} is not written.",
                        pointer=type_.key,
                    )
                branches.append((label[:1].lower() + label[1:], expr, type_.key))
            if type_.union_members:
                self.losses.record(
                    LossKind.INFERRED,
                    "union-member-cases",
                    f"The members of union {type_.key!r} are written as one case each of a discriminated union.",
                    pointer=type_.key,
                )
        self._stack.pop()
        written = [(label, expr, pointer) for label, expr, pointer in branches if expr is not None]
        if all(expr == "void" for _, expr, _ in written):
            self.losses.record(
                LossKind.INFERRED,
                "empty-union-placeholder",
                f"An IDL union needs a case; {type_.key!r} has none, so it is written as a placeholder struct.",
                pointer=type_.key,
            )
            return [f"struct {name} {{", f"  octet {_Scope(name).claim('reserved')};", "};"]

        kind_name = self._top.claim(f"{name}Kind")
        self.kind_names[type_.key] = kind_name
        scope = _Scope(name)
        cases: List[Tuple[str, str, str]] = []
        for label, expr, pointer in written:
            member = scope.claim(label, "branch")
            enumerator = self._top.claim(f"{name}_{member}")
            cases.append((enumerator, expr, member))
            self.tracker.record(pointer, Provenance.SOURCE)
        lines = [f"enum {kind_name} {{"]
        lines += [f"  {enumerator}," for enumerator, _, _ in cases[:-1]] + [f"  {cases[-1][0]}", "};", ""]
        lines.append(f"union {name} switch ({self._scoped(kind_name)}) {{")
        fields = {field.key: field for field in type_.fields}
        for (enumerator, expr, member), (_, _, pointer) in zip(cases, written):
            # A ``void`` arm carries no data: its discriminator value simply selects no member.
            if expr != "void":
                field = fields.get(pointer)
                if field is not None:
                    lines.extend(self._comment_lines(field.constraints, field.key, "  "))
                lines.append(f"  case {self._scoped(enumerator)}: {expr} {member};")
        lines.append("};")
        return lines

    def _bounded(self, expr: str, field: CanonicalField) -> str:
        """Write a field's ``max_length`` / ``max_items`` as an IDL bound when its type takes one.

        ``string`` becomes ``string<N>`` and an unbounded ``sequence<T>`` becomes ``sequence<T, N>`` — the
        constraint is then represented, not lost (MFX-28.2). A CORBA source's own expression is kept.
        """
        c = field.constraints
        if c is None or (self._corba_source and field.extras.get("corbaidl_type_expr")):
            return expr
        if expr == "string" and isinstance(c.max_length, int) and c.max_length > 0:
            self.bounded.setdefault(field.key, set()).add("max_length")
            return f"string<{c.max_length}>"
        if (
            expr.startswith("sequence<")
            and field.type.item is not None
            and isinstance(c.max_items, int)
            and c.max_items > 0
            and not re.search(r",\s*\d+\s*>$", expr)
        ):
            self.bounded.setdefault(field.key, set()).add("max_items")
            return _sequence(expr[len("sequence<"):-1].rstrip(), c.max_items)
        return expr

    def _comment_lines(
        self, constraints: Any, pointer: str, indent: str, *, label: Optional[str] = None
    ) -> List[str]:
        """A ``// constraints: …`` line for what IDL cannot state (MFX-28.2), recorded as a loss.

        Constraints already written as a bound are left out.

        Args:
            constraints: The member's, parameter's or type's constraints.
            pointer: The construct key the comment and the loss are recorded against.
            indent: The indentation of the line it precedes.
            label: A parameter name the comment is about (operation parameters share one comment block).

        Returns:
            The comment line, or nothing when nothing is left to say.
        """
        if constraints is None:
            return []
        bounded = self.bounded.get(pointer, set())
        remaining = constraints.model_copy(update={attr: None for attr in bounded}) if bounded else constraints
        comment = constraint_comment(remaining)
        if comment is None:
            return []
        if label:
            comment = f"{label} {comment}"
        self.commented[pointer] = comment
        self.losses.record(
            LossKind.INFERRED,
            "constraints-as-comment",
            f"IDL has no validation; the constraints of {pointer!r} are written as a comment ({comment}).",
            pointer=pointer,
        )
        return [f"{indent}// {comment}"]

    def _render_topic(self, channel: Any) -> List[str]:
        """DDS profile: a channel is a topic — its payload type is declared and the topic named in a comment.

        A DDS topic is created at run time from a name and a type; IDL declares only the type.
        """
        payload = next(
            (
                message.payload
                for operation in self._api.operations()
                if operation.channel_ref == channel.key
                for message in operation.messages
                if message.payload is not None
            ),
            None,
        )
        expr = self._expr(payload) if payload is not None else None
        self.topics[channel.key] = expr
        self.losses.record(
            LossKind.INFERRED,
            "channel-as-topic",
            f"DDS has no channels in IDL; {channel.key!r} is a topic created at run time"
            + (f" with the type {expr}" if expr else " (no payload type is known)") + "; its name is written as a "
            "comment.",
            pointer=channel.key,
        )
        topic = " ".join(str(channel.address or channel.key).split())
        return [f"// DDS topic \"{topic}\": {expr or 'type unknown'}"]

    def _render_typedef(self, type_: Type) -> List[str]:
        """An alias as ``typedef <aliased> Name;``, a named scalar as a typedef of its IDL type."""
        if type_.kind is TypeKind.ALIAS and type_.aliased is not None:
            fmt = type_.constraints.format if type_.constraints is not None else None
            expr = self._expr(type_.aliased, fmt)
            if expr is None:
                expr = "string"
                self.losses.record(
                    LossKind.INFERRED,
                    "recursive-alias",
                    f"{type_.key!r} refers to itself; it is written as a typedef of string.",
                    pointer=type_.key,
                )
        else:
            fmt = type_.constraints.format if type_.constraints is not None else None
            expr = self._scalar(type_.name, fmt, subject="custom-scalar", pointer=type_.key)
        return self._comment_lines(type_.constraints, type_.key, "") + [f"typedef {expr} {self._names[type_.key]};"]

    def _render_map(self, type_: Type) -> List[str]:
        """A map as ``struct <Map>Entry { K key; V value; }`` plus ``typedef sequence<<Map>Entry> <Map>;``."""
        name = self._names[type_.key]
        self._stack.append(type_.key)
        key_expr = self._expr(type_.key_type or TypeRef(name="string")) or "string"
        value_expr = self._expr(type_.value_type or TypeRef(name="string")) or "string"
        self._stack.pop()
        entry = self._top.claim(f"{name}Entry")
        self.entry_names[type_.key] = entry
        self.losses.record(
            LossKind.INFERRED,
            "map-as-sequence",
            f"IDL has no portable map type; {type_.key!r} is written as a sequence of {entry!r} key/value pairs.",
            pointer=type_.key,
        )
        scope = _Scope(entry)
        return [
            f"struct {entry} {{",
            f"  {key_expr} {scope.claim('key')};",
            f"  {value_expr} {scope.claim('value')};",
            "};",
            "",
            f"typedef {_sequence(self._scoped(entry))} {name};",
        ]

    # ------------------------------------------------------------------
    # Type references
    # ------------------------------------------------------------------

    def _expr(self, ref: TypeRef, fmt: Optional[str] = None, *, in_sequence: bool = False) -> Optional[str]:
        """Render a type reference as an IDL type expression.

        Args:
            ref: The reference (a list, a scalar or a named type).
            fmt: The ``format`` constraint, which picks the width of a JSON Schema ``integer`` / ``number``.
            in_sequence: Whether the reference is a sequence's element (recursion is legal there).

        Returns:
            The expression (``sequence<::acme::Pet>``, ``long long``), or ``None`` when the reference is
            recursion IDL cannot express here.
        """
        if ref.item is not None:
            inner = self._expr(ref.item, fmt, in_sequence=True)
            return _sequence(inner) if inner is not None else None
        target = self._lookup(ref.name)
        if target is None:
            return self._scalar(ref.name, fmt)
        return self._named(target, in_sequence=in_sequence)

    def _named(self, target: Type, *, in_sequence: bool) -> Optional[str]:
        """A reference to a declared type: declare it first, or handle recursion when it is in progress."""
        self._declare(target)
        state = self._state[target.key]
        if state == _DONE:
            return self._scoped(self._names[target.key])
        if state == _SKIPPED:
            return "string"
        if target.kind not in (TypeKind.RECORD, TypeKind.UNION) or target.key in self._exceptions:
            return None
        if self._dds or not self._stack or self._stack[-1] != target.key:
            return None
        self._forward_declare(target)
        scoped = self._scoped(self._names[target.key])
        if in_sequence:
            return scoped
        self.losses.record(
            LossKind.INFERRED,
            "recursive-member-bounded",
            f"IDL allows a type to contain itself only through a sequence; a direct reference of {target.key!r} "
            "to itself is written as a sequence of at most one element.",
            pointer=target.key,
        )
        return _sequence(scoped, 1)

    def _scalar(self, name: Optional[str], fmt: Optional[str] = None, *, subject: str = "unknown-type",
                pointer: Optional[str] = None) -> str:
        """The IDL keyword for a canonical scalar spelling; anything unknown is written as ``string``."""
        if not name:
            return "string"
        if name == "void":
            return "void"
        mapped = target_scalar(name, OMG_IDL_SCALAR_FOR_KIND, fmt)
        if mapped is not None:
            return mapped
        lowered = name.lower()
        if lowered in _STRING_LIKE:
            return "string"
        if lowered in _FREE_FORM:
            self.losses.record(
                LossKind.INFERRED,
                "free-form-as-string",
                f"IDL has no portable free-form value; {name!r} is written as a string (JSON text).",
                pointer=pointer,
            )
            return "string"
        self.losses.record(
            LossKind.INFERRED,
            subject,
            f"The type {name!r} has no IDL equivalent; it is written as a string.",
            pointer=pointer,
        )
        return "string"

    # ------------------------------------------------------------------
    # CORBA sources: their own spelling, scoped
    # ------------------------------------------------------------------

    def _declare_source_typedef(self, name: str) -> None:
        key = f"typedef:{name}"
        if key in self._state:
            return
        self._state[key] = _IN_PROGRESS
        expr = self._source_expr(self._source_typedefs[name])
        self._definitions.append([f"typedef {expr} {self._typedef_names[name]};"])
        if expr.startswith("sequence<"):
            # An operation signature using the same sequence reuses the source's own typedef.
            self._sequence_typedefs.setdefault(expr, self._typedef_names[name])
        self._state[key] = _DONE

    def _source_expr(self, expr: str) -> str:
        """A CORBA source's type expression with every type it names declared first and fully scoped."""

        def scope_name(match: re.Match) -> str:
            word = match.group(0)
            if self._dds and word in _WIDE_TYPES:
                self.losses.record(
                    LossKind.INFERRED,
                    "wide-character-narrowed",
                    f"The DDS profile writes no wide characters; {word!r} is written as {_WIDE_TYPES[word]!r}.",
                )
                return _WIDE_TYPES[word]
            if word in _EXPR_WORDS:
                return word
            if word in self._source_typedefs:
                self._declare_source_typedef(word)
                return self._scoped(self._typedef_names[word])
            target = self._types_by_name.get(word)
            if target is None:
                return word
            self._declare(target)
            if self._state.get(target.key) == _IN_PROGRESS and target.kind in (TypeKind.RECORD, TypeKind.UNION):
                self._forward_declare(target)
            return self._scoped(self._names[target.key])

        scoped = re.sub(r"(?<![\w:])[A-Za-z_]\w*(?![\w:])", scope_name, expr.strip())
        # ``>>`` lexes as a shift operator; the closing brackets of nested sequences need a space.
        return re.sub(r">(?=>)", "> ", scoped)

    # ------------------------------------------------------------------
    # Interfaces
    # ------------------------------------------------------------------

    def _interface_sources(self) -> List[Tuple[str, Any]]:
        """``(name, source)`` per interface: a CORBA source's own interface dicts, else the services."""
        own = self._api.extras.get("corbaidl_interfaces") if self._corba_source else None
        if isinstance(own, list) and own:
            return [(str(item.get("name", "Interface")), item) for item in own if isinstance(item, dict)]
        return [(service.name, service) for service in self._api.services]

    def _render_interface(self, name: str, source: Any) -> List[str]:
        lines = [f"interface {name} {{"]
        scope = _Scope(name)
        if isinstance(source, Service):
            for operation in source.operations:
                self._op_comments = []
                rendered = self._render_operation(operation, scope)
                if rendered:
                    lines.extend(f"  {comment}" for comment in self._op_comments)
                    lines.append(f"  {rendered};")
            self.tracker.record(source.key, Provenance.SOURCE)
        else:
            for operation in source.get("operations", []):
                if isinstance(operation, dict):
                    lines.append(f"  {self._render_source_operation(operation, scope)};")
        lines.append("};")
        return lines

    def _render_source_operation(self, operation: Dict[str, Any], scope: _Scope) -> str:
        """An operation of a CORBA source's interface, as it was declared."""
        declared = str(operation.get("name", "operation"))
        name = scope.claim(declared, "call")
        if name != declared:
            self.losses.record(
                LossKind.INFERRED,
                "renamed-operation",
                f"IDL operation names are identifiers unique (case-insensitively) in their interface and unlike "
                f"its name; {declared!r} is written as {name!r}.",
                pointer=declared,
            )
        params: List[str] = []
        param_scope = _Scope()
        for param in operation.get("parameters", []) or []:
            if not isinstance(param, dict):
                continue
            direction = str(param.get("direction", "in"))
            direction = direction if direction in ("in", "out", "inout") else "in"
            expr = self._signature_type(self._source_expr(str(param.get("type", "string"))))
            params.append(f"{direction} {expr} {param_scope.claim(str(param.get('name', 'arg')), 'arg')}")
        return_type = self._signature_type(self._source_expr(str(operation.get("return_type", "void"))))
        raises = [self._source_expr(str(item)) for item in operation.get("raises", []) or []]
        raises_clause = f" raises ({', '.join(raises)})" if raises else ""
        return f"{return_type} {name}({', '.join(params)}){raises_clause}"

    def _render_operation(self, operation: Operation, scope: _Scope) -> Optional[str]:
        """``<return> name(in T param, …, in Body body) raises (…)`` for a canonical operation."""
        if operation.kind in _EVENT_OPERATION_KINDS:
            self.losses.record(
                LossKind.NA,
                "event-operation-dropped",
                f"IDL interfaces have no events; {operation.kind.value} operation {operation.key!r} is not written.",
                pointer=operation.key,
            )
            return None
        name = scope.claim(operation.name, "call")
        self.operation_names[operation.key] = name
        if name != operation.name:
            self.losses.record(
                LossKind.INFERRED,
                "renamed-operation",
                f"IDL operation names are identifiers unique (case-insensitively) in their interface; "
                f"{operation.name!r} is written as {name!r}.",
                pointer=operation.key,
            )
        if operation.streaming is not StreamingMode.NONE:
            self.losses.record(
                LossKind.NA,
                "streaming-dropped",
                f"IDL operations do not stream; {operation.key!r} is written as one call.",
                pointer=operation.key,
            )
        if is_http_operation(operation) and not self._corba_source:
            self.losses.record(
                LossKind.NA,
                "http-binding-dropped",
                f"IDL has no HTTP binding; the method, path, status codes and parameter locations of "
                f"{operation.key!r} are not written (it is the operation {name!r}).",
                pointer=operation.key,
            )
        for param in operation.parameters:
            self._op_comments.extend(
                self._comment_lines(param.constraints, param.key, "", label=param.name)
            )
        response = _response(operation)
        return_type = (
            self._signature_type(self._expr(response.payload) or "string") if response is not None else "void"
        )
        params: List[str] = []
        param_scope = _Scope()
        for param in operation.parameters:
            fmt = param.constraints.format if param.constraints is not None else None
            expr = self._signature_type(self._expr(param.type, fmt) or "string")
            params.append(f"in {expr} {param_scope.claim(param.name, 'param')}")
        request = next((m for m in operation.messages if m.role is MessageRole.REQUEST), None)
        if request is not None and request.payload is not None:
            expr = self._signature_type(self._expr(request.payload) or "string")
            params.append(f"in {expr} {param_scope.claim('body')}")
        self.tracker.record(operation.key, Provenance.SOURCE)
        return f"{return_type} {name}({', '.join(params)}){self._raises(operation)}"

    def _signature_type(self, expr: str) -> str:
        """An operation's parameter / return type: IDL refuses anonymous sequences there, so one is typedef'd."""
        if not expr.startswith("sequence<"):
            return expr
        name = self._sequence_typedefs.get(expr)
        if name is None:
            words = [word for word in re.findall(r"[A-Za-z]\w*", expr) if word != "sequence"]
            element = words[-1] if words else "Item"
            depth = expr.count("sequence<")
            name = self._top.claim(element[:1].upper() + element[1:] + "Seq" * depth)
            self._sequence_typedefs[expr] = name
            self._definitions.append([f"typedef {expr} {name};"])
        return self._scoped(name)

    def _raises(self, operation: Operation) -> str:
        """`` raises (…)`` for the error responses whose type is an exception; the rest are reported."""
        names: List[str] = []
        for message in operation.messages:
            if message.role is not MessageRole.ERROR or message.payload is None:
                continue
            key = self._type_key(message.payload)
            if key is None or key not in self._exceptions or message.payload.item is not None:
                self.losses.record(
                    LossKind.NA,
                    "raises-dropped",
                    f"IDL operations raise exceptions only; the error response {message.key!r} of "
                    f"{operation.key!r} is not written.",
                    pointer=operation.key,
                )
                continue
            scoped = self._scoped(self._names[key])
            if scoped not in names:
                names.append(scoped)
        return f" raises ({', '.join(names)})" if names else ""


def _response(operation: Operation) -> Optional[Message]:
    """The response an operation returns: the first success response with a body, else the first with one."""
    responses = [m for m in operation.messages if m.role is MessageRole.RESPONSE and m.payload is not None]
    success = [m for m in responses if str(m.status_code or m.extras.get("http_status") or "2").startswith("2")]
    return (success or responses or [None])[0]


def _output_path(api: CanonicalApi) -> str:
    module = api.extras.get("corbaidl_module")
    if isinstance(module, str) and module:
        base = module
    elif api.services:
        base = api.services[0].name
    else:
        base = api.identity.name or "module"
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", base).strip("_") or "module"
    return f"{safe}.idl"


def validate_corbaidl_document(content: str) -> None:
    """Validate OMG IDL text by re-parsing it with the CORBA IDL reader."""
    parse_corbaidl(content)
