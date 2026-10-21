"""NCPDP → canonical model normalizer — FMT-6.8 (#5452).

Maps a parsed :class:`~app.ncpdp_parser.NcpdpDocument` into a
:class:`~app.canonical_model.CanonicalApi` of paradigm
:attr:`~app.canonical_model.ApiParadigm.DATA_SCHEMA` whose types are the document's own structure.

**SCRIPT** — instance inference over every message read:

.. code-block:: text

    Message        version · release · Header · Body
    Body           one optional field per transaction type observed (NewRx, RxFill, Status …)
    NewRx          Patient · Pharmacy · Prescriber · MedicationPrescribed …

One record type per element name, folded across every occurrence: an element with child elements or
attributes is a record, any other element a ``string`` field; an element that repeats under one
parent is a list, and a field missing from some occurrence of its parent is optional. Attributes are
fields marked ``ncpdp_xml: attribute``; the text of a record element is its ``value`` field.

**Telecom D.0** — the transmission's segment structure:

.. code-block:: text

    TelecomTransmission   header · patient · insurance · transactions: [Transaction]
    Transaction           one field per transaction-level segment observed (claim, pricing …)
    ClaimSegment          one string field per field id observed, named by its id (``D2``)

The header is a positional record (each field's columns in ``extras``); segment fields are named by
their two-character id and described by their data element when :data:`FIELD_LABELS` knows it.

No payload value enters the model — patient names, drug codes, quantities, identifiers and amounts
belong to the payload analysis, where the value-visibility policy governs them. ``extras`` records
structure: the sub-format, every message's (or transaction's) detected transaction type, the
version claimed, and for Telecom the declared versus observed transaction count.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

from .canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Type,
    TypeKind,
    TypeRef,
)
from .ncpdp_parser import SUB_FORMAT_SCRIPT, NcpdpDocument
from .ncpdp_script import ScriptDocument, element_children, local_name
from .ncpdp_telecom import (
    CLAIM_TRANSACTION_CODES,
    FIELD_LABELS,
    HEADER_LAYOUT,
    TelecomSegment,
    TelecomTransmission,
    segment_name,
)
from .normalizer import Keys, Normalizer, normalize_ordering

__all__ = [
    "NCPDP_SCRIPT_NAMESPACE",
    "NCPDP_TELECOM_NAMESPACE",
    "NcpdpNormalizer",
    "format_profile",
    "segment_field_name",
    "segment_type_name",
    "telecom_transaction_count",
]

_FORMAT_KEY = "ncpdp"
#: Namespace SCRIPT type keys are minted under.
NCPDP_SCRIPT_NAMESPACE = "NCPDP-SCRIPT"
#: Namespace Telecom type keys are minted under.
NCPDP_TELECOM_NAMESPACE = "NCPDP-Telecom"

_WORD_RE = re.compile(r"[A-Za-z0-9]+")


def segment_type_name(segment_id: str) -> str:
    """The record type name of a segment (``07`` → ``ClaimSegment``, ``05`` →
    ``CoordinationOfBenefitsOtherPaymentsSegment``, unnamed ``31`` → ``SegmentAM31``)."""
    words = _WORD_RE.findall(segment_name(segment_id))
    if words[:1] == ["Segment"]:
        return f"SegmentAM{segment_id}"
    return "".join(word[0].upper() + word[1:] for word in words) + "Segment"


def segment_field_name(segment_id: str) -> str:
    """The field a segment occupies on its container (``07`` → ``claim``, ``31`` → ``segmentAM31``)."""
    name = segment_type_name(segment_id)
    if name.endswith("Segment"):
        name = name[: -len("Segment")]
    return name[0].lower() + name[1:]


def telecom_transaction_count(transmission: TelecomTransmission) -> Dict[str, Any]:
    """The header's declared transaction count beside the transactions observed.

    Compared only for the claim transaction codes (B1/B2/B3), whose every transaction carries one
    claim segment; for the other codes the declaration is recorded and ``compared`` is false.

    Returns:
        ``{declared, observed, compared, consistent?}``.
    """
    declared = transmission.declared_transaction_count
    observed = len(transmission.transactions)
    compared = transmission.transaction_code in CLAIM_TRANSACTION_CODES and declared is not None
    result: Dict[str, Any] = {"declared": declared, "observed": observed, "compared": compared}
    if compared:
        result["consistent"] = declared == observed
    return result


def format_profile(document: NcpdpDocument) -> Dict[str, Any]:
    """The ``format_profile`` extras naming the sub-format read, lifted into provenance."""
    if document.sub_format == SUB_FORMAT_SCRIPT:
        assert document.script is not None
        versions = sorted({m.version_label for m in document.script.messages if m.version_label})
        return {
            "key": "ncpdp-script",
            "label": "NCPDP SCRIPT",
            "engine": _FORMAT_KEY,
            "evidence": [
                f"`<{document.script.root_name}>` root in the http://www.ncpdp.org/schema/SCRIPT namespace.",
                *[f"Version claimed: {version}." for version in versions],
            ],
            "implementation_guide_consulted": False,
        }
    assert document.telecom is not None
    return {
        "key": "ncpdp-telecom",
        "label": "NCPDP Telecommunication D.0",
        "engine": _FORMAT_KEY,
        "evidence": [
            f"Transaction header version/release `{document.telecom.version}`, transaction code "
            f"`{document.telecom.transaction_code}` ({document.telecom.transaction_name})."
        ],
        "implementation_guide_consulted": False,
    }


# ===========================================================================
# SCRIPT — instance inference
# ===========================================================================


@dataclass
class _FieldShape:
    """What every occurrence of one child name under one record type showed."""

    name: str
    xml: str  # attribute | element | text
    record: bool = False
    repeated: bool = False
    seen_in: int = 0


@dataclass
class _TypeShape:
    """One record type folded across every occurrence of its element name."""

    name: str
    instances: int = 0
    fields: Dict[str, _FieldShape] = field(default_factory=dict)


def _is_record(element: ET.Element) -> bool:
    return bool(element_children(element)) or any("}" not in key for key in element.attrib)


class _ScriptShapes:
    """Folds element occurrences into record-type shapes."""

    def __init__(self) -> None:
        self.types: Dict[str, _TypeShape] = {}

    def _field(self, shape: _TypeShape, name: str, xml: str) -> _FieldShape:
        found = shape.fields.get(name)
        if found is None:
            found = shape.fields[name] = _FieldShape(name=name, xml=xml)
        return found

    def visit(self, element: ET.Element) -> None:
        """Fold ``element`` into its type, and its record children into theirs."""
        name = local_name(element)
        shape = self.types.setdefault(name, _TypeShape(name=name))
        shape.instances += 1
        for key in element.attrib:
            if "}" in key:  # xsi:… and other qualified attributes are markup, not message fields
                continue
            self._field(shape, key, "attribute").seen_in += 1
        children = element_children(element)
        if not children and (element.text or "").strip():
            self._field(shape, "value", "text").seen_in += 1
        groups: Dict[str, List[ET.Element]] = {}
        for child in children:
            groups.setdefault(local_name(child), []).append(child)
        for child_name, items in groups.items():
            shape_field = self._field(shape, child_name, "element")
            shape_field.seen_in += 1
            shape_field.repeated = shape_field.repeated or len(items) > 1
            for item in items:
                if _is_record(item):
                    shape_field.record = True
                    self.visit(item)


def _script_key(name: str) -> str:
    return Keys.type(name, NCPDP_SCRIPT_NAMESPACE)


def _script_types(document: ScriptDocument) -> List[Type]:
    shapes = _ScriptShapes()
    for message in document.messages:
        shapes.visit(message.element)
    types: List[Type] = []
    for shape in shapes.types.values():
        type_key = _script_key(shape.name)
        fields: List[CanonicalField] = []
        for number, item in enumerate(shape.fields.values(), start=1):
            ref = TypeRef(name=_script_key(item.name) if item.record else "string", nullable=False)
            if item.repeated:
                ref = TypeRef(item=ref, nullable=False)
            if item.seen_in < shape.instances:
                ref = ref.model_copy(update={"nullable": True})
            fields.append(
                CanonicalField(
                    key=Keys.field(type_key, item.name),
                    name=item.name,
                    type=ref,
                    field_number=number,
                    extras={"ncpdp_xml": item.xml},
                )
            )
        types.append(
            Type(
                key=type_key,
                name=shape.name,
                kind=TypeKind.RECORD,
                fields=tuple(fields),
                extras={"ncpdp_kind": "element"},
            )
        )
    return types


def _script_transactions(document: ScriptDocument) -> List[Dict[str, Any]]:
    """Per message: where it sits, its transaction type and its header's linkage facts."""
    ids = {message.message_id for message in document.messages if message.message_id}
    out: List[Dict[str, Any]] = []
    for message in document.messages:
        entry: Dict[str, Any] = {
            "path": message.path,
            "transactionType": message.transaction_type,
            "recognized": message.recognized,
        }
        if message.message_id:
            entry["messageId"] = message.message_id
        if message.relates_to:
            entry["relatesToMessageId"] = message.relates_to
            entry["relatesToResolved"] = message.relates_to in ids
        if message.version_label:
            entry["version"] = message.version_label
        out.append(entry)
    return out


