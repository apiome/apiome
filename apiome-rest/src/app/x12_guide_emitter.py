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
from typing import Any, Dict, List, Mapping, Optional, Union

from pydantic import Field, ValidationError, field_validator

from .canonical_model import ApiParadigm, CanonicalApi, CanonicalField, Type
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
from .lossiness import LossinessKind, LossinessReport, LossinessSeverity

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
_TYPES_ONLY_DROP_MESSAGE = "only data schemas are exported"


class X12GuideFidelityRulePack(CapabilityRulePack):
    """Fidelity rules for the X12 implementation guide — MFX-24.1 (#4145), MFX-24.3 (#4147).

    X12 is the most structurally constrained target: a transaction set is flat segments in loops. The pack
    lays the guide out for the report's options (:meth:`apply_options`) and files each thing the layout
    invented, degraded or dropped on the construct it came from:

    * **critical** ``DROP`` — operations and channels (with the types-only advisory), a union or a map (a
      segment holds flat values), a record that contains itself, values beyond a segment's 99 elements:
      these make the conversion **severe**, so the MFX-3.3 guard asks for confirmation and names each one;
    * ``SYNTH`` — a default element length (warn), a segment ID made from a name, a marker element, a code
      synthesized for an enum value that does not fit an ID code (warn);
    * ``APPROX`` — a list of lists flattened into one loop, rules kept only as guide notes, a decimal of
      unknown scale written as a real, a decimal with implied places, a float as a real, a timestamp split
      into date and time, a scalar with no element type;
    * a field whose type holds no value is an info ``DROP``.
    """

    target_label = "X12 implementation guide"

    #: Writer loss subject → (verdict kind, severity).
    _WRITER_LOSSES = {
        "union-dropped": (LossinessKind.DROP, LossinessSeverity.CRITICAL),
        "map-dropped": (LossinessKind.DROP, LossinessSeverity.CRITICAL),
        "recursion-cut": (LossinessKind.DROP, LossinessSeverity.CRITICAL),
        "elements-truncated": (LossinessKind.DROP, LossinessSeverity.CRITICAL),
        "field-dropped": (LossinessKind.DROP, LossinessSeverity.INFO),
        "length-synthesized": (LossinessKind.SYNTH, LossinessSeverity.WARN),
        "code-renamed": (LossinessKind.SYNTH, LossinessSeverity.WARN),
        "segment-id-synthesized": (LossinessKind.SYNTH, LossinessSeverity.INFO),
        "element-synthesized": (LossinessKind.SYNTH, LossinessSeverity.INFO),
        "list-flattened": (LossinessKind.APPROX, LossinessSeverity.WARN),
        "constraint-as-note": (LossinessKind.APPROX, LossinessSeverity.WARN),
        "decimal-as-real": (LossinessKind.APPROX, LossinessSeverity.WARN),
        "unmapped-scalar": (LossinessKind.APPROX, LossinessSeverity.WARN),
        "decimal-implied": (LossinessKind.APPROX, LossinessSeverity.INFO),
        "float-as-real": (LossinessKind.APPROX, LossinessSeverity.INFO),
        "timestamp-split": (LossinessKind.APPROX, LossinessSeverity.INFO),
    }
    #: Set by :meth:`evaluate`.
    _filed: Dict[str, List[FidelityVerdict]] = {}

    def apply_options(self, options: Mapping[str, Any]) -> None:
        """Compute the report for these emit options (invalid options fall back to the defaults)."""
        try:
            self._options = X12GuideEmitOptions.model_validate(dict(options))
        except ValidationError:
            self._options = X12GuideEmitOptions()

    def evaluate(self, api: CanonicalApi) -> LossinessReport:
        """Lay the guide out once (as it will be emitted), file its losses by construct, then walk the model."""
        writer = _X12GuideWriter(api, getattr(self, "_options", None) or X12GuideEmitOptions())
        try:
            writer.guide()
        except EmitPreconditionError:
            pass  # a model with no record is refused at export; there is no layout to report
        constructs = {""} | {t.key for t in api.types} | {f.key for t in api.types for f in t.fields}
        self._filed = {}
        seen = set()
        for loss in writer.losses.records():
            rule = self._WRITER_LOSSES.get(loss.subject)
            if rule is None or (loss.subject, loss.detail) in seen:
                continue
            seen.add((loss.subject, loss.detail))
            kind, severity = rule
            self._filed.setdefault(_owning_construct(loss.pointer or "", constructs), []).append(
                FidelityVerdict(kind=kind, severity=severity, message=loss.detail, target_mapping=loss.subject)
            )
        return super().evaluate(api)

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
        return verdicts + self._filed.get("", [])

    def type_verdicts(self, type_: Type) -> List[FidelityVerdict]:
        return super().type_verdicts(type_) + self._filed.get(type_.key, [])

    def field_verdicts(self, field: CanonicalField) -> List[FidelityVerdict]:
        return super().field_verdicts(field) + self._filed.get(field.key, [])

    def _union_verdict(self, type_: Type) -> FidelityVerdict:
        """A union type itself is not written; the fields that use it carry the critical drop."""
        return FidelityVerdict.drop(
            message=f"{self.target_label} has no union: a segment holds flat values, so {type_.key!r} is not "
            "written (each field of this type is dropped)",
            severity=LossinessSeverity.WARN,
            target_mapping="union → dropped",
        )

    def _field_identity_verdict(self, field: CanonicalField) -> Optional[FidelityVerdict]:
        """An element is identified by its position in its segment, which the guide keeps."""
        return None

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


