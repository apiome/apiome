"""DICOM → canonical model normalizer — FMT-6.7 (#5451).

Maps a parsed :class:`~app.dicom_model.DicomDocument` into a :class:`~app.canonical_model.CanonicalApi`
of paradigm :attr:`~app.canonical_model.ApiParadigm.DATA_SCHEMA` whose types are DICOM's own
information model:

.. code-block:: text

    CTImageStorage               one record per SOP class (an IOD as the instances realise it)
      PatientName: PN            one field per attribute, keyed by its tag, typed by its VR
      ImageType: [CS]            a multi-valued attribute (VM 1-n, or more than one value seen)
      ReferencedImageSequence: [ReferencedImageSequenceItem]
    ReferencedImageSequenceItem  one record per sequence tag: nested sequences are nested types
    FileMetaInformation          the Part 10 file meta group (0002,xxxx)
    StudyQueryResult             a query/retrieve result, which names no SOP class
    CS, UI, DS …                 one alias per VR used, over string / integer / number
    PN                           a record: Alphabetic, Ideographic, Phonetic (PS3.18 F.2.2)

Every occurrence of a type is folded into it: an attribute missing from some instance or item is
nullable, and one with several values anywhere is a list. ``ContentSequence`` folds into one
recursive ``ContentSequenceItem`` — the SR content item macro — and the Structured Report's
concrete content **tree** is recorded beside the model (``dicom_sr_content_trees``) as a hierarchy
of value types, relationship types and concept names.

No attribute value enters the model. Field extras carry the tag, keyword, VR, VM and whether PS3.15
lists the attribute as patient-identifying; model extras carry only the few values that *are*
structure (:data:`app.dicom_dictionary.STRUCTURAL_VALUE_TAGS`: SOP class, transfer syntax,
modality …), counts, and the pixel-data statement. The model also asks the import not to keep the
verbatim upload (``source_retention``): it is patient data and, for Part 10, pixel data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

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
from .dicom_dictionary import (
    CONCEPT_NAME_CODE_SEQUENCE,
    CONTENT_SEQUENCE,
    PIXEL_DATA_BOUNDARY_STATEMENT,
    SOP_CLASS_UID,
    VR_SPECS,
    attribute_info,
    is_group_length,
    is_identifying,
    is_private,
    is_private_creator,
    pascal_name,
    sop_class_name,
    tag_hex,
    tag_text,
)
from .dicom_model import (
    VALUE_BULK_DATA,
    VALUE_INLINE_BINARY,
    VALUE_PIXEL_SKIPPED,
    VALUE_SEQUENCE,
    DicomDataset,
    DicomDocument,
    DicomElement,
    DicomItem,
)
from .dicom_parser import is_query_result
from .normalizer import Keys, Normalizer, normalize_ordering

__all__ = [
    "DICOM_NAMESPACE",
    "DICOM_VALUE_STATEMENT",
    "DicomNormalizer",
    "MAX_CONTENT_TREE_NODES",
    "SOURCE_RETENTION_REASON",
    "attribute_field_name",
    "dataset_type_name",
    "sequence_item_type_name",
]

_FORMAT_KEY = "dicom"
#: The namespace every DICOM type key is minted under.
DICOM_NAMESPACE = "DICOM"
#: Most content items one SR content tree records beside the model.
MAX_CONTENT_TREE_NODES = 2000

#: What the model says about values, wherever a reader meets it.
DICOM_VALUE_STATEMENT = (
    "No attribute value is in this model: patient names, identifiers, dates, UIDs and report text "
    "are payload. The model holds each attribute's tag, keyword, VR and multiplicity; values are "
    "only in the native analysis, under the value-visibility policy (presence and length by "
    "default)."
)
#: Why the verbatim upload is not kept as the version's source.
SOURCE_RETENTION_REASON = "dicom-patient-and-pixel-data"

_VALUE_TYPE = 0x0040A040
_RELATIONSHIP_TYPE = 0x0040A010
_CONTENT_TEMPLATE_SEQUENCE = 0x0040A504
_TEMPLATE_IDENTIFIER = 0x0040DB00
_CODE_VALUE = 0x00080100
_CODING_SCHEME = 0x00080102
_CODE_MEANING = 0x00080104
_MODALITY = 0x00080060
_QUERY_RETRIEVE_LEVEL = 0x00080052
_STUDY_INSTANCE_UID = 0x0020000D
_SERIES_INSTANCE_UID = 0x0020000E
_SPECIFIC_CHARACTER_SET = 0x00080005
_MEDIA_STORAGE_SOP_CLASS = 0x00020002

#: The PN value object's component groups (PS3.18 F.2.2).
_PN_COMPONENTS = ("Alphabetic", "Ideographic", "Phonetic")


# ===========================================================================
# Naming
# ===========================================================================


def attribute_field_name(tag: int) -> str:
    """The canonical field name for ``tag``: its keyword, or a stable spelling of the tag."""
    keyword = attribute_info(tag).keyword
    if keyword:
        return keyword
    if is_private(tag):
        return f"Private_{tag >> 16:04X}_{tag & 0xFFFF:04X}"
    if is_group_length(tag):
        return f"GroupLength_{tag >> 16:04X}"
    return f"Tag_{tag_hex(tag)}"


def sequence_item_type_name(tag: int) -> str:
    """The record type a sequence's items fold into (``ContentSequence`` → ``ContentSequenceItem``)."""
    return f"{attribute_field_name(tag)}Item"


