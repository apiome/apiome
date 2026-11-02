"""WADL parser — MFI-17.1, extended by MFI-21.3 (#3993).

Parses WADL REST service descriptions into a typed :class:`WadlDocument` AST using
the stdlib :mod:`xml.etree.ElementTree`. Syntax errors surface as
:class:`WadlParseError`.

What the AST keeps (W3C WADL submission, 2009-02 namespace):

* **Resources and methods** — every ``resource`` (nested paths joined) and ``method`` becomes a
  :class:`WadlOperation`. WADL's reuse is resolved in place: a ``method href="#id"``, a
  ``param href``, a ``representation href`` and a resource's ``type="#rt1 #rt2"`` (its
  ``resource_type`` s' params, methods and child resources) read as if written inline. A
  reference that names no element of the document is kept in
  :attr:`WadlDocument.unresolved_refs` rather than guessed at.
* **Params** — name, location (from ``style``), XSD type, ``required``, ``repeating``,
  ``default`` and ``option`` values, plus the original ``style`` (``matrix`` and ``plain`` have
  no canonical location of their own).
* **Representations** — the media types of a request and of each response, and the grammar type
  an ``element`` / ``type`` names. A response's ``status`` is a *list* of codes; each code reads
  as its own response.
* **Grammars** — named ``complexType`` s (sequence elements with ``minOccurs`` / ``maxOccurs`` /
  ``nillable``) and named ``simpleType`` restrictions (enumerations and their base type).
"""

from __future__ import annotations

import posixpath
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import List, Mapping, Optional, Tuple

from .secure_xml import SecureXmlError, parse_xml

__all__ = [
    "WadlParseError",
    "WadlField",
    "WadlComplexType",
    "WadlSimpleType",
    "WadlElementDecl",
    "WadlParameter",
    "WadlOperation",
    "WadlDocument",
    "is_wadl",
    "parse_wadl",
]

_WADL_NS_MARKERS = (
    "http://wadl.dev.java.net/2009/02",
    "http://wadl.dev.java.net/ns/wadl",
)


#: A WADL ``application`` start tag, prefixed or not.
_APPLICATION_TAG = re.compile(r"<(?:[\w.\-]+:)?application[\s>/]", re.IGNORECASE)


class WadlParseError(ValueError):
    """Raised when WADL text cannot be parsed."""


@dataclass(frozen=True)
class WadlField:
    """One ``xsd:element`` of a complex type's sequence.

    Attributes:
        name: The element name.
        type_expr: Its XSD type, prefix stripped (``string``, ``Book``).
        min_occurs: ``minOccurs`` (XSD default ``1``; ``0`` makes the element optional).
        max_occurs: ``maxOccurs`` — ``1`` by default, a number, or ``None`` for ``unbounded``.
        nillable: Whether the element is ``nillable="true"``.
    """

    name: str
    type_expr: str
    min_occurs: int = 1
    max_occurs: Optional[int] = 1
    nillable: bool = False


@dataclass(frozen=True)
class WadlComplexType:
    name: str
    fields: Tuple[WadlField, ...]


@dataclass(frozen=True)
class WadlSimpleType:
    """A named ``xsd:simpleType`` restriction.

    Attributes:
        name: The simple type's name.
        base: The restriction's base type, prefix stripped (``string``).
        enumerations: The ``xsd:enumeration`` values, in source order (empty when the
            restriction is only a facet on its base).
    """

    name: str
    base: str
    enumerations: Tuple[str, ...] = ()


@dataclass(frozen=True)
class WadlElementDecl:
    name: str
    type_expr: str


@dataclass(frozen=True)
class WadlParameter:
    """A WADL ``param`` of a resource or a request.

    Attributes:
        name: The param name.
        location: ``path`` / ``query`` / ``header`` (from ``style``).
        type_expr: Its XSD type, prefix stripped.
        required: ``required`` (WADL's default is ``false``; this parser has always read an
            omitted attribute as ``true``, which the corpus relies on).
        style: The original ``style`` (``template``, ``matrix``, ``query``, ``header``,
            ``plain``).
        repeating: ``repeating="true"`` — the param may occur more than once.
        default: The ``default`` value, when declared.
        options: The ``option`` values, in source order (the allowed values).
    """

    name: str
    location: str
    type_expr: str
    required: bool = True
    style: str = "template"
    repeating: bool = False
    default: Optional[str] = None
    options: Tuple[str, ...] = ()


