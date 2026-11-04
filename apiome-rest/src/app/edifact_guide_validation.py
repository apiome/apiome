"""Validation of emitted UN/EDIFACT message guides — MFX-24.2 (#4146).

The EDIFACT counterpart of :mod:`app.x12_guide_validation` (MFX-24.4): a guide describes messages, it is not one,
so it is machine-checked before delivery rather than read back, through the export validator seam (target
``edifact-guide``). Every problem is reported with its rule (``keyword``), file and a JSON Pointer:

1. **Schema** (``edifact-guide.schema``) — the JSON guide matches :data:`GUIDE_SCHEMA`; when it does not, the
   rules below are not run.
2. **Segments and data elements** — tags are three letters (``edifact-guide.segment-tag``, never a ``U…`` service
   tag for a segment made from a type), defined once (``edifact-guide.duplicate-segment``); data element refs run
   ``<TAG>01`` upward with no gap and a composite's components ``<ref>-1`` upward (``edifact-guide.element-ref``);
   representations ``an`` / ``n`` with a length (``edifact-guide.representation``) that agrees with the lengths
   (``edifact-guide.lengths``); status ``M`` / ``C`` / ``N`` (``edifact-guide.status``).
3. **The message** — ``message.type`` is six letters and ``message.release`` a directory release
   (``edifact-guide.message``); ``UNH`` and ``UNT`` are defined and ``UNH02``'s message type and release are the
   guide's (``edifact-guide.envelope``).
4. **Referential integrity** — the structure starts with ``UNH`` and ends with ``UNT``, uses only defined segments
   and every one of them (``edifact-guide.undefined-segment`` / ``unused-segment``); a segment group starts with
   its trigger segment and groups are numbered ``SG1`` upward in order (``edifact-guide.group``); positions are
   four digits and increase (``edifact-guide.position``); a maximum repetition is a positive count
   (``edifact-guide.max-use``).
5. **Code lists** (``edifact-guide.codes``) — codes fit the element's lengths, are not repeated, and
   ``codeValues`` names only listed codes.
6. **Files agree** (``edifact-guide.files``) — the export has the JSON guide, the segment CSV and the Markdown
   guide, and the CSV and Markdown say exactly what the JSON says.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from jsonschema import Draft202012Validator

from .edifact_guide_emitter import EDIFACT_SEGMENT_TAG_RULE, edifact_csv, edifact_markdown

__all__ = ["GUIDE_SCHEMA", "GuideProblem", "check_guide_files", "guide_problems"]

_SIMPLE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["ref", "name", "representation", "minLength", "maxLength", "status"],
    "properties": {
        "ref": {"type": "string"},
        "name": {"type": "string"},
        "representation": {"type": "string"},
        "minLength": {"type": "integer"},
        "maxLength": {"type": "integer"},
        "status": {"type": "string"},
        "decimals": {"type": "integer", "minimum": 0},
        "format": {"type": "string"},
        "codes": {"type": "array", "items": {"type": "string"}},
        "codeValues": {"type": "object", "additionalProperties": {"type": "string"}},
        "notes": {"type": "array", "items": {"type": "string", "minLength": 1}},
        "source": {"type": ["string", "null"]},
    },
    "additionalProperties": False,
}

_COMPOSITE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["ref", "name", "composite", "status", "components"],
    "properties": {
        "ref": {"type": "string"},
        "name": {"type": "string"},
        "composite": {"const": True},
        "status": {"type": "string"},
        "components": {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/simple"}},
        "source": {"type": ["string", "null"]},
    },
    "additionalProperties": False,
}

_NODE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["type", "status", "maxUse"],
    "properties": {
        "type": {"enum": ["segment", "group"]},
        "position": {"type": "string"},
        "segment": {"type": "string"},
        "group": {"type": "string"},
        "trigger": {"type": "string"},
        "name": {"type": "string"},
        "status": {"type": "string"},
        "maxUse": {"type": "integer"},
        "source": {"type": ["string", "null"]},
        "children": {"type": "array", "items": {"$ref": "#/$defs/node"}},
    },
    "additionalProperties": False,
    "allOf": [
        {"if": {"properties": {"type": {"const": "group"}}},
         "then": {"required": ["group", "trigger", "children"]},
         "else": {"required": ["segment"]}},
    ],
}

#: The JSON Schema of the ``<Name>.edifact-guide.json`` file the EDIFACT guide emitter writes.
GUIDE_SCHEMA: Dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://apiome.dev/schemas/edifact-guide.schema.json",
    "title": "UN/EDIFACT message implementation guide",
    "type": "object",
    "required": ["message", "segments", "structure"],
    "properties": {
        "guide": {"type": "string"},
        "standard": {"type": "string"},
        "message": {
            "type": "object",
            "required": ["type", "version", "release", "agency"],
            "properties": {k: {"type": "string"} for k in ("type", "version", "release", "agency", "name")},
        },
        "generatedFrom": {"type": "object"},
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["tag", "name", "elements"],
                "properties": {
                    "tag": {"type": "string"},
                    "name": {"type": "string"},
                    "source": {"type": ["string", "null"]},
                    "elements": {"type": "array",
                                 "items": {"anyOf": [{"$ref": "#/$defs/simple"}, {"$ref": "#/$defs/composite"}]}},
                },
                "additionalProperties": False,
            },
        },
        "structure": {"type": "array", "items": {"$ref": "#/$defs/node"}},
    },
    "$defs": {"simple": _SIMPLE_SCHEMA, "composite": _COMPOSITE_SCHEMA, "node": _NODE_SCHEMA},
}

_SCHEMA_VALIDATOR = Draft202012Validator(GUIDE_SCHEMA)
_TAG_RE = re.compile(r"^[A-Z]{3}$")
_TYPE_TAG_RE = re.compile(EDIFACT_SEGMENT_TAG_RULE)
_SERVICE = frozenset({"UNH", "UNT"})
_REPRESENTATION_RE = re.compile(r"^(an|n)(\.\.)?(\d+)$")


@dataclass(frozen=True)
class GuideProblem:
    """One reason an emitted guide is invalid.

    Attributes:
        rule: The rule that found it (``edifact-guide.<name>``).
        message: What is wrong, naming where (``NAD02-3``, ``segment ZZZ``).
        path: JSON Pointer into the guide document, or ``None``.
        file: The emitted file it is in, when it is tied to one.
    """

    rule: str
    message: str
    path: Optional[str] = None
    file: Optional[str] = None


@dataclass
class _Collector:
    problems: List[GuideProblem] = field(default_factory=list)

    def add(self, rule: str, message: str, path: Optional[str] = None) -> None:
        self.problems.append(GuideProblem(rule=f"edifact-guide.{rule}", message=message, path=path))


def guide_problems(guide: Any) -> List[GuideProblem]:
    """Every problem with one guide document: its schema, then its structural and code-list rules.

    Args:
        guide: The parsed ``<Name>.edifact-guide.json`` document.

    Returns:
        The problems, in document order (empty for a valid guide). A guide that does not match
        :data:`GUIDE_SCHEMA` reports only its schema problems.
    """
    out = _Collector()
    for error in sorted(_SCHEMA_VALIDATOR.iter_errors(guide), key=lambda e: list(e.absolute_path)):
        pointer = "".join(f"/{part}" for part in error.absolute_path)
        out.add("schema", f"{pointer or '/'}: {error.message}", pointer or "/")
    if out.problems:
        return out.problems

    message = guide["message"]
    if not re.fullmatch(r"[A-Z]{6}", message["type"]):
        out.add("message", "message.type must be a 6-letter EDIFACT message type", "/message/type")
    if not re.fullmatch(r"\d{2}[A-Z]", message["release"]) or message["version"] != "D":
        out.add("message", "message.version must be D and message.release a directory release such as 96A",
                "/message/release")

    defined: Dict[str, int] = {}
    for index, segment in enumerate(guide["segments"]):
        _check_segment(out, index, segment, defined)
    _check_envelope(out, guide, defined)

    structure = guide["structure"]
    if not structure or structure[0].get("segment") != "UNH" or structure[-1].get("segment") != "UNT":
        out.add("envelope", "the structure must start with the UNH segment and end with the UNT segment",
                "/structure")
    used: Dict[str, str] = {}
    _check_nodes(out, structure, defined, used, "/structure", [], [0])
    for tag, index in defined.items():
        if tag not in used:
            out.add("unused-segment", f"segment {tag} is defined but the structure never uses it", f"/segments/{index}")
    return out.problems


def _check_segment(out: _Collector, index: int, segment: Mapping[str, Any], defined: Dict[str, int]) -> None:
    tag = segment["tag"]
    where = f"/segments/{index}"
    if not _TAG_RE.match(tag):
        out.add("segment-tag", f"segment tag {tag!r} is not three letters", f"{where}/tag")
    elif tag not in _SERVICE and not _TYPE_TAG_RE.match(tag):
        out.add("segment-tag", f"segment tag {tag!r} is a service segment tag (U…)", f"{where}/tag")
    if tag in defined:
        out.add("duplicate-segment", f"segment {tag} is defined twice", where)
    else:
        defined[tag] = index
    elements = segment["elements"]
    if not elements or len(elements) > 99:
        out.add("element-ref", f"segment {tag} must have 1 to 99 data elements", f"{where}/elements")
    for position, element in enumerate(elements, start=1):
        ref = f"{tag}{position:02d}"
        here = f"{where}/elements/{position - 1}"
        if element["ref"] != ref:
            out.add("element-ref", f"segment {tag}: data element {position} must be {ref}, not {element['ref']!r}",
                    f"{here}/ref")
        _check_status(out, ref, element["status"], f"{here}/status")
        if element.get("composite"):
            for k, component in enumerate(element["components"], start=1):
                expected = f"{ref}-{k}"
                if component["ref"] != expected:
                    out.add("element-ref", f"{ref}: component {k} must be {expected}, not {component['ref']!r}",
                            f"{here}/components/{k - 1}/ref")
                _check_simple(out, expected, component, f"{here}/components/{k - 1}")
        else:
            _check_simple(out, ref, element, here)


def _check_status(out: _Collector, ref: str, status: str, where: str) -> None:
    if status not in ("M", "C", "N"):
        out.add("status", f"{ref}: status must be M, C or N", where)


def _check_simple(out: _Collector, ref: str, element: Mapping[str, Any], where: str) -> None:
    """A simple value's representation, lengths, status and codes."""
    _check_status(out, ref, element["status"], f"{where}/status")
    low, high = element["minLength"], element["maxLength"]
    lengths_ok = 1 <= low <= high
    if not lengths_ok:
        out.add("lengths", f"{ref}: lengths must satisfy 1 <= minLength <= maxLength", where)
    match = _REPRESENTATION_RE.match(element["representation"])
    if match is None:
        out.add("representation", f"{ref}: {element['representation']!r} is not an EDIFACT representation "
                "(an..n, ann, n..n, nn)", f"{where}/representation")
    elif lengths_ok and (int(match.group(3)) != high or (match.group(2) is None and low != high)):
        out.add("lengths", f"{ref}: {element['representation']} does not say lengths {low}/{high}",
                f"{where}/representation")
    codes = element.get("codes") or []
    for code in codes:
        if lengths_ok and not (low <= len(code) <= high):
            out.add("codes", f"{ref}: code {code!r} is not {low}-{high} characters", f"{where}/codes")
    duplicates = sorted({code for code in codes if codes.count(code) > 1})
    if duplicates:
        out.add("codes", f"{ref}: codes listed more than once: {duplicates}", f"{where}/codes")
    unknown = set(element.get("codeValues") or {}) - set(codes)
    if unknown:
        out.add("codes", f"{ref}: codeValues names codes the element does not have: {sorted(unknown)}",
                f"{where}/codeValues")


