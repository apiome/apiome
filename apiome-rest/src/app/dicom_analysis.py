"""DICOM native-analysis extractor — FMT-6.7 (#5451).

The normalizer (:mod:`app.dicom_normalizer`) folds a DICOM upload's datasets into types. This
extractor describes the upload itself, every element in source order, in DICOM's own vocabulary:

.. code-block:: text

    dataset               SOP class, modality, transfer syntax; pixel data present / read
      file-meta           the Part 10 file meta group
        attribute         (0002,0010) TransferSyntaxUID — tag, VR, length
      attribute           (0010,0010) PatientName — tag, VR, VM, length; the value (policy-governed)
      sequence            (0008,1140) ReferencedImageSequence
        item              one item — its own attributes
      sequence            (0040,A730) ContentSequence
        content-item      an SR content item: value type, relationship, concept name
      pixel-data          (7FE0,0010) — VR and declared length; read: false

The honesty contract
--------------------
* **Pixel data is never read.** A ``pixel-data`` node says the element is present, its VR and its
  declared length (or fragment count), with ``read: false`` — and carries no value. Each one is also
  an informational warning, so the skip is stated wherever the record is read.
* **Values are payload.** Attribute values sit only in ``value``, which the value-visibility policy
  governs: at the default (``structural``) a stored record keeps presence and length, so no
  patient-identifying value is stored. Attributes on a node are structure — tag, VR, VM, the few
  values that describe structure (SOP class, transfer syntax, an SR content item's value type and
  concept name) — never a patient's, study's or instance's value.
* **Positions are checked.** A Part 10 element carries its byte offset and length; a DICOM JSON
  attribute carries its JSON pointer.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from .dicom_dictionary import (
    CONCEPT_NAME_CODE_SEQUENCE,
    CONTENT_SEQUENCE,
    PIXEL_DATA_BOUNDARY_STATEMENT,
    SOP_CLASS_UID,
    attribute_info,
    is_identifying,
    is_private,
    is_private_creator,
    sop_class_name,
    tag_text,
)
from .dicom_model import (
    FORM_PART10,
    VALUE_INLINE,
    VALUE_PIXEL_SKIPPED,
    VALUE_SEQUENCE,
    DicomDataset,
    DicomDocument,
    DicomElement,
    DicomItem,
    PixelDataSkip,
)
from .dicom_normalizer import attribute_field_name, dataset_type_name
from .payload_analysis import (
    MAX_TREE_DEPTH,
    MAX_TREE_NODES,
    SEVERITY_INFO,
    AnalysisWarning,
    AnalyzerCapabilities,
    AnalyzerInfo,
    PayloadAnalysisDocument,
    SourceLocation,
    analyzer_capabilities,
)
from .payload_analyzer import NativeNode, analysis_limits, build_analysis_document

__all__ = [
    "DICOM_ANALYZER_KEY",
    "DICOM_ANALYZER_VERSION",
    "KIND_ATTRIBUTE",
    "KIND_CONTENT_ITEM",
    "KIND_DATASET",
    "KIND_FILE_META",
    "KIND_ITEM",
    "KIND_PIXEL_DATA",
    "KIND_SEQUENCE",
    "WARNING_FILESET_MEMBER_SKIPPED",
    "WARNING_MEDIA_STORAGE_MISMATCH",
    "WARNING_PIXEL_DATA_NOT_READ",
    "WARNING_PRIVATE_ATTRIBUTES",
    "analyze_dicom",
    "dicom_capabilities",
]

#: Analyzer key recorded on every record this module produces.
DICOM_ANALYZER_KEY = "dicom"
#: Version of this extractor.
DICOM_ANALYZER_VERSION = "1.0.0"

KIND_DATASET = "dataset"
KIND_FILE_META = "file-meta"
KIND_ATTRIBUTE = "attribute"
KIND_SEQUENCE = "sequence"
KIND_ITEM = "item"
KIND_CONTENT_ITEM = "content-item"
KIND_PIXEL_DATA = "pixel-data"

#: Emitted once per pixel-data element: present, stepped over, never read.
WARNING_PIXEL_DATA_NOT_READ = "dicom.pixel_data_not_read"
#: Emitted when a dataset carries private attributes, whose meaning is not modelled.
WARNING_PRIVATE_ATTRIBUTES = "dicom.private_attributes_not_modelled"
#: Emitted when a Part 10 file's meta group names a different SOP class than its dataset.
WARNING_MEDIA_STORAGE_MISMATCH = "dicom.media_storage_sop_class_mismatch"
#: Emitted for an archive member that was not read as DICOM.
WARNING_FILESET_MEMBER_SKIPPED = "dicom.fileset_member_skipped"

_VALUE_TYPE = 0x0040A040
_RELATIONSHIP_TYPE = 0x0040A010
_CODE_VALUE = 0x00080100
_CODING_SCHEME = 0x00080102
_CODE_MEANING = 0x00080104
_MODALITY = 0x00080060
_MEDIA_STORAGE_SOP_CLASS = 0x00020002


def dicom_capabilities(*, max_nodes: int = MAX_TREE_NODES) -> AnalyzerCapabilities:
    """Return what this extractor models, and what it knowingly does not.

    Args:
        max_nodes: The node budget the record was produced under.

    Returns:
        The :class:`~app.payload_analysis.AnalyzerCapabilities` for a DICOM analysis.
    """
    return analyzer_capabilities(
        supported=[
            "dicom.part10_file_meta",
            "dicom.explicit_vr_little_endian",
            "dicom.implicit_vr_little_endian",
            "dicom.explicit_vr_big_endian",
            "dicom.deflated_dataset",
            "dicom.encapsulated_transfer_syntaxes",
            "dicom.json_model",
            "dicom.attributes",
            "dicom.value_representations",
            "dicom.value_multiplicity",
            "dicom.sequences",
            "dicom.undefined_length_sequences",
            "dicom.unknown_vr_sequences",
            "dicom.structured_report_content_tree",
            "dicom.query_results",
            "dicom.private_attribute_structure",
            "dicom.byte_offsets",
        ],
        unsupported=[
            "dicom.pixel_data",
            "dicom.overlay_data",
            "dicom.private_attribute_meaning",
            "dicom.iod_module_validation",
            "dicom.iso2022_character_sets",
            "dicom.part10_in_archives",
            "dicom.sr_template_validation",
        ],
        limits=analysis_limits(max_nodes=max_nodes),
    )


# ===========================================================================
# Node construction
# ===========================================================================


def _location(element: DicomElement, ordinal: int, label: Optional[str]) -> SourceLocation:
    length = None
    if element.offset is not None and element.header_length is not None and element.value_length is not None:
        length = element.header_length + element.value_length
    return SourceLocation(
        file=label,
        offset=element.offset,
        length=length,
        ordinal=ordinal,
        path=element.path,
    )


def _element_attributes(element: DicomElement) -> Dict[str, object]:
    info = attribute_info(element.tag)
    attributes: Dict[str, object] = {"tag": tag_text(element.tag), "vr": element.vr, "valueForm": element.value_form}
    if info.keyword:
        attributes["keyword"] = info.keyword
    if info.vm:
        attributes["vm"] = info.vm
    if element.value_form != VALUE_SEQUENCE:
        attributes["valueCount"] = element.multiplicity
    if not element.vr_explicit:
        attributes["vrImplicit"] = True
    if info.retired:
        attributes["retired"] = True
    if is_private(element.tag):
        attributes["private"] = True
    if is_identifying(element.tag):
        attributes["patientIdentifying"] = True
    return attributes


def _pixel_node(element: DicomElement, skip: PixelDataSkip, ordinal: int, label: Optional[str]) -> NativeNode:
    attributes: Dict[str, object] = {"tag": tag_text(skip.tag), "vr": skip.vr, "read": False, "stored": False}
    if skip.declared_length is not None:
        attributes["declaredLength"] = skip.declared_length
    if skip.fragments is not None:
        attributes["encapsulatedFragments"] = skip.fragments
    if skip.json_form is not None:
        attributes["jsonForm"] = skip.json_form
    return NativeNode(
        kind=KIND_PIXEL_DATA,
        name=attribute_field_name(skip.tag),
        label=attribute_info(skip.tag).name,
        ordinal=ordinal,
        attributes=attributes,
        location=_location(element, ordinal, label),
        value_present=True,
        value_length=skip.declared_length,
        value=None,
    )


def _content_attributes(item: DicomItem) -> Dict[str, object]:
    """An SR content item's structure: value type, relationship, concept name — never its value."""
    attributes: Dict[str, object] = {}
    for name, tag in (("valueType", _VALUE_TYPE), ("relationshipType", _RELATIONSHIP_TYPE)):
        value = item.first_value(tag)
        if value:
            attributes[name] = value
    concept = item.element(CONCEPT_NAME_CODE_SEQUENCE)
    if concept is not None and concept.items:
        code = concept.items[0]
        for name, tag in (
            ("conceptCode", _CODE_VALUE),
            ("conceptScheme", _CODING_SCHEME),
            ("conceptMeaning", _CODE_MEANING),
        ):
            value = code.first_value(tag)
            if value:
                attributes[name] = value
    return attributes


