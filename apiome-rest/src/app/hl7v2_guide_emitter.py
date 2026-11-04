"""HL7 v2 segment-definition guide emitter: canonical types → an HL7 v2 message/segment definition — MFX-26.3 (#4159).

Hospital integration engines (Mirth, Rhapsody, Cloverleaf) are configured from HL7 v2 message and segment
definitions: which segments a message holds, in what order and how often, and each segment's fields with their
data type, length, optionality, repetition and table. This emitter writes one for the item's types, laid out by
the **same plan** as the X12 and UN/EDIFACT guides (:func:`app.edi_guide.plan_guide`, MFX-24.1), in three files:

* ``<Name>.hl7v2-guide.json`` — the machine-readable definition: the message, the segment definitions, the
  tables and the structure (segment groups, optionality, repetition);
* ``<Name>.hl7v2-segments.csv`` — the segment definitions, one row per field;
* ``<Name>.hl7v2-guide.md`` — the human-readable guide, with the message's abstract message syntax
  (``MSH ZPA [ZNO] { ZOR }``).

**HL7 terms.** A segment made from a type is a site-defined **Z-segment** (``ZPA``); an imported HL7 v2 message keeps
its own segments (``PID``, ``OBX``) and field sequence. A field is ``SEG-n`` (``ZPA-3``), with a data type: text
``ST``, a number ``NM`` (HL7 sends the decimal point), a date ``DT``, a time ``TM``, a timestamp one ``TS`` field
(``DTM`` from v2.6), a coded value ``IS`` (``CWE`` from v2.7) bound to a **table**, a boolean ``ID`` bound to HL7
table ``0136`` (Yes/no indicator). Each enum is a **user-defined table**, numbered from ``first_table_number``
(9001): its codes and the values they stand for. Optionality is ``R`` (required), ``O`` (optional) or ``X`` (not
used); repetition ``N`` (no), ``Y`` (unlimited) or a count. A loop is a **segment group** named after its record
(``ORDER_LINE``). The message starts with ``MSH`` — the item's own when it has one, else the standard header — with
``MSH-9`` the message type and ``MSH-12`` the version.

**Options:** ``message_type`` (``ADT^A01``; an imported item's own, else ``ZZZ^Z01``, a site-defined message),
``version`` (``2.5.1``; an imported item's own), ``default_field_length`` (199), ``max_code_length`` (20) and
``first_table_number`` (9001). :mod:`app.hl7v2_guide_validation` checks the guide.
"""

from __future__ import annotations

import csv
import io
import json
import re
from typing import Any, Dict, List, Mapping, Optional, Tuple, Union

from pydantic import Field, ValidationError, field_validator

from .canonical_model import ApiParadigm, CanonicalApi
from .edi_guide import GuideElement, GuideLoop, GuideOptions, GuideSegment, SegmentUse, plan_guide
from .emitter import (
    CapabilityProfile,
    EmitOptions,
    EmitPreconditionError,
    EmitResult,
    EmittedFile,
    Emitter,
    Loss,
    LossKind,
    LossTracker,
    Provenance,
    ProvenanceTracker,
)
from .fidelity_rulepack import CapabilityRulePack, types_only_advisory
from .lossiness import LossinessKind, LossinessSeverity
from .x12_guide_emitter import X12GuideFidelityRulePack, _base_name

__all__ = [
    "HL7V2_DATA_TYPES",
    "Hl7v2GuideEmitOptions",
    "Hl7v2GuideEmitter",
    "Hl7v2GuideFidelityRulePack",
    "abstract_syntax",
    "hl7v2_csv",
    "hl7v2_markdown",
]

