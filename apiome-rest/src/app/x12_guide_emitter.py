"""X12 implementation-guide emitter: canonical types → an X12 transaction-set guide — MFX-24.1 (#4145).

Trading-partner onboarding runs on implementation guides: which segments a transaction set holds, in
what order and how often, and each segment's elements with their type, length, usage and codes. This
emitter writes one for the item's types, laid out by :mod:`app.edi_guide`, in three files:

* ``<Name>.x12-guide.json`` — the machine-readable guide: the transaction set, the segment dictionary
  and the structure (positions, loops, usage, maximum use);
* ``<Name>.x12-segments.csv`` — the segment dictionary, one row per element, for spreadsheet tooling;
* ``<Name>.x12-guide.md`` — the human-readable guide.

**X12 terms.** Text is ``AN``, a code list ``ID``, an integer ``N0``, a decimal with a known scale ``Nn``
(``n`` implied decimal places) and one without ``R``, a date ``DT`` (``CCYYMMDD``), a time ``TM``
(``HHMM`` to ``HHMMSSDD``). Usage is ``M`` (mandatory), ``O`` (optional) or ``X`` (not used). The
transaction set is wrapped in its ``ST`` header (``ST01`` = the set's ID) and ``SE`` trailer; positions
number the structure ``0100``, ``0200`` …

**Options:** ``transaction_set`` (the set's 3-digit ID: ``850``, ``810``, ``837`` …; an imported X12
item keeps its own, else ``850``), ``version`` (the 6-digit X12 version; default ``005010``) and
``default_element_length`` (the maximum of text with no ``maxLength``).

:func:`validate_x12_guide_document` checks a guide's structure (segment IDs, contiguous element refs,
types, lengths, usage, codes, the envelope and every segment the structure uses being defined).
"""

from __future__ import annotations

import csv
import io
import json
import re
from typing import Any, Dict, List, Optional, Union

from pydantic import Field, field_validator

from .canonical_model import ApiParadigm, CanonicalApi
from .edi_guide import GuideElement, GuideLoop, GuideOptions, GuideSegment, SegmentUse, plan_guide
from .emitter import (
    CapabilityProfile,
    EmitOptions,
    EmitPreconditionError,
    EmitResult,
    EmittedFile,
    Emitter,
    LossKind,
    LossTracker,
    Provenance,
    ProvenanceTracker,
)
from .fidelity_rulepack import CapabilityRulePack, FidelityVerdict, types_only_advisory
from .lossiness import LossinessSeverity

__all__ = [
    "X12_ELEMENT_TYPES",
    "X12GuideEmitOptions",
    "X12GuideEmitter",
    "X12GuideFidelityRulePack",
    "validate_x12_guide",
    "validate_x12_guide_document",
]

#: Segment IDs of the X12 envelope: never given to a segment made from a type.
_ENVELOPE_IDS = frozenset({"ISA", "IEA", "GS", "GE", "ST", "SE", "TA1"})
#: The element types a guide may use: ``AN``, ``ID``, ``N0``-``N9``, ``R``, ``DT``, ``TM``.
X12_ELEMENT_TYPES = frozenset({"AN", "ID", "R", "DT", "TM", *(f"N{d}" for d in range(10))})
_SEGMENT_ID_RE = re.compile(r"^[A-Z][A-Z0-9]{1,2}$")
_TYPES_ONLY_DROP_MESSAGE = "only data schemas are exported"


