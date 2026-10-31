"""Validation of emitted X12 implementation guides — MFX-24.4 (#4148).

There is no importer for an implementation guide (it describes interchanges; it is not one), so an
emitted guide cannot be checked by reading it back. It is machine-checked here instead, before delivery,
through the MFX-5.1 export validator seam (:func:`app.export_validation.validate_emitted_artifact`,
target ``x12-guide``). Every problem is reported, each with the rule that found it (``keyword``), the
file and a JSON Pointer into the guide:

1. **Schema** (``x12-guide.schema``) — the JSON guide file matches :data:`GUIDE_SCHEMA`, the shape the
   emitter writes: ``transactionSet``, ``version``, ``segments`` (each with its ``elements``) and the
   ``structure`` tree. When the shape is wrong, the rules below are not run (they read that shape).
2. **Segments and elements** — segment IDs (``x12-guide.segment-id``, ``x12-guide.duplicate-segment``),
   element references ``<ID>01`` upward with no gap (``x12-guide.element-ref``), types
   (``x12-guide.element-type``), lengths (``x12-guide.lengths``), usage (``x12-guide.usage``) and the
   envelope (``x12-guide.transaction-set``, ``x12-guide.version``, ``x12-guide.envelope``).
3. **Referential integrity** — the structure uses only defined segments (``x12-guide.undefined-segment``)
   and every defined segment is used (``x12-guide.unused-segment``); a loop starts with its own segment
   (``x12-guide.loop``); positions are four digits and increase (``x12-guide.position``); a maximum use
   is a positive count or ``">1"`` (``x12-guide.max-use``).
4. **Code sets** (``x12-guide.codes``) — an ``ID`` element has a code list whose codes fit its lengths,
   with no duplicates; no other element has codes; ``codeValues`` names only listed codes; ``ST01``'s
   code is the transaction set's ID.
5. **Files agree** (``x12-guide.files``) — the export has the JSON guide, the segment CSV and the
   Markdown guide, and the CSV and Markdown say exactly what the JSON says.
6. **Dictionary spot-check** (``x12-guide.dictionary``) — when ``pyx12`` is installed and ships maps
   for the guide's X12 version, the ``ST`` / ``SE`` envelope must match the standard data elements
   (type and lengths), and the envelope and every segment carried from an X12 source must not have more
   elements than the standard segment defines. Without ``pyx12`` (or maps for that version) the
   spot-check is skipped and the verdict says so; the other checks still run.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from jsonschema import Draft202012Validator

from .x12_guide_emitter import X12_ELEMENT_TYPES, _csv, _markdown

__all__ = [
    "GUIDE_SCHEMA",
    "GuideProblem",
    "X12Dictionary",
    "GuideCheck",
    "check_guide_files",
    "dictionary_problems",
    "guide_problems",
    "load_x12_dictionary",
]

#: A segment ID: a letter, then one or two letters or digits.
_SEGMENT_ID_RE = re.compile(r"^[A-Z][A-Z0-9]{1,2}$")

_ELEMENT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["ref", "name", "type", "minLength", "maxLength", "usage"],
    "properties": {
        "ref": {"type": "string"},
        "name": {"type": "string"},
        "type": {"type": "string"},
        "minLength": {"type": "integer"},
        "maxLength": {"type": "integer"},
        "usage": {"type": "string"},
        "codes": {"type": "array", "items": {"type": "string"}},
        "codeValues": {"type": "object", "additionalProperties": {"type": "string"}},
        "notes": {"type": "array", "items": {"type": "string", "minLength": 1}},
        "source": {"type": ["string", "null"]},
    },
    "additionalProperties": False,
}

_NODE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["type", "usage", "maxUse"],
    "properties": {
        "type": {"enum": ["segment", "loop"]},
        "position": {"type": "string"},
        "segment": {"type": "string"},
        "loopId": {"type": "string"},
        "name": {"type": "string"},
        "usage": {"type": "string"},
        "maxUse": {"anyOf": [{"type": "integer"}, {"const": ">1"}]},
        "source": {"type": ["string", "null"]},
        "children": {"type": "array", "items": {"$ref": "#/$defs/node"}},
    },
    "additionalProperties": False,
    "allOf": [
        {"if": {"properties": {"type": {"const": "loop"}}},
         "then": {"required": ["loopId", "children"]},
         "else": {"required": ["segment"]}},
    ],
}

#: The JSON Schema of the ``<Name>.x12-guide.json`` file the X12 guide emitter writes (MFX-24.1).
GUIDE_SCHEMA: Dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://apiome.dev/schemas/x12-guide.schema.json",
    "title": "X12 implementation guide",
    "type": "object",
    "required": ["transactionSet", "version", "segments", "structure"],
    "properties": {
        "standard": {"type": "string"},
        "transactionSet": {
            "type": "object",
            "required": ["id"],
            "properties": {"id": {"type": "string"}, "name": {"type": "string"}},
        },
        "version": {"type": "string"},
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "name", "elements"],
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "source": {"type": ["string", "null"]},
                    "elements": {"type": "array", "items": {"$ref": "#/$defs/element"}},
                },
                "additionalProperties": False,
            },
        },
        "structure": {"type": "array", "items": {"$ref": "#/$defs/node"}},
    },
    "$defs": {"element": _ELEMENT_SCHEMA, "node": _NODE_SCHEMA},
}

_SCHEMA_VALIDATOR = Draft202012Validator(GUIDE_SCHEMA)


@dataclass(frozen=True)
class GuideProblem:
    """One reason an emitted guide is invalid.

    Attributes:
        rule: The rule that found it (``x12-guide.<name>``).
        message: What is wrong, naming where (``PUR02``, ``segment ZZZ``).
        path: JSON Pointer into the guide document (``/segments/1/elements/0``), or ``None``.
        file: The emitted file it is in, when it is tied to one.
    """

    rule: str
    message: str
    path: Optional[str] = None
    file: Optional[str] = None


@dataclass
class _Collector:
    """Gathers problems; ``add`` is the one way rules report."""

    problems: List[GuideProblem] = field(default_factory=list)

    def add(self, rule: str, message: str, path: Optional[str] = None) -> None:
        self.problems.append(GuideProblem(rule=f"x12-guide.{rule}", message=message, path=path))


# ===========================================================================
# 1–4. The JSON guide on its own
# ===========================================================================


def guide_problems(guide: Any) -> List[GuideProblem]:
    """Every problem with one guide document: its schema, then its structural and code-set rules.

    Args:
        guide: The parsed ``<Name>.x12-guide.json`` document.

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

    tset = guide["transactionSet"]
    if not re.fullmatch(r"\d{3}", tset["id"]):
        out.add("transaction-set", "transactionSet.id must be a 3-digit X12 transaction set ID", "/transactionSet/id")
    if not re.fullmatch(r"\d{6}", guide["version"]):
        out.add("version", "version must be a 6-digit X12 version", "/version")

    defined: Dict[str, int] = {}
    for index, segment in enumerate(guide["segments"]):
        _check_segment(out, index, segment, defined)
    _check_envelope(out, guide, defined)

    structure = guide["structure"]
    if not structure or structure[0].get("segment") != "ST" or structure[-1].get("segment") != "SE":
        out.add("envelope", "the structure must start with the ST segment and end with the SE segment", "/structure")
    used: Dict[str, str] = {}
    _check_nodes(out, structure, defined, used, "/structure", [])
    for seg_id, index in defined.items():
        if seg_id not in used:
            out.add("unused-segment", f"segment {seg_id} is defined but the structure never uses it",
                    f"/segments/{index}")
    return out.problems


