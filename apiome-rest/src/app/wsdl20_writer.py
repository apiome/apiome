"""WSDL 2.0 writer: canonical model → W3C WSDL 2.0 ``description`` + XSD — MFX-14.5 (#4182).

The ``wsdl_version="2.0"`` mode of :class:`app.wsdl_emitter.WsdlEmitter`. It reuses everything the 1.1
writer plans — names, the shared XSD writer (:mod:`app.xsd_schema`), the document/literal wrapper elements
and a WSDL source's messages — and only writes the description in the 2.0 grammar
(https://www.w3.org/TR/wsdl20/):

* ``description`` (no ``name``) with ``types``: an ``xs:import`` of the ``.xsd`` (bundle) or the schema
  inline (single);
* one ``interface`` per service. Each operation names its payload elements directly (2.0 has no
  ``message`` element) and states its message-exchange pattern (:mod:`app.wsdl_versions`): ``in-out``,
  ``in-only`` / ``robust-in-only`` for a one-way operation, ``out-only`` / ``robust-out-only`` for a
  WSDL source's notification. Faults are interface ``fault`` s, referenced by ``outfault`` (``infault``
  for an out-bound pattern);
* one ``binding`` per binding: SOAP (``wsoap:version`` 1.1 or 1.2, ``wsoap:protocol``, ``wsoap:action``)
  or HTTP (``whttp:methodDefault="POST"``);
* one ``service`` per interface with its ``endpoint`` s.

**What 2.0 cannot say** (recorded as losses, reported by :class:`app.wsdl_emitter.WsdlFidelityRulePack`):

* ``message-parts-wrapped`` — a 1.1 message with several parts becomes one wrapper element named after
  the message, its parts the children;
* ``scalar-payload-as-element`` — a payload that is a built-in type (a 1.1 ``type`` part, or an element
  of a built-in type, which the model keeps only as the type) gets an element of that type, named after
  the message (``<op>Input``) or the fault;
* ``rpc-style-as-document`` — 2.0 has no SOAP ``rpc`` binding style: the operation is document/literal;
* ``service-split`` — a 2.0 service exposes one interface, so a 1.1 service whose ports expose different
  port types is written as one service per interface;
* ``description-name-dropped`` — a 2.0 ``description`` has no ``name``: the API's name is not written,
  and a re-import names the API after its first service;
* ``empty-interface-synthesized`` — a model with no services (types only) gets one empty ``interface``
  named after the API, because a WSDL 2.0 importer reads a description with no interface as describing
  nothing; a re-import reads it as a service with no operations.

A WSDL 1.1 binding's SOAP-over-HTTP ``transport`` is written as the 2.0 ``wsoap:protocol`` of its SOAP
version (:func:`soap_protocol`), and a 1.1 operation with only an input is ``in-only``: the same
meaning in 2.0's spelling, so neither is reported.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Tuple

from .canonical_model import CanonicalApi, Message, MessageRole, Operation, OperationKind, Server, Service
from .emitter import LossKind, Provenance
from .wsdl_emitter import _TNS_PREFIX, _XSD_NS, _XSD_PREFIX, WsdlEmitOptions, _WsdlWriter
from .wsdl_versions import (
    MEP_IN_ONLY,
    MEP_IN_OUT,
    MEP_OUT_ONLY,
    MEP_ROBUST_IN_ONLY,
    MEP_ROBUST_OUT_ONLY,
    VERSION_2_0,
    WSDL_2_0_NAMESPACE,
)
from .xsd_schema import NameScope, comment_safe
from .xsd_types import ncname, xsd_builtin

__all__ = ["Wsdl20Writer", "soap_protocol"]

_WSDL_PREFIX = "wsdl"
_WSOAP_NS = "http://www.w3.org/ns/wsdl/soap"
_WSOAP_PREFIX = "wsoap"
_WHTTP_NS = "http://www.w3.org/ns/wsdl/http"
_WHTTP_PREFIX = "whttp"

#: The SOAP 1.1 HTTP binding protocol of the W3C note "SOAP 1.1 Binding for WSDL 2.0".
SOAP11_HTTP_PROTOCOL = "http://www.w3.org/2006/01/soap11/bindings/HTTP/"
#: The SOAP 1.2 HTTP binding protocol (SOAP 1.2 Part 2, §7).
SOAP12_HTTP_PROTOCOL = "http://www.w3.org/2003/05/soap/bindings/HTTP/"
#: The WSDL 1.1 SOAP-over-HTTP ``transport`` URI, which 2.0 spells as a protocol per SOAP version.
_WSDL11_HTTP_TRANSPORT = "http://schemas.xmlsoap.org/soap/http"


def soap_protocol(version: str, transport: Optional[str]) -> str:
    """The ``wsoap:protocol`` of a SOAP binding.

    Args:
        version: ``"1.1"`` or ``"1.2"``.
        transport: The source binding's transport URI (a 1.1 ``soap:binding/@transport`` or a 2.0
            ``wsoap:protocol``), or ``None``.

    Returns:
        A 2.0 source's protocol and any non-HTTP transport (JMS …) as they are; the 1.1 HTTP transport,
        or none, as the HTTP protocol of ``version``.
    """
    if transport and transport.rstrip("/") != _WSDL11_HTTP_TRANSPORT:
        return transport
    return SOAP11_HTTP_PROTOCOL if version == "1.1" else SOAP12_HTTP_PROTOCOL


def _pattern(*, has_input: bool, has_output: bool, has_faults: bool) -> str:
    """The message-exchange pattern of an operation with these messages.

    Args:
        has_input: The operation receives a message.
        has_output: The operation sends a message.
        has_faults: The operation has faults.

    Returns:
        ``in-out`` when it has both; ``in-only`` / ``robust-in-only`` with only an input; ``out-only`` /
        ``robust-out-only`` with only an output (a WSDL source's notification).
    """
    if has_input and has_output:
        return MEP_IN_OUT
    if has_output:
        return MEP_ROBUST_OUT_ONLY if has_faults else MEP_OUT_ONLY
    return MEP_ROBUST_IN_ONLY if has_faults else MEP_IN_ONLY


def _fault_reference(pattern: str) -> Tuple[str, str]:
    """How an operation of ``pattern`` refers to its faults (WSDL 2.0 Part 2, §2.2).

    Args:
        pattern: The operation's message-exchange pattern.

    Returns:
        ``(element, messageLabel)``: in ``in-out`` a fault replaces the reply (``outfault``, ``Out``); in
        ``robust-in-only`` it answers the input (``outfault``, ``In``); in ``robust-out-only`` the client
        answers the output with it (``infault``, ``Out``).
    """
    if pattern == MEP_ROBUST_OUT_ONLY:
        return "infault", "Out"
    if pattern == MEP_ROBUST_IN_ONLY:
        return "outfault", "In"
    return "outfault", "Out"


class Wsdl20Writer(_WsdlWriter):
    """Write the model as a WSDL 2.0 description (see the module docstring)."""

    def __init__(self, api: CanonicalApi, options: WsdlEmitOptions) -> None:
        super().__init__(api, options)
        #: ``(message or fault name, payload type)`` → the element a WSDL source's message is written as.
        self._message_elements: Dict[Tuple[str, Optional[str]], Optional[str]] = {}

    def render(self) -> Tuple[str, Optional[str]]:
        """Render the WSDL 2.0 description, and the XSD when the layout is ``bundle``.

        Returns:
            ``(wsdl text, xsd text or None)``.
        """
        ET.register_namespace(_WSDL_PREFIX, WSDL_2_0_NAMESPACE)
        ET.register_namespace(_XSD_PREFIX, _XSD_NS)
        ET.register_namespace(_WSOAP_PREFIX, _WSOAP_NS)
        ET.register_namespace(_WHTTP_PREFIX, _WHTTP_NS)

        schema_el = self._build_schema()
        root = ET.Element(
            ET.QName(WSDL_2_0_NAMESPACE, "description"),
            {
                "targetNamespace": self._target_ns,
                # `tns:` appears only in attribute values, which ElementTree never declares.
                f"xmlns:{_TNS_PREFIX}": self._target_ns,
            },
        )
        types_el = ET.SubElement(root, ET.QName(WSDL_2_0_NAMESPACE, "types"))
        bundle = self._options.layout == "bundle"
        if bundle:
            # WSDL 2.0 §3.1.1: an `xs:import` directly in `types` makes the schema's components referenceable.
            ET.SubElement(
                types_el,
                ET.QName(_XSD_NS, "import"),
                {"namespace": self._target_ns, "schemaLocation": self.schema_path},
            )
        else:
            types_el.append(schema_el)

        for service in self._api.services:
            self._append_interface(root, schema_el, service)
        if not self._api.services:
            name = ncname(self._api.identity.name or "Service", pascal=True, fallback="Service")
            ET.SubElement(root, ET.QName(WSDL_2_0_NAMESPACE, "interface"), {"name": name})
            self.losses.record(
                LossKind.INFERRED,
                "empty-interface-synthesized",
                f"The model has no operations; WSDL 2.0 is written with one empty interface {name!r}, which a "
                "re-import reads as a service with no operations.",
            )

        topology = [server for server in self._api.servers if server.extras.get("wsdl_binding")]
        if topology:
            self._append_topology_20(root, topology)
        else:
            self._append_default_endpoints(root)

        if self._api.channels:
            self.losses.record(
                LossKind.NA,
                "channels-dropped",
                "WSDL export omits event/channel constructs",
                pointer="channels",
            )
        # A 2.0 source's name already came from its first service: a re-import reads it back the same.
        if self._api.identity.name and self._api.extras.get("wsdl_version") != VERSION_2_0:
            self.losses.record(
                LossKind.INFERRED,
                "description-name-dropped",
                f"A WSDL 2.0 description has no name; the API name {self._api.identity.name!r} is not written, "
                "and a re-import names the API after its first service.",
            )

        header = ""
        if self._options.include_comments:
            title = self._api.identity.name or "Exported service"
            header = f"<!-- Generated WSDL 2.0 for {comment_safe(title)} -->\n"
        wsdl_text = f"{header}{ET.tostring(root, encoding='unicode')}\n"
        schema_text = None
        if bundle:
            schema_header = header.replace("Generated WSDL 2.0", "Generated XSD types") if header else ""
            schema_text = f"{schema_header}{ET.tostring(schema_el, encoding='unicode')}\n"
        return wsdl_text, schema_text

    # ------------------------------------------------------------------
    # Interfaces
    # ------------------------------------------------------------------

    def _append_interface(self, root: ET.Element, schema_el: ET.Element, service: Service) -> None:
        """Write ``service`` as an ``interface``: its faults, then one ``operation`` per operation.

        Args:
            root: The ``description``.
            schema_el: The schema, which may receive elements a WSDL source's messages need.
            service: The service.
        """
        interface_el = ET.SubElement(
            root, ET.QName(WSDL_2_0_NAMESPACE, "interface"), {"name": self._service_names[service.key]}
        )
        self.tracker.record(service.key, Provenance.SOURCE)
        #: ``(fault label, element)`` → its interface fault name: operations sharing a fault share one.
        faults: Dict[Tuple[str, Optional[str]], str] = {}
        fault_scope = NameScope()
        operation_els: List[ET.Element] = []
        for operation in self._operations(service):
            input_element, output_element, operation_faults = self._signature(schema_el, operation)
            names = []
            for label, element in operation_faults:
                if (label, element) not in faults:
                    faults[(label, element)] = fault_scope.claim(label)
                    attributes = {"name": faults[(label, element)]}
                    if element:
                        attributes["element"] = f"{_TNS_PREFIX}:{element}"
                    ET.SubElement(interface_el, ET.QName(WSDL_2_0_NAMESPACE, "fault"), attributes)
                names.append(faults[(label, element)])
            pattern = _pattern(
                has_input=input_element is not None,
                has_output=output_element is not None,
                has_faults=bool(names),
            )
            op_el = ET.Element(
                ET.QName(WSDL_2_0_NAMESPACE, "operation"),
                {"name": self._operation_names[operation.key], "pattern": pattern},
            )
            for direction, label, element in (("input", "In", input_element), ("output", "Out", output_element)):
                if element is not None:
                    ET.SubElement(
                        op_el,
                        ET.QName(WSDL_2_0_NAMESPACE, direction),
                        {"messageLabel": label, "element": f"{_TNS_PREFIX}:{element}"},
                    )
            fault_direction, fault_label = _fault_reference(pattern)
            for name in names:
                ET.SubElement(
                    op_el,
                    ET.QName(WSDL_2_0_NAMESPACE, fault_direction),
                    {"ref": f"{_TNS_PREFIX}:{name}", "messageLabel": fault_label},
                )
            if operation.extras.get("wsdl_soap_style") == "rpc":
                self.losses.record(
                    LossKind.INFERRED,
                    "rpc-style-as-document",
                    f"WSDL 2.0 has no SOAP rpc binding style; operation {self._operation_names[operation.key]!r} "
                    "is written document/literal.",
                    pointer=operation.key,
                )
            operation_els.append(op_el)
            self.tracker.record(
                operation.key,
                Provenance.SOURCE if self._wsdl_source else Provenance.INFERRED,
                None if self._wsdl_source else "document/literal wrapped operation",
            )
        # Interface faults first, then operations: the order the 2.0 examples use.
        interface_el.extend(operation_els)

    def _signature(
        self, schema_el: ET.Element, operation: Operation
    ) -> Tuple[Optional[str], Optional[str], List[Tuple[str, Optional[str]]]]:
        """The elements an operation's input and output carry, and its faults.

        Args:
            schema_el: The schema (receives the elements a WSDL source's messages need).
            operation: The operation.

        Returns:
            ``(input element or None, output element or None, [(fault label, element or None)])``.
        """
        if not self._wsdl_source:
            plan = self._wrapped[operation.key]
            responds = operation.kind is not OperationKind.ONE_WAY or any(
                message.role is MessageRole.RESPONSE and message.payload is not None for message in operation.messages
            )
            return (
                plan.request_element,
                plan.response_element if responds else None,
                [(fault, element) for fault, element in plan.faults],
            )
        input_element: Optional[str] = None
        output_element: Optional[str] = None
        faults: List[Tuple[str, Optional[str]]] = []
        for message, name in self._operation_messages(operation):
            if message.role is MessageRole.ERROR:
                # A fault is named once per interface: operations sharing it share its element too.
                label = ncname(message.name or "fault", fallback="fault")
                faults.append((label, self._message_element_20(schema_el, label, message)))
                continue
            element = self._message_element_20(schema_el, name, message)
            if message.role is MessageRole.REQUEST:
                input_element = element
            else:
                output_element = element
        return input_element, output_element, faults

    def _message_element_20(self, schema_el: ET.Element, name: str, message: Message) -> Optional[str]:
        """The element a WSDL source's message is written as (2.0 names elements, not messages).

        A one-part message that names an element is that element. A multi-part message becomes one
        wrapper element named after it, its parts the children (``message-parts-wrapped``); a payload of
        a built-in type gets an element of that type named ``name`` (``scalar-payload-as-element``). Each
        ``(name, payload)`` is written once.

        Args:
            schema_el: The schema the synthesized elements are added to.
            name: The 1.1 ``message`` name (:meth:`_operation_messages`), or a fault's name.
            message: The canonical message.

        Returns:
            The element's local name, or ``None`` for a message with no payload.
        """
        cache_key = (name, message.payload.name if message.payload else None)
        if cache_key in self._message_elements:
            return self._message_elements[cache_key]
        element: Optional[str] = None
        message_type = self._message_types.get(message.payload.name or "") if message.payload else None
        if message_type is not None:
            element = self._schema.element_scope.claim(ncname(name, fallback="message"))
            sequence = self._schema.wrapper(schema_el, element)
            for field in sorted(message_type.fields, key=lambda f: f.field_number or 0):
                if field.extras.get("wsdl_part_element"):
                    ET.SubElement(
                        sequence,
                        ET.QName(_XSD_NS, "element"),
                        {"ref": f"{_TNS_PREFIX}:{field.extras['wsdl_part_element']}"},
                    )
                else:
                    ET.SubElement(
                        sequence,
                        ET.QName(_XSD_NS, "element"),
                        {
                            "name": ncname(field.name, fallback="part"),
                            "type": self._schema.source_type_qname(field.type, hint=field.extras.get("xsd_type")),
                        },
                    )
            self.losses.record(
                LossKind.INFERRED,
                "message-parts-wrapped",
                f"WSDL 2.0 has no message element; the {len(message_type.fields)} parts of message {name!r} "
                f"are written as the children of one element {element!r}.",
                pointer=message_type.key,
            )
        elif message.payload is not None and message.payload.name and message.payload.name not in self._types_by_key:
            mapped = xsd_builtin(message.payload.name)
            if mapped:
                element = self._schema.element_scope.claim(ncname(name, fallback="message"))
                ET.SubElement(
                    schema_el, ET.QName(_XSD_NS, "element"), {"name": element, "type": f"{_XSD_PREFIX}:{mapped}"}
                )
                self.losses.record(
                    LossKind.INFERRED,
                    "scalar-payload-as-element",
                    f"WSDL 2.0 messages name an element; the xsd:{mapped} payload of {name!r} is written as the "
                    f"element {element!r}.",
                    pointer=message.key,
                )
        if element is None and message.payload is not None:
            element = self._payload_type_name(message.payload)
        self._message_elements[cache_key] = element
        return element

    # ------------------------------------------------------------------
    # Bindings and services
    # ------------------------------------------------------------------

    def _append_binding_20(
        self,
        root: ET.Element,
        name: str,
        *,
        service: Optional[Service],
        protocol: Optional[str],
        transport: Optional[str],
    ) -> None:
        """Write one ``binding`` of ``service``'s interface over ``protocol`` (``soap11`` / ``soap12`` / ``http``).

        Args:
            root: The ``description``.
            name: The binding name.
            service: The service whose interface is bound, or ``None`` when the source's is unknown.
            protocol: ``soap11``, ``soap12`` or ``http`` (``None`` is SOAP 1.1).
            transport: The source binding's transport URI, or ``None``.
        """
        attributes = {"name": name}
        if service is not None:
            attributes["interface"] = f"{_TNS_PREFIX}:{self._service_names[service.key]}"
        if protocol == "http":
            attributes["type"] = _WHTTP_NS
            attributes[ET.QName(_WHTTP_NS, "methodDefault")] = "POST"
        else:
            version = "1.2" if protocol == "soap12" else "1.1"
            attributes["type"] = _WSOAP_NS
            attributes[ET.QName(_WSOAP_NS, "version")] = version
            attributes[ET.QName(_WSOAP_NS, "protocol")] = soap_protocol(version, transport)
        binding_el = ET.SubElement(root, ET.QName(WSDL_2_0_NAMESPACE, "binding"), attributes)
        if service is None:
            return
        for operation in self._operations(service):
            op_name = self._operation_names[operation.key]
            bind_op = {"ref": f"{_TNS_PREFIX}:{op_name}"}
            if protocol == "http":
                bind_op[ET.QName(_WHTTP_NS, "location")] = op_name
            elif operation.extras.get("wsdl_soap_action"):
                bind_op[ET.QName(_WSOAP_NS, "action")] = str(operation.extras["wsdl_soap_action"])
            ET.SubElement(binding_el, ET.QName(WSDL_2_0_NAMESPACE, "operation"), bind_op)

    def _append_default_endpoints(self, root: ET.Element) -> None:
        """For a source with no WSDL topology: one SOAP 1.1 binding and one service per interface."""
        for service in self._api.services:
            interface = self._service_names[service.key]
            binding_name = f"{interface}Binding"
            self._append_binding_20(root, binding_name, service=service, protocol="soap11", transport=None)
            service_el = ET.SubElement(
                root,
                ET.QName(WSDL_2_0_NAMESPACE, "service"),
                {"name": f"{interface}Service", "interface": f"{_TNS_PREFIX}:{interface}"},
            )
            server_url = self._api.servers[0].url if self._api.servers else "https://api.example.com/service"
            ET.SubElement(
                service_el,
                ET.QName(WSDL_2_0_NAMESPACE, "endpoint"),
                {"name": interface, "binding": f"{_TNS_PREFIX}:{binding_name}", "address": server_url},
            )

    def _append_topology_20(self, root: ET.Element, servers: List[Server]) -> None:
        """Write the bindings, services and endpoints a WSDL source's servers record (MFI-13.2).

        A 2.0 service exposes one interface. A 1.1 service whose ports bind different port types is
        written as one service per interface, the later ones named ``<service><interface>``
        (``service-split``).

        Args:
            root: The ``description``.
            servers: The servers that record a WSDL binding.
        """
        services_by_interface = {self._service_names[s.key]: s for s in self._api.services}
        fallback_interface = next(iter(services_by_interface), None)
        bindings_written: set = set()
        for server in servers:
            binding = str(server.extras["wsdl_binding"])
            if binding in bindings_written:
                continue
            bindings_written.add(binding)
            self._append_binding_20(
                root,
                binding,
                service=services_by_interface.get(str(server.extras.get("wsdl_port_type") or "")),
                protocol=server.protocol,
                transport=server.extras.get("wsdl_transport"),
            )
        services: Dict[Tuple[str, Optional[str]], ET.Element] = {}
        names = NameScope()
        for server in servers:
            source_name = str(server.extras.get("wsdl_service") or "Service")
            port_type = str(server.extras.get("wsdl_port_type") or "")
            interface = port_type if port_type in services_by_interface else fallback_interface
            key = (source_name, interface)
            if key not in services:
                split = any(existing == source_name for existing, _ in services)
                name = names.claim(f"{source_name}{interface or ''}" if split else source_name)
                if split:
                    self.losses.record(
                        LossKind.INFERRED,
                        "service-split",
                        f"A WSDL 2.0 service exposes one interface; the ports of service {source_name!r} that "
                        f"bind {interface!r} are written as the service {name!r}.",
                        pointer=f"service:{source_name}",
                    )
                attributes = {"name": name}
                if interface:
                    attributes["interface"] = f"{_TNS_PREFIX}:{interface}"
                services[key] = ET.SubElement(root, ET.QName(WSDL_2_0_NAMESPACE, "service"), attributes)
            ET.SubElement(
                services[key],
                ET.QName(WSDL_2_0_NAMESPACE, "endpoint"),
                {
                    "name": ncname(server.name or source_name, fallback="Endpoint"),
                    "binding": f"{_TNS_PREFIX}:{server.extras['wsdl_binding']}",
                    "address": server.url,
                },
            )
