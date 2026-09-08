"""CTG-4.2 consumer-aware breaking analysis (#4480).

A whole-spec verdict ("47 breaking changes") tells a provider to panic and tells a consumer
nothing. This module answers the question that actually gates a release: *whose* code does this
change break? It intersects the CTG-1.1 classified change list
(:class:`~app.change_taxonomy.ClassifiedDiff`) with each registered consumer's declared surface
(CTG-4.1, :mod:`app.consumer_contract`) and produces a per-consumer verdict plus the
"breaks 2 of 7 consumers" summary.

This module is **pure** — no DB, no network. :mod:`app.consumer_impact_service` is the seam that
loads the registry and calls it; ``POST /v1/diff/{tenant}/classified`` with ``consumers: true``
is the HTTP surface.

How a change is attributed
--------------------------

Both sides speak the same JSON Pointer vocabulary — that is the whole reason CTG-4.1 stores
pointers written exactly the way :mod:`app.change_taxonomy_enum` writes them — so attribution is
a pointer comparison rather than a re-derivation of what a change touched.

Pointer overlap is **segment-aware**, unlike the ``starts_with`` narrowing query in
``db.find_consumer_contracts_by_pointers``: ``/components/schemas/Pet`` must not be treated as
touching ``/components/schemas/PetFood``. The SQL is allowed to over-select because it only
narrows the candidate set; this module renders the verdict, so it is exact.

Three match kinds, from most to least specific:

``field``
    The change overlaps a declared field's pointer in **either** direction — a change at
    ``…/schema`` touches a field below it, and a change at ``…/properties/name/type`` touches the
    field declared at ``…/properties/name``. Both of a field's pointers are tried (the
    operation-anchored one and the ``$ref`` target), because which one the classifier emits
    depends on how the document was authored, not on what the consumer uses.

``operation``
    The change is at or above a declared operation (``/paths/~1pets`` removed), or inside one at a
    node that affects every caller regardless of the fields they read: parameters, security,
    servers, response codes, the schema root. An operation declared with **no** fields is
    operation-wide throughout — nothing finer was declared, so nothing finer can be claimed.

``document``
    The change is under a document-wide node (:data:`DOCUMENT_WIDE_PREFIXES`) — root security,
    servers, security schemes. These reach every caller and would otherwise be reported as
    affecting nobody, which is the one silence that would matter.

The deliberate exclusion is the point of the ticket: a change **inside a body schema**, on an
operation whose consumer declared which fields it reads, attributes only when one of those fields
is met. Removing a field nobody reads breaks nobody.

Known limitation: a change under ``/components/schemas/...`` reaches a consumer only through a
declared field's ``schema_pointer``. A contract that declared an operation but no fields cannot be
linked to the components its body ``$ref``\\ s, so such a change is reported as unattributed for
that consumer. Declaring fields — which the Pact importer and the UI picker both do — resolves it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field

from .change_taxonomy import ClassifiedChange, ClassifiedDiff
from .consumer_contract import (
    ConsumerContractField,
    ConsumerContractOperation,
    ConsumerSummary,
)

__all__ = [
    "CONSUMER_IMPACT_SCHEMA_VERSION",
    "DOCUMENT_WIDE_PREFIXES",
    "MAX_IMPACTS_PER_CONSUMER",
    "ChangeAttribution",
    "ConsumerChangeImpact",
    "ConsumerImpactReport",
    "ConsumerVerdict",
    "analyze_consumer_impact",
    "pointer_covers",
    "pointer_segments",
    "pointers_overlap",
    "render_consumer_impact_markdown",
]

#: Stable schema id for JSON consumers (CLI gate output, CTG-4.5 deploy gate).
CONSUMER_IMPACT_SCHEMA_VERSION = "ctg.consumer-impact.v1"

#: Nodes whose change reaches every caller of the document, whatever they declared.
#: Deliberately short: ``/info`` and ``/tags`` move nobody's code, and adding them here would
#: mark every consumer "affected" on a typo fix.
DOCUMENT_WIDE_PREFIXES: Tuple[str, ...] = (
    "/security",
    "/servers",
    "/components/securitySchemes",
)

#: Per-consumer cap on emitted impact rows. One change can meet forty declared fields (a whole
#: ``$ref``\\ ed schema removed); the *counts* stay exact, only the enumeration is bounded.
MAX_IMPACTS_PER_CONSUMER = 500

#: Verdicts a consumer can receive, worst first. ``undeclared`` is not a severity — it means the
#: consumer is registered but has never declared a surface, so no claim can be made about it.
VERDICT_BREAKING = "breaking"
VERDICT_NON_BREAKING = "non-breaking"
VERDICT_DOCS_ONLY = "docs-only"
VERDICT_UNAFFECTED = "unaffected"
VERDICT_UNDECLARED = "undeclared"

_SEVERITY_RANK: Dict[str, int] = {
    "docs-only": 0,
    "non-breaking": 1,
    "breaking": 2,
}

MATCH_DOCUMENT = "document"
MATCH_OPERATION = "operation"
MATCH_FIELD = "field"


# -------------------------------------------------------------------------------------------
# Pointer algebra
# -------------------------------------------------------------------------------------------


def pointer_segments(pointer: str) -> Tuple[str, ...]:
    """Split a JSON Pointer into its raw (still-escaped) segments.

    Escapes are left alone: both sides of the comparison were produced by
    :func:`~app.change_taxonomy_enum.json_pointer_join`, so they are escaped identically and
    unescaping would only create a way for ``~1`` and ``/`` to be confused.

    Args:
        pointer: A JSON Pointer such as ``/paths/~1pets/get``.

    Returns:
        The segments, empty for the root pointer (``""`` or ``"/"``).
    """
    text = (pointer or "").strip()
    if not text or text == "/":
        return ()
    if text.startswith("/"):
        text = text[1:]
    return tuple(text.split("/"))


def _segments_cover(outer: Tuple[str, ...], inner: Tuple[str, ...]) -> bool:
    """:func:`pointer_covers` on already-split pointers, so a hot loop splits nothing."""
    if len(outer) > len(inner):
        return False
    return inner[: len(outer)] == outer


def _segments_overlap(left: Tuple[str, ...], right: Tuple[str, ...]) -> bool:
    """:func:`pointers_overlap` on already-split pointers."""
    return _segments_cover(left, right) or _segments_cover(right, left)


def pointer_covers(outer: str, inner: str) -> bool:
    """Whether ``outer`` is ``inner`` or a **segment-wise** ancestor of it.

    Segment-wise is what separates this from a string prefix: ``/components/schemas/Pet`` covers
    ``/components/schemas/Pet/properties/name`` but not ``/components/schemas/PetFood``.

    Args:
        outer: The candidate ancestor pointer.
        inner: The candidate descendant pointer.

    Returns:
        True when ``inner`` is at or below ``outer``.
    """
    return _segments_cover(pointer_segments(outer), pointer_segments(inner))


def pointers_overlap(left: str, right: str) -> bool:
    """Whether either pointer is at or below the other.

    Tested both ways because a classified change and a declared field are not always at the same
    depth: a change at ``/components/schemas/Pet`` touches a field at ``…/Pet/properties/name``,
    and a change at ``…/properties/name/type`` touches a field declared at ``…/properties/name``.

    Args:
        left: One pointer.
        right: The other pointer.

    Returns:
        True when the two nodes intersect.
    """
    return pointer_covers(left, right) or pointer_covers(right, left)


def _is_document_wide(pointer: str) -> bool:
    """Whether a change pointer sits under a node that reaches every caller."""
    return any(pointer_covers(prefix, pointer) for prefix in DOCUMENT_WIDE_PREFIXES)


def _inside_body_schema(remainder: Sequence[str]) -> bool:
    """Whether an in-operation remainder path descends *into* a body schema.

    ``["responses", "200", "content", "application~1json", "schema", "properties", "id"]`` is
    inside a schema; ``[..., "schema"]`` (the schema root itself, e.g. object → array) is not,
    because replacing the whole body affects every caller of the operation.

    Args:
        remainder: Change pointer segments below the operation pointer.

    Returns:
        True when there is at least one segment below a ``schema`` segment.
    """
    for index, segment in enumerate(remainder):
        if segment == "schema":
            return index < len(remainder) - 1
    return False


# -------------------------------------------------------------------------------------------
# Report models
# -------------------------------------------------------------------------------------------


class ConsumerChangeImpact(BaseModel):
    """One classified change, as it lands on one consumer's declared surface.

    Attributes:
        rule_id: The CTG-1.1 rule that fired.
        severity: ``breaking`` / ``non-breaking`` / ``docs-only``.
        pointer: The change's own JSON Pointer.
        change_kind: Raw enumerator kind behind the rule.
        unclassified: True when the classifier fell back to breaking.
        match: ``field``, ``operation``, or ``document`` — how specific the attribution is.
        declared_pointer: The declared pointer the change met, empty for a document-wide match.
        method: Declared operation's method, for an operation or field match.
        path: Declared operation's path template, for an operation or field match.
        operation_id: The declared ``operationId``, when the specification has one.
        field_path: Dotted data path or parameter name, for a field match.
        field_location: ``response`` / ``request`` / ``parameter``, for a field match.
        field_status: Response status the field was declared at, for a response field.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    rule_id: str = Field(serialization_alias="ruleId")
    severity: str
    pointer: str
    change_kind: str = Field(default="", serialization_alias="changeKind")
    unclassified: bool = False
    match: str = Field(description="field | operation | document.")
    declared_pointer: str = Field(default="", serialization_alias="declaredPointer")
    method: Optional[str] = None
    path: Optional[str] = None
    operation_id: Optional[str] = Field(default=None, serialization_alias="operationId")
    field_path: Optional[str] = Field(default=None, serialization_alias="fieldPath")
    field_location: Optional[str] = Field(default=None, serialization_alias="fieldLocation")
    field_status: Optional[str] = Field(default=None, serialization_alias="fieldStatus")


