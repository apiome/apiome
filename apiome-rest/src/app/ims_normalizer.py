"""IMS DBD / PSB → canonical model normalizer — FMT-11.2 (#5482).

Maps a parsed :class:`~app.ims_parser.ImsDocument` onto the **data_schema** paradigm:

.. code-block:: text

    DBD NAME=CUSTDB                          → identity CUSTDB, namespace ims
    SEGM NAME=CUSTOMER,PARENT=0,BYTES=200    → RECORD ims.CUSTDB.CUSTOMER (the root)
      FIELD NAME=(CUSTID,SEQ,U),BYTES=10,…   →   field CUSTID: string ≤ 10, offset 0, sequence (unique)
    SEGM NAME=ORDER,PARENT=CUSTOMER          → RECORD ims.CUSTDB.ORDER, and on CUSTOMER the field
                                               ORDER: list of ims.CUSTDB.ORDER (its occurrences)
    PCB DBDNAME=CUSTDB,PROCOPT=G (PSB P)     → RECORD ims.P.<pcb>.CUSTOMER … — the program view,
      SENSEG / SENFLD                            nested the same way, holding the sensitive fields

The hierarchy is the ``PARENT`` relationships: each segment is a record, and a parent holds one
list field per child segment type. ``FIELD`` types: ``C`` → ``string`` with ``max_length``, ``X`` →
``bytes`` of exactly ``BYTES``, ``P`` / ``Z`` (packed / zoned decimal) → ``decimal``, ``H`` / ``F``
(halfword / fullword binary) → ``integer``. Every field carries its byte offset (0-based) and
``START`` (1-based), length and storage in ``extras['ims']``, under the assumptions in
:data:`LAYOUT_ASSUMPTIONS`, which the document states in ``extras['ims']['layoutAssumptions']``.

A PSB's ``PROCOPT``s are the **declared access profile**: decoded (get / insert / replace /
delete / path) on every program-view record, on the PSB summary in ``extras['ims']['psbs']``, and —
when the PSB's DBD is in the same upload — on the DBD segment's record as
``extras['ims']['access']``. Declared limits are counted in ``extras['ims']['capability_limits']``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Constraints,
    Type,
    TypeKind,
    TypeRef,
)
from .ims_parser import (
    FIELD_TYPES,
    FORMAT_KEY,
    ImsDbd,
    ImsDocument,
    ImsField,
    ImsPcb,
    ImsPsb,
    ImsSegment,
    ImsSenseg,
    OperandValue,
    decode_procopt,
)
from .normalizer import Keys, Normalizer, normalize_ordering
from .typescript_types_normalizer import _limits_payload
from .typescript_types_parser import LimitRecorder

__all__ = [
    "IMS_EXTRAS_KEY",
    "IMS_LIMIT_DETAILS",
    "IMS_NAMESPACE",
    "IMS_PARTIAL_LIMITS",
    "ImsNormalizer",
    "LAYOUT_ASSUMPTIONS",
]

#: Root extras key of the projection record (also used on types and fields).
IMS_EXTRAS_KEY = "ims"
#: The namespace record types are keyed under.
IMS_NAMESPACE = "ims"

#: What every byte offset and length of this module assumes. The DBD states none of it.
LAYOUT_ASSUMPTIONS: Tuple[str, ...] = (
    "START and BYTES are 1-based byte positions and byte lengths within the segment's data as IMS "
    "presents it to the program; the offset reported is START − 1.",
    "One byte per character (TYPE=C) in a single-byte EBCDIC or ASCII code page.",
    "TYPE=P is packed decimal — two digits per byte with the sign in the last nibble, so BYTES=n "
    "holds 2n − 1 digits; TYPE=Z is zoned decimal, one digit per byte. The DBD declares no scale, "
    "so neither carries a decimal point.",
    "TYPE=H is a 2-byte and TYPE=F a 4-byte signed binary integer; TYPE=X is uninterpreted bytes.",
    "In a variable-length segment (BYTES=(max,min)) the first two bytes of each occurrence hold its "
    "length; START positions are taken as written, not shifted past that prefix.",
    "Byte ranges no FIELD covers are segment data the DBD does not describe — IMS needs FIELD "
    "statements only for the sequence field and the fields programs search on.",
    "A SENFLD's START is the field's position in the program's I/O area, not in the stored segment.",
)

#: The declared-limit vocabulary (stable keys → reviewed sentence).
IMS_LIMIT_DETAILS: Dict[str, str] = {
    "ims.segment_layout": (
        "A DBD declares only the fields IMS sequences and searches on; the segment's other bytes are "
        "described by the application's copybook. The record keeps the declared fields at their "
        "offsets, and the undescribed byte ranges are listed in extras['ims']['undescribed']."
    ),
    "ims.overlapping_fields": (
        "FIELD statements may overlap, one field naming a part of another. The canonical model has no "
        "overlay, so each field keeps its own offset and names the fields it overlaps in "
        "extras['ims']['overlaps']."
    ),
    "ims.variable_length_segment": (
        "A variable-length segment (BYTES=(max,min)) has a different length in each occurrence; the "
        "record is laid out at its maximum and the bounds are in extras['ims']['variableLength']."
    ),
    "ims.secondary_index_field": (
        "An XDFLD is a search field built from source fields for a secondary index, not segment data; "
        "it is listed with its SRCH / SUBSEQ / DDATA / NULLVAL in extras['ims']['secondaryIndexes'] "
        "and not modelled as a field."
    ),
    "ims.index_database": (
        "An LCHILD with POINTER=INDX pairs the segment with an index database (the HIDAM primary index "
        "or a secondary index). The index database is a separate DBD; it is named in "
        "extras['ims']['lchildren'] and not modelled."
    ),
    "ims.logical_relationship": (
        "A logical child's logical parent, and an LCHILD pairing with a segment of another database, "
        "cross the physical hierarchy; they are named in extras['ims'] and not modelled as fields."
    ),
    "ims.logical_database": (
        "A segment of a LOGICAL database is a projection of the physical segments named by SOURCE=; "
        "its data is theirs. The record keeps the logical hierarchy, and each source names the "
        "physical segment's record when that DBD is in the same upload."
    ),
    "ims.system_related_field": (
        "A /SX or /CK field is system-related (a segment's RBA or its concatenated key), not segment "
        "data; it is listed in extras['ims']['systemFields'] and not modelled."
    ),
    "ims.unresolved_dbd": (
        "A database PCB names a DBD that is not in the upload. The program view keeps its sensitive "
        "segments and fields by name, without types or lengths; upload the DBD beside the PSB as a "
        "fileset to resolve them."
    ),
    "ims.non_database_pcb": (
        "A TP PCB is a message destination and a GSAM PCB a sequential file, not a view of a "
        "database; they are listed in extras['ims']['psbs'] and not modelled."
    ),
}
#: Limits whose construct is still modelled, with only a detail lost.
IMS_PARTIAL_LIMITS = frozenset(
    {
        "ims.segment_layout",
        "ims.overlapping_fields",
        "ims.variable_length_segment",
        "ims.logical_database",
        "ims.unresolved_dbd",
    }
)


def _payload(value: OperandValue) -> Any:
    """An operand value as JSON (tuples become lists)."""
    return [_payload(part) for part in value] if isinstance(value, tuple) else value


def _operands_payload(operands: Dict[str, OperandValue]) -> Dict[str, Any]:
    return {key.lower(): _payload(value) for key, value in operands.items()}


def _dbd_type_name(dbd: ImsDbd, segment: str) -> str:
    return f"{dbd.name}.{segment}"


def _view_type_name(psb: ImsPsb, pcb: ImsPcb, segment: str) -> str:
    return f"{psb.name}.{pcb.name}.{segment}"


def _scalar(item: ImsField) -> Tuple[TypeRef, Optional[Constraints], Dict[str, Any]]:
    """The reference, constraints and storage facts of a ``FIELD``'s bytes."""
    length = item.length or 0
    code = item.type_code
    facts: Dict[str, Any] = {"type": code, "storage": FIELD_TYPES[code]}
    if code == "C":
        return TypeRef(name="string", nullable=False), Constraints(max_length=length), facts
    if code == "X":
        return TypeRef(name="bytes", nullable=False), Constraints(min_length=length, max_length=length), facts
    if code in ("P", "Z"):
        facts["digits"] = 2 * length - 1 if code == "P" else length
        return TypeRef(name="decimal", nullable=False), None, facts
    return TypeRef(name="integer", nullable=False), None, facts


