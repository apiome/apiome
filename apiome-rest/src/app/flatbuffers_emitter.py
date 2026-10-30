"""FlatBuffers emitter: canonical model → ``.fbs`` schema — MFX-16.1, MFX-30.1 (#4178).

The inverse of :class:`app.flatbuffers_normalizer.FlatBuffersNormalizer` and an implementation of the
:class:`app.emitter.Emitter` SPI. The model's types become one schema that ``flatc`` compiles:

* a record → ``table`` (a ``struct`` when the source declared one and every field fits a struct:
  scalars, enums and other structs); a union → ``union``; an enum → ``enum`` with an underlying integer
  type and its values in ascending order; a list → a vector ``[T]``; a map → a vector of
  ``<Map>Entry`` tables keyed by ``key`` (``(key)``, so a reader can binary-search it);
* scalars → ``bool``, ``byte`` … ``ulong``, ``float``, ``double``, ``string``; bytes → ``[ubyte]``;
  aliases and named scalars are written as what they stand for (FlatBuffers has no typedef);
* what a vector, union or struct cannot hold gets a synthesized wrapper table — a vector of vectors
  (``[[T]]``) becomes ``[<Name>Item]`` with an ``items`` field, a union member that is not a table
  (``string``, a struct) becomes ``<Union><Member>`` with a ``value`` field;
* operations and channels are dropped (types-only).

**Field ids.** Every table field is written with ``(id: N)``, in id order: ids are part of the wire
contract. A ``.fbs`` source keeps its own ids; any other source gets ids assigned by
:class:`~app.flatbuffers_identity.FieldIdAllocator`, which also reuses the ids an earlier export stored
(option ``persisted_field_numbers``, filled from the MFX-12.2 store by the export service) and keeps a
removed field's id as a ``(deprecated)`` placeholder. Newly assigned ids are returned in
:attr:`~app.emitter.EmitResult.field_identity_assignments` for the caller to persist.

**Options:** ``root_type`` (the table a buffer starts with; defaults to the imported one),
``persisted_field_numbers`` and ``include_comments``. Everything the schema cannot say as the source
did is recorded on the :class:`~app.emitter.LossTracker` with the key of the type or field it concerns.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any, Dict, List, Optional, Tuple, Union

from pydantic import Field, field_validator

from .canonical_model import (
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    OperationKind,
    Type,
    TypeKind,
    TypeRef,
)
from .constraint_text import constraint_comment
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
from .fidelity_rulepack import CapabilityRulePack, FidelityVerdict, types_only_advisory
from .flatbuffers_identity import FieldIdAllocator, compact_field_ids
from .lossiness import LossinessKind, LossinessReport, LossinessSeverity
from .writer_loss_rulepack import filed_writer_verdicts

__all__ = ["FlatBuffersEmitOptions", "FlatBuffersEmitter", "FlatBuffersFidelityRulePack"]

#: Canonical scalar name (lower-cased) → (FlatBuffers type, value kind). The kind decides what a field
#: of it may carry: a ``number`` / ``bool`` default, ``required`` (``string`` and ``bytes`` only).
_SCALARS: Dict[str, Tuple[str, str]] = {
    **{name: ("bool", "bool") for name in ("bool", "boolean")},
    **{name: ("byte", "int") for name in ("int8", "i8", "sbyte")},
    **{name: ("ubyte", "int") for name in ("uint8", "u8", "byte")},
    **{name: ("short", "int") for name in ("int16", "i16", "short")},
    **{name: ("ushort", "int") for name in ("uint16", "u16")},
    **{name: ("int", "int") for name in ("int32", "i32", "int", "sint32", "sfixed32")},
    **{name: ("uint", "int") for name in ("uint32", "u32", "fixed32")},
    **{name: ("long", "int") for name in ("int64", "i64", "long", "sint64", "sfixed64", "integer", "bigint")},
    **{name: ("ulong", "int") for name in ("uint64", "u64", "fixed64")},
    **{name: ("float", "float") for name in ("float", "f32", "float32")},
    **{name: ("double", "float") for name in ("double", "f64", "float64", "number", "decimal")},
    **{name: ("string", "string") for name in (
        "string", "str", "text", "char", "id", "uuid", "guid", "uri", "url", "email", "hostname", "ipv4",
        "ipv6", "date", "time", "datetime", "date-time", "timestamp", "instant", "duration",
    )},
    **{name: ("[ubyte]", "bytes") for name in ("bytes", "binary", "blob")},
}
#: Canonical names for "any JSON value": written as opaque bytes.
_ANY_SCALARS = frozenset({"any", "object", "json", "map", "value", "unknown", "variant"})
#: Canonical names for "no value": a field of one is left out.
_NONE_SCALARS = frozenset({"null", "void", "none"})

#: The integer types an enum may use, smallest first, with their ranges.
_INT_RANGES: Dict[str, Tuple[int, int]] = {
    "byte": (-(2**7), 2**7 - 1), "ubyte": (0, 2**8 - 1),
    "short": (-(2**15), 2**15 - 1), "ushort": (0, 2**16 - 1),
    "int": (-(2**31), 2**31 - 1), "uint": (0, 2**32 - 1),
    "long": (-(2**63), 2**63 - 1), "ulong": (0, 2**64 - 1),
}

#: Words ``flatc`` reads as keywords or type names: no declared name may be one.
FBS_KEYWORDS = frozenset({
    "table", "struct", "enum", "union", "namespace", "root_type", "file_identifier", "file_extension",
    "include", "native_include", "attribute", "rpc_service", "true", "false", "null", "nan", "inf",
    "bool", "byte", "ubyte", "short", "ushort", "int", "uint", "float", "long", "ulong", "double",
    "int8", "uint8", "int16", "uint16", "int32", "uint32", "int64", "uint64", "float32", "float64",
    "string",
})

_EVENT_OPERATION_KINDS = frozenset({OperationKind.PUBLISH, OperationKind.SUBSCRIBE})
_TYPES_ONLY_DROP_MESSAGE = "only data schemas are exported"


class FlatBuffersFidelityRulePack(CapabilityRulePack):
    """Fidelity rules for FlatBuffers export — MFX-30.3 (#4180).

    The pack builds the schema with the FlatBuffers writer (default options) and files each loss the
    writer records on the type or field it concerns, so the report names exactly what the export does:

    * **types-only** — every operation and channel is a critical ``DROP``, and a source that has any
      carries the critical root advisory with counts (:func:`~app.fidelity_rulepack.types_only_advisory`);
    * **constraints** — written as a ``//`` comment that nothing checks, ``APPROX``;
    * **maps** — a vector of ``<Map>Entry`` key/value tables, ``APPROX``;
    * **field ids** — an id the source does not give is ``SYNTH`` (a ``.fbs`` source keeps its own);
      synthesized wrapper tables are ``SYNTH`` too;
    * structs written as tables, renumbered or empty enums, inlined aliases, opaque or unmapped values and
      respelled names (info) are ``APPROX``; a field of no value, a default FlatBuffers cannot hold and a
      root type that is not a table are ``DROP``.
    """

    target_label = "FlatBuffers"

    #: Writer loss subject → (verdict kind, severity).
    _WRITER_LOSSES = {
        "constraints-as-comment": (LossinessKind.APPROX, LossinessSeverity.WARN),
        "constraints-dropped": (LossinessKind.DROP, LossinessSeverity.WARN),
        "map-as-vector": (LossinessKind.APPROX, LossinessSeverity.WARN),
        "map-key-as-string": (LossinessKind.APPROX, LossinessSeverity.WARN),
        "synthesized-field-id": (LossinessKind.SYNTH, LossinessSeverity.INFO),
        "table-synthesized": (LossinessKind.SYNTH, LossinessSeverity.INFO),
        "struct-as-table": (LossinessKind.APPROX, LossinessSeverity.INFO),
        "empty-enum": (LossinessKind.APPROX, LossinessSeverity.WARN),
        "enum-renumbered": (LossinessKind.APPROX, LossinessSeverity.WARN),
        "alias-inlined": (LossinessKind.APPROX, LossinessSeverity.INFO),
        "opaque-value": (LossinessKind.APPROX, LossinessSeverity.WARN),
        "unmapped-scalar": (LossinessKind.APPROX, LossinessSeverity.WARN),
        "name-respelled": (LossinessKind.APPROX, LossinessSeverity.INFO),
        "field-dropped": (LossinessKind.DROP, LossinessSeverity.WARN),
        "default-dropped": (LossinessKind.DROP, LossinessSeverity.WARN),
        "root-type-dropped": (LossinessKind.DROP, LossinessSeverity.WARN),
    }
    #: Set by :meth:`evaluate`: construct key → the verdicts of its writer losses.
    _filed: Dict[str, List[FidelityVerdict]] = {}

    def evaluate(self, api: CanonicalApi) -> LossinessReport:
        """Build the schema once (as it will be emitted), file its losses by construct, then walk the model."""
        writer = _FlatBuffersWriter(api, FlatBuffersEmitOptions())
        try:
            writer.render()
        except EmitPreconditionError:
            pass  # refused at export too; the capability verdicts still describe the model
        self._filed = filed_writer_verdicts(api, writer.losses.records(), self._WRITER_LOSSES)
        return super().evaluate(api)

    def root_verdicts(self, api: CanonicalApi) -> List[FidelityVerdict]:
        """The types-only advisory, then what the writer changed at the schema level (namespace, root type)."""
        advisory = types_only_advisory(api, target_label=self.target_label, keep_in="OpenAPI or AsyncAPI")
        return ([advisory] if advisory is not None else []) + self._filed.get("", [])

    def type_verdicts(self, type_: Type) -> List[FidelityVerdict]:
        return super().type_verdicts(type_) + self._filed.get(type_.key, [])

    def field_verdicts(self, field: CanonicalField) -> List[FidelityVerdict]:
        return super().field_verdicts(field) + self._filed.get(field.key, [])

    def _constraints_verdict(self, field: CanonicalField) -> Optional[FidelityVerdict]:
        """Reported from the writer, which says what it wrote (a comment, or nothing)."""
        return None

    def _field_identity_verdict(self, field: CanonicalField) -> Optional[FidelityVerdict]:
        """Reported from the writer, which knows the ids a ``.fbs`` source gives."""
        return None

    def operation_verdict(self, operation) -> FidelityVerdict:
        return FidelityVerdict.drop(
            message=f"{self.target_label} is types-only — {_TYPES_ONLY_DROP_MESSAGE}; "
            f"the {operation.kind.value} operation is dropped",
            target_mapping="operation → dropped (types-only export)",
        )

    def channel_verdict(self, channel) -> FidelityVerdict:
        return FidelityVerdict.drop(
            message=f"{self.target_label} is types-only — {_TYPES_ONLY_DROP_MESSAGE}; "
            "the event channel is dropped",
            target_mapping="channel → dropped (types-only export)",
        )


class FlatBuffersEmitOptions(EmitOptions):
    """Per-target options for :class:`FlatBuffersEmitter`."""

    include_comments: bool = Field(
        default=True,
        description="Emit a generated-file header and type / field descriptions as `///` comments.",
    )
    root_type: Optional[str] = Field(
        default=None,
        description="The table a buffer starts with (`root_type`), by type name or key; defaults to the "
        "imported schema's root type.",
    )
    persisted_field_numbers: Dict[str, int] = Field(
        default_factory=dict,
        description="Field ids stored by earlier exports (`<field key> → id`); filled by the export service "
        "so a re-export writes the same ids.",
    )

    @field_validator("root_type")
    @classmethod
    def _blank_root_type(cls, value: Optional[str]) -> Optional[str]:
        """A blank root type means the default."""
        return value.strip() if value and value.strip() else None


class FlatBuffersEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as a FlatBuffers ``.fbs`` schema."""

    key = "flatbuffers"
    format = "flatbuffers"
    label = "FlatBuffers"
    description = "Export as a FlatBuffers schema (.fbs): tables, structs, enums and unions with stable field ids."
    icon = "boxes"
    paradigm = ApiParadigm.DATA_SCHEMA
    multi_file = False
    options_model = FlatBuffersEmitOptions

    OUTPUT_MEDIA_TYPE = "text/x-flatbuffers"

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        return CapabilityProfile(
            operations=False,
            events=False,
            unions=True,
            nullability=False,
            field_identity=True,
        )

    @classmethod
    def fidelity_rule_pack(cls) -> type[CapabilityRulePack]:
        return FlatBuffersFidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[FlatBuffersEmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        options = (
            opts
            if isinstance(opts, FlatBuffersEmitOptions)
            else FlatBuffersEmitOptions.model_validate(opts.model_dump() if opts else {})
        )
        writer = _FlatBuffersWriter(api, options)
        content = writer.render()
        return EmitResult(
            files=[EmittedFile(path=writer.output_path, content=content, media_type=self.OUTPUT_MEDIA_TYPE)],
            media_type=self.OUTPUT_MEDIA_TYPE,
            provenance=writer.tracker.records(),
            losses=writer.losses.records(),
            field_identity_assignments=writer.field_identity_assignments,
        )


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------


def fbs_identifier(name: str, *, fallback: str = "value") -> str:
    """``name`` as a FlatBuffers identifier: word characters, not starting with a digit, not a keyword.

    ``order-id`` → ``order_id``, ``2fa`` → ``_2fa``, ``string`` → ``string_``.
    """
    word = re.sub(r"[^A-Za-z0-9_]+", "_", name or "").strip("_") or fallback
    if word[0].isdigit():
        word = f"_{word}"
    return f"{word}_" if word in FBS_KEYWORDS else word


class _Namer:
    """Unique identifiers in one scope (``name``, ``name_2`` …)."""

    def __init__(self) -> None:
        self._used: set = set()
        self._given: Dict[str, str] = {}

    def reserve(self, name: str) -> None:
        """Mark ``name`` taken (a union's hidden ``<name>_type``)."""
        self._used.add(name)

    def name(self, source: str, *, key: Optional[str] = None) -> str:
        """The unique identifier for ``source`` (the same one again for the same ``key``)."""
        if key is not None and key in self._given:
            return self._given[key]
        base = fbs_identifier(source)
        candidate, suffix = base, 2
        while candidate in self._used:
            candidate = f"{base}_{suffix}"
            suffix += 1
        self._used.add(candidate)
        if key is not None:
            self._given[key] = candidate
        return candidate


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------


@dataclass
class _Resolved:
    """A reference as the schema writes it.

    Attributes:
        expr: The type expression (``string``, ``[Vec3]``, ``Color``).
        kind: ``bool`` / ``int`` / ``float`` (scalars), ``string``, ``bytes``, ``enum``, ``struct``,
            ``table``, ``union``, ``vector``, ``external`` (a type from an included file) or ``none``.
        target: The model type it names, if any.
    """

    expr: str
    kind: str
    target: Optional[Type] = None

    @property
    def width(self) -> int:
        """Ids a table field of this type takes (a union: its type and its value)."""
        return 2 if self.kind == "union" else 1


@dataclass
class _Table:
    """A table or struct to write: a model record, or one synthesized (map entry, wrapper)."""

    type_: Type
    struct: bool = False
    synthesized: bool = False
    key_field: Optional[str] = None
    lines: List[str] = dataclass_field(default_factory=list)


class _FlatBuffersWriter:
    """Writes one ``.fbs`` schema (single use)."""

    def __init__(self, api: CanonicalApi, options: FlatBuffersEmitOptions) -> None:
        self._api = api
        self._options = options
        self.tracker = ProvenanceTracker()
        self.losses = LossTracker()
        #: Newly assigned field ids (``store key → id``), for the export service to persist.
        self.field_identity_assignments: Dict[str, int] = {}
        self.output_path = _output_path(api)
        self._types_by_key = {t.key: t for t in api.types if t.key}
        names = [t.name for t in api.types]
        self._by_unique_name = {t.name: t for t in api.types if t.name and names.count(t.name) == 1}
        includes = api.extras.get("fbs_includes")
        self._includes = [i for i in includes if isinstance(i, str) and i] if isinstance(includes, list) else []
        self._noted: set = set()
        #: Synthesized tables by key, in the order they were made.
        self._synthesized: Dict[str, _Table] = {}
        self._type_names = _Namer()
        for type_ in api.types:
            if type_.kind in (TypeKind.RECORD, TypeKind.ENUM, TypeKind.UNION, TypeKind.MAP):
                self._type_names.name(type_.name or type_.key, key=type_.key)
        self._structs = self._struct_keys()

    # --- module -------------------------------------------------------------

    def render(self) -> str:
        """The schema text: header, namespace, includes, enums, structs, unions, tables, root_type."""
        lines: List[str] = []
        if self._options.include_comments:
            lines += [f"// Generated FlatBuffers schema for {self._api.identity.name or 'Exported schema'}", ""]
        namespace = self._namespace()
        if namespace:
            lines += [f"namespace {namespace};", ""]
        for include in self._includes:
            lines.append(f'include "{include}";')
        if self._includes:
            lines.append("")

        enums, structs, unions, tables = [], [], [], []
        for type_ in self._api.types:
            if type_.kind is TypeKind.ENUM:
                enums.append(self._enum(type_))
            elif type_.kind is TypeKind.UNION:
                unions.append(self._union(type_))
            elif type_.kind is TypeKind.RECORD and type_.key in self._structs:
                structs.append(type_)
            elif type_.kind is TypeKind.RECORD:
                tables.append(self._table(_Table(type_)))
            elif type_.kind is TypeKind.MAP:
                self._map_entry(type_)
            else:
                self._inlined(type_)
            self.tracker.record(type_.key, Provenance.SOURCE)
        struct_blocks = [self._table(_Table(t, struct=True)) for t in self._struct_order(structs)]
        # Synthesized tables can make more of themselves (a map of vectors of vectors): drain the queue.
        written: set = set()
        while len(written) < len(self._synthesized):
            for key, table in list(self._synthesized.items()):
                if key not in written:
                    written.add(key)
                    tables.append(self._table(table))
        for block in [*enums, *struct_blocks, *unions, *tables]:
            lines += block + [""]

        root = self._root_type()
        if root:
            lines += [f"root_type {root};", ""]
        advisory = types_only_advisory(self._api, target_label="FlatBuffers", keep_in="OpenAPI or AsyncAPI")
        if advisory is not None:
            self.losses.record(LossKind.NA, "services-dropped", advisory.message)
        return "\n".join(lines).rstrip() + "\n"

    def _namespace(self) -> Optional[str]:
        """The item's namespace, each part a FlatBuffers identifier (``acme.shop-v1`` → ``acme.shop_v1``)."""
        namespace = self._api.identity.namespace
        if not namespace:
            return None
        written = ".".join(fbs_identifier(part, fallback="ns") for part in namespace.split(".") if part)
        if written != namespace:
            self._loss("name-respelled", "",
                       f"The namespace {namespace!r} is written as {written!r} to follow the FlatBuffers naming rules.")
        return written or None

    def _root_type(self) -> Optional[str]:
        """The ``root_type``: the option, else the imported one — a table either way."""
        wanted = self._options.root_type
        imported = self._api.extras.get("fbs_root_type")
        source = wanted or (imported if isinstance(imported, str) and imported else None)
        if source is None:
            return None
        target = self._resolve_name(source)
        if target is not None and target.kind is TypeKind.RECORD and target.key not in self._structs:
            return self._type_names.name(target.name or target.key, key=target.key)
        if wanted:
            raise EmitPreconditionError(
                f"root_type {wanted!r} is not a table of this model; name a record type (by name or key)."
            )
        self._loss("root-type-dropped", "", f"The imported root_type {source!r} is not a table here; "
                   "no root_type is written.")
        return None

    # --- types --------------------------------------------------------------

    def _struct_keys(self) -> set:
        """Records the source declared as ``struct`` that a struct can hold (else they become tables)."""
        candidates = {t.key for t in self._api.types
                      if t.kind is TypeKind.RECORD and t.extras.get("fbs_kind") == "struct"}
        changed = True
        while changed:
            changed = False
            for key in sorted(candidates):
                type_ = self._types_by_key[key]
                if not type_.fields or not all(self._fits_struct(f, candidates, key) for f in type_.fields):
                    candidates.discard(key)
                    changed = True
        for type_ in self._api.types:
            if type_.extras.get("fbs_kind") == "struct" and type_.key not in candidates:
                self._loss("struct-as-table", type_.key,
                           f"{type_.key!r} is written as a table: a struct holds only scalars, enums and structs.")
        return candidates

    def _fits_struct(self, field: CanonicalField, candidates: set, owner: str) -> bool:
        """Whether a struct can hold ``field``: a scalar (not text), an enum, or another struct."""
        if field.type.is_list():
            return False
        target = self._resolve_name(field.type.name or "")
        if target is not None:
            if target.kind is TypeKind.ENUM:
                return True
            return target.kind is TypeKind.RECORD and target.key in candidates and target.key != owner
        spec = _SCALARS.get((field.type.name or "").lower())
        return spec is not None and spec[1] in ("bool", "int", "float")

    def _struct_order(self, structs: List[Type]) -> List[Type]:
        """Structs with each one after the structs it holds (``flatc`` sizes a struct from its parts)."""
        ordered: List[Type] = []
        placed: set = set()

        def place(type_: Type) -> None:
            if type_.key in placed:
                return
            placed.add(type_.key)
            for f in type_.fields:
                target = self._resolve_name(f.type.name or "")
                if target is not None and target.key in self._structs:
                    place(target)
            ordered.append(type_)

        for type_ in structs:
            place(type_)
        return ordered

    def _enum(self, type_: Type) -> List[str]:
        """``enum Name : <int type> { A = 0, B = 1 }``, values ascending."""
        name = self._type_names.name(type_.name or type_.key, key=type_.key)
        self._renamed(type_.name, name, type_.key, "type")
        members = list(type_.enum_values)
        if not members:
            self._loss("empty-enum", type_.key, f"Enum {type_.key!r} has no values; FlatBuffers needs one, so it "
                       "is written with a single UNKNOWN = 0.")
            return [*self._doc(type_.description, ""), f"enum {name} : byte {{", "  UNKNOWN = 0", "}"]
        entries = _enum_items(type_)
        if any(number != member.value for member, number, _ in entries):
            self._loss("enum-renumbered", type_.key, f"The values of {type_.key!r} are not distinct integers; "
                       "FlatBuffers numbers them from 0 in declaration order.")
        base = self._enum_base(type_, [number for _, number, _ in entries])
        items = []
        for member, number, item in entries:
            self._renamed(member.name, item, member.key or type_.key, "enum value")
            items.append(f"  {item} = {number}")
        return [*self._doc(type_.description, ""), f"enum {name} : {base} {{", ",\n".join(items), "}"]

    def _enum_base(self, type_: Type, numbers: List[int]) -> str:
        """The enum's integer type: the imported one when its values fit, else the smallest that does."""
        low, high = min(numbers), max(numbers)
        imported = type_.extras.get("fbs_base_type")
        if imported in _INT_RANGES and _INT_RANGES[imported][0] <= low and high <= _INT_RANGES[imported][1]:
            return imported
        return next(name for name, (lo, hi) in _INT_RANGES.items() if lo <= low and high <= hi)

    def _union(self, type_: Type) -> List[str]:
        """``union Name { A, B }`` — a member that is not a table is wrapped in one."""
        name = self._type_names.name(type_.name or type_.key, key=type_.key)
        self._renamed(type_.name, name, type_.key, "type")
        members: List[str] = []
        for member in type_.union_members:
            resolved = self._resolve(TypeRef(name=member), type_.key, hint=f"{name}_{member.split('.')[-1]}")
            if resolved.kind not in ("table", "external"):
                wrapper = self._wrapper(_pascal(f"{name}_{member.split('.')[-1]}"),
                                        "value", TypeRef(name=member), type_.key,
                                        f"the union {type_.key!r} member {member!r} is not a table")
                resolved = _Resolved(wrapper, "table")
            if resolved.expr not in members:
                members.append(resolved.expr)
        if not members:
            empty = self._wrapper(f"{name}None", None, None, type_.key, f"the union {type_.key!r} has no members")
            members.append(empty)
        return [*self._doc(type_.description, ""), f"union {name} {{", "  " + ",\n  ".join(members), "}"]

    def _map_entry(self, type_: Type) -> None:
        """A map as ``<Map>Entry { key (key); value; }`` — referenced as a vector of entries."""
        self._entry_table(type_)
        self._loss("map-as-vector", type_.key, f"FlatBuffers has no map type; {type_.key!r} is written as a "
                   "vector of key / value tables keyed by `key`, which does not require keys to be unique.")

    def _entry_table(self, type_: Type) -> str:
        """The name of the ``<Map>Entry`` table of a map type (made once)."""
        entry_key = f"{type_.key}#entry"
        if entry_key not in self._synthesized:
            base = self._type_names.name(type_.name or type_.key, key=type_.key)
            name = self._type_names.name(f"{base}Entry")
            key_ref = type_.key_type or TypeRef(name="string")
            key_kind = self._resolve(key_ref, type_.key).kind
            if key_kind not in ("string", "int", "float", "bool", "enum"):
                self._loss("map-key-as-string", type_.key, f"A FlatBuffers key must be a scalar or a string; the "
                           f"keys of {type_.key!r} are written as strings.")
                key_ref = TypeRef(name="string")
            entry = Type(key=entry_key, name=name, kind=TypeKind.RECORD, fields=[
                CanonicalField(key=f"{entry_key}.key", name="key", type=key_ref.model_copy(update={"nullable": False})),
                CanonicalField(key=f"{entry_key}.value", name="value", type=type_.value_type or TypeRef(name="bytes")),
            ])
            self._synthesized[entry_key] = _Table(entry, synthesized=True, key_field="key")
        return self._synthesized[entry_key].type_.name

    def _wrapper(self, name: str, field_name: Optional[str], ref: Optional[TypeRef], owner: str, why: str) -> str:
        """A synthesized table holding one field (``None``: an empty table) — recorded once per name."""
        wrapper_key = f"{owner}#{name}"
        if wrapper_key not in self._synthesized:
            written = self._type_names.name(name)
            fields = [CanonicalField(key=f"{wrapper_key}.{field_name}", name=field_name, type=ref)] if ref else []
            self._synthesized[wrapper_key] = _Table(
                Type(key=wrapper_key, name=written, kind=TypeKind.RECORD, fields=fields), synthesized=True,
            )
            self._loss("table-synthesized", owner, f"The table {written!r} is synthesized: {why}.")
        return self._synthesized[wrapper_key].type_.name

    def _inlined(self, type_: Type) -> None:
        """An alias or named scalar: written as what it stands for wherever it is used (no typedef)."""
        self._loss("alias-inlined", type_.key, f"FlatBuffers has no typedef; {type_.key!r} is written as the type "
                   "it stands for wherever it is used.")

    # --- tables -------------------------------------------------------------

    def _table(self, table: _Table) -> List[str]:
        """A ``table`` (fields with ids, in id order, with deprecated placeholders) or a ``struct``."""
        type_ = table.type_
        name = table.type_.name if table.synthesized else self._type_names.name(type_.name or type_.key, key=type_.key)
        if not table.synthesized:
            self._renamed(type_.name, name, type_.key, "type")
        keyword = "struct" if table.struct else "table"
        names = _Namer()
        fields = sorted(type_.fields, key=lambda f: f.field_number or 0) if not table.synthesized else type_.fields
        resolved: Dict[str, Tuple[CanonicalField, _Resolved, str]] = {}
        for f in fields:
            target = self._resolve(f.type, f.key, hint=f"{name}_{f.name}")
            if target.kind == "none":
                self._loss("field-dropped", f.key, f"{f.key!r} has the type {f.type.name!r}, which holds no value; "
                           "FlatBuffers has no such type, so the field is left out.")
                continue
            written = names.name(f.name or f.key)
            if target.kind == "union":
                names.reserve(f"{written}_type")
            self._renamed(f.name, written, f.key, "field")
            resolved[f.key] = (f, target, written)
            self.tracker.record(f.key, Provenance.SOURCE)

        body: List[str] = []
        if table.struct:
            for f, target, written in resolved.values():
                if f.default is not None:
                    self._default_dropped(f, f.default)
                body += self._doc(f.description, "  ")
                body += self._constraints(f, "  ")
                body.append(f"  {written}: {target.expr};")
        else:
            body = self._table_fields(type_, resolved, names, table.key_field)
        return [*self._doc(type_.description, ""), f"{keyword} {name} {{", *body, "}"]

    def _table_fields(
        self, type_: Type, resolved: Dict[str, Tuple[CanonicalField, _Resolved, str]], names: _Namer,
        key_field: Optional[str],
    ) -> List[str]:
        """A table's field lines, id 0 upward: ``name: T (id: N[, required][, key]) [= default];``."""
        allocator = FieldIdAllocator(type_.key, persisted=self._options.persisted_field_numbers)
        source_ids = self._source_ids(type_, resolved)
        for key, (f, target, _written) in resolved.items():
            allocator.add(key, f, width=target.width, source_id=source_ids.get(key))
        slots = allocator.finish()
        self.field_identity_assignments.update(allocator.new_assignments)
        deprecated_names = type_.extras.get("fbs_deprecated") if isinstance(type_.extras.get("fbs_deprecated"),
                                                                             dict) else {}
        lines: List[str] = []
        for slot in slots:
            if slot.placeholder:
                retired = slot.key.rsplit(".", 1)[-1]
                source = deprecated_names.get(str(slot.id)) or retired
                placeholder = names.name(source)
                lines.append(f"  {placeholder}: ubyte (id: {slot.id}, deprecated);")
                continue
            f, target, written = resolved[slot.key]
            if source_ids.get(slot.key) is None:
                self._loss("synthesized-field-id", f.key,
                           f"The source gives {f.key!r} no FlatBuffers field id; it is written with id: {slot.id}.")
            attributes = [f"id: {slot.id}"]
            if not f.type.nullable and target.kind in ("string", "bytes", "vector", "table", "struct"):
                attributes.append("required")
            if key_field is not None and f.name == key_field:
                attributes.append("key")
            default = self._default(f, target)
            lines += self._doc(f.description, "  ")
            lines += self._constraints(f, "  ")
            lines.append(f"  {written}: {target.expr}{default} ({', '.join(attributes)});")
        return lines

    def _source_ids(
        self, type_: Type, resolved: Dict[str, Tuple[CanonicalField, _Resolved, str]]
    ) -> Dict[str, int]:
        """The ids a ``.fbs`` source gave its fields (position-implied, or moved ones from ``fbs_id``)."""
        if self._api.format != "flatbuffers" or type_.key not in self._types_by_key:
            return {}
        keys = list(resolved)
        compact = compact_field_ids([resolved[k][1].width for k in keys])
        ids: Dict[str, int] = {}
        for key, implied in zip(keys, compact):
            moved = resolved[key][0].extras.get("fbs_id")
            ids[key] = moved if isinstance(moved, int) and not isinstance(moved, bool) else implied
        return ids

    def _default(self, f: CanonicalField, target: _Resolved) -> str:
        """`` = <value>`` for a scalar or enum field, or ``""``.

        An enum field with no default whose enum has no ``0`` value gets its first value: ``flatc``
        refuses an enum field whose implicit ``0`` default is not one of its values.
        """
        value = f.extras.get("fbs_default", f.default)
        if target.kind == "enum" and target.target is not None:
            entries = _enum_items(target.target)
            if value is not None and not isinstance(value, bool):
                for member, _number, item in entries:
                    if value in (member.name, member.value, item):
                        return f" = {item}"
            if entries and 0 not in [number for _, number, _ in entries]:
                if value is not None:
                    self._default_dropped(f, value)
                return f" = {entries[0][2]}"  # ascending: the smallest value
            if value is not None:
                self._default_dropped(f, value)
            return ""
        if value is None:
            return ""
        literal = _scalar_default(value, target)
        if literal is None:
            self._default_dropped(f, value)
            return ""
        return f" = {literal}"

    def _default_dropped(self, f: CanonicalField, value: Any) -> None:
        self._loss("default-dropped", f.key, f"The default {value!r} of {f.key!r} is not written: FlatBuffers "
                   "defaults are scalar or enum values of the field's type.")

    # --- references ---------------------------------------------------------

    def _resolve_name(self, name: str) -> Optional[Type]:
        """The model type a name refers to: by key, else by its name when that is unique."""
        return self._types_by_key.get(name) or self._by_unique_name.get(name)

    def _resolve(self, ref: TypeRef, owner: str, *, hint: str = "", _seen: Optional[set] = None) -> _Resolved:
        """A reference written as a FlatBuffers type (wrapping what a vector cannot hold)."""
        if ref.is_list():
            item = self._resolve(ref.item or TypeRef(name="string"), owner, hint=f"{hint}Item", _seen=_seen)
            if item.kind in ("vector", "bytes", "union"):
                why = (f"a vector cannot hold a {'union' if item.kind == 'union' else 'vector'}; the items of "
                       f"{owner!r} are wrapped")
                wrapper = self._wrapper(_pascal(f"{hint}Item"), "items" if item.kind != "union" else "value",
                                        ref.item, owner, why)
                return _Resolved(f"[{wrapper}]", "vector")
            if item.kind == "none":
                return item
            return _Resolved(f"[{item.expr}]", "vector")
        name = ref.name or "string"
        target = self._resolve_name(name)
        if target is not None:
            seen = _seen or set()
            if target.key in seen:
                return _Resolved("string", "string")
            if target.kind is TypeKind.ENUM:
                return _Resolved(self._type_names.name(target.name or target.key, key=target.key), "enum", target)
            if target.kind is TypeKind.UNION:
                return _Resolved(self._type_names.name(target.name or target.key, key=target.key), "union", target)
            if target.kind is TypeKind.RECORD:
                kind = "struct" if target.key in self._structs else "table"
                return _Resolved(self._type_names.name(target.name or target.key, key=target.key), kind, target)
            if target.kind is TypeKind.MAP:
                return _Resolved(f"[{self._entry_table(target)}]", "vector", target)
            if target.kind is TypeKind.ALIAS and target.aliased is not None:
                return self._resolve(target.aliased, owner, hint=hint, _seen=seen | {target.key})
            return self._scalar(target.name or target.key, owner)
        return self._scalar(name, owner)

    def _scalar(self, name: str, owner: str) -> _Resolved:
        """The FlatBuffers type of a canonical scalar name."""
        lowered = name.lower()
        spec = _SCALARS.get(lowered)
        if spec is not None:
            return _Resolved(spec[0], spec[1])
        if lowered in _NONE_SCALARS:
            return _Resolved("", "none")
        if lowered in _ANY_SCALARS:
            self._loss("opaque-value", owner, f"FlatBuffers has no type for any value; {name!r} in {owner!r} is "
                       "written as bytes ([ubyte]).")
            return _Resolved("[ubyte]", "bytes")
        if self._includes:
            # A type from an included file: written by name, for the include to define.
            return _Resolved(".".join(fbs_identifier(p) for p in name.split(".")), "external")
        self._loss("unmapped-scalar", owner, f"{name!r} has no FlatBuffers type; values of it are written as "
                   "strings.")
        return _Resolved("string", "string")

    # --- bookkeeping --------------------------------------------------------

    def _doc(self, text: Optional[str], indent: str) -> List[str]:
        """A description as ``///`` doc-comment lines (only with ``include_comments``)."""
        if not text or not self._options.include_comments:
            return []
        return [f"{indent}/// {line.strip()}".rstrip() for line in text.strip().splitlines()]

    def _constraints(self, f: CanonicalField, indent: str) -> List[str]:
        """A field's constraints as a ``//`` comment line — or, with comments off, nothing (both recorded).

        FlatBuffers has no validation facets: a comment keeps them for the schema's readers, and nothing
        checks them.
        """
        text = constraint_comment(f.constraints)
        if text is None:
            return []
        if not self._options.include_comments:
            self._loss("constraints-dropped", f.key, f"FlatBuffers cannot enforce constraints and comments are off; "
                       f"the {text} of {f.key!r} are not written.")
            return []
        self._loss("constraints-as-comment", f.key, f"FlatBuffers cannot enforce constraints; those of {f.key!r} "
                   f"are written as a comment that nothing checks ({text}).")
        return [f"{indent}// {text}"]

    def _renamed(self, source: Optional[str], written: str, key: str, what: str) -> None:
        if source and source != written:
            self._loss("name-respelled", key,
                       f"The {what} {source!r} is written as {written!r} to follow the FlatBuffers naming rules.")

    def _loss(self, subject: str, pointer: str, detail: str) -> None:
        """Record a loss once (a type resolved from several fields is reported on the first)."""
        if (subject, pointer, detail) in self._noted:
            return
        self._noted.add((subject, pointer, detail))
        dropped = subject in ("field-dropped", "default-dropped", "root-type-dropped", "constraints-dropped")
        kind = LossKind.NA if dropped else LossKind.INFERRED
        self.losses.record(kind, subject, detail, pointer=pointer or None)


def _enum_items(type_: Type) -> List[Tuple[Any, int, str]]:
    """An enum's ``(member, number, written name)`` in ascending number order.

    Numbers are the members' values when every one is a distinct integer, else positions from 0.
    Shared by the ``enum`` block and the defaults of fields of it, so both spell members alike.
    """
    members = list(type_.enum_values)
    numbers = [m.value for m in members]
    integers = all(isinstance(n, int) and not isinstance(n, bool) for n in numbers)
    distinct = integers and len(set(numbers)) == len(numbers)
    if not distinct:
        numbers = list(range(len(members)))
    names = _Namer()
    written = [names.name(m.name or str(m.value)) for m in members]
    return sorted(zip(members, numbers, written), key=lambda entry: entry[1])


def _pascal(text: str) -> str:
    """``order_lines_Item`` → ``OrderLinesItem`` (a synthesized table's name)."""
    return "".join(part[:1].upper() + part[1:] for part in re.split(r"[^A-Za-z0-9]+", text) if part) or "Item"


def _scalar_default(value: Any, target: _Resolved) -> Optional[str]:
    """A default as a FlatBuffers literal for a scalar field, or ``None`` when it cannot be one."""
    if target.kind == "bool":
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, str) and value.lower() in ("true", "false"):
            return value.lower()
        return None
    if target.kind not in ("int", "float") or isinstance(value, bool):
        return None
    try:
        number = float(value) if target.kind == "float" else int(str(value), 0)
    except (TypeError, ValueError):
        try:
            as_float = float(value)
        except (TypeError, ValueError):
            return None
        if target.kind == "int" and as_float.is_integer():
            number = int(as_float)
        else:
            return None
    if target.kind == "int":
        low, high = _INT_RANGES[target.expr]
        return str(number) if low <= number <= high else None
    return repr(float(number)) if not float(number).is_integer() else f"{float(number):.1f}"


def _output_path(api: CanonicalApi) -> str:
    base = api.identity.name or "schema"
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", base).strip("_") or "schema"
    return f"{safe}.fbs"
