"""UN/EDIFACT message-guide emitter: canonical types → an EDIFACT message implementation guide — MFX-24.2 (#4146).

International trading partners exchange UN/EDIFACT messages (``ORDERS``, ``INVOIC``, ``DESADV`` …) rather than
X12 transaction sets. This emitter writes the item's types as an EDIFACT message implementation guide, laid out
by the **same plan** as the X12 guide (:func:`app.edi_guide.plan_guide`, MFX-24.1), so the two guides of one
item have the same segments, elements, groups and usage and cannot drift apart. Three files, as for X12:

* ``<Name>.edifact-guide.json`` — the machine-readable guide: the message, the segment directory and the
  structure (positions, segment groups, status, maximum repetitions);
* ``<Name>.edifact-segments.csv`` — the segment directory, one row per data element and component;
* ``<Name>.edifact-guide.md`` — the human-readable guide.

**EDIFACT terms.** A segment's tag is three letters (never a ``U…`` service tag). A data element is
**simple** or **composite**: a composite's values are its components (refs ``NAD02-1``, ``NAD02-2`` …) — an
imported EDIFACT message keeps its own composites, and a timestamp is a composite of its date and its time.
Each simple value has a representation: ``an..35`` (alphanumeric, up to 35), ``an3`` (exactly 3), ``n..15``
(numeric; a decimal mark is always sent, so a decimal's places are a ``decimals`` count, not implied). A
coded value — an enum, which EDIFACT calls a qualifier when it says what the next value means — lists its
codes. Status is ``M`` (mandatory), ``C`` (conditional) or ``N`` (not used). A loop is a **segment group**,
``SG1``, ``SG2`` … in order, triggered by its first segment; every repetition is a number (a list with no
``maxItems`` repeats at most ``default_max_use`` times — recorded). The message is wrapped in its ``UNH``
header (``UNH02`` = the message identifier: type, version ``D``, release, agency ``UN``) and ``UNT``
trailer; positions number the structure ``0010``, ``0020`` ….

**Options:** ``message_type`` (six letters: ``ORDERS``, ``INVOIC`` …; an imported EDIFACT item keeps its own,
else ``ORDERS``), ``release`` (the directory release: ``96A``, ``01B`` …; an imported item's own, else ``01B``),
``default_element_length`` (35), ``max_code_length`` (3) and ``default_max_use`` (9999).

The plan's losses keep their subjects; the few whose X12 wording does not fit EDIFACT (implied decimals, reals,
a split timestamp) are restated (:func:`_restate`). :mod:`app.edifact_guide_validation` checks the guide.
"""

from __future__ import annotations

import csv
import io
import json
import re
from typing import Any, Dict, List, Mapping, Optional, Union

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
    "EDIFACT_SEGMENT_TAG_RULE",
    "EdifactGuideEmitOptions",
    "EdifactGuideEmitter",
    "EdifactGuideFidelityRulePack",
    "edifact_csv",
    "edifact_markdown",
    "representation",
]

#: A segment tag a guide may give a segment made from a type: three letters, never a ``U…`` service tag.
EDIFACT_SEGMENT_TAG_RULE = r"^(?!U)[A-Z]{3}$"
#: The service segments of the envelope (also kept out by the tag rule).
_SERVICE_TAGS = frozenset({"UNA", "UNB", "UNG", "UNH", "UNT", "UNE", "UNZ", "UNS"})
_LABEL = "UN/EDIFACT message guide"
#: Plan loss subjects whose wording is restated for EDIFACT: subject → (pattern, replacement).
_RESTATEMENTS = {
    "decimal-implied": (r"is written with (\d+) implied decimal places: the value is sent without its decimal point",
                        r"is written as a number with at most \1 decimal places; EDIFACT always sends the decimal "
                        r"mark"),
    "decimal-as-real": (r"it is written as a real \(explicit decimal point\), so its precision is not fixed",
                        "it is written as a number (n..15) with its decimal mark, so its precision is not fixed"),
    "float-as-real": (r"it is written as a real \(explicit decimal point\) of at most 15 digits",
                      "it is written as a number (n..15) with its decimal mark"),
    "timestamp-split": (r"it is written as two elements, its date \(CCYYMMDD\) and its time \(HHMM\[SS…\]\)",
                        "it is written as a composite data element of two components, its date (CCYYMMDD) and "
                        "its time (HHMM[SS])"),
}