_LABEL = "HL7 v2 segment guide"
#: The data types a guide may use: the ones it writes for values, and the ones the standard ``MSH`` uses.
HL7V2_DATA_TYPES = frozenset({"ST", "NM", "DT", "TM", "TS", "DTM", "ID", "IS", "CWE", "HD", "MSG", "PT", "VID"})
#: Any segment ID: a letter, then two letters or digits (``PID``, ``ZPA``).
_SEGMENT_ID_RULE = r"^[A-Z][A-Z0-9]{2}$"
#: HL7 table 0136 — Yes/no indicator.
_YES_NO = {"id": "0136", "name": "Yes/no indicator", "type": "HL7",
           "values": [{"code": "Y", "description": "Yes"}, {"code": "N", "description": "No"}]}
#: Plan loss subjects whose wording is restated for HL7 v2: subject → (pattern, replacement).
_RESTATEMENTS = {
    "decimal-implied": (r"is written with (\d+) implied decimal places: the value is sent without its decimal point",
                        r"is written as NM with at most \1 decimal places; HL7 sends the decimal point"),
    "decimal-as-real": (r"it is written as a real \(explicit decimal point\), so its precision is not fixed",
                        "it is written as NM (a number with its decimal point), so its precision is not fixed"),
    "float-as-real": (r"it is written as a real \(explicit decimal point\) of at most 15 digits",
                      "it is written as NM (a number with its decimal point)"),
    "timestamp-split": (r"it is written as two elements, its date \(CCYYMMDD\) and its time \(HHMM\[SS…\]\)",
                        "it is written as one date/time field (YYYYMMDDHHMM[SS])"),
    "segment-id-synthesized": (r"is written as segment ([A-Z0-9]{3}) \(an ID made from its name\)",
                               r"is written as the site-defined segment \1 (a Z-segment made from its name)"),
}


class Hl7v2GuideFidelityRulePack(X12GuideFidelityRulePack):
    """Fidelity rules for the HL7 v2 segment guide — MFX-26.3 (#4159).

    The X12 guide's rules (MFX-24.3) on the same plan, restated in HL7 v2 terms, plus ``table-synthesized``
    (SYNTH): an enum becomes a user-defined table whose number the export assigns.
    """

    target_label = _LABEL
    _layout_note = ("an", "HL7 v2 message", "segments of positional fields in segment groups, with HL7 data "
                    "types, lengths and tables")
    _WRITER_LOSSES = {
        **X12GuideFidelityRulePack._WRITER_LOSSES,
        "table-synthesized": (LossinessKind.SYNTH, LossinessSeverity.INFO),
    }

    def apply_options(self, options: Mapping[str, Any]) -> None:
        try:
            self._options = Hl7v2GuideEmitOptions.model_validate(dict(options))
        except ValidationError:
            self._options = Hl7v2GuideEmitOptions()

    def _writer_losses(self, api: CanonicalApi) -> List[Loss]:
        writer = _Hl7v2GuideWriter(api, getattr(self, "_options", None) or Hl7v2GuideEmitOptions())
        try:
            writer.guide()
        except EmitPreconditionError:
            pass  # a model with no record is refused at export; there is no layout to report
        return writer.losses.records()