class ConsumerVerdict(BaseModel):
    """What a single change set does to a single registered consumer.

    Attributes:
        consumer_id: Registry id.
        consumer_slug: The stable handle CI jobs and Pact files use.
        consumer_name: Display name.
        owner: Accountable team or person, so a breaking verdict names someone to tell.
        contact: Where to reach them.
        declared: Whether the consumer has a current contract at all.
        verdict: ``breaking`` / ``non-breaking`` / ``docs-only`` / ``unaffected`` / ``undeclared``.
        contract_id: The contract revision the verdict was computed against.
        contract_revision: Its per-consumer revision number.
        contract_version_label: The specification version its pointers were resolved against.
        contract_matches_base: Whether that is the same revision as the diff's base. When false
            the surface was resolved against a different document and a pointer may have moved;
            the verdict is still the best available answer, but it is not silently equated.
        operations_declared: How many operations the contract declares.
        fields_declared: How many fields it declares.
        operations_affected: How many declared operations the change set touches.
        counts: Distinct changes per severity, plus ``unclassified`` and ``total``.
        impacts: The attributed changes, most severe first (bounded, see ``truncated``).
        truncated: True when ``impacts`` was cut at :data:`MAX_IMPACTS_PER_CONSUMER`.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    consumer_id: str = Field(serialization_alias="consumerId")
    consumer_slug: str = Field(serialization_alias="consumerSlug")
    consumer_name: str = Field(serialization_alias="consumerName")
    owner: Optional[str] = None
    contact: Optional[str] = None
    declared: bool = True
    verdict: str
    contract_id: Optional[str] = Field(default=None, serialization_alias="contractId")
    contract_revision: Optional[int] = Field(
        default=None, serialization_alias="contractRevision"
    )
    contract_version_label: Optional[str] = Field(
        default=None, serialization_alias="contractVersionLabel"
    )
    contract_matches_base: Optional[bool] = Field(
        default=None, serialization_alias="contractMatchesBase"
    )
    operations_declared: int = Field(default=0, serialization_alias="operationsDeclared")
    fields_declared: int = Field(default=0, serialization_alias="fieldsDeclared")
    operations_affected: int = Field(default=0, serialization_alias="operationsAffected")
    counts: Dict[str, int] = Field(default_factory=dict)
    impacts: List[ConsumerChangeImpact] = Field(default_factory=list)
    truncated: bool = False


class ChangeAttribution(BaseModel):
    """One classified change and the consumers it touches — every change, in diff order.

    An **empty** ``consumers`` list is the "no registered consumer affected" flag: the change is
    still classified globally, it simply meets nobody's declared surface. That is the difference
    between "safe" and "nobody has told us they use this", and it is exact — unlike a consumer's
    ``impacts`` list, this is never truncated.

    Attributes:
        rule_id: The rule that fired.
        severity: Its global severity.
        pointer: The change's JSON Pointer.
        change_kind: Raw enumerator kind.
        unclassified: True when the classifier fell back to breaking.
        consumers: Handles of the consumers whose declared surface this change touches.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    rule_id: str = Field(serialization_alias="ruleId")
    severity: str
    pointer: str
    change_kind: str = Field(default="", serialization_alias="changeKind")
    unclassified: bool = False
    consumers: List[str] = Field(default_factory=list)