class EdifactGuideFidelityRulePack(X12GuideFidelityRulePack):
    """Fidelity rules for the UN/EDIFACT message guide — MFX-24.2 (#4146).

    The X12 guide's rules (:class:`app.x12_guide_emitter.X12GuideFidelityRulePack`, MFX-24.3) on the same plan,
    restated in EDIFACT terms, plus ``max-use-synthesized`` (SYNTH): a list with no ``maxItems`` repeats a
    stated number of times, because an EDIFACT guide has no unlimited repetition.
    """

    target_label = _LABEL
    _layout_note = ("a", "UN/EDIFACT message", "segments of simple and composite data elements in segment groups, "
                    "with EDIFACT representations and lengths")
    _WRITER_LOSSES = {
        **X12GuideFidelityRulePack._WRITER_LOSSES,
        "max-use-synthesized": (LossinessKind.SYNTH, LossinessSeverity.INFO),
    }

    def apply_options(self, options: Mapping[str, Any]) -> None:
        """Compute the report for these emit options (invalid options fall back to the defaults)."""
        try:
            self._options = EdifactGuideEmitOptions.model_validate(dict(options))
        except ValidationError:
            self._options = EdifactGuideEmitOptions()

    def _writer_losses(self, api: CanonicalApi) -> List[Loss]:
        writer = _EdifactGuideWriter(api, getattr(self, "_options", None) or EdifactGuideEmitOptions())
        try:
            writer.guide()
        except EmitPreconditionError:
            pass  # a model with no record is refused at export; there is no layout to report
        return writer.losses.records()