class Hl7v2GuideEmitOptions(EmitOptions):
    """Per-target options for :class:`Hl7v2GuideEmitter`."""

    message_type: Optional[str] = Field(
        default=None,
        description="The message type, `<code>^<event>` or `<code>^<event>^<structure>` (`ADT^A01`, `ORU^R01`). "
        "Default: an imported HL7 v2 item's own, else `ZZZ^Z01` (a site-defined message).",
    )
    version: Optional[str] = Field(
        default=None,
        description="The HL7 v2 version (`2.3`, `2.5.1`, `2.8` …). Default: an imported HL7 v2 item's own, else "
        "`2.5.1`. From 2.6 a timestamp is `DTM`, from 2.7 a coded value is `CWE`.",
    )
    default_field_length: int = Field(
        default=199, ge=1, le=99999,
        description="Maximum length of a text field with no maxLength.",
    )
    max_code_length: int = Field(
        default=20, ge=1, le=99,
        description="The longest code an enum value may be used as directly; a longer value (or one that is not "
        "upper-case letters and digits) gets a synthesized code.",
    )
    first_table_number: int = Field(
        default=9001, ge=1, le=9999,
        description="The number of the first user-defined table (one per enum, numbered in order).",
    )

    @field_validator("message_type")
    @classmethod
    def _message_type(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not value.strip():
            return None
        value = value.strip().upper()
        if not re.fullmatch(r"[A-Z0-9]{3}\^[A-Z0-9]{3}(\^[A-Z0-9_]{3,7})?", value):
            raise ValueError("message_type must be <code>^<event>, such as ADT^A01")
        return value

    @field_validator("version")
    @classmethod
    def _version(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not value.strip():
            return None
        value = value.strip()
        if not re.fullmatch(r"2\.[1-9](\.\d)?", value):
            raise ValueError("version must be an HL7 v2 version, such as 2.5.1")
        return value


class Hl7v2GuideEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi`'s types as an HL7 v2 message/segment definition guide (JSON, CSV, Markdown)."""

    key = "hl7v2-guide"
    format = "hl7v2-guide"
    label = _LABEL
    description = "Export the types as an HL7 v2 message and segment definition guide (JSON, CSV and Markdown)."
    icon = "table"
    paradigm = ApiParadigm.DATA_SCHEMA
    multi_file = True
    options_model = Hl7v2GuideEmitOptions

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        return CapabilityProfile(operations=False, events=False, unions=False, nullability=True,
                                 constraints=False, field_identity=False)

    @classmethod
    def fidelity_rule_pack(cls) -> type[CapabilityRulePack]:
        return Hl7v2GuideFidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[Hl7v2GuideEmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        options = (
            opts
            if isinstance(opts, Hl7v2GuideEmitOptions)
            else Hl7v2GuideEmitOptions.model_validate(opts.model_dump() if opts else {})
        )
        writer = _Hl7v2GuideWriter(api, options)
        guide = writer.guide()
        base = _base_name(api)
        files = [
            EmittedFile(path=f"{base}.hl7v2-guide.json",
                        content=json.dumps(guide, indent=2, ensure_ascii=False) + "\n", media_type="application/json"),
            EmittedFile(path=f"{base}.hl7v2-segments.csv", content=hl7v2_csv(guide), media_type="text/csv"),
            EmittedFile(path=f"{base}.hl7v2-guide.md", content=hl7v2_markdown(guide), media_type="text/markdown"),
        ]
        return EmitResult(files=files, media_type="application/json", provenance=writer.tracker.records(),
                          losses=writer.losses.records())


# ---------------------------------------------------------------------------
# The guide document
# ---------------------------------------------------------------------------

_OPTIONALITY = {"M": "R", "O": "O", "X": "X"}


def _at_least(version: str, minimum: str) -> bool:
    """Whether HL7 ``version`` (``2.5.1``) is ``minimum`` (``2.6``) or later."""
    def parts(text: str) -> Tuple[int, ...]:
        return tuple(int(p) for p in text.split("."))
    return parts(version) >= parts(minimum)


class _Hl7v2GuideWriter:
    """Builds one guide document (single use)."""

    def __init__(self, api: CanonicalApi, options: Hl7v2GuideEmitOptions) -> None:
        self._api = api
        self._options = options
        self.tracker = ProvenanceTracker()
        self.losses = LossTracker()
        self._version = options.version or _imported(api, "hl7v2_version", r"2\.[1-9](\.\d)?") or "2.5.1"
        self._tables: List[Dict[str, Any]] = []
        self._uses_yes_no = False
        self._group_names: Dict[str, int] = {}

    def guide(self) -> Dict[str, Any]:
        """The guide as a JSON-ready document."""
        plan_losses = LossTracker()
        plan = plan_guide(self._api, GuideOptions(default_length=self._options.default_field_length,
                                                  reserved_ids=frozenset() if self._has_msh() else frozenset({"MSH"}),
                                                  max_code_length=self._options.max_code_length,
                                                  segment_id_rule=_SEGMENT_ID_RULE, hl7v2_refs=True,
                                                  allocated_id_prefix="Z"), plan_losses)
        if not plan.structure:
            raise EmitPreconditionError(
                "An HL7 v2 segment guide lays out record types, and this model has none (only enums, scalars or "
                "operations)."
            )
        for loss in plan_losses.records():
            rule = _RESTATEMENTS.get(loss.subject)
            detail = re.sub(rule[0], rule[1], loss.detail) if rule else loss.detail
            self.losses.record(loss.kind, loss.subject, detail, pointer=loss.pointer)
        message_type = (self._options.message_type
                        or _imported(self._api, "hl7v2_message_type", r"[A-Z0-9]{3}\^[A-Z0-9]{3}(\^[A-Z0-9_]{3,7})?")
                        or "ZZZ^Z01")
        advisory = types_only_advisory(self._api, target_label=_LABEL, keep_in="OpenAPI or AsyncAPI")
        if advisory is not None:
            self.losses.record(LossKind.NA, "services-dropped", advisory.message)
        for type_ in self._api.types:
            self.tracker.record(type_.key, Provenance.SOURCE)

        segments = [self._segment_json(s) for s in plan.segments.values()]
        structure = [self._node(n) for n in plan.structure]
        if "MSH" in plan.segments:
            # An imported message's own header comes first, naming the guide's message type and version.
            structure.sort(key=lambda node: 0 if node.get("segment") == "MSH" else 1)
            msh = next(segment for segment in segments if segment["id"] == "MSH")
            for field in msh["fields"]:
                if field["seq"] in (9, 12):
                    field["value"] = message_type if field["seq"] == 9 else self._version
        else:
            segments.insert(0, _msh_segment(message_type, self._version))
            structure.insert(0, {"type": "segment", "segment": "MSH", "optionality": "R", "repetition": "N"})
        tables = ([_YES_NO] if self._uses_yes_no else []) + self._tables
        return {
            "guide": "HL7 v2 message and segment definition",
            "standard": "HL7 v2",
            "version": self._version,
            "message": {"type": message_type,
                        "name": self._api.title or self._api.identity.name or "Message"},
            "generatedFrom": {"name": self._api.identity.name, "format": self._api.format},
            "segments": segments,
            "tables": tables,
            "structure": structure,
        }

    def _has_msh(self) -> bool:
        return any(isinstance(s, dict) and s.get("id") == "MSH" for s in self._api.extras.get("hl7v2_segments") or [])

    # --- structure ----------------------------------------------------------------

    def _repetition(self, max_use: Optional[int]) -> Union[str, int]:
        """``N`` (once), ``Y`` (no limit) or a count."""
        if max_use == 1:
            return "N"
        return "Y" if max_use is None else max_use

    def _node(self, node: Union[SegmentUse, GuideLoop]) -> Dict[str, Any]:
        if isinstance(node, SegmentUse):
            out: Dict[str, Any] = {"type": "segment", "segment": node.segment, "optionality": _OPTIONALITY[node.usage],
                                   "repetition": self._repetition(node.max_use)}
            if node.source:
                out["source"] = node.source
            return out
        group = {"type": "group", "group": self._group_name(node.name), "optionality": _OPTIONALITY[node.usage],
                 "repetition": self._repetition(node.max_use), "source": node.source}
        group["children"] = [self._node(child) for child in node.children]
        return group

    def _group_name(self, name: str) -> str:
        """A segment group's name: its record's, in upper snake case (``OrderLine`` → ``ORDER_LINE``), unique."""
        snake = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name or "GROUP")
        base = re.sub(r"[^A-Za-z0-9]+", "_", snake).strip("_").upper() or "GROUP"
        count = self._group_names.get(base, 0) + 1
        self._group_names[base] = count
        return base if count == 1 else f"{base}_{count}"

    # --- segments -------------------------------------------------------------------

    def _segment_json(self, segment: GuideSegment) -> Dict[str, Any]:
        """A segment definition; a timestamp's two plan values are one date/time field."""
        fields: List[Dict[str, Any]] = []
        values = list(segment.elements)
        index = 0
        while index < len(values):
            element = values[index]
            following = values[index + 1] if index + 1 < len(values) else None
            seq = len(fields) + 1
            if (following is not None and element.kind == "date" and following.kind == "time" and element.source
                    and following.source == element.source):
                stamp = "DTM" if _at_least(self._version, "2.6") else "TS"
                field = self._field(element, seq, segment.id)
                field.update(name=element.name.removesuffix(" (date)"), dataType=stamp, length=26)
                fields.append(field)
                index += 2
                continue
            fields.append(self._field(element, seq, segment.id))
            index += 1
        return {"id": segment.id, "name": segment.name, "source": segment.source, "fields": fields}

    def _field(self, element: GuideElement, seq: int, segment_id: str) -> Dict[str, Any]:
        out: Dict[str, Any] = {"seq": seq, "ref": f"{segment_id}-{seq}", "name": element.name,
                               "dataType": self._data_type(element), "length": element.max_length,
                               "optionality": _OPTIONALITY[element.usage], "repetition": "N"}
        if element.kind == "code":
            out["table"] = self._table_for(element)
        if element.notes:
            out["notes"] = element.notes
        if element.source:
            out["source"] = element.source
        return out

    def _data_type(self, element: GuideElement) -> str:
        if element.kind == "code":
            if element.codes == ["Y", "N"] and not element.code_values:
                return "ID"
            return "CWE" if _at_least(self._version, "2.7") else "IS"
        if element.kind in ("integer", "decimal"):
            return "NM"
        if element.kind == "date":
            return "DT"
        if element.kind == "time":
            return "TM"
        return "ST"

    def _table_for(self, element: GuideElement) -> str:
        """The table a coded field is bound to: HL7 0136 for a boolean, else a new user-defined table."""
        if element.codes == ["Y", "N"] and not element.code_values:
            self._uses_yes_no = True
            return "0136"
        number = f"{self._options.first_table_number + len(self._tables):04d}"
        self._tables.append({
            "id": number, "name": element.name, "type": "User",
            "values": [{"code": code, "description": element.code_values.get(code, code)} for code in element.codes],
        })
        self.losses.record(
            LossKind.INFERRED, "table-synthesized",
            f"The values of {element.source!r} become user-defined table {number}; HL7 numbers each site's tables, so "
            "the export assigns the number (set first_table_number to choose where numbering starts).",
            pointer=element.source or None,
        )
        return number


def _imported(api: CanonicalApi, key: str, pattern: str) -> Optional[str]:
    value = api.extras.get(key)
    return value if isinstance(value, str) and re.fullmatch(pattern, value) else None


def _msh_segment(message_type: str, version: str) -> Dict[str, Any]:
    """The standard ``MSH`` message header, with ``MSH-9`` the message type and ``MSH-12`` the version."""
    stamp = "DTM" if _at_least(version, "2.6") else "TS"

    def f(seq: int, name: str, data_type: str, length: int, optionality: str, value: Optional[str] = None):
        out = {"seq": seq, "ref": f"MSH-{seq}", "name": name, "dataType": data_type, "length": length,
               "optionality": optionality, "repetition": "N"}
        if value is not None:
            out["value"] = value
        return out

    return {"id": "MSH", "name": "Message Header", "fields": [
        f(1, "Field Separator", "ST", 1, "R", "|"),
        f(2, "Encoding Characters", "ST", 4, "R", "^~\\&"),
        f(3, "Sending Application", "HD", 227, "O"),
        f(4, "Sending Facility", "HD", 227, "O"),
        f(5, "Receiving Application", "HD", 227, "O"),
        f(6, "Receiving Facility", "HD", 227, "O"),
        f(7, "Date/Time of Message", stamp, 26, "R"),
        f(8, "Security", "ST", 40, "O"),
        f(9, "Message Type", "MSG", 15, "R", message_type),
        f(10, "Message Control ID", "ST", 20, "R"),
        f(11, "Processing ID", "PT", 3, "R"),
        f(12, "Version ID", "VID", 60, "R", version),
    ]}


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------

_CSV_COLUMNS = ["segment", "segment_name", "seq", "ref", "field", "data_type", "length", "optionality",
                "repetition", "table", "value", "notes", "source"]


def hl7v2_csv(guide: Dict[str, Any]) -> str:
    """The segment definitions: one row per field of each segment."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(_CSV_COLUMNS)
    for segment in guide["segments"]:
        for field in segment["fields"]:
            writer.writerow([segment["id"], segment["name"], field["seq"], field["ref"], field["name"],
                             field["dataType"], field["length"], field["optionality"], field["repetition"],
                             field.get("table", ""), field.get("value", ""), "; ".join(field.get("notes") or []),
                             field.get("source", "")])
    return buffer.getvalue()


def abstract_syntax(nodes: List[Dict[str, Any]]) -> str:
    """The HL7 abstract message syntax: ``[ ]`` optional, ``{ }`` repeating (``MSH ZPA [ZNO] { ZOR }``)."""
    parts: List[str] = []
    for node in nodes:
        inner = node["segment"] if node["type"] == "segment" else abstract_syntax(node["children"])
        if node["repetition"] != "N":
            inner = f"{{ {inner} }}"
        if node["optionality"] == "O":
            inner = f"[ {inner} ]"
        parts.append(inner)
    return " ".join(parts)


def _cell(value: Any) -> str:
    return " ".join(str(value).split()).replace("|", "\\|")


def hl7v2_markdown(guide: Dict[str, Any]) -> str:
    """The human-readable guide: the abstract message syntax, each segment's fields, then the tables."""
    message = guide["message"]
    lines = [
        f"# HL7 v{guide['version']} {message['type']} message definition — {_cell(message['name'])}",
        "",
        f"HL7 version {guide['version']}, message type {message['type']}. Generated by Apiome from "
        f"{_cell(guide['generatedFrom'].get('name') or 'the item')}.",
        "",
        "## Message structure",
        "",
        "`[ ]` is optional and `{ }` repeats.",
        "",
        "```",
        abstract_syntax(guide["structure"]),
        "```",
        "",
        "## Segments",
        "",
    ]
    for segment in guide["segments"]:
        lines += [f"### {segment['id']} — {_cell(segment['name'])}", "",
                  "| Seq | Field | Data type | Len | Opt | Rep | Table | Notes |",
                  "| --- | --- | --- | --- | --- | --- | --- | --- |"]
        for field in segment["fields"]:
            notes = "; ".join(field.get("notes") or [])
            if field.get("value"):
                notes = f"value `{field['value']}`" + (f"; {notes}" if notes else "")
            lines.append(f"| {field['ref']} | {_cell(field['name'])} | {field['dataType']} | {field['length']} | "
                         f"{field['optionality']} | {field['repetition']} | {field.get('table', '—')} | "
                         f"{_cell(notes) or '—'} |")
        lines.append("")
    if guide["tables"]:
        lines += ["## Tables", ""]
        for table in guide["tables"]:
            lines += [f"### Table {table['id']} — {_cell(table['name'])} ({table['type']})", "",
                      "| Code | Description |", "| --- | --- |"]
            lines += [f"| {_cell(v['code'])} | {_cell(v['description'])} |" for v in table["values"]]
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"
