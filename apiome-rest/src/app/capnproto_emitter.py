"""Cap'n Proto emitter: canonical model → ``.capnp`` — MFX-17.1, MFX-30.2 (#4179).

The inverse of :class:`app.capnproto_normalizer.CapnpNormalizer` and an implementation of
the :class:`app.emitter.Emitter` SPI. Any canonical model exports, not only one imported from
``.capnp``, and the output compiles under ``capnp compile``:

* ``RECORD`` → ``struct`` with ``@N`` field ordinals; types nested in a ``.capnp`` source stay nested;
* ``ENUM`` → ``enum`` with ``@N`` enumerants;
* ``UNION`` → a ``struct`` holding an unnamed ``union`` group, one member per variant;
* ``MAP`` → a ``struct`` with ``entries :List(Entry)`` and a nested ``Entry`` (``key``, ``value``);
* ``ALIAS`` / ``SCALAR`` → ``using Name = …;``;
* lists → ``List(T)``; scalars through :data:`app.scalar_aliases.CAPNP_SCALAR_FOR_KIND`;
* services → ``interface`` with ``@N`` methods; parameters and the request body become the method's
  parameter list, the response body its result.

Names are rewritten to the compiler's rules (:mod:`app.capnproto_names`). Ordinals and the file
``@0x`` id come from the source when it is a ``.capnp`` import; otherwise they are synthesized and
kept stable across re-exports through the field-identity store (:mod:`app.capnproto_identity`).
"""

from __future__ import annotations

import posixpath
import re
from typing import Dict, List, Optional, Set, Tuple, Union

from pydantic import Field

