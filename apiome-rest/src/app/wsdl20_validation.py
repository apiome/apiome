"""WSDL 2.0 structure check for an emitted bundle — MFX-14.5 (#4182).

The ``wsdl.structure`` check of :func:`app.wsdl_bundle_validation.validate_wsdl_bundle` for a WSDL 2.0
description. ``xmlschema`` reads WSDL 1.1 only, so a 2.0 description is checked in three steps:

1. it validates against the W3C WSDL 2.0 schema (``app/data/wsdl20.xsd``, the 2007 Recommendation's
   schema with its DTD line removed so nothing is fetched);
2. every schema it uses builds — an ``xs:import`` in ``types`` (read from the bundle) and every inline
   ``xs:schema`` — so an unknown type, a broken facet or a dangling ``ref`` fails here;
3. every reference resolves: an operation's ``input`` / ``output`` and an interface ``fault`` name a
   global element of those schemas (or one of the ``#any`` / ``#none`` / ``#other`` tokens); an
   ``outfault`` / ``infault`` names a fault of its interface; a binding, service and endpoint name an
   interface or binding the description declares; a binding ``operation`` names an operation of its
   interface.
"""

from __future__ import annotations

import io
import posixpath
import tempfile
import xml.etree.ElementTree as ET
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Set, Tuple

import xmlschema

from .wsdl_versions import WSDL_2_0_NAMESPACE
from .xml_import_graph import resolve_bundle_path

__all__ = ["wsdl20_schema", "wsdl20_structure_problems"]

_XSD_NS = "http://www.w3.org/2001/XMLSchema"
_W = f"{{{WSDL_2_0_NAMESPACE}}}"

#: Message content tokens WSDL 2.0 allows in place of an element QName (Part 1, §2.5.2).
_ELEMENT_TOKENS = frozenset({"#any", "#none", "#other", "#element"})


@lru_cache(maxsize=1)
def wsdl20_schema() -> xmlschema.XMLSchema10:
    """The W3C WSDL 2.0 schema, as shipped in ``app/data``."""
    path = resources.files("app").joinpath("data/wsdl20.xsd")
    with resources.as_file(path) as local:
        return xmlschema.XMLSchema10(str(local), allow="local")


def wsdl20_structure_problems(root_path: str, root: ET.Element, files: Mapping[str, str]) -> List[Tuple[str, str]]:
    """Every structural problem of a WSDL 2.0 bundle (see the module docstring).

    Args:
        root_path: The bundle path of the description.
        root: The description, parsed by :func:`app.secure_xml.parse_xml`.
        files: Every member's text keyed by its bundle path (already safe, well-formed and packaged).

    Returns:
        ``(message, file)`` per problem, in check order; empty when the description is valid. Later
        steps are skipped when the schema validation fails.
    """
    text = files[root_path]
    errors = list(wsdl20_schema().iter_errors(xmlschema.XMLResource(text, defuse="always", allow="none")))
    if errors:
        return [(f"Not valid against the WSDL 2.0 schema: {error.reason or error.message}", root_path)
                for error in errors]
    namespaces = _namespaces(text)
    problems: List[Tuple[str, str]] = []
    elements = _schema_elements(root_path, root, text, files, problems)
    if elements is None:
        return problems
    problems.extend((message, root_path) for message in _reference_problems(root, namespaces, elements))
    return problems


def _namespaces(text: str) -> Dict[str, str]:
    """Every ``prefix → namespace`` the document declares (the first declaration of a prefix wins)."""
    namespaces: Dict[str, str] = {}
    for _event, (prefix, uri) in ET.iterparse(io.StringIO(text), events=("start-ns",)):
        namespaces.setdefault(prefix, uri)
    return namespaces