def _check_envelope(out: _Collector, guide: Mapping[str, Any], defined: Mapping[str, int]) -> None:
    """``UNH`` and ``UNT`` are defined, and ``UNH02`` names the guide's message type and release."""
    for tag in ("UNH", "UNT"):
        if tag not in defined:
            out.add("envelope", f"the {tag} segment is not defined", "/segments")
    if "UNH" not in defined:
        return
    index = defined["UNH"]
    elements = guide["segments"][index]["elements"]
    identifier = elements[1] if len(elements) > 1 and elements[1].get("composite") else None
    components = identifier["components"] if identifier else []
    found = [c.get("codes") for c in components[:3]]
    message = guide["message"]
    if found != [[message["type"]], [message["version"]], [message["release"]]]:
        out.add("envelope", f"UNH02 must identify message {message['type']} {message['version']}:{message['release']}",
                f"/segments/{index}/elements/1")


def _check_nodes(out: _Collector, nodes: Sequence[Mapping[str, Any]], defined: Mapping[str, int],
                 used: Dict[str, str], where: str, last_position: List[str], groups: List[int]) -> None:
    for index, node in enumerate(nodes):
        here = f"{where}/{index}"
        if not (isinstance(node["maxUse"], int) and node["maxUse"] >= 1):
            out.add("max-use", f"maxUse {node['maxUse']!r} must be a positive count", f"{here}/maxUse")
        if node["status"] not in ("M", "C"):
            out.add("status", f"status {node['status']!r} must be M or C", f"{here}/status")
        if node["type"] == "group":
            groups[0] += 1
            if node["group"] != f"SG{groups[0]}":
                out.add("group", f"segment group {node['group']!r} must be SG{groups[0]} (groups are numbered in "
                        "order)", f"{here}/group")
            children = node["children"]
            if not children or children[0].get("type") != "segment" or children[0].get("segment") != node["trigger"]:
                out.add("group", f"segment group {node['group']!r} must start with its trigger segment "
                        f"{node['trigger']!r}", here)
            _check_nodes(out, children, defined, used, f"{here}/children", last_position, groups)
            continue
        tag = node["segment"]
        if tag not in defined:
            out.add("undefined-segment", f"the structure uses segment {tag!r}, which is not defined", f"{here}/segment")
        used.setdefault(tag, here)
        position = node.get("position")
        if position is None:
            continue
        if not re.fullmatch(r"\d{4}", position):
            out.add("position", f"segment {tag}: position {position!r} is not four digits", f"{here}/position")
        elif last_position and position <= last_position[0]:
            out.add("position", f"segment {tag} is at position {position}, not after {last_position[0]}",
                    f"{here}/position")
        else:
            last_position[:] = [position]


