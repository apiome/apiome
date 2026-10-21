"""NACHA ACH native-analysis extractor — FMT-6.6 (#5450).

The normalizer (:mod:`app.nacha_normalizer`) turns an ACH file's record layouts into types. This
extractor describes the file itself, every record in source order, in ACH's own vocabulary:

.. code-block:: text

    file                  file header facts; the file control's declared vs observed totals
      record              fileHeader — its fields
      batch               batch number, service class, SEC code; declared vs observed totals
        record            batchHeader — its fields
        entry             transaction code, direction, prenote, addenda indicator, check digit
          field           …the entry's fields
          addenda         addenda type 05 / 98 / 99 — its fields
        record            batchControl — its fields
      record              fileControl — its fields

The honesty contract — X12's, through the shared EDI base
---------------------------------------------------------
* **Declared versus observed.** Every total a batch control or file control record declares — entry
  and addenda count, entry hash, total debit, total credit, batch count, block count — is recomputed
  (:mod:`app.nacha_controls`) and recorded beside the declaration as ``declared*`` / ``observed*``
  attributes, and each disagreement is an informational warning: read, not rejected.
* **Values are payload.** Account numbers, names, amounts and identification numbers sit only in
  field nodes' ``value``, which the value-visibility policy governs. Attributes carry structure:
  record types, codes, counts and the control totals (aggregates, not any one payment).
* **Positions are checked.** Every record and every field carries the line, offset and length it
  was cut from.
* **Operating rules are not consulted.** The NACHA Operating Rules' SEC-code requirements, return
  reason semantics and IAT layouts are not evaluated; an ``IAT`` batch is read with the domestic
  layouts and the record says so.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from .edi_analysis_base import (
    ControlCount,
    envelope_node_budget,
    implementation_guide_statement,
    int_or_none,
)
from .nacha_controls import batch_control_counts, file_control_counts
from .nacha_parser import NachaBatch, NachaEntry, NachaFile, NachaRecord
from .nacha_records import (
    ADDENDA_LAYOUTS,
    FIELD_ALPHANUMERIC,
    RECORD_NAMES,
    credit_or_debit,
    is_prenote,
    record_fields,
    routing_check_digit,
)
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
    "KIND_ADDENDA",
    "KIND_BATCH",
    "KIND_ENTRY",
    "KIND_FIELD",
    "KIND_FILE",
    "KIND_RECORD",
    "NACHA_ANALYZER_KEY",
    "NACHA_ANALYZER_VERSION",
    "NACHA_OPERATING_RULES_STATEMENT",
    "WARNING_ADDENDA_INDICATOR",
    "WARNING_CONTROL_TOTAL_MISMATCH",
    "WARNING_IAT_LAYOUT",
    "WARNING_UNMODELLED_ADDENDA",
    "analyze_nacha",
    "nacha_capabilities",
]

#: Analyzer key recorded on every record this module produces.
NACHA_ANALYZER_KEY = "nacha"
#: Version of this extractor.
NACHA_ANALYZER_VERSION = "1.0.0"

KIND_FILE = "file"
KIND_BATCH = "batch"
KIND_ENTRY = "entry"
KIND_ADDENDA = "addenda"
KIND_RECORD = "record"
KIND_FIELD = "field"

#: Emitted for every batch or file control total that disagrees with what was observed.
WARNING_CONTROL_TOTAL_MISMATCH = "nacha.control_total_mismatch"
#: Emitted when an entry's addenda record indicator disagrees with the addenda that follow it.
WARNING_ADDENDA_INDICATOR = "nacha.addenda_indicator_mismatch"
#: Emitted for an addenda type code whose layout is not modelled (its content is kept whole).
WARNING_UNMODELLED_ADDENDA = "nacha.addenda_layout_not_modelled"
#: Emitted for an IAT batch, which is read with the domestic layouts.
WARNING_IAT_LAYOUT = "nacha.iat_layout_not_modelled"

#: The statement the capability declaration and the format registry both carry.
NACHA_OPERATING_RULES_STATEMENT = implementation_guide_statement(
    "NACHA ACH record format (94-character records, types 1/5/6/7/8/9)",
    ("the NACHA Operating Rules' SEC-code requirements", "IAT layouts", "ODFI or bank file specs"),
)

#: Header facts lifted into attributes: structure, never payload.
_FILE_ATTRIBUTES = (
    "fileCreationDate",
    "fileCreationTime",
    "fileIdModifier",
    "recordSize",
    "blockingFactor",
    "formatCode",
)
_BATCH_ATTRIBUTES = (
    "serviceClassCode",
    "standardEntryClassCode",
    "companyEntryDescription",
    "effectiveEntryDate",
    "originatorStatusCode",
)


#: Control record → the phrase a mismatch warning names it by.
_RECORD_PHRASE = {"batchControl": "batch control record (8)", "fileControl": "file control record (9)"}


def nacha_capabilities(*, max_nodes: int = MAX_TREE_NODES) -> AnalyzerCapabilities:
    """Return what this extractor models, and what it knowingly does not.

    Args:
        max_nodes: The node budget the record was produced under.

    Returns:
        The :class:`~app.payload_analysis.AnalyzerCapabilities` for an ACH analysis.
    """
    return analyzer_capabilities(
        supported=[
            "nacha.file_header",
            "nacha.batch",
            "nacha.entry_detail",
            "nacha.addenda_05",
            "nacha.addenda_98",
            "nacha.addenda_99",
            "nacha.batch_control_totals",
            "nacha.file_control_totals",
            "nacha.entry_hash",
            "nacha.block_count",
            "nacha.transaction_direction",
            "nacha.routing_check_digit",
            "nacha.fixed_width_fields",
            "nacha.byte_offsets",
        ],
        unsupported=[
            "nacha.operating_rules_validation",
            "nacha.iat_layouts",
            "nacha.return_reason_semantics",
        ],
        limits=analysis_limits(max_nodes=max_nodes),
    )


# ===========================================================================
# Node construction
# ===========================================================================


def _record_location(record: NachaRecord, *, ordinal: int, path: str) -> SourceLocation:
    return SourceLocation(
        line=record.line,
        column=record.column,
        offset=record.offset,
        length=record.length,
        ordinal=ordinal,
        path=path,
    )


def _field_nodes(record: NachaRecord, *, path: str) -> List[NativeNode]:
    """One value node per field, positions included.

    Fixed-width fields are always written, so every one is ``value_present``. Alphanumeric fields
    are left-justified and space-padded: the padding is dropped, so an all-blank field is present
    and empty (length 0). Numeric fields keep their leading zeros.
    """
    nodes: List[NativeNode] = []
    for ordinal, (spec, raw) in enumerate(record_fields(record.text)):
        value = raw.rstrip() if spec.kind == FIELD_ALPHANUMERIC else raw
        nodes.append(
            NativeNode(
                kind=KIND_FIELD,
                name=spec.name,
                label=spec.label,
                ordinal=ordinal,
                attributes={"start": spec.start, "end": spec.end, "fieldKind": spec.kind},
                location=SourceLocation(
                    line=record.line,
                    column=record.column + spec.start - 1,
                    offset=record.offset + spec.start - 1,
                    length=spec.length,
                    ordinal=ordinal,
                    path=f"{path}/{spec.name}",
                ),
                value_present=True,
                value_length=len(value),
                value=value,
            )
        )
    return nodes


def _record_node(record: NachaRecord, *, name: str, ordinal: int, parent: str) -> NativeNode:
    """A header or control record: its type code and its fields."""
    path = f"{parent}/{name}"
    return NativeNode(
        kind=KIND_RECORD,
        name=name,
        label=RECORD_NAMES[record.record_type],
        ordinal=ordinal,
        attributes={"recordTypeCode": record.record_type},
        location=_record_location(record, ordinal=ordinal, path=path),
        children=lambda: _field_nodes(record, path=path),
    )


def _set_if(attributes: Dict[str, object], name: str, value: str) -> None:
    text = value.strip()
    if text:
        attributes[name] = text


def _control_attributes(attributes: Dict[str, object], counts: List[ControlCount]) -> None:
    """Record each control total as ``declared<Field>`` / ``observed<Field>``, plus one verdict."""
    verdicts = []
    for count in counts:
        field = count.trailer.split(".", 1)[1]
        suffix = field[0].upper() + field[1:]
        attributes[f"observed{suffix}"] = count.observed
        if count.declared is not None:
            attributes[f"declared{suffix}"] = count.declared
            verdicts.append(count.consistent)
    if verdicts:
        attributes["controlTotalsConsistent"] = all(verdicts)


def _addenda_node(record: NachaRecord, *, ordinal: int, entry_path: str) -> NativeNode:
    path = f"{entry_path}/7[{ordinal}]"
    return NativeNode(
        kind=KIND_ADDENDA,
        name=f"addenda{record.addenda_type}",
        label=f"Addenda {record.addenda_type}",
        ordinal=ordinal,
        attributes={
            "addendaTypeCode": record.addenda_type,
            "layoutModelled": record.addenda_type in ADDENDA_LAYOUTS,
        },
        location=_record_location(record, ordinal=ordinal, path=path),
        children=lambda: _field_nodes(record, path=path),
    )


def _entry_node(entry: NachaEntry, *, ordinal: int, batch_path: str) -> NativeNode:
    """One entry detail record with its addenda.

    ``checkDigitValid`` recomputes the ABA check digit of the receiving DFI routing number; the
    routing number itself is not looked up.
    """
    path = f"{batch_path}/6[{ordinal}]"
    record = entry.record
    code = entry.transaction_code
    indicator = record.field("addendaRecordIndicator")
    expected = routing_check_digit(record.field("receivingDfiIdentification"))
    written = int_or_none(record.field("checkDigit"))
    attributes: Dict[str, object] = {
        "transactionCode": code,
        "prenote": is_prenote(code),
        "addendaRecordIndicator": indicator,
        "addendaCount": len(entry.addenda),
        "traceNumber": entry.trace_number,
    }
    direction = credit_or_debit(code)
    if direction is not None:
        attributes["direction"] = direction
    if expected is not None and written is not None:
        attributes["checkDigitValid"] = expected == written
    return NativeNode(
        kind=KIND_ENTRY,
        name=f"entry{code}",
        label=f"Entry {entry.trace_number}",
        ordinal=ordinal,
        attributes=attributes,
        location=_record_location(record, ordinal=ordinal, path=path),
        children=lambda: (
            _field_nodes(record, path=path)
            + [
                _addenda_node(addenda, ordinal=index, entry_path=path)
                for index, addenda in enumerate(entry.addenda)
            ]
        ),
    )


def _batch_node(batch: NachaBatch, *, ordinal: int) -> NativeNode:
    path = f"FILE/5[{ordinal}]"
    attributes: Dict[str, object] = {
        "batchNumber": batch.batch_number,
        "entryCount": len(batch.entries),
        "addendaCount": batch.addenda_count,
    }
    for name in _BATCH_ATTRIBUTES:
        _set_if(attributes, name, batch.header.field(name))
    _control_attributes(attributes, batch_control_counts(batch))
    sec = batch.sec_code or "batch"
    return NativeNode(
        kind=KIND_BATCH,
        name=sec,
        label=f"Batch {batch.batch_number} ({sec})",
        ordinal=ordinal,
        attributes=attributes,
        location=_record_location(batch.header, ordinal=ordinal, path=path),
        children=lambda: [
            _record_node(batch.header, name="batchHeader", ordinal=0, parent=path),
            *[
                _entry_node(entry, ordinal=index + 1, batch_path=path)
                for index, entry in enumerate(batch.entries)
            ],
            _record_node(batch.control, name="batchControl", ordinal=len(batch.entries) + 1, parent=path),
        ],
    )


def _file_node(file: NachaFile) -> NativeNode:
    path = "FILE"
    attributes: Dict[str, object] = {
        "batchCount": len(file.batches),
        "recordCount": file.record_count,
        "paddingRecords": file.padding_records,
        "operatingRulesConsulted": False,
    }
    for name in _FILE_ATTRIBUTES:
        _set_if(attributes, name, file.header.field(name))
    _control_attributes(attributes, file_control_counts(file))
    return NativeNode(
        kind=KIND_FILE,
        name="ACH",
        label="ACH file",
        ordinal=0,
        attributes=attributes,
        location=_record_location(file.header, ordinal=0, path=path),
        children=lambda: [
            _record_node(file.header, name="fileHeader", ordinal=0, parent=path),
            *[_batch_node(batch, ordinal=index + 1) for index, batch in enumerate(file.batches)],
            _record_node(file.control, name="fileControl", ordinal=len(file.batches) + 1, parent=path),
        ],
    )


# ===========================================================================
# Warnings
# ===========================================================================


def _info(code: str, message: str) -> AnalysisWarning:
    return AnalysisWarning(code=code, severity=SEVERITY_INFO, message=message)


def _record_warnings(file: NachaFile) -> List[AnalysisWarning]:
    """Addenda-indicator disagreements, unmodelled addenda layouts and IAT batches."""
    warnings: List[AnalysisWarning] = []
    unmodelled: List[str] = []
    for batch in file.batches:
        if batch.sec_code == "IAT":
            warnings.append(
                _info(
                    WARNING_IAT_LAYOUT,
                    f"Batch {batch.batch_number} is an IAT batch. Its entry and addenda records are "
                    "read with the domestic layouts, so their fields are positions, not IAT meanings.",
                )
            )
        for entry in batch.entries:
            indicator = entry.record.field("addendaRecordIndicator")
            if (indicator == "1") != bool(entry.addenda):
                warnings.append(
                    _info(
                        WARNING_ADDENDA_INDICATOR,
                        f"Entry {entry.trace_number} declares addenda record indicator {indicator!r} "
                        f"but is followed by {len(entry.addenda)} addenda record(s). Both are recorded.",
                    )
                )
            for addenda in entry.addenda:
                if addenda.addenda_type not in ADDENDA_LAYOUTS and addenda.addenda_type not in unmodelled:
                    unmodelled.append(addenda.addenda_type)
    for code in unmodelled:
        warnings.append(
            _info(
                WARNING_UNMODELLED_ADDENDA,
                f"Addenda type {code!r} has no modelled layout; its content is kept whole as one field.",
            )
        )
    return warnings


def _control_warnings(counts: List[ControlCount]) -> List[AnalysisWarning]:
    """One warning per control total that disagrees with what the file carries.

    Informational, as the shared EDI base states every disagreement: the file is still readable, so
    nothing is rejected, and both figures stay on the batch or file node.
    """
    warnings: List[AnalysisWarning] = []
    for count in counts:
        if count.consistent is not False:
            continue
        record, field = count.trailer.split(".", 1)
        warnings.append(
            _info(
                WARNING_CONTROL_TOTAL_MISMATCH,
                f"The {_RECORD_PHRASE[record]} for {count.subject} declares {field} "
                f"{count.declared}, but {count.observed} was observed. The file disagrees with "
                "itself; both figures are recorded.",
            )
        )
    return warnings


def _envelope_node_count(file: NachaFile) -> int:
    """File, its header/control records, and every batch with its header/control records."""
    return 3 + 3 * len(file.batches)


# ===========================================================================
# Entry point
# ===========================================================================


def analyze_nacha(
    file: NachaFile,
    *,
    source: Optional[str] = None,
    source_format: str = NACHA_ANALYZER_KEY,
    max_nodes: int = MAX_TREE_NODES,
    max_depth: int = MAX_TREE_DEPTH,
) -> PayloadAnalysisDocument:
    """Describe a parsed ACH file as a payload analysis.

    Args:
        file: The parsed file (:func:`app.nacha_parser.parse_nacha`).
        source: The exact text analysed; defaults to the file's retained ``raw`` text.
        source_format: Adapter key recorded on the record.
        max_nodes: Node budget. Raised, if smaller, to fit every file and batch node.
        max_depth: Depth budget; the tree is at most five levels deep.

    Returns:
        The analysis document, with observed field values still on it —
        :func:`app.payload_analysis_store.store_analysis` applies the value-visibility policy.
    """
    text = source if source is not None else file.raw
    effective_nodes = envelope_node_budget(max_nodes, _envelope_node_count(file))
    counts: List[ControlCount] = []
    for batch in file.batches:
        counts.extend(batch_control_counts(batch))
    counts.extend(file_control_counts(file))
    warnings = _control_warnings(counts) + _record_warnings(file)
    return build_analysis_document(
        roots=[_file_node(file)],
        analyzer=AnalyzerInfo(key=NACHA_ANALYZER_KEY, version=NACHA_ANALYZER_VERSION),
        capabilities=nacha_capabilities(max_nodes=effective_nodes),
        source=text,
        source_format=source_format,
        warnings=warnings,
        max_nodes=effective_nodes,
        max_depth=max_depth,
    )