def _field_description(item: ImsField, overlaps: List[str]) -> str:
    """``Sequence field (unique). TYPE=C, 10 bytes at START=1 (offset 0).``"""
    parts: List[str] = []
    if item.sequence:
        parts.append(f"Sequence field ({'unique' if item.unique else 'non-unique'}).")
    parts.append(
        f"TYPE={item.type_code} ({FIELD_TYPES[item.type_code]}), {item.length} byte{'s' if item.length != 1 else ''} "
        f"at START={item.start} (offset {(item.start or 1) - 1})."
    )
    if overlaps:
        parts.append(f"Overlaps {', '.join(overlaps)}.")
    return " ".join(parts)


def _overlaps(fields: List[ImsField]) -> Dict[str, List[str]]:
    """Field name → the names of the fields whose bytes it shares."""
    result: Dict[str, List[str]] = {f.name: [] for f in fields}
    for index, item in enumerate(fields):
        start, end = item.start or 0, (item.start or 0) + (item.length or 0)
        for other in fields[index + 1 :]:
            other_start, other_end = other.start or 0, (other.start or 0) + (other.length or 0)
            if start < other_end and other_start < end:
                result[item.name].append(other.name)
                result[other.name].append(item.name)
    return result


def _undescribed(segment: ImsSegment, fields: List[ImsField]) -> List[Dict[str, int]]:
    """The byte ranges (1-based, inclusive) of the segment no field covers."""
    if segment.max_bytes is None:
        return []
    covered = [False] * segment.max_bytes
    for item in fields:
        for position in range((item.start or 1) - 1, (item.start or 1) - 1 + (item.length or 0)):
            covered[position] = True
    gaps: List[Dict[str, int]] = []
    start: Optional[int] = None
    for position, flag in enumerate(covered + [True]):
        if not flag and start is None:
            start = position
        elif flag and start is not None:
            gaps.append({"start": start + 1, "end": position})
            start = None
    return gaps