class EdifactGuideEmitOptions(EmitOptions):
    """Per-target options for :class:`EdifactGuideEmitter`."""

    message_type: Optional[str] = Field(
        default=None,
        description="The message type: six letters (`ORDERS`, `INVOIC`, `DESADV` …). Default: an imported "
        "EDIFACT item's own, else `ORDERS`.",
    )
    release: Optional[str] = Field(
        default=None,
        description="The directory release (`96A`, `01B` …), written with version `D`. Default: an imported "
        "EDIFACT item's own, else `01B`.",
    )
    default_element_length: int = Field(
        default=35, ge=1, le=9999,
        description="Maximum length of a text element with no maxLength (`an..35`).",
    )
    max_code_length: int = Field(
        default=3, ge=1, le=35,
        description="The longest code an enum value may be used as directly; a longer value (or one that is not "
        "upper-case letters and digits) gets a synthesized code.",
    )
    default_max_use: int = Field(
        default=9999, ge=1, le=99999,
        description="How many times a segment or segment group from a list with no maxItems may repeat.",
    )

    @field_validator("message_type")
    @classmethod
    def _six_letters(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not value.strip():
            return None
        value = value.strip().upper()
        if not re.fullmatch(r"[A-Z]{6}", value):
            raise ValueError("message_type must be a 6-letter EDIFACT message type, such as ORDERS")
        return value

    @field_validator("release")
    @classmethod
    def _release(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not value.strip():
            return None
        value = value.strip().upper().removeprefix("D.").removeprefix("D:")
        if not re.fullmatch(r"\d{2}[A-Z]", value):
            raise ValueError("release must be an EDIFACT directory release, such as 96A or 01B")
        return value


class EdifactGuideEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi`'s types as a UN/EDIFACT message implementation guide (JSON, CSV, Markdown)."""

    key = "edifact-guide"
    format = "edifact-guide"
    label = _LABEL
    description = "Export the types as a UN/EDIFACT message implementation guide (JSON, CSV and Markdown)."
    icon = "table"
    paradigm = ApiParadigm.DATA_SCHEMA
    multi_file = True
    options_model = EdifactGuideEmitOptions

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        return CapabilityProfile(operations=False, events=False, unions=False, nullability=True,
                                 constraints=False, field_identity=False)

    @classmethod
    def fidelity_rule_pack(cls) -> type[CapabilityRulePack]:
        return EdifactGuideFidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[EdifactGuideEmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        options = (
            opts
            if isinstance(opts, EdifactGuideEmitOptions)
            else EdifactGuideEmitOptions.model_validate(opts.model_dump() if opts else {})
        )
        writer = _EdifactGuideWriter(api, options)
        guide = writer.guide()
        base = _base_name(api)
        files = [
            EmittedFile(path=f"{base}.edifact-guide.json",
                        content=json.dumps(guide, indent=2, ensure_ascii=False) + "\n", media_type="application/json"),
            EmittedFile(path=f"{base}.edifact-segments.csv", content=edifact_csv(guide), media_type="text/csv"),
            EmittedFile(path=f"{base}.edifact-guide.md", content=edifact_markdown(guide), media_type="text/markdown"),
        ]
        return EmitResult(files=files, media_type="application/json", provenance=writer.tracker.records(),
                          losses=writer.losses.records())


# ---------------------------------------------------------------------------
# The guide document
# ---------------------------------------------------------------------------


def representation(element: GuideElement) -> str:
    """An EDIFACT representation: ``an..35``, ``an3`` (fixed), ``n..15``, ``n8``.

    Args:
        element: A simple guide element.

    Returns:
        ``an`` for text and codes, ``n`` for numbers, dates and times; ``..`` unless the length is fixed.
    """
    kind = "n" if element.kind in ("integer", "decimal", "date", "time") else "an"
    if element.min_length == element.max_length:
        return f"{kind}{element.max_length}"
    return f"{kind}..{element.max_length}"


_STATUS = {"M": "M", "O": "C", "X": "N"}


class _EdifactGuideWriter:
    """Builds one guide document (single use)."""

    def __init__(self, api: CanonicalApi, options: EdifactGuideEmitOptions) -> None:
        self._api = api
        self._options = options
        self.tracker = ProvenanceTracker()
        self.losses = LossTracker()
        self._position = 0
        self._position_step = 10
        self._groups = 0

    def guide(self) -> Dict[str, Any]:
        """The guide as a JSON-ready document."""
        plan_losses = LossTracker()
        plan = plan_guide(self._api, GuideOptions(default_length=self._options.default_element_length,
                                                  reserved_ids=_SERVICE_TAGS,
                                                  max_code_length=self._options.max_code_length,
                                                  segment_id_rule=EDIFACT_SEGMENT_TAG_RULE,
                                                  edifact_refs=True), plan_losses)
        if not plan.structure:
            raise EmitPreconditionError(
                "A UN/EDIFACT message guide lays out record types, and this model has none (only enums, scalars or "
                "operations)."
            )
        for loss in plan_losses.records():
            self.losses.record(loss.kind, loss.subject, _restate(loss), pointer=loss.pointer)
        message_type = self._options.message_type or _imported_type(self._api) or "ORDERS"
        release = self._options.release or _imported_release(self._api) or "01B"
        advisory = types_only_advisory(self._api, target_label=_LABEL, keep_in="OpenAPI or AsyncAPI")
        if advisory is not None:
            self.losses.record(LossKind.NA, "services-dropped", advisory.message)
        for type_ in self._api.types:
            self.tracker.record(type_.key, Provenance.SOURCE)

        segments = [_unh_segment(message_type, release), *(_segment_json(s) for s in plan.segments.values()),
                    _unt_segment()]
        # Positions are four digits: a guide with more than 998 segment uses numbers them closer together.
        self._position_step = max(1, min(10, 9999 // (_segment_uses(plan.structure) + 2)))
        structure = [self._use(SegmentUse("UNH", "M", 1)), *(self._node(n) for n in plan.structure),
                     self._use(SegmentUse("UNT", "M", 1))]
        return {
            "guide": "UN/EDIFACT message implementation guide",
            "standard": "UN/EDIFACT",
            "message": {"type": message_type, "version": "D", "release": release, "agency": "UN",
                        "name": self._api.title or self._api.identity.name or "Message"},
            "generatedFrom": {"name": self._api.identity.name, "format": self._api.format},
            "segments": segments,
            "structure": structure,
        }

    def _next_position(self) -> str:
        self._position += self._position_step
        return f"{self._position:04d}"

    def _max_use(self, value: Optional[int], source: str) -> int:
        """A repetition count; a list with no maxItems gets ``default_max_use`` (recorded)."""
        if value is not None:
            return value
        self.losses.record(LossKind.INFERRED, "max-use-synthesized",
                           f"{source!r} has no maxItems; an EDIFACT guide states how often a segment or group "
                           f"repeats, so it repeats at most {self._options.default_max_use} times (the default).",
                           pointer=source or None)
        return self._options.default_max_use

    def _use(self, use: SegmentUse) -> Dict[str, Any]:
        node: Dict[str, Any] = {"type": "segment", "position": self._next_position(), "segment": use.segment,
                                "status": _STATUS[use.usage], "maxUse": self._max_use(use.max_use, use.source)}
        if use.source:
            node["source"] = use.source
        return node

    def _node(self, node: Union[SegmentUse, GuideLoop]) -> Dict[str, Any]:
        if isinstance(node, SegmentUse):
            return self._use(node)
        self._groups += 1
        group = {"type": "group", "group": f"SG{self._groups}", "trigger": node.id, "name": node.name,
                 "status": _STATUS[node.usage], "maxUse": self._max_use(node.max_use, node.source),
                 "source": node.source}
        group["children"] = [self._node(child) for child in node.children]
        return group


def _restate(loss: Loss) -> str:
    """A plan loss in EDIFACT terms (most are standard-neutral and kept as they are)."""
    rule = _RESTATEMENTS.get(loss.subject)
    return re.sub(rule[0], rule[1], loss.detail) if rule else loss.detail


def _segment_uses(nodes: List[Union[SegmentUse, GuideLoop]]) -> int:
    return sum(_segment_uses(node.children) if isinstance(node, GuideLoop) else 1 for node in nodes)


def _imported_type(api: CanonicalApi) -> Optional[str]:
    value = api.extras.get("edifact_message_type")
    return value if isinstance(value, str) and re.fullmatch(r"[A-Z]{6}", value) else None


def _imported_release(api: CanonicalApi) -> Optional[str]:
    """An imported item's release, from its directory (``D:96A`` → ``96A``)."""
    value = api.extras.get("edifact_directory")
    match = re.fullmatch(r"D[:.]?(\d{2}[A-Z])", value) if isinstance(value, str) else None
    return match.group(1) if match else None


def _segment_json(segment: GuideSegment) -> Dict[str, Any]:
    """A segment, with a timestamp's two plan elements written as one composite of two components."""
    elements: List[Dict[str, Any]] = []
    plan_elements = list(segment.elements)
    index = 0
    while index < len(plan_elements):
        element = plan_elements[index]
        following = plan_elements[index + 1] if index + 1 < len(plan_elements) else None
        ref = f"{segment.id}{len(elements) + 1:02d}"
        if (following is not None and element.kind == "date" and following.kind == "time" and element.source
                and following.source == element.source):
            name = element.name.removesuffix(" (date)")
            elements.append({"ref": ref, "name": name, "composite": True, "status": _STATUS[element.usage],
                             "components": [_simple_json(element, f"{ref}-1"), _simple_json(following, f"{ref}-2")],
                             "source": element.source})
            index += 2
            continue
        if element.kind == "composite":
            elements.append({"ref": ref, "name": element.name, "composite": True, "status": _STATUS[element.usage],
                             "components": [_simple_json(c, f"{ref}-{k}") for k, c in
                                            enumerate(element.components, start=1)]})
        else:
            elements.append(_simple_json(element, ref))
        index += 1
    return {"tag": segment.id, "name": segment.name, "source": segment.source, "elements": elements}


def _simple_json(element: GuideElement, ref: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {"ref": ref, "name": element.name, "representation": representation(element),
                           "minLength": element.min_length, "maxLength": element.max_length,
                           "status": _STATUS[element.usage]}
    if element.kind == "decimal" and element.scale is not None:
        out["decimals"] = element.scale
    if element.kind in ("date", "time"):
        out["format"] = "102 (CCYYMMDD)" if element.kind == "date" else "HHMM[SS]"
    if element.codes:
        out["codes"] = element.codes
    if element.code_values:
        out["codeValues"] = element.code_values
    if element.notes:
        out["notes"] = element.notes
    if element.source:
        out["source"] = element.source
    return out


def _unh_segment(message_type: str, release: str) -> Dict[str, Any]:
    """The ``UNH`` message header, whose ``UNH02`` (S009) identifies the message."""
    def code(ref: str, name: str, value: str, low: int, high: int) -> Dict[str, Any]:
        return {"ref": ref, "name": name, "representation": f"an..{high}", "minLength": low, "maxLength": high,
                "status": "M", "codes": [value]}
    return {"tag": "UNH", "name": "Message header", "elements": [
        {"ref": "UNH01", "name": "Message reference number", "representation": "an..14", "minLength": 1,
         "maxLength": 14, "status": "M"},
        {"ref": "UNH02", "name": "Message identifier", "composite": True, "status": "M", "components": [
            code("UNH02-1", "Message type", message_type, 1, 6),
            code("UNH02-2", "Message version number", "D", 1, 3),
            code("UNH02-3", "Message release number", release, 1, 3),
            code("UNH02-4", "Controlling agency", "UN", 1, 3),
            {"ref": "UNH02-5", "name": "Association assigned code", "representation": "an..6", "minLength": 1,
             "maxLength": 6, "status": "C"},
        ]},
    ]}


def _unt_segment() -> Dict[str, Any]:
    return {"tag": "UNT", "name": "Message trailer", "elements": [
        {"ref": "UNT01", "name": "Number of segments in the message", "representation": "n..6", "minLength": 1,
         "maxLength": 6, "status": "M"},
        {"ref": "UNT02", "name": "Message reference number", "representation": "an..14", "minLength": 1,
         "maxLength": 14, "status": "M"},
    ]}


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------

_CSV_COLUMNS = ["segment", "segment_name", "ref", "element", "kind", "representation", "min_length", "max_length",
                "status", "codes", "notes", "source"]


def _values(segment: Dict[str, Any]):
    """Each data element of a segment, then (for a composite) each component, as ``(element, kind)``."""
    for element in segment["elements"]:
        if element.get("composite"):
            yield element, "composite"
            for component in element["components"]:
                yield component, "component"
        else:
            yield element, "simple"


def _code_labels(element: Dict[str, Any]) -> List[str]:
    values = element.get("codeValues") or {}
    return [f"{code} ({values[code]})" if code in values else code for code in element.get("codes") or []]


def edifact_csv(guide: Dict[str, Any]) -> str:
    """The segment directory: one row per data element of each segment, and one per component of a composite."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(_CSV_COLUMNS)
    for segment in guide["segments"]:
        for element, kind in _values(segment):
            writer.writerow([segment["tag"], segment["name"], element["ref"], element["name"], kind,
                             element.get("representation", ""), element.get("minLength", ""),
                             element.get("maxLength", ""), element["status"], "|".join(_code_labels(element)),
                             "; ".join(element.get("notes") or []), element.get("source", "")])
    return buffer.getvalue()


def _cell(value: Any) -> str:
    return " ".join(str(value).split()).replace("|", "\\|")


def edifact_markdown(guide: Dict[str, Any]) -> str:
    """The human-readable guide: the structure table, then each segment's data elements and codes."""
    message = guide["message"]
    lines = [
        f"# UN/EDIFACT {message['type']} message implementation guide — {_cell(message['name'])}",
        "",
        f"Directory {message['version']}.{message['release']} ({message['agency']}), message {message['type']}. "
        f"Generated by Apiome from {_cell(guide['generatedFrom'].get('name') or 'the item')}.",
        "",
        "## Structure",
        "",
        "| Pos | Tag | Name | Status | Max rep | Group |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    names = {segment["tag"]: segment["name"] for segment in guide["segments"]}

    def walk(nodes: List[Dict[str, Any]], groups: List[str]) -> None:
        for node in nodes:
            if node["type"] == "group":
                walk(node["children"], [*groups, f"{node['group']} (max {node['maxUse']}, {node['status']})"])
            else:
                lines.append(f"| {node['position']} | {node['segment']} | {_cell(names.get(node['segment'], ''))} | "
                             f"{node['status']} | {node['maxUse']} | {_cell(' › '.join(groups)) or '—'} |")

    walk(guide["structure"], [])
    lines += ["", "## Segments", ""]
    for segment in guide["segments"]:
        lines += [f"### {segment['tag']} — {_cell(segment['name'])}", "",
                  "| Ref | Data element | Repr | Min/Max | Status | Codes | Notes |",
                  "| --- | --- | --- | --- | --- | --- | --- |"]
        for element, kind in _values(segment):
            if kind == "composite":
                lines.append(f"| {element['ref']} | {_cell(element['name'])} (composite) | — | — | "
                             f"{element['status']} | — | — |")
                continue
            codes = ", ".join(_code_labels(element)) or "—"
            notes = "; ".join(element.get("notes") or []) or "—"
            name = f"  {element['name']}" if kind == "component" else element["name"]
            lines.append(f"| {element['ref']} | {_cell(name)} | {element['representation']} | "
                         f"{element['minLength']}/{element['maxLength']} | {element['status']} | {_cell(codes)} | "
                         f"{_cell(notes)} |")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
