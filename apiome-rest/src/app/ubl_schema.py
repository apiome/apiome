"""UBL 2.x document schemas (and Peppol BIS) on the XSD normalizer — MFI-20.5 (#3989).

OASIS **UBL** (Universal Business Language) publishes one XML Schema per business document —
``UBL-Invoice-2.1.xsd``, ``UBL-CreditNote-2.1.xsd``, ``UBL-Order-2.1.xsd`` … — whose
``targetNamespace`` names the document and the major version
(``urn:oasis:names:specification:ubl:schema:xsd:Invoice-2``), and whose ``schema`` element carries
the release (``version="2.1"``). Each document schema imports the shared component libraries —
the aggregate components (``CommonAggregateComponents-2``, ``cac:``) and the basic components
(``CommonBasicComponents-2``, ``cbc:``) — so a UBL schema is imported as a multi-file XSD set.

**Peppol BIS** e-invoicing (Peppol BIS Billing 3.0, the EN 16931 profile EU mandates build on)
defines no schema of its own: a Peppol invoice or credit note *is* a UBL 2.1 ``Invoice`` /
``CreditNote`` document, constrained by Peppol's Schematron business rules. So the UBL 2.1 Invoice
and CreditNote schemas are the Peppol document definitions, and this module says so; the Peppol
rules themselves import as a Schematron item (``bring-in/schematron-import``).

The schema imports as ``xsd`` — it versions, diffs, lints and exports like any other XML Schema —
and :func:`ubl_extras` adds what makes it a UBL document definition to the model's ``extras``:

* ``ubl_document`` — the document type, the namespace, the major version, the release and whether
  it is a document or a component library;
* ``format_profile`` — the ``ubl`` profile with its evidence, which the import lifts into the
  revision's provenance (``format_metadata.formatProfile``), noting Peppol BIS Billing 3.0 for an
  Invoice or CreditNote at 2.1.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .edi_dialect_profiles import PROFILE_EXTRAS_KEY

__all__ = [
    "PEPPOL_BIS_BILLING",
    "PEPPOL_DOCUMENT_TYPES",
    "UBL_COMPONENT_LIBRARIES",
    "UBL_PROFILE_KEY",
    "ubl_document_type",
    "ubl_extras",
]

#: The ``format_profile`` key of a UBL document schema.
UBL_PROFILE_KEY = "ubl"

#: The Peppol specification whose documents are UBL 2.1 Invoices and CreditNotes.
PEPPOL_BIS_BILLING = "Peppol BIS Billing 3.0"

#: The UBL document types Peppol BIS Billing 3.0 uses.
PEPPOL_DOCUMENT_TYPES = frozenset({"Invoice", "CreditNote"})

#: The UBL namespaces that are shared component libraries rather than business documents.
UBL_COMPONENT_LIBRARIES = frozenset(
    {
        "CommonAggregateComponents",
        "CommonBasicComponents",
        "CommonExtensionComponents",
        "CommonSignatureComponents",
        "QualifiedDataTypes",
        "UnqualifiedDataTypes",
        "SignatureAggregateComponents",
        "SignatureBasicComponents",
    }
)

#: A UBL schema namespace: the document (or library) name and the major version.
_UBL_NAMESPACE_RE = re.compile(r"^urn:oasis:names:specification:ubl:schema:xsd:([A-Za-z]+)-(\d+)$")

#: The ``version`` attribute of the (first) ``schema`` element, any prefix.
_SCHEMA_VERSION_RE = re.compile(r"<(?:[\w.-]+:)?schema\b[^>]*?\bversion\s*=\s*[\"']([^\"']+)[\"']", re.S)


def ubl_document_type(target_namespace: Optional[str]) -> Optional[tuple[str, str]]:
    """The UBL document (or component library) name and major version a namespace declares.

    Args:
        target_namespace: A schema's ``targetNamespace``.

    Returns:
        ``("Invoice", "2")`` for ``urn:oasis:names:specification:ubl:schema:xsd:Invoice-2``;
        ``None`` for any namespace that is not a UBL schema namespace.
    """
    match = _UBL_NAMESPACE_RE.match((target_namespace or "").strip())
    return (match.group(1), match.group(2)) if match else None


def ubl_extras(target_namespace: Optional[str], raw: str) -> Dict[str, Any]:
    """The extras that label a UBL schema, or ``{}`` for any other schema.

    Args:
        target_namespace: The root schema's ``targetNamespace``.
        raw: The root schema's text, for its ``version`` attribute.

    Returns:
        ``{"ubl_document": {...}, "format_profile": {...}}`` for a UBL schema, else ``{}``.
    """
    declared = ubl_document_type(target_namespace)
    if declared is None:
        return {}
    name, major = declared
    match = _SCHEMA_VERSION_RE.search(raw or "")
    version = match.group(1).strip() if match else None
    kind = "component-library" if name in UBL_COMPONENT_LIBRARIES else "document"
    peppol = kind == "document" and name in PEPPOL_DOCUMENT_TYPES and version == "2.1"

    evidence: List[str] = [f"targetNamespace {target_namespace}"]
    if version:
        evidence.append(f"schema version {version}")
    profile: Dict[str, Any] = {
        "key": UBL_PROFILE_KEY,
        "label": f"UBL {version or major}",
        "engine": "xsd",
        "evidence": evidence,
        "document_type": name,
        "implementation_guide_consulted": False,
    }
    if peppol:
        profile["peppol"] = PEPPOL_BIS_BILLING
    return {
        "ubl_document": {
            "document_type": name,
            "kind": kind,
            "namespace": target_namespace,
            "major_version": major,
            "version": version,
            "peppol": PEPPOL_BIS_BILLING if peppol else None,
        },
        PROFILE_EXTRAS_KEY: profile,
    }