def _item_node(
    element: DicomElement, item: DicomItem, ordinal: int, label: Optional[str], content: bool
) -> NativeNode:
    attributes: Dict[str, object] = {"attributeCount": len(item.elements)}
    if content:
        attributes.update(_content_attributes(item))
    return NativeNode(
        kind=KIND_CONTENT_ITEM if content else KIND_ITEM,
        name=str(attributes.get("valueType") or "item") if content else "item",
        label=str(attributes.get("conceptMeaning")) if content and attributes.get("conceptMeaning") else None,
        ordinal=ordinal,
        attributes=attributes,
        location=SourceLocation(file=label, offset=item.offset, length=item.length, ordinal=ordinal, path=item.path),
        children=lambda: _element_nodes(item.elements, label),
    )


def _element_node(element: DicomElement, ordinal: int, label: Optional[str]) -> NativeNode:
    if element.value_form == VALUE_PIXEL_SKIPPED and element.pixel is not None:
        return _pixel_node(element, element.pixel, ordinal, label)
    info = attribute_info(element.tag)
    if element.value_form == VALUE_SEQUENCE:
        content = element.tag == CONTENT_SEQUENCE
        return NativeNode(
            kind=KIND_SEQUENCE,
            name=attribute_field_name(element.tag),
            label=info.name,
            ordinal=ordinal,
            attributes={**_element_attributes(element), "itemCount": len(element.items)},
            location=_location(element, ordinal, label),
            value_present=bool(element.items),
            children=lambda: [
                _item_node(element, item, index, label, content) for index, item in enumerate(element.items)
            ],
        )
    value = "\\".join(element.values) if element.value_form == VALUE_INLINE else None
    return NativeNode(
        kind=KIND_ATTRIBUTE,
        name=attribute_field_name(element.tag),
        label=info.name or ("Private Creator" if is_private_creator(element.tag) else None),
        ordinal=ordinal,
        attributes=_element_attributes(element),
        location=_location(element, ordinal, label),
        value_present=bool(element.value_length) or bool(element.values),
        value_length=element.value_length if element.value_length is not None else (len(value) if value else 0),
        value=value,
    )