def _check_segment(out: _Collector, index: int, segment: Mapping[str, Any], defined: Dict[str, int]) -> None:
    """A segment's ID, then each of its elements."""
    seg_id = segment["id"]
    where = f"/segments/{index}"
    if not _SEGMENT_ID_RE.match(seg_id):
        out.add("segment-id", f"segment ID {seg_id!r} is not 2-3 letters or digits starting with a letter",
                f"{where}/id")
    if seg_id in defined:
        out.add("duplicate-segment", f"segment {seg_id} is defined twice", where)
    else:
        defined[seg_id] = index
    elements = segment["elements"]
    if not elements or len(elements) > 99:
        out.add("element-ref", f"segment {seg_id} must have 1 to 99 elements", f"{where}/elements")
    for position, element in enumerate(elements, start=1):
        _check_element(out, seg_id, position, element, f"{where}/elements/{position - 1}")


def _check_element(out: _Collector, seg_id: str, position: int, element: Mapping[str, Any], where: str) -> None:
    """An element's reference, type, lengths, usage and codes."""
    ref = f"{seg_id}{position:02d}"
    if element["ref"] != ref:
        out.add("element-ref", f"segment {seg_id}: element {position} must be {ref}, not {element['ref']!r}",
                f"{where}/ref")
    if element["type"] not in X12_ELEMENT_TYPES:
        out.add("element-type", f"{ref}: type {element['type']!r} is not an X12 element type", f"{where}/type")
    low, high = element["minLength"], element["maxLength"]
    lengths_ok = 1 <= low <= high
    if not lengths_ok:
        out.add("lengths", f"{ref}: lengths must satisfy 1 <= minLength <= maxLength", where)
    if element["usage"] not in ("M", "O", "X"):
        out.add("usage", f"{ref}: usage must be M, O or X", f"{where}/usage")
    codes = element.get("codes")
    if element["type"] == "ID":
        if not codes:
            out.add("codes", f"{ref}: an ID element needs a code list", where)
        for code in codes or []:
            if lengths_ok and not (low <= len(code) <= high):
                out.add("codes", f"{ref}: code {code!r} is not {low}-{high} characters", f"{where}/codes")
        duplicates = sorted({code for code in codes or [] if (codes or []).count(code) > 1})
        if duplicates:
            out.add("codes", f"{ref}: codes listed more than once: {duplicates}", f"{where}/codes")
    elif codes:
        out.add("codes", f"{ref}: only an ID element has codes", f"{where}/codes")
    unknown = set(element.get("codeValues") or {}) - set(codes or [])
    if unknown:
        out.add("codes", f"{ref}: codeValues names codes the element does not have: {sorted(unknown)}",
                f"{where}/codeValues")


