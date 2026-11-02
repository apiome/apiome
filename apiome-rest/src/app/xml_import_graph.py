"""The import graph of a WSDL or XSD description — MFI-13.1 (#3788).

A SOAP service or an XML Schema is rarely one file. A WSDL description pulls other descriptions in
with ``wsdl:import`` (WSDL 1.1 and 2.0) and ``wsdl:include`` (WSDL 2.0), and its schemas — like a
standalone XSD — pull further schemas in with ``xs:import``, ``xs:include``, ``xs:redefine`` and
``xs:override``. :func:`resolve_import_graph` follows every one of those references, transitively
and cycle-safely, against the documents of a multi-file set (an uploaded archive or a live fetch),
and returns the documents it reached in discovery order plus the references nothing answered.

**Where a location points.** A location is resolved the way a SOAP toolkit reads an unpacked
bundle: **relative to the directory of the document that declares it**
(:func:`resolve_bundle_path`), so ``../common/types.xsd`` from ``schemas/orders.xsd`` is
``common/types.xsd``. Two fallbacks keep the other ways members are keyed working:

1. the location exactly as written — a live fetch (:mod:`app.wsdl_fetch`) keys each document by
   the location its referrer wrote, which may be a URL or ``?xsd=xsd0``;
2. the bare file name, **only when exactly one member has it** — a flat upload of files that
   were laid out in folders. Two members with the same name are never guessed between.

Each document is visited once, keyed by the member it resolved to — not by the text of the
location — so the same relative location written in two folders reaches two documents. Nothing
here fails an import: an unresolved or unreadable reference is returned in
:attr:`XmlImportGraph.unresolved`, for lint (``wsi.unresolved-import``) to report.
"""

from __future__ import annotations

import posixpath
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Tuple

from .secure_xml import SecureXmlError, parse_xml

__all__ = [
    "KIND_SCHEMA",
    "KIND_WSDL",
    "ImportedDocument",
    "UnresolvedImport",
    "XmlImportGraph",
    "resolve_bundle_path",
    "resolve_member",
    "resolve_import_graph",
]

XSD_NS = "http://www.w3.org/2001/XMLSchema"
WSDL_1_1_NS = "http://schemas.xmlsoap.org/wsdl/"
WSDL_2_0_NS = "http://www.w3.org/ns/wsdl"

#: A document reached through an XSD reference (``xs:import`` / ``include`` / ``redefine`` /
#: ``override``) or through a WSDL one (``wsdl:import`` / ``wsdl:include``).
KIND_SCHEMA = "schema"
KIND_WSDL = "wsdl"

#: ``(namespace, local name) -> (location attribute, kind)`` for every reference followed.
_REFERENCES: Dict[Tuple[str, str], Tuple[str, str]] = {
    (XSD_NS, "import"): ("schemaLocation", KIND_SCHEMA),
    (XSD_NS, "include"): ("schemaLocation", KIND_SCHEMA),
    (XSD_NS, "redefine"): ("schemaLocation", KIND_SCHEMA),
    (XSD_NS, "override"): ("schemaLocation", KIND_SCHEMA),
    (WSDL_1_1_NS, "import"): ("location", KIND_WSDL),
    (WSDL_2_0_NS, "import"): ("location", KIND_WSDL),
    (WSDL_2_0_NS, "include"): ("location", KIND_WSDL),
}

#: Why a reference was not followed.
REASON_MISSING = "missing"
REASON_UNREADABLE = "unreadable"


@dataclass(frozen=True)
class ImportedDocument:
    """One document of the graph.

    Attributes:
        path: The member key it resolved to (the root's own path for the root).
        element: Its parsed root element.
        text: Its text, as the member holds it.
        kind: :data:`KIND_SCHEMA` or :data:`KIND_WSDL` — how it was reached (the root is reached
            as what its own root element is).
    """

    path: str
    element: ET.Element
    text: str
    kind: str


@dataclass(frozen=True)
class UnresolvedImport:
    """A reference nothing in the set answered.

    Attributes:
        declared_in: The path of the document that declares it.
        location: The location as written.
        reason: :data:`REASON_MISSING` (no member matches) or :data:`REASON_UNREADABLE` (the
            member is not well-formed, or is refused by :mod:`app.secure_xml`).
    """

    declared_in: str
    location: str
    reason: str

    def as_dict(self) -> Dict[str, str]:
        """The reference as ``{"declared_in", "location", "reason"}``."""
        return {"declared_in": self.declared_in, "location": self.location, "reason": self.reason}