def _element_nodes(elements, label: Optional[str]) -> List[NativeNode]:
    return [_element_node(element, ordinal, label) for ordinal, element in enumerate(elements)]


def _dataset_node(dataset: DicomDataset, ordinal: int, fileset: bool) -> NativeNode:
    label = dataset.label if fileset else None
    attributes: Dict[str, object] = {
        "form": dataset.form,
        "typeName": dataset_type_name(dataset),
        "attributeCount": len(dataset.elements),
        "pixelDataPresent": bool(dataset.pixel_data),
        "pixelDataRead": False,
        "structuredReport": dataset.element(_VALUE_TYPE) is not None
        and dataset.element(CONTENT_SEQUENCE) is not None,
    }
    uid = dataset.first_value(SOP_CLASS_UID)
    if uid:
        attributes["sopClassUid"] = uid
        name = sop_class_name(uid)
        if name:
            attributes["sopClassName"] = name
    modality = dataset.first_value(_MODALITY)
    if modality:
        attributes["modality"] = modality
    if dataset.transfer_syntax:
        attributes["transferSyntaxUid"] = dataset.transfer_syntax
        attributes["transferSyntaxName"] = dataset.transfer_syntax_name
        attributes["deflated"] = dataset.deflated

    def children() -> List[NativeNode]:
        nodes: List[NativeNode] = []
        if dataset.file_meta:
            nodes.append(
                NativeNode(
                    kind=KIND_FILE_META,
                    name="FileMetaInformation",
                    label="File meta information",
                    ordinal=0,
                    attributes={"attributeCount": len(dataset.file_meta)},
                    location=SourceLocation(offset=132, ordinal=0, path="(0002,xxxx)"),
                    children=lambda: _element_nodes(dataset.file_meta, label),
                )
            )
        offset = len(nodes)
        nodes.extend(
            _element_node(element, ordinal + offset, label) for ordinal, element in enumerate(dataset.elements)
        )
        return nodes

    return NativeNode(
        kind=KIND_DATASET,
        name=str(attributes["typeName"]),
        label=sop_class_name(uid) if uid else "Query result",
        ordinal=ordinal,
        attributes=attributes,
        location=SourceLocation(file=label, ordinal=ordinal, path=dataset.path or "/"),
        children=children,
    )


