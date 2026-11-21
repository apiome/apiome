"""XML-RPC emitter: canonical model → XML-RPC ``methodCall`` XML.

The inverse of :class:`app.xmlrpc_normalizer.XmlRpcNormalizer` and an implementation
of the :class:`app.emitter.Emitter` SPI.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple, Union

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

__all__ = ["XmlRpcEmitOptions", "XmlRpcEmitter", "XmlRpcFidelityRulePack", "xmlrpc_method_name"]

_EVENT_OPERATION_KINDS = frozenset({OperationKind.PUBLISH, OperationKind.SUBSCRIBE})


class XmlRpcFidelityRulePack(CapabilityRulePack):
    """Fidelity rules for XML-RPC export.

    An XML-RPC document is one ``methodCall``: the first RPC operation of the source, by name, with
    its parameters. Everything else is left out, and the report says so (COA-3.1, #7052): every other
    operation and every named type is a ``DROP``, the written operation reads back under the key
    ``{method}.{method}`` in a service named after it (``DROP`` + ``SYNTH``), and the document has no
    title, description, identifier, namespace or version.
    """

    target_label = "XML-RPC"
    #: Whether the source is itself XML-RPC (:meth:`evaluate`); a pack asked before that adds nothing.
    _native = True

    def evaluate(self, api: CanonicalApi) -> LossinessReport:
        """Find the one operation the ``methodCall`` is written for, walk, then add agent losses."""
        self._native = api.format == XmlRpcEmitter.format
        primary = _primary_rpc_operation(api)
        self._primary_key = primary.key if primary is not None else None
        self._method = xmlrpc_method_name(primary.name) if primary is not None else None
        report = super().evaluate(api)
        if self._native or not api.agents:
            return report
        return LossinessReport(
            items=[*report.items, *agent_loss_items(api, target_label=self.target_label)]
        )

    def root_verdicts(self, api: CanonicalApi) -> List[FidelityVerdict]:
        """The paradigm change and the envelope a ``methodCall`` cannot hold."""
        verdicts = list(super().root_verdicts(api))
        if self._native:
            return verdicts
        paradigm = paradigm_change_verdict(api, ApiParadigm.RPC, target_label=self.target_label)
        if paradigm is not None:
            verdicts.append(paradigm)
        verdicts += envelope_verdicts(
            api, target_label=self.target_label, keeps_title=False, keeps_id=False,
            keeps_namespace=False, keeps_version=False,
        )
        return verdicts

    def operation_verdicts(self, operation: Operation) -> List[FidelityVerdict]:
        """The operation's verdict: only the first RPC operation is written, under its method name."""
        verdicts = [self.operation_verdict(operation)]
        if self._native or verdicts[0].kind is not LossinessKind.OK:
            return verdicts
        if operation.key != self._primary_key:
            return [FidelityVerdict.drop(
                message=f"an {self.target_label} document is one methodCall, written for operation "
                f"{self._primary_key!r}; operation {operation.key!r} is not written",
                severity=LossinessSeverity.WARN,
                target_mapping="operation → dropped (one methodCall per document)",
            )]
        rekey = self._method_rekey(operation)
        return [rekey[0]] if rekey else verdicts

    def service_verdicts(self, service: Service) -> List[FidelityVerdict]:
        """A ``methodCall`` names a method, not a service: the service is not written."""
        verdicts = list(super().service_verdicts(service))
        if not self._native and service.key != self._method:
            verdicts.append(FidelityVerdict.drop(
                message=f"{self.target_label} has no service construct; service {service.key!r} is "
                "not written",
                severity=LossinessSeverity.INFO,
                target_mapping="service → dropped",
            ))
        return verdicts

    def type_verdict(self, type_: Type) -> FidelityVerdict:
        """A ``methodCall`` carries parameter values, not type declarations."""
        if self._native:
            return super().type_verdict(type_)
        return FidelityVerdict.drop(
            message=f"{self.target_label} has no type declarations — a methodCall carries parameter "
            f"values; type {type_.key!r} is not written",
            severity=LossinessSeverity.WARN,
            target_mapping="type → dropped",
        )

    def field_verdicts(self, field: CanonicalField) -> List[FidelityVerdict]:
        """A dropped type's fields go with it (the type's ``DROP`` covers them)."""
        return super().field_verdicts(field) if self._native else []

    def synthesized_verdicts(self, api: CanonicalApi) -> List[Tuple[str, FidelityVerdict]]:
        """The key the written operation reads back under, and the service named after its method."""
        pairs = list(super().synthesized_verdicts(api))
        if self._native or self._method is None:
            return pairs
        primary = next(op for op in api.operations() if op.key == self._primary_key)
        rekey = self._method_rekey(primary)
        if rekey:
            pairs.append(rekey[1])
        if all(service.key != self._method for service in api.services):
            pairs.append((self._method, FidelityVerdict.synth(
                message=f"a reader files the methodCall under a service named after its method, "
                f"{self._method!r}",
                target_mapping="methodName → service",
            )))
        return pairs

    def _method_rekey(
        self, operation: Operation
    ) -> Optional[Tuple[FidelityVerdict, Tuple[str, FidelityVerdict]]]:
        """The re-key verdicts of the written operation (``{method}.{method}`` on re-import)."""
        method = xmlrpc_method_name(operation.name)
        return rekey_verdicts(
            operation.key, Keys.operation_rpc(method, method),
            target_label=self.target_label, noun="operation",
            reason="names a call by its method only",
        )

    def event_verdict(self, event) -> FidelityVerdict:
        return FidelityVerdict.drop(
            message=f"{self.target_label} has no event/channel representation; event {event.key!r} is dropped",
            target_mapping="event → dropped",
        )

    def operation_verdict(self, operation: Operation) -> FidelityVerdict:
        if operation.kind in _EVENT_OPERATION_KINDS:
            return FidelityVerdict.drop(
                message=f"{self.target_label} has no event vocabulary; "
                f"{operation.kind.value} operation {operation.key!r} is dropped",
                target_mapping="event operation → dropped",
            )
        if operation.http_method or operation.http_path:
            return FidelityVerdict.drop(
                message=f"{self.target_label} has no HTTP binding; operation {operation.key!r} is dropped",
                target_mapping="HTTP operation → dropped",
            )
        return FidelityVerdict.ok(message=f"operation carried to {self.target_label}")


class XmlRpcEmitOptions(EmitOptions):
    """Per-target options for :class:`XmlRpcEmitter`."""

    include_xml_declaration: bool = Field(
        default=True,
        description="Emit the XML 1.0 declaration prolog.",
    )


#: Runs of characters the XML-RPC specification does not allow in a ``methodName``.
_ILLEGAL_METHOD_CHARS = re.compile(r"[^A-Za-z0-9_.:/]+")


def xmlrpc_method_name(name: Optional[str]) -> str:
    """The ``methodName`` XML-RPC can carry for an operation name (COA-3.4, #7055).

    The specification allows only ``A-Z a-z 0-9 _ . : /`` in a method name. An operation named in
    another format (an agent skill ``Build itinerary``, an Agent Card URL) has other characters, and
    writing it as-is fails the export's validator. Each run of illegal characters becomes one
    ``_``; a legal name is returned unchanged, so a native XML-RPC source round-trips byte for byte.
    The rename is reported by the rule pack's re-key verdict, since the call reads back under it.

    Args:
        name: The operation's name.

    Returns:
        A legal, non-empty method name (``method`` when nothing legal is left).
    """
    return _ILLEGAL_METHOD_CHARS.sub("_", name or "").strip("_") or "method"


def _primary_rpc_operation(api: CanonicalApi) -> Optional[Operation]:
    """The first RPC operation of ``api``: not an event, and with no HTTP method or path.

    Args:
        api: The source canonical model.

    Returns:
        The operation the ``methodCall`` is written for, or ``None`` when the source has none.
    """
    for service in api.services:
        for operation in service.operations:
            if operation.kind in _EVENT_OPERATION_KINDS:
                continue
            if operation.http_method or operation.http_path:
                continue
            return operation
    return None


class XmlRpcEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as an XML-RPC ``methodCall`` document."""

    @classmethod
    def source_unsupported_reason(cls, api: CanonicalApi) -> Optional[str]:
        """XML-RPC writes one RPC call, so a source with no RPC operation cannot be exported.

        Args:
            api: The source canonical model.

        Returns:
            The reason, or ``None`` when the source has an RPC operation (RC6-H4, #6211).
        """
        if _primary_rpc_operation(api) is None:
            return (
                "XML-RPC export needs an RPC operation (one with no HTTP method or path); "
                "this source has none."
            )
        return None

    key = "xmlrpc"
    format = "xmlrpc"
    label = "XML-RPC"
    description = "Export as an XML-RPC methodCall message."
    icon = "file-code"
    paradigm = ApiParadigm.RPC
    multi_file = False
    options_model = XmlRpcEmitOptions

    OUTPUT_MEDIA_TYPE = "application/xml"

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        return CapabilityProfile(
            operations=True,
            events=False,
            unions=False,
            nullability=True,
            field_identity=True,
        )

    @classmethod
    def fidelity_rule_pack(cls) -> type[CapabilityRulePack]:
        return XmlRpcFidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[XmlRpcEmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        options = (
            opts
            if isinstance(opts, XmlRpcEmitOptions)
            else XmlRpcEmitOptions.model_validate(opts.model_dump() if opts else {})
        )
        writer = _XmlRpcWriter(api, options)
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


class _XmlRpcWriter:
    def __init__(self, api: CanonicalApi, options: XmlRpcEmitOptions) -> None:
        self._api = api
        self._options = options
        self.tracker = ProvenanceTracker()
        self.losses = LossTracker()
        self._types_by_key = {type_.key: type_ for type_ in api.types}
        self.output_path = _output_path(api)

    def render(self) -> str:
        operation = self._primary_operation()
        if operation is None:
            raise ValueError("XML-RPC export requires at least one RPC operation")

        root = ET.Element("methodCall")
        method_el = ET.SubElement(root, "methodName")
        method_el.text = xmlrpc_method_name(operation.name)

        request = next((m for m in operation.messages if m.role is MessageRole.REQUEST), None)
        params = request.extras.get("xmlrpc_params") if request is not None else None
        if isinstance(params, list) and params:
            params_el = ET.SubElement(root, "params")
            for entry in sorted(params, key=lambda item: int(item.get("index", 0))):
                if not isinstance(entry, dict):
                    continue
                param_el = ET.SubElement(params_el, "param")
                sample = entry.get("sample")
                schema = entry.get("schema") if isinstance(entry.get("schema"), dict) else {}
                param_el.append(self._value_from_schema(schema, sample))

        if self._api.channels:
            self.losses.record(
                LossKind.NA,
                "channels-dropped",
                "XML-RPC export omits event/channel constructs",
                pointer="channels",
            )

        xml = ET.tostring(root, encoding="unicode")
        if self._options.include_xml_declaration:
            return '<?xml version="1.0"?>\n' + xml + "\n"
        return xml + "\n"

    def _primary_operation(self) -> Optional[Operation]:
        return _primary_rpc_operation(self._api)

    def _value_from_schema(self, schema: Dict[str, Any], sample: Any) -> ET.Element:
        value_el = ET.Element("value")
        if sample is not None:
            value_el.append(self._value_from_sample(sample))
            return value_el

        ref = schema.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            type_name = ref.rsplit("/", 1)[-1]
            target = next((t for t in self._api.types if t.name == type_name), None)
            if target is not None:
                value_el.append(self._struct_from_type(target))
                return value_el

        schema_type = schema.get("type")
        if schema_type == "array":
            array_el = ET.SubElement(value_el, "array")
            data_el = ET.SubElement(array_el, "data")
            items = schema.get("items")
            if isinstance(items, dict):
                data_el.append(self._value_from_schema(items, None))
            return value_el
        if schema_type == "integer":
            ET.SubElement(value_el, "int").text = "0"
            return value_el
        if schema_type == "number":
            ET.SubElement(value_el, "double").text = "0"
            return value_el
        if schema_type == "boolean":
            ET.SubElement(value_el, "boolean").text = "0"
            return value_el
        if schema_type == "null":
            ET.SubElement(value_el, "nil")
            return value_el
        ET.SubElement(value_el, "string").text = ""
        return value_el

    def _value_from_sample(self, sample: Any) -> ET.Element:
        if isinstance(sample, dict):
            struct_el = ET.Element("struct")
            for name, value in sample.items():
                member_el = ET.SubElement(struct_el, "member")
                ET.SubElement(member_el, "name").text = str(name)
                value_el = ET.SubElement(member_el, "value")
                value_el.append(self._value_from_sample(value))
            return struct_el
        if isinstance(sample, list):
            array_el = ET.Element("array")
            data_el = ET.SubElement(array_el, "data")
            for item in sample:
                value_el = ET.SubElement(data_el, "value")
                value_el.append(self._value_from_sample(item))
            return array_el
        if isinstance(sample, bool):
            boolean_el = ET.Element("boolean")
            boolean_el.text = "1" if sample else "0"
            return boolean_el
        if isinstance(sample, int):
            int_el = ET.Element("int")
            int_el.text = str(sample)
            return int_el
        if isinstance(sample, float):
            double_el = ET.Element("double")
            double_el.text = str(sample)
            return double_el
        if sample is None:
            return ET.Element("nil")
        string_el = ET.Element("string")
        string_el.text = str(sample)
        return string_el

    def _struct_from_type(self, type_: Type) -> ET.Element:
        struct_el = ET.Element("struct")
        for field in type_.fields:
            member_el = ET.SubElement(struct_el, "member")
            ET.SubElement(member_el, "name").text = field.name
            value_el = ET.SubElement(member_el, "value")
            sample = None
            if isinstance(type_.extras.get("xmlrpc_samples"), dict):
                sample = type_.extras["xmlrpc_samples"].get(field.name)
            if sample is not None:
                value_el.append(self._value_from_sample(sample))
            else:
                value_el.append(self._value_from_type_ref(field.type))
            self.tracker.record(field.key, Provenance.SOURCE)
        self.tracker.record(type_.key, Provenance.SOURCE)
        return struct_el

    def _value_from_type_ref(self, ref: Optional[TypeRef]) -> ET.Element:
        if ref is None or not ref.name:
            return self._value_from_sample("")
        if ref.is_list():
            array_el = ET.Element("array")
            data_el = ET.SubElement(array_el, "data")
            if ref.item is not None:
                value_el = ET.SubElement(data_el, "value")
                value_el.append(self._value_from_type_ref(ref.item))
            return array_el
        target = self._types_by_key.get(ref.name)
        if target is not None and target.kind is TypeKind.RECORD:
            return self._struct_from_type(target)
        mapping = {
            "integer": ("int", "0"),
            "int32": ("int", "0"),
            "int64": ("int", "0"),
            "double": ("double", "0"),
            "float": ("double", "0"),
            "bool": ("boolean", "0"),
            "boolean": ("boolean", "0"),
            "null": ("nil", None),
        }
        tag, text = mapping.get(ref.name, ("string", ""))
        element = ET.Element(tag)
        if text is not None:
            element.text = text
        return element


def _output_path(api: CanonicalApi) -> str:
    base = api.identity.name or "method"
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", base).strip("_") or "method"
    return f"{safe}.xmlrpc.xml"