class X12GuideFidelityRulePack(CapabilityRulePack):
    """Fidelity rules for the X12 implementation guide (the full pack is MFX-24.3).

    Types-only: every operation and channel is dropped, with the critical types-only advisory, and a
    document of another format is noted on the root.
    """

    target_label = "X12 implementation guide"

    def root_verdicts(self, api: CanonicalApi) -> List[FidelityVerdict]:
        verdicts: List[FidelityVerdict] = []
        advisory = types_only_advisory(api, target_label=self.target_label, keep_in="OpenAPI or AsyncAPI")
        if advisory is not None:
            verdicts.append(advisory)
        verdicts.append(FidelityVerdict.approx(
            message=f"The {api.format or 'source'} types are laid out as an X12 transaction set: segments of flat "
            "elements in loops, with X12 element types and lengths",
            severity=LossinessSeverity.INFO,
            target_mapping="types → X12 transaction set",
        ))
        return verdicts

    def operation_verdict(self, operation) -> FidelityVerdict:
        return FidelityVerdict.drop(
            message=f"{self.target_label} is types-only — {_TYPES_ONLY_DROP_MESSAGE}; "
            f"the {operation.kind.value} operation is dropped",
            target_mapping="operation → dropped (types-only export)",
        )

    def channel_verdict(self, channel) -> FidelityVerdict:
        return FidelityVerdict.drop(
            message=f"{self.target_label} is types-only — {_TYPES_ONLY_DROP_MESSAGE}; the event channel is dropped",
            target_mapping="channel → dropped (types-only export)",
        )


