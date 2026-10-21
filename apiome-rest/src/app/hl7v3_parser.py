"""HL7 v3 / CDA parser — FMT-6.4 (#5448).

Reads an HL7 v3 Clinical Document Architecture (CDA R2) document — a CCD, a discharge summary or any
other C-CDA document type — into a :class:`CdaDocument`: the parsed ``ClinicalDocument`` element plus
what the importer reads out of it as structure:

* every ``templateId`` as a :class:`TemplateClaim` — an *asserted* conformance claim, never checked;
* the structured body as a :class:`CdaSection` tree (``component`` → ``section`` → nested sections),
  each section with its code, title, template claims and the entries it holds.

An HL7 v3 **transmission wrapper** (``MCCI_IN000002UV01`` and other interactions whose
``ControlActProcess`` references a document) is read only as the root of a fileset: its payload
reference names the member holding the CDA document, and the wrapper is kept as
:class:`TransmissionWrapper`.

XML goes through :func:`app.secure_xml.parse_xml` (no DTD, entities, external references or
XInclude; size and depth caps). **Errors** are :class:`Hl7V3ParseError` with an intake-taxonomy code:

* ``INPUT_TRUNCATED`` — the XML ends before the document does;
* ``INPUT_MALFORMED`` — the XML is not well formed;
* ``FORMAT_MISMATCH`` — the text is not XML, or its root element is not in the ``urn:hl7-org:v3``
  namespace;
* ``INPUT_SEMANTIC_INVALID`` — a v3 root that is neither a ``ClinicalDocument`` nor a wrapper, or a
  header missing ``id``, ``code``, ``effectiveTime``, ``recordTarget``, ``author``, ``custodian`` or
  the body ``component``;
* ``INPUT_REFERENCE_UNRESOLVED`` — a narrative ``reference`` (``#anchor``) that no ``ID`` in the
  document defines, or a wrapper whose payload is not in the upload.

A guard code from :mod:`app.secure_xml` (``INPUT_UNSAFE_CONSTRUCT``, ``INPUT_TOO_LARGE``, …) is kept.
Encoding faults are refused code-less so the import pipeline names them.
"""

from __future__ import annotations

import posixpath
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Mapping, Optional, Tuple

from .hl7v3_datatypes import CDA_NAMESPACE, SDTC_NAMESPACE, XSI_NAMESPACE
from .secure_xml import SecureXmlError, parse_xml

__all__ = [
    "CdaDocument",
    "CdaEntry",
    "CdaSection",
    "Hl7V3ParseError",
    "REQUIRED_HEADER",
    "TemplateClaim",
    "TransmissionWrapper",
    "element_path",
    "is_hl7v3",
    "local_name",
    "parse_hl7v3",
    "parse_hl7v3_fileset",
    "qualified_name",
    "xsi_type",
]

#: Header children a ``ClinicalDocument`` must carry for the importer to read it as one.
REQUIRED_HEADER: Tuple[str, ...] = (
    "id",
    "code",
    "effectiveTime",
    "recordTarget",
    "author",
    "custodian",
    "component",
)

_CDA = "{" + CDA_NAMESPACE + "}"
_XSI_TYPE = "{" + XSI_NAMESPACE + "}type"
_PREFIXES = {SDTC_NAMESPACE: "sdtc"}
_TRUNCATION_MESSAGES = ("no element found", "unclosed token")
# Text decoded from the wrong encoding (UTF-16 read as UTF-8) opens with NULs or replacement characters.
_ENCODING_FAULT_MARKERS = ("\x00", "\ufffd")
_ENCODING_WINDOW = 1024

# A root element in the v3 namespace: ``<ClinicalDocument xmlns="urn:hl7-org:v3"`` or a v3
# interaction such as ``<MCCI_IN000002UV01 xmlns="urn:hl7-org:v3"``. Checked on the first element only.
_ROOT_RE = re.compile(r"<(?:[A-Za-z_][\w.-]*:)?([A-Za-z_][\w.-]*)\b[^>]*?\burn:hl7-org:v3\b", re.S)
_FIRST_ELEMENT_RE = re.compile(r"<(?![?!])")
_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_SNIFF_WINDOW = 65536