def _data_field(type_key: str, item: ImsField, overlaps: List[str], number: int) -> CanonicalField:
    """One ``FIELD`` as a canonical field."""
    ref, constraints, facts = _scalar(item)
    metadata: Dict[str, Any] = {
        "offset": (item.start or 1) - 1,
        "start": item.start,
        "length": item.length,
        **facts,
        **({"sequence": {"unique": item.unique}} if item.sequence else {}),
        **({"overlaps": overlaps} if overlaps else {}),
        **({"operands": _operands_payload(item.operands)} if item.operands else {}),
        "line": item.line,
    }
    return CanonicalField(
        key=Keys.field(type_key, item.name),
        name=item.name,
        type=ref,
        field_number=number,
        constraints=constraints,
        description=_field_description(item, overlaps),
        extras={IMS_EXTRAS_KEY: metadata},
    )


def _child_field(type_key: str, name: str, child_key: str, number: int, description: str) -> CanonicalField:
    """The list field a parent record holds for one child segment type."""
    return CanonicalField(
        key=Keys.field(type_key, name),
        name=name,
        type=TypeRef(item=TypeRef(name=child_key, nullable=False), nullable=False),
        field_number=number,
        description=description,
        extras={IMS_EXTRAS_KEY: {"role": "child-segment", "segment": child_key}},
    )


def _child_name(child: str, taken: List[str]) -> str:
    """The parent's field name for a child segment: the segment name, ``…_SEGMENTS`` on a clash."""
    return child if child not in taken else f"{child}_SEGMENTS"