def _schema_elements(
    root_path: str, root: ET.Element, text: str, files: Mapping[str, str], problems: List[Tuple[str, str]]
) -> Optional[Set[str]]:
    """Build every schema ``types`` uses; the global elements they declare (``{ns}name``).

    Args:
        root_path: The description's bundle path.
        root: The parsed description.
        text: Its text (inline schemas need the namespace declarations the tree drops).
        files: Every bundle member.
        problems: Receives ``(message, file)`` per schema that does not build.

    Returns:
        The element names, or ``None`` when a schema does not build.
    """
    types = root.find(f"{_W}types")
    if types is None:
        return set()
    elements: Set[str] = set()
    with tempfile.TemporaryDirectory(prefix="wsdl20-bundle-") as folder:
        for path, member in files.items():
            target = Path(folder, path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(member, encoding="utf-8")
        # (schema file to build, bundle member reported when it fails)
        locations: List[Tuple[Path, str]] = []
        for imported in types.findall(f"{{{_XSD_NS}}}import"):
            # The packaging check already proved every schemaLocation names a member.
            path = resolve_bundle_path(posixpath.dirname(root_path), imported.get("schemaLocation") or "")
            if path in files:
                locations.append((Path(folder, path), path))
        for index, schema_el in enumerate(types.findall(f"{{{_XSD_NS}}}schema")):
            location = Path(folder, f"inline-schema-{index}.xsd")
            location.write_text(_inline_schema_text(schema_el, text), encoding="utf-8")
            locations.append((location, root_path))
        for location, label in locations:
            try:
                schema = xmlschema.XMLSchema10(str(location), allow="sandbox")
            except Exception as exc:  # noqa: BLE001 — any processor failure means "not a valid schema"
                problems.append((f"A schema of the description does not build: {_first_line(exc, folder)}", label))
                continue
            elements.update(schema.maps.elements)
    return None if problems else elements


def _inline_schema_text(schema: ET.Element, text: str) -> str:
    """An inline ``xs:schema`` of ``types`` as a document, with every namespace of the description declared.

    Args:
        schema: The inline schema element.
        text: The description's text (its namespace declarations).

    Returns:
        The schema document's text.
    """
    namespaces = _namespaces(text)
    for prefix, uri in namespaces.items():
        ET.register_namespace(prefix, uri)
    body = ET.tostring(schema, encoding="unicode")
    # QName values (`type="tns:Pet"`) need their prefixes declared on the schema itself.
    declared = " ".join(f'xmlns:{p}="{u}"' for p, u in namespaces.items() if p and f'xmlns:{p}="' not in body)
    return body.replace(">", f" {declared}>", 1) if declared else body


def _first_line(exc: Exception, folder: str) -> str:
    """The processor's error as one line, without the temporary folder."""
    message = str(getattr(exc, "message", "") or "") or str(exc).strip().splitlines()[0]
    return message.replace(Path(folder).as_uri() + "/", "").replace(folder + "/", "")


def _reference_problems(root: ET.Element, namespaces: Mapping[str, str], elements: Set[str]) -> List[str]:
    """Every element, interface, fault, binding and operation reference that does not resolve.

    Args:
        root: The parsed description.
        namespaces: Its prefix declarations.
        elements: The global elements of its schemas (``{ns}name``).

    Returns:
        One message per dangling reference.
    """
    target = root.get("targetNamespace") or ""

    def qualified(qname: Optional[str]) -> Optional[str]:
        prefix, _, local = (qname or "").rpartition(":")
        if prefix not in namespaces:
            return None
        return f"{{{namespaces[prefix]}}}{local}"

    problems: List[str] = []
    interfaces: Dict[str, ET.Element] = {
        f"{{{target}}}{el.get('name')}": el for el in root.findall(f"{_W}interface")
    }
    bindings = {f"{{{target}}}{el.get('name')}" for el in root.findall(f"{_W}binding")}

    def check_element(owner: str, qname: Optional[str]) -> None:
        if qname is None or qname in _ELEMENT_TOKENS:
            return
        if qualified(qname) not in elements:
            problems.append(f"{owner} names the element {qname!r}, which no schema of the description declares.")

    for interface in interfaces.values():
        name = interface.get("name")
        faults = {f"{{{target}}}{fault.get('name')}" for fault in interface.findall(f"{_W}fault")}
        for fault in interface.findall(f"{_W}fault"):
            check_element(f"Fault {fault.get('name')!r} of interface {name!r}", fault.get("element"))
        for operation in interface.findall(f"{_W}operation"):
            owner = f"Operation {operation.get('name')!r} of interface {name!r}"
            for direction in ("input", "output"):
                for message in operation.findall(f"{_W}{direction}"):
                    check_element(f"The {direction} of {owner[0].lower()}{owner[1:]}", message.get("element"))
            for direction in ("outfault", "infault"):
                for reference in operation.findall(f"{_W}{direction}"):
                    if qualified(reference.get("ref")) not in faults:
                        problems.append(f"{owner} has an {direction} {reference.get('ref')!r} that is not a fault "
                                        "of the interface.")
    for binding in root.findall(f"{_W}binding"):
        interface = interfaces.get(qualified(binding.get("interface")) or "") if binding.get("interface") else None
        if binding.get("interface") and interface is None:
            problems.append(f"Binding {binding.get('name')!r} names the interface {binding.get('interface')!r}, "
                            "which the description does not declare.")
            continue
        declared = interface.findall(f"{_W}operation") if interface is not None else []
        operations = {f"{{{target}}}{op.get('name')}" for op in declared}
        for operation in binding.findall(f"{_W}operation"):
            if qualified(operation.get("ref")) not in operations:
                problems.append(f"Binding {binding.get('name')!r} binds the operation {operation.get('ref')!r}, "
                                "which its interface does not declare.")
    for service in root.findall(f"{_W}service"):
        if qualified(service.get("interface")) not in interfaces:
            problems.append(f"Service {service.get('name')!r} names the interface {service.get('interface')!r}, "
                            "which the description does not declare.")
        for endpoint in service.findall(f"{_W}endpoint"):
            if qualified(endpoint.get("binding")) not in bindings:
                problems.append(f"Endpoint {endpoint.get('name')!r} of service {service.get('name')!r} names the "
                                f"binding {endpoint.get('binding')!r}, which the description does not declare.")
    return problems
