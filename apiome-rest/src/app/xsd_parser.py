"""XML Schema (XSD) parser.

Parses W3C XML Schema documents into a typed :class:`XsdDocument` AST using the
stdlib :mod:`xml.etree.ElementTree`.

**A schema split across files** (MFI-13.1, #3788). Parsed with the members of a multi-file set,
the schema's ``xs:import`` / ``xs:include`` / ``xs:redefine`` / ``xs:override`` references are
followed (:func:`app.xml_import_graph.resolve_import_graph`, each location relative to the file
that declares it), and the types and elements of every schema reached are read with the root's.
Names are merged the way the WSDL reader merges them: by local name, the first declaration (the
root's, then discovery order) winning.

**XSD 1.1** is recognized (:func:`detect_xsd_version`) and recorded; its 1.1-only constructs
(assertions, type alternatives, open content) are not modeled.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional, Set, Tuple

from .secure_xml import SecureXmlError, parse_xml
from .xml_canonical_hash import canonical_xml_sha256
from .xml_import_graph import resolve_import_graph

__all__ = [
    "XsdParseError",
    "XsdField",
    "XsdComplexType",
    "XsdSimpleType",
    "XsdElementDecl",
    "XsdDocument",
    "detect_xsd_version",
    "is_xsd",
    "parse_xsd",
]

_XSD_NS = "http://www.w3.org/2001/XMLSchema"
#: The XSD versioning namespace; ``vc:minVersion="1.1"`` marks a schema as XSD 1.1.
_VC_NS = "http://www.w3.org/2007/XMLSchema-versioning"
#: Elements that exist only in XSD 1.1.
_XSD_1_1_ONLY = frozenset({"assert", "assertion", "alternative", "openContent", "defaultOpenContent", "override"})


class XsdParseError(ValueError):
    """Raised when XSD text cannot be parsed."""


@dataclass(frozen=True)
class XsdField:
    """One member of a complex type.

    ``kind`` is ``"element"`` for a sequence / choice / all member, ``"attribute"`` for an
    attribute, and ``"value"`` for the simple content a ``simpleContent`` type wraps (MFI-20.3).
    """

    name: str
    type_expr: str
    kind: str = "element"
    max_occurs: Optional[str] = None
    min_occurs: Optional[str] = None


@dataclass(frozen=True)
class XsdComplexType:
    name: str
    fields: Tuple[XsdField, ...]


@dataclass(frozen=True)
class XsdSimpleType:
    name: str
    base: Optional[str]
    enum_values: Tuple[str, ...]


@dataclass(frozen=True)
class XsdElementDecl:
    name: str
    type_expr: str


@dataclass(frozen=True)
class XsdDocument:
    """A parsed schema and, when parsed as a set, the schemas it imports.

    Attributes:
        target_namespace: The root schema's ``targetNamespace``.
        root_element: The first global element's name, if any.
        complex_types: Named complex types, the root's first.
        simple_types: Named simple types, the root's first.
        elements: Global element declarations, the root's first.
        raw: The root document's text.
        import_graph: The documents the schema was read from and the references nothing
            answered (MFI-13.1); ``None`` for one self-contained file.
        c14n_sha256: SHA-256 over Canonical XML 2.0 of every document read (MFI-13.1,
            :mod:`app.xml_canonical_hash`), or ``None`` when it could not be computed.
        xsd_version: ``1.1`` when any schema read is XSD 1.1, else ``1.0``.
    """

    target_namespace: Optional[str]
    root_element: Optional[str]
    complex_types: Tuple[XsdComplexType, ...]
    simple_types: Tuple[XsdSimpleType, ...]
    elements: Tuple[XsdElementDecl, ...]
    raw: str
    import_graph: Optional[Dict[str, object]] = None
    c14n_sha256: Optional[str] = None
    xsd_version: str = "1.0"


def detect_xsd_version(schemas: Iterable[ET.Element]) -> str:
    """Return ``1.1`` when any schema is XSD 1.1, else ``1.0``.

    A schema is XSD 1.1 when it says so (``vc:minVersion="1.1"`` or higher on the ``schema``
    element) or when it uses an element only XSD 1.1 defines (``xs:assert``, ``xs:assertion``,
    ``xs:alternative``, ``xs:openContent``, ``xs:defaultOpenContent``, ``xs:override``).

    Args:
        schemas: ``xs:schema`` elements.

    Returns:
        ``"1.1"`` or ``"1.0"``.
    """
    for schema in schemas:
        min_version = (schema.get(f"{{{_VC_NS}}}minVersion") or "").strip()
        try:
            if min_version and float(min_version) >= 1.1:
                return "1.1"
        except ValueError:
            pass
        for node in schema.iter():
            tag = node.tag
            if isinstance(tag, str) and tag.startswith(f"{{{_XSD_NS}}}") and _local(tag) in _XSD_1_1_ONLY:
                return "1.1"
    return "1.0"


def is_xsd(content: str) -> bool:
    """Return ``True`` when ``content`` looks like a standalone XSD schema."""
    if not content or not isinstance(content, str):
        return False
    trimmed = content.strip()
    if not trimmed:
        return False
    if "<wsdl:definitions" in trimmed or (
        "<definitions" in trimmed and "schemas.xmlsoap.org/wsdl" in trimmed
    ):
        return False
    if "<application" in trimmed and "wadl.dev.java.net" in trimmed:
        return False
    if "<xs:schema" in trimmed or "<xsd:schema" in trimmed:
        return True
    try:
        root = parse_xml(trimmed)
    except SecureXmlError:
        # Sniffers must never raise: an unsafe or malformed document is simply
        # not a recognized XSD (the parse phase reports the real reason).
        return False
    return _local(root.tag) == "schema" and _XSD_NS in root.tag


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _attr_local(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    if ":" in value:
        return value.split(":", 1)[1]
    return value


def _children(element: ET.Element, local_name: str) -> List[ET.Element]:
    return [child for child in element if isinstance(child.tag, str) and _local(child.tag) == local_name]


def _find_descendants(element: ET.Element, local_name: str) -> List[ET.Element]:
    return [node for node in element.iter() if isinstance(node.tag, str) and _local(node.tag) == local_name]


def _global_element_types(schemas: Iterable[ET.Element]) -> Dict[str, str]:
    """Every global element's local name -> its type's local name, across a schema set.

    A ``<xs:element ref="cbc:ID"/>`` declares no name or type of its own: it *is* the global
    element it names. UBL builds every document type this way (MFI-20.5). The first schema to
    declare a name wins, as it does for types.

    Args:
        schemas: The ``xs:schema`` elements read, the root's first.

    Returns:
        ``{element_name: type_name}`` for the global elements that name a type.
    """
    types: Dict[str, str] = {}
    for schema in schemas:
        for element in _children(schema, "element"):
            name, type_expr = element.get("name"), element.get("type")
            if name and type_expr and name not in types:
                types[name] = _attr_local(type_expr) or type_expr
    return types


def _parse_complex_types(
    schema_el: ET.Element, global_elements: Optional[Mapping[str, str]] = None
) -> Tuple[XsdComplexType, ...]:
    """Read a schema's named complex types and their fields.

    Args:
        schema_el: One ``xs:schema`` element.
        global_elements: :func:`_global_element_types` of the whole set, so a member written as
            ``<xs:element ref="…"/>`` reads as the global element it refers to.

    Returns:
        The named complex types, in document order.
    """
    global_elements = global_elements or {}
    complex_types: List[XsdComplexType] = []
    for complex_type in _children(schema_el, "complexType"):
        name = complex_type.get("name")
        if not name:
            continue
        fields: List[XsdField] = []
        seen: Set[str] = set()
        # MFI-20.3: a member of an ``xs:choice`` (or ``xs:all``) is a field like a sequence
        # member — ISO 20022 message definitions build most of their types from ``…Choice``
        # types — and, being one alternative among several, is optional unless it says
        # otherwise. The first declaration of a name wins when a type repeats it.
        for group_name in ("sequence", "choice", "all"):
            for group in _find_descendants(complex_type, group_name):
                for field_el in _children(group, "element"):
                    field_name = field_el.get("name")
                    type_expr = field_el.get("type")
                    reference = field_el.get("ref")
                    if not field_name and reference:
                        # MFI-20.5: a reference to a global element takes its name and type.
                        field_name = _attr_local(reference)
                        type_expr = global_elements.get(field_name or "")
                    if not field_name or not type_expr or field_name in seen:
                        continue
                    seen.add(field_name)
                    min_occurs = field_el.get("minOccurs")
                    if group_name == "choice" and min_occurs is None:
                        min_occurs = "0"
                    fields.append(
                        XsdField(
                            name=field_name,
                            type_expr=_attr_local(type_expr) or type_expr,
                            kind="element",
                            max_occurs=field_el.get("maxOccurs"),
                            min_occurs=min_occurs,
                        )
                    )
        # ``xs:simpleContent`` wraps a simple value (an ISO 20022 amount) with attributes (its
        # ``Ccy``): the value is read as the ``value`` field of the base type (MFI-20.3).
        for simple_content in _children(complex_type, "simpleContent"):
            for derivation in (*_children(simple_content, "extension"), *_children(simple_content, "restriction")):
                base = derivation.get("base")
                if base and "value" not in seen:
                    seen.add("value")
                    fields.append(XsdField(name="value", type_expr=_attr_local(base) or base, kind="value"))
        # Attributes may sit on the type itself or inside a simpleContent / complexContent
        # derivation; read them wherever they are declared.
        for attr_el in _find_descendants(complex_type, "attribute"):
            attr_name = attr_el.get("name")
            type_expr = attr_el.get("type")
            if attr_name and type_expr and attr_name not in seen:
                seen.add(attr_name)
                fields.append(
                    XsdField(
                        name=attr_name,
                        type_expr=_attr_local(type_expr) or type_expr,
                        kind="attribute",
                    )
                )
        complex_types.append(XsdComplexType(name=name, fields=tuple(fields)))
    return tuple(complex_types)


def _parse_simple_types(schema_el: ET.Element) -> Tuple[XsdSimpleType, ...]:
    simple_types: List[XsdSimpleType] = []
    for simple_type in _children(schema_el, "simpleType"):
        name = simple_type.get("name")
        if not name:
            continue
        restriction = next(iter(_children(simple_type, "restriction")), None)
        base = _attr_local(restriction.get("base")) if restriction is not None else None
        enum_values: List[str] = []
        if restriction is not None:
            for enum_el in _children(restriction, "enumeration"):
                value = enum_el.get("value")
                if isinstance(value, str) and value:
                    enum_values.append(value)
        simple_types.append(
            XsdSimpleType(name=name, base=base, enum_values=tuple(enum_values))
        )
    return tuple(simple_types)


def _parse_elements(schema_el: ET.Element) -> Tuple[XsdElementDecl, ...]:
    elements: List[XsdElementDecl] = []
    for element in _children(schema_el, "element"):
        name = element.get("name")
        type_expr = element.get("type")
        if name and type_expr:
            elements.append(
                XsdElementDecl(name=name, type_expr=_attr_local(type_expr) or type_expr)
            )
    return tuple(elements)


def _first_by_name(items: Iterable, seen: Set[str]) -> List:
    """Keep the items whose ``name`` is not yet in ``seen`` (and add theirs); first one wins."""
    kept = []
    for item in items:
        if item.name in seen:
            continue
        seen.add(item.name)
        kept.append(item)
    return kept


def parse_xsd(
    content: str,
    *,
    source_label: Optional[str] = None,
    members: Optional[Mapping[str, str]] = None,
) -> XsdDocument:
    """Parse XSD XML into an :class:`XsdDocument`.

    Args:
        content: The root schema's text.
        source_label: Label used in error messages; for a set, the root's member key, which
            relative locations resolve from.
        members: The documents of a multi-file set, key -> text, or ``None`` for one file.

    Returns:
        The parsed schema, with the types of every schema it imports when ``members`` is given.

    Raises:
        XsdParseError: When the text is empty, is not XSD, is malformed, or no schema read
            declares a type or element.
    """
    if not content or not content.strip():
        raise XsdParseError("Invalid or empty XSD document")
    if not is_xsd(content):
        label = f" ({source_label})" if source_label else ""
        raise XsdParseError(f"Content does not appear to be an XSD schema{label}")
    try:
        root = parse_xml(content, source_label=source_label)
    except SecureXmlError as exc:
        if exc.code == "INPUT_MALFORMED":
            raise XsdParseError(f"Malformed XSD document: {exc}") from exc
        raise

    if _local(root.tag) != "schema":
        raise XsdParseError("XSD root element must be `schema`")

    graph = resolve_import_graph(root, root_text=content, root_path=source_label, members=members)
    schemas: List[ET.Element] = [root]
    for document in graph.imported():
        element = document.element
        schemas.extend([element] if _local(element.tag) == "schema" else _find_descendants(element, "schema"))

    complex_names: Set[str] = set()
    simple_names: Set[str] = set()
    element_names: Set[str] = set()
    complex_types_list: List[XsdComplexType] = []
    simple_types_list: List[XsdSimpleType] = []
    elements_list: List[XsdElementDecl] = []
    global_elements = _global_element_types(schemas)
    for schema in schemas:
        complex_types_list += _first_by_name(_parse_complex_types(schema, global_elements), complex_names)
        simple_types_list += _first_by_name(_parse_simple_types(schema), simple_names)
        elements_list += _first_by_name(_parse_elements(schema), element_names)
    complex_types = tuple(complex_types_list)
    simple_types = tuple(simple_types_list)
    elements = tuple(elements_list)
    if not complex_types and not simple_types and not elements:
        label = f" ({source_label})" if source_label else ""
        raise XsdParseError(f"No XSD types or elements found{label}")

    root_element = elements[0].name if elements else None
    return XsdDocument(
        target_namespace=root.get("targetNamespace"),
        root_element=root_element,
        complex_types=complex_types,
        simple_types=simple_types,
        elements=elements,
        raw=content,
        import_graph=graph.as_extras(),
        c14n_sha256=canonical_xml_sha256(graph),
        xsd_version=detect_xsd_version(schemas),
    )