def _script_title(document: ScriptDocument) -> str:
    kinds: List[str] = []
    for message in document.messages:
        if message.transaction_type not in kinds:
            kinds.append(message.transaction_type)
    if len(kinds) == 1:
        return f"NCPDP SCRIPT {kinds[0]}"
    return f"NCPDP SCRIPT ({', '.join(kinds)})"


def _normalize_script(document: NcpdpDocument, *, include_raw: bool) -> CanonicalApi:
    script = document.script
    assert script is not None
    title = _script_title(script)
    transaction_types: List[str] = []
    for message in script.messages:
        if message.transaction_type not in transaction_types:
            transaction_types.append(message.transaction_type)
    return CanonicalApi(
        paradigm=ApiParadigm.DATA_SCHEMA,
        format=_FORMAT_KEY,
        identity=ApiIdentity(name=title, namespace=NCPDP_SCRIPT_NAMESPACE),
        title=title,
        types=_script_types(script),
        raw={"ncpdp": document.raw} if include_raw else None,
        extras={
            "ncpdp_sub_format": "script",
            "ncpdp_script": {
                "root": script.root_name,
                "messageCount": len(script.messages),
                "versions": sorted({m.version_label for m in script.messages if m.version_label}),
                "members": list(script.members),
            },
            "ncpdp_transaction_types": transaction_types,
            "ncpdp_transactions": _script_transactions(script),
            "format_profile": format_profile(document),
        },
    )