class X12GuideEmitOptions(EmitOptions):
    """Per-target options for :class:`X12GuideEmitter`."""

    transaction_set: Optional[str] = Field(
        default=None,
        description="The transaction set's 3-digit ID (`850`, `810`, `837` …). Default: an imported X12 item's "
        "own, else `850`.",
    )
    version: Optional[str] = Field(
        default=None,
        description="The 6-digit X12 version (`005010`, `004010` …). Default: an imported X12 item's own, else "
        "`005010`.",
    )
    default_element_length: int = Field(
        default=80, ge=1, le=9999,
        description="Maximum length of a text element with no maxLength.",
    )

    @field_validator("transaction_set")
    @classmethod
    def _three_digits(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not value.strip():
            return None
        if not re.fullmatch(r"\d{3}", value.strip()):
            raise ValueError("transaction_set must be a 3-digit X12 transaction set ID, such as 850")
        return value.strip()

    @field_validator("version")
    @classmethod
    def _six_digits(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not value.strip():
            return None
        if not re.fullmatch(r"\d{6}", value.strip()):
            raise ValueError("version must be a 6-digit X12 version, such as 005010")
        return value.strip()


class X12GuideEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi`'s types as an X12 implementation guide (JSON, CSV and Markdown)."""

    key = "x12-guide"
    format = "x12-guide"
    label = "X12 implementation guide"
    description = "Export the types as an X12 transaction-set implementation guide (JSON, CSV and Markdown)."
    icon = "table"
    paradigm = ApiParadigm.DATA_SCHEMA
    multi_file = True
    options_model = X12GuideEmitOptions

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        return CapabilityProfile(operations=False, events=False, unions=False, nullability=True,
                                 constraints=False, field_identity=False)

    @classmethod
    def fidelity_rule_pack(cls) -> type[CapabilityRulePack]:
        return X12GuideFidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[X12GuideEmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        options = (
            opts
            if isinstance(opts, X12GuideEmitOptions)
            else X12GuideEmitOptions.model_validate(opts.model_dump() if opts else {})
        )
        writer = _X12GuideWriter(api, options)
        guide = writer.guide()
        base = _base_name(api)
        files = [
            EmittedFile(path=f"{base}.x12-guide.json", content=json.dumps(guide, indent=2, ensure_ascii=False) + "\n",
                        media_type="application/json"),
            EmittedFile(path=f"{base}.x12-segments.csv", content=_csv(guide), media_type="text/csv"),
            EmittedFile(path=f"{base}.x12-guide.md", content=_markdown(guide), media_type="text/markdown"),
        ]
        return EmitResult(files=files, media_type="application/json", provenance=writer.tracker.records(),
                          losses=writer.losses.records())


class _X12GuideWriter:
    """Builds one guide document (single use)."""

    def __init__(self, api: CanonicalApi, options: X12GuideEmitOptions) -> None:
        self._api = api
        self._options = options
        self.tracker = ProvenanceTracker()
        self.losses = LossTracker()
        self._position = 0

    def guide(self) -> Dict[str, Any]:
        """The guide as a JSON-ready document."""
        plan = plan_guide(self._api, GuideOptions(default_length=self._options.default_element_length,
                                                  reserved_ids=_ENVELOPE_IDS), self.losses)
        if not plan.structure:
            raise EmitPreconditionError(
                "An X12 implementation guide lays out record types, and this model has none (only enums, scalars or "
                "operations)."
            )
        set_id = self._options.transaction_set or _imported(self._api, "x12_set_id", r"\d{3}") or "850"
        version = self._options.version or _imported(self._api, "x12_version", r"\d{6}") or "005010"
        advisory = types_only_advisory(self._api, target_label=X12GuideEmitter.label, keep_in="OpenAPI or AsyncAPI")
        if advisory is not None:
            self.losses.record(LossKind.NA, "services-dropped", advisory.message)
        for type_ in self._api.types:
            self.tracker.record(type_.key, Provenance.SOURCE)

        segments = [_st_segment(set_id), *(_segment_json(s) for s in plan.segments.values()), _se_segment()]
        structure = [self._use(SegmentUse("ST", "M", 1)), *(self._node(n) for n in plan.structure),
                     self._use(SegmentUse("SE", "M", 1))]
        return {
            "guide": "X12 implementation guide",
            "standard": "X12",
            "version": version,
            "transactionSet": {"id": set_id, "name": self._api.title or self._api.identity.name or "Transaction"},
            "generatedFrom": {"name": self._api.identity.name, "format": self._api.format},
            "segments": segments,
            "structure": structure,
        }

    def _next_position(self) -> str:
        self._position += 100
        return f"{self._position:04d}"

    def _use(self, use: SegmentUse) -> Dict[str, Any]:
        node: Dict[str, Any] = {"type": "segment", "position": self._next_position(), "segment": use.segment,
                                "usage": use.usage, "maxUse": _max_use(use.max_use)}
        if use.source:
            node["source"] = use.source
        return node

    def _node(self, node: Union[SegmentUse, GuideLoop]) -> Dict[str, Any]:
        if isinstance(node, SegmentUse):
            return self._use(node)
        loop = {"type": "loop", "loopId": node.id, "name": node.name, "usage": node.usage,
                "maxUse": _max_use(node.max_use), "source": node.source}
        loop["children"] = [self._node(child) for child in node.children]
        return loop


def _imported(api: CanonicalApi, key: str, pattern: str) -> Optional[str]:
    value = api.extras.get(key)
    return value if isinstance(value, str) and re.fullmatch(pattern, value) else None


def _max_use(value: Optional[int]) -> Union[int, str]:
    """An X12 maximum use: a count, or ``">1"`` for no limit."""
    return value if value is not None else ">1"


def _x12_type(element: GuideElement) -> str:
    """The X12 data element type of a guide element."""
    if element.kind == "code":
        return "ID"
    if element.kind == "integer":
        return "N0"
    if element.kind == "decimal":
        return f"N{element.scale}" if element.scale is not None else "R"
    if element.kind == "date":
        return "DT"
    if element.kind == "time":
        return "TM"
    return "AN"


def _segment_json(segment: GuideSegment) -> Dict[str, Any]:
    return {
        "id": segment.id,
        "name": segment.name,
        "source": segment.source,
        "elements": [_element_json(e) for e in segment.elements],
    }


def _element_json(element: GuideElement) -> Dict[str, Any]:
    out: Dict[str, Any] = {"ref": element.ref, "name": element.name, "type": _x12_type(element),
                           "minLength": element.min_length, "maxLength": element.max_length, "usage": element.usage}
    if element.codes:
        out["codes"] = element.codes
    if element.source:
        out["source"] = element.source
    return out


def _st_segment(set_id: str) -> Dict[str, Any]:
    return {"id": "ST", "name": "Transaction Set Header", "elements": [
        {"ref": "ST01", "name": "Transaction Set Identifier Code", "type": "ID", "minLength": 3, "maxLength": 3,
         "usage": "M", "codes": [set_id]},
        {"ref": "ST02", "name": "Transaction Set Control Number", "type": "AN", "minLength": 4, "maxLength": 9,
         "usage": "M"},
        {"ref": "ST03", "name": "Implementation Convention Reference", "type": "AN", "minLength": 1, "maxLength": 35,
         "usage": "O"},
    ]}


def _se_segment() -> Dict[str, Any]:
    return {"id": "SE", "name": "Transaction Set Trailer", "elements": [
        {"ref": "SE01", "name": "Number of Included Segments", "type": "N0", "minLength": 1, "maxLength": 10,
         "usage": "M"},
        {"ref": "SE02", "name": "Transaction Set Control Number", "type": "AN", "minLength": 4, "maxLength": 9,
         "usage": "M"},
    ]}


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------

_CSV_COLUMNS = ["segment", "segment_name", "ref", "element", "type", "min_length", "max_length", "usage", "codes",
                "source"]


def _csv(guide: Dict[str, Any]) -> str:
    """The segment dictionary: one row per element of each segment."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(_CSV_COLUMNS)
    for segment in guide["segments"]:
        for element in segment["elements"]:
            writer.writerow([segment["id"], segment["name"], element["ref"], element["name"], element["type"],
                             element["minLength"], element["maxLength"], element["usage"],
                             "|".join(element.get("codes") or []), element.get("source", "")])
    return buffer.getvalue()


def _cell(value: Any) -> str:
    """A Markdown table cell (pipes escaped, no line breaks)."""
    return " ".join(str(value).split()).replace("|", "\\|")


def _markdown(guide: Dict[str, Any]) -> str:
    """The human-readable guide: the structure table, then each segment's elements and codes."""
    tset = guide["transactionSet"]
    lines = [
        f"# X12 {tset['id']} implementation guide — {_cell(tset['name'])}",
        "",
        f"X12 version {guide['version']}, transaction set {tset['id']}. Generated by Apiome from "
        f"{_cell(guide['generatedFrom'].get('name') or 'the item')}.",
        "",
        "## Structure",
        "",
        "| Pos | Segment | Name | Usage | Max use | Loop |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    names = {segment["id"]: segment["name"] for segment in guide["segments"]}

    def walk(nodes: List[Dict[str, Any]], loops: List[str]) -> None:
        for node in nodes:
            if node["type"] == "loop":
                walk(node["children"], [*loops, f"{node['loopId']} (max {node['maxUse']}, {node['usage']})"])
            else:
                lines.append(f"| {node['position']} | {node['segment']} | {_cell(names.get(node['segment'], ''))} | "
                             f"{node['usage']} | {node['maxUse']} | {_cell(' › '.join(loops)) or '—'} |")

    walk(guide["structure"], [])
    lines += ["", "## Segments", ""]
    for segment in guide["segments"]:
        lines += [f"### {segment['id']} — {_cell(segment['name'])}", "",
                  "| Ref | Element | Type | Min/Max | Usage | Codes |", "| --- | --- | --- | --- | --- | --- |"]
        for element in segment["elements"]:
            codes = ", ".join(element.get("codes") or []) or "—"
            lines.append(f"| {element['ref']} | {_cell(element['name'])} | {element['type']} | "
                         f"{element['minLength']}/{element['maxLength']} | {element['usage']} | {_cell(codes)} |")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _base_name(api: CanonicalApi) -> str:
    base = api.title or api.identity.name or "guide"
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", base).strip("-") or "guide"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_x12_guide(guide: Dict[str, Any]) -> None:
    """Check that a guide document is structurally valid.

    Rules: a 3-digit transaction set and 6-digit version; unique segment IDs (a letter, then 1-2 letters
    or digits); each segment's element refs ``<id>01`` upward with no gap; known element types;
    ``1 <= minLength <= maxLength``; usage ``M``/``O``/``X``; an ``ID`` element has codes, each within its
    lengths, and no other element has codes; the structure starts with ``ST``, ends with ``SE``, uses only
    defined segments, and every loop starts with a segment; a maximum use is a positive count or ``">1"``.

    Raises:
        ValueError: The first rule broken, naming where.
    """
    tset = guide.get("transactionSet") or {}
    if not re.fullmatch(r"\d{3}", str(tset.get("id", ""))):
        raise ValueError("transactionSet.id must be a 3-digit X12 transaction set ID")
    if not re.fullmatch(r"\d{6}", str(guide.get("version", ""))):
        raise ValueError("version must be a 6-digit X12 version")
    defined: Dict[str, Dict[str, Any]] = {}
    for segment in guide.get("segments") or []:
        seg_id = segment.get("id", "")
        if not _SEGMENT_ID_RE.match(seg_id):
            raise ValueError(f"segment ID {seg_id!r} is not 2-3 letters or digits starting with a letter")
        if seg_id in defined:
            raise ValueError(f"segment {seg_id} is defined twice")
        defined[seg_id] = segment
        elements = segment.get("elements") or []
        if not elements or len(elements) > 99:
            raise ValueError(f"segment {seg_id} must have 1 to 99 elements")
        for position, element in enumerate(elements, start=1):
            _check_element(seg_id, position, element)
    structure = guide.get("structure") or []
    if not structure or structure[0].get("segment") != "ST" or structure[-1].get("segment") != "SE":
        raise ValueError("the structure must start with the ST segment and end with the SE segment")
    _check_nodes(structure, defined)


def _check_element(seg_id: str, position: int, element: Dict[str, Any]) -> None:
    ref = f"{seg_id}{position:02d}"
    if element.get("ref") != ref:
        raise ValueError(f"segment {seg_id}: element {position} must be {ref}, not {element.get('ref')!r}")
    if element.get("type") not in X12_ELEMENT_TYPES:
        raise ValueError(f"{ref}: type {element.get('type')!r} is not an X12 element type")
    low, high = element.get("minLength"), element.get("maxLength")
    if not (isinstance(low, int) and isinstance(high, int) and 1 <= low <= high):
        raise ValueError(f"{ref}: lengths must satisfy 1 <= minLength <= maxLength")
    if element.get("usage") not in ("M", "O", "X"):
        raise ValueError(f"{ref}: usage must be M, O or X")
    codes = element.get("codes")
    if element["type"] == "ID":
        if not codes:
            raise ValueError(f"{ref}: an ID element needs a code list")
        for code in codes:
            if not (low <= len(str(code)) <= high):
                raise ValueError(f"{ref}: code {code!r} is not {low}-{high} characters")
    elif codes:
        raise ValueError(f"{ref}: only an ID element has codes")


def _check_nodes(nodes: List[Dict[str, Any]], defined: Dict[str, Dict[str, Any]]) -> None:
    for node in nodes:
        max_use = node.get("maxUse")
        if not (max_use == ">1" or (isinstance(max_use, int) and max_use >= 1)):
            raise ValueError(f"maxUse {max_use!r} must be a positive count or '>1'")
        if node.get("usage") not in ("M", "O"):
            raise ValueError(f"usage {node.get('usage')!r} must be M or O")
        if node.get("type") == "loop":
            children = node.get("children") or []
            if not children or children[0].get("type") != "segment" or children[0].get("segment") != node.get("loopId"):
                raise ValueError(f"loop {node.get('loopId')!r} must start with its own segment")
            _check_nodes(children, defined)
        elif node.get("segment") not in defined:
            raise ValueError(f"the structure uses segment {node.get('segment')!r}, which is not defined")


def validate_x12_guide_document(content: str) -> None:
    """Parse and validate the JSON guide file (:func:`validate_x12_guide`).

    Raises:
        ValueError: The text is not JSON, or the guide breaks a rule.
    """
    try:
        guide = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Not a JSON guide: {exc}") from exc
    if not isinstance(guide, dict):
        raise ValueError("A guide must be a JSON object")
    validate_x12_guide(guide)

