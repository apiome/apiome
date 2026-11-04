"""ISO 20022 message profile for the XSD export — MFX-22.4 (#4135).

The XSD emitter (:mod:`app.xsd_emitter`, MFX-22.1) writes any model's types as an XML Schema. With
``profile="iso20022"`` it writes them as an **ISO 20022 message definition** instead — the schema shape the
standard publishes for one message (``pain.001.001.09.xsd``) and that the ISO 20022 importer reads back
(:mod:`app.iso20022_message_definition`):

* **Message identifier.** ``<business area>.<message number>.<variant>.<version>`` (``pain.001.001.09``),
  from the ``message_identifier`` option, else the one an ISO 20022 source declares. The schema's
  ``targetNamespace`` is ``urn:iso:std:iso:20022:tech:xsd:<identifier>`` and the file is
  ``<identifier>.xsd``. With no identifier one is synthesized (``<area>.001.001.01``, the area from
  ``business_area`` or ``xxxx``) and reported as ``SYNTH``.
* **Document root.** The schema's one global element is ``Document``, whose ``complexType Document`` wraps
  the **business element** — the message type (``message_type``, else the one record no other record uses)
  as an element named after it (``CustomerCreditTransferInitiation``). An ISO 20022 source keeps its own
  ``Document`` and business element. Everything else is a message component (``complexType``) or a data
  type (``simpleType``) in the one message namespace.
* **Names.** Every type and element name is ISO 20022's UpperCamelCase, ASCII letters and digits only
  (:func:`iso20022_name`): ``customer_id`` → ``CustomerId``. A name with characters ISO 20022 names cannot
  hold is reported ``APPROX``; a name with nothing to keep is invented and reported ``SYNTH``. An ISO 20022
  source keeps its own names (the standard's, such as ``ActiveOrHistoricCurrencyAndAmount_SimpleType``).
* **Documentation.** Each type's and field's description is its ``xs:annotation`` / ``xs:documentation``
  (the shared writer, :mod:`app.xsd_schema`); ``Document`` is documented with the message it carries.
* **Message catalog.** A manifest, :data:`MESSAGE_CATALOG_PATH`, lists the message: its identifier, business
  area, namespace, schema file, root and business elements, and its message components and data types.

Every convention the source cannot meet is recorded on the writer's :class:`~app.emitter.LossTracker`, and the
XSD fidelity pack reports it with the subject's verdict (:data:`SYNTHESIZED_SUBJECTS` → ``SYNTH``, everything
else → ``APPROX``).
"""

from __future__ import annotations

import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple

from .canonical_model import CanonicalApi, Type, TypeKind
from .emitter import LossKind, LossTracker
from .iso20022_sepa import parse_message_id
from .xsd_schema import XSD_NS, XsdSchemaWriter, annotate
from .xsd_types import is_ncname

__all__ = [
    "BUSINESS_AREA_RE",
    "DOCUMENT",
    "ISO20022_NAMESPACE_PREFIX",
    "MESSAGE_CATALOG_PATH",
    "MESSAGE_IDENTIFIER_RE",
    "SYNTHESIZED_SUBJECTS",
    "Iso20022Message",
    "Iso20022SchemaWriter",
    "iso20022_name",
    "message_catalog",
    "resolve_message",
    "unused_records",
]

#: The namespace every ISO 20022 message definition is in, before its identifier.
ISO20022_NAMESPACE_PREFIX = "urn:iso:std:iso:20022:tech:xsd:"
#: The root element (and its type) of every ISO 20022 message.
DOCUMENT = "Document"
#: The message-catalog manifest written beside the schema.
MESSAGE_CATALOG_PATH = "message-catalog.json"
#: ``pain.001.001.09``: a business area, then the message number, variant and version.
MESSAGE_IDENTIFIER_RE = re.compile(r"^[a-z]{4}\.\d{3}\.\d{3}\.\d{2}$")
#: ``pain``, ``pacs``, ``camt`` …: four lower-case letters.
BUSINESS_AREA_RE = re.compile(r"^[a-z]{4}$")
#: The area a synthesized identifier uses when ``business_area`` is not given.
_PLACEHOLDER_AREA = "xxxx"

#: Loss subjects the fidelity pack reports as ``SYNTH`` — the export invents what the source lacks.
SYNTHESIZED_SUBJECTS: FrozenSet[str] = frozenset(
    {"iso20022-message-id-synthesized", "iso20022-document-root", "iso20022-name-synthesized"}
)

_ISO_NAME = re.compile(r"^[A-Z][A-Za-z0-9]*$")
_ASCII_WORD = re.compile(r"[A-Za-z0-9]+")