# ===========================================================================
# Telecom D.0 — segment structure
# ===========================================================================


def _telecom_key(name: str) -> str:
    return Keys.type(name, NCPDP_TELECOM_NAMESPACE)


def _container(name: str, fields: List[Tuple[str, str, bool, bool, str]], description: str) -> Type:
    """A structure-only record: ``(field, type name, repeated, optional, description)`` per field."""
    type_key = _telecom_key(name)
    out: List[CanonicalField] = []
    for number, (field_name, type_name, repeated, optional, text) in enumerate(fields, start=1):
        ref = TypeRef(name=_telecom_key(type_name), nullable=False)
        if repeated:
            ref = TypeRef(item=ref, nullable=False)
        if optional:
            ref = ref.model_copy(update={"nullable": True})
        out.append(
            CanonicalField(
                key=Keys.field(type_key, field_name),
                name=field_name,
                description=text,
                type=ref,
                field_number=number,
                extras={"ncpdp_kind": "structure"},
            )
        )
    return Type(
        key=type_key,
        name=name,
        kind=TypeKind.RECORD,
        description=description,
        fields=tuple(out),
        extras={"ncpdp_kind": "structure"},
    )


def _header_type() -> Type:
    type_key = _telecom_key("TransactionHeader")
    fields = tuple(
        CanonicalField(
            key=Keys.field(type_key, spec.name),
            name=spec.name,
            description=spec.label,
            type=TypeRef(name="string", nullable=False),
            field_number=number,
            extras={"ncpdp_position": [spec.start, spec.end], "ncpdp_length": spec.length},
        )
        for number, spec in enumerate(HEADER_LAYOUT, start=1)
    )
    return Type(
        key=type_key,
        name="TransactionHeader",
        kind=TypeKind.RECORD,
        description="The fixed 56-character request transaction header",
        fields=fields,
        extras={"ncpdp_kind": "header"},
    )


def _segment_types(segments: List[TelecomSegment]) -> List[Type]:
    """One record per segment id, its fields folded across every occurrence in first-seen order."""
    by_id: Dict[str, List[TelecomSegment]] = {}
    for segment in segments:
        by_id.setdefault(segment.segment_id, []).append(segment)
    types: List[Type] = []
    for segment_id, occurrences in by_id.items():
        type_key = _telecom_key(segment_type_name(segment_id))
        order: List[str] = []
        seen: Dict[str, int] = {}
        repeated: Dict[str, bool] = {}
        for segment in occurrences:
            counts: Dict[str, int] = {}
            for item in segment.fields:
                counts[item.field_id] = counts.get(item.field_id, 0) + 1
                if item.field_id not in order:
                    order.append(item.field_id)
            for field_id, count in counts.items():
                seen[field_id] = seen.get(field_id, 0) + 1
                repeated[field_id] = repeated.get(field_id, False) or count > 1
        fields: List[CanonicalField] = []
        for number, field_id in enumerate(order, start=1):
            ref = TypeRef(name="string", nullable=False)
            if repeated[field_id]:
                ref = TypeRef(item=ref, nullable=False)
            if seen[field_id] < len(occurrences):
                ref = ref.model_copy(update={"nullable": True})
            label = FIELD_LABELS.get(field_id)
            extras: Dict[str, Any] = {"ncpdp_field_id": field_id}
            if label:
                extras["ncpdp_data_element"] = label.split(" ", 1)[0]
            fields.append(
                CanonicalField(
                    key=Keys.field(type_key, field_id),
                    name=field_id,
                    description=label,
                    type=ref,
                    field_number=number,
                    extras=extras,
                )
            )
        types.append(
            Type(
                key=type_key,
                name=segment_type_name(segment_id),
                kind=TypeKind.RECORD,
                description=f"{segment_name(segment_id)} segment (AM{segment_id})",
                fields=tuple(fields),
                extras={"ncpdp_kind": "segment", "ncpdp_segment_id": f"AM{segment_id}"},
            )
        )
    return types


