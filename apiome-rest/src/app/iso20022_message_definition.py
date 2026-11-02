"""ISO 20022 message definitions (XSD) on the ISO 20022 adapter — MFI-20.3 (#3987).

An ISO 20022 **message definition** is the XML Schema the standard publishes for one message —
``pain.001.001.09.xsd`` — whose ``targetNamespace`` is the message's namespace
(``urn:iso:std:iso:20022:tech:xsd:pain.001.001.09``) and whose one global element, ``Document``,
wraps the business element (``CstmrCdtTrfInitn``). The shipped adapter read **messages** (instances)
and inferred their schema; this module lets it read the **definition** itself, built on the XSD
reader and normalizer (MFI-EPIC-13) the way Connect builds on gRPC:

* :func:`declared_definition_id` recognises the schema by its target namespace and names the
  message definition it declares;
* :func:`parse_message_definition` parses it with :func:`app.xsd_parser.parse_xsd` and keeps the
  message id beside the schema in an :class:`Iso20022MessageDefinition`;
* :func:`normalize_message_definition` runs :class:`app.xsd_normalizer.XsdNormalizer` and
  re-labels the model as ``iso20022``, recording the message definition
  (``extras["iso20022_message_definition"]``: family, variant, version, root and business element)
  next to the message id, and the SEPA profile when the family is one (FMT-6.6).

The result is a schemas-only ``iso20022`` catalog item: the message's complex types become
record types (``Choice`` members read as optional fields, amounts as a ``value`` plus their
``Ccy``), its simple types become scalars and enums, and the item versions, diffs and lints like
any other. It carries no ``iso20022_tree``, so it cannot be written back out as a message; it
exports as a schema (XSD, JSON Schema …) instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

from .canonical_model import ApiIdentity, CanonicalApi
from .edi_dialect_profiles import PROFILE_EXTRAS_KEY
from .iso20022_sepa import parse_message_id, sepa_profile_extras
from .normalizer import normalize_ordering
from .xsd_normalizer import XsdNormalizer
from .xsd_parser import XsdDocument, parse_xsd

__all__ = [
    "Iso20022MessageDefinition",
    "declared_definition_id",
    "is_iso20022_message_definition",
    "normalize_message_definition",
    "parse_message_definition",
]

_FORMAT_KEY = "iso20022"

# The schema element (any prefix) carrying an ISO 20022 message namespace as its target.
_SCHEMA_RE = re.compile(r"<(?:[\w.-]+:)?schema\b[^>]*?\btargetNamespace\s*=\s*[\"']([^\"']+)[\"']", re.S)
_ISO20022_TARGET_RE = re.compile(r"^urn:iso:std:iso:20022:tech:xsd:([\w.]+)$", re.IGNORECASE)


@dataclass(frozen=True)
class Iso20022MessageDefinition:
    """A parsed ISO 20022 message definition.

    Attributes:
        message_id: The message-definition identifier the target namespace names
            (``pain.001.001.09``).
        namespace: The full target namespace.
        schema: The parsed XML Schema.
        raw: The schema text as imported.
    """

    message_id: str
    namespace: str
    schema: XsdDocument
    raw: str


def declared_definition_id(text: str) -> Optional[str]:
    """The message-definition identifier an XML Schema's target namespace declares, if any.

    Args:
        text: The document text.

    Returns:
        ``"pain.001.001.09"`` for a schema whose ``targetNamespace`` is
        ``urn:iso:std:iso:20022:tech:xsd:pain.001.001.09``; ``None`` for anything else — a message
        instance, a schema in another namespace, or no schema at all.
    """
    if not text or not isinstance(text, str):
        return None
    match = _SCHEMA_RE.search(text)
    if match is None:
        return None
    target = _ISO20022_TARGET_RE.match(match.group(1).strip())
    return target.group(1) if target else None


def is_iso20022_message_definition(text: str) -> bool:
    """Return ``True`` when *text* is an XML Schema in an ISO 20022 message namespace."""
    return declared_definition_id(text) is not None


def parse_message_definition(
    raw: str,
    *,
    source_label: Optional[str] = None,
    members: Optional[Mapping[str, str]] = None,
) -> Iso20022MessageDefinition:
    """Parse a message-definition schema.

    Args:
        raw: The schema text (``declared_definition_id`` must recognise it).
        source_label: Label for errors.
        members: The documents of a multi-file set, when the schema imports others.

    Returns:
        The definition with its message id and parsed schema.

    Raises:
        ValueError: When the text is not an ISO 20022 message definition.
        app.xsd_parser.XsdParseError, app.secure_xml.SecureXmlError: As :func:`parse_xsd` raises.
    """
    message_id = declared_definition_id(raw)
    if message_id is None:
        raise ValueError("Not an ISO 20022 message definition: no ISO 20022 target namespace")
    schema = parse_xsd(raw, source_label=source_label, members=members)
    namespace = schema.target_namespace or f"urn:iso:std:iso:20022:tech:xsd:{message_id}"
    return Iso20022MessageDefinition(message_id=message_id, namespace=namespace, schema=schema, raw=raw)


def _business_element(schema: XsdDocument) -> Dict[str, Optional[str]]:
    """The root element, its type, and the business element the root wraps with its type."""
    root_name = schema.root_element
    root_type = next((e.type_expr for e in schema.elements if e.name == root_name), None)
    root = next((t for t in schema.complex_types if t.name == root_type), None)
    business = next((f for f in root.fields if f.kind == "element"), None) if root else None
    return {
        "root_element": root_name,
        "root_type": root_type,
        "business_element": business.name if business else None,
        "business_type": business.type_expr if business else None,
    }


def normalize_message_definition(
    definition: Iso20022MessageDefinition, *, include_raw: bool = True
) -> CanonicalApi:
    """Normalize a message definition through the XSD normalizer and label it ``iso20022``.

    Args:
        definition: The parsed definition.
        include_raw: Whether the canonical ``raw`` bag keeps the schema text.

    Returns:
        The XSD normalizer's model with ``format = "iso20022"``, the message id as the identity's
        namespace, and the message-definition record (and SEPA profile, when one applies) in
        ``extras``.
    """
    api = XsdNormalizer().normalize(definition.schema, include_raw=include_raw)
    parts = parse_message_id(definition.message_id)
    structure = _business_element(definition.schema)
    title = f"{structure['business_element'] or structure['root_element'] or 'Document'} ({definition.message_id})"
    extras: Dict[str, Any] = dict(api.extras)
    extras.update(
        {
            "iso20022_message_id": definition.message_id,
            "iso20022_namespace": definition.namespace,
            "iso20022_message_definition": {
                "family": parts[0] if parts else None,
                "variant": parts[1] if parts else None,
                "version": parts[2] if parts else None,
                **structure,
            },
        }
    )
    if structure["business_element"]:
        extras["iso20022_business_element"] = structure["business_element"]
    sepa = sepa_profile_extras(definition.message_id)
    if sepa is not None:
        extras[PROFILE_EXTRAS_KEY] = sepa
    relabeled = api.model_copy(
        update={
            "format": _FORMAT_KEY,
            "identity": ApiIdentity(name=title, namespace=definition.message_id),
            "title": title,
            "extras": extras,
            "raw": {"iso20022": definition.raw} if include_raw else None,
        }
    )
    return normalize_ordering(relabeled)