def _query_level(dataset: DicomDataset) -> str:
    level = dataset.first_value(_QUERY_RETRIEVE_LEVEL)
    if level:
        return level.title()
    if dataset.element(0x00201209) is not None and dataset.element(0x00201206) is None:
        return "Series"
    return "Study"


def dataset_type_name(dataset: DicomDataset) -> str:
    """The record type a dataset folds into: its SOP class, or its query level for a query result."""
    uid = dataset.first_value(SOP_CLASS_UID)
    if uid:
        name = sop_class_name(uid)
        return pascal_name(name) if name else f"SopClass_{uid.replace('.', '_')}"
    return f"{_query_level(dataset)}QueryResult"


def _key(name: str) -> str:
    return Keys.type(name, DICOM_NAMESPACE)


# ===========================================================================
# Folding
# ===========================================================================


@dataclass
class _FieldFold:
    """Everything seen about one attribute across every occurrence of its type."""

    tag: int
    vr: str
    vr_explicit: bool = True
    observed_vrs: List[str] = field(default_factory=list)
    occurrences: int = 0
    max_values: int = 0
    item_type: Optional[str] = None
    pixel: bool = False
    bulk: bool = False
    private_creator: Optional[str] = None


@dataclass
class _TypeFold:
    """One record type under construction."""

    name: str
    kind: str
    occurrences: int = 0
    fields: Dict[int, _FieldFold] = field(default_factory=dict)
    extras: Dict[str, Any] = field(default_factory=dict)