def _check_envelope(out: _Collector, guide: Mapping[str, Any], defined: Mapping[str, int]) -> None:
    """``ST`` and ``SE`` are defined, and ``ST01``'s one code is the transaction set's ID."""
    for seg_id in ("ST", "SE"):
        if seg_id not in defined:
            out.add("envelope", f"the {seg_id} segment is not defined", "/segments")
    if "ST" not in defined:
        return
    index = defined["ST"]
    elements = guide["segments"][index]["elements"]
    codes = elements[0].get("codes") if elements else None
    if codes != [guide["transactionSet"]["id"]]:
        out.add("codes", f"ST01 must list exactly the transaction set ID {guide['transactionSet']['id']!r}, "
                f"not {codes!r}", f"/segments/{index}/elements/0/codes")


def _check_nodes(out: _Collector, nodes: Sequence[Mapping[str, Any]], defined: Mapping[str, int],
                 used: Dict[str, str], where: str, last_position: List[str]) -> None:
    """Each structure node: its maximum use and usage, a loop's first segment, positions in order."""
    for index, node in enumerate(nodes):
        here = f"{where}/{index}"
        max_use = node["maxUse"]
        if not (max_use == ">1" or (isinstance(max_use, int) and max_use >= 1)):
            out.add("max-use", f"maxUse {max_use!r} must be a positive count or '>1'", f"{here}/maxUse")
        if node["usage"] not in ("M", "O"):
            out.add("usage", f"usage {node['usage']!r} must be M or O", f"{here}/usage")
        if node["type"] == "loop":
            children = node["children"]
            if not children or children[0].get("type") != "segment" or children[0].get("segment") != node["loopId"]:
                out.add("loop", f"loop {node['loopId']!r} must start with its own segment", here)
            _check_nodes(out, children, defined, used, f"{here}/children", last_position)
            continue
        seg_id = node["segment"]
        if seg_id not in defined:
            out.add("undefined-segment", f"the structure uses segment {seg_id!r}, which is not defined",
                    f"{here}/segment")
        used.setdefault(seg_id, here)
        position = node.get("position")
        if position is None:
            continue
        if not re.fullmatch(r"\d{4}", position):
            out.add("position", f"segment {seg_id}: position {position!r} is not four digits", f"{here}/position")
        elif last_position and position <= last_position[0]:
            out.add("position", f"segment {seg_id} is at position {position}, not after {last_position[0]}",
                    f"{here}/position")
        else:
            last_position[:] = [position]