class Hl7V3ParseError(ValueError):
    """Raised when text is not a readable HL7 v3 / CDA document.

    Attributes:
        code: The intake-taxonomy code naming the failure; ``None`` for an encoding fault, which
            the import pipeline's encoding rule names more precisely than the parser can.
    """

    def __init__(self, message: str, *, code: Optional[str]) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class TemplateClaim:
    """A ``templateId`` — what the document asserts the element conforms to.

    Attributes:
        path: Where the claim sits (``ClinicalDocument/component/structuredBody/component[2]/section``).
        root: The template OID.
        extension: The template version, when the claim names one.
    """

    path: str
    root: Optional[str]
    extension: Optional[str]


@dataclass(frozen=True)
class CdaEntry:
    """One ``entry`` of a section: the clinical statement it carries.

    Attributes:
        path: The entry's path.
        type_code: The entry's ``typeCode`` (``DRIV``, ``COMP``), when written.
        statement: The local name of the clinical statement (``observation``, ``act``, ``organizer``).
    """

    path: str
    type_code: Optional[str]
    statement: Optional[str]


@dataclass
class CdaSection:
    """A ``section`` of the structured body and the sections nested in it.

    Attributes:
        path: The section's path.
        code: The section ``code`` attributes (``code``, ``codeSystem``, ``displayName``, …).
        title: The section title.
        template_ids: The section's own template claims, as ``(root, extension)``.
        entries: The section's entries in document order.
        sections: Sections nested through ``component/section``.
    """

    path: str
    code: Dict[str, str] = field(default_factory=dict)
    title: Optional[str] = None
    template_ids: List[Tuple[Optional[str], Optional[str]]] = field(default_factory=list)
    entries: List[CdaEntry] = field(default_factory=list)
    sections: List["CdaSection"] = field(default_factory=list)


@dataclass(frozen=True)
class TransmissionWrapper:
    """The HL7 v3 transmission wrapper a fileset's CDA document arrived in.

    Attributes:
        interaction: The wrapper's root element (the interaction, ``MCCI_IN000002UV01``).
        interaction_id: The ``interactionId`` extension, when written.
        payload: The member path the wrapper's payload reference resolved to.
        payload_id: The ``(root, extension)`` of the document id the wrapper names, when it names one.
        payload_id_matches: Whether that id equals the CDA document's own ``id``; ``None`` when the
            wrapper names no document id.
    """

    interaction: str
    interaction_id: Optional[str]
    payload: str
    payload_id: Optional[Tuple[Optional[str], Optional[str]]]
    payload_id_matches: Optional[bool]


@dataclass
class CdaDocument:
    """A parsed CDA document.

    Attributes:
        root: The ``ClinicalDocument`` element.
        raw: The document text.
        source_label: The file name, when known.
        type_id: The ``typeId`` as ``(root, extension)`` (``POCD_HD000040``), when written.
        template_claims: Every ``templateId`` in document order.
        sections: The structured body's top-level sections.
        body: ``structuredBody`` or ``nonXMLBody``.
        transmission: The wrapper the document arrived in, for a fileset rooted at one.
    """

    root: ET.Element
    raw: str
    source_label: Optional[str]
    type_id: Optional[Tuple[Optional[str], Optional[str]]]
    template_claims: List[TemplateClaim]
    sections: List[CdaSection]
    body: Optional[str]
    transmission: Optional[TransmissionWrapper] = None


# ---------------------------------------------------------------------------
# Names and paths
# ---------------------------------------------------------------------------


def local_name(element: ET.Element) -> str:
    """The element's local name, without its namespace."""
    tag = element.tag if isinstance(element.tag, str) else ""
    return tag.rsplit("}", 1)[-1]


