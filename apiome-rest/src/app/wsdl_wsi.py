"""WS-I Basic Profile checks for WSDL — MFI-13.4 (#3791).

The WS-I Basic Profile (BP 1.1 / 1.2 for SOAP 1.1, BP 2.0 for SOAP 1.2;
https://www.ws-i.org/Profiles/BasicProfile-1.2-2010-11-09.html) is the interoperability contract
SOAP toolkits agree on. Its assertions are about bindings and imports — the parts of a WSDL the
canonical model does not keep — so this module reads the document's XML (and the fileset or
live-fetch members it imports) directly and records what it finds for the ``wsi`` lint pack
(:mod:`app.wsdl_lint`). Each issue names its rule:

* ``wsi.literal-use`` (R2706) — a ``soap:body`` / ``header`` / ``fault`` / ``headerfault`` with
  ``use="encoded"``; only literal is interoperable.
* ``wsi.binding-style`` (R2705) — one binding mixes ``rpc`` and ``document`` operations.
* ``wsi.document-literal`` (R2201, R2204, R2716) — a document-literal body that references more
  than one part, a part defined by ``type`` rather than ``element``, or carries ``namespace``.
* ``wsi.rpc-literal`` (R2203, R2717) — an rpc-literal body that references a part defined by
  ``element``, or has no ``namespace``.
* ``wsi.unique-operation-signature`` (R2710) — two operations of a binding that a receiver cannot
  tell apart on the wire: the same SOAP body child (and the same ``soapAction``).
* ``wsi.unique-soap-action`` — two operations of a binding share a non-empty ``soapAction``, so a
  service that dispatches on it cannot route them (BP does not require it; most stacks rely on it).
* ``wsi.unresolved-import`` (R2001-R2003 intent) — a ``wsdl:import``, ``xs:import`` or ``xs:include``
  that resolves to nothing in the import: its location is not part of the uploaded set or the live
  fetch, it cannot be read, or (``xs:import`` without ``schemaLocation``) no schema declares its
  namespace.
* ``wsi.wsdl-import-target`` (R2007, R2001, R2002) — a ``wsdl:import`` with no ``location``, or one
  that names something other than a WSDL description (schemas are imported with ``xs:import``).

Binding rules apply to WSDL 1.1 (WSDL 2.0 has no ``soap:body``); import rules to both grammars.
Issue paths read ``/binding/<name>/operation/<operation>``, ``/import/<location>`` and
``/schema/<targetNamespace>/import/<location>``.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Set, Tuple

from .secure_xml import SecureXmlError, parse_xml
from .wsdl_parser import _attr_local, _children, _find_descendants, _local, _namespace, _resolve_member
from .wsdl_versions import VERSION_2_0

__all__ = [
    "MAX_REPORTED_ISSUES",
    "RULE_BINDING_STYLE",
    "RULE_DOCUMENT_LITERAL",
    "RULE_LITERAL_USE",
    "RULE_RPC_LITERAL",
    "RULE_UNIQUE_OPERATION_SIGNATURE",
    "RULE_UNIQUE_SOAP_ACTION",
    "RULE_UNRESOLVED_IMPORT",
    "RULE_WSDL_IMPORT_TARGET",
    "WsiIssue",
    "check_wsi",
]

RULE_LITERAL_USE = "wsi.literal-use"
RULE_BINDING_STYLE = "wsi.binding-style"
RULE_DOCUMENT_LITERAL = "wsi.document-literal"
RULE_RPC_LITERAL = "wsi.rpc-literal"
RULE_UNIQUE_OPERATION_SIGNATURE = "wsi.unique-operation-signature"
RULE_UNIQUE_SOAP_ACTION = "wsi.unique-soap-action"
RULE_UNRESOLVED_IMPORT = "wsi.unresolved-import"
RULE_WSDL_IMPORT_TARGET = "wsi.wsdl-import-target"

#: Most issues recorded for one document (the rest are counted, not listed).
MAX_REPORTED_ISSUES = 50

#: SOAP 1.1 and SOAP 1.2 WSDL binding extension namespaces.
_SOAP_BINDING_NAMESPACES = frozenset(
    {"http://schemas.xmlsoap.org/wsdl/soap/", "http://schemas.xmlsoap.org/wsdl/soap12/"}
)

#: Namespaces an ``xs:import`` may name without a ``schemaLocation``: every processor knows them.
_WELL_KNOWN_NAMESPACES = frozenset(
    {
        "http://www.w3.org/2001/XMLSchema",
        "http://www.w3.org/XML/1998/namespace",
        "http://schemas.xmlsoap.org/soap/encoding/",
        "http://schemas.xmlsoap.org/wsdl/",
        "http://www.w3.org/2003/05/soap-encoding",
    }
)


@dataclass(frozen=True)
class WsiIssue:
    """One WS-I Basic Profile problem.

    Attributes:
        rule: The ``wsi.*`` lint rule that reports it.
        path: Where it is (``/binding/OrdersSoap/operation/GetOrder``).
        message: What is wrong, naming the profile assertion.
    """

    rule: str
    path: str
    message: str

    def as_dict(self) -> Dict[str, str]:
        """The issue as ``{"rule", "path", "message"}``."""
        return {"rule": self.rule, "path": self.path, "message": self.message}


def _soap(element: ET.Element, local_name: str) -> List[ET.Element]:
    """The SOAP (1.1 or 1.2) binding extension children of ``element`` named ``local_name``."""
    return [
        child
        for child in element
        if _local(child.tag) == local_name and _namespace(child.tag) in _SOAP_BINDING_NAMESPACES
    ]


def _read_member(location: str, members: Optional[Mapping[str, str]]) -> Tuple[Optional[ET.Element], str]:
    """Resolve and parse an import target.

    Returns:
        ``(root, "")`` when it resolved, else ``(None, reason)``.
    """
    text = _resolve_member(location, members) if members else None
    if text is None:
        return None, "it is not part of the import (upload it with the description, or import the service URL)"
    try:
        return parse_xml(text, source_label=location), ""
    except SecureXmlError as exc:
        return None, f"it cannot be read ({exc})"


class _Checker:
    """Collects the :class:`WsiIssue` list for one description."""

    def __init__(self, root: ET.Element, members: Optional[Mapping[str, str]], version: str) -> None:
        self.root = root
        self.members = members
        self.version = version
        self.issues: List[WsiIssue] = []
        self.definitions: List[ET.Element] = [root]

    def _add(self, rule: str, path: str, message: str) -> None:
        self.issues.append(WsiIssue(rule, path, message))

    # -- imports ------------------------------------------------------------------------------

    def wsdl_imports(self) -> None:
        """Check every ``wsdl:import`` (and 2.0 ``include``), following resolved ones."""
        expected_root = "description" if self.version == VERSION_2_0 else "definitions"
        seen: Set[str] = set()
        queue = [self.root]
        while queue:
            current = queue.pop(0)
            for ref in _children(current, "import") + _children(current, "include"):
                if _namespace(ref.tag) != _namespace(self.root.tag):
                    continue
                location = (ref.get("location") or "").strip()
                if not location:
                    if self.version != VERSION_2_0:
                        self._add(
                            RULE_WSDL_IMPORT_TARGET,
                            "/import",
                            "a `wsdl:import` has no `location` (WS-I R2007: it must name the description it imports).",
                        )
                    continue
                if location in seen:
                    continue
                seen.add(location)
                path = f"/import/{location}"
                member, reason = _read_member(location, self.members)
                if member is None:
                    self._add(
                        RULE_UNRESOLVED_IMPORT, path, f"`wsdl:import` of `{location}` does not resolve: {reason}."
                    )
                    continue
                if _local(member.tag) != expected_root:
                    self._add(
                        RULE_WSDL_IMPORT_TARGET,
                        path,
                        f"`wsdl:import` of `{location}` names a `{_local(member.tag)}`, not a WSDL description; "
                        f"import schemas with `xs:import` inside `types` (WS-I R2001, R2002).",
                    )
                    continue
                self.definitions.append(member)
                queue.append(member)

    def schema_imports(self) -> None:
        """Check every ``xs:import`` / ``xs:include`` reachable from the description's ``types``."""
        schemas = [
            schema
            for definition in self.definitions
            for types in _children(definition, "types")
            for schema in _find_descendants(types, "schema")
        ]
        declared = {schema.get("targetNamespace") or "" for schema in schemas}
        seen: Set[str] = set()
        queue = list(schemas)
        pending_namespaces: List[Tuple[str, str]] = []
        while queue:
            schema = queue.pop(0)
            schema_ns = schema.get("targetNamespace") or "(no namespace)"
            for ref in _children(schema, "import") + _children(schema, "include"):
                kind = f"xs:{_local(ref.tag)}"
                location = (ref.get("schemaLocation") or "").strip()
                if not location:
                    if kind == "xs:import":
                        pending_namespaces.append((schema_ns, (ref.get("namespace") or "").strip()))
                    continue
                if location in seen:
                    continue
                seen.add(location)
                member, reason = _read_member(location, self.members)
                if member is None:
                    self._add(
                        RULE_UNRESOLVED_IMPORT,
                        f"/schema/{schema_ns}/import/{location}",
                        f"`{kind}` of `{location}` does not resolve: {reason}.",
                    )
                    continue
                member_schemas = [member] if _local(member.tag) == "schema" else _find_descendants(member, "schema")
                for member_schema in member_schemas:
                    declared.add(member_schema.get("targetNamespace") or "")
                queue.extend(member_schemas)
        for schema_ns, namespace in pending_namespaces:
            if namespace in declared or namespace in _WELL_KNOWN_NAMESPACES:
                continue
            target = f"`{namespace}`" if namespace else "the no-namespace schema"
            self._add(
                RULE_UNRESOLVED_IMPORT,
                f"/schema/{schema_ns}/import/{namespace}",
                f"`xs:import` of {target} has no `schemaLocation`, and no schema in the import declares it.",
            )

    # -- bindings (WSDL 1.1) ------------------------------------------------------------------

    def bindings(self) -> None:
        """Check every SOAP binding of the description and the documents it imports."""
        messages: Dict[str, Dict[str, ET.Element]] = {}
        port_types: Dict[str, Dict[str, Tuple[Optional[str], Optional[str]]]] = {}
        for definition in self.definitions:
            for message in _children(definition, "message"):
                parts = {part.get("name") or "": part for part in _children(message, "part")}
                messages.setdefault(message.get("name") or "", parts)
            for port_type in _children(definition, "portType"):
                operations: Dict[str, Tuple[Optional[str], Optional[str]]] = {}
                for operation in _children(port_type, "operation"):
                    io = [next(iter(_children(operation, tag)), None) for tag in ("input", "output")]
                    operations.setdefault(
                        operation.get("name") or "",
                        tuple(_attr_local(el.get("message")) if el is not None else None for el in io),  # type: ignore[arg-type]
                    )
                port_types.setdefault(port_type.get("name") or "", operations)
        for definition in self.definitions:
            for binding in _children(definition, "binding"):
                soap_binding = next(iter(_soap(binding, "binding")), None)
                if soap_binding is not None:
                    self.binding(binding, soap_binding, messages, port_types)

    def binding(
        self,
        binding: ET.Element,
        soap_binding: ET.Element,
        messages: Dict[str, Dict[str, ET.Element]],
        port_types: Dict[str, Dict[str, Tuple[Optional[str], Optional[str]]]],
    ) -> None:
        """Check one SOAP binding: style consistency, literal use, body parts, signatures."""
        name = binding.get("name") or "(unnamed)"
        path = f"/binding/{name}"
        default_style = soap_binding.get("style") or "document"
        operations = port_types.get(_attr_local(binding.get("type")) or "", {})
        styles: Dict[str, List[str]] = {}
        actions: Dict[str, List[str]] = {}
        signatures: Dict[Tuple[str, str], List[str]] = {}
        for operation in _children(binding, "operation"):
            op_name = operation.get("name") or "(unnamed)"
            op_path = f"{path}/operation/{op_name}"
            soap_operation = next(iter(_soap(operation, "operation")), None)
            style = (soap_operation.get("style") if soap_operation is not None else None) or default_style
            action = (soap_operation.get("soapAction") if soap_operation is not None else None) or ""
            styles.setdefault(style, []).append(op_name)
            if action:
                actions.setdefault(action, []).append(op_name)
            input_message, output_message = operations.get(op_name, (None, None))
            body_child = ""
            for direction, message_name in (("input", input_message), ("output", output_message)):
                for io in _children(operation, direction):
                    child = self.io(io, style, messages.get(message_name or "", {}), op_name, f"{op_path}/{direction}")
                    if direction == "input":
                        body_child = child
            for fault in _children(operation, "fault"):
                self.literal_use(fault, op_name, f"{op_path}/fault/{fault.get('name') or ''}")
            if style == "rpc":
                body_child = op_name
            signatures.setdefault((body_child, action), []).append(op_name)
        if len(styles) > 1:
            listing = "; ".join(f"{style}: {', '.join(names)}" for style, names in sorted(styles.items()))
            self._add(
                RULE_BINDING_STYLE,
                path,
                f"binding `{name}` mixes operation styles ({listing}); a binding must be all rpc-literal or all "
                f"document-literal (WS-I R2705).",
            )
        for action, names in actions.items():
            if len(names) > 1:
                self._add(
                    RULE_UNIQUE_SOAP_ACTION,
                    path,
                    f"operations {', '.join(f'`{n}`' for n in names)} of binding `{name}` share soapAction "
                    f"`{action}`, so a service that dispatches on it cannot tell them apart.",
                )
        for (body_child, action), names in signatures.items():
            if len(names) > 1:
                wire = f"body element `{body_child}`" if body_child else "an empty body"
                self._add(
                    RULE_UNIQUE_OPERATION_SIGNATURE,
                    path,
                    f"operations {', '.join(f'`{n}`' for n in names)} of binding `{name}` send {wire}"
                    + (f" with the same soapAction `{action}`" if action else " and no soapAction")
                    + "; a receiver cannot tell them apart (WS-I R2710).",
                )

    def literal_use(self, element: ET.Element, op_name: str, path: str) -> None:
        """Report every ``soap:body`` / ``header`` / ``headerfault`` / ``fault`` with ``use="encoded"``.

        Args:
            element: A binding operation's ``input``, ``output`` or ``fault``.
            op_name: The operation, for the message.
            path: Where the element is.
        """
        extensions = [(tag, ext) for tag in ("body", "header", "fault") for ext in _soap(element, tag)]
        extensions += [
            ("headerfault", nested) for header in _soap(element, "header") for nested in _soap(header, "headerfault")
        ]
        for tag, extension in extensions:
            # R2707: an absent `use` is treated as literal.
            if (extension.get("use") or "literal") == "encoded":
                self._add(
                    RULE_LITERAL_USE,
                    path,
                    f'`soap:{tag}` of `{op_name}` uses `encoded`; WS-I requires `use="literal"` (R2706).',
                )

    def io(self, io: ET.Element, style: str, parts: Dict[str, ET.Element], op_name: str, path: str) -> str:
        """Check one binding ``input`` / ``output``; return the document-literal body child (or ``""``)."""
        self.literal_use(io, op_name, path)
        body = next(iter(_soap(io, "body")), None)
        if body is None:
            return ""
        listed = body.get("parts")
        referenced = [parts[n] for n in listed.split() if n in parts] if listed is not None else list(parts.values())
        if style == "rpc":
            for part in referenced:
                if part.get("element"):
                    self._add(
                        RULE_RPC_LITERAL,
                        path,
                        f"rpc-literal `{op_name}` body references part `{part.get('name')}` defined by `element`; "
                        f"rpc-literal parts must use `type` (WS-I R2203).",
                    )
            if not (body.get("namespace") or "").strip():
                self._add(
                    RULE_RPC_LITERAL,
                    path,
                    f"rpc-literal `{op_name}` body has no `namespace`; it must name the wrapper element's "
                    f"namespace (WS-I R2717).",
                )
            return ""
        if len(referenced) > 1:
            self._add(
                RULE_DOCUMENT_LITERAL,
                path,
                f"document-literal `{op_name}` body references {len(referenced)} parts; it may reference at most "
                f"one (WS-I R2201). Wrap them in one element, or list one with `parts`.",
            )
        for part in referenced:
            if part.get("type") and not part.get("element"):
                self._add(
                    RULE_DOCUMENT_LITERAL,
                    path,
                    f"document-literal `{op_name}` body references part `{part.get('name')}` defined by `type`; "
                    f"document-literal parts must use `element` (WS-I R2204).",
                )
        if body.get("namespace") is not None:
            self._add(
                RULE_DOCUMENT_LITERAL,
                path,
                f"document-literal `{op_name}` body has a `namespace` attribute; it must not (WS-I R2716).",
            )
        return _attr_local(referenced[0].get("element")) or "" if len(referenced) == 1 else ""

    def run(self) -> List[WsiIssue]:
        """Run the import checks, then (WSDL 1.1) the binding checks."""
        self.wsdl_imports()
        self.schema_imports()
        if self.version != VERSION_2_0:
            self.bindings()
        return self.issues


def check_wsi(
    raw: str, *, version: str, members: Optional[Mapping[str, str]] = None, source_label: Optional[str] = None
) -> Tuple[List[WsiIssue], int]:
    """Run the WS-I Basic Profile checks over a WSDL description.

    Args:
        raw: The root description's text (already parsed successfully by the WSDL parser).
        version: Its WSDL version (``1.1`` or ``2.0``).
        members: The fileset / live-fetch documents its imports resolve against, if any.
        source_label: Label for XML errors.

    Returns:
        The first :data:`MAX_REPORTED_ISSUES` issues in document order, and how many there were.
    """
    try:
        root = parse_xml(raw, source_label=source_label)
    except SecureXmlError:
        return [], 0
    issues = _Checker(root, members, version).run()
    return issues[:MAX_REPORTED_ISSUES], len(issues)