def _owning_construct(pointer: str, constructs: set) -> str:
    """The construct a writer loss belongs to: its own key, else the longest key it extends, else the root."""
    if pointer in constructs:
        return pointer
    owners = [key for key in constructs if key and pointer.startswith(f"{key}.")]
    return max(owners, key=len) if owners else ""


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
    max_code_length: int = Field(
        default=3, ge=1, le=30,
        description="The longest code an enum value may be used as directly; a longer value (or one that is not "
        "upper-case letters and digits) gets a synthesized code.",
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
        #: The gap between positions: 100 (``0100``, ``0200`` …), smaller when that would pass ``9999``.
        self._position_step = 100

    def guide(self) -> Dict[str, Any]:
        """The guide as a JSON-ready document."""
        plan = plan_guide(self._api, GuideOptions(default_length=self._options.default_element_length,
                                                  reserved_ids=_ENVELOPE_IDS,
                                                  max_code_length=self._options.max_code_length), self.losses)
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

        segments = [_st_segment(set_id, version), *(_segment_json(s) for s in plan.segments.values()), _se_segment()]
        # X12 positions are four digits: a guide with more than 98 segment uses numbers them closer together.
        self._position_step = min(100, 9999 // (_segment_uses(plan.structure) + 2))
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
        self._position += self._position_step
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


def _segment_uses(nodes: List[Union[SegmentUse, GuideLoop]]) -> int:
    """How many segment uses ``nodes`` hold, loops included (each one takes a position)."""
    return sum(_segment_uses(node.children) if isinstance(node, GuideLoop) else 1 for node in nodes)


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
    if element.code_values:
        out["codeValues"] = element.code_values
    if element.notes:
        out["notes"] = element.notes
    if element.source:
        out["source"] = element.source
    return out


def _st_segment(set_id: str, version: str) -> Dict[str, Any]:
    """The ``ST`` transaction set header for ``set_id`` in X12 ``version``.

    ``ST03`` (implementation convention reference) exists from release 004020; an older version's ``ST``
    has two elements (MFX-24.4: the pyx12 4010 dictionary spot-check).
    """
    elements = [
        {"ref": "ST01", "name": "Transaction Set Identifier Code", "type": "ID", "minLength": 3, "maxLength": 3,
         "usage": "M", "codes": [set_id]},
        {"ref": "ST02", "name": "Transaction Set Control Number", "type": "AN", "minLength": 4, "maxLength": 9,
         "usage": "M"},
    ]
    if version >= "004020":
        elements.append({"ref": "ST03", "name": "Implementation Convention Reference", "type": "AN", "minLength": 1,
                         "maxLength": 35, "usage": "O"})
    return {"id": "ST", "name": "Transaction Set Header", "elements": elements}


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
                "notes", "source"]


def _csv(guide: Dict[str, Any]) -> str:
    """The segment dictionary: one row per element of each segment."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(_CSV_COLUMNS)
    for segment in guide["segments"]:
        for element in segment["elements"]:
            writer.writerow([segment["id"], segment["name"], element["ref"], element["name"], element["type"],
                             element["minLength"], element["maxLength"], element["usage"],
                             "|".join(_code_labels(element)), "; ".join(element.get("notes") or []),
                             element.get("source", "")])
    return buffer.getvalue()


def _code_labels(element: Dict[str, Any]) -> List[str]:
    """Each code, with the source value a synthesized one stands for (``ONH (ON-HOLD)``)."""
    values = element.get("codeValues") or {}
    return [f"{code} ({values[code]})" if code in values else code for code in element.get("codes") or []]


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
                  "| Ref | Element | Type | Min/Max | Usage | Codes | Notes |",
                  "| --- | --- | --- | --- | --- | --- | --- |"]
        for element in segment["elements"]:
            codes = ", ".join(_code_labels(element)) or "—"
            notes = "; ".join(element.get("notes") or []) or "—"
            lines.append(f"| {element['ref']} | {_cell(element['name'])} | {element['type']} | "
                         f"{element['minLength']}/{element['maxLength']} | {element['usage']} | {_cell(codes)} | "
                         f"{_cell(notes)} |")
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

    Rules (MFX-24.4, :func:`app.x12_guide_validation.guide_problems`): the guide's JSON shape; a 3-digit
    transaction set and 6-digit version; unique segment IDs (a letter, then 1-2 letters or digits); each
    segment's element refs ``<id>01`` upward with no gap; known element types; ``1 <= minLength <=
    maxLength``; usage ``M``/``O``/``X``; an ``ID`` element has codes, each within its lengths, and no other
    element has codes; ``ST01`` lists the transaction set; the structure starts with ``ST``, ends with
    ``SE``, uses every defined segment and only those, positions increase, and every loop starts with a
    segment; a maximum use is a positive count or ``">1"``.

    Raises:
        ValueError: The first rule broken, naming where.
    """
    from .x12_guide_validation import guide_problems  # noqa: PLC0415 - that module imports this one

    problems = guide_problems(guide)
    if problems:
        raise ValueError(problems[0].message)


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