def qualified_name(element: ET.Element) -> str:
    """The element's name as written in CDA: local for the v3 namespace, ``sdtc:`` for SDTC.

    An element from any other namespace keeps its ``{namespace}local`` form, so it can never be
    mistaken for a v3 element of the same local name.
    """
    tag = element.tag if isinstance(element.tag, str) else ""
    if not tag.startswith("{"):
        return tag
    namespace, local = tag[1:].split("}", 1)
    if namespace == CDA_NAMESPACE:
        return local
    prefix = _PREFIXES.get(namespace)
    return f"{prefix}:{local}" if prefix else tag


def xsi_type(element: ET.Element) -> Optional[str]:
    """The local part of the element's ``xsi:type`` (``IVL_TS`` for ``xsi:type="IVL_TS"``)."""
    value = element.get(_XSI_TYPE)
    if not value:
        return None
    return value.rsplit(":", 1)[-1].strip() or None


def element_path(parent_path: str, parent: ET.Element, child: ET.Element) -> str:
    """The path of ``child`` under ``parent``: its name, indexed when the name repeats."""
    name = qualified_name(child)
    siblings = [item for item in parent if qualified_name(item) == name]
    if len(siblings) > 1:
        position = next(index for index, item in enumerate(siblings, start=1) if item is child)
        name = f"{name}[{position}]"
    return f"{parent_path}/{name}"


def _children(element: ET.Element, name: str) -> List[ET.Element]:
    return [child for child in element if isinstance(child.tag, str) and child.tag == _CDA + name]


def _child(element: ET.Element, name: str) -> Optional[ET.Element]:
    found = _children(element, name)
    return found[0] if found else None


def _ii(element: Optional[ET.Element]) -> Optional[Tuple[Optional[str], Optional[str]]]:
    if element is None:
        return None
    return (element.get("root"), element.get("extension"))


def _label(source_label: Optional[str]) -> str:
    return f" ({source_label})" if source_label else ""


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def _root_match(text: str) -> Optional[re.Match]:
    """Match the document's first element when it is declared in the v3 namespace."""
    # Comments before the root may hold markup of their own; only a bounded prefix is examined.
    text = _COMMENT_RE.sub("", text[:_SNIFF_WINDOW])
    start = _FIRST_ELEMENT_RE.search(text)
    if start is None:
        return None
    end = text.find(">", start.start())
    head = text[start.start() : end + 1 if end >= 0 else len(text)]
    return _ROOT_RE.match(head)


def is_hl7v3(text: str) -> Optional[str]:
    """Return the root element name when ``text`` opens with an element in the v3 namespace.

    Checks only the first element's start tag, so a truncated or malformed document is still
    claimed (the parser then names the fault). Never raises.

    Returns:
        ``ClinicalDocument``, the interaction name of a wrapper, or ``None``.
    """
    if not text or "urn:hl7-org:v3" not in text:
        return None
    try:
        match = _root_match(text)
    except (TypeError, ValueError):  # pragma: no cover - defensive, the sniffer never raises
        return None
    return match.group(1) if match else None


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def _parse_root(text: str, source_label: Optional[str]) -> ET.Element:
    """Parse XML safely, mapping parser messages onto intake codes."""
    head = text[:_ENCODING_WINDOW] if text else ""
    if any(marker in head for marker in _ENCODING_FAULT_MARKERS):
        # Code-less on purpose: the pipeline's encoding rule names this fault precisely.
        raise Hl7V3ParseError(
            f"Document{_label(source_label)} is not valid text in its declared encoding.", code=None
        )
    if text.strip() and not text.lstrip("\ufeff \t\r\n").startswith("<"):
        raise Hl7V3ParseError(
            f"Document{_label(source_label)} is not XML, so it cannot be an HL7 v3 document.",
            code="FORMAT_MISMATCH",
        )
    try:
        return parse_xml(text, source_label=source_label)
    except SecureXmlError as exc:
        message = str(exc)
        if exc.code not in (None, "INPUT_MALFORMED"):
            # A guard fired (DTD, entity, size, depth): its own code is the precise one.
            raise Hl7V3ParseError(message, code=exc.code) from exc
        truncated = any(marker in message for marker in _TRUNCATION_MESSAGES)
        raise Hl7V3ParseError(
            message + (" The document was truncated." if truncated else ""),
            code="INPUT_TRUNCATED" if truncated else "INPUT_MALFORMED",
        ) from exc


