"""COBOL copybook emitter: canonical model → `.cpy` — MFX-31.1, MFX-23.1 (#4139).

The inverse of :class:`app.cobolcopybook_normalizer.CobolCopybookNormalizer` and an implementation of
the :class:`app.emitter.Emitter` SPI.

A copybook item is re-emitted from the layout it was imported with (``cobolcopybook_tree``), so its
pictures, usages, tables and ``REDEFINES`` survive exactly. Any other source is laid out by
:func:`app.cobolcopybook_plan.plan_copybook` — one ``01`` record per top-level record type, nested
objects as group items, synthesized lengths, ``OCCURS`` counters and COBOL data names — under the
options ``numeric_usage``, ``default_string_length``, ``default_occurs`` and ``decimal_scale``.

The copybook is written in fixed format (columns 8-72, ``*`` comments in column 7) by default, or in
free format (``fixed_format=False``: no column limits, ``*>`` comments).

**PL/I output mode** (MFX-23.3, #4141): ``mode="pli"`` writes the same record layout as a PL/I include
structure (``<NAME>.pli``: ``DCL 1 … UNALIGNED``, ``CHAR`` / ``FIXED DEC`` / ``FIXED BIN`` / numeric pictures,
dimensions, ``REFER``, ``UNION``), in PL/I's margins (columns 2-72) or free format
(:mod:`app.cobolcopybook_pli`). The plan's losses are reported with the same subjects, in PL/I terms.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Literal, Mapping, Optional, Union

from pydantic import Field, ValidationError

from .canonical_model import ApiParadigm, CanonicalApi, CanonicalField, OperationKind, Type
from .cobolcopybook_parser import parse_cobolcopybook
from .cobolcopybook_plan import CopybookPlanOptions, plan_copybook
from .cobolcopybook_pli import PLI_EXTENSION, PliRenderOptions, render_pli, restate_losses
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
    "CobolCopybookEmitOptions",
    "CobolCopybookEmitter",
    "CobolCopybookFidelityRulePack",
    "copybook_emit_options",
    "copybook_emit_plan",
    "validate_cobolcopybook_document",
    "validate_pli_document",
]

_EVENT_OPERATION_KINDS = frozenset({OperationKind.PUBLISH, OperationKind.SUBSCRIBE})
#: What the PL/I output mode is called in messages (MFX-23.3).
PLI_LABEL = "PL/I include structure"
_TYPES_ONLY_DROP_MESSAGE = "only data schemas are exported"

#: Last column of a fixed-format copybook's code area (columns 8-72; 1-6 are the sequence area and
#: 7 the indicator). A reader that honours the format — including this repo's own parser — stops at
#: this column, so a clause emitted past it is not merely ugly: it is silently truncated, and the
#: truncated text parses as a *different, shorter data name*.
_CODE_AREA_END = 72
#: Area B starts in column 12: where a continuation that cannot follow the name's indent goes.
_AREA_B = " " * 11
#: Nesting deeper than this many levels is not indented further, so a 30-character name still fits.
_MAX_INDENT_LEVELS = 6


def _fixed_format_entry(prefix: str, head: str, clauses: List[str]) -> List[str]:
    """Lay out one data-description entry inside the fixed-format code area.

    A COBOL entry ends at a period, not at a line break, so an entry too long for one line
    continues onto the next. Clauses are kept whole — a clause is never split across the boundary,
    because half of ``DEPENDING ON CUST-PHONE-COUNT`` is not a shorter clause, it is a wrong one.

    Args:
        prefix: The leading whitespace placing the entry in the code area.
        head: The entry's level and name (``05  CUST-PHONES``), which always starts the first line.
        clauses: The clauses to follow it, each already rendered.

    Returns:
        One or more source lines, the last of which carries the terminating period. A single clause
        longer than the code area is emitted on its own line rather than dropped — an over-long name
        is the source's problem, and truncating it here would invent a different one.
    """
    # Continuations indent past the name, which is how a hand-written copybook reads — unless a deeply
    # nested entry would push the clause past the code area, then they start at Area B (column 12).
    continuation = " " * (len(prefix) + 15)
    lines: List[str] = []
    current = head if not prefix else f"{prefix}{head}"

    for clause in clauses:
        candidate = f"{current} {clause}"
        # +1 for the period this entry must still end with.
        if len(candidate) + 1 <= _CODE_AREA_END:
            current = candidate
            continue
        lines.append(current)
        indent = continuation if len(continuation) + len(clause) + 1 <= _CODE_AREA_END else _AREA_B
        current = f"{indent}{clause}"

    lines.append(f"{current}.")
    return lines


class CobolCopybookFidelityRulePack(CapabilityRulePack):
    """Fidelity rules for COBOL copybook export — MFX-23.1 (#4139), MFX-23.2 (#4140).

    A copybook is fixed-width and positional, so most of what it says is synthesized. The pack builds
    the copybook as it will be emitted — for the options the report is computed for
    (:meth:`apply_options`) — and files each thing the layout invented or degraded on the type or field
    it came from (its canonical key is the source path), with the message naming the COBOL item:

    * **types-only** — every operation and channel is a critical ``DROP``, and a source that has any
      carries the critical root advisory with counts (:func:`~app.fidelity_rulepack.types_only_advisory`);
    * **SYNTH** — a default ``PIC X(n)`` length for unbounded text (warn), a ``-COUNT`` counter for a
      variable table, a data name respelled to COBOL's rules (``name-mangled``);
    * **APPROX** — an unbounded list's synthesized maximum (``OCCURS … DEPENDING ON``), a list inside a
      table made fixed, a union written as ``REDEFINES``, a ``pattern`` / ``format`` kept only as a comment
      line, a float written as a decimal, a scalar with no COBOL type; and every **optional** field — a
      copybook has no null, so an absent value is written as spaces or zeros by convention;
    * **DROP** — a map, a union whose members cannot share storage (one holds ``OCCURS DEPENDING ON``), a
      reference back to a containing record, a field whose type holds no value;
    * a document of another format is noted on the root.

    A copybook item re-exported from its own layout synthesizes nothing, so it reports only what its
    source says.

    In the **PL/I output mode** (MFX-23.3) the same entries are reported in PL/I terms, and what only PL/I
    changes besides: ``conditions-as-comment``, ``names-respelled``, ``picture-as-char``,
    ``binary-scale-as-comment``, ``redefines-unresolved`` (APPROX), ``overlay-union-synthesized`` (SYNTH) and
    ``renames-dropped`` (DROP).
    Every document — a copybook item too — is noted as laid out as PL/I structures.
    """

    target_label = "COBOL copybook"

    #: Writer loss subject → (verdict kind, severity).
    _WRITER_LOSSES = {
        "length-synthesized": (LossinessKind.SYNTH, LossinessSeverity.WARN),
        "counter-synthesized": (LossinessKind.SYNTH, LossinessSeverity.INFO),
        "name-mangled": (LossinessKind.SYNTH, LossinessSeverity.INFO),
        "occurs-synthesized": (LossinessKind.APPROX, LossinessSeverity.WARN),
        "occurs-fixed": (LossinessKind.APPROX, LossinessSeverity.WARN),
        "union-as-redefines": (LossinessKind.APPROX, LossinessSeverity.WARN),
        "pattern-as-comment": (LossinessKind.APPROX, LossinessSeverity.WARN),
        "format-as-comment": (LossinessKind.APPROX, LossinessSeverity.INFO),
        "float-as-decimal": (LossinessKind.APPROX, LossinessSeverity.WARN),
        "unmapped-scalar": (LossinessKind.APPROX, LossinessSeverity.WARN),
        "map-dropped": (LossinessKind.DROP, LossinessSeverity.WARN),
        "union-dropped": (LossinessKind.DROP, LossinessSeverity.WARN),
        "recursion-cut": (LossinessKind.DROP, LossinessSeverity.WARN),
        "field-dropped": (LossinessKind.DROP, LossinessSeverity.WARN),
        # PL/I output mode only (MFX-23.3).
        "conditions-as-comment": (LossinessKind.APPROX, LossinessSeverity.INFO),
        "names-respelled": (LossinessKind.APPROX, LossinessSeverity.INFO),
        "picture-as-char": (LossinessKind.APPROX, LossinessSeverity.WARN),
        "binary-scale-as-comment": (LossinessKind.APPROX, LossinessSeverity.WARN),
        "overlay-union-synthesized": (LossinessKind.SYNTH, LossinessSeverity.INFO),
        "renames-dropped": (LossinessKind.DROP, LossinessSeverity.WARN),
        "redefines-unresolved": (LossinessKind.APPROX, LossinessSeverity.WARN),
    }
    #: Set by :meth:`evaluate`.
    _filed: Dict[str, List[FidelityVerdict]] = {}

    def apply_options(self, options: Mapping[str, Any]) -> None:
        """Compute the report for these emit options (invalid options fall back to the defaults)."""
        try:
            self._options = CobolCopybookEmitOptions.model_validate(dict(options))
        except ValidationError:
            self._options = CobolCopybookEmitOptions()

    def evaluate(self, api: CanonicalApi) -> LossinessReport:
        """Lay the copybook out once (as it will be emitted), file its losses by construct, then walk the model."""
        # A copybook item is re-emitted from its own layout (``cobolcopybook_tree``), so what its
        # pictures imply — widths, numeric bounds, overlays — is written back exactly (MFI-21.1).
        self._from_layout = isinstance(api.extras.get("cobolcopybook_tree"), dict)
        writer = _CobolCopybookWriter(api, getattr(self, "_options", None) or CobolCopybookEmitOptions())
        try:
            writer.render()
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
        """The types-only advisory, and a note when a document of another format is rewritten as a copybook."""
        verdicts: List[FidelityVerdict] = []
        pli = (getattr(self, "_options", None) or CobolCopybookEmitOptions()).mode == "pli"
        label = PLI_LABEL if pli else self.target_label
        advisory = types_only_advisory(api, target_label=label, keep_in="OpenAPI or AsyncAPI")
        if advisory is not None:
            verdicts.append(advisory)
        if pli:
            verdicts.append(
                FidelityVerdict.approx(
                    message=f"The {api.format or 'source'} document is laid out as PL/I DECLARE structures (the "
                    "copybook record layout, item for item) and reads back as a PL/I item",
                    severity=LossinessSeverity.INFO,
                    target_mapping="document → PL/I include structure",
                )
            )
        elif api.format != "cobolcopybook":
            verdicts.append(
                FidelityVerdict.approx(
                    message=f"The {api.format or 'source'} document is laid out as COBOL copybook records and "
                    "reads back as a copybook item; names, lengths and tables follow COBOL's rules",
                    severity=LossinessSeverity.INFO,
                    target_mapping="document → COBOL copybook",
                )
            )
        return verdicts + self._filed.get("", [])

    def type_verdicts(self, type_: Type) -> List[FidelityVerdict]:
        return super().type_verdicts(type_) + self._filed.get(type_.key, [])

    def field_verdicts(self, field: CanonicalField) -> List[FidelityVerdict]:
        return super().field_verdicts(field) + self._filed.get(field.key, [])

    def _nullability_verdict(self, field: CanonicalField) -> Optional[FidelityVerdict]:
        """An optional field: a fixed-width record always holds it, so absence is only a convention."""
        if field.type.nullable is False:
            return None
        return FidelityVerdict.approx(
            message="A copybook record has no null: an optional field is always present, and an absent value is "
            "written as spaces (text) or zeros (numbers) — agree that convention with the record's readers",
            severity=LossinessSeverity.INFO,
            target_mapping="optional → always present (spaces / zeros when absent)",
        )

    def _field_identity_verdict(self, field: CanonicalField) -> Optional[FidelityVerdict]:
        """A copybook identifies a field by its position, which the layout keeps: no number is involved."""
        return None

    def _constraints_verdict(self, field: CanonicalField) -> Optional[FidelityVerdict]:
        """A copybook item's constraints are its PICTURE / OCCURS, written back as declared (MFI-21.1).

        The normalizer derives ``max_length``, numeric bounds and item counts from the item's own
        clauses (``extras["cobol_picture"]`` / ``cobol_occurs_max``); re-emitted from the layout they
        lose nothing. Any other source's constraints are graded by the base rules.
        """
        if getattr(self, "_from_layout", False) and "cobol_picture" in field.extras:
            return None
        return super()._constraints_verdict(field)

    def _union_verdict(self, type_: Type) -> FidelityVerdict:
        """A copybook item's REDEFINES overlay is written back as the same REDEFINES (MFI-21.1).

        Any other union is graded by the base rules (the writer files its own ``union-as-redefines``
        or ``union-dropped`` loss for it).
        """
        if getattr(self, "_from_layout", False) and type_.extras.get("cobol_kind") == "redefines":
            return FidelityVerdict.ok(
                message=f"REDEFINES overlay carried to {self.target_label} as declared",
                target_mapping="union → REDEFINES (as imported)",
            )
        return super()._union_verdict(type_)

    def _scalar_verdict(self, type_: Type) -> FidelityVerdict:
        """An elementary REDEFINES layout's constraints are its PICTURE, written back as declared."""
        if getattr(self, "_from_layout", False) and "cobol_picture" in type_.extras:
            return FidelityVerdict.ok(message=f"scalar carried to {self.target_label}")
        return super()._scalar_verdict(type_)

    def operation_verdict(self, operation) -> FidelityVerdict:
        return FidelityVerdict.drop(
            message=f"{self.target_label} is types-only — {_TYPES_ONLY_DROP_MESSAGE}; "
            f"the {operation.kind.value} operation is dropped",
            target_mapping="operation → dropped (types-only export)",
        )

    def channel_verdict(self, channel) -> FidelityVerdict:
        return FidelityVerdict.drop(
            message=f"{self.target_label} is types-only — {_TYPES_ONLY_DROP_MESSAGE}; "
            "the event channel is dropped",
            target_mapping="channel → dropped (types-only export)",
        )


def _owning_construct(pointer: str, constructs: set) -> str:
    """The construct a writer loss belongs to: its own key, else the longest key it extends, else the root."""
    if pointer in constructs:
        return pointer
    owners = [key for key in constructs if key and pointer.startswith(f"{key}.")]
    return max(owners, key=len) if owners else ""


class CobolCopybookEmitOptions(EmitOptions):
    """Per-target options for :class:`CobolCopybookEmitter`."""

    include_comments: bool = Field(
        default=True,
        description="Emit a header comment block in the generated copybook.",
    )
    fixed_format: bool = Field(
        default=True,
        description="Fixed-format layout (code in columns 8-72, long entries continued on the next line); "
        "`false` writes free format with no column limits.",
    )
    numeric_usage: Literal["comp", "display"] = Field(
        default="comp",
        description="`comp`: binary integers (`COMP`), packed decimals (`COMP-3`) and floats (`COMP-1`/`COMP-2`); "
        "`display`: zoned decimal numbers. Applies to a source that is not a copybook.",
    )
    default_string_length: int = Field(
        default=255, ge=1, le=32767,
        description="Length of text with no maxLength (`PIC X(n)`).",
    )
    default_occurs: int = Field(
        default=10, ge=1, le=32767,
        description="Maximum occurrences of a list with no maxItems (`OCCURS … TO n`).",
    )
    decimal_scale: int = Field(
        default=2, ge=0, le=17,
        description="Digits after the decimal point of a decimal with no multipleOf (`S9(p)V9(s)`).",
    )
    mode: Literal["copybook", "pli"] = Field(
        default="copybook",
        description="`copybook` (default) writes a COBOL copybook (`<NAME>.cpy`). `pli` writes the same record "
        "layout as a PL/I include structure (`<NAME>.pli`): `DCL 1 … UNALIGNED` with `CHAR`, `FIXED DEC`, "
        "`FIXED BIN` and numeric pictures, dimensions, `REFER` and `UNION`. `fixed_format` keeps PL/I within "
        "columns 2-72.",
    )


class CobolCopybookEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as a COBOL copybook (``.cpy``)."""

    key = "cobolcopybook"
    format = "cobolcopybook"
    label = "COBOL Copybook"
    description = "Export as a COBOL copybook record layout (.cpy) from any source."
    icon = "file-code"
    paradigm = ApiParadigm.DATA_SCHEMA
    multi_file = False
    options_model = CobolCopybookEmitOptions

    OUTPUT_MEDIA_TYPE = "text/plain"

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        return CapabilityProfile(
            operations=False,
            events=False,
            unions=False,
            nullability=False,
            field_identity=True,
        )

    @classmethod
    def fidelity_rule_pack(cls) -> type[CapabilityRulePack]:
        return CobolCopybookFidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[CobolCopybookEmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        options = (
            opts
            if isinstance(opts, CobolCopybookEmitOptions)
            else CobolCopybookEmitOptions.model_validate(opts.model_dump() if opts else {})
        )
        writer = _CobolCopybookWriter(api, options)
        content = writer.render()
        return EmitResult(
            files=[
                EmittedFile(
                    path=writer.output_path,
                    content=content,
                    media_type=self.OUTPUT_MEDIA_TYPE,
                )
            ],
            media_type=self.OUTPUT_MEDIA_TYPE,
            provenance=writer.tracker.records(),
            losses=writer.losses.records(),
        )


class _CobolCopybookWriter:
    """Writes one copybook (single use)."""

    def __init__(self, api: CanonicalApi, options: CobolCopybookEmitOptions) -> None:
        self._api = api
        self._options = options
        self.tracker = ProvenanceTracker()
        self.losses = LossTracker()
        self._tree = api.extras.get("cobolcopybook_tree")
        self.output_path = _output_path(api, PLI_EXTENSION if options.mode == "pli" else ".cpy")

    def trees(self) -> List[Dict[str, Any]]:
        """The emit plan: the import-time tree of a copybook item, else one planned tree per ``01`` record."""
        if isinstance(self._tree, dict):
            return [self._tree]
        return plan_copybook(
            self._api,
            CopybookPlanOptions(
                numeric_usage=self._options.numeric_usage,
                default_string_length=self._options.default_string_length,
                default_occurs=self._options.default_occurs,
                decimal_scale=self._options.decimal_scale,
            ),
            self.losses,
        )

    def render(self) -> str:
        """The copybook text: an optional header, then each ``01`` record."""
        trees = self.trees()
        if not trees:
            raise EmitPreconditionError(
                "COBOL copybook export lays out record types, and this model has none (only enums, scalars or "
                "operations)."
            )
        if self._options.mode == "pli":
            return self._render_pli(trees)
        lines: List[str] = []
        if self._options.include_comments:
            title = self._api.identity.name or "Exported record"
            lines.extend(self._header(title))
        for index, tree in enumerate(trees):
            if index:
                lines.append("")
            self._render_field(tree, lines=lines, indent=0)
        # The engine labels the report with the emitter's label, so the emit loss reads the same.
        advisory = types_only_advisory(
            self._api, target_label=CobolCopybookEmitter.label, keep_in="OpenAPI or AsyncAPI"
        )
        if advisory is not None:
            self.losses.record(LossKind.NA, "services-dropped", advisory.message)
        self.tracker.record(self._api.identity.name or "cobolcopybook", Provenance.SOURCE)
        return "\n".join(lines).rstrip() + "\n"

    def _render_pli(self, trees: List[Dict[str, Any]]) -> str:
        """The same trees as a PL/I include member (MFX-23.3); the plan's losses restated in PL/I terms."""
        own = LossTracker()
        text, names = render_pli(
            trees,
            title=self._api.identity.name or "Exported record",
            options=PliRenderOptions(
                fixed_format=self._options.fixed_format, include_comments=self._options.include_comments
            ),
            losses=own,
        )
        renamed = sorted((c, p) for c, p in names.items() if p not in {c, "*"} and c != p)
        if renamed and isinstance(self._tree, dict):
            # A copybook item's names are its own: respelling them for PL/I is the one change to report.
            example = renamed[0]
            own.record(
                LossKind.INFERRED,
                "names-respelled",
                f"PL/I names cannot hold a hyphen, so every COBOL data name with one is written with an "
                f"underscore ({len(renamed)} name(s), such as {example[0]} → {example[1]}).",
            )
        losses = LossTracker()
        for loss in [*restate_losses(self.losses.records(), names), *own.records()]:
            losses.record(loss.kind, loss.subject, loss.detail, pointer=loss.pointer)
        advisory = types_only_advisory(self._api, target_label=PLI_LABEL, keep_in="OpenAPI or AsyncAPI")
        if advisory is not None:
            losses.record(LossKind.NA, "services-dropped", advisory.message)
        self.losses = losses
        self.tracker.record(self._api.identity.name or "cobolcopybook", Provenance.SOURCE)
        return text

    def _header(self, title: str) -> List[str]:
        """The generated-file banner: ``*`` in column 7 (fixed format) or ``*>`` (free format)."""
        title = " ".join(str(title).split())
        if not self._options.fixed_format:
            return [f"*> Generated COBOL copybook for {title}"]
        rule = "      *" + "*" * 65
        return [rule, f"      * Generated COBOL copybook for {title}"[:_CODE_AREA_END], rule]

    def _render_field(self, node: Dict[str, Any], *, lines: List[str], indent: int) -> None:
        level = int(node.get("level", 1))
        name = str(node.get("name", "RECORD"))
        picture = node.get("picture")
        usage = node.get("usage")
        occurs_min = node.get("occurs_min")
        occurs_max = node.get("occurs_max")
        depending_on = node.get("depending_on")
        redefines = node.get("redefines")
        children = node.get("children") or []

        clauses: List[str] = []
        # REDEFINES comes first, as COBOL requires: it qualifies the item's storage, and everything
        # after it describes that storage. Emitting it at all is CPDO-2.3 — without it an export
        # turns two overlays into two sequential items and silently changes the record's length.
        if isinstance(redefines, str) and redefines:
            clauses.append(f"REDEFINES {redefines}")
        if isinstance(picture, str) and picture:
            clauses.append(f"PIC {picture}")
        if isinstance(usage, str) and usage:
            clauses.append(usage)
        if occurs_max is not None:
            high = int(occurs_max)
            if isinstance(depending_on, str) and depending_on:
                low = int(occurs_min if occurs_min is not None else 1)
                clauses.append(f"OCCURS {low} TO {high} TIMES")
                # Its own clause, so it wraps onto a continuation line whole rather than being cut
                # in half by the code-area boundary.
                clauses.append(f"DEPENDING ON {depending_on}")
            else:
                # A fixed table (MFX-23.1): `OCCURS n TO n TIMES` is only legal with DEPENDING ON.
                clauses.append(f"OCCURS {high} TIMES")
        head = f"{level:02d}  {name}"
        for comment in node.get("comments") or []:
            lines.extend(self._comment(str(comment)))
        lines.extend(self._entry(head, clauses, indent))

        for condition in node.get("conditions") or []:
            if not isinstance(condition, dict):
                continue
            cond_name = str(condition.get("name", "VALUE"))
            lines.extend(self._entry(f"88  {cond_name:<24}", [f"VALUE {_condition_value(condition)}"], indent + 1))

        if isinstance(children, list):
            for child in children:
                if isinstance(child, dict):
                    self._render_field(child, lines=lines, indent=indent + 1)

    def _comment(self, text: str) -> List[str]:
        """A comment above an entry (a constraint a picture cannot hold): ``*`` in column 7, or ``*>``.

        In fixed format the text is split so every line ends by column 72; a line break in the text
        never starts a new entry.
        """
        text = " ".join(text.split())
        if not self._options.fixed_format:
            return [f"*> {text}"]
        width = _CODE_AREA_END - len("      * ")
        return [f"      * {text[i:i + width]}" for i in range(0, len(text), width)] or ["      *"]

    def _entry(self, head: str, clauses: List[str], indent: int) -> List[str]:
        """One entry: wrapped inside the code area (fixed format), or on one line (free format)."""
        if not self._options.fixed_format:
            # Free format has no columns; nesting is carried by the level numbers.
            return [" ".join([head.rstrip(), *clauses]) + "."]
        return _fixed_format_entry(" " * 7 + " " * (min(indent, _MAX_INDENT_LEVELS) * 4), head, clauses)


#: A list or range of quoted literals, recorded as written by the parser (``'B' 'X'``, ``'A' THRU 'C'``).
_LITERAL_LIST_RE = re.compile(
    r"""^(?:'(?:[^']|'')*'|"(?:[^"]|"")*")(?:(?:\s*,\s*|\s+|\s+(?:THRU|THROUGH)\s+)(?:'(?:[^']|'')*'|"(?:[^"]|"")*"))+$""",
    re.IGNORECASE,
)


def _condition_value(condition: Dict[str, Any]) -> str:
    """An ``88`` level's value: a number as is, a list of literals as imported, else text in quotes.

    A quote inside a single text value is doubled. A list or range of quoted literals is the form the
    parser keeps verbatim (:func:`~app.cobolcopybook_parser.condition_value`), so it is written back
    unchanged rather than re-quoted into one literal (MFI-21.1).
    """
    value = str(condition.get("value", ""))
    if condition.get("numeric") and value.lstrip("-").isdigit():
        return value
    if _LITERAL_LIST_RE.match(value):
        return value
    return "'" + value.replace("'", "''") + "'"


def _output_path(api: CanonicalApi, extension: str = ".cpy") -> str:
    root = api.extras.get("cobolcopybook_root")
    base = str(root) if isinstance(root, str) and root else api.identity.name or "record"
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", base).strip("-") or "record"
    return f"{safe}{extension}"


def copybook_emit_options(options: Optional[Mapping[str, Any]] = None) -> CobolCopybookEmitOptions:
    """The emitter's options from an export request's raw ``options`` (the defaults when they do not validate).

    Args:
        options: The per-target options the export ran with; ``None`` or empty for the defaults.

    Returns:
        The validated :class:`CobolCopybookEmitOptions`.
    """
    try:
        return CobolCopybookEmitOptions.model_validate(dict(options or {}))
    except ValidationError:
        return CobolCopybookEmitOptions()


def copybook_emit_plan(api: CanonicalApi, options: CobolCopybookEmitOptions) -> List[Dict[str, Any]]:
    """The record layouts the emitter writes for ``api`` — MFX-23.4 (#4142).

    The same trees :meth:`CobolCopybookEmitter.emit` renders, so the cb2xml validation
    (:mod:`app.cobolcopybook_cb2xml`) can check that a copybook parses to exactly the layout planned.

    Args:
        api: The canonical model the copybook was emitted from.
        options: The options it was emitted with.

    Returns:
        One tree per ``01`` record, in the shape of :func:`app.cobolcopybook_parser.field_template`.
    """
    return _CobolCopybookWriter(api, options).trees()


def validate_cobolcopybook_document(content: str) -> None:
    """Validate COBOL copybook text by re-parsing it."""
    parse_cobolcopybook(content)


def validate_pli_document(content: str) -> None:
    """Validate a PL/I include member by re-parsing it with Apiome's PL/I reader (MFX-23.3)."""
    from .pli_parser import parse_pli_text

    parse_pli_text(content, label="export.pli")