class _Folder:
    """Folds datasets and sequence items into record types."""

    def __init__(self) -> None:
        self.types: Dict[str, _TypeFold] = {}
        self.vrs: List[str] = []

    def _type(self, name: str, kind: str) -> _TypeFold:
        fold = self.types.get(name)
        if fold is None:
            fold = self.types[name] = _TypeFold(name=name, kind=kind)
        return fold

    def _use_vr(self, vr: str) -> None:
        if vr != "SQ" and vr not in self.vrs:
            self.vrs.append(vr)

    def fold(self, name: str, kind: str, item: DicomItem) -> _TypeFold:
        """Fold one dataset or item's elements into the type called ``name``."""
        fold = self._type(name, kind)
        fold.occurrences += 1
        creators = {
            (element.tag >> 16, element.tag & 0xFF): element.values[0]
            for element in item.elements
            if is_private_creator(element.tag) and element.values
        }
        for element in item.elements:
            self._fold_element(fold, element, creators)
        return fold

    def _fold_element(
        self, fold: _TypeFold, element: DicomElement, creators: Dict[Tuple[int, int], str]
    ) -> None:
        entry = fold.fields.get(element.tag)
        if entry is None:
            entry = fold.fields[element.tag] = _FieldFold(
                tag=element.tag, vr=element.vr, vr_explicit=element.vr_explicit
            )
        if element.vr not in entry.observed_vrs:
            entry.observed_vrs.append(element.vr)
        entry.occurrences += 1
        entry.max_values = max(entry.max_values, element.multiplicity)
        entry.pixel = entry.pixel or element.value_form == VALUE_PIXEL_SKIPPED
        entry.bulk = entry.bulk or element.value_form in (VALUE_BULK_DATA, VALUE_INLINE_BINARY)
        if is_private(element.tag) and not is_private_creator(element.tag):
            entry.private_creator = entry.private_creator or creators.get(
                (element.tag >> 16, (element.tag >> 8) & 0xFF)
            )
        if element.value_form == VALUE_SEQUENCE:
            entry.item_type = sequence_item_type_name(element.tag)
            for item in element.items:
                self.fold(entry.item_type, "sequence-item", item)
            if not element.items:
                self._type(entry.item_type, "sequence-item")
        else:
            self._use_vr(element.vr)


# ===========================================================================
# Types
# ===========================================================================


def _vr_type(vr: str) -> Type:
    """The canonical type a VR names: an alias over its primitive, or the PN record."""
    spec = VR_SPECS[vr]
    extras = {"dicom_kind": "value-representation", "dicom_vr": vr, "dicom_binary": spec.binary}
    if vr == "PN":
        type_key = _key("PN")
        return Type(
            key=type_key,
            name="PN",
            kind=TypeKind.RECORD,
            description=f"{spec.name} — one value per component group (PS3.18 F.2.2)",
            fields=[
                CanonicalField(
                    key=Keys.field(type_key, component),
                    name=component,
                    type=TypeRef(name="string"),
                    field_number=number,
                    constraints=Constraints(max_length=spec.max_length),
                )
                for number, component in enumerate(_PN_COMPONENTS, start=1)
            ],
            extras=extras,
        )
    constraints = Constraints(max_length=spec.max_length) if spec.max_length else None
    return Type(
        key=_key(vr),
        name=vr,
        kind=TypeKind.ALIAS,
        description=spec.name,
        aliased=TypeRef(name=spec.primitive or "string", nullable=False),
        constraints=constraints,
        extras=extras,
    )


def _field(fold: _TypeFold, entry: _FieldFold) -> CanonicalField:
    """One attribute as a canonical field, keyed by its tag."""
    info = attribute_info(entry.tag)
    type_key = _key(fold.name)
    nullable = entry.occurrences < fold.occurrences
    if entry.item_type is not None:
        ref = TypeRef(item=TypeRef(name=_key(entry.item_type), nullable=False), nullable=nullable)
    else:
        leaf = TypeRef(name=_key(entry.vr), nullable=False)
        if info.multi_valued or entry.max_values > 1:
            ref = TypeRef(item=leaf, nullable=nullable)
        else:
            ref = leaf.model_copy(update={"nullable": nullable})

    extras: Dict[str, Any] = {"dicom_tag": tag_text(entry.tag), "dicom_vr": entry.vr}
    if info.keyword:
        extras["dicom_keyword"] = info.keyword
    if info.vm:
        extras["dicom_vm"] = info.vm
    if entry.item_type is None and entry.max_values > 1:
        extras["dicom_observed_max_values"] = entry.max_values
    if info.vr and info.vr != entry.vr:
        extras["dicom_dictionary_vr"] = info.vr
    if len(entry.observed_vrs) > 1:
        extras["dicom_observed_vrs"] = list(entry.observed_vrs)
    if not entry.vr_explicit:
        extras["dicom_vr_implicit"] = True
    if info.retired:
        extras["dicom_retired"] = True
    if is_private(entry.tag):
        extras["dicom_private"] = True
        if entry.private_creator:
            extras["dicom_private_creator"] = entry.private_creator
    if is_identifying(entry.tag):
        extras["dicom_patient_identifying"] = True
    if entry.pixel:
        extras["dicom_pixel_data"] = {"read": False, "stored": False}
    if entry.bulk:
        extras["dicom_bulk_data"] = True

    if info.name:
        description = info.name
    elif is_private_creator(entry.tag):
        description = "Private Creator"
    elif is_private(entry.tag):
        creator = f" of {entry.private_creator}" if entry.private_creator else ""
        description = f"Private attribute{creator} (not in the DICOM data dictionary)"
    else:
        description = "Attribute not in the DICOM data dictionary"
    if entry.pixel:
        description += " — value never read (pixel data)"
    return CanonicalField(
        # Keyed by tag: two attributes can never collide, and the key sorts in tag order.
        key=Keys.field(type_key, tag_hex(entry.tag)),
        name=attribute_field_name(entry.tag),
        description=description,
        type=ref,
        extras=extras,
    )