# ===========================================================================
# Warnings
# ===========================================================================


def _info(code: str, message: str) -> AnalysisWarning:
    return AnalysisWarning(code=code, severity=SEVERITY_INFO, message=message)


def _warnings(document: DicomDocument) -> List[AnalysisWarning]:
    warnings: List[AnalysisWarning] = []
    for dataset, skip in document.all_pixel_data():
        length = (
            f"{skip.declared_length} byte(s)"
            if skip.declared_length is not None
            else f"{skip.fragments} encapsulated fragment(s)"
            if skip.fragments is not None
            else f"a {skip.json_form} value"
            if skip.json_form
            else "an empty value"
        )
        warnings.append(
            _info(
                WARNING_PIXEL_DATA_NOT_READ,
                f"{tag_text(skip.tag)} {attribute_info(skip.tag).name or 'pixel data'} ({skip.vr}, {length}) "
                "is present and was stepped over without being read. " + PIXEL_DATA_BOUNDARY_STATEMENT,
            )
        )
    for index, dataset in enumerate(document.datasets):
        private = sum(
            1 for element in dataset.elements if is_private(element.tag) and not is_private_creator(element.tag)
        )
        if private:
            warnings.append(
                _info(
                    WARNING_PRIVATE_ATTRIBUTES,
                    f"Dataset {index} carries {private} private attribute(s). Their tag, VR and length "
                    "are recorded; their meaning is not in the DICOM data dictionary and is not modelled.",
                )
            )
        media = dataset.meta_value(_MEDIA_STORAGE_SOP_CLASS)
        uid = dataset.first_value(SOP_CLASS_UID)
        if media and uid and media != uid:
            warnings.append(
                _info(
                    WARNING_MEDIA_STORAGE_MISMATCH,
                    f"The file meta group names SOP class {media} but the dataset names {uid}. Both are "
                    "recorded; the dataset's is used.",
                )
            )
    for path, reason in document.skipped_members:
        warnings.append(_info(WARNING_FILESET_MEMBER_SKIPPED, f"Archive member {path} was not read: {reason}."))
    return warnings


# ===========================================================================
# Entry point
# ===========================================================================


def analyze_dicom(
    document: DicomDocument,
    *,
    source: Optional[object] = None,
    source_format: str = DICOM_ANALYZER_KEY,
    max_nodes: int = MAX_TREE_NODES,
    max_depth: int = MAX_TREE_DEPTH,
) -> PayloadAnalysisDocument:
    """Describe a parsed DICOM upload as a payload analysis.

    Args:
        document: The parsed document (:mod:`app.dicom_parser`).
        source: The material hashed into ``source_hash``; defaults to the document's own — the JSON
            text, or the Part 10 bytes with every pixel-data value excised, so the record never
            digests image content.
        source_format: Adapter key recorded on the record.
        max_nodes: Node budget.
        max_depth: Depth budget.

    Returns:
        The analysis document, with observed values still on it —
        :func:`app.payload_analysis_store.store_analysis` applies the value-visibility policy.
    """
    material = document.source if source is None or document.form == FORM_PART10 else source
    fileset = document.fileset_root is not None
    return build_analysis_document(
        roots=[_dataset_node(dataset, index, fileset) for index, dataset in enumerate(document.datasets)],
        analyzer=AnalyzerInfo(key=DICOM_ANALYZER_KEY, version=DICOM_ANALYZER_VERSION),
        capabilities=dicom_capabilities(max_nodes=max_nodes),
        source=material,  # type: ignore[arg-type]
        source_format=source_format,
        warnings=_warnings(document),
        max_nodes=max_nodes,
        max_depth=max_depth,
    )