class _Builder:
    """Builds the records of one document, recording declared limits as it goes."""

    def __init__(self, document: ImsDocument, limits: LimitRecorder) -> None:
        self.document = document
        self.limits = limits
        #: ``(dbd name, segment name)`` → the access entries of the PSBs that see it.
        self.access: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}

    # ---------------------------------------------------------------- DBDs

    def dbd_types(self, dbd: ImsDbd) -> List[Type]:
        """One record per segment of a DBD, parents holding a list field per child type."""
        return [self._segment_type(dbd, segment) for segment in dbd.segments]

    def level(self, dbd: ImsDbd, segment: ImsSegment) -> int:
        """The segment's hierarchic level (1 for the root)."""
        level, current = 1, segment.parent
        while current is not None:
            level += 1
            current = dbd.segment(current).parent  # type: ignore[union-attr]
        return level

    def _segment_type(self, dbd: ImsDbd, segment: ImsSegment) -> Type:
        type_key = Keys.type(_dbd_type_name(dbd, segment.name), IMS_NAMESPACE)
        location = f"{dbd.name}.{segment.name}"
        data = [f for f in segment.fields if not f.system_related]
        system = [f for f in segment.fields if f.system_related]
        overlaps = _overlaps(data)
        ordered = sorted(data, key=lambda f: (f.start or 0, f.line))
        fields = [_data_field(type_key, item, overlaps[item.name], n) for n, item in enumerate(ordered, start=1)]
        taken = [f.name for f in data]
        for child in dbd.children(segment.name):
            name = _child_name(child.name, taken)
            taken.append(name)
            fields.append(
                _child_field(
                    type_key,
                    name,
                    Keys.type(_dbd_type_name(dbd, child.name), IMS_NAMESPACE),
                    len(fields) + 1,
                    f"Occurrences of child segment {child.name} under this {segment.name}.",
                )
            )
        undescribed = _undescribed(segment, data)
        if undescribed:
            self.limits.record("ims.segment_layout", location=location)
        if any(overlaps.values()):
            self.limits.record("ims.overlapping_fields", location=location)
        if segment.variable_length:
            self.limits.record("ims.variable_length_segment", location=location)
        for item in system:
            self.limits.record("ims.system_related_field", location=f"{location}.{item.name}")
        for lchild in segment.lchildren:
            self.limits.record(
                "ims.index_database" if lchild.is_index else "ims.logical_relationship",
                location=f"{location} → {lchild.dbd or dbd.name}.{lchild.segment}",
            )
        for xdfld in segment.xdflds:
            self.limits.record("ims.secondary_index_field", location=f"{location}.{xdfld.name}")
        if segment.logical_parent:
            self.limits.record("ims.logical_relationship", location=f"{location} → {segment.logical_parent[0]}")
        if dbd.logical:
            self.limits.record("ims.logical_database", location=location)
        metadata: Dict[str, Any] = {
            "dbd": dbd.name,
            "segment": segment.name,
            "level": self.level(dbd, segment),
            **({"parent": segment.parent} if segment.parent else {"root": True}),
            **({"parentPointer": segment.parent_pointer} if segment.parent_pointer else {}),
            **({"length": segment.max_bytes} if segment.max_bytes is not None else {}),
            **(
                {"variableLength": {"maximum": segment.max_bytes, "minimum": segment.min_bytes}}
                if segment.variable_length
                else {}
            ),
            **({"undescribed": undescribed} if undescribed else {}),
            **({"sequenceField": next(f.name for f in data if f.sequence)} if any(f.sequence for f in data) else {}),
            **({"logicalParent": self._logical_parent(segment)} if segment.logical_parent else {}),
            **({"lchildren": [self._lchild_payload(lc) for lc in segment.lchildren]} if segment.lchildren else {}),
            **({"secondaryIndexes": [self._xdfld_payload(x) for x in segment.xdflds]} if segment.xdflds else {}),
            **({"sources": [self._source_payload(s) for s in segment.sources]} if segment.sources else {}),
            **({"systemFields": [{"name": f.name, **_operands_payload(f.operands)} for f in system]} if system else {}),
            **({"operands": _operands_payload(segment.operands)} if segment.operands else {}),
            **({"access": self.access[(dbd.name, segment.name)]} if (dbd.name, segment.name) in self.access else {}),
            **({"file": dbd.path} if dbd.path else {}),
            "line": segment.line,
        }
        return Type(
            key=type_key,
            name=_dbd_type_name(dbd, segment.name),
            kind=TypeKind.RECORD,
            namespace=IMS_NAMESPACE,
            description=self._segment_description(dbd, segment, data),
            fields=fields,
            extras={IMS_EXTRAS_KEY: metadata},
        )

    def _segment_description(self, dbd: ImsDbd, segment: ImsSegment, data: List[ImsField]) -> str:
        where = "root segment" if segment.parent is None else f"child of {segment.parent}"
        if dbd.logical:
            sources = ", ".join(f"{s.dbd}.{s.segment}" for s in segment.sources)
            return f"IMS logical segment {segment.name} of DBD {dbd.name} ({where}), built from {sources}."
        if segment.variable_length:
            size = f"{segment.min_bytes}–{segment.max_bytes} bytes"
        else:
            size = f"{segment.max_bytes} bytes"
        access = "/".join(dbd.access) or "access not declared"
        return (
            f"IMS segment {segment.name} of DBD {dbd.name} ({access}): {where}, {size}, "
            f"{len(data)} declared field{'s' if len(data) != 1 else ''}."
        )

    def _logical_parent(self, segment: ImsSegment) -> Dict[str, Any]:
        assert segment.logical_parent is not None
        name, storage, dbd_name = segment.logical_parent
        resolved = self.document.dbd(dbd_name)
        return {
            "segment": name,
            "storage": storage,
            **({"dbd": dbd_name} if dbd_name else {}),
            **(
                {"type": Keys.type(_dbd_type_name(resolved, name), IMS_NAMESPACE)}
                if resolved is not None and resolved.segment(name) is not None
                else {}
            ),
        }

    @staticmethod
    def _lchild_payload(lchild: Any) -> Dict[str, Any]:
        return {
            "segment": lchild.segment,
            **({"dbd": lchild.dbd} if lchild.dbd else {}),
            **({"pointer": lchild.pointer} if lchild.pointer else {}),
            "kind": "index" if lchild.is_index else "logical-child",
            **({"operands": _operands_payload(lchild.operands)} if lchild.operands else {}),
        }

    @staticmethod
    def _xdfld_payload(xdfld: Any) -> Dict[str, Any]:
        return {
            "name": xdfld.name,
            "indexSegment": xdfld.index.segment,
            **({"indexDbd": xdfld.index.dbd} if xdfld.index.dbd else {}),
            "sourceSegment": xdfld.source_segment,
            "search": list(xdfld.search),
            **({"subsequence": list(xdfld.subsequence)} if xdfld.subsequence else {}),
            **({"duplicateData": list(xdfld.duplicate_data)} if xdfld.duplicate_data else {}),
            **({"nullValue": xdfld.null_value} if xdfld.null_value else {}),
            **({"operands": _operands_payload(xdfld.operands)} if xdfld.operands else {}),
        }

    def _source_payload(self, source: Any) -> Dict[str, Any]:
        resolved = self.document.dbd(source.dbd)
        return {
            "segment": source.segment,
            "mode": source.mode,
            "dbd": source.dbd,
            **(
                {"type": Keys.type(_dbd_type_name(resolved, source.segment), IMS_NAMESPACE)}
                if resolved is not None and resolved.segment(source.segment) is not None
                else {}
            ),
        }

    # ---------------------------------------------------------------- PSBs

    def collect_access(self) -> None:
        """Index every database PCB's access profile by the DBD segment it applies to."""
        for psb in self.document.psbs:
            for pcb in psb.pcbs:
                if pcb.pcb_type != "DB" or self.document.dbd(pcb.dbd_name) is None:
                    continue
                for senseg in pcb.sensegs:
                    self.access.setdefault((pcb.dbd_name or "", senseg.name), []).append(
                        {
                            "psb": psb.name,
                            "pcb": pcb.name,
                            "procopt": decode_procopt(senseg.procopt or pcb.procopt or "G"),
                            "fields": [f.name for f in senseg.fields] if senseg.fields else "all",
                        }
                    )

    def psb_types(self, psb: ImsPsb) -> List[Type]:
        """One record per sensitive segment of every database PCB: the program's view."""
        types: List[Type] = []
        for pcb in psb.pcbs:
            if pcb.pcb_type != "DB":
                self.limits.record("ims.non_database_pcb", location=f"{psb.name}.{pcb.name} ({pcb.pcb_type})")
                continue
            dbd = self.document.dbd(pcb.dbd_name)
            if dbd is None:
                self.limits.record("ims.unresolved_dbd", location=f"{psb.name}.{pcb.name} → {pcb.dbd_name}")
            types.extend(self._view_type(psb, pcb, senseg, dbd) for senseg in pcb.sensegs)
        return types

    def _view_type(self, psb: ImsPsb, pcb: ImsPcb, senseg: ImsSenseg, dbd: Optional[ImsDbd]) -> Type:
        type_key = Keys.type(_view_type_name(psb, pcb, senseg.name), IMS_NAMESPACE)
        segment = dbd.segment(senseg.name) if dbd is not None else None
        fields: List[CanonicalField] = []
        if senseg.fields:
            for number, senfld in enumerate(senseg.fields, start=1):
                source = segment.field(senfld.name) if segment is not None else None
                fields.append(self._view_field(type_key, senfld, source, number))
        elif segment is not None:
            data = [f for f in segment.fields if not f.system_related]
            overlaps = _overlaps(data)
            ordered = sorted(data, key=lambda f: (f.start or 0, f.line))
            fields = [_data_field(type_key, item, overlaps[item.name], n) for n, item in enumerate(ordered, start=1)]
        taken = [f.name for f in fields]
        for child in (s for s in pcb.sensegs if s.parent == senseg.name):
            name = _child_name(child.name, taken)
            taken.append(name)
            fields.append(
                _child_field(
                    type_key,
                    name,
                    Keys.type(_view_type_name(psb, pcb, child.name), IMS_NAMESPACE),
                    len(fields) + 1,
                    f"Occurrences of sensitive segment {child.name} under this {senseg.name}.",
                )
            )
        procopt = senseg.procopt or pcb.procopt or "G"
        metadata: Dict[str, Any] = {
            "psb": psb.name,
            "pcb": pcb.name,
            "dbd": pcb.dbd_name,
            "segment": senseg.name,
            **({"parent": senseg.parent} if senseg.parent else {"root": True}),
            "procopt": decode_procopt(procopt),
            "procoptSource": "senseg" if senseg.procopt else "pcb",
            "sensitiveFields": [f.name for f in senseg.fields] if senseg.fields else "all",
            **(
                {"dbdType": Keys.type(_dbd_type_name(dbd, senseg.name), IMS_NAMESPACE)}
                if dbd is not None and segment is not None
                else {"dbdResolved": False}
            ),
            **({"operands": _operands_payload(senseg.operands)} if senseg.operands else {}),
            **({"file": psb.path} if psb.path else {}),
            "line": senseg.line,
        }
        intents = ", ".join(decode_procopt(procopt)["intents"]) or "none"  # type: ignore[arg-type]
        return Type(
            key=type_key,
            name=_view_type_name(psb, pcb, senseg.name),
            kind=TypeKind.RECORD,
            namespace=IMS_NAMESPACE,
            description=(
                f"Program view of segment {senseg.name} of DBD {pcb.dbd_name} through PCB {pcb.name} of PSB "
                f"{psb.name}: PROCOPT={procopt} ({intents})."
            ),
            fields=fields,
            extras={IMS_EXTRAS_KEY: metadata},
        )

    @staticmethod
    def _view_field(type_key: str, senfld: Any, source: Optional[ImsField], number: int) -> CanonicalField:
        """One ``SENFLD``: typed from the DBD field when the DBD is in the upload."""
        metadata: Dict[str, Any] = {
            **({"offset": senfld.start - 1, "start": senfld.start} if senfld.start else {}),
            "replace": senfld.replace,
            "line": senfld.line,
        }
        if source is None:
            return CanonicalField(
                key=Keys.field(type_key, senfld.name),
                name=senfld.name,
                type=TypeRef(name="bytes", nullable=False),
                field_number=number,
                description=(
                    f"Sensitive field {senfld.name} at START={senfld.start} of the I/O area; its DBD is not in "
                    "the upload."
                ),
                extras={IMS_EXTRAS_KEY: {**metadata, "dbdResolved": False}},
            )
        ref, constraints, facts = _scalar(source)
        return CanonicalField(
            key=Keys.field(type_key, senfld.name),
            name=senfld.name,
            type=ref,
            field_number=number,
            constraints=constraints,
            description=(
                f"Sensitive field {senfld.name}: TYPE={source.type_code}, {source.length} bytes at START="
                f"{senfld.start} of the I/O area (START={source.start} in the segment)."
            ),
            extras={
                IMS_EXTRAS_KEY: {
                    **metadata,
                    "length": source.length,
                    "segmentStart": source.start,
                    **facts,
                    **({"sequence": {"unique": source.unique}} if source.sequence else {}),
                }
            },
        )