from .canonical_model import (
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    MessageRole,
    Operation,
    OperationKind,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from .capnproto_identity import (
    FILE_ID_KEY,
    Layout,
    OrdinalAllocator,
    Slot,
    file_id_from_store,
    file_id_to_store,
    format_file_id,
    parse_file_id,
    placeholder_type,
    synthesize_file_id,
)
from .capnproto_names import BUILTIN_TYPE_NAMES, NameScope, member_identifier, type_identifier
from .constraint_text import constraint_comment
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
from .fidelity_rulepack import CapabilityRulePack, FidelityVerdict, rename_verdict
from .lossiness import LossinessKind, LossinessReport, LossinessSeverity
from .scalar_aliases import CAPNP_SCALAR_FOR_KIND, target_scalar
from .writer_loss_rulepack import filed_writer_verdicts

__all__ = ["CapnpEmitOptions", "CapnpEmitter", "CapnpFidelityRulePack"]

_CANONICAL_TO_CAPNP: Dict[str, str] = {
    "bool": "Bool",
    "int8": "Int8",
    "uint8": "UInt8",
    "i16": "Int16",
    "uint16": "UInt16",
    "i32": "Int32",
    "uint32": "UInt32",
    "i64": "Int64",
    "uint64": "UInt64",
    "float": "Float32",
    "double": "Float64",
    "string": "Text",
    "bytes": "Data",
    "void": "Void",
}

#: Wire size class of each built-in type; everything not listed is a pointer.
_BUILTIN_LAYOUT: Dict[str, Layout] = {
    "Void": Layout.VOID,
    "Bool": Layout.BOOL,
    "Int8": Layout.BITS8,
    "UInt8": Layout.BITS8,
    "Int16": Layout.BITS16,
    "UInt16": Layout.BITS16,
    "Int32": Layout.BITS32,
    "UInt32": Layout.BITS32,
    "Float32": Layout.BITS32,
    "Int64": Layout.BITS64,
    "UInt64": Layout.BITS64,
    "Float64": Layout.BITS64,
}

_EVENT_OPERATION_KINDS = frozenset({OperationKind.PUBLISH, OperationKind.SUBSCRIBE})

#: The source format whose ordinals and file id the emitter takes as given.
_CAPNP_FORMAT = "capnproto"


class CapnpFidelityRulePack(CapabilityRulePack):
    """Fidelity rules for Cap'n Proto export — MFX-30.2 (#4179), MFX-30.3 (#4180).

    The pack builds the schema with the Cap'n Proto writer (default options) and files each loss the
    writer records on the construct it concerns, beside the capability verdicts:

    * **operations** — an interface method, ``APPROX``: how it is called (HTTP method, path, parameter
      locations) is not kept (an operation of a ``.capnp`` source is its own method); its error responses
      are a ``DROP``; an event operation and every channel are a ``DROP``;
    * **constraints** — written as a ``#`` comment that nothing checks, ``APPROX``;
    * **maps** — a struct with a list of key/value ``Entry`` structs, ``APPROX``;
    * **ordinals and the file id** — an ``@N`` ordinal or ``@0x…`` file id the source does not give is
      ``SYNTH``, as are placeholders kept for a removed member or a gap;
    * a name that breaks the compiler's rules is an ``APPROX`` rename (info), so a re-import showing the
      new name is never a surprise; single-member unions, inline payloads and untyped or unmapped values
      are ``APPROX``.
    """

    target_label = "Cap'n Proto"

    #: Writer loss subject → (verdict kind, severity).
    _WRITER_LOSSES = {
        "operation-as-method": (LossinessKind.APPROX, LossinessSeverity.WARN),
        "errors-dropped": (LossinessKind.DROP, LossinessSeverity.WARN),
        "constraints-as-comment": (LossinessKind.APPROX, LossinessSeverity.WARN),
        "constraints-dropped": (LossinessKind.DROP, LossinessSeverity.WARN),
        "map-as-entry-list": (LossinessKind.APPROX, LossinessSeverity.WARN),
        "synthesized-ordinal": (LossinessKind.SYNTH, LossinessSeverity.INFO),
        "synthesized-file-id": (LossinessKind.SYNTH, LossinessSeverity.INFO),
        "retired-ordinal": (LossinessKind.SYNTH, LossinessSeverity.INFO),
        "ordinal-gap": (LossinessKind.SYNTH, LossinessSeverity.INFO),
        "single-member-union": (LossinessKind.APPROX, LossinessSeverity.WARN),
        "inline-payload": (LossinessKind.APPROX, LossinessSeverity.WARN),
        "untyped-value": (LossinessKind.APPROX, LossinessSeverity.WARN),
        "unmapped-type": (LossinessKind.APPROX, LossinessSeverity.WARN),
        "unsupported-type": (LossinessKind.DROP, LossinessSeverity.CRITICAL),
    }
    #: Set by :meth:`evaluate`: construct key → the verdicts of its writer losses.
    _filed: Dict[str, List[FidelityVerdict]] = {}

    def evaluate(self, api: CanonicalApi) -> LossinessReport:
        """Build the schema once (as it will be emitted), file its losses by construct, then walk the model."""
        writer = _CapnpWriter(api, CapnpEmitOptions())
        writer.render()
        self._filed = filed_writer_verdicts(api, writer.losses.records(), self._WRITER_LOSSES)
        return super().evaluate(api)

    def root_verdicts(self, api: CanonicalApi) -> List[FidelityVerdict]:
        """What the writer synthesized for the schema itself (its file id)."""
        return self._filed.get("", [])

    def event_verdict(self, event) -> FidelityVerdict:
        return FidelityVerdict.drop(
            message=f"{self.target_label} has no event/channel representation; event {event.key!r} is dropped",
            target_mapping="event → dropped",
        )

    def operation_verdicts(self, operation: Operation) -> List[FidelityVerdict]:
        return [self.operation_verdict(operation), *self._filed.get(operation.key, [])]

    def operation_verdict(self, operation: Operation) -> FidelityVerdict:
        verdict = super().operation_verdict(operation)
        if verdict.kind is not LossinessKind.OK:
            return verdict
        source = operation.name or operation.key
        renamed = _rename_verdict(source, member_identifier(source, fallback="method"), "method")
        return renamed or verdict

    def type_verdicts(self, type_: Type) -> List[FidelityVerdict]:
        return [self.type_verdict(type_), *self._filed.get(type_.key, [])]

    def type_verdict(self, type_: Type) -> FidelityVerdict:
        verdict = super().type_verdict(type_)
        if verdict.kind is not LossinessKind.OK:
            return verdict
        return _rename_verdict(type_.name, type_identifier(type_.name), "type") or verdict

    def field_verdicts(self, field: CanonicalField) -> List[FidelityVerdict]:
        verdicts = super().field_verdicts(field) + self._filed.get(field.key, [])
        renamed = _rename_verdict(field.name, member_identifier(field.name), "field")
        return [*verdicts, renamed] if renamed else verdicts

    def _constraints_verdict(self, field: CanonicalField) -> Optional[FidelityVerdict]:
        """Reported from the writer, which says what it wrote (a comment, or nothing)."""
        return None

    def _field_identity_verdict(self, field: CanonicalField) -> Optional[FidelityVerdict]:
        """Reported from the writer, which knows the ordinals a ``.capnp`` source gives."""
        return None


def _rename_verdict(source: str, emitted: str, noun: str) -> Optional[FidelityVerdict]:
    """An ``APPROX`` (info) verdict when Cap'n Proto writes ``source`` as ``emitted``, else ``None``."""
    return rename_verdict(source, emitted, target_label=CapnpFidelityRulePack.target_label, noun=noun)


class CapnpEmitOptions(EmitOptions):
    """Per-target options for :class:`CapnpEmitter`."""

    include_comments: bool = Field(
        default=True,
        description="Emit brief generated-file header comments.",
    )
    persisted_field_numbers: Dict[str, int] = Field(
        default_factory=dict,
        description="Pre-loaded stable ordinals, field layouts and the file id, keyed as "
        "app.capnproto_identity describes (MFX-30.2).",
    )


class CapnpEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as a Cap'n Proto ``.capnp`` schema."""

    key = "capnproto"
    format = "capnproto"
    label = "Cap'n Proto"
    description = "Export as a Cap'n Proto schema (.capnp)."
    icon = "zap"
    paradigm = ApiParadigm.RPC
    multi_file = False
    options_model = CapnpEmitOptions

    OUTPUT_MEDIA_TYPE = "text/x-capnproto"

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        return CapabilityProfile(
            operations=True,
            events=False,
            unions=True,
            nullability=False,
            field_identity=True,
        )

    @classmethod
    def fidelity_rule_pack(cls) -> type[CapabilityRulePack]:
        return CapnpFidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[CapnpEmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        options = (
            opts
            if isinstance(opts, CapnpEmitOptions)
            else CapnpEmitOptions.model_validate(opts.model_dump() if opts else {})
        )
        writer = _CapnpWriter(api, options)
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


class _CapnpWriter:
    """Render one canonical model as ``.capnp`` text (single use)."""

    def __init__(self, api: CanonicalApi, options: CapnpEmitOptions) -> None:
        self._api = api
        self._options = options
        self._persisted = options.persisted_field_numbers
        self._capnp_source = api.format == _CAPNP_FORMAT
        self.tracker = ProvenanceTracker()
        self.losses = LossTracker()
        self._types_by_key = {t.key: t for t in api.types}
        self.output_path = _output_path(api)
        #: Store rows assigned on this export that were not stored before (ordinals, layouts, the
        #: file id), for the caller to persist so the next export reuses them (MFX-30.2).
        self.field_identity_assignments: Dict[str, int] = {}

        self._file_scope = NameScope()
        self._import_names = self._plan_imports()
        #: Type key → the name a reference writes (``Person.PhoneNumber`` for a nested type).
        self._paths: Dict[str, str] = {}
        self._children: Dict[str, List[Type]] = {}
        self._top_level: List[Type] = []
        self._plan_types()
        self._interface_names = {
            service.key: self._file_scope.claim(type_identifier(service.name, fallback="Service"))
            for service in api.services
        }

    # ------------------------------------------------------------------
    # Planning: names and nesting, before anything is written
    # ------------------------------------------------------------------

    def _plan_imports(self) -> List[Tuple[str, str]]:
        """Claim a ``using <Name> = import "<path>";`` name for each import a ``.capnp`` source had."""
        imports = self._api.extras.get("capnp_imports") or []
        planned: List[Tuple[str, str]] = []
        if isinstance(imports, list):
            for path in imports:
                if not isinstance(path, str) or not path:
                    continue
                stem = posixpath.splitext(posixpath.basename(path))[0]
                planned.append((self._file_scope.claim(type_identifier(stem, fallback="Import")), path))
        return planned

    def _plan_types(self) -> None:
        """Decide which types nest inside which struct, then give every type its name and path."""
        by_qualified: Dict[str, Type] = {}
        for type_ in self._api.types:
            by_qualified.setdefault(self._qualified_name(type_), type_)
        for type_ in self._api.types:
            parent = self._nesting_parent(type_, by_qualified)
            if parent is None:
                self._top_level.append(type_)
            else:
                self._children.setdefault(parent.key, []).append(type_)
        for type_ in self._top_level:
            self._name_type(type_, scope=self._file_scope, parent_path=None)

    def _name_type(self, type_: Type, *, scope: NameScope, parent_path: Optional[str]) -> None:
        name = scope.claim(type_identifier(type_.name))
        path = f"{parent_path}.{name}" if parent_path else name
        self._paths[type_.key] = path
        children = self._children.get(type_.key, [])
        if children:
            inner = NameScope()
            for child in children:
                self._name_type(child, scope=inner, parent_path=path)

    @staticmethod
    def _qualified_name(type_: Type) -> str:
        qualified = type_.extras.get("capnp_qualified_name")
        return qualified if isinstance(qualified, str) and qualified else type_.name

    def _nesting_parent(self, type_: Type, by_qualified: Dict[str, Type]) -> Optional[Type]:
        """The struct a ``.capnp`` source declared ``type_`` inside, if it is in the model."""
        qualified = type_.extras.get("capnp_qualified_name")
        if not (isinstance(qualified, str) and "." in qualified):
            return None
        parent = by_qualified.get(qualified.rsplit(".", 1)[0])
        if parent is None or parent is type_ or parent.kind is not TypeKind.RECORD:
            return None
        return parent

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render(self) -> str:
        lines: List[str] = []
        if self._options.include_comments:
            title = self._api.identity.name or "Exported schema"
            lines.append(f"# Generated Cap'n Proto schema for {title}")
            lines.append("")

        lines.append(f"@{format_file_id(self._file_id())};")
        lines.append("")

        for name, path in self._import_names:
            lines.append(f'using {name} = import "{path}";')
        if self._import_names:
            lines.append("")

        for type_ in self._top_level:
            rendered = self._render_type(type_, depth=0)
            if rendered:
                lines.extend(rendered)
                lines.append("")

        for service in self._api.services:
            lines.extend(self._render_interface(service))
            lines.append("")

        if self._api.channels:
            self.losses.record(
                LossKind.NA,
                "channels-dropped",
                "Cap'n Proto export omits event/channel constructs",
                pointer="channels",
            )

        return "\n".join(lines).rstrip() + "\n"

    def _file_id(self) -> int:
        """The file id: the source's, else the stored one, else a new one (then persisted)."""
        source_id = parse_file_id(self._api.extras.get("capnp_file_id"))
        if source_id is not None:
            self.tracker.record("file-id", Provenance.SOURCE)
            return source_id
        file_id = file_id_from_store(self._persisted.get(FILE_ID_KEY))
        if file_id is None:
            identity = self._api.identity
            file_id = synthesize_file_id(f"{identity.namespace or ''}/{identity.name or 'schema'}")
            self.field_identity_assignments[FILE_ID_KEY] = file_id_to_store(file_id)
        self.tracker.record("file-id", Provenance.INFERRED, "synthesized file id")
        self.losses.record(
            LossKind.INFERRED,
            "synthesized-file-id",
            f"The source has no Cap'n Proto file id; the schema uses @{format_file_id(file_id)}.",
            pointer="file-id",
        )
        return file_id

    def _render_type(self, type_: Type, *, depth: int) -> List[str]:
        capnp_kind = type_.extras.get("capnp_kind")
        if type_.kind is TypeKind.ENUM or capnp_kind == "enum":
            return self._render_enum(type_, depth)
        if type_.kind is TypeKind.UNION:
            return self._render_union(type_, depth)
        if type_.kind is TypeKind.RECORD or capnp_kind == "struct":
            return self._render_struct(type_, depth)
        if type_.kind is TypeKind.MAP:
            return self._render_map(type_, depth)
        if type_.kind in (TypeKind.ALIAS, TypeKind.SCALAR):
            return self._render_using(type_, depth)
        self.losses.record(
            LossKind.NA,
            "unsupported-type",
            f"Type {type_.key!r} has no Cap'n Proto representation and is skipped",
            pointer=type_.key,
        )
        return []

    def _render_enum(self, type_: Type, depth: int) -> List[str]:
        pad = _indent(depth)
        from_capnp = type_.extras.get("capnp_kind") == "enum"
        scope = NameScope()
        allocator = OrdinalAllocator(type_.key, self._persisted)
        for value in type_.enum_values:
            name = scope.claim(member_identifier(value.name, fallback="value"))
            source = value.value if from_capnp and isinstance(value.value, int) else None
            allocator.add(name, value, source_ordinal=source)
        lines = [f"{pad}enum {_last_segment(self._paths[type_.key])} {{"]
        for slot in self._finish(allocator, type_.key, scope):
            if slot.member is not None:
                self._record_member(slot, slot.member.key, "enum value")
            lines.append(f"{pad}  {slot.name} @{slot.ordinal};")
        lines.append(f"{pad}}}")
        self.tracker.record(type_.key, Provenance.SOURCE)
        return lines

    def _render_struct(self, type_: Type, depth: int) -> List[str]:
        pad = _indent(depth)
        scope = NameScope()
        allocator = OrdinalAllocator(type_.key, self._persisted)
        for field in type_.fields:
            name = scope.claim(member_identifier(field.name))
            expr, layout = self._resolve(field.type, _field_format(field), pointer=field.key)
            slot_value = field.extras.get("capnp_slot")
            allocator.add(
                name,
                (field, expr),
                source_ordinal=slot_value if isinstance(slot_value, int) else None,
                layout=layout,
            )
        lines = [f"{pad}struct {_last_segment(self._paths[type_.key])} {{"]
        lines.extend(self._field_lines(allocator, type_.key, scope, pad=f"{pad}  "))
        for child in self._children.get(type_.key, []):
            rendered = self._render_type(child, depth=depth + 1)
            if rendered:
                lines.append("")
                lines.extend(rendered)
        lines.append(f"{pad}}}")
        self.tracker.record(type_.key, Provenance.SOURCE)
        return lines

    def _render_union(self, type_: Type, depth: int) -> List[str]:
        """A union becomes a struct holding one unnamed ``union`` group of its variants."""
        pad = _indent(depth)
        scope = NameScope()
        allocator = OrdinalAllocator(type_.key, self._persisted)
        if type_.fields:
            # Union fields (a Thrift ``union``, a Protobuf ``oneof``): one member each.
            for field in type_.fields:
                name = scope.claim(member_identifier(field.name))
                expr, layout = self._resolve(field.type, _field_format(field), pointer=field.key)
                allocator.add(name, (field, expr), layout=layout)
        else:
            for member_key in type_.union_members:
                ref = TypeRef(name=member_key)
                expr, layout = self._resolve(ref, None, pointer=type_.key)
                name = scope.claim(member_identifier(_last_segment(expr), fallback="variant"))
                allocator.add(name, (None, expr), layout=layout)
        body = self._field_lines(allocator, type_.key, scope, pad=f"{pad}    ")
        lines = [f"{pad}struct {_last_segment(self._paths[type_.key])} {{"]
        if len(body) >= 2:
            lines.append(f"{pad}  union {{")
            lines.extend(body)
            lines.append(f"{pad}  }}")
        else:
            # Cap'n Proto needs at least two union members; one becomes a plain field.
            lines.extend(line[2:] for line in body)
            self.losses.record(
                LossKind.INFERRED,
                "single-member-union",
                f"Union {type_.key!r} has fewer than two variants; Cap'n Proto needs two, so it is "
                "written as a plain struct.",
                pointer=type_.key,
            )
        lines.append(f"{pad}}}")
        self.tracker.record(type_.key, Provenance.SOURCE)
        return lines

    def _render_map(self, type_: Type, depth: int) -> List[str]:
        """Cap'n Proto has no map type: a map is a list of key/value entries."""
        pad = _indent(depth)
        key_expr, _ = self._resolve(type_.key_type or TypeRef(name="string"), None, pointer=type_.key)
        value_expr, _ = self._resolve(
            type_.value_type or TypeRef(name="string"), None, pointer=type_.key
        )
        self.losses.record(
            LossKind.INFERRED,
            "map-as-entry-list",
            f"Map {type_.key!r} is written as a list of key/value entries.",
            pointer=type_.key,
        )
        self.tracker.record(type_.key, Provenance.INFERRED, "map as entry list")
        return [
            f"{pad}struct {_last_segment(self._paths[type_.key])} {{",
            f"{pad}  entries @0 :List(Entry);",
            "",
            f"{pad}  struct Entry {{",
            f"{pad}    key @0 :{key_expr};",
            f"{pad}    value @1 :{value_expr};",
            f"{pad}  }}",
            f"{pad}}}",
        ]

    def _render_using(self, type_: Type, depth: int) -> List[str]:
        """An alias or a named scalar becomes ``using Name = <type>;``."""
        name = _last_segment(self._paths[type_.key])
        if type_.kind is TypeKind.ALIAS and type_.aliased is not None:
            expr, _ = self._resolve(type_.aliased, None, pointer=type_.key, seen={type_.key})
        else:
            fmt = type_.constraints.format if type_.constraints is not None else None
            builtin = self._scalar_expr(type_.name, fmt)
            if builtin is None:
                self._unmapped(type_.name, type_.key)
            expr = builtin or "Text"
        self.tracker.record(type_.key, Provenance.SOURCE)
        return [f"{_indent(depth)}using {name} = {expr};"]

    def _field_lines(
        self, allocator: OrdinalAllocator, scope_key: str, scope: NameScope, *, pad: str
    ) -> List[str]:
        """Render the slots of a struct (or union) scope, one ``name @N :Type;`` line each."""
        lines: List[str] = []
        for slot in self._finish(allocator, scope_key, scope):
            if slot.placeholder:
                lines.append(f"{pad}{slot.name} @{slot.ordinal} :{placeholder_type(slot.layout)};")
                continue
            field, expr = slot.member
            if field is not None:
                self._record_member(slot, field.key, "field")
                lines.extend(self._constraints(field, pad))
            lines.append(f"{pad}{slot.name} @{slot.ordinal} :{expr};")
        return lines

    def _constraints(self, field: CanonicalField, pad: str) -> List[str]:
        """A field's constraints as a ``#`` comment line — or, with comments off, nothing (both recorded).

        Cap'n Proto has no validation facets (MFX-30.3): a comment keeps them for the schema's readers,
        and nothing checks them.
        """
        text = constraint_comment(field.constraints)
        if text is None:
            return []
        if not self._options.include_comments:
            self.losses.record(
                LossKind.NA,
                "constraints-dropped",
                f"Cap'n Proto cannot enforce constraints and comments are off; the {text} of {field.key!r} "
                "are not written.",
                pointer=field.key,
            )
            return []
        self.losses.record(
            LossKind.INFERRED,
            "constraints-as-comment",
            f"Cap'n Proto cannot enforce constraints; those of {field.key!r} are written as a comment that "
            f"nothing checks ({text}).",
            pointer=field.key,
        )
        return [f"{pad}# {text}"]

    def _finish(self, allocator: OrdinalAllocator, scope_key: str, scope: NameScope) -> List[Slot]:
        """Close a scope: collect its new store rows and name (and report) its placeholders."""
        slots = allocator.finish()
        self.field_identity_assignments.update(allocator.new_assignments)
        for slot in slots:
            if not slot.placeholder:
                continue
            if slot.retired:
                original = slot.name
                slot.name = scope.claim(f"obsolete{original[:1].upper()}{original[1:]}")
                self.losses.record(
                    LossKind.INFERRED,
                    "retired-ordinal",
                    f"{original!r} is no longer in {scope_key!r}; Cap'n Proto cannot remove a member, "
                    f"so @{slot.ordinal} is kept as {slot.name!r}.",
                    pointer=f"{scope_key}.{original}",
                )
            else:
                slot.name = scope.claim(slot.name)
                self.losses.record(
                    LossKind.INFERRED,
                    "ordinal-gap",
                    f"{scope_key!r} has no member numbered @{slot.ordinal}; Cap'n Proto needs "
                    f"ordinals without gaps, so it is written as {slot.name!r}.",
                    pointer=scope_key,
                )
        return slots

    def _record_member(self, slot: Slot, key: str, noun: str) -> None:
        """Note a member's provenance — and, when its ordinal was synthesized, the loss."""
        if not slot.synthesized:
            self.tracker.record(key, Provenance.SOURCE)
            return
        self.tracker.record(key, Provenance.INFERRED, "synthesized ordinal")
        self.losses.record(
            LossKind.INFERRED,
            "synthesized-ordinal",
            f"The source gives {noun} {key!r} no Cap'n Proto ordinal; assigned @{slot.ordinal}.",
            pointer=key,
        )

    # ------------------------------------------------------------------
    # Interfaces
    # ------------------------------------------------------------------

    def _render_interface(self, service: Service) -> List[str]:
        scope = NameScope()
        allocator = OrdinalAllocator(service.key, self._persisted)
        for operation in service.operations:
            if operation.kind in _EVENT_OPERATION_KINDS:
                self.losses.record(
                    LossKind.NA,
                    "event-operation-dropped",
                    f"Operation {operation.key!r} is an event; a Cap'n Proto interface has no "
                    "representation for it.",
                    pointer=operation.key,
                )
                continue
            name = scope.claim(member_identifier(operation.name or operation.key, fallback="method"))
            slot_value = operation.extras.get("capnp_slot")
            allocator.add(
                name, operation, source_ordinal=slot_value if isinstance(slot_value, int) else None
            )
        lines = [f"interface {self._interface_names[service.key]} {{"]
        for slot in self._finish(allocator, service.key, scope):
            if slot.placeholder:
                lines.append(f"  {slot.name} @{slot.ordinal} () -> ();")
                continue
            self._record_member(slot, slot.member.key, "method")
            if not self._capnp_source:
                self.losses.record(
                    LossKind.INFERRED,
                    "operation-as-method",
                    f"Operation {slot.member.key!r} is written as the interface method {slot.name!r} "
                    f"@{slot.ordinal}; how it is called (an HTTP method and path, where each parameter goes) "
                    "is not kept.",
                    pointer=slot.member.key,
                )
            params = self._render_params(slot.member)
            results = self._render_results(slot.member)
            lines.append(f"  {slot.name} @{slot.ordinal} ({params}) -> ({results});")
        lines.append("}")
        self.tracker.record(service.key, Provenance.SOURCE)
        return lines

    def _render_params(self, operation: Operation) -> str:
        """The method's parameter list: a ``.capnp`` source's own, else its parameters and body."""
        request = next((m for m in operation.messages if m.role is MessageRole.REQUEST), None)
        inline = request.extras.get("capnp_parameters") if request else None
        if isinstance(inline, list):
            return ", ".join(
                f"{param['name']} :{self._capnp_type_expr(param['type'])}" for param in inline
            )
        scope = NameScope()
        parts: List[str] = []
        for param in operation.parameters:
            fmt = param.constraints.format if param.constraints is not None else None
            expr, _ = self._resolve(param.type, fmt, pointer=param.key)
            parts.append(f"{scope.claim(member_identifier(param.name, fallback='param'))} :{expr}")
        if request and request.payload:
            name = member_identifier(request.extras.get("capnp_param_name", "arg"), fallback="arg")
            expr, _ = self._resolve(request.payload, None, pointer=request.key)
            parts.append(f"{scope.claim(name)} :{expr}")
        elif request and request.payload_schema:
            parts.append(f"{scope.claim('arg')} :AnyPointer")
            self.losses.record(
                LossKind.INFERRED,
                "inline-payload",
                f"The request body of {operation.key!r} is an inline schema; it is passed as "
                "AnyPointer.",
                pointer=request.key,
            )
        errors = [m for m in operation.messages if m.role is MessageRole.ERROR]
        if errors:
            self.losses.record(
                LossKind.NA,
                "errors-dropped",
                f"Cap'n Proto methods declare no error types; {len(errors)} error response(s) of "
                f"{operation.key!r} are omitted.",
                pointer=operation.key,
            )
        return ", ".join(parts)

    def _render_results(self, operation: Operation) -> str:
        responses = [m for m in operation.messages if m.role is MessageRole.RESPONSE]
        response = next((m for m in responses if m.payload), responses[0] if responses else None)
        if not response:
            return ""
        inline = response.extras.get("capnp_results")
        if isinstance(inline, list):
            return ", ".join(
                f"{result['name']} :{self._capnp_type_expr(result['type'])}" for result in inline
            )
        if response.payload:
            name = member_identifier(
                response.extras.get("capnp_result_name", "result"), fallback="result"
            )
            expr, _ = self._resolve(response.payload, None, pointer=response.key)
            return f"{name} :{expr}"
        return ""

    def _capnp_type_expr(self, type_expr: str) -> str:
        """A type written in a ``.capnp`` source's method signature, with built-ins normalized."""
        list_match = re.fullmatch(r"List\s*\(\s*([^)]+)\s*\)", type_expr.strip(), re.IGNORECASE)
        if list_match:
            return f"List({self._capnp_type_expr(list_match.group(1))})"
        mapped = _CANONICAL_TO_CAPNP.get(type_expr.lower())
        return mapped or type_expr

    # ------------------------------------------------------------------
    # Type references
    # ------------------------------------------------------------------

    def _resolve(
        self,
        ref: TypeRef,
        fmt: Optional[str],
        *,
        pointer: str,
        seen: Optional[Set[str]] = None,
    ) -> Tuple[str, Layout]:
        """Render a type reference and report its wire size class.

        Args:
            ref: The reference (a list, a named type, or a scalar spelling).
            fmt: The use site's ``format`` constraint (picks the width of ``integer``/``number``).
            pointer: Where the reference sits, for loss records.
            seen: Alias keys already being resolved (guards a cyclic alias).

        Returns:
            ``(type expression, layout)``, e.g. ``("List(Pet)", Layout.POINTER)``.
        """
        if ref.item is not None:
            inner, _ = self._resolve(ref.item, fmt, pointer=pointer, seen=seen)
            # ``List(AnyPointer)`` does not compile; a list of untyped values is an ``AnyList``.
            return ("AnyList" if inner == "AnyPointer" else f"List({inner})"), Layout.POINTER
        name = ref.name
        if not name:
            self.losses.record(
                LossKind.INFERRED,
                "untyped-value",
                f"{pointer!r} has no declared type; it is written as AnyPointer.",
                pointer=pointer,
            )
            return "AnyPointer", Layout.POINTER
        target = self._types_by_key.get(name)
        if target is not None and target.key in self._paths:
            return self._paths[target.key], self._type_layout(target, seen or set())
        builtin = self._scalar_expr(name, fmt)
        if builtin is not None:
            return builtin, _BUILTIN_LAYOUT.get(builtin, Layout.POINTER)
        if self._capnp_source:
            # A name from an imported file (``Party``, ``Shared.Money``): kept as written.
            return name, Layout.POINTER
        self._unmapped(name, pointer)
        return "Text", Layout.POINTER

    def _scalar_expr(self, name: str, fmt: Optional[str]) -> Optional[str]:
        """The built-in Cap'n Proto type for a scalar spelling, or ``None``."""
        if name in BUILTIN_TYPE_NAMES:
            return name
        return _CANONICAL_TO_CAPNP.get(name.lower()) or target_scalar(
            name, CAPNP_SCALAR_FOR_KIND, fmt
        )

    def _type_layout(self, type_: Type, seen: Set[str]) -> Layout:
        """The wire size class of a field whose type is the named ``type_``."""
        if type_.kind is TypeKind.ENUM or type_.extras.get("capnp_kind") == "enum":
            return Layout.BITS16
        if type_.key in seen:
            return Layout.POINTER
        if type_.kind is TypeKind.ALIAS and type_.aliased is not None:
            return self._resolve(
                type_.aliased, None, pointer=type_.key, seen={*seen, type_.key}
            )[1]
        if type_.kind is TypeKind.SCALAR:
            fmt = type_.constraints.format if type_.constraints is not None else None
            builtin = self._scalar_expr(type_.name, fmt)
            return _BUILTIN_LAYOUT.get(builtin or "Text", Layout.POINTER)
        return Layout.POINTER

    def _unmapped(self, name: str, pointer: str) -> None:
        self.losses.record(
            LossKind.INFERRED,
            "unmapped-type",
            f"{name!r} is not a Cap'n Proto type or a type in this model; it is written as Text.",
            pointer=pointer,
        )


def _indent(depth: int) -> str:
    return "  " * depth


def _last_segment(path: str) -> str:
    """``Person.PhoneNumber`` → ``PhoneNumber``; ``List(Pet)`` stays ``List(Pet)``."""
    return path if "(" in path else path.rsplit(".", 1)[-1]


def _field_format(field: CanonicalField) -> Optional[str]:
    return field.constraints.format if field.constraints is not None else None


def _output_path(api: CanonicalApi) -> str:
    base = api.identity.name or "schema"
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", base).strip("_") or "schema"
    return f"{safe}.capnp"