def _is_wrapper(root: ET.Element) -> bool:
    return root.tag.startswith(_CDA) and any(local_name(child) == "ControlActProcess" for child in root)


def _check_namespace(root: ET.Element, source_label: Optional[str]) -> None:
    if not (isinstance(root.tag, str) and root.tag.startswith(_CDA)):
        raise Hl7V3ParseError(
            f"Document{_label(source_label)} is not HL7 v3: its <{local_name(root)}> root is not in "
            f"the {CDA_NAMESPACE} namespace.",
            code="FORMAT_MISMATCH",
        )


def _template_claims(root: ET.Element) -> List[TemplateClaim]:
    claims: List[TemplateClaim] = []

    def visit(element: ET.Element, path: str) -> None:
        for child in element:
            if not isinstance(child.tag, str):
                continue
            child_path = element_path(path, element, child)
            if child.tag == _CDA + "templateId":
                claims.append(TemplateClaim(path, child.get("root"), child.get("extension")))
                continue
            visit(child, child_path)

    visit(root, local_name(root))
    return claims


def _section(element: ET.Element, path: str) -> CdaSection:
    code = _child(element, "code")
    title = _child(element, "title")
    section = CdaSection(
        path=path,
        code={key: value for key, value in (code.attrib.items() if code is not None else ()) if "}" not in key},
        title=(title.text or "").strip() or None if title is not None else None,
        template_ids=[_ii(item) for item in _children(element, "templateId")],  # type: ignore[misc]
    )
    for child in element:
        if not isinstance(child.tag, str):
            continue
        child_path = element_path(path, element, child)
        if child.tag == _CDA + "entry":
            statement = next((item for item in child if isinstance(item.tag, str)), None)
            section.entries.append(
                CdaEntry(
                    path=child_path,
                    type_code=child.get("typeCode"),
                    statement=None if statement is None else qualified_name(statement),
                )
            )
        elif child.tag == _CDA + "component":
            nested = _child(child, "section")
            if nested is not None:
                section.sections.append(_section(nested, f"{child_path}/section"))
    return section


def _body(root: ET.Element) -> Tuple[Optional[str], List[CdaSection]]:
    component = _child(root, "component")
    if component is None:
        return None, []
    structured = _child(component, "structuredBody")
    if structured is None:
        return ("nonXMLBody" if _child(component, "nonXMLBody") is not None else None), []
    base = "ClinicalDocument/component/structuredBody"
    sections: List[CdaSection] = []
    for child in _children(structured, "component"):
        nested = _child(child, "section")
        if nested is not None:
            sections.append(_section(nested, f"{element_path(base, structured, child)}/section"))
    return "structuredBody", sections


def _check_header(root: ET.Element, source_label: Optional[str]) -> None:
    missing = [name for name in REQUIRED_HEADER if _child(root, name) is None]
    if missing:
        raise Hl7V3ParseError(
            f"ClinicalDocument{_label(source_label)} is missing required header element(s): "
            f"{', '.join(missing)}.",
            code="INPUT_SEMANTIC_INVALID",
        )


def _check_narrative_references(root: ET.Element, source_label: Optional[str]) -> None:
    """Every ``reference value="#anchor"`` must point at an ``ID`` defined in the document."""
    anchors = {element.get("ID") for element in root.iter() if element.get("ID")}
    for element in root.iter(_CDA + "reference"):
        value = (element.get("value") or "").strip()
        if value.startswith("#") and value[1:] not in anchors:
            raise Hl7V3ParseError(
                f"ClinicalDocument{_label(source_label)} references narrative anchor {value!r}, "
                "but no element in the document carries that ID.",
                code="INPUT_REFERENCE_UNRESOLVED",
            )