# ===========================================================================
# 6. The pyx12 dictionary spot-check
# ===========================================================================


@dataclass(frozen=True)
class X12Dictionary:
    """What pyx12's maps say about the standard segments of one X12 version.

    Attributes:
        version: The 4-digit release the maps are for (``5010``).
        element_counts: Standard segment ID → the number of elements the maps define for it.
        elements: ``(segment ID, position)`` → ``(type, minLength, maxLength)`` from the data-element dictionary.
    """

    version: str
    element_counts: Mapping[str, int]
    elements: Mapping[Tuple[str, int], Tuple[str, int, int]]


def _pyx12_map_dir() -> Optional[Path]:
    """pyx12's ``map`` folder, or ``None`` when pyx12 is not installed."""
    try:
        import pyx12  # noqa: PLC0415 - optional toolchain, probed on use
    except ImportError:
        return None
    folder = Path(pyx12.__file__).resolve().parent / "map"
    return folder if (folder / "dataele.xml").is_file() else None


@lru_cache(maxsize=8)
def load_x12_dictionary(version: str) -> Optional[X12Dictionary]:
    """The standard segment dictionary for a 6-digit X12 ``version`` (``005010``), read from pyx12's maps.

    Every map pyx12 ships for that release (``*.5010.*.xml``) contributes the segments it defines; the
    data-element dictionary (``dataele.xml``) gives each element's type and lengths.

    Args:
        version: The guide's 6-digit X12 version.

    Returns:
        The dictionary, or ``None`` when pyx12 is not installed or ships no map for that release.
    """
    folder = _pyx12_map_dir()
    if folder is None or not re.fullmatch(r"\d{6}", version):
        return None
    release = version[2:6]
    maps = sorted(folder.glob(f"*.{release}.*xml"))
    if not maps:
        return None
    data_elements = {
        node.get("ele_num"): (node.get("data_type"), int(node.get("min_len")), int(node.get("max_len")))
        for node in ElementTree.parse(folder / "dataele.xml").getroot().iter("data_ele")
    }
    counts: Dict[str, int] = {}
    elements: Dict[Tuple[str, int], Tuple[str, int, int]] = {}
    for path in maps:
        for segment in ElementTree.parse(path).getroot().iter("segment"):
            seg_id = segment.get("xid")
            for element in segment.findall("element"):
                seq_text, number = element.findtext("seq"), element.findtext("data_ele")
                if not (seq_text and seq_text.isdigit()):
                    continue
                seq = int(seq_text)
                counts[seg_id] = max(counts.get(seg_id, 0), seq)
                if number in data_elements:
                    elements.setdefault((seg_id, seq), data_elements[number])
    return X12Dictionary(version=release, element_counts=counts, elements=elements)