class ConsumerImpactReport(BaseModel):
    """Per-consumer verdicts for one classified diff, plus the headline summary.

    Attributes:
        schema_version: :data:`CONSUMER_IMPACT_SCHEMA_VERSION`.
        summary: One line, e.g. ``breaks 2 of 7 consumers: billing-service, mobile-app``.
        max_severity: Worst severity across every *attributed* change; ``None`` when none.
        counts: Consumer and change tallies (see :func:`analyze_consumer_impact`). Its keys are
            ``snake_case`` and are part of the published schema — they name tallies, not model
            fields, exactly as :attr:`~app.change_taxonomy.ClassifiedDiff.counts` does.
        consumers: Every live consumer, worst verdict first then by handle.
        breaking_consumers: Handles of the consumers this change set breaks, in order.
        attribution: Every classified change with the consumers it touches, in diff order. An
            empty ``consumers`` list flags a change no registered consumer is affected by.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: str = Field(
        default=CONSUMER_IMPACT_SCHEMA_VERSION, serialization_alias="schemaVersion"
    )
    summary: str = ""
    max_severity: Optional[str] = Field(default=None, serialization_alias="maxSeverity")
    counts: Dict[str, int] = Field(default_factory=dict)
    consumers: List[ConsumerVerdict] = Field(default_factory=list)
    breaking_consumers: List[str] = Field(
        default_factory=list, serialization_alias="breakingConsumers"
    )
    attribution: List[ChangeAttribution] = Field(default_factory=list)


# -------------------------------------------------------------------------------------------
# Attribution
# -------------------------------------------------------------------------------------------


def _change_key(change: ClassifiedChange) -> Tuple[str, str, str]:
    """Identity of a change for distinct-change counting."""
    return (change.pointer, change.rule_id, change.change_kind)


def _field_impact(
    change: ClassifiedChange,
    operation: ConsumerContractOperation,
    field: ConsumerContractField,
) -> ConsumerChangeImpact:
    """Build a field-level impact row."""
    declared = field.pointer
    if not pointers_overlap(change.pointer, declared) and field.schema_pointer:
        declared = field.schema_pointer
    return ConsumerChangeImpact(
        rule_id=change.rule_id,
        severity=change.severity,
        pointer=change.pointer,
        change_kind=change.change_kind,
        unclassified=change.unclassified,
        match=MATCH_FIELD,
        declared_pointer=declared,
        method=operation.method,
        path=operation.path,
        operation_id=operation.operation_id,
        field_path=field.path,
        field_location=field.location,
        field_status=field.status,
    )


def _operation_impact(
    change: ClassifiedChange, operation: ConsumerContractOperation
) -> ConsumerChangeImpact:
    """Build an operation-level impact row."""
    return ConsumerChangeImpact(
        rule_id=change.rule_id,
        severity=change.severity,
        pointer=change.pointer,
        change_kind=change.change_kind,
        unclassified=change.unclassified,
        match=MATCH_OPERATION,
        declared_pointer=operation.pointer,
        method=operation.method,
        path=operation.path,
        operation_id=operation.operation_id,
    )


def _document_impact(change: ClassifiedChange) -> ConsumerChangeImpact:
    """Build a document-wide impact row."""
    return ConsumerChangeImpact(
        rule_id=change.rule_id,
        severity=change.severity,
        pointer=change.pointer,
        change_kind=change.change_kind,
        unclassified=change.unclassified,
        match=MATCH_DOCUMENT,
        declared_pointer="",
    )


def _operation_wide_match(
    change_segments: Tuple[str, ...],
    operation: ConsumerContractOperation,
    operation_segments: Tuple[str, ...],
) -> bool:
    """Whether a change with **no** declared-field match still reaches a declared operation.

    Field matches are checked first by the caller and win when there are any: they are the most
    specific statement available, and reporting the operation as well would count one change twice.

    Args:
        change_segments: Segments of the change's pointer.
        operation: The declared operation.
        operation_segments: Segments of that operation's pointer.

    Returns:
        True when the operation as a whole is affected. False means untouched — which, for a
        change inside a body schema whose fields were declared, is the whole point of CTG-4.2.
    """
    if _segments_cover(change_segments, operation_segments):
        # The change is at or above the operation — the operation itself moved.
        return True
    if not _segments_cover(operation_segments, change_segments):
        # Somewhere else entirely (e.g. a component schema this operation never declared).
        return False

    remainder = change_segments[len(operation_segments) :]
    if not operation.fields:
        # Nothing finer than "I call this operation" was declared, so nothing finer is claimed.
        return True
    if remainder and remainder[0] == "parameters":
        # A newly required (or withdrawn) parameter reaches every caller, declared or not.
        return True
    # Security, servers, a response code, the schema root — operation-wide. Anything below a
    # schema is field-granular, and this operation declared no field that meets it.
    return not _inside_body_schema(remainder)


#: How many leading segments a declared pointer is bucketed by. Three is the natural join key:
#: ``/paths/<path>/<method>`` and ``/components/schemas/<name>`` are both three segments, so a
#: change is compared only against declarations on the same operation or the same component.
_BUCKET_DEPTH = 3


@dataclass(frozen=True)
class _DeclaredEntry:
    """One declared pointer, ready to compare.

    Attributes:
        operation_index: Position of the owning operation in the surface.
        segments: The declared pointer, pre-split.
        field: The declared field, or ``None`` for the operation's own pointer.
    """

    operation_index: int
    segments: Tuple[str, ...]
    field: Optional[ConsumerContractField]


class _SurfaceIndex:
    """A contract's declared pointers, bucketed so one change is not compared against all of them.

    A consumer may declare 300 fields on each of dozens of operations, and a diff may carry
    hundreds of changes; comparing every pair would be quadratic on a synchronous request. Two
    pointers can only overlap when their leading segments agree, so bucketing by the first
    :data:`_BUCKET_DEPTH` segments narrows each change to the declarations on its own operation
    or its own component schema, and the result is identical to the exhaustive scan.
    """

    __slots__ = ("operations", "operation_segments", "_buckets", "_shallow", "_all")

    def __init__(self, operations: Sequence[ConsumerContractOperation]) -> None:
        """Index every operation and field pointer of one declared surface.

        Args:
            operations: The contract's declared operations, in stored order.
        """
        self.operations: Tuple[ConsumerContractOperation, ...] = tuple(operations)
        self.operation_segments: Tuple[Tuple[str, ...], ...] = tuple(
            pointer_segments(operation.pointer) for operation in self.operations
        )
        self._buckets: Dict[Tuple[str, ...], List[_DeclaredEntry]] = {}
        self._shallow: List[_DeclaredEntry] = []
        self._all: List[_DeclaredEntry] = []

        for index, operation in enumerate(self.operations):
            self._add(_DeclaredEntry(index, self.operation_segments[index], None))
            for field in operation.fields:
                seen: set[str] = set()
                for pointer in (field.pointer, field.schema_pointer):
                    if not pointer or pointer in seen:
                        continue
                    seen.add(pointer)
                    self._add(_DeclaredEntry(index, pointer_segments(pointer), field))

    def _add(self, entry: _DeclaredEntry) -> None:
        """File one declared pointer under every prefix a change could look it up by.

        An entry is filed either in the buckets or in ``_shallow``, never both, so a lookup that
        reads one bucket plus ``_shallow`` cannot return the same declaration twice.
        """
        self._all.append(entry)
        if len(entry.segments) < _BUCKET_DEPTH:
            # Shorter than the deepest bucket key; a change could look it up at any depth.
            self._shallow.append(entry)
            return
        for depth in range(1, _BUCKET_DEPTH + 1):
            self._buckets.setdefault(entry.segments[:depth], []).append(entry)

    def candidates(self, change_segments: Tuple[str, ...]) -> Sequence[_DeclaredEntry]:
        """Declarations a change *could* overlap; the caller still verifies each.

        Args:
            change_segments: Segments of the change's pointer.

        Returns:
            The entries whose leading segments are compatible. A root-level change (no segments)
            returns everything, because it covers the whole document.
        """
        if not change_segments:
            return self._all
        depth = min(_BUCKET_DEPTH, len(change_segments))
        bucket = self._buckets.get(change_segments[:depth], ())
        if not self._shallow:
            return bucket
        return [*bucket, *self._shallow]


def _verdict_for(severities: Iterable[str], *, declared: bool) -> str:
    """Reduce matched severities to a consumer verdict."""
    if not declared:
        return VERDICT_UNDECLARED
    worst: Optional[str] = None
    for severity in severities:
        if worst is None or _SEVERITY_RANK.get(severity, 2) > _SEVERITY_RANK.get(worst, 2):
            worst = severity
    return worst or VERDICT_UNAFFECTED


def _tally(changes: Sequence[ClassifiedChange]) -> Dict[str, int]:
    """Severity tallies for a set of distinct changes."""
    counts = {
        "breaking": 0,
        "non-breaking": 0,
        "docs-only": 0,
        "unclassified": 0,
        "total": len(changes),
    }
    for change in changes:
        counts[change.severity] = counts.get(change.severity, 0) + 1
        if change.unclassified:
            counts["unclassified"] += 1
    return counts


_VERDICT_ORDER: Dict[str, int] = {
    VERDICT_BREAKING: 0,
    VERDICT_NON_BREAKING: 1,
    VERDICT_DOCS_ONLY: 2,
    VERDICT_UNAFFECTED: 3,
    VERDICT_UNDECLARED: 4,
}


def _impact_sort_key(impact: ConsumerChangeImpact) -> Tuple[int, str, str, str]:
    """Order impacts worst-first, then stably by operation, pointer and rule."""
    rank = -_SEVERITY_RANK.get(impact.severity, 2)
    return (rank, f"{impact.path or ''} {impact.method or ''}", impact.pointer, impact.rule_id)


def _summarize(
    *,
    breaking_slugs: Sequence[str],
    consumers_declared: int,
    consumers_undeclared: int,
) -> str:
    """Build the headline sentence.

    The denominator is consumers that have **declared** a surface, never the registry total: a
    consumer that has declared nothing cannot be counted as safe, and hiding it inside "breaks 2
    of 7" would read as reassurance about a service nobody has heard from. It is reported
    alongside instead.

    Args:
        breaking_slugs: Handles of the consumers the change set breaks.
        consumers_declared: How many consumers have a current contract.
        consumers_undeclared: How many are registered without one.

    Returns:
        One line of text, e.g. ``breaks 2 of 5 consumers: billing-service, mobile-app``.
    """
    if consumers_declared == 0:
        base = "no consumer has declared a surface for this project"
    else:
        noun = "consumer" if consumers_declared == 1 else "consumers"
        base = f"breaks {len(breaking_slugs)} of {consumers_declared} {noun}"
        if breaking_slugs:
            base += ": " + ", ".join(breaking_slugs)
    if consumers_undeclared:
        noun = "consumer has" if consumers_undeclared == 1 else "consumers have"
        base += f" ({consumers_undeclared} registered {noun} declared no surface)"
    return base


def analyze_consumer_impact(
    diff: ClassifiedDiff,
    summaries: Sequence[ConsumerSummary],
    *,
    base_version_id: Optional[str] = None,
    max_impacts_per_consumer: int = MAX_IMPACTS_PER_CONSUMER,
) -> ConsumerImpactReport:
    """Intersect a classified diff with every registered consumer's declared surface.

    Args:
        diff: The CTG-1.1 classification of the base→head pair.
        summaries: Every live consumer in the project with its current contract, as returned by
            :func:`~app.consumer_contract_store.list_consumer_summaries`. A consumer without a
            contract is kept and reported ``undeclared`` rather than dropped.
        base_version_id: Revision id of the diff's base side, when known. Used only to tell a
            consumer whether its surface was resolved against that same revision.
        max_impacts_per_consumer: Cap on enumerated impacts per consumer. Counts and
            ``attribution`` stay exact; only the per-consumer enumeration is bounded.

    Returns:
        A :class:`ConsumerImpactReport`. ``counts`` carries ``consumers_total``,
        ``consumers_declared``, ``consumers_undeclared``, ``consumers_affected``,
        ``consumers_breaking``, ``changes_total``, ``changes_attributed`` and
        ``changes_unattributed``.
    """
    changes = list(diff.changes)
    # Split each change pointer once, not once per consumer per declared pointer.
    change_segments = [pointer_segments(change.pointer) for change in changes]
    document_wide = [_is_document_wide(change.pointer) for change in changes]
    #: change identity -> handles of the consumers it touches; exact, never truncated.
    attributed: Dict[Tuple[str, str, str], List[str]] = {}
    verdicts: List[ConsumerVerdict] = []

    for summary in summaries:
        consumer = summary.consumer
        contract = summary.contract
        surface = contract.surface if contract else None
        operations = list(surface.operations) if surface else []
        declared = contract is not None

        impacts: List[ConsumerChangeImpact] = []
        matched: Dict[Tuple[str, str, str], ClassifiedChange] = {}
        touched_operations: set[str] = set()

        if declared:
            index = _SurfaceIndex(operations)
            for position, change in enumerate(changes):
                if document_wide[position]:
                    impacts.append(_document_impact(change))
                    matched[_change_key(change)] = change
                    continue

                segments = change_segments[position]
                fields_by_operation: Dict[int, List[ConsumerContractField]] = {}
                operation_hits: List[int] = []
                seen_fields: set[int] = set()

                for entry in index.candidates(segments):
                    if entry.field is None:
                        if entry.operation_index not in operation_hits:
                            operation_hits.append(entry.operation_index)
                        continue
                    if id(entry.field) in seen_fields:
                        continue
                    if not _segments_overlap(segments, entry.segments):
                        continue
                    seen_fields.add(id(entry.field))
                    fields_by_operation.setdefault(entry.operation_index, []).append(entry.field)

                found: List[ConsumerChangeImpact] = []
                for operation_index, fields in fields_by_operation.items():
                    operation = operations[operation_index]
                    found.extend(_field_impact(change, operation, field) for field in fields)
                    touched_operations.add(operation.pointer)
                for operation_index in operation_hits:
                    if operation_index in fields_by_operation:
                        # A field match is the more specific statement; do not count it twice.
                        continue
                    operation = operations[operation_index]
                    if not _operation_wide_match(
                        segments, operation, index.operation_segments[operation_index]
                    ):
                        continue
                    found.append(_operation_impact(change, operation))
                    touched_operations.add(operation.pointer)

                if found:
                    impacts.extend(found)
                    matched[_change_key(change)] = change

        for key in matched:
            attributed.setdefault(key, []).append(consumer.slug)
        matched_changes = list(matched.values())
        verdict = _verdict_for((c.severity for c in matched_changes), declared=declared)
        impacts.sort(key=_impact_sort_key)
        truncated = len(impacts) > max_impacts_per_consumer

        verdicts.append(
            ConsumerVerdict(
                consumer_id=consumer.id,
                consumer_slug=consumer.slug,
                consumer_name=consumer.name,
                owner=consumer.owner,
                contact=consumer.contact,
                declared=declared,
                verdict=verdict,
                contract_id=contract.id if contract else None,
                contract_revision=contract.revision if contract else None,
                contract_version_label=contract.version_label if contract else None,
                contract_matches_base=(
                    None
                    if not contract or not base_version_id
                    else str(contract.version_id or "") == str(base_version_id)
                ),
                operations_declared=len(operations),
                fields_declared=sum(len(op.fields) for op in operations),
                operations_affected=len(touched_operations),
                counts=_tally(matched_changes),
                impacts=impacts[:max_impacts_per_consumer],
                truncated=truncated,
            )
        )

    verdicts.sort(key=lambda v: (_VERDICT_ORDER.get(v.verdict, 5), v.consumer_slug))

    breaking_slugs = [v.consumer_slug for v in verdicts if v.verdict == VERDICT_BREAKING]
    consumers_declared = sum(1 for v in verdicts if v.declared)
    consumers_undeclared = len(verdicts) - consumers_declared

    attribution = [
        ChangeAttribution(
            rule_id=change.rule_id,
            severity=change.severity,
            pointer=change.pointer,
            change_kind=change.change_kind,
            unclassified=change.unclassified,
            consumers=sorted(attributed.get(_change_key(change), [])),
        )
        for change in changes
    ]
    unattributed_count = sum(1 for entry in attribution if not entry.consumers)

    max_severity: Optional[str] = None
    for entry in attribution:
        if not entry.consumers:
            continue
        if max_severity is None or _SEVERITY_RANK.get(entry.severity, 2) > _SEVERITY_RANK.get(
            max_severity, 2
        ):
            max_severity = entry.severity

    return ConsumerImpactReport(
        summary=_summarize(
            breaking_slugs=breaking_slugs,
            consumers_declared=consumers_declared,
            consumers_undeclared=consumers_undeclared,
        ),
        max_severity=max_severity,
        counts={
            "consumers_total": len(verdicts),
            "consumers_declared": consumers_declared,
            "consumers_undeclared": consumers_undeclared,
            "consumers_affected": sum(
                1 for v in verdicts if v.declared and v.counts.get("total", 0) > 0
            ),
            "consumers_breaking": len(breaking_slugs),
            "changes_total": len(changes),
            "changes_attributed": len(changes) - unattributed_count,
            "changes_unattributed": unattributed_count,
        },
        consumers=verdicts,
        breaking_consumers=breaking_slugs,
        attribution=attribution,
    )


# -------------------------------------------------------------------------------------------
# Rendering
# -------------------------------------------------------------------------------------------

_VERDICT_LABEL: Dict[str, str] = {
    VERDICT_BREAKING: "breaking",
    VERDICT_NON_BREAKING: "non-breaking",
    VERDICT_DOCS_ONLY: "docs-only",
    VERDICT_UNAFFECTED: "unaffected",
    VERDICT_UNDECLARED: "no declared surface",
}


def _impact_target(impact: ConsumerChangeImpact) -> str:
    """Human phrase for what a single impact touches."""
    if impact.match == MATCH_DOCUMENT:
        return "document-wide"
    operation = f"{(impact.method or '').upper()} {impact.path or ''}".strip()
    if impact.match == MATCH_OPERATION or not impact.field_path:
        return operation
    where = impact.field_location or "field"
    if impact.field_status:
        where = f"{impact.field_status} {where}"
    return f"{operation} — {where} `{impact.field_path}`"


def render_consumer_impact_markdown(report: ConsumerImpactReport) -> str:
    """Render a consumer impact report as stable markdown.

    Appended to the CTG-1.3 changelog when a classified diff is asked for consumer analysis, so
    the document a reviewer reads answers "who does this break" without a second request.

    Args:
        report: The analysis result.

    Returns:
        Markdown text; a short "no consumers registered" document when the registry is empty.
    """
    lines: List[str] = ["## Consumer impact", ""]
    if not report.consumers:
        lines.append("No consumers are registered for this project.")
        lines.append("")
        return "\n".join(lines)

    lines.append(f"_{report.summary}._")
    lines.append("")

    for verdict in report.consumers:
        label = _VERDICT_LABEL.get(verdict.verdict, verdict.verdict)
        heading = f"### `{verdict.consumer_slug}` — {label}"
        lines.append(heading)
        lines.append("")
        if verdict.owner:
            lines.append(f"Owner: {verdict.owner}")
            lines.append("")
        if not verdict.declared:
            lines.append(
                "This consumer is registered but has declared no surface, so no verdict can be "
                "given for it."
            )
            lines.append("")
            continue
        if verdict.contract_matches_base is False:
            lines.append(
                "_Surface resolved against "
                f"`{verdict.contract_version_label or 'another revision'}`, not the base of this "
                "diff._"
            )
            lines.append("")
        if not verdict.impacts:
            lines.append("No declared operation or field is touched.")
            lines.append("")
            continue
        for impact in verdict.impacts:
            lines.append(
                f"- **[{impact.severity}]** {_impact_target(impact)} "
                f"(`{impact.rule_id}`) — `{impact.pointer}`"
            )
        if verdict.truncated:
            lines.append(
                f"- _…{verdict.counts.get('total', 0)} change(s) in total; list truncated._"
            )
        lines.append("")

    unattributed_count = report.counts.get("changes_unattributed", 0)
    if unattributed_count:
        lines.append(
            f"_{unattributed_count} change(s) affect no registered consumer._"
        )
        lines.append("")
    return "\n".join(lines)