@dataclass(frozen=True)
class XmlImportGraph:
    """Every document a description reaches, root first, and what it could not reach.

    Attributes:
        documents: The root, then each reached document in breadth-first discovery order.
        unresolved: The references nothing answered, in discovery order.
    """

    documents: Tuple[ImportedDocument, ...]
    unresolved: Tuple[UnresolvedImport, ...] = ()

    @property
    def root(self) -> ImportedDocument:
        """The document the graph was resolved from."""
        return self.documents[0]

    def imported(self) -> Tuple[ImportedDocument, ...]:
        """Every document but the root."""
        return self.documents[1:]

    def as_extras(self) -> Optional[Dict[str, object]]:
        """The graph as canonical-model ``extras``, or ``None`` when the root imports nothing.

        Returns:
            ``{"documents": [{"path", "kind"}...], "unresolved": [...]}`` — the root first — or
            ``None`` for a single self-contained document, so its model is unchanged.
        """
        if len(self.documents) == 1 and not self.unresolved:
            return None
        return {
            "documents": [{"path": document.path, "kind": document.kind} for document in self.documents],
            "unresolved": [reference.as_dict() for reference in self.unresolved],
        }


def resolve_bundle_path(base: str, location: str) -> Optional[str]:
    """Return ``location`` as a set path relative to the directory ``base``.

    Args:
        base: The directory of the declaring document (``""`` at the set's top level).
        location: The location as written.

    Returns:
        The normalized path, or ``None`` for a URL, an absolute path, a drive-qualified path, or
        one that climbs out of the set (``../outside.xsd`` from the top level).
    """
    if not location or "://" in location or location.startswith(("/", "\\")) or ":" in location.split("/")[0]:
        return None
    resolved = posixpath.normpath(posixpath.join(base, location))
    if resolved == ".." or resolved.startswith("../"):
        return None
    return resolved


def resolve_member(
    location: str,
    members: Mapping[str, str],
    *,
    declared_in: Optional[str] = None,
) -> Optional[Tuple[str, str]]:
    """Find the member a location names (see the module docstring for the order tried).

    Args:
        location: The location as written.
        members: Member key -> text.
        declared_in: The path of the declaring document; ``None`` resolves from the top level.

    Returns:
        ``(member key, text)``, or ``None`` when nothing in the set matches.
    """
    location = location.strip()
    if not location:
        return None
    relative = resolve_bundle_path(posixpath.dirname(declared_in or ""), location)
    if relative is not None and relative in members:
        return relative, members[relative]
    if location in members:
        return location, members[location]
    name = location.replace("\\", "/").rsplit("/", 1)[-1].split("?", 1)[0]
    if not name:
        return None
    matches = [key for key in members if key.replace("\\", "/").rsplit("/", 1)[-1] == name]
    if len(matches) == 1:
        return matches[0], members[matches[0]]
    return None


def _namespace(tag: str) -> Optional[str]:
    return tag[1:].split("}", 1)[0] if tag.startswith("{") else None


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _references(element: ET.Element) -> List[Tuple[str, str]]:
    """Every ``(location, kind)`` reference ``element``'s document declares, in document order."""
    found: List[Tuple[str, str]] = []
    for node in element.iter():
        if not isinstance(node.tag, str):
            continue
        namespace = _namespace(node.tag)
        if namespace is None:
            continue
        spec = _REFERENCES.get((namespace, _local(node.tag)))
        if spec is None:
            continue
        attribute, kind = spec
        location = (node.get(attribute) or "").strip()
        if location:
            found.append((location, kind))
    return found


def _root_kind(element: ET.Element) -> str:
    return KIND_SCHEMA if _local(element.tag) == "schema" else KIND_WSDL


def resolve_import_graph(
    root: ET.Element,
    *,
    root_text: str,
    root_path: Optional[str] = None,
    members: Optional[Mapping[str, str]] = None,
) -> XmlImportGraph:
    """Follow every import and include reachable from ``root``.

    Args:
        root: The parsed root element of the description or schema.
        root_text: Its text.
        root_path: Its member key in the set, which relative locations resolve from; ``None``
            (or a key the set does not hold, such as a URL) resolves from the top level.
        members: The set's documents, key -> text; ``None`` or empty for a single document,
            whose graph is the root alone (its references are not reported as unresolved —
            a single upload cannot carry them, and lint already says so).

    Returns:
        The graph. The root's own key is never followed back into, so an import cycle ends.
    """
    start = root_path or ""
    documents: List[ImportedDocument] = [ImportedDocument(start, root, root_text, _root_kind(root))]
    if not members:
        return XmlImportGraph(tuple(documents))

    unresolved: List[UnresolvedImport] = []
    visited = {start}
    queue = [documents[0]]
    while queue:
        current = queue.pop(0)
        for location, kind in _references(current.element):
            match = resolve_member(location, members, declared_in=current.path or None)
            if match is None:
                reference = UnresolvedImport(current.path, location, REASON_MISSING)
                if reference not in unresolved:
                    unresolved.append(reference)
                continue
            key, text = match
            if key in visited:
                continue
            visited.add(key)
            try:
                element = parse_xml(text, source_label=key)
            except SecureXmlError:
                unresolved.append(UnresolvedImport(current.path, location, REASON_UNREADABLE))
                continue
            document = ImportedDocument(key, element, text, kind)
            documents.append(document)
            queue.append(document)
    return XmlImportGraph(tuple(documents), tuple(unresolved))
