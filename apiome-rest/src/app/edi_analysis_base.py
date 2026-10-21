"""Shared EDI analysis base — FMT-6.1 (#5445).

The X12 extractor (:mod:`app.edix12_analysis`, CPDO-1.2/2.2) set an honesty contract for an EDI
payload analysis, and every EDI family that follows it — UN/EDIFACT (:mod:`app.edifact_analysis`)
first, then the EDIFACT dialect profiles, payment files and NCPDP — has to keep the *same* contract,
not a lookalike of it. This module is where the pieces of that contract that do not depend on any
one syntax live, so a second family inherits them rather than re-deriving them:

* **Locations.** :func:`segment_location` builds a node's
  :class:`~app.payload_analysis.SourceLocation` from a segment's byte position, or from its envelope
  path and ordinal alone when no checked position exists — never something in between.
* **Declared versus observed control counts.** :func:`int_or_none` reads a trailer's control total
  without ever turning an unreadable declaration into a zero, and :class:`ControlCount` /
  :func:`control_count_warnings` state a disagreement between what a trailer *declared* and what the
  envelope *carried*, so a self-inconsistent interchange is visibly so.
* **The five-way element presence vocabulary.** :func:`observed_value_node` is the single
  constructor for an observed value: a position the source wrote is ``value_present`` with its
  length (zero when it was written and left empty), and the value itself sits in ``value``, the one
  field :func:`~app.payload_analysis.apply_value_visibility` governs. A position the source never
  wrote is not a node at all. The reader-side vocabulary — *has value*, *present-empty*,
  *withheld*, *not present*, *not recorded* — is derived from exactly those three fields, so a
  family that builds its value nodes here gets it by construction.
* **Envelopes before leaves.** :func:`envelope_node_budget` raises a node budget to fit every
  envelope node, so a bounded analysis drops elements and never a group or a message.
* **The canonical-subset statement.** :func:`canonical_subset_warning` says, explicitly, when the
  canonical model was derived from one message of several.
* **The implementation-guide statement.** :func:`implementation_guide_statement` is the sentence
  every EDI family's capability declaration carries: nothing here consults an implementation guide,
  so a structurally valid interchange is never presented as a conformant one.

Nothing in this module parses anything. It takes facts an extractor already holds and states them
the way every EDI record states them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Protocol, Sequence

from .payload_analysis import SEVERITY_INFO, AnalysisWarning, SourceLocation
from .payload_analyzer import MAX_VISITED_NODES, NativeNode

__all__ = [
    "ControlCount",
    "SegmentPosition",
    "canonical_subset_warning",
    "control_count_warnings",
    "envelope_node_budget",
    "implementation_guide_statement",
    "int_or_none",
    "observed_value_node",
    "segment_location",
]


class SegmentPosition(Protocol):
    """Where one segment's bytes sit in the interchange text.

    Any raw-segment record with these four attributes qualifies — X12's scan result
    (:class:`~app.edix12_segment_scan.X12RawSegment`) and EDIFACT's parsed segment
    (:class:`~app.edifact_parser.EdifactSegment`) both do.

    Attributes:
        line: 1-based line the segment starts on.
        column: 1-based column the segment starts at.
        offset: 0-based character offset of the segment's first character.
        length: Number of characters the segment occupies, terminator included.
    """

    line: int
    column: int
    offset: int
    length: int


def segment_location(
    raw: Optional[SegmentPosition], *, ordinal: int, path: str
) -> SourceLocation:
    """Build a node's location, carrying source positions only where they were checked.

    Args:
        raw: The segment's position, when the extractor holds one it can vouch for.
        ordinal: The node's sibling ordinal.
        path: The node's envelope path (``ISA/GS[0]/ST[2]/NM1[4]``, ``UNB/UNG[0]/UNH[1]/NAD[3]``).

    Returns:
        A :class:`~app.payload_analysis.SourceLocation` with offset/length/line/column when a
        position was supplied, and with path and ordinal alone when it was not. Nothing in between
        is emitted: a location either addresses bytes, or addresses structure.
    """
    if raw is None:
        return SourceLocation(ordinal=ordinal, path=path)
    return SourceLocation(
        line=raw.line,
        column=raw.column,
        offset=raw.offset,
        length=raw.length,
        ordinal=ordinal,
        path=path,
    )


def int_or_none(value: Optional[str]) -> Optional[int]:
    """Return ``value`` as an int, or ``None`` when it is not a plain integer.

    A control total that is not a number is not reported as zero — an unreadable declaration and a
    declaration of nothing are different facts, and only the first should ever look like a fault.

    Args:
        value: The declared text, as the trailer carried it.

    Returns:
        The integer, or ``None`` for an absent, blank or non-numeric declaration.
    """
    if value is None:
        return None
    text = value.strip()
    if not text or not text.lstrip("+-").isdigit():
        return None
    return int(text)


def observed_value_node(
    *,
    kind: str,
    name: str,
    ordinal: int,
    path: str,
    value: str,
    attributes: Optional[dict] = None,
    label: Optional[str] = None,
) -> NativeNode:
    """Describe one value the source wrote — the only way an EDI value node is built.

    The position exists in the source: the delimiter that opened it proves that much, so
    ``value_present`` is always true here. Whether it carried anything is the length, and a zero
    length means *present and empty*. The value itself goes in ``value`` and nowhere else, so the
    value-visibility policy decides what the stored record keeps and no attribute can carry a payload
    value past it.

    Args:
        kind: The node kind (``element``, ``component``, ``repetition``).
        name: Its reference (``BGM01``, ``DTM01-2``, ``BEG01[0]``).
        ordinal: Its sibling ordinal.
        path: Its envelope path.
        value: The observed text, delimiters and release characters already resolved.
        attributes: Structure only — position, reference, repeat index.
        label: Optional human label.

    Returns:
        The :class:`~app.payload_analyzer.NativeNode`.
    """
    return NativeNode(
        kind=kind,
        name=name,
        label=label,
        ordinal=ordinal,
        attributes=dict(attributes or {}),
        location=SourceLocation(ordinal=ordinal, path=path),
        value_present=True,
        value_length=len(value),
        value=value,
    )


def envelope_node_budget(max_nodes: int, envelope_nodes: int) -> int:
    """Return a node budget that keeps every envelope node.

    Breadth-first admission keeps envelopes before leaves, but only while the budget lasts. Raising
    the budget to the number of envelope nodes makes "every group and message is kept" hold by
    construction — never above what a single analysis may visit, so an interchange whose envelope
    alone exceeds the visit cap is bounded like anything else, and says so.

    Args:
        max_nodes: The requested budget.
        envelope_nodes: How many interchange/group/message nodes the interchange contains.

    Returns:
        ``min(MAX_VISITED_NODES, max(max_nodes, envelope_nodes))``.
    """
    return min(MAX_VISITED_NODES, max(max_nodes, envelope_nodes))


def canonical_subset_warning(
    *,
    code: str,
    derived_from: str,
    observed: int,
    unit: str,
    scope: str = "",
) -> List[AnalysisWarning]:
    """State, explicitly, when the canonical conversion read less than the analysis did.

    A canonical model describes one schema, so an EDI normalizer reads one message. That is a
    correct decision and an invisible one: the model a reader is looking at may have been derived
    from a fraction of the interchange they imported. The analysis knows, so it says.

    Args:
        code: The family's warning code (``x12.canonical_projection_subset``).
        derived_from: What the conversion read (``transaction set 850 (0001) in functional group
            PO``).
        observed: How many such units the interchange carried.
        unit: The family's word for one unit (``transaction set``, ``message``).
        scope: Optional trailing phrase on the count (`` across 2 functional group(s)``).

    Returns:
        A one-entry ``info`` list when more than one unit was observed, else empty. Informational
        because nothing was dropped from the *analysis* — every unit is in the tree.
    """
    if observed <= 1:
        return []
    return [
        AnalysisWarning(
            code=code,
            severity=SEVERITY_INFO,
            message=(
                f"The canonical model is derived from {derived_from} alone. This interchange "
                f"carries {observed} {unit}(s){scope}; the remaining {observed - 1} are described "
                "here and nowhere else."
            ),
        )
    ]


@dataclass(frozen=True)
class ControlCount:
    """One trailer's declared control total beside the count the envelope actually carried.

    Attributes:
        subject: What the trailer closes, for the message (``message 1 (ORDERS)``).
        counted: What the total counts, plural (``segments``, ``messages``).
        trailer: The trailer that declared it (``UNT``, ``UNE``, ``UNZ``).
        declared: The declared total, or ``None`` when the trailer is absent or unreadable.
        observed: The count observed.
    """

    subject: str
    counted: str
    trailer: str
    declared: Optional[int]
    observed: int

    @property
    def consistent(self) -> Optional[bool]:
        """Whether the declaration agrees with the observation; ``None`` when nothing was declared."""
        if self.declared is None:
            return None
        return self.declared == self.observed


def control_count_warnings(code: str, counts: Iterable[ControlCount]) -> List[AnalysisWarning]:
    """Name every control total that disagrees with what the envelope carried.

    The interchange is not rejected for disagreeing with itself — the counts are a claim about the
    payload, and the payload is still readable. What a reader must not have to do is find the
    disagreement by comparing two attributes on two rows, so each one is stated.

    ``info`` on purpose: nothing was dropped from the analysis and nothing went unmodelled, so the
    record stays ``available``; the warning is a fact about the *source*.

    Args:
        code: The family's warning code (``edifact.control_count_mismatch``).
        counts: Every control total the extractor read.

    Returns:
        One warning per inconsistent count, in the order given. A count with no declaration is not
        a disagreement and yields nothing.
    """
    warnings: List[AnalysisWarning] = []
    for count in counts:
        if count.consistent is not False:
            continue
        warnings.append(
            AnalysisWarning(
                code=code,
                severity=SEVERITY_INFO,
                message=(
                    f"{count.trailer} declares {count.declared} {count.counted} for "
                    f"{count.subject}, but {count.observed} were observed. The interchange "
                    "disagrees with itself; both figures are recorded."
                ),
            )
        )
    return warnings


def implementation_guide_statement(standard: str, guides: Sequence[str]) -> str:
    """The sentence every EDI capability declaration carries about implementation guides.

    Args:
        standard: The syntax standard that *was* read (``UN/EDIFACT syntax (ISO 9735)``).
        guides: Examples of the guides that were not consulted (``D.96A``, ``EANCOM``).

    Returns:
        A reviewed sentence stating that only the syntax was read and no guide was consulted.
    """
    examples = ", ".join(guides)
    return (
        f"Only the {standard} is read. No implementation guide ({examples}…) is consulted, so a "
        "structurally valid interchange is not claimed to be a conformant one, and a message "
        "version or association code is recorded as the sender's claim rather than as a checked "
        "fact."
    )