def iso20022_name(raw: Optional[str], fallback: str) -> Tuple[str, str]:
    """Write a source name as an ISO 20022 name: UpperCamelCase, ASCII letters and digits only.

    Args:
        raw: The source name (``customer_id``, ``GrpHdr``, ``größe`` …).
        fallback: The name to use when ``raw`` keeps nothing (``Type``, ``Field``).

    Returns:
        ``(name, how)``. ``how`` is ``"kept"`` (already conventional), ``"recased"`` (only case and
        separators changed: ``customer_id`` → ``CustomerId``), ``"lossy"`` (characters an ISO 20022 name
        cannot hold were dropped or replaced: ``größe`` → ``Groe``, ``2xx`` → ``X2xx``) or ``"synthesized"``
        (nothing was left: ``fallback``).
    """
    text = raw or ""
    if _ISO_NAME.match(text):
        return text, "kept"
    # Accents come off (é → e); a letter with no ASCII form (ß, 名) is dropped, and the name is then lossy.
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    lossy = any(ch.isalnum() and not ch.isascii() for ch in text)
    words = _ASCII_WORD.findall(ascii_text)
    if not words:
        return fallback, "synthesized"
    name = "".join(word[:1].upper() + word[1:] for word in words)
    if name[0].isdigit():
        return f"X{name}", "lossy"
    return name, "lossy" if lossy else "recased"


@dataclass
class Iso20022Message:
    """The message an ISO 20022 export describes.

    Attributes:
        identifier: ``pain.001.001.09``.
        business_area: ``pain``.
        synthesized_identifier: Whether the identifier was invented (no option and no ISO 20022 source).
        message_type: The key of the type the ``Document`` wraps, or ``None`` when the model has no record.
        business_element: The element ``Document`` wraps it in (``CstmrCdtTrfInitn``).
        source_document: The key of an ISO 20022 source's own ``Document`` type, written as it is.
        candidates: The record types that could be the message (none uses another), when more than one.
    """

    identifier: str
    business_area: str
    synthesized_identifier: bool
    message_type: Optional[str]
    business_element: Optional[str]
    source_document: Optional[str] = None
    candidates: List[str] = field(default_factory=list)

    @property
    def namespace(self) -> str:
        """``urn:iso:std:iso:20022:tech:xsd:pain.001.001.09``."""
        return f"{ISO20022_NAMESPACE_PREFIX}{self.identifier}"

    @property
    def schema_path(self) -> str:
        """``pain.001.001.09.xsd``."""
        return f"{self.identifier}.xsd"


def resolve_message(
    api: CanonicalApi,
    *,
    message_identifier: Optional[str],
    business_area: Optional[str],
    message_type: Optional[str],
) -> Iso20022Message:
    """Decide the message an export describes: its identifier, its message type and its business element.

    Args:
        api: The model being exported.
        message_identifier: The ``message_identifier`` option (already validated), or ``None``.
        business_area: The ``business_area`` option (already validated), or ``None``.
        message_type: The ``message_type`` option: a type name or key, or ``None``.

    Returns:
        The resolved message. The identifier is the option's, else an ISO 20022 source's, else synthesized.

    Raises:
        ValueError: When ``message_type`` names no record type of the model.
    """
    extras = api.extras or {}
    source_identifier = extras.get("iso20022_message_id")
    if message_identifier:
        identifier, synthesized = message_identifier, False
    elif isinstance(source_identifier, str) and MESSAGE_IDENTIFIER_RE.match(source_identifier.lower()):
        identifier, synthesized = source_identifier.lower(), False
    else:
        identifier, synthesized = f"{business_area or _PLACEHOLDER_AREA}.001.001.01", True
    area = identifier.split(".", 1)[0]

    records = [t for t in api.types if t.kind is TypeKind.RECORD]
    by_name = {t.name: t for t in api.types}
    definition = extras.get("iso20022_message_definition") or {}
    source_document = by_name.get(str(definition.get("root_type") or ""))
    if source_document is not None and source_document.kind is not TypeKind.RECORD:
        source_document = None

    if message_type:
        chosen = next((t for t in records if message_type in (t.key, t.name)), None)
        if chosen is None:
            raise ValueError(f"message_type {message_type!r} names no record type of this item")
        candidates: List[Type] = []
    elif source_document is not None and by_name.get(str(definition.get("business_type") or "")) is not None:
        chosen, candidates = by_name[str(definition["business_type"])], []
    else:
        # The one record no other record uses; an ISO 20022 source's Document is not a candidate.
        candidates = [t for t in unused_records(api, records) if source_document is None or t is not source_document]
        chosen = (candidates or records or [None])[0]

    business_element = None
    if source_document is not None and chosen is not None and chosen.name == definition.get("business_type"):
        business_element = definition.get("business_element")
    elif chosen is not None:
        business_element = iso20022_name(_message_stem(chosen.name), "Message")[0]
    if source_document is not None and (chosen is None or chosen.name != definition.get("business_type")):
        source_document = None  # a different message type was asked for: write a new Document
    return Iso20022Message(
        identifier=identifier,
        business_area=area,
        synthesized_identifier=synthesized,
        message_type=chosen.key if chosen is not None else None,
        business_element=business_element,
        source_document=source_document.key if source_document is not None else None,
        candidates=[t.key for t in candidates] if len(candidates) > 1 else [],
    )


