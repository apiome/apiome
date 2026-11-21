"""ONC RPC / XDR emitter: canonical model → ``.x`` RPCL — MFX-24.1.

The inverse of :class:`app.oncrpc_normalizer.OncRpcNormalizer` and an implementation of
the :class:`app.emitter.Emitter` SPI.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple, Union

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
from .conversion_verdicts import (
    agent_loss_items,
    envelope_verdicts,
    paradigm_change_verdict,
    rekey_verdicts,
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
from .normalizer import Keys
from .oncrpc_parser import parse_oncrpc

__all__ = ["OncRpcEmitOptions", "OncRpcEmitter", "OncRpcFidelityRulePack", "validate_oncrpc_document"]

_CANONICAL_TO_XDR: Dict[str, str] = {
    "bool": "bool",
    "i16": "short",
    "i32": "int",
    "i64": "hyper",
    "uint16": "unsigned short",
    "uint32": "unsigned int",
    "uint64": "unsigned hyper",
    "float": "float",
    "double": "double",
    "string": "string",
    "bytes": "opaque",
    "void": "void",
}

_EVENT_OPERATION_KINDS = frozenset({OperationKind.PUBLISH, OperationKind.SUBSCRIBE})


_NON_IDENTIFIER = re.compile(r"[^A-Za-z0-9_]")


def _identifier(name: str) -> str:
    """Return ``name`` as an RPCL identifier (``[A-Za-z_][A-Za-z0-9_]*``).

    A name from another format (``Task API``, ``GET /orders``) is not one; every other character
    becomes ``_`` and a leading digit is prefixed with ``_``. A name read from RPCL is unchanged.

    Args:
        name: The canonical name of a type, field, service or operation.

    Returns:
        The identifier the writer uses for it.
    """
    folded = _NON_IDENTIFIER.sub("_", name or "") or "_"
    return f"_{folded}" if folded[0].isdigit() else folded


#: The namespace a reader gives the types of an RPCL file that declares no program.
_DEFAULT_NAMESPACE = "OncRpc"
#: The type kinds an RPCL file declares (an enum, a struct, a union); any other kind is not written.
_WRITTEN_KINDS = frozenset({TypeKind.ENUM, TypeKind.RECORD, TypeKind.UNION})


class OncRpcFidelityRulePack(CapabilityRulePack):
    """Fidelity rules for ONC RPC export.

    An RPCL file is enums, structs, unions and programs — it has no title, version or namespace of
    its own, and a reader files everything under the first program's name (``OncRpc`` when there is
    none). So a file built from another format's model (COA-3.1, #7052) reads back with every
    type, service and procedure re-keyed (``DROP`` + ``SYNTH``), a source that is not an RPC API
    reads back as one, and a type that is not an enum, a struct or a union is not written.
    """

    target_label = "ONC RPC"
    #: Whether the source is itself ONC RPC (:meth:`evaluate`); a pack asked before that adds nothing.
    _native = True

    def evaluate(self, api: CanonicalApi) -> LossinessReport:
        """Predict the namespace a re-import files the document under, then walk the model."""
        self._native = api.format == OncRpcEmitter.format
        self._namespace = _identifier(api.services[0].name) if api.services else _DEFAULT_NAMESPACE
        self._operation_keys: Dict[str, str] = {}
        self._rekeyed: Set[str] = set()
        if not self._native:
            for service in api.services:
                service_key = self._service_key(service)
                for operation in service.operations:
                    if operation.kind not in _EVENT_OPERATION_KINDS:
                        self._operation_keys[operation.key] = Keys.operation_rpc(
                            service_key, _identifier(operation.name)
                        )
        report = super().evaluate(api)
        if self._native or not api.agents:
            return report
        return LossinessReport(
            items=[*report.items, *agent_loss_items(api, target_label=self.target_label)]
        )

    def _service_key(self, service: Service) -> str:
        """The key a re-import gives the program ``service`` is written as."""
        return Keys.type(_identifier(service.name), self._namespace)

    def root_verdicts(self, api: CanonicalApi) -> List[FidelityVerdict]:
        """The paradigm change and the envelope an RPCL file cannot hold."""
        verdicts = list(super().root_verdicts(api))
        if self._native:
            return verdicts
        paradigm = paradigm_change_verdict(api, ApiParadigm.RPC, target_label=self.target_label)
        if paradigm is not None:
            verdicts.append(paradigm)
        envelope = envelope_verdicts(
            api, target_label=self.target_label, keeps_title=False, keeps_id=False,
            keeps_namespace=api.identity.namespace == self._namespace, keeps_version=False,
        )
        if not envelope and (api.identity.name, api.identity.namespace) != (self._namespace, self._namespace):
            envelope = [FidelityVerdict.approx(
                message=f"an {self.target_label} file has no name of its own: the document reads back "
                f"named {self._namespace!r}, after its first program",
                severity=LossinessSeverity.INFO,
                target_mapping=f"document name → {self._namespace}",
            )]
        return verdicts + envelope

    def operation_verdicts(self, operation: Operation) -> List[FidelityVerdict]:
        """The operation's own verdict, plus the re-key ``DROP`` of a procedure of a built program."""
        verdicts = super().operation_verdicts(operation)
        if self._native:
            return verdicts
        rekey = self._rekey(operation.key, self._operation_keys.get(operation.key), "operation")
        if rekey is None or any(v.kind is not LossinessKind.OK for v in verdicts):
            # A verdict that already says the operation is reframed as a procedure covers its key.
            return verdicts
        self._rekeyed.add(operation.key)
        return [rekey[0]]

    def service_verdicts(self, service: Service) -> List[FidelityVerdict]:
        """The re-key ``DROP`` of a service written as a program."""
        verdicts = list(super().service_verdicts(service))
        rekey = None if self._native else self._rekey(service.key, self._service_key(service), "service")
        if rekey is not None:
            verdicts.append(rekey[0])
        return verdicts

    def type_verdicts(self, type_: Type) -> List[FidelityVerdict]:
        """The re-key ``DROP`` of a written type; a ``DROP`` for a kind RPCL does not declare."""
        verdicts = super().type_verdicts(type_)
        if self._native:
            return verdicts
        if type_.kind not in _WRITTEN_KINDS:
            return [FidelityVerdict.drop(
                message=f"{self.target_label} declares enums, structs and unions; the "
                f"{type_.kind.value} type {type_.key!r} is not written",
                severity=LossinessSeverity.WARN,
                target_mapping=f"{type_.kind.value} type → dropped",
            )]
        rekey = self._rekey(type_.key, Keys.type(_identifier(type_.name), self._namespace), "type")
        if rekey is None:
            return verdicts
        return [v for v in verdicts if v.kind is not LossinessKind.OK] + [rekey[0]]

    def synthesized_verdicts(self, api: CanonicalApi) -> List[Tuple[str, FidelityVerdict]]:
        """The keys re-keyed types, services and procedures read back under."""
        pairs = list(super().synthesized_verdicts(api))
        if self._native:
            return pairs
        candidates = [
            *(
                (t.key, Keys.type(_identifier(t.name), self._namespace), "type")
                for t in api.types if t.kind in _WRITTEN_KINDS
            ),
            *((s.key, self._service_key(s), "service") for s in api.services),
            *(
                (o.key, self._operation_keys.get(o.key), "operation")
                for o in api.operations() if o.key in self._rekeyed
            ),
        ]
        seen = set()
        for key, emitted, noun in candidates:
            rekey = self._rekey(key, emitted, noun)
            if rekey is not None and rekey[1][0] not in seen:
                seen.add(rekey[1][0])
                pairs.append(rekey[1])
        return pairs

    def _rekey(
        self, key: str, emitted: Optional[str], noun: str
    ) -> Optional[Tuple[FidelityVerdict, Tuple[str, FidelityVerdict]]]:
        """The re-key verdicts of ``key``, or ``None`` when it is not written or keeps its key."""
        if emitted is None:
            return None
        return rekey_verdicts(
            key, emitted, target_label=self.target_label, noun=noun,
            reason=f"files every declaration under its first program, {self._namespace!r}",
        )

    def operation_verdict(self, operation) -> FidelityVerdict:
        if operation.kind in _EVENT_OPERATION_KINDS:
            return FidelityVerdict.drop(
                message=f"{self.target_label} has no event vocabulary; "
                f"{operation.kind.value} operation {operation.key!r} is dropped",
                target_mapping="event operation → dropped",
            )
        if operation.http_method or operation.http_path:
            return FidelityVerdict.approx(
                message=f"{self.target_label} has no HTTP binding; reframing "
                f"{operation.key!r} as an RPC procedure",
                target_mapping="HTTP operation → RPC procedure",
            )
        return super().operation_verdict(operation)


