"""SAP IDoc → canonical model normalizer — FMT-6.2 (#5446).

Maps a parsed :class:`~app.idoc_parser.IdocFile` into a :class:`~app.canonical_model.CanonicalApi`
of paradigm :attr:`~app.canonical_model.ApiParadigm.DATA_SCHEMA`. The form the IDoc arrived in is not
part of the model: a flat file and an XML document carrying the same IDoc — with the same segment
definitions, where the flat form needs them — produce the same model.

* The **basic type** (``ORDERS05``) is the root record type; each **segment type** (``E1EDK01``) is a
  record type of its own, holding its fields and then its child segments.
* The hierarchy is the parsed one (rebuilt from segment numbers), never the record order. A child
  segment is a list when any parent occurrence carries more than one of it, or when the definition
  allows more than one.
* A field's description and length come from the segment definition when one is supplied. A flat
  segment with no definition has one opaque ``SDATA`` field.
* Payload values are never field defaults. The control record (basic type, message type, partners)
  is recorded in ``idoc_control`` as structure, and the first IDoc's segment values in
  ``idoc_segments`` — the template the IDoc emitter replays.

Like the other EDI normalizers, the model is derived from the **first** IDoc; the analysis keeps the
rest and says so.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

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
from .idoc_parser import SDATA_LENGTH, IdocFile, IdocSegment, SegmentDefinitionSet
from .normalizer import Keys, Normalizer, normalize_ordering

__all__ = ["IdocNormalizer", "segment_template"]

_FORMAT_KEY = "idoc"


@dataclass
class _FieldShape:
    """What is known about one field of a segment type."""

    description: Optional[str] = None
    length: Optional[int] = None


@dataclass
class _SegmentShape:
    """Every occurrence of one segment type, folded together."""

    fields: Dict[str, _FieldShape] = field(default_factory=dict)
    children: Dict[str, int] = field(default_factory=dict)  # child name → max per occurrence


def _fold(
    siblings: Sequence[IdocSegment],
    parent: _SegmentShape,
    shapes: Dict[str, _SegmentShape],
    definitions: Optional[SegmentDefinitionSet],
) -> None:
    """Fold one parent occurrence's children into the shape table, recursively."""
    counts = Counter(segment.name for segment in siblings)
    for segment in siblings:
        parent.children[segment.name] = max(parent.children.get(segment.name, 0), counts[segment.name])
        shape = shapes.get(segment.name)
        if shape is None:
            shape = shapes[segment.name] = _SegmentShape()
            definition = definitions.segments.get(segment.name) if definitions else None
            for declared in definition.fields if definition else ():
                shape.fields[declared.name] = _FieldShape(declared.description, declared.length)
        for item in segment.fields:
            if item.name not in shape.fields:
                length = SDATA_LENGTH if item.name == "SDATA" and not segment.defined else None
                shape.fields[item.name] = _FieldShape(item.description, length)
        _fold(segment.children, shape, shapes, definitions)


def _child_fields(
    owner_key: str,
    shape: _SegmentShape,
    namespace: str,
    definitions: Optional[SegmentDefinitionSet],
    start: int,
) -> List[CanonicalField]:
    """Fields referencing child segment types — a list where more than one may occur."""
    fields: List[CanonicalField] = []
    for offset, (name, observed_max) in enumerate(shape.children.items()):
        definition = definitions.segments.get(name) if definitions else None
        declared_max = definition.max_occurs if definition else None
        repeated = observed_max > 1 or (declared_max is not None and declared_max > 1)
        reference = TypeRef(name=Keys.type(name, namespace), nullable=False)
        fields.append(
            CanonicalField(
                key=Keys.field(owner_key, name),
                name=name,
                type=TypeRef(item=reference, nullable=False) if repeated else reference,
                field_number=start + offset,
                description=definition.description if definition else None,
            )
        )
    return fields


def _segment_type(
    name: str,
    shape: _SegmentShape,
    namespace: str,
    definitions: Optional[SegmentDefinitionSet],
) -> Type:
    """The record type for one segment type: its fields, then its child segments."""
    key = Keys.type(name, namespace)
    fields: List[CanonicalField] = [
        CanonicalField(
            key=Keys.field(key, field_name),
            name=field_name,
            type=TypeRef(name="string"),
            field_number=index,
            description=meta.description,
            constraints=Constraints(max_length=meta.length) if meta.length else None,
        )
        for index, (field_name, meta) in enumerate(shape.fields.items(), start=1)
    ]
    fields.extend(_child_fields(key, shape, namespace, definitions, len(fields) + 1))
    definition = definitions.segments.get(name) if definitions else None
    return Type(
        key=key,
        name=name,
        kind=TypeKind.RECORD,
        fields=fields,
        description=definition.description if definition else None,
    )


def segment_template(segment: IdocSegment) -> Dict[str, Any]:
    """One segment occurrence as written — the shape ``idoc_segments`` and the emitter share."""
    return {
        "name": segment.name,
        "fields": [[item.name, item.value] for item in segment.fields],
        "children": [segment_template(child) for child in segment.children],
    }


class IdocNormalizer(Normalizer, register=True):
    """Normalize a parsed SAP IDoc into a :class:`CanonicalApi`."""

    format = _FORMAT_KEY
    paradigm = ApiParadigm.DATA_SCHEMA

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(source, IdocFile):
            raise ValueError("IDoc source must be an IdocFile (see app.idoc_parser.parse_idoc)")

        idoc = source.idocs[0]
        basic_type = idoc.control.basic_type
        namespace = f"IDOC-{basic_type}"
        root = _SegmentShape()
        shapes: Dict[str, _SegmentShape] = {}
        _fold(idoc.segments, root, shapes, source.definitions)

        root_key = Keys.type(basic_type, namespace)
        types: List[Type] = [
            Type(
                key=root_key,
                name=basic_type,
                kind=TypeKind.RECORD,
                fields=_child_fields(root_key, root, namespace, source.definitions, 1),
                description=f"IDoc basic type {basic_type} (message type {idoc.control.message_type})"
                if idoc.control.message_type
                else f"IDoc basic type {basic_type}",
            )
        ]
        types.extend(
            _segment_type(name, shape, namespace, source.definitions) for name, shape in shapes.items()
        )

        definitions = source.definitions
        title = f"IDoc {basic_type}"
        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            identity=ApiIdentity(name=title, namespace=namespace),
            title=title,
            types=types,
            raw={"idoc": source.raw} if include_raw else None,
            extras={
                "idoc_basic_type": basic_type,
                "idoc_message_type": idoc.control.message_type,
                "idoc_control": idoc.control.non_empty(),
                "idoc_segments": [segment_template(segment) for segment in idoc.segments],
                "idoc_definition": (
                    {"basic_type": definitions.basic_type, "release": definitions.release}
                    if definitions is not None
                    else None
                ),
            },
        )
        return normalize_ordering(api)