def unused_records(api: CanonicalApi, records: List[Type]) -> List[Type]:
    """The record types no field of another record refers to — the candidates for the message (or document) type.

    Shared with the UBL profile (:mod:`app.ubl_xsd_profile`, MFX-24.6).
    """
    used: Set[str] = set()

    def walk(ref: Any) -> None:
        while ref is not None:
            if ref.name:
                used.add(ref.name)
            ref = ref.item

    for type_ in api.types:
        for field_ in type_.fields:
            if type_.key != field_.type.name:
                walk(field_.type)
        for member in type_.union_members:
            used.add(member)
        if type_.aliased is not None:
            walk(type_.aliased)
        walk(type_.value_type)
    return [t for t in records if t.key not in used and t.name not in used]


def _message_stem(name: str) -> str:
    """A message type's name without a trailing ``Type`` / ``V09`` version: the business element's name."""
    stem = re.sub(r"(?:_?V\d+|Type)$", "", name or "")
    return stem or name


class Iso20022SchemaWriter(XsdSchemaWriter):
    """The shared XSD writer with ISO 20022 names: UpperCamelCase, ASCII letters and digits only.

    Each name is converted by :func:`iso20022_name`; :meth:`rename` reports a recased name as the usual
    (cosmetic) ``renamed-identifier``, a name that lost characters as ``iso20022-name-unmappable`` and an
    invented one as ``iso20022-name-synthesized``. An ISO 20022 source's names are the standard's own and are
    kept whenever they are legal XML names.
    """

    def __init__(self, api: CanonicalApi, **kwargs: Any) -> None:
        #: Source name → how :func:`iso20022_name` converted it (set before the base names the types).
        self._how: Dict[str, str] = {}
        #: Whether the model came from ISO 20022, whose names are kept.
        self._iso_source = api.format == "iso20022"
        super().__init__(api, **kwargs)

    def legal_name(self, raw: str, *, pascal: bool = False, fallback: str = "item") -> str:
        """``raw`` as an ISO 20022 name (``pascal`` does not apply: every ISO 20022 name is UpperCamelCase)."""
        if self._iso_source and is_ncname(raw):
            self._how[raw] = "kept"
            return raw
        name, how = iso20022_name(raw, fallback[:1].upper() + fallback[1:])
        self._how[raw] = how
        return name

    def structural_name(self, name: str) -> str:
        """``Item``, ``Entry``, ``Key``, ``Value`` (an ISO 20022 source keeps the default names)."""
        return name if self._iso_source else name[:1].upper() + name[1:]

    def rename(self, source: Optional[str], emitted: str, pointer: str, noun: str) -> str:
        """Report ``source`` → ``emitted`` by how far the name had to move to meet the convention."""
        how = self._how.get(source or "", "recased")
        if source == emitted:
            return emitted
        if how == "synthesized":
            self.losses.record(
                LossKind.INFERRED,
                "iso20022-name-synthesized",
                f"ISO 20022 {noun} names are UpperCamelCase letters and digits; {source!r} has none to keep, so "
                f"the export names it {emitted!r}.",
                pointer=pointer,
            )
        elif how == "lossy":
            self.losses.record(
                LossKind.INFERRED,
                "iso20022-name-unmappable",
                f"ISO 20022 {noun} names use only the letters A–Z and a–z and digits, starting with a capital; "
                f"{source!r} cannot be written as it is and is written as {emitted!r}.",
                pointer=pointer,
            )
        else:
            self.losses.record(
                LossKind.INFERRED,
                "renamed-identifier",
                f"ISO 20022 {noun} names are UpperCamelCase; {source!r} is written as {emitted!r}.",
                pointer=pointer,
            )
        return emitted