def _record(fold: _TypeFold, description: str) -> Type:
    fields = [_field(fold, entry) for entry in sorted(fold.fields.values(), key=lambda e: e.tag)]
    return Type(
        key=_key(fold.name),
        name=fold.name,
        kind=TypeKind.RECORD,
        description=description,
        fields=[f.model_copy(update={"field_number": n}) for n, f in enumerate(fields, start=1)],
        extras={"dicom_kind": fold.kind, "dicom_occurrences": fold.occurrences, **fold.extras},
    )


def _type_description(fold: _TypeFold) -> str:
    if fold.kind == "file-meta":
        return "Part 10 file meta information (group 0002), always explicit VR little endian"
    if fold.kind == "query-result":
        return "A query/retrieve result: attributes describing a study or series, not an instance"
    if fold.kind == "sequence-item":
        base = fold.name[: -len("Item")]
        return f"One item of {base}"
    uid = fold.extras.get("dicom_sop_class_uid")
    name = fold.extras.get("dicom_sop_class_name")
    if name:
        return f"Instances of the {name} SOP class ({uid})"
    return f"Instances of the SOP class {uid} (not in the DICOM UID registry)"


# ===========================================================================
# Extras recorded beside the model
# ===========================================================================


def _concept_name(item: DicomItem) -> Optional[Dict[str, str]]:
    sequence = item.element(CONCEPT_NAME_CODE_SEQUENCE)
    if sequence is None or not sequence.items:
        return None
    code = sequence.items[0]
    concept = {
        "code": code.first_value(_CODE_VALUE),
        "scheme": code.first_value(_CODING_SCHEME),
        "meaning": code.first_value(_CODE_MEANING),
    }
    return {key: value for key, value in concept.items() if value}


class _TreeBudget:
    def __init__(self) -> None:
        self.nodes = 0
        self.truncated = False


def _content_item(item: DicomItem, budget: _TreeBudget, depth: int) -> Dict[str, Any]:
    """One SR content item: value type, relationship, concept name and children — no value."""
    budget.nodes += 1
    node: Dict[str, Any] = {"valueType": item.first_value(_VALUE_TYPE)}
    relationship = item.first_value(_RELATIONSHIP_TYPE)
    if relationship:
        node["relationshipType"] = relationship
    concept = _concept_name(item)
    if concept:
        node["conceptName"] = concept
    templates = item.element(_CONTENT_TEMPLATE_SEQUENCE)
    if templates is not None and templates.items:
        template = templates.items[0].first_value(_TEMPLATE_IDENTIFIER)
        if template:
            node["templateIdentifier"] = template
    content = item.element(CONTENT_SEQUENCE)
    if content is not None and content.items:
        children = []
        for child in content.items:
            if budget.nodes >= MAX_CONTENT_TREE_NODES:
                budget.truncated = True
                break
            children.append(_content_item(child, budget, depth + 1))
        node["children"] = children
    return node