def check_guide_files(files: Mapping[str, str]) -> List[GuideProblem]:
    """Check an emitted guide's three files: the JSON guide, the CSV and the Markdown.

    Args:
        files: Emitted file path → text.

    Returns:
        Every problem, each with the file it is in (empty for a valid export).
    """
    by_suffix = {suffix: next((path for path in files if path.endswith(suffix)), None)
                 for suffix in (".edifact-guide.json", ".edifact-segments.csv", ".edifact-guide.md")}
    problems = [GuideProblem(rule="edifact-guide.files", message=f"the export has no {suffix} file")
                for suffix, path in by_suffix.items() if path is None]
    json_path = by_suffix[".edifact-guide.json"]
    if json_path is None:
        return problems
    try:
        guide = json.loads(files[json_path])
    except json.JSONDecodeError as exc:
        return [*problems, GuideProblem(rule="edifact-guide.schema", message=f"Not a JSON guide: {exc}",
                                        file=json_path, path="/")]
    own = [GuideProblem(rule=p.rule, message=p.message, path=p.path, file=json_path) for p in guide_problems(guide)]
    problems.extend(own)
    if own:
        return problems
    for suffix, render in ((".edifact-segments.csv", edifact_csv), (".edifact-guide.md", edifact_markdown)):
        path = by_suffix[suffix]
        if path is not None and files[path] != render(guide):
            problems.append(GuideProblem(rule="edifact-guide.files", file=path,
                                         message=f"{path} does not match {json_path}: it must list exactly the "
                                         "guide's segments, data elements and structure"))
    return problems