def _read_document(root: ET.Element, text: str, source_label: Optional[str]) -> CdaDocument:
    _check_namespace(root, source_label)
    if local_name(root) != "ClinicalDocument":
        if _is_wrapper(root):
            raise Hl7V3ParseError(
                f"{local_name(root)}{_label(source_label)} is an HL7 v3 transmission wrapper; the CDA "
                "document it carries is a separate file. Upload both together (as an archive).",
                code="INPUT_REFERENCE_UNRESOLVED",
            )
        raise Hl7V3ParseError(
            f"Document{_label(source_label)} is HL7 v3 but its root is <{local_name(root)}>, not a "
            "<ClinicalDocument>; only CDA documents are read.",
            code="INPUT_SEMANTIC_INVALID",
        )
    _check_header(root, source_label)
    _check_narrative_references(root, source_label)
    body, sections = _body(root)
    return CdaDocument(
        root=root,
        raw=text,
        source_label=source_label,
        type_id=_ii(_child(root, "typeId")),
        template_claims=_template_claims(root),
        sections=sections,
        body=body,
    )


def parse_hl7v3(text: str, *, source_label: Optional[str] = None) -> CdaDocument:
    """Parse one CDA document.

    Args:
        text: The document text.
        source_label: The file name, used in error messages.

    Returns:
        The parsed document.

    Raises:
        Hl7V3ParseError: When the text is not a readable CDA document (see the module docstring
            for the codes).
    """
    return _read_document(_parse_root(text, source_label), text, source_label)


def _payload_references(wrapper: ET.Element) -> Iterator[str]:
    for element in wrapper.iter(_CDA + "reference"):
        value = (element.get("value") or "").strip()
        if value and not value.startswith("#"):
            yield value


def _document_id(wrapper: ET.Element) -> Optional[Tuple[Optional[str], Optional[str]]]:
    for element in wrapper.iter(_CDA + "document"):
        return _ii(_child(element, "id"))
    return None


def parse_hl7v3_fileset(
    members: Mapping[str, str], root_path: str, *, source_label: Optional[str] = None
) -> CdaDocument:
    """Parse a fileset rooted at a CDA document or at the transmission wrapper that carries one.

    Args:
        members: Every member's text, keyed by its relative POSIX path.
        root_path: The root member's path.
        source_label: A label for error messages; the root path when omitted.

    Returns:
        The CDA document, with :attr:`CdaDocument.transmission` set when the root is a wrapper.

    Raises:
        Hl7V3ParseError: When the root or its payload is unreadable, or the wrapper's payload
            reference names no member of the set (``INPUT_REFERENCE_UNRESOLVED``).
    """
    label = source_label or root_path
    text = members[root_path]
    root = _parse_root(text, label)
    _check_namespace(root, label)
    if local_name(root) == "ClinicalDocument" or not _is_wrapper(root):
        return _read_document(root, text, label)

    base = posixpath.dirname(root_path)
    for reference in _payload_references(root):
        candidate = posixpath.normpath(posixpath.join(base, reference))
        if candidate in members and candidate != root_path:
            document = parse_hl7v3(members[candidate], source_label=candidate)
            named = _document_id(root)
            own = _ii(_child(document.root, "id"))
            interaction = _child(root, "interactionId")
            document.transmission = TransmissionWrapper(
                interaction=local_name(root),
                interaction_id=None if interaction is None else interaction.get("extension"),
                payload=candidate,
                payload_id=named,
                payload_id_matches=None if named is None else named == own,
            )
            return document
    raise Hl7V3ParseError(
        f"Transmission wrapper {local_name(root)}{_label(label)} references no CDA document that is "
        "in the upload.",
        code="INPUT_REFERENCE_UNRESOLVED",
    )
