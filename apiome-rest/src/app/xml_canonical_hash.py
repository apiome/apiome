"""Canonical-XML hash of a WSDL or XSD description and its imports — MFI-13.1 (#3788).

The semantic version fingerprint (:mod:`app.fingerprint`) is taken over the canonical model. This
is the format's own identity alongside it: a SHA-256 over **Canonical XML 2.0** of every document
the description reaches (:mod:`app.xml_import_graph`), so the hash answers "is this the same set
of XML documents?" the way an XML toolchain would — after resolving all imports, and regardless of
how each file happens to be written.

Canonicalization (stdlib :func:`xml.etree.ElementTree.canonicalize`) makes the hash ignore:

* whitespace between elements and around text (``strip_text``);
* comments;
* attribute order and quoting;
* namespace **prefix** choice — prefixes are rewritten, including inside QName-valued attributes
  (``type="tns:Order"``), so ``xs:`` vs ``xsd:`` or ``tns:`` vs ``p:`` does not change it.

Anything else — a changed facet, an added element, an edited ``xs:documentation``, an edit to any
*imported* file — does. The root is hashed first under a fixed label (so uploading a description
alone or as the root of an archive gives the same hash), then every imported document in path
order, each prefixed by its path — so the hash does not depend on discovery order but does notice
an imported document moving or being renamed.

**Safety.** :func:`~xml.etree.ElementTree.canonicalize` parses the text again. It is only ever
called on text :func:`app.secure_xml.parse_xml` has already accepted (no DTD, no entities, within
size and depth limits), which is what every :class:`~app.xml_import_graph.ImportedDocument` is.
"""

from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from typing import Dict, Optional

from .canonical_model import CanonicalApi
from .fingerprint import FingerprintHasher
from .xml_import_graph import XmlImportGraph

__all__ = [
    "C14N_ALGORITHM",
    "WsdlCanonicalXmlHasher",
    "XsdCanonicalXmlHasher",
    "canonical_xml",
    "canonical_xml_sha256",
    "xml_provenance_extras",
]

#: Recorded beside the digest so a stored hash can be re-validated (and migrated) by algorithm.
C14N_ALGORITHM = "sha256-c14n2-v1"

#: Attributes whose values are QNames in WSDL 1.1 / 2.0 and XSD, so a prefix inside them is
#: rewritten with the element prefixes. ``memberTypes`` (a *list* of QNames) cannot be rewritten by
#: C14N 2.0 and is left as written.
_QNAME_ATTRIBUTES = frozenset(
    {
        "type",
        "base",
        "ref",
        "element",
        "message",
        "binding",
        "interface",
        "itemType",
        "substitutionGroup",
        "refer",
    }
)


def canonical_xml(text: str) -> str:
    """Return the Canonical XML 2.0 form of one document, prefixes and whitespace normalized.

    Args:
        text: Document text already accepted by :func:`app.secure_xml.parse_xml`.

    Returns:
        The canonical text.
    """
    return ET.canonicalize(
        text,
        strip_text=True,
        with_comments=False,
        rewrite_prefixes=True,
        qname_aware_attrs=_QNAME_ATTRIBUTES,
    )


def canonical_xml_sha256(graph: XmlImportGraph) -> Optional[str]:
    """Hash a description's documents in canonical form.

    Args:
        graph: The description's import graph (:func:`app.xml_import_graph.resolve_import_graph`).

    Returns:
        64 lowercase hex digits, or ``None`` when a document cannot be canonicalized (the import
        never fails over its format hash).
    """
    labelled = [("", graph.root.text)] + sorted(
        (document.path, document.text) for document in graph.imported()
    )
    digest = hashlib.sha256()
    try:
        for label, text in labelled:
            digest.update(label.encode("utf-8") + b"\0")
            digest.update(canonical_xml(text).encode("utf-8") + b"\0")
    except (ET.ParseError, ValueError):
        return None
    return digest.hexdigest()


def xml_provenance_extras(
    *,
    c14n_sha256: Optional[str],
    import_graph: Optional[Dict[str, object]],
    xsd_version: str,
) -> Dict[str, object]:
    """The canonical-model ``extras`` a WSDL or XSD import records about its documents.

    Args:
        c14n_sha256: The Canonical XML hash (:func:`canonical_xml_sha256`).
        import_graph: The import graph's extras form, or ``None`` for one self-contained file.
        xsd_version: ``1.0`` or ``1.1``.

    Returns:
        ``xml_c14n_sha256`` (with ``xml_c14n_algorithm``) when there is a hash,
        ``xml_import_graph`` when the description spans files, and ``xsd_version`` only when it
        is ``1.1`` — XSD 1.0 is what every schema meant before, so it adds nothing. Both
        ``xml_c14n_sha256`` and ``xml_import_graph`` are kept out of the version fingerprint
        (:data:`app.fingerprint.UNHASHED_EXTRAS`): whitespace or a renamed file mints no version.
    """
    extras: Dict[str, object] = {}
    if c14n_sha256:
        extras["xml_c14n_sha256"] = c14n_sha256
        extras["xml_c14n_algorithm"] = C14N_ALGORITHM
    if import_graph:
        extras["xml_import_graph"] = import_graph
    if xsd_version == "1.1":
        extras["xsd_version"] = xsd_version
    return extras


class _CanonicalXmlHasher(FingerprintHasher):
    """Expose a WSDL / XSD import's canonical-XML hash as ``FingerprintResult.format_hash``.

    Reads what the normalizer recorded (``extras["xml_c14n_sha256"]``), so it needs no re-parse;
    a model built without it yields ``None``.
    """

    algorithm = C14N_ALGORITHM

    def hash(self, api: CanonicalApi) -> Optional[str]:
        """Return the recorded canonical-XML SHA-256, or ``None``.

        Args:
            api: A WSDL or XSD canonical model.

        Returns:
            64 lowercase hex digits, or ``None``.
        """
        value = (api.extras or {}).get("xml_c14n_sha256")
        return value if isinstance(value, str) and value else None


class WsdlCanonicalXmlHasher(_CanonicalXmlHasher, register=True):
    """The canonical-XML hash of a WSDL description (1.1 or 2.0) and its imports."""

    format = "wsdl"


class XsdCanonicalXmlHasher(_CanonicalXmlHasher, register=True):
    """The canonical-XML hash of an XSD schema and its imports."""

    format = "xsd"