class OncRpcEmitOptions(EmitOptions):
    """Per-target options for :class:`OncRpcEmitter`."""

    include_comments: bool = Field(
        default=True,
        description="Emit brief generated-file header comments.",
    )


class OncRpcEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as an ONC RPC / XDR ``.x`` document."""

    key = "oncrpc"
    format = "oncrpc"
    label = "ONC RPC"
    description = "Export as an ONC RPC / XDR rpcgen definition (.x)."
    icon = "network"
    paradigm = ApiParadigm.RPC
    multi_file = False
    options_model = OncRpcEmitOptions

    OUTPUT_MEDIA_TYPE = "text/plain"

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
        return OncRpcFidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[OncRpcEmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        options = (
            opts
            if isinstance(opts, OncRpcEmitOptions)
            else OncRpcEmitOptions.model_validate(opts.model_dump() if opts else {})
        )
        writer = _OncRpcWriter(api, options)
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


class _OncRpcWriter:
    def __init__(self, api: CanonicalApi, options: OncRpcEmitOptions) -> None:
        self._api = api
        self._options = options
        self.tracker = ProvenanceTracker()
        self.losses = LossTracker()
        self._types_by_key = {type_.key: type_ for type_ in api.types}
        self._typedefs = api.extras.get("oncrpc_typedefs") or {}
        self._programs = api.extras.get("oncrpc_programs") or []
        self.output_path = _output_path(api)

    def render(self) -> str:
        lines: List[str] = []
        if self._options.include_comments:
            title = self._api.identity.name or "Exported API"
            lines.append(f"/* Generated ONC RPC / XDR RPCL for {title} */")
            lines.append("")

        for type_ in sorted(self._api.types, key=lambda item: item.name):
            if type_.kind is TypeKind.ENUM or type_.extras.get("oncrpc_kind") == "enum":
                lines.extend(self._render_enum(type_))
                lines.append("")

        if isinstance(self._typedefs, dict):
            for name, type_expr in sorted(self._typedefs.items()):
                rendered = self._render_typedef(name, str(type_expr))
                if rendered:
                    lines.append(rendered)
            if self._typedefs:
                lines.append("")

        for type_ in sorted(self._api.types, key=lambda item: item.name):
            oncrpc_kind = type_.extras.get("oncrpc_kind")
            if type_.kind is TypeKind.UNION or oncrpc_kind == "union":
                lines.extend(self._render_union(type_))
                lines.append("")
            elif type_.kind is TypeKind.RECORD and oncrpc_kind in (None, "struct"):
                # A record from another format carries no `oncrpc_kind`; it is a struct all the
                # same, and leaving it out left the procedures naming undeclared types (COA-3.1).
                lines.extend(self._render_struct(type_))
                lines.append("")

        if isinstance(self._programs, list) and self._programs:
            for program in self._programs:
                lines.extend(self._render_program(program))
                lines.append("")
        elif self._api.services:
            for service in self._api.services:
                lines.extend(self._render_program_from_service(service))

        if self._api.channels:
            self.losses.record(
                LossKind.NA,
                "channels-dropped",
                "ONC RPC export has no event channel representation",
            )

        return "\n".join(lines).rstrip() + "\n"

    def _render_enum(self, type_: Type) -> List[str]:
        values = ", ".join(
            f"{_identifier(value.name)} = {value.value}" if value.value is not None
            else _identifier(value.name)
            for value in type_.enum_values
        )
        self.tracker.record(type_.key, Provenance.SOURCE)
        return [f"enum {_identifier(type_.name)} {{ {values} }};"]

    def _render_typedef(self, name: str, type_expr: str) -> str:
        match = re.fullmatch(r"(\w+)<(\d+)>", type_expr)
        if match:
            return f"typedef {match.group(1)} {name}<{match.group(2)}>;"
        return f"typedef {type_expr} {name};"

    def _render_struct(self, type_: Type) -> List[str]:
        lines = [f"struct {_identifier(type_.name)} {{"]
        for field in sorted(type_.fields, key=lambda item: item.field_number or 0):
            lines.append(f"    {self._render_field(field)};")
        lines.append("};")
        self.tracker.record(type_.key, Provenance.SOURCE)
        return lines

    def _render_union(self, type_: Type) -> List[str]:
        switch_type = type_.extras.get("oncrpc_switch_type", "int")
        switch_field = type_.extras.get("oncrpc_switch_field", "status")
        lines = [f"union {_identifier(type_.name)} switch ({switch_type} {switch_field}) {{"]
        cases = type_.extras.get("oncrpc_union_cases")
        if isinstance(cases, list) and cases:
            for index, case in enumerate(cases):
                if not isinstance(case, dict):
                    continue
                label = case.get("label", "default")
                prefix = "default" if label == "default" else f"case {label}"
                case_type = case.get("type", "void")
                field_name = case.get("field")
                if case_type == "void" or not field_name:
                    lines.append(f"{prefix}:")
                    lines.append("    void;")
                else:
                    lines.append(f"{prefix}:")
                    lines.append(f"    {case_type} {field_name};")
        else:
            for member_key in type_.union_members:
                mapped = _CANONICAL_TO_XDR.get(member_key, member_key.split(".")[-1])
                lines.append(f"    {mapped} branch;")
        lines.append("};")
        self.tracker.record(type_.key, Provenance.SOURCE)
        return lines

    def _render_field(self, field: CanonicalField) -> str:
        type_expr = field.extras.get("oncrpc_type_expr")
        if isinstance(type_expr, str) and type_expr:
            bound_match = re.fullmatch(r"(opaque|string)<(\d+)>", type_expr)
            if bound_match:
                rendered = f"{bound_match.group(1)} {field.name}<{bound_match.group(2)}>"
            else:
                rendered = f"{type_expr} {field.name}"
        else:
            rendered = f"{self._render_type_ref(field.type)} {_identifier(field.name)}"
        self.tracker.record(field.key, Provenance.SOURCE)
        return rendered

    def _render_type_expr(self, type_expr: str) -> str:
        match = re.fullmatch(r"(\w+)<(\d+)>", type_expr)
        if match and match.group(1) in {"string", "opaque"}:
            return f"{match.group(1)} {match.group(2)}"
        if match:
            return f"{match.group(1)}<{match.group(2)}>"
        return type_expr

    def _render_type_ref(self, ref: TypeRef) -> str:
        if ref.name:
            mapped = _CANONICAL_TO_XDR.get(ref.name)
            if mapped:
                return mapped
            target = self._types_by_key.get(ref.name)
            if target is not None:
                return _identifier(target.name)
            return _identifier(ref.name.split(".")[-1])
        return "string"

    def _render_program(self, program: Dict[str, Any]) -> List[str]:
        name = str(program.get("name", "PROGRAM"))
        number = program.get("number", 1)
        lines = [f"program {name} {{"]
        for version in program.get("versions", []):
            if not isinstance(version, dict):
                continue
            version_name = str(version.get("name", "VERS"))
            version_number = version.get("number", 1)
            lines.append(f"    version {version_name} {{")
            for procedure in version.get("procedures", []):
                if not isinstance(procedure, dict):
                    continue
                lines.append(
                    "        "
                    f"{procedure.get('return_type', 'void')} "
                    f"{procedure.get('name', 'PROC')}({procedure.get('arg_type', 'void')}) "
                    f"= {procedure.get('number', 1)};"
                )
            lines.append(f"    }} = {version_number};")
        if isinstance(number, int):
            suffix = hex(number) if number > 255 else str(number)
        else:
            suffix = str(number)
        lines.append(f"}} = {suffix};")
        self.tracker.record(str(program.get("name", "PROGRAM")), Provenance.SOURCE)
        return lines

    def _render_program_from_service(self, service: Service) -> List[str]:
        lines = [f"program {_identifier(service.name)} {{", "    version VERS {"]
        # A procedure from another format has no number; number them in order, after any the
        # source assigned, so no two procedures of the version share one (COA-3.1, #7052).
        taken = {
            operation.extras.get("oncrpc_procedure_number") for operation in service.operations
        } - {None}
        next_number = 1
        for operation in service.operations:
            if operation.kind in _EVENT_OPERATION_KINDS:
                continue
            response = next((m for m in operation.messages if m.role is MessageRole.RESPONSE), None)
            request = next((m for m in operation.messages if m.role is MessageRole.REQUEST), None)
            return_type = (
                self._render_type_ref(response.payload)
                if response and response.payload
                else "void"
            )
            arg_type = (
                self._render_type_ref(request.payload)
                if request and request.payload
                else "void"
            )
            proc_num = operation.extras.get("oncrpc_procedure_number")
            if proc_num is None:
                while next_number in taken:
                    next_number += 1
                proc_num = next_number
                taken.add(proc_num)
            lines.append(
                f"        {return_type} {_identifier(operation.name)}({arg_type}) = {proc_num};"
            )
        lines.extend(["    } = 1;", "} = 1;"])
        return lines


def _output_path(api: CanonicalApi) -> str:
    programs = api.extras.get("oncrpc_programs")
    if isinstance(programs, list) and programs and isinstance(programs[0], dict):
        base = str(programs[0].get("name", "program"))
    elif api.services:
        base = api.services[0].name
    else:
        base = api.identity.name or "program"
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", base).strip("_") or "program"
    return f"{safe}.x"


def validate_oncrpc_document(content: str) -> None:
    """Validate ONC RPC / XDR RPCL text by re-parsing it."""
    parse_oncrpc(content)
