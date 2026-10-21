"""NACHA ACH → canonical model normalizer — FMT-6.6 (#5450).

Maps a parsed :class:`~app.nacha_parser.NachaFile` into a :class:`~app.canonical_model.CanonicalApi`
of paradigm :attr:`~app.canonical_model.ApiParadigm.DATA_SCHEMA` whose types are the file's own
structure:

.. code-block:: text

    AchFile        fileHeader: FileHeader · batches: [Batch] · fileControl: FileControl
    Batch          batchHeader: BatchHeader · entries: [EntryDetail] · batchControl: BatchControl
    EntryDetail    the entry's fields · addenda05: [Addenda05] · addenda99: [Addenda99] …

Every record type is one record whose fields are the layout's fields
(:mod:`app.nacha_records`), in position order, each carrying its positions, length and kind in
``extras``. An addenda list appears on ``EntryDetail`` only for the addenda types the file carries.
Field values are fixed-width digit or text strings, so every field is a ``string``.

No payload value enters the model: account numbers, names and amounts belong to the payload
analysis, where the value-visibility policy governs them. ``extras`` records structure — the file's
SEC codes and batches — and every control total as declared versus observed
(:func:`app.nacha_controls.control_totals_extras`).
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

from .canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Type,
    TypeKind,
    TypeRef,
)
from .nacha_controls import control_totals_extras
from .nacha_parser import NachaFile
from .nacha_records import (
    BATCH_CONTROL,
    BATCH_HEADER,
    ENTRY_DETAIL,
    FILE_CONTROL,
    FILE_HEADER,
    NachaFieldSpec,
    addenda_layout,
)
from .normalizer import Keys, Normalizer, normalize_ordering

__all__ = ["NACHA_NAMESPACE", "NachaNormalizer", "addenda_type_name"]

_FORMAT_KEY = "nacha"
#: The namespace every NACHA type key is minted under.
NACHA_NAMESPACE = "NACHA-ACH"


def addenda_type_name(addenda_type: str) -> str:
    """The record type name for an addenda type code (``05`` → ``Addenda05``)."""
    return f"Addenda{addenda_type}"


def _key(name: str) -> str:
    return Keys.type(name, NACHA_NAMESPACE)


def _layout_type(
    name: str, layout: Sequence[NachaFieldSpec], extra_fields: Sequence[CanonicalField] = ()
) -> Type:
    """One record type from a fixed-width layout, plus any structural fields after it."""
    type_key = _key(name)
    fields: List[CanonicalField] = []
    for number, spec in enumerate(layout, start=1):
        extras: Dict[str, Any] = {
            "nacha_position": [spec.start, spec.end],
            "nacha_length": spec.length,
            "nacha_field_kind": spec.kind,
        }
        if spec.note:
            extras["nacha_note"] = spec.note
        fields.append(
            CanonicalField(
                key=Keys.field(type_key, spec.name),
                name=spec.name,
                description=spec.label,
                type=TypeRef(name="string", nullable=False),
                field_number=number,
                extras=extras,
            )
        )
    for number, field in enumerate(extra_fields, start=len(fields) + 1):
        fields.append(
            field.model_copy(update={"key": Keys.field(type_key, field.name), "field_number": number})
        )
    return Type(
        key=type_key,
        name=name,
        kind=TypeKind.RECORD,
        fields=tuple(fields),
        extras={"nacha_kind": "record"},
    )


def _structure_field(name: str, type_name: str, *, repeated: bool, description: str) -> CanonicalField:
    """A field that holds another record (``fileHeader``) or a list of them (``batches``)."""
    ref = TypeRef(name=_key(type_name), nullable=False)
    if repeated:
        ref = TypeRef(item=ref, nullable=False)
    return CanonicalField(
        key=name,  # re-keyed by _layout_type / _container
        name=name,
        description=description,
        type=ref,
        extras={"nacha_kind": "structure"},
    )


def _container(name: str, fields: Sequence[CanonicalField], description: str) -> Type:
    """A structure-only record type (``AchFile``, ``Batch``)."""
    type_key = _key(name)
    return Type(
        key=type_key,
        name=name,
        kind=TypeKind.RECORD,
        description=description,
        fields=tuple(
            field.model_copy(update={"key": Keys.field(type_key, field.name), "field_number": number})
            for number, field in enumerate(fields, start=1)
        ),
        extras={"nacha_kind": "structure"},
    )


def _addenda_types(file: NachaFile) -> List[str]:
    """Addenda type codes the file carries, in first-seen order."""
    seen: List[str] = []
    for _, entry in file.all_entries():
        for record in entry.addenda:
            if record.addenda_type not in seen:
                seen.append(record.addenda_type)
    return seen


def _types(file: NachaFile) -> List[Type]:
    """Every record and structure type for ``file``."""
    addenda = _addenda_types(file)
    entry_extra = [
        _structure_field(
            f"addenda{code}",
            addenda_type_name(code),
            repeated=True,
            description=f"Addenda records of type {code} that follow the entry",
        )
        for code in addenda
    ]
    return [
        _container(
            "AchFile",
            [
                _structure_field(
                    "fileHeader", "FileHeader", repeated=False, description="File header record (1)"
                ),
                _structure_field("batches", "Batch", repeated=True, description="Batches in file order"),
                _structure_field(
                    "fileControl", "FileControl", repeated=False, description="File control record (9)"
                ),
            ],
            "A NACHA ACH file",
        ),
        _container(
            "Batch",
            [
                _structure_field(
                    "batchHeader", "BatchHeader", repeated=False, description="Batch header record (5)"
                ),
                _structure_field(
                    "entries", "EntryDetail", repeated=True, description="Entry detail records (6)"
                ),
                _structure_field(
                    "batchControl", "BatchControl", repeated=False, description="Batch control record (8)"
                ),
            ],
            "One ACH batch",
        ),
        _layout_type("FileHeader", FILE_HEADER),
        _layout_type("BatchHeader", BATCH_HEADER),
        _layout_type("EntryDetail", ENTRY_DETAIL, entry_extra),
        *[_layout_type(addenda_type_name(code), addenda_layout(code)) for code in addenda],
        _layout_type("BatchControl", BATCH_CONTROL),
        _layout_type("FileControl", FILE_CONTROL),
    ]


def _batch_summary(file: NachaFile) -> List[Dict[str, Any]]:
    """Per-batch structure: number, service class, SEC code, entry and addenda counts."""
    return [
        {
            "batchNumber": batch.batch_number,
            "serviceClassCode": batch.header.field("serviceClassCode"),
            "standardEntryClassCode": batch.sec_code,
            "entryCount": len(batch.entries),
            "addendaCount": batch.addenda_count,
        }
        for batch in file.batches
    ]


def _sec_codes(file: NachaFile) -> Tuple[str, ...]:
    """SEC codes in first-seen order."""
    codes: List[str] = []
    for batch in file.batches:
        if batch.sec_code and batch.sec_code not in codes:
            codes.append(batch.sec_code)
    return tuple(codes)


class NachaNormalizer(Normalizer, register=True):
    """Normalize a parsed ACH file into a :class:`CanonicalApi`."""

    format = _FORMAT_KEY
    paradigm = ApiParadigm.DATA_SCHEMA

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(source, NachaFile):
            raise ValueError("NACHA source must be a NachaFile (see app.nacha_parser.parse_nacha)")

        sec_codes = _sec_codes(source)
        title = "NACHA ACH file"
        if sec_codes:
            title += f" ({', '.join(sec_codes)})"
        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            identity=ApiIdentity(name=title, namespace=NACHA_NAMESPACE),
            title=title,
            types=_types(source),
            raw={"nacha": source.raw} if include_raw else None,
            extras={
                "nacha_file": {
                    "fileCreationDate": source.header.field("fileCreationDate"),
                    "fileIdModifier": source.header.field("fileIdModifier"),
                    "recordSize": source.header.field("recordSize"),
                    "blockingFactor": source.header.field("blockingFactor"),
                    "batchCount": len(source.batches),
                    "entryCount": sum(len(batch.entries) for batch in source.batches),
                    "addendaCount": sum(batch.addenda_count for batch in source.batches),
                    "paddingRecords": source.padding_records,
                },
                "nacha_sec_codes": list(sec_codes),
                "nacha_batches": _batch_summary(source),
                "nacha_control_totals": control_totals_extras(source),
            },
        )
        return normalize_ordering(api)