def _content_tree(dataset: DicomDataset) -> Optional[Dict[str, Any]]:
    """The SR content tree rooted at the dataset, when the dataset is a Structured Report."""
    if dataset.element(_VALUE_TYPE) is None or dataset.element(CONTENT_SEQUENCE) is None:
        return None
    budget = _TreeBudget()
    root = _content_item(dataset, budget, 0)
    return {"root": root, "contentItems": budget.nodes, "truncated": budget.truncated}


def _walk_elements(elements: Sequence[DicomElement], depth: int = 0):
    for element in elements:
        yield element, depth
        for item in element.items:
            yield from _walk_elements(item.elements, depth + 1)


def _pixel_entry(skip) -> Dict[str, Any]:
    entry: Dict[str, Any] = {"tag": tag_text(skip.tag), "vr": skip.vr, "path": skip.path, "read": False}
    if skip.declared_length is not None:
        entry["declaredLength"] = skip.declared_length
    if skip.fragments is not None:
        entry["encapsulatedFragments"] = skip.fragments
    if skip.json_form is not None:
        entry["jsonForm"] = skip.json_form
    return entry


def _dataset_summary(dataset: DicomDataset, type_name: str, fileset: bool) -> Dict[str, Any]:
    """Structure of one dataset — counts and structural values, never payload."""
    walked = list(_walk_elements(dataset.elements))
    summary: Dict[str, Any] = {
        "form": dataset.form,
        "kind": "query-result" if is_query_result(dataset) and not dataset.first_value(SOP_CLASS_UID) else "instance",
        "typeName": type_name,
        "attributeCount": len(dataset.elements),
        "elementCount": len(walked),
        "sequenceCount": sum(1 for element, _ in walked if element.value_form == VALUE_SEQUENCE),
        "privateAttributeCount": sum(
            1 for element, _ in walked if is_private(element.tag) and not is_private_creator(element.tag)
        ),
        "maxSequenceDepth": max((depth for _, depth in walked), default=0),
    }
    if fileset and dataset.label:
        summary["member"] = dataset.label
    uid = dataset.first_value(SOP_CLASS_UID)
    if uid:
        summary["sopClassUid"] = uid
        name = sop_class_name(uid)
        if name:
            summary["sopClassName"] = name
    for key, tag in (("modality", _MODALITY), ("queryRetrieveLevel", _QUERY_RETRIEVE_LEVEL)):
        value = dataset.first_value(tag)
        if value:
            summary[key] = value
    charset = dataset.element(_SPECIFIC_CHARACTER_SET)
    if charset is not None and charset.values:
        summary["specificCharacterSet"] = [value for value in charset.values if value]
    if dataset.transfer_syntax:
        summary["transferSyntaxUid"] = dataset.transfer_syntax
        summary["transferSyntaxName"] = dataset.transfer_syntax_name
        summary["deflated"] = dataset.deflated
        media = dataset.meta_value(_MEDIA_STORAGE_SOP_CLASS)
        if media:
            summary["mediaStorageSopClassUid"] = media
            summary["mediaStorageMatchesSopClass"] = media == uid
    summary["pixelData"] = [_pixel_entry(skip) for skip in dataset.pixel_data]
    return summary


def _distinct_count(datasets: Sequence[DicomDataset], tag: int) -> int:
    """How many distinct values ``tag`` takes — compared, never recorded."""
    return len({value for value in (dataset.first_value(tag) for dataset in datasets) if value})


def _declared_limits(document: DicomDocument) -> List[Dict[str, Any]]:
    """Constructs the reader read but could not model, each counted."""
    private = unknown_vr = 0
    for dataset in document.datasets:
        for element, _ in _walk_elements(dataset.elements):
            if is_private(element.tag) and not is_private_creator(element.tag):
                private += 1
            if element.vr == "UN" and element.value_form != VALUE_SEQUENCE:
                unknown_vr += 1
    limits = []
    if private:
        limits.append(
            {
                "key": "dicom.private_attributes",
                "count": private,
                "detail": "Private attributes are not in the DICOM data dictionary: their tag, VR and "
                "length are modelled, their meaning is not.",
            }
        )
    if unknown_vr:
        limits.append(
            {
                "key": "dicom.unknown_vr",
                "count": unknown_vr,
                "detail": "An attribute written with VR UN carries bytes whose representation the file "
                "does not state; its length is recorded and its value is not decoded.",
            }
        )
    return limits