def _dbd_summary(dbd: ImsDbd, builder: _Builder) -> Dict[str, Any]:
    return {
        "name": dbd.name,
        "access": list(dbd.access),
        "logical": dbd.logical,
        "root": dbd.root.name,
        "hierarchy": [
            {
                "segment": s.name,
                "parent": s.parent,
                "level": builder.level(dbd, s),
                "type": Keys.type(_dbd_type_name(dbd, s.name), IMS_NAMESPACE),
            }
            for s in dbd.segments
        ],
        **({"datasets": [_operands_payload(d) for d in dbd.datasets]} if dbd.datasets else {}),
        **({"operands": _operands_payload(dbd.operands)} if dbd.operands else {}),
        **({"file": dbd.path} if dbd.path else {}),
    }


def _psb_summary(psb: ImsPsb, document: ImsDocument) -> Dict[str, Any]:
    """The PSB's declared access profile: each PCB's view and PROCOPT, decoded."""
    pcbs: List[Dict[str, Any]] = []
    for pcb in psb.pcbs:
        entry: Dict[str, Any] = {"name": pcb.name, "type": pcb.pcb_type}
        if pcb.dbd_name:
            entry["dbd"] = pcb.dbd_name
            entry["dbdResolved"] = document.dbd(pcb.dbd_name) is not None
        if pcb.procopt:
            entry["procopt"] = decode_procopt(pcb.procopt)
        if pcb.key_length is not None:
            entry["keyLength"] = pcb.key_length
        if pcb.processing_sequence:
            entry["processingSequence"] = pcb.processing_sequence
        if pcb.sensegs:
            entry["sensitiveSegments"] = [
                {
                    "segment": s.name,
                    "parent": s.parent,
                    "procopt": decode_procopt(s.procopt or pcb.procopt or "G"),
                    "fields": [
                        {"name": f.name, **({"start": f.start} if f.start else {}), "replace": f.replace}
                        for f in s.fields
                    ]
                    or "all",
                }
                for s in pcb.sensegs
            ]
        if pcb.operands:
            entry["operands"] = _operands_payload(pcb.operands)
        pcbs.append(entry)
    return {
        "name": psb.name,
        **({"language": psb.language} if psb.language else {}),
        "pcbs": pcbs,
        **({"operands": _operands_payload(psb.operands)} if psb.operands else {}),
        **({"file": psb.path} if psb.path else {}),
    }


