"""Validation of emitted HL7 v2 segment guides — MFX-26.3 (#4159).

The HL7 v2 counterpart of :mod:`app.x12_guide_validation` (MFX-24.4) and :mod:`app.edifact_guide_validation`: a guide
describes messages, it is not one, so it is machine-checked before delivery through the export validator seam (target
``hl7v2-guide``). Every problem has its rule (``keyword``), file and a JSON Pointer:

1. **Schema** (``hl7v2-guide.schema``) — the JSON guide matches :data:`GUIDE_SCHEMA`; when it does not, nothing else is
   checked.
2. **Segments and fields** — IDs are three letters or digits starting with a letter, defined once
   (``hl7v2-guide.segment-id``, ``hl7v2-guide.duplicate-segment``); fields run ``SEG-1`` upward with no gap
   (``hl7v2-guide.field-ref``); known data types (``hl7v2-guide.data-type``); a positive length
   (``hl7v2-guide.length``); optionality ``R`` / ``O`` / ``X`` (``hl7v2-guide.optionality``); repetition ``N``,
   ``Y`` or a positive count (``hl7v2-guide.repetition``).
3. **The message** — ``message.type`` is ``<code>^<event>`` and ``version`` an HL7 v2 version
   (``hl7v2-guide.message``); ``MSH`` is defined and first in the structure, and its ``MSH-9`` and ``MSH-12``
   (when it has them) name the guide's message type and version (``hl7v2-guide.envelope``).
4. **Tables** (``hl7v2-guide.table``) — every coded field (``ID`` / ``IS`` / ``CWE``) names a table the guide
   defines, no other field does, a table's codes are unique and fit the field, and every table is used.
5. **Referential integrity** — the structure uses only defined segments and every one of them
   (``hl7v2-guide.undefined-segment`` / ``unused-segment``); a segment group is named and not empty
   (``hl7v2-guide.group``).
6. **Files agree** (``hl7v2-guide.files``) — the export has the JSON guide, the segment CSV and the Markdown guide, and
   the CSV and Markdown say exactly what the JSON says.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set

from jsonschema import Draft202012Validator

from .hl7v2_guide_emitter import HL7V2_DATA_TYPES, hl7v2_csv, hl7v2_markdown

__all__ = ["GUIDE_SCHEMA", "GuideProblem", "check_guide_files", "guide_problems"]

_FIELD_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["seq", "ref", "name", "dataType", "length", "optionality", "repetition"],
    "properties": {
        "seq": {"type": "integer"},
        "ref": {"type": "string"},
        "name": {"type": "string"},
        "dataType": {"type": "string"},
        "length": {"type": "integer"},
        "optionality": {"type": "string"},
        "repetition": {"anyOf": [{"type": "integer"}, {"type": "string"}]},
        "table": {"type": "string"},
        "value": {"type": "string"},
        "notes": {"type": "array", "items": {"type": "string", "minLength": 1}},
        "source": {"type": ["string", "null"]},
    },
    "additionalProperties": False,
}

_NODE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["type", "optionality", "repetition"],
    "properties": {
        "type": {"enum": ["segment", "group"]},
        "segment": {"type": "string"},
        "group": {"type": "string"},
        "optionality": {"type": "string"},
        "repetition": {"anyOf": [{"type": "integer"}, {"type": "string"}]},
        "source": {"type": ["string", "null"]},
        "children": {"type": "array", "items": {"$ref": "#/$defs/node"}},
    },
    "additionalProperties": False,
    "allOf": [{"if": {"properties": {"type": {"const": "group"}}},
               "then": {"required": ["group", "children"]}, "else": {"required": ["segment"]}}],
}

#: The JSON Schema of the ``<Name>.hl7v2-guide.json`` file the HL7 v2 guide emitter writes.
GUIDE_SCHEMA: Dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://apiome.dev/schemas/hl7v2-guide.schema.json",
    "title": "HL7 v2 message and segment definition",
    "type": "object",
    "required": ["version", "message", "segments", "tables", "structure"],
    "properties": {
        "guide": {"type": "string"},
        "standard": {"type": "string"},
        "version": {"type": "string"},
        "message": {"type": "object", "required": ["type"],
                    "properties": {"type": {"type": "string"}, "name": {"type": "string"}}},
        "generatedFrom": {"type": "object"},
        "segments": {"type": "array", "items": {
            "type": "object", "required": ["id", "name", "fields"],
            "properties": {"id": {"type": "string"}, "name": {"type": "string"},
                           "source": {"type": ["string", "null"]},
                           "fields": {"type": "array", "items": {"$ref": "#/$defs/field"}}},
            "additionalProperties": False}},
        "tables": {"type": "array", "items": {
            "type": "object", "required": ["id", "name", "type", "values"],
            "properties": {"id": {"type": "string"}, "name": {"type": "string"}, "type": {"enum": ["HL7", "User"]},
                           "values": {"type": "array", "minItems": 1, "items": {
                               "type": "object", "required": ["code", "description"],
                               "properties": {"code": {"type": "string"}, "description": {"type": "string"}},
                               "additionalProperties": False}}},
            "additionalProperties": False}},
        "structure": {"type": "array", "items": {"$ref": "#/$defs/node"}},
    },
    "$defs": {"field": _FIELD_SCHEMA, "node": _NODE_SCHEMA},
}

_SCHEMA_VALIDATOR = Draft202012Validator(GUIDE_SCHEMA)
_SEGMENT_ID_RE = re.compile(r"^[A-Z][A-Z0-9]{2}$")
_CODED = frozenset({"ID", "IS", "CWE"})


@dataclass(frozen=True)
class GuideProblem:
    """One reason an emitted guide is invalid: its rule (``hl7v2-guide.<name>``), message, pointer and file."""

    rule: str
    message: str
    path: Optional[str] = None
    file: Optional[str] = None


@dataclass
class _Collector:
    problems: List[GuideProblem] = field(default_factory=list)

    def add(self, rule: str, message: str, path: Optional[str] = None) -> None:
        self.problems.append(GuideProblem(rule=f"hl7v2-guide.{rule}", message=message, path=path))


def guide_problems(guide: Any) -> List[GuideProblem]:
    """Every problem with one guide document: its schema, then its structural and table rules.

    Args:
        guide: The parsed ``<Name>.hl7v2-guide.json`` document.

    Returns:
        The problems, in document order (empty for a valid guide).
    """
    out = _Collector()
    for error in sorted(_SCHEMA_VALIDATOR.iter_errors(guide), key=lambda e: list(e.absolute_path)):
        pointer = "".join(f"/{part}" for part in error.absolute_path)
        out.add("schema", f"{pointer or '/'}: {error.message}", pointer or "/")
    if out.problems:
        return out.problems

    if not re.fullmatch(r"[A-Z0-9]{3}\^[A-Z0-9]{3}(\^[A-Z0-9_]{3,7})?", guide["message"]["type"]):
        out.add("message", "message.type must be <code>^<event>, such as ADT^A01", "/message/type")
    if not re.fullmatch(r"2\.[1-9](\.\d)?", guide["version"]):
        out.add("message", "version must be an HL7 v2 version, such as 2.5.1", "/version")

    tables = {table["id"]: table for table in guide["tables"]}
    used_tables: Set[str] = set()
    defined: Dict[str, int] = {}
    for index, segment in enumerate(guide["segments"]):
        _check_segment(out, index, segment, defined, tables, used_tables)
    for index, table in enumerate(guide["tables"]):
        codes = [v["code"] for v in table["values"]]
        duplicates = sorted({code for code in codes if codes.count(code) > 1})
        if duplicates:
            out.add("table", f"table {table['id']} lists codes more than once: {duplicates}", f"/tables/{index}")
        if table["id"] not in used_tables:
            out.add("table", f"table {table['id']} is defined but no field uses it", f"/tables/{index}")

    _check_envelope(out, guide, defined)
    used: Dict[str, str] = {}
    _check_nodes(out, guide["structure"], defined, used, "/structure")
    for seg_id, index in defined.items():
        if seg_id not in used:
            out.add("unused-segment", f"segment {seg_id} is defined but the structure never uses it",
                    f"/segments/{index}")
    return out.problems


def _check_segment(out: _Collector, index: int, segment: Mapping[str, Any], defined: Dict[str, int],
                   tables: Mapping[str, Any], used_tables: Set[str]) -> None:
    seg_id = segment["id"]
    where = f"/segments/{index}"
    if not _SEGMENT_ID_RE.match(seg_id):
        out.add("segment-id", f"segment ID {seg_id!r} is not three letters or digits starting with a letter",
                f"{where}/id")
    if seg_id in defined:
        out.add("duplicate-segment", f"segment {seg_id} is defined twice", where)
    else:
        defined[seg_id] = index
    if not segment["fields"]:
        out.add("field-ref", f"segment {seg_id} has no fields", f"{where}/fields")
    for seq, f in enumerate(segment["fields"], start=1):
        here = f"{where}/fields/{seq - 1}"
        ref = f"{seg_id}-{seq}"
        if f["seq"] != seq or f["ref"] != ref:
            out.add("field-ref", f"segment {seg_id}: field {seq} must be {ref}, not {f['ref']!r}", f"{here}/ref")
        if f["dataType"] not in HL7V2_DATA_TYPES:
            out.add("data-type", f"{ref}: data type {f['dataType']!r} is not one this guide writes", f"{here}/dataType")
        if f["length"] < 1:
            out.add("length", f"{ref}: length must be positive", f"{here}/length")
        if f["optionality"] not in ("R", "O", "X"):
            out.add("optionality", f"{ref}: optionality must be R, O or X", f"{here}/optionality")
        _check_repetition(out, ref, f["repetition"], f"{here}/repetition")
        table = f.get("table")
        if f["dataType"] in _CODED and seg_id != "MSH":
            if table is None:
                out.add("table", f"{ref}: a coded field ({f['dataType']}) must name a table", here)
            elif table not in tables:
                out.add("table", f"{ref}: table {table} is not defined", f"{here}/table")
            else:
                used_tables.add(table)
                too_long = [v["code"] for v in tables[table]["values"] if len(v["code"]) > f["length"]]
                if too_long:
                    out.add("table", f"{ref}: codes longer than the field's length {f['length']}: {too_long}",
                            f"{here}/table")
        elif table is not None:
            out.add("table", f"{ref}: only a coded field (ID, IS, CWE) names a table", f"{here}/table")


def _check_repetition(out: _Collector, ref: str, repetition: Any, where: str) -> None:
    if not (repetition in ("N", "Y") or (isinstance(repetition, int) and repetition >= 1)):
        out.add("repetition", f"{ref}: repetition {repetition!r} must be N, Y or a positive count", where)


def _check_envelope(out: _Collector, guide: Mapping[str, Any], defined: Mapping[str, int]) -> None:
    """``MSH`` is defined and first; its ``MSH-9`` and ``MSH-12`` (those it has) name the message type and version."""
    structure = guide["structure"]
    if "MSH" not in defined:
        out.add("envelope", "the MSH segment is not defined", "/segments")
        return
    if not structure or structure[0].get("segment") != "MSH":
        out.add("envelope", "the structure must start with the MSH segment", "/structure")
    msh = guide["segments"][defined["MSH"]]
    values = {f["seq"]: f.get("value") for f in msh["fields"]}
    expected = {9: guide["message"]["type"], 12: guide["version"]}
    # An imported MSH may lack MSH-9 or MSH-12; the fields it has name the message.
    if any(seq in values and values[seq] != value for seq, value in expected.items()):
            out.add("envelope", f"MSH-9 and MSH-12 must name message {guide['message']['type']} and version "
                    f"{guide['version']}", f"/segments/{defined['MSH']}")


def _check_nodes(out: _Collector, nodes: Sequence[Mapping[str, Any]], defined: Mapping[str, int],
                 used: Dict[str, str], where: str) -> None:
    for index, node in enumerate(nodes):
        here = f"{where}/{index}"
        _check_repetition(out, node.get("segment") or node.get("group") or "node", node["repetition"],
                          f"{here}/repetition")
        if node["optionality"] not in ("R", "O"):
            out.add("optionality", f"optionality {node['optionality']!r} must be R or O", f"{here}/optionality")
        if node["type"] == "group":
            if not node["children"] or not re.fullmatch(r"[A-Z][A-Z0-9_]*", node["group"]):
                out.add("group", f"segment group {node['group']!r} must be named in upper case and hold segments",
                        here)
            _check_nodes(out, node["children"], defined, used, f"{here}/children")
            continue
        seg_id = node["segment"]
        if seg_id not in defined:
            out.add("undefined-segment", f"the structure uses segment {seg_id!r}, which is not defined",
                    f"{here}/segment")
        used.setdefault(seg_id, here)


def check_guide_files(files: Mapping[str, str]) -> List[GuideProblem]:
    """Check an emitted guide's three files: the JSON guide, the CSV and the Markdown.

    Args:
        files: Emitted file path → text.

    Returns:
        Every problem, each with the file it is in (empty for a valid export).
    """
    by_suffix = {suffix: next((path for path in files if path.endswith(suffix)), None)
                 for suffix in (".hl7v2-guide.json", ".hl7v2-segments.csv", ".hl7v2-guide.md")}
    problems = [GuideProblem(rule="hl7v2-guide.files", message=f"the export has no {suffix} file")
                for suffix, path in by_suffix.items() if path is None]
    json_path = by_suffix[".hl7v2-guide.json"]
    if json_path is None:
        return problems
    try:
        guide = json.loads(files[json_path])
    except json.JSONDecodeError as exc:
        return [*problems, GuideProblem(rule="hl7v2-guide.schema", message=f"Not a JSON guide: {exc}",
                                        file=json_path, path="/")]
    own = [GuideProblem(rule=p.rule, message=p.message, path=p.path, file=json_path) for p in guide_problems(guide)]
    problems.extend(own)
    if own:
        return problems
    for suffix, render in ((".hl7v2-segments.csv", hl7v2_csv), (".hl7v2-guide.md", hl7v2_markdown)):
        path = by_suffix[suffix]
        if path is not None and files[path] != render(guide):
            problems.append(GuideProblem(rule="hl7v2-guide.files", file=path,
                                         message=f"{path} does not match {json_path}: it must list exactly the "
                                         "guide's segments, fields, tables and structure"))
    return problems