def record_message_losses(api: CanonicalApi, message: Iso20022Message, losses: LossTracker) -> None:
    """Record what the export had to choose or invent about the message itself (filed at the root).

    Args:
        api: The model being exported.
        message: The resolved message.
        losses: Where the deviations are recorded.
    """
    if message.synthesized_identifier:
        losses.record(
            LossKind.INFERRED,
            "iso20022-message-id-synthesized",
            f"The item names no ISO 20022 message identifier, so the export uses {message.identifier!r} "
            f"(namespace {message.namespace}). Set message_identifier (for example 'pain.001.001.09') to "
            "name the message.",
            pointer="",
        )
    if message.message_type is None:
        losses.record(
            LossKind.NA,
            "iso20022-no-message",
            "The item has no record type to carry as the message, so Document wraps nothing.",
            pointer="",
        )
    elif message.source_document is None:
        type_name = next((t.name for t in api.types if t.key == message.message_type), message.message_type)
        losses.record(
            LossKind.INFERRED,
            "iso20022-document-root",
            f"ISO 20022 messages have one root element, Document; the export adds it, wrapping {type_name!r} as "
            f"the business element {message.business_element!r}.",
            pointer="",
        )
    if message.candidates:
        names = ", ".join(next((t.name for t in api.types if t.key == key), key) for key in message.candidates)
        losses.record(
            LossKind.INFERRED,
            "iso20022-message-type-inferred",
            f"Several record types could be the message ({names}); the export uses the first. Set message_type "
            "to choose another.",
            pointer="",
        )
    other = sorted({
        t.namespace for t in api.types
        if t.namespace and ":" in t.namespace and t.namespace != message.namespace
        and not (api.format == "iso20022" and t.namespace.startswith(ISO20022_NAMESPACE_PREFIX))
    })
    for namespace in other:
        losses.record(
            LossKind.INFERRED,
            "iso20022-namespace-merged",
            f"An ISO 20022 message definition is one namespace; the types of {namespace} are written in "
            f"{message.namespace}.",
            pointer="",
        )


def append_document(
    schema_el: ET.Element, writer: XsdSchemaWriter, message: Iso20022Message, title: Optional[str]
) -> None:
    """Put the ``Document`` element (and, unless the source has its own, its type) first in the schema.

    Args:
        schema_el: The message's schema document, with its types already written.
        writer: The writer that wrote them (for the business type's reference).
        message: The resolved message.
        title: The item's title, for the documentation.
    """
    element = ET.Element(ET.QName(XSD_NS, "element"), {"name": DOCUMENT, "type": writer.qualified(
        DOCUMENT, message.namespace)})
    annotate(element, f"ISO 20022 message {message.identifier}" + (f": {title}" if title else ""))
    schema_el.insert(0, element)
    if message.source_document is not None:
        return
    complex_el = ET.Element(ET.QName(XSD_NS, "complexType"), {"name": DOCUMENT})
    sequence = ET.SubElement(complex_el, ET.QName(XSD_NS, "sequence"))
    if message.message_type is not None and message.business_element:
        ET.SubElement(
            sequence,
            ET.QName(XSD_NS, "element"),
            {"name": message.business_element, "type": writer.type_ref(message.message_type)},
        )
    schema_el.insert(1, complex_el)


def message_catalog(api: CanonicalApi, writer: XsdSchemaWriter, message: Iso20022Message) -> str:
    """The message-catalog manifest: what the export holds, for a reader that wants it without the XSD.

    Args:
        api: The model exported.
        writer: The writer that wrote it (for the names the types were written under).
        message: The resolved message.

    Returns:
        The manifest as indented JSON.
    """
    parts = parse_message_id(message.identifier)
    components: List[str] = []
    data_types: List[str] = []
    for type_ in api.types:
        name = writer.type_names.get(type_.key)
        if name is None or type_.key == message.source_document:
            continue
        (data_types if writer.is_simple(type_) else components).append(name)
    entry: Dict[str, Any] = {
        "message_identifier": message.identifier,
        "business_area": message.business_area,
        "message_number": message.identifier.split(".")[1],
        "variant": parts[1] if parts else None,
        "version": message.identifier.split(".")[3],
        "identifier_synthesized": message.synthesized_identifier,
        "namespace": message.namespace,
        "schema": message.schema_path,
        "root_element": DOCUMENT,
        "business_element": message.business_element,
        "message_type": writer.type_names.get(message.message_type) if message.message_type else None,
        "title": api.title or api.identity.name,
        "description": api.description,
        "message_components": sorted(components),
        "data_types": sorted(data_types),
    }
    return json.dumps({"standard": "ISO 20022", "messages": [entry]}, indent=2, ensure_ascii=False) + "\n"