def _title(type_names: Sequence[str], datasets: Sequence[DicomDataset]) -> str:
    names = []
    for dataset, name in zip(datasets, type_names):
        label = sop_class_name(dataset.first_value(SOP_CLASS_UID)) or name
        if label not in names:
            names.append(label)
    return "DICOM " + ", ".join(names)


# ===========================================================================
# Normalizer
# ===========================================================================


class DicomNormalizer(Normalizer, register=True):
    """Normalize a parsed DICOM document into a :class:`CanonicalApi`."""

    format = _FORMAT_KEY
    paradigm = ApiParadigm.DATA_SCHEMA

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(source, DicomDocument):
            raise ValueError("DICOM source must be a DicomDocument (see app.dicom_parser)")

        folder = _Folder()
        type_names: List[str] = []
        fileset = source.fileset_root is not None
        for dataset in source.datasets:
            name = dataset_type_name(dataset)
            type_names.append(name)
            uid = dataset.first_value(SOP_CLASS_UID)
            fold = folder.fold(name, "information-object" if uid else "query-result", dataset)
            if uid:
                fold.extras["dicom_sop_class_uid"] = uid
                registered = sop_class_name(uid)
                if registered:
                    fold.extras["dicom_sop_class_name"] = registered
            if dataset.file_meta:
                folder.fold("FileMetaInformation", "file-meta", DicomItem(elements=dataset.file_meta, path=""))

        types: List[Type] = [_vr_type(vr) for vr in folder.vrs]
        types.extend(_record(fold, _type_description(fold)) for fold in folder.types.values())

        trees = []
        for index, dataset in enumerate(source.datasets):
            tree = _content_tree(dataset)
            if tree is not None:
                trees.append({"dataset": index, "typeName": type_names[index], **tree})

        pixel = [entry for dataset in source.datasets for entry in map(_pixel_entry, dataset.pixel_data)]
        extras: Dict[str, Any] = {
            "dicom_form": source.form,
            "dicom_datasets": [
                _dataset_summary(dataset, name, fileset) for dataset, name in zip(source.datasets, type_names)
            ],
            "dicom_pixel_data": {
                "statement": PIXEL_DATA_BOUNDARY_STATEMENT,
                "present": bool(pixel),
                "read": False,
                "stored": False,
                "elements": pixel,
            },
            "dicom_values": {"inModel": False, "statement": DICOM_VALUE_STATEMENT},
            "source_retention": {"verbatim": False, "reason": SOURCE_RETENTION_REASON},
        }
        if trees:
            extras["dicom_sr_content_trees"] = trees
        if len(source.datasets) > 1:
            extras["dicom_study_set"] = {
                "datasets": len(source.datasets),
                "distinctStudies": _distinct_count(source.datasets, _STUDY_INSTANCE_UID),
                "distinctSeries": _distinct_count(source.datasets, _SERIES_INSTANCE_UID),
            }
        if fileset:
            extras["dicom_fileset"] = {
                "root": source.fileset_root,
                "skippedMembers": [{"path": path, "reason": reason} for path, reason in source.skipped_members],
            }
        limits = _declared_limits(source)
        if limits:
            extras["dicom_declared_limits"] = limits

        title = _title(type_names, source.datasets)
        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            identity=ApiIdentity(name=title, namespace=DICOM_NAMESPACE),
            title=title,
            types=types,
            # The verbatim upload is patient data (and, for Part 10, pixel data); the fidelity bag
            # keeps only its shape.
            raw={"dicom": {"form": source.form, "datasets": len(source.datasets)}} if include_raw else None,
            extras=extras,
        )
        return normalize_ordering(api)