@dataclass(frozen=True)
class WadlOperation:
    path: str
    method: str
    operation_id: Optional[str]
    description: Optional[str]
    parameters: Tuple[WadlParameter, ...]
    request_type: Optional[str]
    response_types: Tuple[Tuple[str, Optional[str]], ...]
    #: The media types of the request's representations, in source order.
    request_media_types: Tuple[str, ...] = ()
    #: The media types of each response, aligned with :attr:`response_types` by index.
    response_media_types: Tuple[Tuple[str, ...], ...] = ()


@dataclass(frozen=True)
class WadlDocument:
    name: str
    target_namespace: Optional[str]
    base_uri: Optional[str]
    complex_types: Tuple[WadlComplexType, ...]
    elements: Tuple[WadlElementDecl, ...]
    operations: Tuple[WadlOperation, ...]
    raw: str
    simple_types: Tuple[WadlSimpleType, ...] = ()
    #: Every ``href`` / resource ``type`` reference that names no element of the document, as
    #: ``"<element> <reference>"`` (``"method #getBook"``), in document order without repeats.
    unresolved_refs: Tuple[str, ...] = ()


def is_wadl(content: str) -> bool:
    """Return ``True`` when ``content`` looks like a WADL document."""
    if not content or not isinstance(content, str):
        return False
    trimmed = content.strip()
    if not trimmed:
        return False
    # The root may be prefixed (`<wadl:application`), as WADL written by Apiome's emitter is.
    if not _APPLICATION_TAG.search(trimmed):
        return False
    return any(marker in trimmed for marker in _WADL_NS_MARKERS)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _attr_local(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    if ":" in value:
        return value.split(":", 1)[1]
    return value


def _children(element: ET.Element, local_name: str) -> List[ET.Element]:
    return [child for child in element if _local(child.tag) == local_name]


def _find_descendants(element: ET.Element, local_name: str) -> List[ET.Element]:
    return [node for node in element.iter() if _local(node.tag) == local_name]


def _join_path(parent: str, segment: str) -> str:
    if not segment:
        return parent or "/"
    if segment.startswith("/"):
        return segment
    base = parent.rstrip("/") if parent else ""
    if not base:
        return f"/{segment}"
    return f"{base}/{segment}"


def _inline_restriction_base(element: ET.Element) -> Optional[str]:
    """The base of an element's inline ``simpleType`` restriction (``xsd:string`` → ``string``)."""
    for simple in _children(element, "simpleType"):
        for restriction in _children(simple, "restriction"):
            return _attr_local(restriction.get("base"))
    return None


def _grammar_schemas(
    grammars_el: Optional[ET.Element], members: Optional[Mapping[str, str]], source_label: Optional[str]
) -> List[ET.Element]:
    """Every ``xsd:schema`` of the grammars: inline ones, then each ``include`` found in ``members``.

    An ``include`` whose document is not in the set (or is not a schema) is skipped: a single
    uploaded WADL that references an external grammar still imports its resources.
    """
    if grammars_el is None:
        return []
    schemas = list(_find_descendants(grammars_el, "schema"))
    for include in _children(grammars_el, "include"):
        href = include.get("href")
        if not href or not members:
            continue
        text = members.get(href) or members.get(posixpath.basename(href))
        if not text:
            continue
        try:
            document = parse_xml(text, source_label=href or source_label)
        except SecureXmlError:
            continue
        if _local(document.tag) == "schema":
            schemas.append(document)
    return schemas


def _occurs(value: Optional[str], default: Optional[int]) -> Optional[int]:
    """An XSD occurrence attribute: an integer, ``None`` for ``unbounded``, else ``default``."""
    if value is None:
        return default
    if value.strip().lower() == "unbounded":
        return None
    try:
        return max(int(value.strip()), 0)
    except ValueError:
        return default


def _parse_complex_types(schemas: List[ET.Element]) -> Tuple[WadlComplexType, ...]:
    complex_types: List[WadlComplexType] = []
    for schema in schemas:
        for complex_type in _children(schema, "complexType"):
            name = complex_type.get("name")
            if not name:
                continue
            fields: List[WadlField] = []
            for sequence in _find_descendants(complex_type, "sequence"):
                for field_el in _children(sequence, "element"):
                    field_name = field_el.get("name")
                    type_expr = field_el.get("type") or _inline_restriction_base(field_el)
                    if field_name and type_expr:
                        fields.append(
                            WadlField(
                                name=field_name,
                                type_expr=_attr_local(type_expr) or type_expr,
                                min_occurs=_occurs(field_el.get("minOccurs"), 1) or 0,
                                max_occurs=_occurs(field_el.get("maxOccurs"), 1),
                                nillable=(field_el.get("nillable") or "").strip().lower() == "true",
                            )
                        )
            complex_types.append(WadlComplexType(name=name, fields=tuple(fields)))
    return tuple(complex_types)


def _parse_simple_types(schemas: List[ET.Element]) -> Tuple[WadlSimpleType, ...]:
    """Every named top-level ``xsd:simpleType`` restriction of the grammars."""
    simple_types: List[WadlSimpleType] = []
    for schema in schemas:
        for simple in _children(schema, "simpleType"):
            name = simple.get("name")
            restriction = next(iter(_children(simple, "restriction")), None)
            if not name or restriction is None:
                continue
            enumerations = _children(restriction, "enumeration")
            values = tuple(enum.get("value") or "" for enum in enumerations if enum.get("value") is not None)
            simple_types.append(
                WadlSimpleType(
                    name=name,
                    base=_attr_local(restriction.get("base")) or "string",
                    enumerations=values,
                )
            )
    return tuple(simple_types)


def _parse_elements(schemas: List[ET.Element]) -> Tuple[WadlElementDecl, ...]:
    elements: List[WadlElementDecl] = []
    for schema in schemas:
        for element in _children(schema, "element"):
            name = element.get("name")
            type_expr = element.get("type")
            if name and type_expr:
                elements.append(
                    WadlElementDecl(
                        name=name,
                        type_expr=_attr_local(type_expr) or type_expr,
                    )
                )
    return tuple(elements)


def _param_location(style: Optional[str]) -> str:
    mapping = {
        "template": "path",
        "query": "query",
        "header": "header",
        "matrix": "path",
        "plain": "query",
    }
    return mapping.get((style or "template").lower(), "query")


#: The WADL elements a local ``href`` (or a resource ``type``) may name.
_REFERABLE = frozenset({"method", "param", "representation", "resource_type"})

#: How many ``href`` hops are followed before a chain is treated as a cycle.
_MAX_HREF_HOPS = 8


class _References:
    """The document's referable elements by id, and the references that resolved to none.

    WADL lets a ``method``, ``param`` or ``representation`` be written once with an ``id`` and
    reused with ``href="#id"``; a ``resource`` names ``resource_type`` s in ``type``. Only local
    (``#id``) references are followed: an external WADL is not fetched.
    """

    def __init__(self, root: ET.Element) -> None:
        self._by_id: dict[Tuple[str, str], ET.Element] = {}
        for node in root.iter():
            local = _local(node.tag) if isinstance(node.tag, str) else ""
            node_id = node.get("id")
            if local in _REFERABLE and node_id and (local, node_id) not in self._by_id:
                self._by_id[(local, node_id)] = node
        self.unresolved: List[str] = []

    def _miss(self, kind: str, reference: str) -> None:
        entry = f"{kind} {reference}"
        if entry not in self.unresolved:
            self.unresolved.append(entry)

    def lookup(self, kind: str, reference: str) -> Optional[ET.Element]:
        """The element of ``kind`` a ``#id`` reference names, recording a miss."""
        target = self._by_id.get((kind, reference[1:])) if reference.startswith("#") else None
        if target is None:
            self._miss(kind, reference)
        return target

    def deref(self, element: ET.Element) -> Optional[ET.Element]:
        """``element`` itself, or what its ``href`` chain points at (``None`` when unresolved)."""
        kind = _local(element.tag)
        current = element
        for _ in range(_MAX_HREF_HOPS):
            href = current.get("href")
            if not href:
                return current
            target = self.lookup(kind, href.strip())
            if target is None:
                return None
            current = target
        self._miss(kind, element.get("href") or "")
        return None

    def children(self, element: ET.Element, local_name: str) -> List[ET.Element]:
        """``element``'s ``local_name`` children with every ``href`` resolved (misses dropped)."""
        resolved = (self.deref(child) for child in _children(element, local_name))
        return [child for child in resolved if child is not None]

    def resource_types(self, resource_el: ET.Element) -> List[ET.Element]:
        """The ``resource_type`` s a resource's ``type`` attribute names, in order."""
        found: List[ET.Element] = []
        for reference in (resource_el.get("type") or "").split():
            target = self.lookup("resource_type", reference)
            if target is not None:
                found.append(target)
        return found


def _parse_param(param_el: ET.Element) -> Optional[WadlParameter]:
    """One ``param`` element, or ``None`` when it has no name."""
    name = param_el.get("name")
    if not name:
        return None
    style = (param_el.get("style") or "template").strip().lower()
    options = tuple(
        option.get("value") or "" for option in _children(param_el, "option") if option.get("value") is not None
    )
    return WadlParameter(
        name=name,
        location=_param_location(style),
        type_expr=_attr_local(param_el.get("type")) or "string",
        required=param_el.get("required", "true").lower() != "false",
        style=style,
        repeating=(param_el.get("repeating") or "").strip().lower() == "true",
        default=param_el.get("default"),
        options=options,
    )


def _parse_parameters(param_els: List[ET.Element]) -> Tuple[WadlParameter, ...]:
    params = (_parse_param(param_el) for param_el in param_els)
    return tuple(param for param in params if param is not None)


def _resolve_element_type(
    element_ref: Optional[str],
    *,
    element_to_type: dict[str, str],
) -> Optional[str]:
    """The grammar type a representation's ``element`` names (the element's own name if untyped)."""
    if not element_ref:
        return None
    local = _attr_local(element_ref) or element_ref
    mapped = element_to_type.get(local)
    if mapped:
        return _attr_local(mapped) or mapped
    return local


def _representations(
    container: Optional[ET.Element],
    *,
    element_to_type: dict[str, str],
    references: _References,
) -> Tuple[Optional[str], Tuple[str, ...]]:
    """The first typed representation's type and every representation's media type.

    Args:
        container: A ``request`` or ``response`` element (or ``None``).
        element_to_type: Grammar element name → its type.
        references: The document's ``href`` index.

    Returns:
        ``(type, media_types)`` — the type is ``None`` when no representation names one.
    """
    if container is None:
        return None, ()
    found: Optional[str] = None
    media_types: List[str] = []
    for representation in references.children(container, "representation"):
        media_type = (representation.get("mediaType") or "").strip()
        if media_type and media_type not in media_types:
            media_types.append(media_type)
        if found is None:
            found = _resolve_element_type(representation.get("element"), element_to_type=element_to_type) or (
                _attr_local(representation.get("type"))
            )
    return found, tuple(media_types)


def _statuses(response_el: ET.Element) -> List[str]:
    """The codes of a response's ``status`` list (``"200"`` when it states none)."""
    codes = (response_el.get("status") or "").split()
    return codes or ["200"]


def _parse_method(
    method_el: ET.Element,
    *,
    path: str,
    params: Tuple[WadlParameter, ...],
    element_to_type: dict[str, str],
    references: _References,
) -> WadlOperation:
    """One (already dereferenced) ``method`` at ``path``, inheriting the resource's ``params``."""
    method_name = (method_el.get("name") or "GET").upper()
    doc_el = next(iter(_children(method_el, "doc")), None)
    description = doc_el.text.strip() if doc_el is not None and doc_el.text else None
    request_el = next(iter(_children(method_el, "request")), None)
    # Query, header and plain params a method's request declares, after the resource's own.
    method_params = params + (
        _parse_parameters(references.children(request_el, "param")) if request_el is not None else ()
    )
    request_type, request_media = _representations(
        request_el, element_to_type=element_to_type, references=references
    )
    responses: List[Tuple[str, Optional[str]]] = []
    response_media: List[Tuple[str, ...]] = []
    for response_el in _children(method_el, "response"):
        response_type, media = _representations(
            response_el, element_to_type=element_to_type, references=references
        )
        for status in _statuses(response_el):
            responses.append((status, response_type))
            response_media.append(media)
    return WadlOperation(
        path=path,
        method=method_name,
        operation_id=method_el.get("id"),
        description=description,
        parameters=method_params,
        request_type=request_type,
        response_types=tuple(responses),
        request_media_types=request_media,
        response_media_types=tuple(response_media),
    )


def _collect_operations(
    resource_el: ET.Element,
    *,
    parent_path: str,
    inherited_params: Tuple[WadlParameter, ...],
    element_to_type: dict[str, str],
    references: _References,
) -> List[WadlOperation]:
    """Every method of a resource and its descendants, the resource's ``type`` s applied."""
    operations: List[WadlOperation] = []
    segment = resource_el.get("path") or ""
    current_path = _join_path(parent_path, segment)
    # A resource reads as its own params / methods / child resources followed by those of each
    # resource_type it names.
    sources = [resource_el, *references.resource_types(resource_el)]
    param_els = [param for source in sources for param in references.children(source, "param")]
    params = inherited_params + _parse_parameters(param_els)

    for source in sources:
        for method_el in references.children(source, "method"):
            operations.append(
                _parse_method(
                    method_el,
                    path=current_path,
                    params=params,
                    element_to_type=element_to_type,
                    references=references,
                )
            )

    for source in sources:
        for child in _children(source, "resource"):
            operations.extend(
                _collect_operations(
                    child,
                    parent_path=current_path,
                    inherited_params=params,
                    element_to_type=element_to_type,
                    references=references,
                )
            )
    return operations


def _document_name(root: ET.Element) -> str:
    doc_el = next(iter(_children(root, "doc")), None)
    if doc_el is not None and doc_el.text and doc_el.text.strip():
        return doc_el.text.strip()
    if root.get("id"):
        return root.get("id") or "WADL API"
    return "WADL API"


def parse_wadl(
    content: str, *, source_label: Optional[str] = None, members: Optional[Mapping[str, str]] = None
) -> WadlDocument:
    """Parse WADL XML into a :class:`WadlDocument`.

    Args:
        content: The WADL document.
        source_label: Label for errors.
        members: Sibling documents of a multi-file set (``path → text``); a grammar the WADL
            ``include`` s is read from here.

    Returns:
        The parsed document.

    Raises:
        WadlParseError: The text is empty, is not WADL, is malformed XML, or declares neither
            a grammar type nor a resource.
        SecureXmlError: The XML was refused by the hardened parser (DTD, entity, size, depth).
    """
    if not content or not content.strip():
        raise WadlParseError("Invalid or empty WADL document")
    if not is_wadl(content):
        raise WadlParseError("Content does not appear to be a WADL document")

    try:
        root = parse_xml(content, source_label=source_label)
    except SecureXmlError as exc:
        if exc.code == "INPUT_MALFORMED":
            raise WadlParseError(f"Malformed XML: {exc}") from exc
        raise

    if _local(root.tag) != "application":
        raise WadlParseError("WADL root element must be `application`")

    grammars_el = next(iter(_children(root, "grammars")), None)
    schemas = _grammar_schemas(grammars_el, members, source_label)
    complex_types = _parse_complex_types(schemas)
    simple_types = _parse_simple_types(schemas)
    elements = _parse_elements(schemas)
    element_to_type = {element.name: element.type_expr for element in elements}
    references = _References(root)

    operations: List[WadlOperation] = []
    base_uri: Optional[str] = None
    for resources_el in _children(root, "resources"):
        base_uri = resources_el.get("base") or base_uri
        for resource_el in _children(resources_el, "resource"):
            operations.extend(
                _collect_operations(
                    resource_el,
                    parent_path="",
                    inherited_params=(),
                    element_to_type=element_to_type,
                    references=references,
                )
            )

    target_namespace: Optional[str] = None
    for schema in schemas:
        target_namespace = schema.get("targetNamespace") or target_namespace

    if not complex_types and not operations:
        label = f" ({source_label})" if source_label else ""
        raise WadlParseError(f"No WADL types or resources found{label}")

    return WadlDocument(
        name=_document_name(root),
        target_namespace=target_namespace,
        base_uri=base_uri,
        complex_types=complex_types,
        elements=elements,
        operations=tuple(operations),
        raw=content,
        simple_types=simple_types,
        unresolved_refs=tuple(references.unresolved),
    )