def dictionary_problems(guide: Mapping[str, Any], dictionary: X12Dictionary) -> List[GuideProblem]:
    """Spot-check a structurally valid guide against the standard dictionary.

    * The ``ST`` and ``SE`` elements must have the standard type and lengths (the envelope is never
      the item's own: it is the same for every guide of a version).
    * A segment carried from an X12 source (its elements named by their refs, ``BGN01``) — and the
      envelope — must not have more elements than the standard defines for it: a translator cannot place
      the extra ones. A segment made from a type is not held to a standard segment that shares its ID.

    Args:
        guide: A guide with no :func:`guide_problems`.
        dictionary: :func:`load_x12_dictionary` for its version.

    Returns:
        The problems (empty when the guide agrees with the dictionary).
    """
    out = _Collector()
    for index, segment in enumerate(guide["segments"]):
        seg_id = segment["id"]
        where = f"/segments/{index}"
        if seg_id in ("ST", "SE"):
            for position, element in enumerate(segment["elements"], start=1):
                expected = dictionary.elements.get((seg_id, position))
                actual = (element["type"], element["minLength"], element["maxLength"])
                if expected is not None and actual != expected:
                    out.add("dictionary", f"{element['ref']}: the X12 {dictionary.version} dictionary defines it "
                            f"as {expected[0]} {expected[1]}/{expected[2]}, not {actual[0]} {actual[1]}/{actual[2]}",
                            f"{where}/elements/{position - 1}")
        standard = dictionary.element_counts.get(seg_id)
        # Only a segment carried from an X12 source (its elements named by their refs, ``BGN01``, a skipped
        # position ``Not used``) is the standard segment; one made from a type may share an ID by chance and
        # is not held to its size.
        carried = all(element["name"] in (element["ref"], "Not used") for element in segment["elements"])
        if not (carried or seg_id in ("ST", "SE")):
            continue
        if standard is not None and len(segment["elements"]) > standard:
            out.add("dictionary", f"segment {seg_id} has {len(segment['elements'])} elements; the X12 "
                    f"{dictionary.version} {seg_id} segment defines {standard}", f"{where}/elements")
    return out.problems


# ===========================================================================
# 5. The emitted files together
# ===========================================================================


@dataclass(frozen=True)
class GuideCheck:
    """The result of checking one emitted guide's files.

    Attributes:
        problems: Every problem found (empty for a valid export).
        dictionary_checked: Whether the pyx12 spot-check ran.
        skipped_reason: Why the spot-check did not run, or ``None``.
    """

    problems: List[GuideProblem]
    dictionary_checked: bool
    skipped_reason: Optional[str]


def check_guide_files(files: Mapping[str, str]) -> GuideCheck:
    """Check an emitted guide's three files: the JSON guide, the CSV and the Markdown.

    Args:
        files: Emitted file path → text.

    Returns:
        The :class:`GuideCheck`; each problem carries the file it is in.
    """
    def tagged(problems: List[GuideProblem], file: Optional[str]) -> List[GuideProblem]:
        return [GuideProblem(rule=p.rule, message=p.message, path=p.path, file=file) for p in problems]

    by_suffix = {suffix: next((path for path in files if path.endswith(suffix)), None)
                 for suffix in (".x12-guide.json", ".x12-segments.csv", ".x12-guide.md")}
    json_path = by_suffix[".x12-guide.json"]
    problems: List[GuideProblem] = [
        GuideProblem(rule="x12-guide.files", message=f"the export has no {suffix} file")
        for suffix, path in by_suffix.items() if path is None
    ]
    if json_path is None:
        return GuideCheck(problems=problems, dictionary_checked=False, skipped_reason="there is no JSON guide")
    try:
        guide = json.loads(files[json_path])
    except json.JSONDecodeError as exc:
        problems.append(GuideProblem(rule="x12-guide.schema", message=f"Not a JSON guide: {exc}", file=json_path,
                                     path="/"))
        return GuideCheck(problems=problems, dictionary_checked=False, skipped_reason="the guide is not JSON")
    own = guide_problems(guide)
    problems.extend(tagged(own, json_path))
    if own:
        return GuideCheck(problems=problems, dictionary_checked=False, skipped_reason="the guide is invalid")

    for suffix, render in ((".x12-segments.csv", _csv), (".x12-guide.md", _markdown)):
        path = by_suffix[suffix]
        if path is not None and files[path] != render(guide):
            problems.append(GuideProblem(rule="x12-guide.files", file=path,
                                         message=f"{path} does not match {json_path}: it must list exactly the "
                                         "guide's segments, elements and structure"))

    dictionary = load_x12_dictionary(guide["version"])
    if dictionary is None:
        reason = ("pyx12 is not installed" if _pyx12_map_dir() is None
                  else f"pyx12 ships no segment dictionary for X12 {guide['version']}")
        return GuideCheck(problems=problems, dictionary_checked=False, skipped_reason=reason)
    problems.extend(tagged(dictionary_problems(guide, dictionary), json_path))
    return GuideCheck(problems=problems, dictionary_checked=True, skipped_reason=None)