def _first_seen(segments: List[TelecomSegment]) -> List[str]:
    ids: List[str] = []
    for segment in segments:
        if segment.segment_id not in ids:
            ids.append(segment.segment_id)
    return ids


def _telecom_types(transmission: TelecomTransmission) -> List[Type]:
    root_fields: List[Tuple[str, str, bool, bool, str]] = [
        ("header", "TransactionHeader", False, False, "Fixed transaction header"),
    ]
    for segment_id in _first_seen(transmission.transmission_segments):
        count = sum(1 for s in transmission.transmission_segments if s.segment_id == segment_id)
        root_fields.append(
            (
                segment_field_name(segment_id),
                segment_type_name(segment_id),
                count > 1,
                False,
                f"{segment_name(segment_id)} segment (AM{segment_id})",
            )
        )
    types = [_header_type()]
    transaction_segments = [segment for group in transmission.transactions for segment in group]
    if transmission.transactions:
        root_fields.append(("transactions", "Transaction", True, False, "Transactions in transmission order"))
        transaction_fields: List[Tuple[str, str, bool, bool, str]] = []
        for segment_id in _first_seen(transaction_segments):
            per_group = [sum(1 for s in group if s.segment_id == segment_id) for group in transmission.transactions]
            transaction_fields.append(
                (
                    segment_field_name(segment_id),
                    segment_type_name(segment_id),
                    max(per_group) > 1,
                    min(per_group) == 0,
                    f"{segment_name(segment_id)} segment (AM{segment_id})",
                )
            )
        types.append(_container("Transaction", transaction_fields, "One transaction of the transmission"))
    types.insert(0, _container("TelecomTransmission", root_fields, "An NCPDP Telecommunication D.0 request"))
    types.extend(_segment_types(transmission.segments))
    return types


def _normalize_telecom(document: NcpdpDocument, *, include_raw: bool) -> CanonicalApi:
    transmission = document.telecom
    assert transmission is not None
    code = transmission.transaction_code
    title = f"NCPDP Telecom D.0 {code} ({transmission.transaction_name})"
    separators: List[str] = []
    for segment in transmission.segments:
        if segment.separator not in separators:
            separators.append(segment.separator)
    return CanonicalApi(
        paradigm=ApiParadigm.DATA_SCHEMA,
        format=_FORMAT_KEY,
        identity=ApiIdentity(name=title, namespace=NCPDP_TELECOM_NAMESPACE),
        title=title,
        types=_telecom_types(transmission),
        raw={"ncpdp": document.raw} if include_raw else None,
        extras={
            "ncpdp_sub_format": "telecom",
            "ncpdp_telecom": {
                "version": transmission.version,
                "transactionCode": code,
                "transactionName": transmission.transaction_name,
                "segments": [segment.tag for segment in transmission.segments],
                "separators": separators,
                "transactionCount": telecom_transaction_count(transmission),
            },
            "ncpdp_transaction_types": [code],
            "ncpdp_transactions": [
                {
                    "index": index,
                    "transactionType": code,
                    "transactionName": transmission.transaction_name,
                    "segments": [segment.tag for segment in group],
                }
                for index, group in enumerate(transmission.transactions, start=1)
            ],
            "format_profile": format_profile(document),
        },
    )


class NcpdpNormalizer(Normalizer, register=True):
    """Normalize a parsed NCPDP document into a :class:`CanonicalApi`."""

    format = _FORMAT_KEY
    paradigm = ApiParadigm.DATA_SCHEMA

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(source, NcpdpDocument):
            raise ValueError("NCPDP source must be an NcpdpDocument (see app.ncpdp_parser.parse_ncpdp)")
        if source.sub_format == SUB_FORMAT_SCRIPT:
            api = _normalize_script(source, include_raw=include_raw)
        else:
            api = _normalize_telecom(source, include_raw=include_raw)
        return normalize_ordering(api)
