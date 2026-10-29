"""ASN.1 emitter: canonical model → ASN.1 module (ITU-T X.680) — MFX-27.1 (#4163).

The inverse of :class:`app.asn1_normalizer.Asn1Normalizer` and an implementation of the
:class:`app.emitter.Emitter` SPI. The model's types become one module that compiles under
``asn1tools``:

* a record → ``SEQUENCE``; a field that may be absent → ``OPTIONAL``, or ``DEFAULT <value>`` when it
  has a default the type can spell (X.680 allows one or the other, never both);
* a union → ``CHOICE`` (one alternative per member); an enum → ``ENUMERATED`` (with its numbers when
  every value is a distinct integer); a list → ``SEQUENCE OF``; a map → ``SEQUENCE OF SEQUENCE
  { key K, value V }`` (ASN.1 has no map type — recorded);
* scalars → ``UTF8String``, ``INTEGER``, ``REAL``, ``BOOLEAN``, ``NULL``, ``OCTET STRING``,
  ``GeneralizedTime``, ``DATE``, ``TIME-OF-DAY``; a sized integer keeps its width as a value range
  (``uint8`` → ``INTEGER (0..255)``).

**Constraints are subtype notation** — one of the few targets where they survive:

* ``minLength`` / ``maxLength`` → ``(SIZE (a..b))`` on strings and bytes; ``minItems`` / ``maxItems``
  → ``SEQUENCE (SIZE (a..b)) OF``; the length and value rules of a list field apply to its items;
* ``minimum`` / ``maximum`` → a value range ``(a..b)``, intersected with the integer's width; an
  exclusive bound is exact for an integer (``> 0`` → ``1..``) and written inclusive for a real
  (``asn1tools`` cannot read ``<``) — recorded; an integer ``enum`` → a value set ``(1 | 2 | 5)``;
* ``pattern`` → ``(PATTERN "…")``, recorded because X.680 reads it in its own regular-expression
  syntax.

What has no notation (``multipleOf``, ``uniqueItems``, a string ``enum``, formats other than
date/time, a default the type cannot spell) is left out and recorded on the
:class:`~app.emitter.LossTracker` with the key of the type or field it belongs to.

**Options:** ``module_name`` (else the imported module name, else the item's name) and ``oid`` (the
module's object identifier), beside ``automatic_tags`` and ``include_comments``.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple, Union

from pydantic import Field, field_validator

from .asn1_notation import (
    Namer,
    cstring_literal,
    identifier,
    integer_bounds,
    module_oid,
    number_literal,
    size_constraint,
    type_reference,
    value_range,
)
from .canonical_model import (
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Constraints,
    OperationKind,
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
from .fidelity_rulepack import CapabilityRulePack, FidelityVerdict
from .lossiness import LossinessKind, LossinessReport, LossinessSeverity

__all__ = ["Asn1EmitOptions", "Asn1Emitter", "Asn1FidelityRulePack", "validate_asn1_module"]

_INT64 = (-(2**63), 2**63 - 1)

#: Canonical scalar name (lower-cased) → (ASN.1 type, value kind, integer width range).
#: The kind decides which constraints apply: ``string`` and ``bytes`` take SIZE and PATTERN,
#: ``integer`` and ``real`` take value ranges.
_SCALARS: Dict[str, Tuple[str, str, Optional[Tuple[int, int]]]] = {
    **{name: ("UTF8String", "string", None) for name in (
        "string", "str", "text", "char", "id", "uuid", "guid", "uri", "url", "email", "hostname",
        "ipv4", "ipv6", "duration",
    )},
    **{name: ("GeneralizedTime", "time", None) for name in ("datetime", "date-time", "timestamp", "instant")},
    "date": ("DATE", "time", None),
    "time": ("TIME-OF-DAY", "time", None),
    **{name: ("OCTET STRING", "bytes", None) for name in ("bytes", "binary", "blob")},
    **{name: ("INTEGER", "integer", None) for name in ("integer", "int", "bigint")},
    **{name: ("INTEGER", "integer", (-128, 127)) for name in ("i8", "int8", "sbyte")},
    **{name: ("INTEGER", "integer", (0, 255)) for name in ("u8", "uint8", "byte")},
    **{name: ("INTEGER", "integer", (-32768, 32767)) for name in ("i16", "int16", "short")},
    **{name: ("INTEGER", "integer", (0, 65535)) for name in ("u16", "uint16")},
    **{name: ("INTEGER", "integer", (-(2**31), 2**31 - 1)) for name in (
        "i32", "int32", "sint32", "sfixed32",
    )},
    **{name: ("INTEGER", "integer", (0, 2**32 - 1)) for name in ("u32", "uint32", "fixed32")},
    **{name: ("INTEGER", "integer", _INT64) for name in ("i64", "int64", "sint64", "sfixed64", "long")},
    **{name: ("INTEGER", "integer", (0, 2**64 - 1)) for name in ("u64", "uint64", "fixed64")},
    **{name: ("REAL", "real", None) for name in ("float", "double", "f32", "f64", "number", "decimal")},
    **{name: ("BOOLEAN", "bool", None) for name in ("bool", "boolean")},
    **{name: ("NULL", "null", None) for name in ("null", "void", "none")},
}
#: ASN.1 built-in types an ASN.1 import leaves as references (``Module.OBJECT IDENTIFIER``): written as
#: themselves, with the kind that decides their constraints.
_ASN1_BUILTINS: Dict[str, Tuple[str, str, None]] = {
    **{name: (name, "string", None) for name in (
        "PrintableString", "IA5String", "VisibleString", "NumericString", "BMPString", "UniversalString",
        "GeneralString", "GraphicString", "TeletexString", "T61String", "VideotexString", "ISO646String",
    )},
    "BIT STRING": ("BIT STRING", "bytes", None),
    "UTCTime": ("UTCTime", "time", None),
    "OBJECT IDENTIFIER": ("OBJECT IDENTIFIER", "oid", None),
    "RELATIVE-OID": ("RELATIVE-OID", "oid", None),
}
#: The :class:`~app.canonical_model.Constraints` rules (``format`` picks a type instead).
_CONSTRAINT_KEYWORDS = (
    "minimum", "maximum", "exclusive_minimum", "exclusive_maximum", "multiple_of", "min_length", "max_length",
    "pattern", "min_items", "max_items", "unique_items", "enum",
)
#: Canonical formats that pick an ASN.1 time type for a string.
_TIME_FORMATS = {"date-time": "GeneralizedTime", "date": "DATE", "time": "TIME-OF-DAY"}

_EVENT_OPERATION_KINDS = frozenset({OperationKind.PUBLISH, OperationKind.SUBSCRIBE})
_TYPES_ONLY_DROP_MESSAGE = "only data schemas are exported"


class Asn1FidelityRulePack(CapabilityRulePack):
    """Fidelity rules for ASN.1 export.

    Operations and channels are dropped (types-only). Beside the capability verdicts, the pack builds the
    module as it will be emitted (MFX-27.1) and reports what the writer changed, on the construct it
    changed (an enum value's loss on its enum):

    * a document of another format, written as an ASN.1 module that reads back as an ASN.1 item, and the
      module name, when the source does not key its types under it — a re-import does (info ``APPROX`` on
      the root);
    * ``name-respelled``, ``pattern-dialect``, ``description-as-comment`` (info ``APPROX``);
      ``description-dropped`` (info ``DROP``); ``map-as-sequence``, ``unmapped-scalar``,
      ``exclusive-bound-inclusive``, ``empty-enum``, ``empty-choice`` (``APPROX``); ``constraint-dropped``
      and ``default-dropped`` (``DROP``).

    The finer verdicts (maps, constraints reported OK where subtype notation covers them) are MFX-27.2.
    """

    target_label = "ASN.1"

    #: Writer loss subjects → (verdict kind, severity).
    _WRITER_LOSSES = {
        "name-respelled": (LossinessKind.APPROX, LossinessSeverity.INFO),
        "pattern-dialect": (LossinessKind.APPROX, LossinessSeverity.INFO),
        "description-as-comment": (LossinessKind.APPROX, LossinessSeverity.INFO),
        "description-dropped": (LossinessKind.DROP, LossinessSeverity.INFO),
        "map-as-sequence": (LossinessKind.APPROX, LossinessSeverity.WARN),
        "unmapped-scalar": (LossinessKind.APPROX, LossinessSeverity.WARN),
        "exclusive-bound-inclusive": (LossinessKind.APPROX, LossinessSeverity.WARN),
        "empty-enum": (LossinessKind.APPROX, LossinessSeverity.WARN),
        "empty-choice": (LossinessKind.APPROX, LossinessSeverity.WARN),
        "constraint-dropped": (LossinessKind.DROP, LossinessSeverity.WARN),
        "default-dropped": (LossinessKind.DROP, LossinessSeverity.WARN),
    }
    #: Set by :meth:`evaluate`: the module name written, and the writer's verdicts by construct key.
    _module_name = ""
    _filed: Dict[str, List[FidelityVerdict]] = {}

    def evaluate(self, api: CanonicalApi) -> LossinessReport:
        """Build the module once, file the writer's losses by construct, then walk the model."""
        writer = _Asn1Writer(api, Asn1EmitOptions())
        writer.render()
        self._module_name = writer.module_name
        constructs = {""} | {t.key for t in api.types} | {f.key for t in api.types for f in t.fields}
        self._filed: Dict[str, List[FidelityVerdict]] = {}
        seen = set()
        for loss in writer.losses.records():
            verdict_kind = self._WRITER_LOSSES.get(loss.subject)
            if verdict_kind is None or (loss.subject, loss.detail) in seen:
                continue
            seen.add((loss.subject, loss.detail))
            kind, severity = verdict_kind
            verdict = FidelityVerdict(kind=kind, severity=severity, message=loss.detail,
                                      target_mapping=loss.subject)
            self._filed.setdefault(_owning_construct(loss.pointer or "", constructs), []).append(verdict)
        return super().evaluate(api)

    def root_verdicts(self, api: CanonicalApi) -> List[FidelityVerdict]:
        """A note when the source does not key its types under the module name (a re-import does)."""
        verdicts: List[FidelityVerdict] = []
        if api.format != "asn1":
            verdicts.append(FidelityVerdict.approx(
                message=f"The {api.format or 'source'} document is written as an ASN.1 module and reads back as an "
                "ASN.1 item; details specific to its format are not kept",
                severity=LossinessSeverity.INFO,
                target_mapping="document → ASN.1 module",
            ))
        prefix = f"{self._module_name}."
        if any(t.key and not t.key.startswith(prefix) for t in api.types):
            verdicts.append(FidelityVerdict.approx(
                message=f"An ASN.1 module names its types; they are written in module {self._module_name} and read "
                f"back keyed {self._module_name}.<Type>",
                severity=LossinessSeverity.INFO,
                target_mapping=f"namespace → module {self._module_name}",
            ))
        return verdicts + self._filed.get("", [])

    def type_verdicts(self, type_: Type) -> List[FidelityVerdict]:
        return super().type_verdicts(type_) + self._filed.get(type_.key, [])

    def field_verdicts(self, field: CanonicalField) -> List[FidelityVerdict]:
        return super().field_verdicts(field) + self._filed.get(field.key, [])

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


class Asn1EmitOptions(EmitOptions):
    """Per-target options for :class:`Asn1Emitter`."""

    include_comments: bool = Field(
        default=True,
        description="Emit a generated-file header and type / field descriptions as `--` comments.",
    )
    automatic_tags: bool = Field(
        default=True,
        description="Emit `AUTOMATIC TAGS` on the module header (otherwise the imported module's tagging, "
        "else none).",
    )
    module_name: Optional[str] = Field(
        default=None,
        description="Module name (a modulereference such as `Shop-Orders`); defaults to the imported module "
        "name, else the item's name.",
    )
    oid: Optional[str] = Field(
        default=None,
        description="Module object identifier, dotted (`1.3.6.1.4.1.99999.1`) or as arcs in braces "
        "(`{ iso(1) identified-organization(3) 6 }`).",
    )

    @field_validator("module_name")
    @classmethod
    def _module_name(cls, value: Optional[str]) -> Optional[str]:
        """Blank → ``None``; otherwise it must hold a letter or digit to spell a modulereference from."""
        if value is None or not value.strip():
            return None
        if not re.search(r"[A-Za-z0-9]", value):
            raise ValueError("module_name must contain a letter or digit")
        return value.strip()

    @field_validator("oid")
    @classmethod
    def _oid(cls, value: Optional[str]) -> Optional[str]:
        """Blank → ``None``; otherwise the brace form :func:`app.asn1_notation.module_oid` writes."""
        if value is None or not value.strip():
            return None
        return module_oid(value)


class Asn1Emitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as an ASN.1 module."""

    key = "asn1"
    format = "asn1"
    label = "ASN.1"
    description = (
        "Export as an ASN.1 module (.asn1): SEQUENCE / CHOICE / ENUMERATED types with SIZE and range constraints."
    )
    icon = "binary"
    paradigm = ApiParadigm.DATA_SCHEMA
    multi_file = False
    options_model = Asn1EmitOptions

    OUTPUT_MEDIA_TYPE = "text/plain"

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        return CapabilityProfile(
            operations=False,
            events=False,
            unions=True,
            nullability=True,
            field_identity=True,
        )

    @classmethod
    def fidelity_rule_pack(cls) -> type[CapabilityRulePack]:
        return Asn1FidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[Asn1EmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        options = (
            opts
            if isinstance(opts, Asn1EmitOptions)
            else Asn1EmitOptions.model_validate(opts.model_dump() if opts else {})
        )
        writer = _Asn1Writer(api, options)
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


class _Asn1Writer:
    """Writes one ASN.1 module (single use)."""

    def __init__(self, api: CanonicalApi, options: Asn1EmitOptions) -> None:
        self._api = api
        self._options = options
        self.tracker = ProvenanceTracker()
        self.losses = LossTracker()
        self._types_by_key = {type_.key: type_ for type_ in api.types if type_.key}
        names = [type_.name for type_ in api.types]
        self._by_unique_name = {t.name: t for t in api.types if t.name and names.count(t.name) == 1}
        # Type names are allocated up front, in declaration order, so a reference written before its
        # target's assignment already has the target's final name.
        self._type_names = Namer(type_reference)
        for type_ in api.types:
            self._type_names.name(type_.name or type_.key, key=type_.key)
        self.module_name = type_reference(self._module_source(), fallback="Module")
        self.output_path = f"{self.module_name}.asn1"

    # --- module -------------------------------------------------------------

    def render(self) -> str:
        """The module text: header, one assignment per type, ``END``."""
        lines: List[str] = []
        if self._options.include_comments:
            lines += [f"-- Generated ASN.1 module for {_comment(self._api.identity.name or 'Exported schema')}", ""]
        oid = f" {self._options.oid}" if self._options.oid else ""
        lines += [f"{self.module_name}{oid} DEFINITIONS{self._tag_clause()} ::= BEGIN", ""]
        for type_ in self._ordered_types():
            rendered = self._render_type(type_)
            if rendered:
                lines += rendered + [""]
        if self._api.services or self._api.channels:
            self.losses.record(
                LossKind.NA,
                "services-dropped",
                "ASN.1 export is types-only; services and channels are omitted",
            )
        lines.append("END")
        return "\n".join(lines).rstrip() + "\n"

    def _ordered_types(self) -> List[Type]:
        """Declaration order, with the type named like the item first: the ASN.1 import titles an item
        after its module's first type, so the title survives a round trip."""
        titled = [t for t in self._api.types if self._api.title and t.name == self._api.title]
        if len(titled) != 1:
            return list(self._api.types)
        return titled + [t for t in self._api.types if t is not titled[0]]

    def _module_source(self) -> str:
        """The name the module reference is spelled from: the option, the imported name, the namespace, the item's."""
        imported = self._api.extras.get("asn1_module_name")
        namespace = self._api.identity.namespace
        # A re-import keys every type `<module>.<Type>`: a namespace that already spells a module
        # reference keeps the source's keys.
        if namespace and type_reference(namespace) != namespace:
            namespace = None
        return (
            self._options.module_name
            or (imported if isinstance(imported, str) and imported else None)
            or namespace
            or self._api.identity.name
            or "ExportedModule"
        )

    def _tag_clause(self) -> str:
        """`` AUTOMATIC TAGS`` by default; else the imported module's tagging, else none (explicit)."""
        if self._options.automatic_tags:
            return " AUTOMATIC TAGS"
        tags = self._api.extras.get("asn1_tags")
        if isinstance(tags, str) and tags.upper() in {"AUTOMATIC", "EXPLICIT", "IMPLICIT"}:
            return f" {tags.upper()} TAGS"
        return ""

    # --- type assignments ---------------------------------------------------

    def _render_type(self, type_: Type) -> List[str]:
        """``Name ::= …`` for one type, preceded by its description as comments."""
        name = self._type_names.name(type_.name or type_.key, key=type_.key)
        self._renamed(type_.name, name, type_.key, "type")
        if type_.kind is TypeKind.RECORD:
            body = self._sequence(type_)
        elif type_.kind is TypeKind.ENUM:
            body = [self._enumerated(type_)]
        elif type_.kind is TypeKind.UNION:
            body = self._choice(type_)
        elif type_.kind is TypeKind.MAP:
            body = [self._map(type_)]
        elif type_.kind is TypeKind.ALIAS and type_.aliased is not None:
            body = [self._constrained_ref(type_.aliased, type_.constraints, type_.key)]
        else:
            # SCALAR (and an ALIAS with no target): the type's own name is the scalar vocabulary.
            body = [self._constrained_ref(TypeRef(name=type_.name or type_.key), type_.constraints, type_.key,
                                          scalar_only=True)]
        self.tracker.record(type_.key, Provenance.SOURCE)
        lines = self._comment_lines(type_.description, "  ", type_.key)
        lines.append(f"  {name} ::= {body[0]}")
        lines += body[1:]
        return lines

    def _sequence(self, type_: Type) -> List[str]:
        """A record's ``SEQUENCE { … }`` (first line, then one line per component)."""
        names = Namer(identifier)
        members: List[List[str]] = []
        for field in sorted(type_.fields, key=lambda f: f.field_number or 0):
            component = names.name(field.name or field.key)
            self._renamed(field.name, component, field.key, "field")
            lines = self._comment_lines(field.description, "    ", field.key)
            lines.append(f"    {component} {self._field(field)}")
            self.tracker.record(field.key, Provenance.SOURCE)
            members.append(lines)
        if not members:
            return ["SEQUENCE { }"]
        for lines in members[:-1]:
            lines[-1] += ","
        return ["SEQUENCE {", *[line for lines in members for line in lines], "  }"]

    def _enumerated(self, type_: Type) -> str:
        """``ENUMERATED { a(0), b(1) }`` — numbered only when every value is a distinct integer."""
        if not type_.enum_values:
            self.losses.record(LossKind.INFERRED, "empty-enum",
                               f"Enum {type_.key!r} has no values; ASN.1 needs one, so it is written as NULL.",
                               pointer=type_.key)
            return "NULL"
        numbers = [value.value for value in type_.enum_values]
        numbered = all(isinstance(n, int) and not isinstance(n, bool) for n in numbers) and len(set(numbers)) == len(
            numbers)
        names = Namer(identifier)
        items = []
        for value, number in zip(type_.enum_values, numbers):
            item = names.name(value.name or str(value.value), key=value.name)
            self._renamed(value.name, item, value.key or type_.key, "enum value")
            items.append(f"{item}({number})" if numbered else item)
        return "ENUMERATED { " + ", ".join(items) + " }"

    def _choice(self, type_: Type) -> List[str]:
        """A union's ``CHOICE { … }``: alternatives named as imported, else after their member type."""
        members = list(type_.union_members)
        if not members:
            self.losses.record(LossKind.INFERRED, "empty-choice",
                               f"Union {type_.key!r} has no members; ASN.1 needs one, so it is written as NULL.",
                               pointer=type_.key)
            return ["NULL"]
        imported = type_.extras.get("asn1_choice_members")
        labels = [m.get("name") if isinstance(m, dict) else None for m in imported] if isinstance(
            imported, list) and len(imported) == len(members) else [None] * len(members)
        names = Namer(identifier)
        lines = ["CHOICE {"]
        for index, (member, label) in enumerate(zip(members, labels)):
            target = self._resolve(member)
            source = label if isinstance(label, str) and label else (target.name if target else member.split(".")[-1])
            alternative = names.name(source)
            expr = self._constrained_ref(TypeRef(name=member), None, type_.key)
            lines.append(f"    {alternative} {expr}" + ("," if index < len(members) - 1 else ""))
        return lines + ["  }"]

    def _map(self, type_: Type) -> str:
        """A map as a list of key / value pairs (ASN.1 has no map type)."""
        key = self._constrained_ref(type_.key_type or TypeRef(name="string"), None, type_.key)
        value = self._constrained_ref(type_.value_type or TypeRef(name="bytes"), None, type_.key)
        self.losses.record(
            LossKind.INFERRED, "map-as-sequence",
            f"ASN.1 has no map type; {type_.key!r} is written as SEQUENCE OF SEQUENCE {{ key, value }}, which does "
            "not require its keys to be unique.",
            pointer=type_.key,
        )
        return f"SEQUENCE OF SEQUENCE {{ key {key}, value {value} }}"

    # --- components ---------------------------------------------------------

    def _field(self, field: CanonicalField) -> str:
        """A component's type with its constraints, then ``DEFAULT …`` or ``OPTIONAL``."""
        expr = self._constrained_ref(field.type, field.constraints, field.key)
        if field.default is not None:
            default = self._default(field)
            if default is not None:
                return f"{expr} DEFAULT {default}"
            self.losses.record(
                LossKind.NA, "default-dropped",
                f"The default {field.default!r} of {field.key!r} has no ASN.1 value notation for its type; "
                "the component is written OPTIONAL instead.",
                pointer=field.key,
            )
            return f"{expr} OPTIONAL"
        return f"{expr} OPTIONAL" if field.type.nullable else expr

    def _default(self, field: CanonicalField) -> Optional[str]:
        """``field.default`` in ASN.1 value notation for the field's type, or ``None`` when it cannot be."""
        if field.type.is_list():
            return None
        value = field.default
        target = self._resolve(field.type.name or "")
        if target is not None and target.kind is TypeKind.ENUM:
            for member in target.enum_values:
                if value in (member.name, member.value) and not isinstance(value, bool):
                    return Namer(identifier).name(member.name or str(member.value))
            return None
        kind = self._kind(field.type)
        if kind == "bool":
            if isinstance(value, bool):
                return "TRUE" if value else "FALSE"
            if isinstance(value, str) and value.upper() in ("TRUE", "FALSE"):
                return value.upper()
        elif kind in ("integer", "real"):
            number = _number(value)
            if number is not None and (kind == "real" or float(number).is_integer()):
                return number_literal(int(number) if kind == "integer" else number)
        elif kind == "string" and isinstance(value, str):
            return cstring_literal(value)
        return None

    # --- references and subtype constraints ----------------------------------

    def _resolve(self, name: str) -> Optional[Type]:
        """The model type a reference names: by key, else by its name when that is unique."""
        return self._types_by_key.get(name) or self._by_unique_name.get(name)

    def _kind(self, ref: TypeRef, _seen: Optional[set] = None) -> str:
        """The value kind a reference finally denotes (``string``, ``integer``, ``list``, ``record`` …)."""
        if ref.is_list():
            return "list"
        target = self._resolve(ref.name or "")
        if target is None:
            spec = _scalar_spec(ref.name or "")
            return spec[1] if spec else "unknown"
        seen = _seen or set()
        if target.key in seen:
            return "unknown"
        seen.add(target.key)
        if target.kind is TypeKind.ALIAS and target.aliased is not None:
            return self._kind(target.aliased, seen)
        if target.kind is TypeKind.SCALAR:
            return _scalar_kind(target.name or "")
        return target.kind.value

    def _constrained_ref(
        self, ref: TypeRef, constraints: Optional[Constraints], owner: str, *, scalar_only: bool = False
    ) -> str:
        """A reference written as an ASN.1 type, with ``constraints`` as subtype notation.

        A list's ``minItems`` / ``maxItems`` size the ``SEQUENCE OF``; its other rules apply to the items.
        """
        if ref.is_list():
            item = ref.item or TypeRef(name="string")
            size = ""
            if constraints is not None:
                size = size_constraint(constraints.min_items, constraints.max_items)
                if constraints.unique_items:
                    self._dropped(owner, "uniqueItems", "ASN.1 has no notation for unique items")
                constraints = constraints.model_copy(update={"min_items": None, "max_items": None,
                                                             "unique_items": None})
            inner = self._constrained_ref(item, constraints, owner)
            return f"SEQUENCE {size} OF {inner}" if size else f"SEQUENCE OF {inner}"
        name = ref.name or "string"
        target = None if scalar_only else self._resolve(name)
        if target is not None:
            base, width = self._type_names.name(target.name or target.key, key=target.key), None
        else:
            base, width = self._scalar(name, owner, constraints)
        return self._subtype(base, self._kind(ref) if not scalar_only else _scalar_kind(name), width,
                             constraints, owner)

    def _scalar(self, name: str, owner: str, constraints: Optional[Constraints]) -> Tuple[str, Optional[Tuple]]:
        """The ASN.1 type of a canonical scalar name (a string's time ``format`` picks a time type)."""
        spec = _scalar_spec(name)
        fmt = constraints.format if constraints is not None else None
        if spec is not None and spec[1] == "string" and fmt in _TIME_FORMATS:
            return _TIME_FORMATS[fmt], None
        if spec is None:
            self.losses.record(
                LossKind.INFERRED, "unmapped-scalar",
                f"{name!r} has no ASN.1 type; values of it are written as UTF8String.",
                pointer=owner,
            )
            return "UTF8String", None
        return spec[0], spec[2]

    def _subtype(
        self, base: str, kind: str, width: Optional[Tuple[int, int]], constraints: Optional[Constraints], owner: str
    ) -> str:
        """``base`` followed by the subtype constraints ``constraints`` (and an integer's width) allow."""
        c = constraints or Constraints()
        parts: List[str] = []
        if kind in ("string", "bytes"):
            parts.append(size_constraint(c.min_length, c.max_length))
            if c.pattern and kind == "string":
                parts.append(self._pattern(c.pattern, owner))
            elif c.pattern:
                self._dropped(owner, "pattern", "a pattern applies to text, not to bytes")
            if c.enum:
                self._dropped(owner, "enum", "asn1tools cannot read a set of string values")
        elif kind == "integer":
            parts.append(self._integer_range(c, width, owner))
        elif kind == "real":
            parts.append(self._real_range(c, owner))
        else:
            for keyword in _CONSTRAINT_KEYWORDS:
                if getattr(c, keyword) not in (None, [], False):
                    self._dropped(owner, keyword, f"it does not apply to {kind} values")
        if kind in ("integer", "real") and c.multiple_of is not None:
            self._dropped(owner, "multipleOf", "ASN.1 has no notation for a multiple")
        if c.format and c.format not in _TIME_FORMATS and kind in ("string", "time"):
            self._dropped(owner, f"format {c.format}", "ASN.1 has no type for it; the value is plain text")
        suffix = " ".join(part for part in parts if part)
        return f"{base} {suffix}" if suffix else base

    def _integer_range(self, c: Constraints, width: Optional[Tuple[int, int]], owner: str) -> str:
        """An INTEGER's value range (bounds intersected with its width), or its value set."""
        low, high = integer_bounds(c.minimum, c.maximum, c.exclusive_minimum, c.exclusive_maximum)
        if width is not None:
            low = width[0] if low is None else max(low, width[0])
            high = width[1] if high is None else min(high, width[1])
        if low is not None and high is not None and low > high:
            self._dropped(owner, "minimum/maximum", f"the bounds {low}..{high} admit no value")
            low, high = width if width is not None else (None, None)
        values = [v for v in (c.enum or []) if isinstance(v, int) and not isinstance(v, bool)]
        if c.enum and len(values) == len(c.enum):
            return "(" + " | ".join(number_literal(v) for v in dict.fromkeys(values)) + ")"
        if c.enum:
            self._dropped(owner, "enum", "only a set of integers can be written for an INTEGER")
        return value_range(low, high)

    def _real_range(self, c: Constraints, owner: str) -> str:
        """A REAL's value range; an exclusive bound is written inclusive (``asn1tools`` cannot read ``<``)."""
        low = c.minimum if c.minimum is not None else c.exclusive_minimum
        high = c.maximum if c.maximum is not None else c.exclusive_maximum
        for keyword, bound, used in (("exclusiveMinimum", c.exclusive_minimum, low),
                                     ("exclusiveMaximum", c.exclusive_maximum, high)):
            if bound is not None and used == bound:
                self.losses.record(
                    LossKind.INFERRED, "exclusive-bound-inclusive",
                    f"{keyword} {number_literal(bound)} of {owner!r} is written as an inclusive bound: asn1tools "
                    "cannot read an exclusive REAL bound (`<`), so the bound itself is accepted.",
                    pointer=owner,
                )
        if c.enum:
            self._dropped(owner, "enum", "a REAL takes no value set here")
        if low is not None and high is not None and low > high:
            self._dropped(owner, "minimum/maximum", f"the bounds {low}..{high} admit no value")
            return ""
        return value_range(low, high)

    def _pattern(self, pattern: str, owner: str) -> str:
        """``(PATTERN "…")`` — recorded, since X.680 reads it in its own regular-expression syntax."""
        literal = cstring_literal(pattern)
        if literal is None:
            self._dropped(owner, "pattern", "it contains a quote or a line break, which asn1tools cannot read")
            return ""
        self.losses.record(
            LossKind.INFERRED, "pattern-dialect",
            f"The pattern of {owner!r} is written as an X.680 PATTERN, which uses the regular-expression syntax of "
            "X.680 Annex A rather than ECMAScript's; asn1tools does not check it when encoding.",
            pointer=owner,
        )
        return f"(PATTERN {literal})"

    # --- bookkeeping --------------------------------------------------------

    def _dropped(self, owner: str, keyword: str, reason: str) -> None:
        """Record a constraint left out of the module."""
        self.losses.record(LossKind.NA, "constraint-dropped",
                           f"`{keyword}` of {owner!r} is not written: {reason}.", pointer=owner)

    def _renamed(self, source: Optional[str], written: str, key: str, what: str) -> None:
        """Record a name ASN.1 spells differently (``order_id`` → ``order-id``)."""
        if source and source != written:
            self.losses.record(LossKind.INFERRED, "name-respelled",
                               f"The {what} {source!r} is written as {written!r} to follow the ASN.1 naming rules.",
                               pointer=key)

    def _comment_lines(self, text: Optional[str], indent: str, key: str) -> List[str]:
        """A description as ``--`` comment lines (only with ``include_comments``); either way recorded,
        since an ASN.1 import does not read comments."""
        if not text:
            return []
        if not self._options.include_comments:
            self.losses.record(LossKind.NA, "description-dropped",
                               f"The description of {key!r} is not written (comments are switched off).", pointer=key)
            return []
        self.losses.record(LossKind.INFERRED, "description-as-comment",
                           f"The description of {key!r} is written as a comment, which an ASN.1 import does not read.",
                           pointer=key)
        return [f"{indent}-- {_comment(line)}".rstrip() for line in text.strip().splitlines()]


def _owning_construct(pointer: str, constructs: set) -> str:
    """The construct a writer loss belongs to: its own key, else the longest key it extends, else the root."""
    if pointer in constructs:
        return pointer
    owners = [key for key in constructs if key and pointer.startswith(f"{key}.")]
    return max(owners, key=len) if owners else ""


def _comment(text: str) -> str:
    """``text`` safe inside a ``--`` comment: a second ``--`` would end the comment early."""
    return re.sub(r"-{2,}", lambda m: " ".join("-" * len(m.group())), text)


def _scalar_spec(name: str) -> Optional[Tuple[str, str, Optional[Tuple[int, int]]]]:
    """(ASN.1 type, kind, width) of a canonical scalar name or an ASN.1 built-in, else ``None``."""
    return _SCALARS.get(name.lower()) or _ASN1_BUILTINS.get(name.rsplit(".", 1)[-1])


def _scalar_kind(name: str) -> str:
    """The value kind of a scalar type's own name (an unknown scalar is written as text)."""
    spec = _scalar_spec(name)
    return spec[1] if spec else "string"


def _number(value: Any) -> Optional[float]:
    """``value`` as a number (an int, a float, or numeric text), else ``None``."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        try:
            return float(value) if any(ch in value for ch in ".eE") else int(value)
        except ValueError:
            return None
    return None


def validate_asn1_module(content: str) -> None:
    """Validate ASN.1 module text by compiling it with ``asn1tools``.

    Raises:
        asn1tools.ParseError / asn1tools.CompileError: The module does not parse or compile.
    """
    import asn1tools

    asn1tools.compile_string(content)