class ImsNormalizer(Normalizer, register=True):
    """Normalize a parsed IMS document (:class:`~app.ims_parser.ImsDocument`)."""

    format = FORMAT_KEY
    paradigm = ApiParadigm.DATA_SCHEMA

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Map an :class:`~app.ims_parser.ImsDocument` to the canonical model.

        Args:
            source: The parsed document.
            include_raw: Whether to keep every file's text on ``raw``.

        Returns:
            One ``RECORD`` per DBD segment and per sensitive segment of every database PCB.

        Raises:
            ValueError: When ``source`` is not an :class:`ImsDocument`.
        """
        if not isinstance(source, ImsDocument):
            raise ValueError("IMS source must be an ImsDocument (see app.ims_parser)")
        limits = LimitRecorder(details=IMS_LIMIT_DETAILS)
        builder = _Builder(source, limits)
        builder.collect_access()
        types: List[Type] = []
        for dbd in source.dbds:
            types.extend(builder.dbd_types(dbd))
        for psb in source.psbs:
            types.extend(builder.psb_types(psb))
        name = source.dbds[0].name if source.dbds else source.psbs[0].name
        record: Dict[str, Any] = {
            "input": "fileset" if source.is_fileset else "file",
            "files": sorted(source.sources),
            "dbds": [_dbd_summary(dbd, builder) for dbd in source.dbds],
            "psbs": [_psb_summary(psb, source) for psb in source.psbs],
            "layoutAssumptions": list(LAYOUT_ASSUMPTIONS),
            "capability_limits": _limits_payload(limits.limits()),
        }
        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            identity=ApiIdentity(name=name, namespace=IMS_NAMESPACE),
            title=name,
            description=(
                f"IMS database descriptions and program views: {len(source.dbds)} DBD(s), {len(source.psbs)} "
                "PSB(s). Byte offsets and lengths are computed under the assumptions in "
                "extras['ims']['layoutAssumptions']; PROCOPT access profiles are in extras['ims']['psbs']."
            ),
            types=types,
            raw={"files": [{"path": p, "text": t} for p, t in sorted(source.sources.items())]} if include_raw else None,
            extras={IMS_EXTRAS_KEY: record},
        )
        return normalize_ordering(api)
