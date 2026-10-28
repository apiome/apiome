"""WADL emitter: canonical model → WADL XML + XSD grammars — MFX-20.1, MFX-29.1 (#4173).

The inverse of :class:`app.wadl_normalizer.WadlNormalizer` and an implementation of the
:class:`app.emitter.Emitter` SPI. Writes the W3C WADL submission (``http://wadl.dev.java.net/2009/02``):

**Layout.** By default the export is ``<Name>.wadl`` plus ``<Name>.xsd``, the grammar, linked from
``<grammars><include href="<Name>.xsd"/>``. ``layout="single"`` inlines the schema in ``<grammars>``.
The grammar is written by the shared XSD writer (:mod:`app.xsd_schema`) — the same types WSDL
exports, with every complex type declared as a global element that representations reference.

**Resources.** Operations become a tree of ``resource`` elements by path segment (an operation on
``/`` gets ``<resource path="/">``). Each operation is a ``method`` with its HTTP verb; its ``id`` is
written when the source names the operation. Path parameters are ``template`` params on the resource
whose segment names them; query and header parameters are request params; the request body and every
response (with its status code) carry a ``representation`` referencing a grammar element.

**Not carried, and reported:** operations with no HTTP binding (WADL describes HTTP resources only),
event operations, cookie parameters, status ranges such as ``4XX``, servers beyond the first, and
anything the grammar cannot express (:mod:`app.xsd_schema`). Names that are not legal ``NCName`` s
are rewritten.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional, Tuple, Union

from pydantic import Field

from .canonical_model import (
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Parameter,
    ParameterLocation,
    Type,
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
from .fidelity_rulepack import CapabilityRulePack, FidelityVerdict, rename_verdict
from .lossiness import LossinessKind, LossinessSeverity
from .xsd_schema import (
    TNS_PREFIX,
    XSD_NS,
    XSD_PREFIX,
    NameScope,
    XsdSchemaWriter,
    comment_safe,
    schema_field_verdicts,
    schema_type_verdict,
    target_namespace_verdicts,
)
from .xsd_types import ncname

__all__ = ["WadlEmitOptions", "WadlEmitter", "WadlFidelityRulePack"]

_WADL_NS = "http://wadl.dev.java.net/2009/02"
_WADL_PREFIX = "wadl"
_DEFAULT_MEDIA_TYPE = "application/xml"
_DEFAULT_BASE = "https://api.example.com/"
_DEFAULT_TARGET_NAMESPACE = "http://example.com/service"

#: The source format whose operation names and namespace the emitter writes back as they were read.
_WADL_FORMAT = "wadl"

_EVENT_OPERATION_KINDS = frozenset({OperationKind.PUBLISH, OperationKind.SUBSCRIBE})

#: Canonical parameter location → WADL ``param/@style``, and where the param is written.
_PARAM_STYLES = {
    ParameterLocation.PATH: "template",
    ParameterLocation.QUERY: "query",
    ParameterLocation.HEADER: "header",
}

_STATUS = re.compile(r"^[1-5][0-9]{2}$")


class WadlFidelityRulePack(CapabilityRulePack):
    """Fidelity rules for WADL export.

    On top of the capability rules: the target namespace (synthesized when the source has none) and
    the resources base URI (synthesized when the source has no server; only the first is kept);
    operations without an HTTP binding are dropped; renamed method ids; and what the XSD grammar
    changes or cannot carry (:func:`app.xsd_schema.schema_field_verdicts`).
    """

    target_label = "WADL"

    def root_verdicts(self, api: CanonicalApi) -> List[FidelityVerdict]:
        # The grammar's namespace qualifies the types; with no types and no bodies there is none.
        verdicts = (
            target_namespace_verdicts(
                api,
                target_label=self.target_label,
                namespace=_target_namespace(api),
                source_has_own=api.format == _WADL_FORMAT and bool(api.extras.get("wadl_target_namespace")),
            )
            if _has_grammar(api)
            else []
        )
        not_carried = _document_details_not_carried(api)
        if not_carried:
            verdicts.append(
                FidelityVerdict.approx(
                    message=f"WADL describes one application by its title only; {'; '.join(not_carried)}",
                    severity=LossinessSeverity.INFO,
                    target_mapping="document → application doc",
                )
            )
        if not api.servers:
            verdicts.append(
                FidelityVerdict.synth(
                    message=f"WADL resources need a base URI and the source has no server; {_DEFAULT_BASE!r} is used",
                    severity=LossinessSeverity.INFO,
                    target_mapping=f"resources@base → {_DEFAULT_BASE}",
                )
            )
        elif len(api.servers) > 1:
            verdicts.append(
                FidelityVerdict.approx(
                    message=f"WADL is written with one resources base; {api.servers[0].url!r} is used and "
                    f"{len(api.servers) - 1} other server(s) are dropped",
                    severity=LossinessSeverity.INFO,
                    target_mapping="servers → first resources@base",
                )
            )
        return verdicts

    def operation_verdict(self, operation: Operation) -> FidelityVerdict:
        verdict = super().operation_verdict(operation)
        if verdict.kind is not LossinessKind.OK:
            return verdict
        if not operation.http_method:
            return FidelityVerdict.drop(
                message="WADL describes HTTP resources only; the operation has no HTTP method and path and "
                "is dropped",
                target_mapping="non-HTTP operation → dropped",
            )
        if operation.extras:
            return FidelityVerdict.approx(
                message="WADL carries an operation's HTTP surface only; its source-specific details "
                f"({', '.join(sorted(operation.extras))}) are not written",
                severity=LossinessSeverity.INFO,
                target_mapping="operation details → dropped",
            )
        if _has_explicit_id(operation):
            return (
                rename_verdict(
                    operation.name, ncname(operation.name, fallback="method"),
                    target_label=self.target_label, noun="method id",
                )
                or verdict
            )
        return verdict

    def type_verdict(self, type_: Type) -> FidelityVerdict:
        verdict = super().type_verdict(type_)
        if verdict.kind is not LossinessKind.OK:
            return verdict
        return schema_type_verdict(type_, target_label=self.target_label) or verdict

    def field_verdicts(self, field: CanonicalField) -> List[FidelityVerdict]:
        return [*super().field_verdicts(field), *schema_field_verdicts(field, target_label=self.target_label)]


class WadlEmitOptions(EmitOptions):
    """Per-target options for :class:`WadlEmitter`."""

    include_comments: bool = Field(
        default=True,
        description="Emit an XML comment header in the generated WADL.",
    )
    media_type: str = Field(
        default=_DEFAULT_MEDIA_TYPE,
        description="Representation media type for a body whose message declares none.",
    )
    layout: Literal["bundle", "single"] = Field(
        default="bundle",
        description="`bundle` writes the WADL and its XSD grammar as two files linked by "
        "`<grammars><include>`; `single` inlines the schema in `<grammars>`.",
    )


class WadlEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as a WADL description with an XSD grammar."""

    key = "wadl"
    format = "wadl"
    label = "WADL"
    description = "Export as a WADL REST service description with an XSD grammar."
    icon = "file-code"
    paradigm = ApiParadigm.REST
    multi_file = True
    options_model = WadlEmitOptions

    OUTPUT_MEDIA_TYPE = "application/vnd.sun.wadl+xml"
    SCHEMA_MEDIA_TYPE = "application/xml"

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        return CapabilityProfile(
            operations=True,
            events=False,
            unions=True,
            nullability=True,
            constraints=True,
            field_identity=False,
        )

    @classmethod
    def fidelity_rule_pack(cls) -> type[CapabilityRulePack]:
        return WadlFidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[WadlEmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        options = (
            opts
            if isinstance(opts, WadlEmitOptions)
            else WadlEmitOptions.model_validate(opts.model_dump() if opts else {})
        )
        writer = _WadlWriter(api, options)
        wadl_text, schema_text = writer.render()
        files = [EmittedFile(path=writer.output_path, content=wadl_text, media_type=self.OUTPUT_MEDIA_TYPE)]
        if schema_text is not None:
            files.append(EmittedFile(path=writer.schema_path, content=schema_text, media_type=self.SCHEMA_MEDIA_TYPE))
        return EmitResult(
            files=files,
            media_type=self.OUTPUT_MEDIA_TYPE,
            provenance=writer.tracker.records(),
            losses=writer.losses.records(),
        )


@dataclass
class _PathNode:
    """One path segment of the resource tree, with the operations whose path ends there."""

    operations: List[Operation] = field(default_factory=list)
    children: Dict[str, "_PathNode"] = field(default_factory=dict)


class _WadlWriter:
    def __init__(self, api: CanonicalApi, options: WadlEmitOptions) -> None:
        self._api = api
        self._options = options
        self.tracker = ProvenanceTracker()
        self.losses = LossTracker()
        self.output_path = _output_path(api)
        self.schema_path = re.sub(r"\.wadl$", ".xsd", self.output_path)
        self._target_ns = _target_namespace(api)
        self._schema = XsdSchemaWriter(
            api, target_namespace=self._target_ns, target_label="WADL", losses=self.losses, tracker=self.tracker
        )
        self._method_ids = NameScope()
        #: ``id(message)`` → the grammar element its representation references.
        self._representation_elements: Dict[int, str] = {}

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render(self) -> Tuple[str, Optional[str]]:
        """Render the WADL, and the XSD grammar when the layout is ``bundle``.

        Returns:
            ``(wadl text, xsd text or None)``.
        """
        ET.register_namespace(_WADL_PREFIX, _WADL_NS)
        ET.register_namespace(XSD_PREFIX, XSD_NS)

        operations = self._operations()
        for detail in _document_details_not_carried(self._api):
            self.losses.record(LossKind.NA, "document-details-dropped", f"WADL: {detail}.", pointer="")
        schema_el = self._schema.new_schema()
        self._schema.append_types(schema_el)
        for operation in operations:
            self._plan_representations(schema_el, operation)

        bundle = self._options.layout == "bundle"
        root_attributes = {f"xmlns:{TNS_PREFIX}": self._target_ns}
        if bundle:
            # Param `type` values are `xsd:` QNames; with no inline schema nothing else declares it.
            root_attributes[f"xmlns:{XSD_PREFIX}"] = XSD_NS
        root = ET.Element(ET.QName(_WADL_NS, "application"), root_attributes)
        title = self._api.identity.name or self._api.title
        if title:
            ET.SubElement(root, ET.QName(_WADL_NS, "doc")).text = title
        # A model with no types and no bodies has no grammar: no `<grammars>` and no `.xsd` file.
        has_grammar = len(schema_el) > 0
        if has_grammar:
            grammars_el = ET.SubElement(root, ET.QName(_WADL_NS, "grammars"))
            if bundle:
                ET.SubElement(grammars_el, ET.QName(_WADL_NS, "include"), {"href": self.schema_path})
            else:
                grammars_el.append(schema_el)

        if operations:
            # `resources` must hold at least one `resource`; a model with no HTTP operations (an RPC
            # or types-only source) is a grammar alone.
            resources_el = ET.SubElement(root, ET.QName(_WADL_NS, "resources"), {"base": self._base_uri()})
            tree = _build_path_tree(operations)
            if tree.operations:
                resources_el.append(self._render_resource(tree, "/", ancestors=[]))
            for segment, child in sorted(tree.children.items()):
                resources_el.append(self._render_resource(child, segment, ancestors=[]))

        if self._api.channels:
            self.losses.record(
                LossKind.NA, "channels-dropped", "WADL export omits event/channel constructs", pointer="channels"
            )

        header = ""
        if self._options.include_comments:
            header = f"<!-- Generated WADL for {comment_safe(title or 'Exported API')} -->\n"
        wadl_text = f"{header}{ET.tostring(root, encoding='unicode')}\n"
        schema_text = None
        if bundle and has_grammar:
            schema_header = header.replace("Generated WADL", "Generated XSD grammar") if header else ""
            schema_text = f"{schema_header}{ET.tostring(schema_el, encoding='unicode')}\n"
        return wadl_text, schema_text

    def _operations(self) -> List[Operation]:
        """The operations WADL can carry; events and operations with no HTTP binding are reported."""
        kept: List[Operation] = []
        for service in self._api.services:
            for operation in service.operations:
                if operation.kind in _EVENT_OPERATION_KINDS:
                    self.losses.record(
                        LossKind.NA, "event-operation-dropped",
                        f"Operation {operation.key!r} is an event; WADL has no representation for it.",
                        pointer=operation.key,
                    )
                elif not operation.http_method:
                    self.losses.record(
                        LossKind.NA, "operation-without-http-binding",
                        f"Operation {operation.key!r} has no HTTP method and path; WADL describes HTTP "
                        "resources only, so it is not written.",
                        pointer=operation.key,
                    )
                else:
                    kept.append(operation)
        return kept

    def _base_uri(self) -> str:
        if not self._api.servers:
            self.losses.record(
                LossKind.INFERRED, "base-uri-synthesized",
                f"The source has no server; the resources base is {_DEFAULT_BASE!r}.", pointer="servers",
            )
            return _DEFAULT_BASE
        if len(self._api.servers) > 1:
            self.losses.record(
                LossKind.NA, "servers-dropped",
                f"WADL is written with one resources base ({self._api.servers[0].url!r}); "
                f"{len(self._api.servers) - 1} other server(s) are not written.",
                pointer="servers",
            )
        return self._api.servers[0].url

    # ------------------------------------------------------------------
    # Representations (grammar elements)
    # ------------------------------------------------------------------

    def _plan_representations(self, schema_el: ET.Element, operation: Operation) -> None:
        """Find (or declare) the grammar element each body of ``operation`` is represented by."""
        for message in operation.messages:
            if message.role is MessageRole.REQUEST or message.role in (MessageRole.RESPONSE, MessageRole.ERROR):
                element = self._representation_element(schema_el, operation, message)
                if element:
                    self._representation_elements[id(message)] = element

    def _representation_element(self, schema_el: ET.Element, operation: Operation, message: Message) -> Optional[str]:
        """The global element for ``message``'s body: its type's own element, else a wrapper."""
        if message.payload is None:
            if message.payload_schema:
                self.losses.record(
                    LossKind.INFERRED, "inline-payload",
                    f"The body of {message.key!r} is an inline schema; its representation names no element.",
                    pointer=message.key,
                )
            return None
        payload = message.payload
        if payload.item is None and payload.name in self._schema.type_elements:
            return self._schema.type_elements[payload.name]
        # A list, scalar or simple-typed body: a wrapper element declared for it.
        base = ncname(operation.name or operation.key, fallback="method")
        suffix = "Request" if message.role is MessageRole.REQUEST else f"Response{_status(message) or ''}"
        element = self._schema.element_scope.claim(f"{base}{suffix}")
        sequence = self._schema.wrapper(schema_el, element)
        self._schema.append_value(sequence, "item", payload, optional=False, pointer=message.key)
        self.losses.record(
            LossKind.INFERRED, "body-wrapped",
            f"The body of {message.key!r} is not a named record; it is wrapped in the element {element!r}.",
            pointer=message.key,
        )
        return element

    # ------------------------------------------------------------------
    # Resources and methods
    # ------------------------------------------------------------------

    def _render_resource(self, node: _PathNode, segment: str, *, ancestors: List[str]) -> ET.Element:
        """A ``resource`` for ``segment``, its template params, methods and child resources."""
        resource_el = ET.Element(ET.QName(_WADL_NS, "resource"), {"path": segment})
        path = [*ancestors, segment]
        seen: set = set()
        for operation in self._operations_below(node):
            for param in operation.parameters:
                if param.location is not ParameterLocation.PATH or param.name in seen:
                    continue
                token = f"{{{param.name}}}"
                # A template param belongs to the segment that names it; one no segment names stays
                # on its own operation's resource.
                orphan = operation in node.operations and not any(token in s for s in path)
                if token in segment or orphan:
                    seen.add(param.name)
                    self._append_param(resource_el, param, "template")
        for operation in node.operations:
            resource_el.append(self._render_method(operation))
        for child_segment, child in sorted(node.children.items()):
            resource_el.append(self._render_resource(child, child_segment, ancestors=path))
        return resource_el

    @staticmethod
    def _operations_below(node: _PathNode) -> List[Operation]:
        out = list(node.operations)
        for child in node.children.values():
            out.extend(_WadlWriter._operations_below(child))
        return out

    def _render_method(self, operation: Operation) -> ET.Element:
        attributes = {"name": operation.http_method.upper()}
        if _has_explicit_id(operation):
            method_id = self._method_ids.claim(ncname(operation.name, fallback="method"))
            attributes["id"] = self._schema.rename(operation.name, method_id, operation.key, "method id")
        method_el = ET.Element(ET.QName(_WADL_NS, "method"), attributes)
        if operation.description:
            ET.SubElement(method_el, ET.QName(_WADL_NS, "doc")).text = operation.description

        request = next((m for m in operation.messages if m.role is MessageRole.REQUEST), None)
        params = [p for p in operation.parameters if p.location is not ParameterLocation.PATH]
        if params or request is not None:
            request_el = ET.SubElement(method_el, ET.QName(_WADL_NS, "request"))
            for param in params:
                style = _PARAM_STYLES.get(param.location)
                if style is None:
                    self.losses.record(
                        LossKind.NA, "parameter-dropped",
                        f"WADL has no {param.location.value} parameters; {param.key!r} is not written.",
                        pointer=param.key,
                    )
                    continue
                self._append_param(request_el, param, style)
            if request is not None:
                self._append_representation(request_el, request)

        for message in operation.messages:
            if message.role not in (MessageRole.RESPONSE, MessageRole.ERROR):
                continue
            attributes = {}
            status = _status(message)
            if status:
                attributes["status"] = status
            elif message.status_code or message.extras.get("http_status"):
                self.losses.record(
                    LossKind.NA, "status-range-dropped",
                    f"WADL statuses are single codes; {message.status_code or message.extras.get('http_status')!r} "
                    f"of {message.key!r} is written without a status.",
                    pointer=message.key,
                )
            elif message.role is MessageRole.RESPONSE:
                attributes["status"] = "200"
            response_el = ET.SubElement(method_el, ET.QName(_WADL_NS, "response"), attributes)
            self._append_representation(response_el, message)

        if operation.extras:
            self.losses.record(
                LossKind.NA, "operation-details-dropped",
                f"WADL carries the HTTP surface only; {operation.key!r} loses its source-specific details "
                f"({', '.join(sorted(operation.extras))}).",
                pointer=operation.key,
            )
        self.tracker.record(operation.key, Provenance.SOURCE)
        return method_el

    def _append_param(self, parent: ET.Element, param: Parameter, style: str) -> None:
        """A ``param`` with its style, XSD type, requiredness, default and documentation."""
        fmt = param.constraints.format if param.constraints is not None else None
        hint = param.extras.get("wadl_type")
        builtin = self._schema.builtin(param.type, fmt) if param.type.item is None else None
        if hint:
            type_qname = self._schema.source_type_qname(param.type, hint=hint)
        elif builtin is not None:
            type_qname = f"{XSD_PREFIX}:{builtin}"
        else:
            type_qname = self._schema.type_qname(param.type.item or param.type, fmt, param.key)
        attributes = {
            "name": param.name,
            "style": style,
            "type": type_qname,
            # Explicit both ways: the WADL default is `false`, but readers differ.
            "required": "true" if param.required else "false",
        }
        if param.type.item is not None:
            attributes["repeating"] = "true"
        if param.default is not None and not isinstance(param.default, (dict, list)):
            default = param.default
            attributes["default"] = str(default).lower() if isinstance(default, bool) else str(default)
        param_el = ET.SubElement(parent, ET.QName(_WADL_NS, "param"), attributes)
        if param.description:
            ET.SubElement(param_el, ET.QName(_WADL_NS, "doc")).text = param.description
        self.tracker.record(param.key, Provenance.SOURCE)

    def _append_representation(self, parent: ET.Element, message: Message) -> None:
        """A ``representation`` with the message's media type and its grammar element."""
        element = self._representation_elements.get(id(message))
        if element is None and message.payload is None and not message.payload_schema:
            return
        attributes = {"mediaType": (message.content_types or [self._options.media_type])[0]}
        if element:
            attributes["element"] = f"{TNS_PREFIX}:{element}"
        ET.SubElement(parent, ET.QName(_WADL_NS, "representation"), attributes)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _has_explicit_id(operation: Operation) -> bool:
    """Whether the source named the operation (an unnamed WADL method is ``"<VERB> <path>"``)."""
    synthesized = f"{(operation.http_method or '').upper()} {operation.http_path or ''}"
    return bool(operation.name) and operation.name != synthesized and operation.name != operation.key


def _document_details_not_carried(api: CanonicalApi) -> List[str]:
    """What of the document WADL has no place for: services, version, description, format details.

    A WADL source has none of these beyond what WADL itself writes back, so it gets an empty list.
    """
    if api.format == _WADL_FORMAT:
        return []
    details: List[str] = []
    if api.services:
        names = ", ".join(repr(service.name) for service in api.services[:3])
        more = f" and {len(api.services) - 3} more" if len(api.services) > 3 else ""
        details.append(f"the operations of service(s) {names}{more} become resources of one application")
    if api.version:
        details.append(f"the version {api.version!r} is not written")
    if api.description:
        details.append("the document description is not written")
    if api.extras:
        details.append(f"source-specific details ({', '.join(sorted(api.extras))}) are not written")
    return details


def _has_grammar(api: CanonicalApi) -> bool:
    """Whether an export of ``api`` writes a grammar (any type, or any message body)."""
    return bool(api.types) or any(m.payload is not None for op in api.operations() for m in op.messages)


def _status(message: Message) -> Optional[str]:
    """The message's HTTP status when it is a single code (``404``), else ``None`` (``4XX``)."""
    raw = str(message.status_code or message.extras.get("http_status") or "")
    return raw if _STATUS.match(raw) else None


def _build_path_tree(operations: List[Operation]) -> _PathNode:
    root = _PathNode()
    for operation in operations:
        segments = [segment for segment in (operation.http_path or "/").strip("/").split("/") if segment]
        node = root
        for segment in segments:
            node = node.children.setdefault(segment, _PathNode())
        node.operations.append(operation)
    return root


def _target_namespace(api: CanonicalApi) -> str:
    """The grammar's ``targetNamespace``: a WADL source's own, the source namespace, or the default."""
    return str(api.extras.get("wadl_target_namespace") or api.identity.namespace or _DEFAULT_TARGET_NAMESPACE)


def _output_path(api: CanonicalApi) -> str:
    base = api.identity.name or "api"
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", base).strip("_") or "api"
    return f"{safe}.wadl"
