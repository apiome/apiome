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
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import Field

from .canonical_model import ApiParadigm, CanonicalApi, OperationKind
from .cobolcopybook_parser import parse_cobolcopybook
from .cobolcopybook_plan import CopybookPlanOptions, plan_copybook
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
from .fidelity_rulepack import CapabilityRulePack, FidelityVerdict
from .lossiness import LossinessSeverity

__all__ = [
    "CobolCopybookEmitOptions",
    "CobolCopybookEmitter",
    "CobolCopybookFidelityRulePack",
    "validate_cobolcopybook_document",
]

_EVENT_OPERATION_KINDS = frozenset({OperationKind.PUBLISH, OperationKind.SUBSCRIBE})
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
    """Fidelity rules for COBOL copybook export (the full pack is MFX-23.2).

    Beside the types-only drops, a document of another format is noted on the root (MFX-23.1): it is laid
    out as copybook records and reads back as a copybook item, keyed by its ``01`` record.
    """

    target_label = "COBOL copybook"

    def root_verdicts(self, api: CanonicalApi) -> List[FidelityVerdict]:
        """A note when a document of another format is rewritten as a copybook."""
        if api.format == "cobolcopybook":
            return []
        return [
            FidelityVerdict.approx(
                message=f"The {api.format or 'source'} document is laid out as COBOL copybook records and reads "
                "back as a copybook item; names, lengths and tables follow COBOL's rules",
                severity=LossinessSeverity.INFO,
                target_mapping="document → COBOL copybook",
            )
        ]

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
        self.output_path = _output_path(api)

    def render(self) -> str:
        """The copybook text: an optional header, then each ``01`` record."""
        trees = [self._tree] if isinstance(self._tree, dict) else plan_copybook(
            self._api,
            CopybookPlanOptions(
                numeric_usage=self._options.numeric_usage,
                default_string_length=self._options.default_string_length,
                default_occurs=self._options.default_occurs,
                decimal_scale=self._options.decimal_scale,
            ),
            self.losses,
        )
        if not trees:
            raise EmitPreconditionError(
                "COBOL copybook export lays out record types, and this model has none (only enums, scalars or "
                "operations)."
            )
        lines: List[str] = []
        if self._options.include_comments:
            title = self._api.identity.name or "Exported record"
            lines.extend(self._header(title))
        for index, tree in enumerate(trees):
            if index:
                lines.append("")
            self._render_field(tree, lines=lines, indent=0)
        if self._api.services or self._api.channels:
            self.losses.record(
                LossKind.NA,
                "services-dropped",
                "COBOL copybook export is types-only; services and channels are omitted",
            )
        self.tracker.record(self._api.identity.name or "cobolcopybook", Provenance.SOURCE)
        return "\n".join(lines).rstrip() + "\n"

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

    def _entry(self, head: str, clauses: List[str], indent: int) -> List[str]:
        """One entry: wrapped inside the code area (fixed format), or on one line (free format)."""
        if not self._options.fixed_format:
            # Free format has no columns; nesting is carried by the level numbers.
            return [" ".join([head.rstrip(), *clauses]) + "."]
        return _fixed_format_entry(" " * 7 + " " * (min(indent, _MAX_INDENT_LEVELS) * 4), head, clauses)


def _condition_value(condition: Dict[str, Any]) -> str:
    """An ``88`` level's value: a number as is, text in quotes (a quote inside doubled)."""
    value = str(condition.get("value", ""))
    if condition.get("numeric") and value.lstrip("-").isdigit():
        return value
    return "'" + value.replace("'", "''") + "'"


def _output_path(api: CanonicalApi) -> str:
    root = api.extras.get("cobolcopybook_root")
    base = str(root) if isinstance(root, str) and root else api.identity.name or "record"
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", base).strip("-") or "record"
    return f"{safe}.cpy"


def validate_cobolcopybook_document(content: str) -> None:
    """Validate COBOL copybook text by re-parsing it."""
    parse_cobolcopybook(content)
