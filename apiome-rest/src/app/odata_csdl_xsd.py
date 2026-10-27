"""OASIS OData CSDL XML schema (XSD) validation — MFI-11.4 (#3779).

:mod:`app.odata_csdl_schema` validates a v4 document as CSDL JSON — for CSDL XML, *after* the
OASIS XML → JSON mapping. That mapping reads only the attributes and elements CSDL defines, so
a misspelled attribute (``Nulable="false"``), a stray element or a missing required attribute
in the XML never reaches the JSON form and passes unseen. This module closes the gap by
validating v4 CSDL XML against the OASIS XML schemas themselves, vendored byte for byte so
validation is fully offline:

* ``data/odata_csdl_xsd/edmx.xsd`` — *OData EDMX XML Schema Version 4.01*, OASIS Standard,
  https://docs.oasis-open.org/odata/odata-csdl-xml/v4.01/os/schemas/edmx.xsd
* ``data/odata_csdl_xsd/edm.xsd`` — *OData EDM XML Schema Version 4.01*, OASIS Standard,
  https://docs.oasis-open.org/odata/odata-csdl-xml/v4.01/os/schemas/edm.xsd

  Copyright © OASIS Open 2020. All Rights Reserved. Distributed under the OASIS IPR Policy
  (https://www.oasis-open.org/policies-guidelines/ipr/), which permits copying and
  distributing the documents provided this notice is included.

The document is parsed by :func:`app.secure_xml.parse_xml` (DTD / entity / size / depth guards)
and the *parsed tree* is handed to ``xmlschema`` with every resource access blocked, so neither
the schemas nor a hostile instance (``xsi:schemaLocation``) can reach the network or disk.

Like the JSON-schema check, violations never refuse an import: they are recorded on the catalog
item and reported by the ``odata.csdl-xsd`` lint rule (:mod:`app.odata_lint`). v2/v3 documents
are not validated here: their schemas are Microsoft's ([MS-CSDL]), not OASIS's.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import xmlschema

from .odata_csdl_schema import MAX_REPORTED_VIOLATIONS, CsdlViolation
from .odata_csdl_versions import ODATA_V4_EDM_NS, ODATA_V4_EDMX_NS
from .secure_xml import parse_xml

__all__ = ["CSDL_XSD_DIR", "validate_csdl_xml"]

#: The vendored OASIS CSDL XML schemas.
CSDL_XSD_DIR = Path(__file__).resolve().parent / "data" / "odata_csdl_xsd"


@lru_cache(maxsize=1)
def _schema() -> xmlschema.XMLSchema10:
    """The EDMX schema with the EDM schema it imports (built once, from local files only)."""
    return xmlschema.XMLSchema10(
        str(CSDL_XSD_DIR / "edmx.xsd"),
        locations={ODATA_V4_EDM_NS: str(CSDL_XSD_DIR / "edm.xsd")},
        allow="sandbox",
    )


def _local(tag: str) -> str:
    """An element's local name (``{ns}Property`` → ``Property``)."""
    return tag.rpartition("}")[2]


def _path(element: Optional[ET.Element], parents: Dict[ET.Element, ET.Element]) -> str:
    """A CSDL-JSON-shaped pointer for an element: ``/Namespace/Type/Member``.

    A ``Schema`` contributes its namespace and a named element its name, so the path matches
    the ones the JSON-schema violations and the resolution issues use; an unnamed element
    (``Key``, ``PropertyRef``…) contributes its element name. The ``Edmx`` / ``DataServices``
    wrapper is left out.
    """
    segments: List[str] = []
    current = element
    while current is not None:
        local = _local(current.tag)
        if local in ("Edmx", "DataServices"):
            break
        name = current.get("Namespace") if local == "Schema" else current.get("Name")
        segments.append(name or local)
        current = parents.get(current)
    return "".join("/" + part.replace("~", "~0").replace("/", "~1") for part in reversed(segments))


def validate_csdl_xml(
    xml_text: str, *, source_label: Optional[str] = None
) -> Optional[Tuple[List[CsdlViolation], int]]:
    """Validate OData v4 CSDL XML against the OASIS EDMX / EDM XML schemas.

    Args:
        xml_text: The ``<edmx:Edmx>`` document.
        source_label: Label for parse errors.

    Returns:
        The first :data:`~app.odata_csdl_schema.MAX_REPORTED_VIOLATIONS` violations and the total
        count, or ``None`` when the document is not v4 CSDL XML (nothing to validate).

    Raises:
        app.secure_xml.SecureXmlError: When the text is not safe, well-formed XML.
    """
    root = parse_xml(xml_text, source_label=source_label)
    if root.tag != f"{{{ODATA_V4_EDMX_NS}}}Edmx":
        return None
    parents = {child: parent for parent in root.iter() for child in parent}
    resource = xmlschema.XMLResource(root, allow="none")
    violations: List[CsdlViolation] = []
    total = 0
    for error in _schema().iter_errors(resource, use_location_hints=False):
        total += 1
        if len(violations) < MAX_REPORTED_VIOLATIONS:
            element = error.elem if isinstance(error.elem, ET.Element) else None
            violations.append(CsdlViolation(path=_path(element, parents), message=str(error.reason or error.message)))
    return violations, total
