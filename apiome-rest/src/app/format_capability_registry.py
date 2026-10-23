"""Source-format capability & parsing-limit registry — CPDO-2.4 (#4796).

CPDO-1.1 gave a payload analysis a *status* and a closed *reason code*, and CPDO-1.2 gave
each stored record the analyzer's own :class:`~app.payload_analysis.AnalyzerCapabilities`.
Both are **per record**: they describe one revision that was actually analysed. Neither can
answer the question a reader asks *before* — or *instead of* — reading a record: "what can
apiome ever tell me about this format, and what will it never tell me?"

Without that, one sentence has to cover five unrelated situations: the format has no native
analyzer, the source bytes were never captured, the parser hit a grammar it does not read,
a value-visibility policy withheld the value, and the construct genuinely is not in the
source. Collapsed into "no details", they are indistinguishable — and the fourth and fifth
readings are the only ones that say anything about the *source*. Reporting the first three
as though the source were missing is a lie about the customer's data.

This module is the versioned registry that separates them.

**Per format** it publishes a :class:`FormatCapability`: the native hierarchy its analyzer
models, the quality of the source locations it can point at, the value visibility it can
ever carry, the grammar it knowingly does not read, how much of what it observes survives
the projection onto the canonical model, and whether the format participates in the
conversion graph at all — each stamped with the analyzer key, analyzer version and
underlying tool versions that back the claim, so an entry is evidence rather than assertion.

**Every registered catalog format resolves to an entry.** A format with a reviewed seed gets
it (``provenance = reviewed``); every other registered adapter gets one *derived* from the
adapter itself (``provenance = derived``) — its declared capabilities, its analyzer identity,
its normalizers — with pessimistic defaults wherever the adapter does not say. A key no
adapter is registered under still resolves, to an entry that claims nothing at all
(``provenance = unknown_format``), because a catalog item whose adapter was later retired
must still render an honest explanation instead of a dead end.

**Absence has a closed vocabulary.** :class:`AbsenceCategory` names the eight ways a detail
can be missing, each with one reviewed :class:`AbsenceExplanation`. Exactly one of them —
:attr:`AbsenceCategory.SOURCE_MISSING` — sets ``source_missing``, and it is reachable only
from the ``no_source_captured`` analysis reason. Every other route (an unsupported format, a
bounds/grammar parse limit, an analyzer failure, an unmodelled construct, a registry with no
statement to make) resolves to an explanation whose ``source_missing`` is ``False``. That
invariant is the machine-checkable form of the ticket's "the UI never reports unparsed data
as source-missing": :func:`explain_analysis_absence` and :func:`explain_construct` are the
only two ways to phrase an absence, and neither can produce a source-missing claim from a
parser limitation.

**Version coverage is declared, not inferred.** FMT-3.8 hangs a
:class:`~app.format_version_coverage.VersionCoverage` on every entry: which versions of the format
are read, which are written, which one an export produces by default, and a note wherever a version
is reached through a projection or a downgrade rather than head-on. The declaration lives in
:mod:`app.format_version_coverage` and is checked against fixtures — every declared read version
must have a corpus entry that detects at its key, every declared write version a round-trip matrix
row — so a version cannot be claimed here without evidence that it works.

The whole registry is exposed as a deterministic, versioned
:class:`FormatCapabilitySnapshot` for the REST contract and the UI, mirroring its sibling
:mod:`app.capability_registry` (EFP-1.2), which does the same job for export *destinations*.
The language-neutral half of the vocabulary is committed at
``scripts/format_capabilities/vocabulary.json``; contract tests on both sides assert that the
Python registry and its TypeScript mirror still match it, so a registry change that lands in
one language and not the other turns a suite red.
"""

from __future__ import annotations

import logging
import re
from enum import Enum
from typing import TYPE_CHECKING, Dict, Iterable, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

from .edi_dialect_profiles import EANCOM, ODETTE, TRADACOMS, profile_statement
from .edifact_analysis import EDIFACT_IMPLEMENTATION_GUIDE_STATEMENT
from .format_version_coverage import (
    UNDECLARED_VERSION_COVERAGE,
    FormatVersion,
    VersionCoverage,
    VersionSupport,
    version_coverage_for,
)
from .payload_analysis import (
    ANALYSIS_REASONS,
    PAYLOAD_ANALYSIS_SCHEMA_VERSION,
    REASON_ANALYZER_FAILED,
    REASON_BOUNDS_EXCEEDED,
    REASON_NO_SOURCE_CAPTURED,
    REASON_NOT_ANALYZED,
    REASON_UNSUPPORTED_FORMAT,
    STATUS_AVAILABLE,
    AnalyzerCapabilities,
    ValueVisibility,
)
from .payload_analyzer import GENERIC_ANALYZER_KEY
from .hl7v3_datatypes import TEMPLATE_CLAIM_STATEMENT
from .swift_mt_fields import MX_CORRESPONDENCE_DISCLAIMER
from .nacha_analysis import NACHA_OPERATING_RULES_STATEMENT
from .ncpdp_analysis import NCPDP_IMPLEMENTATION_GUIDE_STATEMENT
from .dicom_dictionary import PIXEL_DATA_BOUNDARY_STATEMENT
from .dicom_normalizer import DICOM_VALUE_STATEMENT
from .tradacoms_analysis import TRADACOMS_IMPLEMENTATION_GUIDE_STATEMENT
from .consul_parser import CONSUL_DECLARED_CONSTRUCTS
from .haproxy_parser import HAPROXY_DECLARED_CONSTRUCTS
from .nginx_parser import NGINX_CARRIED_DIRECTIVES, NGINX_DECLARED_DIRECTIVES, NGINX_READ_DIRECTIVES
from .traefik_parser import TRAEFIK_DECLARED_CONSTRUCTS
from .tyk_parser import TYK_DECLARED_CONSTRUCTS

if TYPE_CHECKING:  # pragma: no cover - typing only
    # Imported lazily at every call site: :mod:`app.import_source` imports the analysis
    # machinery this module also uses, and a module-level import here would make the registry
    # part of the adapter-loading cycle.
    from .import_source import ImportSource

logger = logging.getLogger(__name__)

__all__ = [
    "FORMAT_KEY_PATTERN",
    "IMPLEMENTATION_GUIDE_FAMILY",
    "REGISTRY_VERSION",
    "REVIEW_DATE",
    "AbsenceCategory",
    "AbsenceExplanation",
    "AnalyzerEvidence",
    "CanonicalProjectionSupport",
    "CapabilityProvenance",
    "ConstructAvailability",
    "ConstructExplanation",
    "ConversionSupport",
    "ConversionSupportEntry",
    "FormatAvailability",
    "FormatCapability",
    "FormatCapabilitySnapshot",
    "FormatVersion",
    "ImplementationGuideStatement",
    "NativeHierarchy",
    "ProjectionCoverage",
    "REASON_ABSENCE_CATEGORIES",
    "SourceLocationQuality",
    "SourceLocationSupport",
    "ValueVisibilitySupport",
    "VersionCoverage",
    "VersionSupport",
    "absence_explanation",
    "absence_explanations",
    "capability_for",
    "explain_analysis_absence",
    "explain_construct",
    "format_capabilities",
    "implementation_guide",
    "is_valid_format_key",
    "registry_snapshot",
    "render_absence",
    "version_coverage_for",
]


# ===========================================================================
# Vocabulary
# ===========================================================================

#: The registry contract version. Bumped whenever an entry, a reviewed seed, an absence
#: explanation, or a vocabulary member changes, so a consumer can detect a stale contract and
#: a cached snapshot can be keyed by it. Mirrored in the committed vocabulary snapshot.
REGISTRY_VERSION = "32"

#: The date the current seeds and absence explanations were last reviewed. Recorded as
#: provenance on every entry, so a claim about a format carries the date somebody checked it.
REVIEW_DATE = "2026-10-22"

#: Accepted shape of a format key. The registry resolves an *arbitrary caller-supplied* string
#: (a stored ``source_format`` whose adapter may have been retired), so the key is constrained
#: before it is echoed back in an entry: lowercase alphanumerics plus ``.``/``_``/``-``, at most
#: 64 characters. Anything else is not a format key that could ever have been registered.
FORMAT_KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


class CapabilityProvenance(str, Enum):
    """Where a :class:`FormatCapability` entry's claims come from (CPDO-2.4).

    The single field that tells a reader how much weight an entry carries. It is not a quality
    grade — a ``derived`` entry is as *true* as a reviewed one, because everything in it was
    read off the adapter — but a reviewed entry additionally states boundaries nobody could
    derive, and an ``unknown_format`` entry deliberately states nothing.
    """

    #: A hand-reviewed seed: boundaries and projection coverage were checked against the
    #: format's parser and normalizer by a person on :data:`REVIEW_DATE`.
    REVIEWED = "reviewed"
    #: Derived from the registered adapter — its analyzer identity, its declared capabilities,
    #: its normalizers — with pessimistic defaults wherever the adapter does not say. This is
    #: the safe fallback every registered format is guaranteed.
    DERIVED = "derived"
    #: No adapter is registered under this key. The entry asserts nothing about the format; it
    #: exists so a catalog item naming a retired adapter still renders an honest explanation.
    UNKNOWN_FORMAT = "unknown_format"


class FormatAvailability(str, Enum):
    """Whether this format can actually be imported and analysed in the current runtime."""

    #: Registered, runnable, and persisted to the catalog.
    AVAILABLE = "available"
    #: Registered, but a hard-required toolchain is missing here (MFI-5.2), so nothing this
    #: entry describes can currently be produced.
    TOOL_UNAVAILABLE = "tool_unavailable"
    #: Registered, but the adapter never persists (the internal acceptance adapter), so no
    #: analysis is ever stored for it.
    PREVIEW_ONLY = "preview_only"
    #: No adapter is registered under this key at all.
    UNREGISTERED = "unregistered"


class NativeHierarchy(str, Enum):
    """How much of the format's own structure the analysis tree preserves."""

    #: A format-specific node vocabulary — X12 envelopes and segments, copybook levels.
    NATIVE = "native"
    #: The format-blind object/array/scalar walk. Nesting and ordering survive; format
    #: semantics do not, and their absence from the tree says nothing about the source.
    GENERIC = "generic"
    #: No analysis tree is ever produced for this format.
    NONE = "none"


class SourceLocationQuality(str, Enum):
    """The best source pointer a node from this format can carry.

    Determines what "jump to source" can do, and — more importantly — how precisely a UI may
    claim to know *where* something is. A path-only analyzer must never render a line number.
    """

    #: Byte offsets into the raw source (an exact range).
    BYTE_OFFSETS = "byte_offsets"
    #: 1-based source line numbers.
    LINE_NUMBERS = "line_numbers"
    #: A structural path and/or sibling ordinal only — no position in the raw bytes.
    PATH_ONLY = "path_only"
    #: No source pointer at all.
    NONE = "none"


class ProjectionCoverage(str, Enum):
    """How much of what the analyzer observes survives onto the canonical model.

    The analysis tree and the catalog's entity/field rows are two different views of one
    import. A construct present in the first and absent from the second was *dropped by
    normalization*, which is neither a parse limit nor a missing source.
    """

    #: Everything the analyzer models has a canonical representation.
    FULL = "full"
    #: Some observed constructs have no canonical representation; ``dropped_constructs`` names
    #: the reviewed ones.
    PARTIAL = "partial"
    #: Nothing is projected — no normalizer participates for this format.
    NONE = "none"
    #: Not reviewed. The safe default: it makes no claim in either direction.
    UNKNOWN = "unknown"


class ConversionSupport(str, Enum):
    """Whether this format participates in the canonical conversion graph."""

    #: At least one declared format key resolves to a registered normalizer, so an import can
    #: reach the canonical model and, from there, every export destination.
    SUPPORTED = "supported"
    #: The adapter is registered but its required toolchain is missing in this runtime.
    TOOL_UNAVAILABLE = "tool_unavailable"
    #: No conversion path exists — no registered normalizer, or the adapter never persists.
    UNSUPPORTED = "unsupported"


class AbsenceCategory(str, Enum):
    """The closed vocabulary of *why* a detail is not there (CPDO-2.4).

    Eight causes that "no details" used to conflate. Exactly one of them is a statement about
    the customer's source material being absent; the rest are statements about apiome, about a
    policy, or about the source's *content*. :data:`_ABSENCE_EXPLANATIONS` is the single place
    that decides which, and only :attr:`SOURCE_MISSING` sets ``source_missing``.
    """

    #: No source material was captured for the revision. The only category that is genuinely a
    #: missing source.
    SOURCE_MISSING = "source_missing"
    #: The revision predates payload analysis, or no analyzer has run for it yet.
    NOT_ANALYZED = "not_analyzed"
    #: The format has no analyzer. A capability boundary, not a defect in the source.
    FORMAT_UNSUPPORTED = "format_unsupported"
    #: The analyzer read the source but could not describe this part of it — a node/depth
    #: budget, or a grammar it knowingly does not read. The data is in the source; apiome has
    #: no description of it.
    PARSE_LIMIT = "parse_limit"
    #: The analyzer raised. The failure is recorded rather than hidden.
    ANALYZER_FAILED = "analyzer_failed"
    #: A value-visibility policy withheld the value. The structure is known; the content is
    #: deliberately not stored.
    VALUE_REDACTED = "value_redacted"
    #: The analyzer models this construct and did not observe it — so it is genuinely not in
    #: the source. The one category that is a positive statement about source content.
    ABSENT_IN_SOURCE = "absent_in_source"
    #: The registry makes no statement about this construct for this format. Its absence is
    #: evidence of nothing.
    UNDECLARED = "undeclared"


class ConstructAvailability(str, Enum):
    """What the registry can say about one named construct in one format."""

    #: The format's analyzer models this construct.
    MODELLED = "modelled"
    #: The format's analyzer declares it does **not** model this construct.
    UNMODELLED = "unmodelled"
    #: Neither list names it; the registry has no statement to make.
    UNDECLARED = "undeclared"


#: Analysis reason code → absence category. The bridge between CPDO-1.1's stored reason codes
#: and this registry's explanation vocabulary. Total over :data:`ANALYSIS_REASONS`, asserted by
#: contract test, so a reason code added there without a category here cannot ship.
REASON_ABSENCE_CATEGORIES: Dict[str, AbsenceCategory] = {
    REASON_NOT_ANALYZED: AbsenceCategory.NOT_ANALYZED,
    REASON_NO_SOURCE_CAPTURED: AbsenceCategory.SOURCE_MISSING,
    REASON_UNSUPPORTED_FORMAT: AbsenceCategory.FORMAT_UNSUPPORTED,
    REASON_BOUNDS_EXCEEDED: AbsenceCategory.PARSE_LIMIT,
    REASON_ANALYZER_FAILED: AbsenceCategory.ANALYZER_FAILED,
}


# ===========================================================================
# Value types
# ===========================================================================


class AnalyzerEvidence(BaseModel):
    """Which analyzer backs this entry's claims, and what it was built on.

    The "tool/version evidence" the ticket asks for. A capability claim without it is an
    opinion: "X12 composites are modelled" is only checkable if the reader knows *which*
    extractor at *which* version, over *which* parser release, is being described.

    Deliberately a snake_case sibling of :class:`~app.payload_analysis.AnalyzerInfo` rather
    than a reuse of it: that model serializes under camelCase aliases for the payload-analysis
    surface, and this registry's contract — like :mod:`app.capability_registry`'s — is
    snake_case end to end. One casing per contract beats one model across two.

    Attributes:
        key: Analyzer key (the adapter key, or ``generic`` for the format-blind walk).
        version: That analyzer's version.
        tool_versions: Underlying parser/library versions it leans on; empty when it uses none.
    """

    model_config = ConfigDict(extra="forbid")

    key: str = Field(description="Analyzer key (the adapter key, or ``generic``).")
    version: str = Field(description="The analyzer implementation version this entry describes.")
    tool_versions: Dict[str, str] = Field(
        default_factory=dict,
        description="Underlying parser/library versions the analyzer leans on.",
    )


class SourceLocationSupport(BaseModel):
    """The best source pointer this format's analyzer can attach to a node."""

    model_config = ConfigDict(extra="forbid")

    quality: SourceLocationQuality = Field(
        description="The strongest pointer kind nodes from this format can carry."
    )
    note: str = Field(
        description="One line on what that means for navigation — what a reader can and "
        "cannot be shown."
    )


class ValueVisibilitySupport(BaseModel):
    """The value material this format's analysis can ever carry.

    Two different limits, and conflating them is how a UI ends up implying a value was hidden
    when the analyzer never had one. :attr:`default` is the policy applied when nobody chose;
    :attr:`maximum` is the ceiling the *analyzer* imposes — a COBOL copybook is a layout, not
    data, so its analysis has no observed values to withhold at any policy level.
    """

    model_config = ConfigDict(extra="forbid")

    default: str = Field(
        description="The value-visibility level applied when no explicit policy is chosen."
    )
    maximum: str = Field(
        description="The highest level this format's analyzer can ever supply, regardless of "
        "policy — ``none`` when the analyzer observes no values at all."
    )
    note: str = Field(description="One line on why the ceiling is where it is.")


class CanonicalProjectionSupport(BaseModel):
    """How much of the native analysis survives onto the canonical model."""

    model_config = ConfigDict(extra="forbid")

    coverage: ProjectionCoverage = Field(
        description="Whether every observed construct, some, or none reach the canonical model."
    )
    dropped_constructs: List[str] = Field(
        default_factory=list,
        description="Reviewed construct keys the canonical model has no representation for. "
        "Empty on a derived entry, which makes no claim.",
    )
    note: str = Field(
        description="One line on what the canonical model keeps and what only the analysis holds."
    )


class ImplementationGuideStatement(BaseModel):
    """What a format's reader validates against, and the guides it does not consult (FMT-6.10).

    Every EDI and vertical-messaging format reads a **syntax** — segments, records, elements — and
    nothing above it: no implementation guide, operating rule, template or companion guide. A green
    import therefore means *structurally readable*, never *conformant*, and this statement says so
    in one vocabulary for the whole family (:data:`IMPLEMENTATION_GUIDE_FAMILY`). The Format
    details tab renders :attr:`statement` as a banner on every record of these formats.

    Attributes:
        consulted: Always ``False``: apiome consults no implementation guide for any format.
        standard_read: The syntax that *is* read and checked.
        guides_not_consulted: The guides, rules and specifications that are not applied, by name.
        claims_recorded: Conformance or version claims the document makes about itself, recorded
            as the sender's claim and never checked.
        statement: The reviewed sentence rendered to the reader.
    """

    model_config = ConfigDict(extra="forbid")

    consulted: bool = Field(
        default=False,
        description="Whether any implementation guide is consulted. Always false.",
    )
    standard_read: str = Field(description="The syntax that is read and checked.")
    guides_not_consulted: List[str] = Field(
        description="The implementation guides, operating rules and specifications not applied."
    )
    claims_recorded: List[str] = Field(
        default_factory=list,
        description="Claims the document makes about itself, recorded as the sender's claim.",
    )
    statement: str = Field(description="The reviewed sentence the Format details tab renders.")


def _join(items: List[str], conjunction: str = "and") -> str:
    """``a``, ``a and b``, ``a, b and c`` (or ``or`` in place of ``and``)."""
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + f" {conjunction} " + items[-1]


def implementation_guide(
    standard: str, guides: List[str], claims: Optional[List[str]] = None
) -> ImplementationGuideStatement:
    """Build a format's implementation-guide statement in the family's shared vocabulary.

    Args:
        standard: The syntax that is read (``UN/EDIFACT syntax (ISO 9735)``).
        guides: The guides not consulted, by name (at least one).
        claims: Claims the document makes about itself that are recorded, not checked.

    Returns:
        The :class:`ImplementationGuideStatement`, its sentence rendered.

    Raises:
        ValueError: When no guide is named — a statement that names nothing says nothing.
    """
    if not guides:
        raise ValueError("an implementation-guide statement must name the guides not consulted")
    claims = list(claims or [])
    statement = (
        f"Only the {standard} is read. No implementation guide is consulted — not "
        f"{_join(guides, 'or')} — so a document that imports is structurally readable, not claimed to "
        "be conformant."
    )
    if claims:
        verb = "is" if len(claims) == 1 else "are"
        recorded = _join(claims)
        statement += f" {recorded[0].upper()}{recorded[1:]} {verb} recorded as the sender's claim, not checked."
    return ImplementationGuideStatement(
        standard_read=standard,
        guides_not_consulted=list(guides),
        claims_recorded=claims,
        statement=statement,
    )


class ConversionSupportEntry(BaseModel):
    """Whether this format participates in the conversion graph, and by which route.

    The route matters less than the *fact*: an adapter that persists a catalog item has, by
    contract, produced a canonical model for it, so it can reach every export destination. What
    varies is how — through a normalizer registered under one of the adapter's declared format
    keys, or inside the adapter itself — and whether it can run here at all.
    """

    model_config = ConfigDict(extra="forbid")

    support: ConversionSupport = Field(description="Whether a conversion path exists at all.")
    canonical_formats: List[str] = Field(
        default_factory=list,
        description="Declared format keys that resolve to a registered normalizer — the routes "
        "onto the canonical model, sorted. Empty when the adapter normalizes in-adapter.",
    )
    normalizes_in_adapter: bool = Field(
        default=False,
        description="True when no registered normalizer claims any declared key and the adapter "
        "builds the canonical model itself. Not a gap — a different route.",
    )
    declared_formats: List[str] = Field(
        default_factory=list,
        description="Every format key the adapter declares, sorted. A mix of normalizer keys and "
        "detection aliases, so a key here without a normalizer is not by itself a missing route.",
    )
    note: str = Field(description="One line on the conversion route or its absence.")


class FormatCapability(BaseModel):
    """The versioned capability & parsing-limit entry for one source format (CPDO-2.4).

    Everything a reader needs to know what apiome will *ever* be able to say about a document
    of this format, before opening one: the native hierarchy it preserves, the source pointers
    it can offer, the values it can carry, the grammar it does not read, what survives
    normalization, and whether it converts — each backed by the analyzer and tool versions in
    :attr:`analyzer`.
    """

    model_config = ConfigDict(extra="forbid")

    format: str = Field(description="Stable import-source registry key (e.g. ``edix12``).")
    label: str = Field(description="Human label for the format.")
    paradigm: Optional[str] = Field(
        default=None,
        description="The canonical paradigm the adapter produces, or null for an unknown format.",
    )
    provenance: CapabilityProvenance = Field(
        description="Whether this entry is reviewed, derived from the adapter, or a declaration "
        "that the format is unknown."
    )
    availability: FormatAvailability = Field(
        description="Whether this format can be imported and analysed in the current runtime."
    )
    unavailable_reason: Optional[str] = Field(
        default=None,
        description="Why the format is unavailable here, or null when it is available.",
    )
    native_hierarchy: NativeHierarchy = Field(
        description="How much of the format's own structure the analysis tree preserves."
    )
    native_hierarchy_note: str = Field(
        description="One line on what the tree's node vocabulary actually is."
    )
    analyzer: AnalyzerEvidence = Field(
        description="The analyzer and tool versions backing every claim in this entry."
    )
    source_location: SourceLocationSupport = Field(
        description="The best source pointer nodes from this format can carry."
    )
    value_visibility: ValueVisibilitySupport = Field(
        description="The value material this format's analysis can ever carry."
    )
    supported_constructs: List[str] = Field(
        default_factory=list,
        description="Construct keys the analyzer models, sorted. Their absence from a tree means "
        "they were not in the source.",
    )
    unsupported_constructs: List[str] = Field(
        default_factory=list,
        description="Construct keys the analyzer knowingly does not model, sorted — the format's "
        "unsupported grammar. Their absence from a tree means nothing about the source.",
    )
    limits: Dict[str, int] = Field(
        default_factory=dict,
        description="The numeric parsing limits in force (node/depth budgets, value preview "
        "length), so a bounded record is distinguishable from a small one.",
    )
    canonical_projection: CanonicalProjectionSupport = Field(
        description="How much of the native analysis survives onto the canonical model."
    )
    conversion: ConversionSupportEntry = Field(
        description="Whether this format participates in the conversion graph, and by which route."
    )
    version_coverage: VersionCoverage = Field(
        description="Which versions of this format are read and written, which one an export "
        "produces by default, and where a version is reached through a projection or a downgrade "
        "(FMT-3.8). A claim about *versions*: how completely the format's constructs are modelled "
        "is what ``unsupported_constructs`` and ``canonical_projection`` above answer.",
    )
    implementation_guide: Optional[ImplementationGuideStatement] = Field(
        default=None,
        description="For an EDI or vertical-messaging format (FMT-6.10): the syntax read and the "
        "implementation guides not consulted. Null for every other format.",
    )
    notes: List[str] = Field(
        default_factory=list,
        description="Reviewed prose about this format's boundaries, in reading order.",
    )
    registry_version: str = Field(description="The registry contract version this entry belongs to.")
    review_date: str = Field(description="When this entry's claims were last reviewed.")


class AbsenceExplanation(BaseModel):
    """The reviewed wording for one :class:`AbsenceCategory` (CPDO-2.4).

    One per category, so the eight causes are worded and rendered *separately*.
    :attr:`summary_template` may contain a single ``{construct}`` slot, substituted only with
    an apiome-controlled construct key.

    :attr:`source_missing` is the load-bearing field: it is ``True`` for exactly one category,
    and it is what a UI must consult before saying anything about the customer's source being
    absent. A parse limit, an unsupported format and an analyzer failure all leave it ``False``.
    """

    model_config = ConfigDict(extra="forbid")

    category: AbsenceCategory = Field(description="The cause category this explanation is for.")
    category_label: str = Field(description="Short human label (e.g. 'Parser limit').")
    summary_template: str = Field(
        description="Reviewed one-line explanation, optionally with a single ``{construct}`` slot."
    )
    remediation: str = Field(description="Short, safe guidance for this category.")
    source_missing: bool = Field(
        description="True only when the source material itself was never captured. Never true "
        "for a parser, capability, policy or content cause."
    )


class ConstructExplanation(BaseModel):
    """Why one named construct is not in one format's analysis (CPDO-2.4).

    The resolved answer for "the tree has no ``x12.hl_hierarchy`` node — what does that mean?".
    :attr:`source_missing` is always ``False``: a construct's absence from an analysis is never
    evidence that the source was not captured, whichever way the registry resolves it.
    """

    model_config = ConfigDict(extra="forbid")

    format: str = Field(description="The format key the question was asked about.")
    # Named ``construct_key`` rather than ``construct``: pydantic's ``BaseModel`` already carries
    # a deprecated ``construct`` classmethod, and shadowing it emits a warning on every import.
    construct_key: str = Field(description="The construct key the question was asked about.")
    availability: ConstructAvailability = Field(
        description="Whether the analyzer models, does not model, or says nothing about it."
    )
    category: AbsenceCategory = Field(description="The absence category this resolves to.")
    summary: str = Field(description="The rendered one-line explanation.")
    remediation: str = Field(description="Short, safe guidance.")
    source_missing: bool = Field(
        description="Always false — a construct's absence never means the source is missing."
    )


class FormatCapabilitySnapshot(BaseModel):
    """The full, deterministic registry view exposed to the REST contract + UI (CPDO-2.4).

    Derived from the (deterministic) import-source registry and the static seeds, so identical
    inputs yield an identical snapshot — safe to cache by :attr:`version` and to mirror in a
    TypeScript contract.
    """

    model_config = ConfigDict(extra="forbid")

    version: str = Field(description="The registry contract version (:data:`REGISTRY_VERSION`).")
    review_date: str = Field(description="When the registry's seeds/explanations were reviewed.")
    analysis_schema_version: str = Field(
        description="The payload-analysis contract version this registry's reason mapping pairs "
        "with, so a reader can tell the two apart when either moves.",
    )
    absence_categories: List[str] = Field(
        description="The canonical set of absence-category strings, sorted. Contract tests reject "
        "any category outside this set.",
    )
    absences: List[AbsenceExplanation] = Field(
        description="The reviewed explanation for each absence category, in vocabulary order.",
    )
    reason_absence_categories: Dict[str, str] = Field(
        description="Analysis reason code → absence category, for every reason code CPDO-1.1 can "
        "store.",
    )
    formats: List[FormatCapability] = Field(
        description="One capability entry per registered import source, in key order.",
    )


# ===========================================================================
# Absence explanations (one reviewed template per cause)
# ===========================================================================

# The single source of the eight causes' honest wording. The whole point of the table is the
# ``source_missing`` column: it is True on exactly one row, and no derivation anywhere in this
# module can move it. A parse limit says the data is in the source and apiome cannot describe
# it — the opposite claim from "the source is missing", and the one CPDO-2.4 exists to keep
# distinguishable.
_ABSENCE_EXPLANATIONS: Dict[AbsenceCategory, AbsenceExplanation] = {
    AbsenceCategory.SOURCE_MISSING: AbsenceExplanation(
        category=AbsenceCategory.SOURCE_MISSING,
        category_label="Source not captured",
        summary_template="No source material was captured for this revision, so there is nothing "
        "to analyse for {construct}.",
        remediation="Re-import the item so its source is captured, then the analysis will run.",
        source_missing=True,
    ),
    AbsenceCategory.NOT_ANALYZED: AbsenceExplanation(
        category=AbsenceCategory.NOT_ANALYZED,
        category_label="Not analysed yet",
        summary_template="This revision has not been analysed, so nothing is known about "
        "{construct} either way.",
        remediation="Re-import the item to produce an analysis for its current revision.",
        source_missing=False,
    ),
    AbsenceCategory.FORMAT_UNSUPPORTED: AbsenceExplanation(
        category=AbsenceCategory.FORMAT_UNSUPPORTED,
        category_label="Format not analysed",
        summary_template="apiome has no native analyzer for this format, so {construct} is not "
        "described. The source itself is unaffected.",
        remediation="This is an apiome capability boundary, not a problem with the source.",
        source_missing=False,
    ),
    AbsenceCategory.PARSE_LIMIT: AbsenceExplanation(
        category=AbsenceCategory.PARSE_LIMIT,
        category_label="Parser limit",
        summary_template="apiome's analyzer for this format does not describe {construct}; the "
        "source may well contain it.",
        remediation="This is an apiome parser limitation — read the original source to confirm "
        "what is there.",
        source_missing=False,
    ),
    AbsenceCategory.ANALYZER_FAILED: AbsenceExplanation(
        category=AbsenceCategory.ANALYZER_FAILED,
        category_label="Analysis failed",
        summary_template="The analyzer failed on this revision, so {construct} was never "
        "described. The import itself completed.",
        remediation="Re-import to retry the analysis; the catalog item is unaffected.",
        source_missing=False,
    ),
    AbsenceCategory.VALUE_REDACTED: AbsenceExplanation(
        category=AbsenceCategory.VALUE_REDACTED,
        category_label="Value withheld",
        summary_template="The structure of {construct} is known, but its value is withheld by the "
        "value-visibility policy in force.",
        remediation="Request a wider value visibility only if the stored record was written under "
        "one; a record never held values it can now reveal.",
        source_missing=False,
    ),
    AbsenceCategory.ABSENT_IN_SOURCE: AbsenceExplanation(
        category=AbsenceCategory.ABSENT_IN_SOURCE,
        category_label="Not in the source",
        summary_template="The analyzer models {construct} and did not observe it, so this source "
        "does not contain it.",
        remediation="No action needed — this is a statement about the source, not about apiome.",
        source_missing=False,
    ),
    AbsenceCategory.UNDECLARED: AbsenceExplanation(
        category=AbsenceCategory.UNDECLARED,
        category_label="No statement",
        summary_template="apiome's capability registry makes no statement about {construct} for "
        "this format, so its absence means nothing either way.",
        remediation="Read the original source to determine what is there.",
        source_missing=False,
    ),
}


def absence_explanation(category: AbsenceCategory) -> AbsenceExplanation:
    """Return the reviewed :class:`AbsenceExplanation` for ``category``.

    Args:
        category: The cause category to explain.

    Returns:
        Its reviewed explanation.
    """
    return _ABSENCE_EXPLANATIONS[category]


def absence_explanations() -> List[AbsenceExplanation]:
    """Return every category's reviewed explanation, in vocabulary (enum) order."""
    return [_ABSENCE_EXPLANATIONS[category] for category in AbsenceCategory]


def _render(template: str, construct: Optional[str]) -> str:
    """Render an explanation template, naming ``construct`` safely.

    Substitutes only the single ``{construct}`` slot, and only with a backticked construct key.
    When ``construct`` is omitted a neutral phrase keeps the sentence readable. A literal
    replacement rather than :meth:`str.format`, so a template is text and never a format string —
    the TypeScript mirror does the same, and neither can raise on an unbalanced brace.

    Args:
        template: The reviewed ``summary_template``.
        construct: The construct key to name, or ``None`` for generic phrasing.

    Returns:
        The rendered sentence.
    """
    return template.replace("{construct}", f"`{construct}`" if construct else "this detail")


def explain_analysis_absence(*, status: str, reason: Optional[str]) -> Optional[AbsenceExplanation]:
    """Explain why a payload analysis has no detail, from its stored status and reason.

    The record-level half of the registry's honesty guarantee: every non-available analysis
    status resolves to exactly one reviewed category, and only ``no_source_captured`` resolves
    to a source-missing one. An *unrecognised* reason code resolves to
    :attr:`AbsenceCategory.NOT_ANALYZED` rather than to anything that would claim more than is
    known — a code this registry has never seen is not evidence about the source.

    Args:
        status: The analysis status (:data:`~app.payload_analysis.ANALYSIS_STATUSES`).
        reason: The stored reason code, or ``None``.

    Returns:
        The reviewed explanation, or ``None`` when ``status`` is ``available`` — an available
        analysis has no absence to explain. Pass the result through :func:`render_absence` to
        name the construct it is about.
    """
    if status == STATUS_AVAILABLE and not reason:
        return None
    if not reason:
        # A non-available status is required by the CPDO-1.1 contract to carry a reason; a row
        # that somehow does not is reported as un-analysed rather than as anything stronger.
        return _ABSENCE_EXPLANATIONS[AbsenceCategory.NOT_ANALYZED]
    category = REASON_ABSENCE_CATEGORIES.get(reason)
    if category is None:
        logger.debug("format capability registry: unmapped analysis reason %r", reason)
        return _ABSENCE_EXPLANATIONS[AbsenceCategory.NOT_ANALYZED]
    return _ABSENCE_EXPLANATIONS[category]


def render_absence(explanation: AbsenceExplanation, construct: Optional[str] = None) -> str:
    """Render ``explanation``'s reviewed sentence, naming ``construct`` safely.

    Args:
        explanation: The reviewed explanation to render.
        construct: The construct key to name, or ``None`` for generic phrasing.

    Returns:
        The rendered one-line explanation.
    """
    return _render(explanation.summary_template, construct)


def explain_construct(format_key: str, construct: str) -> ConstructExplanation:
    """Explain what one construct's absence from ``format_key``'s analysis means.

    The construct-level half of the honesty guarantee, and the direct answer to "the tree has
    no node for this — is the data missing?". Three outcomes, and none of them is
    source-missing:

    * the analyzer **models** it → :attr:`AbsenceCategory.ABSENT_IN_SOURCE`: a positive
      statement that the source does not contain it;
    * the analyzer **declares it unmodelled** → :attr:`AbsenceCategory.PARSE_LIMIT`: the source
      may well contain it and apiome has no description of it;
    * neither list names it → :attr:`AbsenceCategory.UNDECLARED`: the registry has nothing to
      say, which is itself the honest answer.

    Args:
        format_key: The import-source key of the analysed format.
        construct: The analyzer's dotted construct key (e.g. ``x12.hl_hierarchy``).

    Returns:
        The resolved :class:`ConstructExplanation`, always with ``source_missing`` false.
    """
    capability = capability_for(format_key)
    normalized = construct.strip()
    if normalized and normalized in set(capability.supported_constructs):
        availability = ConstructAvailability.MODELLED
        category = AbsenceCategory.ABSENT_IN_SOURCE
    elif normalized and normalized in set(capability.unsupported_constructs):
        availability = ConstructAvailability.UNMODELLED
        category = AbsenceCategory.PARSE_LIMIT
    else:
        availability = ConstructAvailability.UNDECLARED
        category = AbsenceCategory.UNDECLARED
    explanation = _ABSENCE_EXPLANATIONS[category]
    return ConstructExplanation(
        format=capability.format,
        construct_key=normalized,
        availability=availability,
        category=category,
        summary=_render(explanation.summary_template, normalized or None),
        remediation=explanation.remediation,
        source_missing=False,
    )


# ===========================================================================
# Reviewed seeds
# ===========================================================================


class _Seed(BaseModel):
    """A reviewed capability seed: the claims no derivation could make on its own.

    Only the fields a person checked against the format's parser and normalizer. Everything
    else on the entry — the analyzer identity, the construct lists, the limits, the conversion
    route — is still read off the live adapter, so a seed cannot go stale about the things the
    code knows.
    """

    model_config = ConfigDict(extra="forbid")

    native_hierarchy: NativeHierarchy
    native_hierarchy_note: str
    source_location: SourceLocationSupport
    value_visibility: ValueVisibilitySupport
    canonical_projection: CanonicalProjectionSupport
    implementation_guide: Optional[ImplementationGuideStatement] = None
    notes: List[str] = Field(default_factory=list)


#: The EDI and vertical-messaging formats (FMT-EPIC-6, plus EDI X12 before it) whose readers
#: check a syntax and nothing above it. Each must ship a reviewed seed carrying an
#: :class:`ImplementationGuideStatement` (FMT-6.10, #5454) — ``test_format_capability_registry``
#: fails for a member without one — and the Format details tab renders that statement as a banner.
IMPLEMENTATION_GUIDE_FAMILY: Tuple[str, ...] = (
    "edix12",
    "edifact",
    "tradacoms",
    "idoc",
    "swift-mt",
    "hl7v3",
    "nacha",
    "dicom",
    "ncpdp",
    "fix-orchestra",
)


def _proxy_route_seed(
    *,
    location_note: str,
    dropped: Iterable[str],
    projection_note: str,
    notes: List[str],
) -> _Seed:
    """A reviewed seed for an FMT-7.5 reverse-proxy route source (#5459).

    The five proxy formats share every judgement but the projection: their payload analysis is
    the format-blind walk, they carry configuration rather than data, and they hold no
    request/response schemas. What differs per format — which constructs are declared rather
    than modelled, and why — is passed in, taken from the parser's own tables so the registry
    names exactly the subset the parser reads.

    Args:
        location_note: How routes are located in this format's source.
        dropped: The declared (not modelled) construct keys, already prefixed.
        projection_note: What the projection keeps, carries and drops.
        notes: Reviewed notes rendered beneath the entry.

    Returns:
        The seed.
    """
    return _Seed(
        native_hierarchy=NativeHierarchy.GENERIC,
        native_hierarchy_note=(
            "The format-blind walk records containers, ordered collections and leaves. Nesting "
            "and ordering survive; this format's own semantics are not named, and their absence "
            "from the tree says nothing about the source."
        ),
        source_location=SourceLocationSupport(quality=SourceLocationQuality.PATH_ONLY, note=location_note),
        value_visibility=ValueVisibilitySupport(
            default=ValueVisibility.DEFAULT,
            maximum=ValueVisibility.NONE,
            note=(
                "A proxy configuration routes requests; it holds no request or response data, so "
                "the analyzer observes no payload values at any policy level. Credential material "
                "the configuration does carry (basic-auth hashes, secret headers, shared secrets) "
                "is redacted at parse time and only counted."
            ),
        ),
        canonical_projection=CanonicalProjectionSupport(
            coverage=ProjectionCoverage.PARTIAL,
            dropped_constructs=sorted(set(dropped)),
            note=projection_note,
        ),
        notes=notes,
    )


def _backticked(names: Iterable[str]) -> str:
    """``a``, ``b`` → "`a`, `b`" for a note."""
    return ", ".join(f"`{name}`" for name in names)


#: The documented nginx subset, directive by directive (FMT-7.5's acceptance criterion), built
#: from :mod:`app.nginx_parser`'s tables so the registry cannot describe a different subset
#: from the one the parser reads.
_NGINX_SUBSET_NOTES: List[str] = [
    "Read (the routing surface): "
    + "; ".join(f"`{name}` — {meaning}" for name, meaning in NGINX_READ_DIRECTIVES.items())
    + ".",
    "Carried by name as policy on the operations they govern, with nginx inheritance resolved "
    "(the innermost of http → server → location that sets a directive wins): "
    + _backticked(NGINX_CARRIED_DIRECTIVES)
    + ".",
    "Declared parsing limits — recognized and deliberately not interpreted: "
    + "; ".join(f"`{name}` — {reason}" for name, reason in NGINX_DECLARED_DIRECTIVES.items())
    + ".",
    "Any directive in none of these lists is declared as `directive.<name>` on the coverage "
    "ledger of the document that uses it. Outside the subset is a declared limit, never a "
    "silent omission.",
]

#: Statement shared by every proxy seed's projection note.
_PROXY_SCHEMALESS = (
    "There are no request/response schemas in the source, so operations have no messages; the "
    "ledger states that as a capability limit of the format, and every operation and service "
    "is labelled inferred."
)


# EDI X12 and COBOL copybook are seeded explicitly because they are the two formats whose
# boundaries the ticket requires to be stated rather than inferred — and the two where the gap
# between "the analysis holds it" and "the canonical model holds it" is widest. gRPC joined them
# in FMT-3.7 (#5432), which needed the registry to say which Protobuf **Editions** features the
# canonical model carries and which it does not.
_CAPABILITY_SEED: Dict[str, _Seed] = {
    "grpc": _Seed(
        # gRPC's payload analysis is still the format-blind walk, so these three fields restate
        # what derivation produces rather than claiming more. Only the projection statement and
        # the notes below are reviewed judgements — which is exactly what FMT-3.7 needed a seed
        # for: what a compiled descriptor set loses on its way into the canonical model.
        native_hierarchy=NativeHierarchy.GENERIC,
        native_hierarchy_note=(
            "The format-blind walk records containers, ordered collections and leaves. Nesting "
            "and ordering survive; this format's own semantics are not named, and their absence "
            "from the tree says nothing about the source."
        ),
        source_location=SourceLocationSupport(
            quality=SourceLocationQuality.PATH_ONLY,
            note=(
                "Nodes locate by structural path and sibling ordinal only. A UI can identify the "
                "construct but cannot point at a line or byte range in the raw source. A "
                "descriptor set is a compiled artifact and carries no source spans, so a line "
                "number could only ever be guessed from the uploaded text."
            ),
        ),
        value_visibility=ValueVisibilitySupport(
            default=ValueVisibility.DEFAULT,
            maximum=ValueVisibility.FULL,
            note=(
                "Leaf values are observed, so the stored record carries whatever the "
                "value-visibility policy in force allows — the default keeps only presence and "
                "length."
            ),
        ),
        canonical_projection=CanonicalProjectionSupport(
            coverage=ProjectionCoverage.PARTIAL,
            dropped_constructs=[
                "protobuf.custom_options",
                "protobuf.extension_ranges",
                "protobuf.features.default_symbol_visibility",
                "protobuf.features.enforce_naming_style",
            ],
            note=(
                "Services, methods with their streaming modes, messages, fields with their "
                "numbers, enums with their value numbers, oneofs and reserved ranges all "
                "survive. **Protobuf Editions** (2023/2024) features are resolved down the "
                "lexical scope chain and six of the eight are modelled: `field_presence` "
                "becomes canonical nullability (an EXPLICIT field is nullable, its IMPLICIT "
                "twin is not, and LEGACY_REQUIRED is neither), `enum_type` becomes the enum's "
                "`enum_closed` flag, and `repeated_field_encoding`, `utf8_validation`, "
                "`message_encoding` and `json_format` are recorded on the construct that sets "
                "them. The two listed above are not modelled: they govern generated-code "
                "naming and symbol visibility — compiler behaviour with no wire or JSON "
                "meaning — so the canonical model has nothing for them to become. Every file's "
                "edition, syntax and fully resolved feature set is recorded in provenance "
                "whether or not each feature is modelled."
            ),
        ),
        notes=[
            "The compiled descriptor set is the artifact of record, not the .proto text: "
            "imports, option inheritance and Editions feature resolution are the compiler's "
            "answers, never a re-parse here. A document that does not compile has no analysis "
            "at all, which is reported as a compile failure rather than as an empty source.",
            "Editions feature resolution is ours, not the compiler's: `buf build` writes each "
            "scope's raw `features` override into the descriptor and leaves the merge to the "
            "reader, so the resolved values reported here are computed from the edition's own "
            "defaults table as published in descriptor.proto.",
            "A type a target file references but an *import* declares (google.protobuf."
            "Timestamp, a sibling module's message) is carried as a reference with no local "
            "definition. That is the shape a protobuf `import` has, not a resolution failure.",
            "Custom options and extension declarations are preserved in the descriptor set and "
            "in the retained source, and only there — the canonical model has no vocabulary for "
            "a user-defined option, so it is neither named nor counted.",
        ],
    ),
    "edix12": _Seed(
        native_hierarchy=NativeHierarchy.NATIVE,
        native_hierarchy_note=(
            "Interchange → functional group → transaction set → segment → element, with "
            "composite components regrouped under their element position rather than flattened "
            "into siblings."
        ),
        source_location=SourceLocationSupport(
            quality=SourceLocationQuality.BYTE_OFFSETS,
            note=(
                "The X12 parser exposes no positions, so the interchange text is scanned a second "
                "time on its own declared delimiters and matched to the parsed segments. Every "
                "segment, group and transaction set then carries the exact offset, length and line "
                "of the bytes it was read from, alongside its envelope path "
                "(``ISA/GS[0]/ST[2]/NM1[4]``). Where the two readings disagree the scan is "
                "abandoned whole and the record falls back to path and ordinal — a record carries "
                "positions that were checked against the parse, or it carries none."
            ),
        ),
        value_visibility=ValueVisibilitySupport(
            default=ValueVisibility.DEFAULT,
            maximum=ValueVisibility.FULL,
            note=(
                "Element values are observed, so the stored record carries whatever the "
                "value-visibility policy in force allows — nothing more. An X12 element is "
                "business data (names, account numbers, claim amounts); the default withholds it "
                "and keeps only presence and length."
            ),
        ),
        canonical_projection=CanonicalProjectionSupport(
            coverage=ProjectionCoverage.PARTIAL,
            dropped_constructs=[
                "x12.control_numbers",
                "x12.delimiters",
                "x12.empty_elements",
                "x12.envelope_control_totals",
                "x12.functional_group",
                "x12.interchange_envelope",
                "x12.repeating_elements",
                "x12.segment_ordinals",
                "x12.segment_repeat_counts",
            ],
            note=(
                "The canonical model describes one schema, so normalization reads the first "
                "functional group's first transaction set and drops the envelope around it. "
                "Every group and transaction set the interchange carried is in the analysis, "
                "and only there. An analysis of an interchange carrying more than one says so "
                "explicitly, naming the set the conversion was derived from."
            ),
        ),
        implementation_guide=implementation_guide(
            "ASC X12 envelope and segment syntax (ISA/GS/ST)",
            ["the 4010 and 5010 implementation guides (TR3s)", "trading-partner companion guides"],
            ["an ST03 implementation convention reference"],
        ),
        notes=[
            "An element position the source wrote and left empty is recorded as present with a "
            "zero length; a position the source never wrote is not recorded at all. The two are "
            "different facts about the payload and are never rendered as one.",
            "HL loops are described as the segments they are, not as the hierarchy they encode. "
            "Where the interchange declares a repetition separator (ISA11 at 00501 and later, "
            "never at 00401) a repeated element carries its occurrences and states how many.",
            "Control totals declared by the SE, GE and IEA trailers are recorded beside the "
            "counts actually observed, so an interchange that disagrees with itself can be seen "
            "to. The trailer segments themselves are not tree nodes, and TA1 acknowledgements are "
            "removed by the parser before the analysis runs.",
            "No 4010/5010 implementation-guide conformance is evaluated — a structurally valid "
            "interchange is not claimed to be a conformant one, and an ST03 implementation "
            "convention reference is recorded as the sender's claim rather than as a checked fact.",
        ],
    ),
    # FMT-6.1 (#5445): X12's rest-of-world twin, seeded for the same reason X12 is — the gap
    # between what the analysis holds and what the canonical model holds is the whole story, and
    # the acceptance criterion is that the panel says no implementation guide was consulted.
    "edifact": _Seed(
        native_hierarchy=NativeHierarchy.NATIVE,
        native_hierarchy_note=(
            "Interchange → functional group (when the interchange uses them) → message → segment "
            "→ element, with composite components under their element position and syntax-4 "
            "repetitions under the element they repeat."
        ),
        source_location=SourceLocationSupport(
            quality=SourceLocationQuality.BYTE_OFFSETS,
            note=(
                "The interchange text is read directly on its own service characters — the ones a "
                "`UNA` declares, or the ISO 9735 defaults when it is absent — so every segment, "
                "group and message carries the exact offset, length and line of the bytes it was "
                "read from, alongside its envelope path (``UNB/UNG[0]/UNH[1]/NAD[3]``). There is "
                "no second reading to disagree with, so every record carries positions."
            ),
        ),
        value_visibility=ValueVisibilitySupport(
            default=ValueVisibility.DEFAULT,
            maximum=ValueVisibility.FULL,
            note=(
                "Element values are observed, so the stored record carries whatever the "
                "value-visibility policy in force allows — nothing more. An EDIFACT element is "
                "business data (party ids, prices, addresses); the default withholds it and keeps "
                "only presence and length. The `UNB` recipient password is never lifted out of "
                "its element."
            ),
        ),
        canonical_projection=CanonicalProjectionSupport(
            coverage=ProjectionCoverage.PARTIAL,
            dropped_constructs=[
                "edifact.control_references",
                "edifact.delimiters",
                "edifact.empty_elements",
                "edifact.envelope_control_totals",
                "edifact.functional_group",
                "edifact.interchange_envelope",
                "edifact.release_character",
                "edifact.repeating_elements",
                "edifact.segment_ordinals",
                "edifact.segment_repeat_counts",
                "edifact.service_string_advice",
            ],
            note=(
                "The canonical model describes one schema, so normalization reads the first "
                "functional group's first message (or the first message, when the interchange "
                "carries no groups) and drops the envelope around it. Every group and message the "
                "interchange carried is in the analysis, and only there. An analysis of an "
                "interchange carrying more than one says so explicitly, naming the message the "
                "conversion was derived from."
            ),
        ),
        implementation_guide=implementation_guide(
            "UN/EDIFACT syntax (ISO 9735)",
            ["the D.96A and D.01B message directories", "EANCOM", "ODETTE/VDA guides"],
            ["a UNH message version, release and association code"],
        ),
        notes=[
            EDIFACT_IMPLEMENTATION_GUIDE_STATEMENT,
            "Segment groups are described as the flat segments they are, not as the nesting a "
            "directory would give them, and code values (qualifiers, units, party roles) are "
            "recorded as written rather than looked up.",
            "Control counts and control references declared by the UNT, UNE and UNZ trailers are "
            "recorded beside what was actually observed, and every disagreement is stated as a "
            "warning, so an interchange that disagrees with itself can be seen to — it is read, "
            "not rejected.",
            "An element position the source wrote and left empty is recorded as present with a "
            "zero length; a position the source never wrote is not recorded at all. The decimal "
            "mark a UNA declares is recorded, and values are never re-read as numbers.",
            "One batch interchange is read per document. Interactive EDIFACT (UIB/UIH), packages "
            "(UNO/UNP) and files carrying several interchanges are refused rather than read in "
            "part.",
            # FMT-6.5 (#5449): the dialect profiles on the EDIFACT engine, and where each stops.
            "Dialect profiles: every interchange is read with the EANCOM profile, the ODETTE/VDA "
            "profile or plain UN/EDIFACT. The profile applied, and the evidence it was recognised "
            "on, are recorded in the import's provenance, the canonical model's `format_profile` "
            "extras and the analysis; each message records whether the profile's message set names "
            "it. A TRADACOMS transmission (`STX=`) is not an EDIFACT interchange and is routed to "
            "its own adapter.",
            profile_statement(EANCOM),
            profile_statement(ODETTE),
        ],
    ),
    # FMT-6.7 (#5451): DICOM, seeded because the panel must state the pixel-data boundary — pixel
    # data is never read, stored or analysed — and that no patient-identifying value is stored at
    # the default value-visibility policy.
    "dicom": _Seed(
        native_hierarchy=NativeHierarchy.NATIVE,
        native_hierarchy_note=(
            "Dataset → attribute, in DICOM's own vocabulary: each attribute with its tag, VR, VM and "
            "length; a sequence (`SQ`) → its items → their attributes, to any depth; a Structured "
            "Report's `ContentSequence` items as content items with their value type, relationship "
            "type and concept name. A Part 10 file adds its file meta group, and every pixel-data "
            "element is a `pixel-data` node with `read: false`."
        ),
        source_location=SourceLocationSupport(
            quality=SourceLocationQuality.BYTE_OFFSETS,
            note=(
                "A Part 10 element carries the byte offset and length of its header and value "
                "(offsets into the inflated dataset for a deflated transfer syntax), beside its tag "
                "path (``(0040,A730)[1]/(0040,A043)``). A DICOM JSON attribute carries its JSON "
                "pointer only."
            ),
        ),
        value_visibility=ValueVisibilitySupport(
            default=ValueVisibility.DEFAULT,
            maximum=ValueVisibility.FULL,
            note=(
                "Attribute values are patient data — names, identifiers, dates, UIDs, report text "
                "— so the stored record carries whatever the value-visibility policy allows; the "
                "default keeps only presence and length, so no patient-identifying value is stored. "
                "Tags, VRs, multiplicities, the SOP class, transfer syntax, modality and an SR "
                "content item's value type and concept name are structure and are always shown. "
                "The verbatim upload is not kept as the version's source."
            ),
        ),
        canonical_projection=CanonicalProjectionSupport(
            coverage=ProjectionCoverage.PARTIAL,
            dropped_constructs=[
                "dicom.byte_offsets",
                "dicom.pixel_data",
                "dicom.private_attribute_meaning",
                "dicom.sr_content_values",
            ],
            note=(
                "The canonical model is DICOM's information model as the instances realise it: one "
                "record type per SOP class (or per query level, for a query result), one field per "
                "attribute keyed by its tag and typed by its VR — an alias over string, integer or "
                "number, with `PN` a record of its component groups — a list where the VM allows "
                "several values, and one nested record type per sequence tag, folded across every "
                "item (`ContentSequence` folds into a recursive `ContentSequenceItem`). The Part 10 "
                "file meta group is its own type. A Structured Report's content tree is recorded "
                "beside the model as a hierarchy (``dicom_sr_content_trees``). "
                + DICOM_VALUE_STATEMENT
            ),
        ),
        implementation_guide=implementation_guide(
            "DICOM Part 10 and DICOM JSON attribute structure",
            ["IOD module requirements (PS3.3)", "SR templates (PS3.16)", "the sending device's conformance statement"],
            ["the SOP Class UID"],
        ),
        notes=[
            PIXEL_DATA_BOUNDARY_STATEMENT,
            "Attributes PS3.15 Annex E lists for de-identification, and every private attribute, are "
            "marked ``dicom_patient_identifying`` on their field; the mark describes the attribute, "
            "since no value is in the model at all.",
            "Read: Part 10 files in implicit or explicit VR little endian, explicit VR big endian, "
            "deflated explicit VR little endian and every encapsulated transfer syntax (only its "
            "pixel data is compressed, and that is never read); the DICOM JSON model (PS3.18 Annex "
            "F), one dataset or an array; and archives of DICOM JSON documents. A Part 10 file "
            "inside an archive is skipped and stated, because archive members are read as text.",
            "Not checked: IOD module requirements (Type 1/2/3), SR templates and the codes a "
            "content item names. A dataset must name its SOP Class UID (0008,0016) unless it is a "
            "query/retrieve result; a file without the `DICM` magic is refused, as is one that "
            "stops inside an element.",
        ],
    ),
    # FMT-6.6 (#5450): NACHA ACH, seeded because its control totals must be stated as declared
    # versus observed and its account numbers governed by value visibility wherever a reader meets
    # them — and because the panel must say the Operating Rules were not consulted.
    "nacha": _Seed(
        native_hierarchy=NativeHierarchy.NATIVE,
        native_hierarchy_note=(
            "File → batch (`5` header … `8` control) → entry detail (`6`) → addenda (`7`: 05 "
            "payment-related, 98 notification of change, 99 return), with the file header (`1`) "
            "and file control (`9`) as records beside the batches. Every record is cut into its "
            "fixed-width fields by its record type code."
        ),
        source_location=SourceLocationSupport(
            quality=SourceLocationQuality.BYTE_OFFSETS,
            note=(
                "Records are fixed-width (94 characters), so every record and every field carries "
                "the exact line, offset and length it was cut from, beside its path "
                "(``FILE/5[1]/6[2]/amount``)."
            ),
        ),
        value_visibility=ValueVisibilitySupport(
            default=ValueVisibility.DEFAULT,
            maximum=ValueVisibility.FULL,
            note=(
                "Field values are payment data — account numbers, names, amounts, identification "
                "numbers — so the stored record carries whatever the value-visibility policy "
                "allows; the default keeps presence and length only. Record types, transaction and "
                "SEC codes, counts and the control totals are structure and are always shown."
            ),
        ),
        canonical_projection=CanonicalProjectionSupport(
            coverage=ProjectionCoverage.PARTIAL,
            dropped_constructs=[
                "nacha.byte_offsets",
                "nacha.routing_check_digit",
                "nacha.transaction_direction",
            ],
            note=(
                "The canonical model is the file's structure: AchFile → Batch → EntryDetail, one "
                "record type per record layout (and per addenda type present) with each field's "
                "positions recorded. Payload values never enter it. The file's SEC codes, batches "
                "and every control total, declared versus observed, are recorded beside the model."
            ),
        ),
        implementation_guide=implementation_guide(
            "NACHA ACH record format (94-character records, types 1/5/6/7/8/9)",
            ["the NACHA Operating Rules' SEC-code requirements", "IAT layouts", "ODFI or bank file specifications"],
            ["a batch's Standard Entry Class code"],
        ),
        notes=[
            NACHA_OPERATING_RULES_STATEMENT,
            "Every total a batch control (`8`) or file control (`9`) record declares — entry and "
            "addenda count, entry hash, total debit, total credit, batch count, block count — is "
            "recomputed and recorded beside the declaration, and each disagreement is stated as a "
            "warning: read, not rejected.",
            "A record that is not 94 characters is refused as malformed (or as truncated when the "
            "file stops inside it); a batch with no entries and an addenda record with no entry "
            "before it are refused as semantically invalid. SEPA payment files are ISO 20022 XML "
            "and route to the ISO 20022 adapter, never here.",
        ],
    ),
    # FMT-6.8 (#5452): NCPDP SCRIPT and Telecom, seeded because the panel must name the supported
    # versions of both sub-formats and say that no NCPDP implementation guide was consulted.
    "ncpdp": _Seed(
        native_hierarchy=NativeHierarchy.NATIVE,
        native_hierarchy_note=(
            "SCRIPT: message (its transaction type — NewRx, RxFill, RxChangeRequest … — detected "
            "per message) → element → leaf element or attribute. Telecom D.0: transmission → the "
            "fixed transaction header and the patient (`AM01`) and insurance (`AM04`) segments → "
            "transaction → segment (`AM07` claim, `AM11` pricing …) → field (two-character id)."
        ),
        source_location=SourceLocationSupport(
            quality=SourceLocationQuality.PATH_ONLY,
            note=(
                "A SCRIPT node locates by its element path (``Message/Body/NewRx/Patient``) only — "
                "the XML reader keeps no positions. A Telecom header field, segment and transaction "
                "additionally carries the exact offset and length it was cut from, beside its path "
                "(``TRANSMISSION/transaction[1]/AM07[0]``); a segment field locates by path."
            ),
        ),
        value_visibility=ValueVisibilitySupport(
            default=ValueVisibility.DEFAULT,
            maximum=ValueVisibility.FULL,
            note=(
                "Element, attribute and field values are patient and prescription data — names, "
                "dates of birth, identifiers, drug codes, quantities, amounts — so the stored record "
                "carries whatever the value-visibility policy allows; the default keeps presence and "
                "length only. Transaction types, segment and field ids, the version and the "
                "transaction counts are structure and are always shown."
            ),
        ),
        canonical_projection=CanonicalProjectionSupport(
            coverage=ProjectionCoverage.PARTIAL,
            dropped_constructs=[
                "ncpdp.telecom_byte_offsets",
                "ncpdp.script_relates_to",
            ],
            note=(
                "SCRIPT: one record type per element name, inferred across every message read "
                "(attributes and repeats included). Telecom: the transmission → transaction → "
                "segment structure, one record per segment id with a field per field id observed, "
                "and the header as a positional record. Payload values never enter the model. Each "
                "message's or transmission's transaction type, the version claimed and the declared "
                "versus observed transaction count are recorded beside the model."
            ),
        ),
        implementation_guide=implementation_guide(
            "NCPDP SCRIPT element structure and Telecommunication D.0 segment/field syntax",
            [
                "the SCRIPT Implementation Guide",
                "the Telecommunication D.0 Implementation Guide and data dictionary",
                "payer sheets",
            ],
            ["a SCRIPT message's version and release"],
        ),
        notes=[
            NCPDP_IMPLEMENTATION_GUIDE_STATEMENT,
            "Versions read: SCRIPT messages of any version — 10.x `version`/`release` or the "
            "2017071-and-later `TransactionVersion` is recorded per message, not branched on; "
            "Telecommunication D.0 request transmissions, whose header version (`D0`) is checked — "
            "any other version is refused. Telecom response transmissions are not read.",
            "Field ids are labelled with their data element where a short table knows them "
            "(`302-C2 Cardholder ID`); the D.0 data dictionary and payer sheets are not consulted, "
            "so a field's presence is recorded, never its requiredness. The header's transaction "
            "count is compared with the transactions observed for B1/B2/B3 and a disagreement is "
            "stated as a warning: read, not rejected.",
        ],
    ),
    # FMT-6.5 (#5449): TRADACOMS, the UK retail dialect — EDIFACT-style segments read with the
    # EDIFACT lexical layer inside an envelope of its own, so the panel must name the profile and
    # say that the TRADACOMS manual was not consulted.
    "tradacoms": _Seed(
        native_hierarchy=NativeHierarchy.NATIVE,
        native_hierarchy_note=(
            "Transmission (`STX` … `END`) → file (a header message carrying `TYP`, then its detail "
            "and trailer messages) → message (`MHD` … `MTR`) → segment → element, with composite "
            "components under their element position. Several transmissions in one document are "
            "each their own root."
        ),
        source_location=SourceLocationSupport(
            quality=SourceLocationQuality.BYTE_OFFSETS,
            note=(
                "The transmission text is read directly on TRADACOMS' fixed service characters "
                "(`=` after the tag, `+`, `:`, `'` and the `?` release character), so every "
                "segment, file and message carries the exact offset, length and line of the bytes "
                "it was read from, alongside its envelope path (``STX[0]/FILE[0]/MHD[1]/OLD[3]``)."
            ),
        ),
        value_visibility=ValueVisibilitySupport(
            default=ValueVisibility.DEFAULT,
            maximum=ValueVisibility.FULL,
            note=(
                "Element values are observed, so the stored record carries whatever the "
                "value-visibility policy in force allows — nothing more. A TRADACOMS element is "
                "business data (trading-party codes, prices, quantities); the default withholds it "
                "and keeps only presence and length. The `STX` recipient's reference, which "
                "trading partners use as a password, is never lifted out of its element."
            ),
        ),
        canonical_projection=CanonicalProjectionSupport(
            coverage=ProjectionCoverage.PARTIAL,
            dropped_constructs=[
                "tradacoms.empty_elements",
                "tradacoms.message_control_totals",
                "tradacoms.message_sequence",
                "tradacoms.multiple_transmissions",
                "tradacoms.segment_ordinals",
                "tradacoms.segment_repeat_counts",
                "tradacoms.transmission_control_totals",
                "tradacoms.transmission_envelope",
            ],
            note=(
                "The canonical model describes one schema, so normalization reads the first "
                "transmission's first detail message — the first that is not a file header "
                "(ORDERS rather than ORDHDR) — and records its transmission, its file and that "
                "file's messages in extras. Every transmission, file and message is in the "
                "analysis, and an analysis of a document carrying more than one message says so "
                "explicitly, naming the message the conversion was derived from."
            ),
        ),
        implementation_guide=implementation_guide(
            "TRADACOMS syntax (STX/MHD/MTR/END envelope over EDIFACT-style segments)",
            ["the TRADACOMS manual's message specifications", "trading-partner guides"],
            ["an MHD message type and version"],
        ),
        notes=[
            TRADACOMS_IMPLEMENTATION_GUIDE_STATEMENT,
            profile_statement(TRADACOMS),
            "The segment counts declared by each `MTR` and the message count declared by `END` "
            "are recorded beside what was observed, and every disagreement is stated as a warning "
            "— read, not rejected. `MHD` message references must count 1, 2, 3 … through a "
            "transmission; a document whose references skip is refused as semantically invalid.",
            "A document that opens with an EDIFACT `UNB` interchange header is refused as a format "
            "mismatch: TRADACOMS' `STX` envelope is parsed as its own structure, never as an "
            "EDIFACT interchange.",
        ],
    ),
    # FMT-6.2 (#5446): SAP IDoc, seeded because the two transport forms differ in what they can
    # say — the flat form has byte offsets and needs a segment definition for its fields, the XML
    # form names its fields and has no byte layout — and a reader must be told which applies.
    "idoc": _Seed(
        native_hierarchy=NativeHierarchy.NATIVE,
        native_hierarchy_note=(
            "IDoc → segment → field, with segments nested by their parent segment numbers "
            "(PSGNUM) rather than by record order. Each IDoc in a file is its own root."
        ),
        source_location=SourceLocationSupport(
            quality=SourceLocationQuality.BYTE_OFFSETS,
            note=(
                "A flat IDoc's control record and every data record carry their line, offset and "
                "length, and each field cut from SDATA its offset within SDATA and within the "
                "record. An XML IDoc has no byte layout, so its records locate by path "
                "(``IDOC[0]/E1EDP01[6]/E1EDP19[0]``) and declare byte offsets unsupported."
            ),
        ),
        value_visibility=ValueVisibilitySupport(
            default=ValueVisibility.DEFAULT,
            maximum=ValueVisibility.FULL,
            note=(
                "Segment field values are observed payload, so the stored record carries whatever "
                "the value-visibility policy allows. The control record — basic type, extension, "
                "message type, partners, ports, direction, dates — is structure, recorded in the "
                "IDoc node's attributes and never withheld."
            ),
        ),
        canonical_projection=CanonicalProjectionSupport(
            coverage=ProjectionCoverage.PARTIAL,
            dropped_constructs=[
                "idoc.byte_offsets",
                "idoc.field_offsets",
                "idoc.multiple_idocs",
                "idoc.segment_numbers",
            ],
            note=(
                "The canonical model is the first IDoc's basic type: one record type per segment "
                "type, nested as the segment numbers nest them, with list cardinality where any "
                "parent carries more than one occurrence or the definition allows it. Segment "
                "numbers, byte offsets and further IDocs in the file are in the analysis only. A "
                "flat file and an XML document produce the same model when both are read with "
                "the same segment definitions."
            ),
        ),
        implementation_guide=implementation_guide(
            "SAP IDoc control and data record layout (EDI_DC40/EDI_DD40) and IDoc XML",
            [
                "the basic type's WE30 structure",
                "standard SAP segment definitions (unless a WE60 export is supplied)",
                "qualifier code lists",
            ],
            ["the control record's IDoc type and message type"],
        ),
        notes=[
            "A flat segment's 1000-character SDATA has no field boundaries of its own. With a "
            "segment definition (a WE60 export) supplied beside the IDoc it is cut at the declared "
            "offsets; without one it is recorded as a single opaque SDATA value. Standard SAP "
            "segment layouts are not bundled.",
            "Field offsets and lengths are computed under stated assumptions — one character per "
            "byte, the release 4.0+ EDI_DC40/EDI_DD40 layouts, trailing blanks as padding — and "
            "every flat record says so.",
            "A declared HLEVEL that disagrees with the depth the parent segment numbers give is "
            "recorded beside it; the hierarchy follows the numbers.",
            "Nothing is checked against the basic type's structure (WE30) or the qualifier code "
            "lists: a well-formed IDoc is not claimed to be a valid one. Status records (EDI_DS40) "
            "and release 2.x record layouts are not read.",
        ],
    ),
    # FMT-6.3 (#5447): SWIFT MT, seeded because the MX correspondence it records must be stated as a
    # note — never as a conversion — wherever a reader meets it, and the capability panel is one.
    "swift-mt": _Seed(
        native_hierarchy=NativeHierarchy.NATIVE,
        native_hierarchy_note=(
            "Message → block (basic, application and user headers, text, trailer) → sequence → "
            "field → component, code word or numbered line. Each field keeps its tag and option "
            "letter (``50K`` and ``50F`` are the same field in different options)."
        ),
        source_location=SourceLocationSupport(
            quality=SourceLocationQuality.BYTE_OFFSETS,
            note=(
                "Every header block and every field carries the line, offset and length of the "
                "text it was read from, beside its path (``MSG[0]/{4}/A/32A[3]``)."
            ),
        ),
        value_visibility=ValueVisibilitySupport(
            default=ValueVisibility.DEFAULT,
            maximum=ValueVisibility.FULL,
            note=(
                "Field components, code-word texts and lines are payment data — accounts, names, "
                "amounts — so the stored record carries whatever the value-visibility policy "
                "allows. Tags, option letters, code-word qualifiers and the header blocks are "
                "structure and are always shown."
            ),
        ),
        canonical_projection=CanonicalProjectionSupport(
            coverage=ProjectionCoverage.PARTIAL,
            dropped_constructs=[
                "swift.basic_header",
                "swift.application_header",
                "swift.user_header",
                "swift.trailer",
                "swift.byte_offsets",
                "swift.multiple_messages",
            ],
            note=(
                "The canonical model is the first message: one record type per message, and one "
                "per field as written with its option (``Field50K``), so option letters survive as "
                "different shapes; code words become qualifier/text records. Header blocks are "
                "recorded beside the model as structure, and further messages in the file are in "
                "the analysis only."
            ),
        ),
        implementation_guide=implementation_guide(
            "SWIFT FIN block structure and the stated MT103, MT202, MT940 and MT942 field catalogue",
            ["SWIFT network-validated rules", "SWIFT usage rules", "the MX usage guidelines", "market practice guides"],
            ["a block 3 validation flag (field 119: STP, COV, REMIT)"],
        ),
        notes=[
            "Where an MX counterpart is documented — MT103 → pacs.008, MT202 → pacs.009, MT202 COV → "
            "pacs.009 (COV), MT940 → camt.053, MT942 → camt.052 — it is recorded as a note, never as "
            "a conversion. " + MX_CORRESPONDENCE_DISCLAIMER,
            "MT103, MT202 (including COV), MT940 and MT942 are read; other message types are "
            "refused. Fields are read by a small stated field catalogue; content that does not "
            "match its documented shape is kept as lines and flagged, never refused.",
            "SWIFT network-validated rules and usage rules are not evaluated, BICs are not looked "
            "up, and CHK/MAC trailers are recorded but not verified.",
        ],
    ),
    # FMT-6.4 (#5448): HL7 v3 / CDA, seeded because a ``templateId`` is a conformance *claim* the
    # document makes about itself, and the capability panel must say it is recorded, not validated.
    "hl7v3": _Seed(
        # The payload analysis is still the format-blind walk, so the first three fields restate
        # what derivation produces. The reviewed judgements are the projection and the notes.
        native_hierarchy=NativeHierarchy.GENERIC,
        native_hierarchy_note=(
            "The format-blind walk records containers, ordered collections and leaves. Nesting "
            "and ordering survive; this format's own semantics are not named, and their absence "
            "from the tree says nothing about the source."
        ),
        source_location=SourceLocationSupport(
            quality=SourceLocationQuality.PATH_ONLY,
            note=(
                "Elements locate by structural path and sibling ordinal only "
                "(``ClinicalDocument/component/structuredBody/component[2]/section``). The "
                "hardened XML reader exposes no positions."
            ),
        ),
        value_visibility=ValueVisibilitySupport(
            default=ValueVisibility.DEFAULT,
            maximum=ValueVisibility.FULL,
            note=(
                "A clinical document is patient data: names, identifiers, dates and observation "
                "values are leaf values, so the stored record carries whatever the "
                "value-visibility policy allows — the default keeps only presence and length."
            ),
        ),
        canonical_projection=CanonicalProjectionSupport(
            coverage=ProjectionCoverage.PARTIAL,
            dropped_constructs=[
                "hl7v3.datatype_part_qualifiers",
                "hl7v3.narrative_markup",
                "hl7v3.unmapped_datatypes",
                "hl7v3.vocabulary_bindings",
            ],
            note=(
                "The canonical model is the document's shape inferred from the instance: one "
                "record type per RIM class, every occurrence folded together (a member that "
                "repeats anywhere is a list, one missing anywhere is nullable). Relationships "
                "that depend on their parent are named by it (``StructuredBodyComponent``, "
                "``OrganizerComponent``), so the header → body → section → entry hierarchy reads "
                "from the types. The RIM data types II, CD, CE, CV, CS, TS, IVL_TS, PQ, IVL_PQ, "
                "RTO_PQ_PQ, INT, REAL, BL, AD, PN, TEL and ED become record types with their "
                "declared members, ST, SC, ON and the section narrative become strings, and a "
                "member written with several ``xsi:type`` s becomes a union. Any other data type "
                "is a declared parsing limit: kept as text and listed in ``cda_datatype_limits``. "
                "The section hierarchy (codes, titles, template claims, the statement each entry "
                "holds) is recorded beside the model in ``cda_sections``."
            ),
        ),
        implementation_guide=implementation_guide(
            "CDA R2 document structure (POCD_HD000040)",
            ["C-CDA R2.1", "any other implementation guide's templates", "the CDA R2 schema", "terminology bindings"],
            ["each templateId"],
        ),
        notes=[
            "Template ids are recorded as asserted conformance claims (``cda_template_claims``, "
            "each ``validated: false``). " + TEMPLATE_CLAIM_STATEMENT,
            "A template id the importer does not recognise imports like any other; a recognised "
            "one gains its C-CDA R2.1 name and nothing more.",
            "CDA R2 documents are read (``typeId`` POCD_HD000040). The header must carry id, code, "
            "effectiveTime, recordTarget, author, custodian and a body component, and every "
            "narrative ``reference`` (``#anchor``) must resolve to an ``ID`` in the document; "
            "nothing else is checked against the CDA schema or any implementation guide, and codes "
            "are recorded as written, never looked up in a terminology.",
            "An HL7 v3 transmission wrapper (for example ``MCCI_IN000002UV01``) is read as the root "
            "of an archive: its payload reference names the member holding the CDA document, and "
            "the wrapper is recorded in ``cda_transmission``. A wrapper uploaded alone is refused.",
        ],
    ),
    # FMT-6.9 (#5453) / FMT-6.10 (#5454): FIX Orchestra, seeded so the panel says the repository is
    # read as declared — the specification itself, never checked against a base repository or the
    # rules of engagement it may restate — and what presence becomes on the canonical model.
    "fix-orchestra": _Seed(
        # The payload analysis is still the format-blind walk, so the first three fields restate
        # what derivation produces. The reviewed judgements are the projection, the guide
        # statement and the notes.
        native_hierarchy=NativeHierarchy.GENERIC,
        native_hierarchy_note=(
            "The format-blind walk records containers, ordered collections and leaves. Nesting "
            "and ordering survive; this format's own semantics are not named, and their absence "
            "from the tree says nothing about the source."
        ),
        source_location=SourceLocationSupport(
            quality=SourceLocationQuality.PATH_ONLY,
            note=(
                "Elements locate by structural path and sibling ordinal only "
                "(``repository/messages/message[2]/structure``). The hardened XML reader exposes "
                "no positions."
            ),
        ),
        value_visibility=ValueVisibilitySupport(
            default=ValueVisibility.DEFAULT,
            maximum=ValueVisibility.FULL,
            note=(
                "A repository is a specification, not trade data: its leaf values are names, tags, "
                "code values and rule expressions. They are still governed by the value-visibility "
                "policy — the default keeps only presence and length."
            ),
        ),
        canonical_projection=CanonicalProjectionSupport(
            coverage=ProjectionCoverage.PARTIAL,
            dropped_constructs=[
                "fix-orchestra.annotations",
                "fix-orchestra.unused_fields",
            ],
            note=(
                "Each message (each scenario of it) is a record type with its msgType, flow and "
                "responses; code sets are enums; components are records; groups are lists of "
                "records with their numInGroup counter recorded. Presence maps to optionality, and "
                "conditional, forbidden, ignored and constant refs carry a declared constraint — "
                "no field is dropped for its presence. Actors, flows, state machines and declared "
                "datatypes are recorded beside the model; a field no message, component or group "
                "references is counted, not typed, and documentation beyond a field's own text is "
                "not kept."
            ),
        ),
        implementation_guide=implementation_guide(
            "FIX Orchestra repository structure (datatypes, code sets, fields, components, groups, messages)",
            [
                "the FIX Latest base repository",
                "the FIX session-layer specification",
                "a counterparty's rules-of-engagement documents",
            ],
            ["the FIX version the repository declares"],
        ),
        notes=[
            "The repository is read as declared: a message, field or code it defines is taken as "
            "given, and nothing is compared with the base FIX specification it extends or restricts.",
            "Rule expressions (``when``, ``assign``) in the Orchestra Score DSL are recorded "
            "verbatim and never evaluated, so a conditional field's condition is stated, not "
            "applied.",
            "An ``xi:include`` is resolved only against the other files of the same upload — never "
            "fetched from a URL or read from disk; a single uploaded file that uses one is refused.",
        ],
    ),
    "relaxng": _Seed(
        # RELAX NG's payload analysis is still the format-blind walk, so the first three
        # fields restate what derivation produces. The reviewed judgement is the projection
        # statement below: FMT-4.1's acceptance criterion is that `interleave` and the
        # datatype-library constructs are *declared*, and this is where a reader is told what
        # a RELAX NG grammar loses on its way into the canonical model.
        native_hierarchy=NativeHierarchy.GENERIC,
        native_hierarchy_note=(
            "The format-blind walk records containers, ordered collections and leaves. Nesting "
            "and ordering survive; this format's own semantics are not named, and their absence "
            "from the tree says nothing about the source."
        ),
        source_location=SourceLocationSupport(
            quality=SourceLocationQuality.PATH_ONLY,
            note=(
                "Patterns locate by structural path and sibling ordinal only. The hardened XML "
                "reader exposes no positions, and the compact syntax is read by a separate "
                "tokenizer, so a line number would have to be guessed differently for each of "
                "the two spellings of one grammar."
            ),
        ),
        value_visibility=ValueVisibilitySupport(
            default=ValueVisibility.DEFAULT,
            maximum=ValueVisibility.NONE,
            note=(
                "A grammar is a schema, not data: the analyzer observes no runtime values at any "
                "policy level. 'No value here' is the absence of data to observe, not a "
                "redaction."
            ),
        ),
        canonical_projection=CanonicalProjectionSupport(
            coverage=ProjectionCoverage.PARTIAL,
            dropped_constructs=[
                "relaxng.datatype_except",
                "relaxng.external_datatype_library",
                "relaxng.interleave",
                "relaxng.list",
                "relaxng.mixed",
                "relaxng.name_class_wildcard",
                "relaxng.remote_href",
            ],
            note=(
                "Named patterns become canonical types, `element`/`attribute` patterns become "
                "fields, `choice` becomes a union (or an `enum` constraint when its branches are "
                "literal values), `optional`/`zeroOrMore`/`oneOrMore` become nullability and "
                "lists, and `data` parameters become canonical constraints. Composition is "
                "resolved before normalization, so `include` (with its overrides) and "
                "`externalRef` leave no trace to lose. The listed constructs are *carried but "
                "not fully expressible*: `interleave`'s branches all survive as members and only "
                "their order-independence is lost (each such member is tagged "
                "`relaxng_interleaved`), an `anyName`/`nsName` wildcard becomes a single "
                "open-content member named `*`, a `data` `except` clause keeps the base datatype "
                "and records the exclusion without enforcing it, `list` becomes a list of its "
                "item type without the single-text-node encoding, `mixed` keeps the character "
                "content as an extra member, and a datatype library other than the W3C XML "
                "Schema datatypes is carried verbatim rather than interpreted. Every occurrence "
                "is counted and located in `extras['relaxng']['capability_limits']`."
            ),
        ),
        notes=[
            "The XML syntax (`.rng`) and the compact syntax (`.rnc`) are two spellings of one "
            "language and are read by two front-ends onto one pattern algebra, so the same "
            "grammar written either way produces the same canonical model — the syntax is "
            "deliberately not part of the model, and survives only on the retained raw source.",
            "An `include`/`externalRef` naming an absolute URL is never fetched. Its shape is "
            "vetted against the SSRF policy — a `file:`/`data:` href, or one carrying "
            "credentials, fails the import as an unsafe construct — and a policy-legal http(s) "
            "href is recorded as a declared limit whose definitions are absent, which then "
            "surfaces as an unresolved reference rather than as a silently smaller grammar.",
            "RELAX NG *output* is not implemented (#4134), so a grammar imported here is "
            "exported through another target's emitter and is not written back as RELAX NG.",
        ],
    ),
    "dtd": _Seed(
        # A DTD's payload analysis is the format-blind walk, so the first three fields
        # restate what derivation produces. The reviewed judgement is the projection
        # statement below: FMT-4.2's acceptance criterion is that mixed content is modelled
        # *or* declared a limit **explicitly**, and this is where a reader is told which —
        # both, as it turns out — and what else a DTD loses on its way into the model.
        native_hierarchy=NativeHierarchy.GENERIC,
        native_hierarchy_note=(
            "The format-blind walk records containers, ordered collections and leaves. Nesting "
            "and ordering survive; this format's own semantics are not named, and their absence "
            "from the tree says nothing about the source."
        ),
        source_location=SourceLocationSupport(
            quality=SourceLocationQuality.PATH_ONLY,
            note=(
                "Declarations locate by structural path and sibling ordinal only. A DTD is read "
                "by a scanner over an entity input stack, so a byte offset in the composed text "
                "does not correspond to a position in any file a user uploaded — a declaration "
                "pulled in through a parameter entity lives in a different file from the "
                "reference that pulled it."
            ),
        ),
        value_visibility=ValueVisibilitySupport(
            default=ValueVisibility.DEFAULT,
            maximum=ValueVisibility.NONE,
            note=(
                "A DTD is a schema, not data: the analyzer observes no runtime values at any "
                "policy level. 'No value here' is the absence of data to observe, not a "
                "redaction. An internal subset arrives inside an instance document, and the "
                "instance's content is not read at all."
            ),
        ),
        canonical_projection=CanonicalProjectionSupport(
            coverage=ProjectionCoverage.PARTIAL,
            dropped_constructs=[
                "dtd.any_content",
                "dtd.id_uniqueness",
                "dtd.mixed_content",
                "dtd.orphan_attlist",
                "dtd.remote_system_id",
                "dtd.repeated_group",
                "dtd.tokenized_attribute",
                "dtd.unparsed_entity",
            ],
            note=(
                "Each `<!ELEMENT>` becomes one canonical type — a `(#PCDATA)` element with no "
                "attributes is a `SCALAR`, everything else a `RECORD` — and a name in a content "
                "model becomes a member typed by that element's type, never a copy of it. "
                "Occurrence indicators become nullability and lists (`?` nullable, `*` a "
                "nullable list, `+` a required list), a `choice` becomes a `UNION` referenced by "
                "one member, and an element named twice in one model folds into one member "
                "bounded by `min_items`/`max_items`. `<!ATTLIST>` definitions become members "
                "carrying the XPath `@` sigil, and the whole default vocabulary becomes "
                "canonical constraints: an enumeration and a `#FIXED` value become `enum`, a "
                "bare literal becomes `default`, `#REQUIRED` a non-nullable member and "
                "`#IMPLIED` a nullable one. Entities are expanded before normalization, so "
                "their uses leave no trace to lose, and the declarations are carried in "
                "`extras['dtd']`. The listed constructs are *carried but not fully "
                "expressible*: mixed content keeps its child elements as repeated members "
                "beside a `#text` member and loses only the interleaving, `ANY` becomes one "
                "open-content member, an occurrence indicator on a group distributes onto the "
                "group's members, `IDREFS`/`ENTITIES`/`NMTOKENS` become lists of strings, "
                "`ID`/`IDREF` record their declared type without enforcing uniqueness or "
                "referential integrity, an unparsed entity and its notation are recorded rather "
                "than modelled, an `<!ATTLIST>` for an element that is never declared is "
                "recorded rather than failed, and an absolute system identifier is recorded "
                "rather than fetched. Every occurrence is counted and located in "
                "`extras['dtd']['capability_limits']`."
            ),
        ),
        notes=[
            "A DTD is not XML and is not read by an XML parser: `<!ELEMENT>`/`<!ATTLIST>` are "
            "markup declarations, and the shared hardened XML reader refuses a `DOCTYPE` "
            "outright. The reader is a scanner with its own byte, nesting and entity-expansion "
            "ceilings, and it reads an external subset, an internal subset, and a modular set "
            "composed through parameter entities by the same path.",
            "Entity expansion is bounded in three dimensions at once — how many references are "
            "expanded, how many bytes they produce, and how deep the expansion nests — and "
            "every reference is charged against one budget, so a document cannot move work "
            "between the parameter-entity and general-entity mechanisms to spend past a guard. "
            "An entity that re-enters its own expansion chain is refused as an unsafe "
            "construct rather than unrolled until a budget stops it.",
            "Nothing external is fetched. A relative system identifier resolves against the "
            "uploaded set; an absolute one is vetted against the SSRF policy — a `file:`/`data:` "
            "identifier, or one carrying credentials, fails the import — and a policy-legal "
            "http(s) identifier is recorded as a declared limit whose declarations are absent. "
            "This is the XXE and blind-XXE shape, and it fails closed.",
            "A DTD has no documentation construct: comments are not attached to the "
            "declarations they precede, so imported types and members carry no description and "
            "the absence is the format's, not the reader's.",
            "DTD *output* is not implemented, so a DTD imported here is exported through "
            "another target's emitter and is not written back as a DTD.",
        ],
    ),
    "odcs": _Seed(
        # ODCS's payload analysis is the format-blind walk, so the first three fields
        # restate what derivation produces. The reviewed judgement is the projection
        # statement below: FMT-5.1's acceptance criterion is that the registry declares
        # what is *modelled* and what is *carried but not modelled*, and this is where a
        # reader is told which half of a data contract each of its blocks lands in.
        native_hierarchy=NativeHierarchy.GENERIC,
        native_hierarchy_note=(
            "The format-blind walk records containers, ordered collections and leaves. Nesting "
            "and ordering survive; this format's own semantics are not named, and their absence "
            "from the tree says nothing about the source."
        ),
        source_location=SourceLocationSupport(
            quality=SourceLocationQuality.PATH_ONLY,
            note=(
                "Schema objects and properties locate by name and structural path only. A "
                "contract published across files is composed before normalization — a quality "
                "pack maintained beside the contract is merged into the object it names — so a "
                "rule's position in one member does not identify it inside the composed "
                "contract."
            ),
        ),
        value_visibility=ValueVisibilitySupport(
            default=ValueVisibility.DEFAULT,
            maximum=ValueVisibility.NONE,
            note=(
                "A data contract is a schema, not data: the analyzer observes no runtime values "
                "at any policy level. 'No value here' is the absence of data to observe, not a "
                "redaction. The values a contract *states* — a property's `examples`, an "
                "enumerated `logicalTypeOptions.enum` — are part of the schema and are carried "
                "as constraints and extras."
            ),
        ),
        canonical_projection=CanonicalProjectionSupport(
            coverage=ProjectionCoverage.PARTIAL,
            dropped_constructs=[
                "odcs.authoritative_definition",
                "odcs.classification",
                "odcs.custom_property",
                "odcs.declaration_order",
                "odcs.free_form_object",
                "odcs.key_uniqueness",
                "odcs.partitioning",
                "odcs.physical_type",
                "odcs.price",
                "odcs.quality_rule",
                "odcs.server",
                "odcs.sla_property",
                "odcs.support_channel",
                "odcs.tag",
                "odcs.team_role",
                "odcs.transform_metadata",
            ],
            note=(
                "A data contract has two halves and they land differently. The *structural* "
                "half is modelled: each `schema[]` object becomes one canonical `RECORD`, each "
                "property becomes one member, `required` becomes nullability, a nested `object` "
                "property becomes a synthesized record keyed by its path, an `array` becomes a "
                "list around its `items` type, and `logicalTypeOptions` — the portable half of "
                "ODCS typing — becomes canonical constraints: lengths, numeric bounds, "
                "`pattern`, `enum`, and `format` when the declared value is a format token "
                "rather than a free-form date pattern. Declaration order is recorded in "
                "`odcs_position` because a dataset's column order is physical and canonical "
                "ordering does not follow it. The *governance* "
                "half — the listed constructs — is **carried but not modelled**: quality rules, "
                "`team`/`roles` ownership, `slaProperties`, `servers`, `support`, `price`, "
                "`tags`, `customProperties` and `authoritativeDefinitions` survive verbatim "
                "under the documented `odcs_*` extras namespace, on whichever node declared "
                "them, so nothing is lost and nothing is re-spelled — but no canonical feature "
                "reads them, and none of them is enforced. `physicalType` is deliberately not "
                "interpreted: `varchar(20)` does not become `maxLength: 20`, because the unit "
                "differs by dialect. Every occurrence is counted and located in "
                "`extras['odcs']['capability_limits']`."
            ),
        ),
        notes=[
            "The reader covers the ODCS v3.x line, and only that line. A v2.2.x contract "
            "declares the same `apiVersion`/`kind` pair but spells a dataset as `quantumName` "
            "with `dataset[].columns[]`, so it is claimed by detection and then rejected *by "
            "version*, with the v2 -> v3 renames named in the message — never parsed into an "
            "empty contract.",
            "A contract that describes no structure is refused rather than imported: a "
            "`schema[]` object with no `properties` would produce an empty catalog type, which "
            "reads as 'this dataset has no columns' rather than as 'this document did not say'.",
            "`authoritativeDefinitions` URLs are recorded and **never fetched** during import. "
            "A relative URL naming a member of the same imported file set is additionally "
            "recorded as resolved, but its content is not expanded — a JSON Schema a contract "
            "delegates its payload shape to stays a reference, not a set of canonical types.",
            "Quality rules are carried, never executed and never translated into constraints. A "
            "`sql` rule's query, a `custom` rule's engine block and a `text` rule's prose are "
            "kept exactly as written, which is what lets the emitter write them back unchanged.",
            "ODCS *output* is implemented (FMT-5.2), and it is the one target in the fleet whose "
            "emitted artifacts are checked against the format's **own published JSON Schema**, "
            "shipped with this service and run offline. The governance half is written back from "
            "the `odcs_*` extras verbatim, so a contract imported and re-exported is canonically "
            "identical. The structural half is rebuilt, and the emitter refuses to write a facet "
            "the standard does not admit beside the column's `logicalType` — a non-standard "
            "`enum` type option is dropped and reported rather than written illegally.",
            "Nothing in the governance half is ever invented on export. A contract emitted from a "
            "schema that carries no ownership, SLA or quality metadata is written *without* those "
            "blocks, and their absence is reported as a `SYNTH` finding: a fabricated owner or "
            "service level is a governance claim nobody made. The only values supplied without a "
            "source are `version` and `status`, which the standard requires for a document to "
            "exist at all, and both are reported as fabricated.",
        ],
    ),
    "arrow": _Seed(
        # Arrow's payload analysis is the format-blind walk, so the first three fields restate
        # what derivation produces. The reviewed judgement is the projection statement below:
        # FMT-4.5's acceptance criterion is that nested, dictionary-encoded and decimal types
        # are *modelled or declared limits*, and this is where a reader is told which of the two
        # each one is — and what an Arrow schema's encoding, as distinct from its data, costs on
        # the way into the canonical model.
        native_hierarchy=NativeHierarchy.GENERIC,
        native_hierarchy_note=(
            "The format-blind walk records containers, ordered collections and leaves. Nesting "
            "and ordering survive; this format's own semantics are not named, and their absence "
            "from the tree says nothing about the source."
        ),
        source_location=SourceLocationSupport(
            quality=SourceLocationQuality.NONE,
            note=(
                "An Arrow schema is read from one of three serializations, and two of them are "
                "binary — an IPC Flatbuffer and a Flight reply have no lines to point at. Fields "
                "locate by name and column position only, and they locate the same way in all "
                "three, which is the property that makes the surfaces interchangeable."
            ),
        ),
        value_visibility=ValueVisibilitySupport(
            default=ValueVisibility.DEFAULT,
            maximum=ValueVisibility.NONE,
            note=(
                "An Arrow *schema* is metadata about a table, not the table: the analyzer "
                "observes no column values at any policy level, because the payload imported "
                "carries none. 'No value here' is the absence of data to observe, not a "
                "redaction."
            ),
        ),
        canonical_projection=CanonicalProjectionSupport(
            coverage=ProjectionCoverage.PARTIAL,
            dropped_constructs=[
                "arrow.decimal_width",
                "arrow.dictionary_encoding",
                "arrow.extension_type",
                "arrow.flight_endpoint",
                "arrow.half_precision",
                "arrow.interval",
                "arrow.physical_layout",
                "arrow.temporal_unit",
                "arrow.union_layout",
            ],
            note=(
                "A schema becomes one canonical `RECORD` — the table — with one field per "
                "column, keeping the column's position in `field_number` so a key-sorted model "
                "does not lose it. Nested types are modelled exactly: a `struct` is a `RECORD`, "
                "a `list`/`fixedsizelist` is a list reference (a fixed size additionally bounds "
                "it with `min_items`/`max_items`), a `map` is a `MAP` with both its key and "
                "value types, and a `union` is a `UNION` over its variants. Primitives take the "
                "canonical scalar of their exact width, a `fixedsizebinary` becomes `bytes` "
                "bounded by its byte width, and the temporal types become a formatted `string`. "
                "The listed constructs are *carried but not fully expressible*: a "
                "dictionary-encoded field keeps its value type and records the index type and "
                "ordering, a `decimal` keeps the `decimal` scalar and records its precision, "
                "scale and storage width, an extension type keeps its storage type and records "
                "its name, a `union` records its mode and type codes, an `interval` and a "
                "half-precision float take the nearest canonical type, the large-offset, view "
                "and run-end-encoded variants take their ordinary counterpart, and a Flight "
                "response's endpoints are recorded rather than becoming operations. Every "
                "occurrence is counted and located in `extras['arrow']['capability_limits']`."
            ),
        ),
        notes=[
            "The three surfaces are one reader. The JSON integration form, a binary IPC stream "
            "or file, and a Flight `GetSchema` reply all parse into the same document type "
            "before anything is normalized, so an IPC schema and its JSON twin produce the same "
            "canonical model — the same types, the same keys, the same fingerprint — rather "
            "than two models that resemble each other.",
            "The model's identity is derived from the *document*, never from the filename: a "
            "Flight descriptor's path names the dataset, a `name` in the schema metadata names "
            "it otherwise, and a schema that names itself nothing is called `Schema`. That is "
            "what lets the same table imported from two serializations be one API.",
            "Schema and field metadata are carried verbatim, and the conventional documentation "
            "keys (`description`, `comment`, `doc`) become descriptions. Arrow defines no "
            "documentation construct, so a schema whose columns are undocumented imports "
            "undocumented — the absence is the format's, not the reader's.",
            "A live Flight endpoint is vetted against the SSRF policy before a client is "
            "constructed, and its credentials come from the shared credential vault as call "
            "headers. Nothing else is fetched: a schema names no external references.",
            "Arrow *output* is not implemented here (#4317 files the Parquet/Arrow emitter), so "
            "a schema imported through this adapter is exported through another target's "
            "emitter and is not written back as Arrow.",
        ],
    ),
    "kafka-connect": _Seed(
        # Kafka Connect's payload analysis is the format-blind walk, so the first three
        # fields restate what derivation produces. The reviewed judgement is the
        # projection statement below: FMT-5.3's acceptance criterion is that logical
        # types map to canonical formats and constraints rather than to opaque strings,
        # and this is where a reader is told which names are decoded, what a name this
        # reader does not know still costs, and where a schema's parameters end up.
        native_hierarchy=NativeHierarchy.GENERIC,
        native_hierarchy_note=(
            "The format-blind walk records containers, ordered collections and leaves. Nesting "
            "and ordering survive; this format's own semantics are not named, and their absence "
            "from the tree says nothing about the source."
        ),
        source_location=SourceLocationSupport(
            quality=SourceLocationQuality.PATH_ONLY,
            note=(
                "Structs and fields locate by name and structural path only. A pipeline "
                "published across files is composed before normalization — the connector "
                "configuration and every schema member are read together — so a field's "
                "position inside one member does not identify it inside the composed model."
            ),
        ),
        value_visibility=ValueVisibilitySupport(
            default=ValueVisibility.DEFAULT,
            maximum=ValueVisibility.NONE,
            note=(
                "A Connect schema is metadata about the records a pipeline carries, not the "
                "records: the analyzer observes no runtime values at any policy level. The one "
                "place a *value* appears is the sample record beside an enveloped schema, and "
                "it is carried verbatim rather than inspected, so nothing is inferred from it."
            ),
        ),
        canonical_projection=CanonicalProjectionSupport(
            coverage=ProjectionCoverage.PARTIAL,
            dropped_constructs=[
                "kafka-connect.anonymous_struct",
                "kafka-connect.connector_config",
                "kafka-connect.decimal_precision",
                "kafka-connect.envelope_payload",
                "kafka-connect.schema_parameters",
                "kafka-connect.schema_version",
                "kafka-connect.unknown_logical_type",
            ],
            note=(
                "Each `struct` becomes one canonical `RECORD` keyed by its schema `name`, each "
                "member becomes one field keyed by its `field` name, `optional` becomes "
                "nullability, `default` becomes the field's default, an `array` becomes a list "
                "reference and a `map` becomes a canonical `MAP` carrying both its key and "
                "value types. Declaration order is kept in `field_number` because a key-sorted "
                "model would otherwise lose it, and two members that name the same struct share "
                "one canonical type — which is what makes a change-event envelope's "
                "`before`/`after` pair one record rather than two. Primitives take the "
                "canonical scalar of their exact declared width, so `int8` stays `int8`. A "
                "**logical type** — Connect's semantic layer, spelled as a `name` on a "
                "non-struct schema — becomes a canonical constraint and never an opaque string: "
                "`Date`, `Time` and `Timestamp` (and the Debezium `MicroTimestamp` / "
                "`ZonedTimestamp` a change-data pipeline carries) become a formatted `string`, "
                "`Decimal` becomes `format: decimal`, and `io.debezium.data.Enum` becomes an "
                "`enum` constraint from its `allowed` parameter. The listed constructs are "
                "*carried but not modelled*: a name this reader does not decode keeps its base "
                "type and is carried verbatim, a `Decimal`'s digits have no canonical facet, "
                "the per-schema registry `version`, the free-form `parameters` map, an "
                "enveloped sample record and a connector configuration all survive under the "
                "documented `connect_*` extras namespace. Every occurrence is counted and "
                "located in `extras['kafka_connect']['capability_limits']`."
            ),
        ),
        notes=[
            "Connect's schema form is neither Avro nor JSON Schema, and telling it from Avro is "
            "the reader's first job: Connect names a struct member with `field`, Avro with "
            "`name`. An Avro schema routed to this adapter is refused without a taxonomy code "
            "so the pipeline reports it as a wrong-format upload on the strength of the Avro "
            "adapter claiming it, rather than as a malformed Connect document.",
            "A logical type this reader does not decode is still recognized *as* a logical "
            "type. The field keeps its base type's canonical scalar and the name is carried "
            "verbatim, so a connector-specific semantic is never silently reduced to its wire "
            "representation — what is lost is the canonical constraint the name would imply, "
            "and that loss is counted.",
            "A connector configuration is operational, not structural. It states how a pipeline "
            "runs — `connector.class`, converters, transforms, sink settings — and is carried "
            "verbatim; the key and value schemas beside it in the file set are what becomes "
            "structure. Imported on its own it is refused, because it describes no record.",
            "Kafka Connect *output* is implemented (FMT-5.3). The Connect spellings the reader "
            "carried are written back verbatim — an `int8` returns as `int8` and a logical type "
            "returns with its parameters — so a schema imported and re-exported is canonically "
            "identical. A model from any other format is projected instead: its canonical "
            "scalars pick Connect primitives, a canonical `format` picks a bundled logical type "
            "where Connect has one, and what Connect cannot carry is reported as a loss.",
            "Connect validates nothing — a schema states a type, not a value range — so every "
            "canonical constraint other than the two a logical type implies is dropped on "
            "export and reported. Connect also has no union and no enumeration type, and this "
            "emitter does not invent a connector-specific logical type to fake one.",
        ],
    ),
    "dbt": _Seed(
        # dbt's payload analysis is the format-blind walk, so the first three fields
        # restate what derivation produces. The reviewed judgement is the projection
        # statement below: FMT-5.4's acceptance criterion is that dbt tests land on
        # constraints or on the shared quality namespace, and this is where a reader is
        # told which of a project's constructs goes where.
        native_hierarchy=NativeHierarchy.GENERIC,
        native_hierarchy_note=(
            "The format-blind walk records containers, ordered collections and leaves. Nesting "
            "and ordering survive; this format's own semantics are not named, and their absence "
            "from the tree says nothing about the source."
        ),
        source_location=SourceLocationSupport(
            quality=SourceLocationQuality.PATH_ONLY,
            note=(
                "Resources and columns locate by name and structural path only. A project "
                "imported as a file set is composed before normalization — several properties "
                "files contribute to one namespace, and each model's SQL contributes its "
                "`ref()` lineage — so a column's position in one member does not identify it "
                "inside the composed project. A compiled manifest hoists every test into a "
                "node of its own, and re-attaching it to the column it constrains loses the "
                "test node's own coordinates."
            ),
        ),
        value_visibility=ValueVisibilitySupport(
            default=ValueVisibility.DEFAULT,
            maximum=ValueVisibility.NONE,
            note=(
                "A dbt project describes a warehouse, it does not contain one: the analyzer "
                "observes no runtime values at any policy level. 'No value here' is the absence "
                "of data to observe, not a redaction. The values a project *states* — an "
                "`accepted_values` test's `values` list — are part of the schema and become "
                "constraints."
            ),
        ),
        canonical_projection=CanonicalProjectionSupport(
            coverage=ProjectionCoverage.PARTIAL,
            dropped_constructs=[
                "dbt.check_constraint",
                "dbt.data_test",
                "dbt.data_type",
                "dbt.declaration_order",
                "dbt.exposure",
                "dbt.freshness",
                "dbt.lineage_relationship",
                "dbt.manifest_graph",
                "dbt.materialization",
                "dbt.meta",
                "dbt.metric",
                "dbt.model_lineage",
                "dbt.model_version",
                "dbt.project_config",
                "dbt.relation_name",
                "dbt.semantic_layer",
                "dbt.tag",
                "dbt.undocumented_columns",
                "dbt.uniqueness",
                "dbt.unresolved_lineage",
            ],
            note=(
                "Every dbt resource that describes data is modelled: a model, a source table, "
                "a seed, a snapshot and a semantic model each become one canonical `RECORD`, "
                "and each column becomes one member. A column's `data_type` is projected onto "
                "a canonical scalar **by its base name only** — `varchar(20)` becomes a "
                "string, not a string of length 20, because the unit of that 20 differs by "
                "dialect and by encoding — and the declared spelling is carried. Where a dbt "
                "*test* lands is the projection's real decision: `not_null` becomes "
                "nullability and `accepted_values` becomes an `enum`, because the canonical "
                "model has those facets; `unique` and `relationships` are carried on the field, "
                "because it has no identity facet and no edge vocabulary; and every other test "
                "— a package test, a singular test, a generic test this reader does not decode "
                "— is projected into the **shared quality namespace FMT-5.1 defined** "
                "(`extras['odcs_quality']`), in the ODCS `type: custom` rule shape with "
                "`engine: dbt`. A dbt project and an ODCS contract describing the same table "
                "therefore put their expectations in the same place, in the same shape. "
                "Everything else the listed constructs name — build configuration, physical "
                "relation names, freshness windows, `meta`, `tags`, model versions, exposures, "
                "metrics, the semantic layer's aggregation vocabulary, the manifest's build "
                "graph — is **carried but not modelled** under the documented `dbt_*` extras "
                "namespace, on whichever node declared it. Every occurrence is counted and "
                "located in `extras['dbt']['capability_limits']`."
            ),
        ),
        notes=[
            "Both of dbt's descriptions of a project read into one model: a hand-written "
            "`schema.yml` properties file and the `manifest.json` dbt compiles from it. A "
            "manifest hoists every test into a node of its own, and this reader re-attaches "
            "each one to the column it constrains, so the two surfaces produce comparable "
            "canonical models rather than two shapes.",
            "A dbt project is a directory, so a file set is the format's ordinary shape rather "
            "than an include mechanism: `dbt_project.yml` names the project, every properties "
            "file contributes to one resource namespace, and each model's `.sql` contributes "
            "the `ref()`/`source()` calls in it as that model's lineage. The SQL is read for "
            "those calls only — it is never compiled, executed, or otherwise interpreted.",
            "Lineage is recorded, not traversed. A `relationships` test and a `foreign_key` "
            "constraint are the two edges this reader writes down, so one that names a model "
            "the import does not contain is refused as `INPUT_REFERENCE_UNRESOLVED` rather "
            "than silently dropped. Every other `ref()` — a semantic model's `model:`, an "
            "exposure's `depends_on`, a call in a member's SQL — is recorded as unresolved "
            "and carried, because an import is one file or one file set and a project's "
            "upstream commonly lives outside it.",
            "A project that describes no data is refused rather than imported: a properties "
            "file with a `version: 2` marker and no models, sources, seeds, snapshots or "
            "semantic models would produce an empty catalog entry, which reads as 'this "
            "project has no tables' rather than as 'this document did not say'.",
            "dbt *output* is not implemented, and is not planned. dbt owns its own project "
            "files, they are under version control, and writing one back would put a second "
            "author on a directory that already has one. A project imported here is exported "
            "through another target's emitter.",
        ],
    ),
    "sql-ddl": _Seed(
        # SQL DDL's payload analysis is the format-blind walk, so the first three fields
        # restate what derivation produces. The reviewed judgement is the projection
        # statement below: FMT-5.6's acceptance criterion is that vendor constructs which
        # cannot be modelled are *declared parsing limits*, and this is where a reader is
        # told which of a script's constructs is modelled, which is carried, and why.
        native_hierarchy=NativeHierarchy.GENERIC,
        native_hierarchy_note=(
            "The format-blind walk records containers, ordered collections and leaves. Nesting "
            "and ordering survive; this format's own semantics are not named, and their absence "
            "from the tree says nothing about the source."
        ),
        source_location=SourceLocationSupport(
            quality=SourceLocationQuality.PATH_ONLY,
            note=(
                "Tables and columns locate by name and structural path only. A script is read "
                "as a *sequence of edits* and the model is the state they leave behind, so a "
                "column that a later `ALTER TABLE` renamed, widened or constrained no longer "
                "corresponds to any single span of the source. A migrations directory makes "
                "that explicit: the shape imported is in none of its files."
            ),
        ),
        value_visibility=ValueVisibilitySupport(
            default=ValueVisibility.DEFAULT,
            maximum=ValueVisibility.NONE,
            note=(
                "A DDL script describes a database, it does not contain one: the analyzer "
                "observes no rows at any policy level. 'No value here' is the absence of data "
                "to observe, not a redaction. The values a script *states* — a `DEFAULT` "
                "literal, an `ENUM`'s members, a `CHECK … IN (…)` list — are part of the "
                "schema and become defaults and constraints."
            ),
        ),
        canonical_projection=CanonicalProjectionSupport(
            coverage=ProjectionCoverage.PARTIAL,
            dropped_constructs=[
                "sql.check_constraint",
                "sql.collation",
                "sql.column_clause",
                "sql.computed_column",
                "sql.default_expression",
                "sql.foreign_key",
                "sql.identity",
                "sql.index",
                "sql.length_semantics",
                "sql.partitioning",
                "sql.schema_definition",
                "sql.sequence",
                "sql.set_type",
                "sql.storage_clause",
                "sql.table_inheritance",
                "sql.type_parameters",
                "sql.uniqueness",
                "sql.unsupported_statement",
                "sql.vendor_type",
                "sql.view_definition",
                "sql.view_derived_column",
            ],
            note=(
                "Every relation that has rows is modelled: a table and a view each become one "
                "canonical `RECORD`, and each column becomes one member. A view is modelled "
                "because it has a shape — its `SELECT` is read only far enough to name the "
                "columns it projects, and a column that is a plain reference takes the source "
                "column's type. A schema's own vocabulary survives as named types: `CREATE TYPE "
                "… AS ENUM` becomes an `ENUM`, `CREATE DOMAIN` an `ALIAS` with its constraints, "
                "and a composite `CREATE TYPE` a `RECORD`, so a column declared with one "
                "references it rather than flattening to a string. A column's type is projected "
                "from its **base name** through one dialect-agnostic table; a character "
                "length does become `maxLength`, because the dialect has been resolved and the "
                "unit is then unambiguous — except under Oracle, where `VARCHAR2(40)` is forty "
                "bytes or forty characters depending on a session setting the script does not "
                "state. `NOT NULL`, a primary key's columns, a literal `DEFAULT`, an inline "
                "`ENUM` and a `CHECK … IN (…)` list all have exact canonical facets and are "
                "modelled. Everything the listed constructs name — identity declarations, "
                "computed columns, `CHECK` predicates, indexes, partitioning, storage clauses, "
                "inheritance links, sequences and the statements this reader does not model — "
                "is **carried but not modelled** under the documented `sql_*` extras namespace, "
                "on whichever node declared it, and counted and located in "
                "`extras['sql_ddl']['capability_limits']`."
            ),
        ),
        notes=[
            "A DDL script is a sequence of *edits*, and the import is the state they leave "
            "behind. `CREATE TABLE` introduces a relation, `ALTER TABLE` changes one, `DROP` "
            "removes one, and a migrations directory is simply more of the same statements in "
            "later files, applied in path order. That is why a migrations set imports as its "
            "final state rather than its first, and why the same code path reads one script "
            "with `ALTER` statements in it.",
            "The dialect is detected from the script's own markers — backticks and "
            "`AUTO_INCREMENT` for MySQL, a bare `GO` and `IDENTITY(1,1)` for SQL Server, "
            "`VARCHAR2` and `NOCACHE` for Oracle, `timestamptz` and `INHERITS` for PostgreSQL "
            "— and is recorded in provenance with the markers that decided it. A script with no "
            "vendor marker is read as ANSI, which is a verdict rather than a guess. The "
            "`sql_dialect` import option forces one, for the cases a user can see and a "
            "marker cannot.",
            "Live introspection against a connection string is **out of scope and not "
            "planned**. An import is a file or a file set; no driver is loaded and no socket "
            "is opened. That keeps the security surface of 'read my schema' to the surface of "
            "'read my file'.",
            "A foreign key is an edge this reader writes down, so one that names a table the "
            "import does not contain is refused as `INPUT_REFERENCE_UNRESOLVED` rather than "
            "silently dropped — the same rule FMT-5.4 applies to a dangling `relationships` "
            "test. Import the whole schema dump or the whole migrations directory so the "
            "referenced table is present.",
            "A script in which *nothing* has a shape — every `CREATE TABLE` has an empty "
            "column list, or there is no relation at all — is refused rather than imported: "
            "it would produce a catalog entry that reads as 'this database has no tables' "
            "rather than as 'this document did not say'. A single column-less table beside "
            "real ones is kept as an empty record, because PostgreSQL allows "
            "`CREATE TABLE t ()` and the script did declare the relation.",
            "SQL DDL *output* is filed separately as #4311. This adapter is the import half "
            "only, and the two share one type-mapping table (`app.sql_ddl_dialects."
            "SQL_TYPE_SCALARS`) so a round trip cannot disagree with itself about what a "
            "`VARCHAR` is.",
        ],
    ),
    "opcua-nodeset": _Seed(
        # FMT-9.1: a native analyzer describes the whole nodeset — address-space instances and the
        # reference graph included — while the canonical model holds the types and methods.
        native_hierarchy=NativeHierarchy.NATIVE,
        native_hierarchy_note=(
            "nodeset → namespaces · models · aliases · one group per node class → node (nodeId, "
            "browseName, role) → definition fields and references. Every node carries a role: "
            "type, a type's instance declaration, a method signature, or an address-space "
            "instance. References are the bottom level, so a model larger than the budget keeps "
            "every node and drops references first."
        ),
        source_location=SourceLocationSupport(
            quality=SourceLocationQuality.LINE_NUMBERS,
            note=(
                "Each node element is located by the line it opens on and addressed by its "
                "NodeId; a fileset member's nodes also name the member they came from."
            ),
        ),
        value_visibility=ValueVisibilitySupport(
            default=ValueVisibility.DEFAULT,
            maximum=ValueVisibility.NONE,
            note=(
                "A nodeset describes an information model; variable values in it are defaults and "
                "sample data, and the analyzer never reads them."
            ),
        ),
        canonical_projection=CanonicalProjectionSupport(
            coverage=ProjectionCoverage.PARTIAL,
            dropped_constructs=sorted(
                [
                    "opcua.access_levels",
                    "opcua.address_space_instances",
                    "opcua.base_type_not_modelled",
                    "opcua.definition_missing",
                    "opcua.multi_dimensional_array",
                    "opcua.option_set",
                    "opcua.union",
                    "opcua.unresolved_reference",
                    "opcua.variable_values",
                ]
            ),
            note=(
                "`UAObjectType` → a `RECORD` of its instance declarations (Mandatory → required, "
                "Optional → nullable, the placeholder rules → lists; a supertype in the file "
                "contributes its fields); `UAVariableType` → an `ALIAS` of its data type; "
                "`UADataType` → `RECORD` (structure), `ENUM` (enumeration or OptionSet bits) or "
                "`ALIAS` (a subtype of a scalar); `UAMethod` → an RPC operation whose arguments "
                "become synthesized request / response records. `ValueRank` and `ArrayDimensions` "
                "become lists and `maxItems`; built-in types become scalars with a `format`. Each "
                "type keeps its references, and the namespaces, models and aliases are recorded in "
                "`extras['opcua']`. Address-space instances stay in the analysis. Declared limits "
                "are counted and located in `extras['opcua']['capability_limits']`."
            ),
        ),
        notes=[
            "A fileset — a model and the companion models it requires — is merged, each member's "
            "namespace indexes re-numbered by URI, so a `RequiredModel` shipped beside the model "
            "resolves.",
            "A reference to a missing node in one of the nodeset's own namespaces rejects the "
            "import with `INPUT_REFERENCE_UNRESOLVED`; a reference into another model's namespace "
            "is declared unresolved and the import continues.",
            "OPC UA *output* is not implemented; a NodeSet2 import is exported through another "
            "target's emitter.",
        ],
    ),
    "sparkplug": _Seed(
        # FMT-9.2: a native analyzer describes every payload and metric (values under the policy);
        # the canonical model holds the topics as channels and the metrics as message schemas.
        native_hierarchy=NativeHierarchy.NATIVE,
        native_hierarchy_note=(
            "payload (inferred message type, timestamp, seq, uuid) → metric (name or alias, "
            "datatype, flags) → its property set, metadata, DataSet columns and Template members; "
            "a topic-namespace description → its topics (each parsed into group, message type, "
            "edge node and device) and the metric catalogues of the edge node and each device."
        ),
        source_location=SourceLocationSupport(
            quality=SourceLocationQuality.PATH_ONLY,
            note=(
                "A metric is addressed by its payload and its position among the payload's metrics "
                "(``ddata.bin/Inputs/Temperature``); a fileset member's metrics also name the file "
                "they came from. A protobuf payload has no lines."
            ),
        ),
        value_visibility=ValueVisibilitySupport(
            default=ValueVisibility.DEFAULT,
            maximum=ValueVisibility.FULL,
            note=(
                "Metric values are plant telemetry, so the stored record keeps whatever the "
                "value-visibility policy allows. Names, aliases, datatypes, flags and property-set "
                "entries (engineering units, ranges) describe the metric and are always shown."
            ),
        ),
        canonical_projection=CanonicalProjectionSupport(
            coverage=ProjectionCoverage.PARTIAL,
            dropped_constructs=sorted(
                [
                    "sparkplug.dataset_rows",
                    "sparkplug.metric_values",
                    "sparkplug.payload_body",
                    "sparkplug.unknown_fields",
                ]
            ),
            note=(
                "Each topic → an MQTT `Channel` whose address is the topic, its components (group, "
                "message type, edge node, device, host) in `extras['sparkplug_topic']`; an unknown "
                "component is an address parameter. Each channel gets one operation — `publish` for "
                "BIRTH, DATA and DEATH, `subscribe` for NCMD, DCMD and STATE — whose event message "
                "carries a `RECORD` of metrics. A metric's datatype maps to a canonical scalar "
                "(`Int8`…`UInt64` → `int8`…`uint64`, `Float`/`Double`, `Boolean`, `String`/`Text` → "
                "`string`, `DateTime` → `timestamp`, `UUID`, `Bytes`/`File` → `bytes`), an array to a "
                "list, a DataSet to a list of a synthesized row record and a template instance to its "
                "definition's record; the alias, the Sparkplug datatype, property set, metadata and "
                "flags stay in the field's extras. A payload-only import stamps every construct "
                "`inferred`. Declared limits are counted in `extras['sparkplug']['capability_limits']`."
            ),
        ),
        notes=[
            "A payload does not carry its topic: the message type is inferred from a message-type "
            "token in the file name (`…-ddata.bin`), else from the metrics (a lone `bdSeq` is an "
            "NDEATH, `bdSeq` among named metrics an NBIRTH); the group, edge node and device stay "
            "address parameters.",
            "A DATA payload names its metrics only by alias. Imported beside its BIRTH in a "
            "fileset, the names are resolved; alone, each keeps the placeholder `alias:<n>` and "
            "the coverage ledger says so.",
            "A topic-namespace description whose topics contradict its declared namespace, group, "
            "edge node or host application is refused with `INPUT_SEMANTIC_INVALID`.",
            "Sparkplug *output* is not implemented; an import is exported through another "
            "target's emitter.",
        ],
    ),
    "ros2": _Seed(
        # FMT-9.3: interface files are schema text, read by the format-blind walk; the reviewed
        # judgement is the projection statement — messages to records, services to request/response
        # operations, actions to a goal operation plus a feedback channel.
        native_hierarchy=NativeHierarchy.GENERIC,
        native_hierarchy_note=(
            "The format-blind walk records containers, ordered collections and leaves. Nesting "
            "and ordering survive; this format's own semantics are not named, and their absence "
            "from the tree says nothing about the source."
        ),
        source_location=SourceLocationSupport(
            quality=SourceLocationQuality.NONE,
            note=(
                "A type is located by its package and interface name (`nav2_msgs.NavigateToPose_Goal`) "
                "and the file it came from is kept in `extras['ros2_interface']`; field lines are "
                "not carried as source positions."
            ),
        ),
        value_visibility=ValueVisibilitySupport(
            default=ValueVisibility.DEFAULT,
            maximum=ValueVisibility.NONE,
            note=(
                "An interface file describes data without containing any: constants and field "
                "defaults are part of the schema and are modelled."
            ),
        ),
        canonical_projection=CanonicalProjectionSupport(
            coverage=ProjectionCoverage.PARTIAL,
            dropped_constructs=sorted(
                [
                    "ros2.external_reference",
                    "ros2.sibling_reference",
                    "ros2.wide_string",
                ]
            ),
            note=(
                "Each `.msg` → a `RECORD`; each `.srv` → `<Name>_Request` and `<Name>_Response` "
                "records and a `request_response` operation; each `.action` → `<Name>_Goal`, "
                "`<Name>_Result` and `<Name>_Feedback` records, a goal operation (goal → result) and "
                "a `subscribe` operation on the `<Name>/_action/feedback` channel. Constants become "
                "the members of a `<Record>_Constants` `ENUM`. Primitives map to canonical scalars "
                "(`float32`/`float64` → `float`/`double`, `byte`/`char` → `uint8`, `wstring` → "
                "`string`); `T[]`, `T[N]` and `T[<=N]` are lists (`min_items`/`max_items` for a fixed "
                "array, `max_items` for a bounded one); `string<=N` sets `max_length`; defaults are "
                "kept. A reference resolves within the import (a bare name within its package); one "
                "outside it keeps the `any` type with the message named in "
                "`extras['ros2_unresolved']`. Declared limits are counted in "
                "`extras['ros2']['capability_limits']`."
            ),
        ),
        notes=[
            "A package-qualified reference to a package outside the import is kept as a declared "
            "unresolved reference when the package is a standard ROS 2 interface package "
            "(`std_msgs`, `geometry_msgs`, `builtin_interfaces` …) or a dependency `package.xml` "
            "declares; any other package is refused with `INPUT_REFERENCE_UNRESOLVED`.",
            "In a package fileset a bare name must be one of the package's own messages; in a "
            "single uploaded file the package's other files were not supplied, so a bare name is "
            "kept as a declared unresolved sibling reference.",
            "A `.srv` with one section or an `.action` with fewer than three is refused as "
            "`INPUT_TRUNCATED`; an interface with no fields and no constants as "
            "`INPUT_SEMANTIC_INVALID`.",
            "ROS 2 interface *output* is not implemented; an import is exported through another "
            "target's emitter.",
        ],
    ),
    "pydantic": _Seed(
        # Pydantic's payload analysis is the format-blind walk; the reviewed judgement is the
        # projection statement. FMT-8.4's acceptance criteria are that models import by *static*
        # analysis with no user module executed, that `Field` constraints become canonical
        # constraints, and that dynamic construction is a declared parsing limit.
        native_hierarchy=NativeHierarchy.GENERIC,
        native_hierarchy_note=(
            "The format-blind walk records containers, ordered collections and leaves. Nesting "
            "and ordering survive; this format's own semantics are not named, and their absence "
            "from the tree says nothing about the source."
        ),
        source_location=SourceLocationSupport(
            quality=SourceLocationQuality.NONE,
            note=(
                "Models are located by class and field name (`Order`, `Order.lines`); a field "
                "inherited from a base or a generic is modelled on the class that uses it, so a "
                "single source line would mislead."
            ),
        ),
        value_visibility=ValueVisibilitySupport(
            default=ValueVisibility.DEFAULT,
            maximum=ValueVisibility.NONE,
            note=(
                "A module of models describes data without containing any: defaults, literals "
                "and enum members are part of the schema and are modelled; nothing is executed, "
                "so there are no runtime values to observe."
            ),
        ),
        canonical_projection=CanonicalProjectionSupport(
            coverage=ProjectionCoverage.PARTIAL,
            dropped_constructs=sorted(
                [
                    "pydantic.alias_generator",
                    "pydantic.class_hook",
                    "pydantic.computed_field",
                    "pydantic.decimal_precision",
                    "pydantic.dynamic_model",
                    "pydantic.tuple_positions",
                    "pydantic.unknown_type",
                    "pydantic.unmodelled_reference",
                    "pydantic.unrepresentable",
                    "pydantic.unresolved_annotation",
                    "pydantic.unresolved_generic",
                    "pydantic.validator",
                ]
            ),
            note=(
                "The source is read with Python's `ast` and never imported or executed. Every "
                "`BaseModel` subclass the root module defines or re-exports becomes a `RECORD` "
                "(inheritance flattened in pydantic's field order; a generic model instantiated "
                "by subclassing — `class OrderPage(Page[Order])` — is concrete); `Enum` "
                "subclasses and `Literal[...]` are `ENUM`s; `Union` / `X | Y` is a `UNION` (named "
                "models referenced by key) and `Optional` / `| None` makes the reference "
                "nullable; `list` / `set` / `tuple` / `dict` are lists and maps; nested and "
                "self-referencing models point at their record. `Field(gt/ge/lt/le/multiple_of/"
                "min_length/max_length/pattern)` and `Annotated[..., StringConstraints(...)]` "
                "become canonical constraints (a length on a collection is an item count); "
                "`datetime` / `date` / `UUID` / `EmailStr` / `AnyUrl` and kin become formats; "
                "defaults (literals and enum members), descriptions and `deprecated` are kept; "
                "`Field(alias=…)` and `alias_generator=to_camel` name the field as it appears on "
                "the wire. The listed constructs are declared: `create_model` and model "
                "factories, validators, computed fields, class-creation hooks, annotations and "
                "types the reader cannot resolve statically, and decimal precision. Each "
                "occurrence is counted and located in `extras['pydantic']['capability_limits']`."
            ),
        ),
        notes=[
            "No user module is executed: importing arbitrary Python is an unacceptable risk in a "
            "multi-tenant service, so the reader parses the source and resolves names, imports "
            "between the upload's modules, aliases and generics without running anything.",
            "A name used in an annotation that neither the upload nor the standard library and "
            "pydantic define — an import from a module that was not included — rejects the "
            "import with `INPUT_REFERENCE_UNRESOLVED` rather than being modelled as `Any`.",
            "Pydantic *output* is not implemented here, so models imported through this adapter "
            "are exported through another target's emitter and are not written back as Python.",
        ],
    ),
    "cue": _Seed(
        # CUE's payload analysis is the format-blind walk; the reviewed judgement is the projection
        # statement. FMT-8.5's acceptance criteria are that CUE imports through its own export tool
        # inside the sandbox and that constraints beyond JSON Schema are declared limits.
        native_hierarchy=NativeHierarchy.GENERIC,
        native_hierarchy_note=(
            "The format-blind walk records containers, ordered collections and leaves. Nesting "
            "and ordering survive; this format's own semantics are not named, and their absence "
            "from the tree says nothing about the source."
        ),
        source_location=SourceLocationSupport(
            quality=SourceLocationQuality.NONE,
            note=(
                "Definitions are located by name (`#Order`, `Order.lines`). The JSON Schema CUE's "
                "generator writes carries no positions, and a field reached by embedding or "
                "unification is modelled on the definition that uses it."
            ),
        ),
        value_visibility=ValueVisibilitySupport(
            default=ValueVisibility.DEFAULT,
            maximum=ValueVisibility.NONE,
            note=(
                "Definitions describe data; the concrete values a file also defines are validated "
                "by `cue export` and listed by name in `extras['cue']['instances']`, not modelled as "
                "types."
            ),
        ),
        canonical_projection=CanonicalProjectionSupport(
            coverage=ProjectionCoverage.PARTIAL,
            dropped_constructs=[
                "cue.additional_properties",
                "cue.builtin_validator",
                "cue.bytes",
                "cue.comprehension",
                "cue.conditional_field",
                "cue.default",
                "cue.hidden_field",
                "cue.interpolation",
                "cue.intersection",
                "cue.label_reference",
                "cue.let_binding",
                "cue.tuple_positions",
                "cue.unmodelled_reference",
                "cue.unrepresentable",
            ],
            note=(
                "The bundled `cue` evaluates the upload (`cue export`, which rejects a conflict, an "
                "incomplete value or a syntax error with CUE's own reason) and its JSON Schema "
                "generator projects every `#Definition` of the root package, and of an imported "
                "package a definition refers to. A struct definition is a closed `RECORD` (an "
                "optional `?:` field is nullable); embedding and unification (`#Narrowed: #Scalars "
                "& {…}`) become one record that extends its base; a disjunction of literals is an "
                "`ENUM` and any other disjunction a `UNION`; a pattern constraint "
                "(`[string]: int`) is a `MAP`; lists are lists. Bounds (`>=0`, `<=9999`), regular "
                "expressions (`=~`), `int`, and the rune and item-count validators become "
                "canonical constraints. The listed constructs are declared, never approximated: "
                "comprehensions and interpolations leave their field out; conditional fields, "
                "`let` bindings, hidden fields, defaults, other standard-library validators, "
                "`bytes` and label references are recorded on what they touch. Every occurrence is "
                "counted and located in `extras['cue']['capability_limits']`."
            ),
        ),
        notes=[
            "Evaluation runs in the sandboxed toolchain runner with network isolation forced on and "
            "strict, a private home and cache, and a time limit; an evaluation that does not finish fails "
            "the import with `INPUT_TIME_LIMIT`.",
            "A CUE module may be uploaded as a directory (`cue.mod/module.cue`, one directory per package) "
            "or flat (a `cue.mod` file beside the package files); a flat upload is laid out as the module "
            "CUE expects before it is evaluated.",
            "CUE *output* is not implemented here, so definitions imported through this adapter are "
            "exported through another target's emitter.",
        ],
    ),
    "pkl": _Seed(
        # Pkl's payload analysis is the format-blind walk; the reviewed judgement is the projection
        # statement. FMT-8.5's acceptance criteria are that Pkl imports through its own evaluator
        # inside the sandbox and that constraints beyond JSON Schema are declared limits.
        native_hierarchy=NativeHierarchy.GENERIC,
        native_hierarchy_note=(
            "The format-blind walk records containers, ordered collections and leaves. Nesting "
            "and ordering survive; this format's own semantics are not named, and their absence "
            "from the tree says nothing about the source."
        ),
        source_location=SourceLocationSupport(
            quality=SourceLocationQuality.NONE,
            note=(
                "Classes and type aliases are located by name (`Order`, `Order.lines`); an "
                "inherited property is modelled on the class that declares it and reached through "
                "the subclass's base."
            ),
        ),
        value_visibility=ValueVisibilitySupport(
            default=ValueVisibility.DEFAULT,
            maximum=ValueVisibility.NONE,
            note=(
                "A module of classes describes data; module-level values that evaluate are "
                "validated (a value that breaks its own type's constraint rejects the import) and "
                "listed by name in `extras['pkl']['instances']`; defaults that evaluate to a "
                "single value are field defaults."
            ),
        ),
        canonical_projection=CanonicalProjectionSupport(
            coverage=ProjectionCoverage.PARTIAL,
            dropped_constructs=[
                "pkl.additional_properties",
                "pkl.computed_default",
                "pkl.external_read",
                "pkl.generator",
                "pkl.intersection",
                "pkl.late_binding",
                "pkl.method",
                "pkl.non_string_key",
                "pkl.output",
                "pkl.tuple_positions",
                "pkl.type_constraint",
                "pkl.unit_type",
                "pkl.unmodelled_reference",
                "pkl.unrepresentable",
            ],
            note=(
                "The bundled `pkl eval` runs a reflection program over the upload: `pkl:reflect` "
                "resolves every class, type alias, import and superclass, and each property's "
                "default is evaluated. A class is a closed `RECORD` that extends its superclass; a "
                "union of string literals is an `ENUM` and any other union a `UNION`; `T?` is "
                "nullable; `Listing`/`List` and `Set` are lists, `Mapping`/`Map` are `MAP`s; a type "
                "alias of a constrained type is an `ALIAS` with constraints; a template module's own "
                "properties (`id: String` with no value) are a record named after the module. "
                "Constraints are read from the annotation the source declares: "
                "`isBetween`, `isPositive`, `isNonNegative`, `this <op> n`, `length` comparisons, "
                "`!isEmpty`, `isDistinct`, `matches(Regex(…))`, `startsWith` and `endsWith` become "
                "canonical constraints, and `Int8`…`UInt` their bounds. The listed constructs are "
                "declared: any other predicate, late binding, computed and generated defaults, "
                "refused resource reads, `output` blocks, methods, `Duration`/`DataSize` and "
                "non-string map keys. Every occurrence is counted and located in "
                "`extras['pkl']['capability_limits']`."
            ),
        ),
        notes=[
            "Evaluation is locked down: modules load only from the upload and Pkl's standard library, no "
            "resource may be read (`read(\"env:…\")` is refused and declared), there is no network, and a "
            "time limit stops an evaluation that does not finish.",
            "A module that imports a module the upload does not contain is rejected with "
            "`INPUT_REFERENCE_UNRESOLVED`, naming the module.",
            "Pkl *output* is not implemented here, so classes imported through this adapter are exported "
            "through another target's emitter.",
        ],
    ),
    "dhall": _Seed(
        # Dhall's payload analysis is the format-blind walk; the reviewed judgement is the
        # projection statement. FMT-8.5's acceptance criteria are that Dhall imports through its own
        # tooling inside the sandbox and that constraints beyond JSON Schema are declared limits.
        native_hierarchy=NativeHierarchy.GENERIC,
        native_hierarchy_note=(
            "The format-blind walk records containers, ordered collections and leaves. Nesting "
            "and ordering survive; this format's own semantics are not named, and their absence "
            "from the tree says nothing about the source."
        ),
        source_location=SourceLocationSupport(
            quality=SourceLocationQuality.NONE,
            note=(
                "Types are located by the name the root expression binds them to (`Order`, "
                "`Order.lines`); normalization inlines every `let`, so a source line would point "
                "at a binding that no longer exists."
            ),
        ),
        value_visibility=ValueVisibilitySupport(
            default=ValueVisibility.DEFAULT,
            maximum=ValueVisibility.NONE,
            note=(
                "Type-valued fields are modelled; data-valued fields (a default record, a list of "
                "services) are type-checked by the interpreter and listed by name in "
                "`extras['dhall']['instances']`. A schema record's `default` fields are field "
                "defaults."
            ),
        ),
        canonical_projection=CanonicalProjectionSupport(
            coverage=ProjectionCoverage.PARTIAL,
            dropped_constructs=[
                "dhall.additional_properties",
                "dhall.computed_default",
                "dhall.function",
                "dhall.integrity_check",
                "dhall.intersection",
                "dhall.tuple_positions",
                "dhall.unmodelled_reference",
                "dhall.unrepresentable",
            ],
            note=(
                "The bundled `dhall` resolves the upload's imports, type-checks and normalizes the "
                "root expression, then encodes the normal form as JSON. Each record type is a "
                "closed `RECORD` (an `Optional` field is nullable and not required); each schema "
                "record (`{ Type = …, default = … }`) is the record of its `Type` with its "
                "`default` fields as defaults; a union of empty alternatives is an `ENUM`, and a "
                "union with payloads a `UNION` whose record payloads are named `<Union><Alternative>`; "
                "`List { mapKey, mapValue }` is a `MAP`, as `dhall-to-json` renders it; `Natural` "
                "is an integer with a minimum of 0. A nested type equal to a named one is a "
                "reference to it (Dhall's types are structural, so the match is exact). Functions "
                "(including type-level ones) and integrity-hash pins are declared. Every occurrence "
                "is counted and located in `extras['dhall']['capability_limits']`."
            ),
        ),
        notes=[
            "Imports from URLs, environment variables, absolute or home paths, and relative paths outside "
            "the upload are refused before Dhall runs, with `INPUT_REFERENCE_UNRESOLVED`; the evaluation "
            "has no network and a time limit.",
            "`dhall-to-json` renders values, not types, so the reader projects the types itself from the "
            "encoded normal form, following `dhall-to-json`'s conventions for what a value of each type "
            "looks like in JSON.",
            "Dhall *output* is not implemented here, so types imported through this adapter are exported "
            "through another target's emitter.",
        ],
    ),
    "trpc": _Seed(
        # tRPC's payload analysis is the format-blind walk; the reviewed judgement is the
        # projection statement. FMT-8.3's acceptance criteria are that procedures become operations
        # with the right kinds, nested routers group them, and inputs and outputs resolve through
        # the FMT-8.2 Zod path — this is where a reader is told how, and what is declared.
        native_hierarchy=NativeHierarchy.GENERIC,
        native_hierarchy_note=(
            "The format-blind walk records containers, ordered collections and leaves. Nesting "
            "and ordering survive; this format's own semantics are not named, and their absence "
            "from the tree says nothing about the source."
        ),
        source_location=SourceLocationSupport(
            quality=SourceLocationQuality.NONE,
            note=(
                "A tRPC router is a value built at runtime: procedures are located by their dotted "
                "path (`invoice.list`), the coordinate a tRPC client calls, not by line."
            ),
        ),
        value_visibility=ValueVisibilitySupport(
            default=ValueVisibility.DEFAULT,
            maximum=ValueVisibility.NONE,
            note=(
                "A router describes procedures without calling them: resolvers are never run, so "
                "there are no request or response values for the analyzer to observe."
            ),
        ),
        canonical_projection=CanonicalProjectionSupport(
            coverage=ProjectionCoverage.PARTIAL,
            dropped_constructs=sorted(
                [
                    "trpc.lazy_router",
                    "trpc.non_schema_input",
                    "trpc.non_schema_output",
                    "zod.additional_properties",
                    "zod.brand",
                    "zod.coerce",
                    "zod.custom",
                    "zod.function",
                    "zod.intersection",
                    "zod.pipe",
                    "zod.preprocess",
                    "zod.promise",
                    "zod.refine",
                    "zod.transform",
                    "zod.tuple_positions",
                    "zod.unmodelled_reference",
                    "zod.unnamed_recursion",
                    "zod.unrepresentable",
                ]
            ),
            note=(
                "Every procedure becomes an `rpc` operation keyed by its router path: `.query()` "
                "is a `QUERY`, `.mutation()` a `MUTATION` and `.subscription()` a server-streaming "
                "`SUBSCRIPTION`. Every router node — the exported router and each nested one — is "
                "a service whose `trpc_parent` names the router it sits in, so the hierarchy "
                "survives. A procedure's `.input()` (chained inputs merged, as tRPC merges them) "
                "is its request payload and `.output()` its response payload, both read through "
                "the FMT-8.2 Zod path with their constraints; a payload that is a named schema "
                "references that schema's type, and an inline one becomes a type named after the "
                "procedure (`InvoiceListInput`). `.meta()` is kept in `trpc_meta`. The listed "
                "constructs are declared: a hand-written validator function has no schema, so its "
                "operation is kept without a payload rather than shown with an empty body; a "
                "`lazy()` router's procedures are not known until it is called; and every Zod "
                "limit applies to the schemas inside. Each occurrence is counted and located in "
                "`extras['trpc']['capability_limits']`."
            ),
        ),
        notes=[
            "The router module is evaluated in the same sandbox as Zod import — Node's permission "
            "model, no network, an empty environment and a time budget — with `@trpc/server` and "
            "`zod` as the only packages it can import. Resolvers are never called, so a "
            "procedure's body, the errors it throws and the context its middleware derives are "
            "not read; middleware context can never appear as a request field.",
            "A router whose procedures all validate with hand-written functions and declare no "
            "output schema has nothing to import and is rejected with `INPUT_SEMANTIC_INVALID`.",
            "tRPC *output* is not implemented here, so a router imported through this adapter is "
            "exported through another target's emitter and is not written back as tRPC.",
        ],
    ),
    "zod": _Seed(
        # Zod's payload analysis is the format-blind walk, so the first three fields restate
        # what derivation produces. The reviewed judgement is the projection statement: FMT-8.2's
        # acceptance criteria are that constraints become canonical constraints and that
        # refinements and transforms are *declared limits, not silently dropped* — this is where a
        # reader is told which Zod constructs model and which are declared.
        native_hierarchy=NativeHierarchy.GENERIC,
        native_hierarchy_note=(
            "The format-blind walk records containers, ordered collections and leaves. Nesting "
            "and ordering survive; this format's own semantics are not named, and their absence "
            "from the tree says nothing about the source."
        ),
        source_location=SourceLocationSupport(
            quality=SourceLocationQuality.NONE,
            note=(
                "A Zod schema is a value built at runtime, not a declaration with a line: schemas "
                "are located by the export that holds them (`Order`, `Order.lines`)."
            ),
        ),
        value_visibility=ValueVisibilitySupport(
            default=ValueVisibility.DEFAULT,
            maximum=ValueVisibility.NONE,
            note=(
                "A module of schemas describes data without containing any: literals, enum "
                "members and defaults are part of the schema and are modelled, and there are no "
                "runtime values for the analyzer to observe."
            ),
        ),
        canonical_projection=CanonicalProjectionSupport(
            coverage=ProjectionCoverage.PARTIAL,
            dropped_constructs=[
                "zod.additional_properties",
                "zod.brand",
                "zod.coerce",
                "zod.custom",
                "zod.function",
                "zod.intersection",
                "zod.pipe",
                "zod.preprocess",
                "zod.promise",
                "zod.refine",
                "zod.transform",
                "zod.tuple_positions",
                "zod.unmodelled_reference",
                "zod.unnamed_recursion",
                "zod.unrepresentable",
            ],
            note=(
                "Every exported schema becomes a canonical type, read from Zod's own `_def` tree "
                "by evaluating the module in a permission-locked, network-free, time-bounded "
                "sandbox. `z.object` is a `RECORD`; `z.enum`, `z.nativeEnum` and literal unions "
                "are `ENUM`s; `z.union` and `z.discriminatedUnion` are `UNION`s (inline variants "
                "named by their discriminant); `z.intersection` of objects is one merged "
                "`RECORD`; `z.record` and `z.map` are `MAP`s; arrays, sets and tuples are lists. "
                "Constraints become canonical constraints: `min`/`max`/`length` bound strings and "
                "arrays, `regex`/`startsWith`/`endsWith`/`includes` become a pattern, "
                "`email`/`url`/`uuid`/`datetime`/`date` a format, `int` an integer, and "
                "`gt`/`gte`/`lt`/`lte`/`positive`/`multipleOf` numeric bounds. `optional`, "
                "`nullable` and `nullish` make the reference nullable and `default` is the "
                "field's default. A reference to another exported schema, and `z.lazy` recursion, "
                "point at its named type. The listed constructs are *declared, never dropped "
                "silently*: a `refine`, `transform`, `preprocess`, `brand`, `pipe` or coercion "
                "keeps the schema it wraps and is recorded on it; `z.custom()`, `z.function()`, "
                "`z.promise()` and schemas with no data meaning leave their declaration or member "
                "out of the model. Every occurrence is counted and located in "
                "`extras['zod']['capability_limits']`."
            ),
        ),
        notes=[
            "This reader executes the uploaded module, because a Zod schema only exists once the "
            "code that builds it has run. It runs under Node's permission model (no file outside "
            "the toolchain, no child process, no worker), with no network and an empty "
            "environment, inside a time budget: a module that loops forever, or a `z.lazy` getter "
            "that never returns, fails the import with `INPUT_TIME_LIMIT`.",
            "Only `zod` and the upload's own modules can be imported; any other import rejects "
            "the import with `INPUT_REFERENCE_UNRESOLVED`, and a module that throws while it is "
            "evaluated is rejected with `INPUT_SEMANTIC_INVALID`.",
            "The Zod 3 API (`import { z } from 'zod'`) is evaluated with the bundled Zod 3.25. A "
            "module written against the Zod 4 entry points (`zod/v4`, `zod/mini`) is rejected "
            "with `FORMAT_VERSION_UNSUPPORTED` rather than evaluated against the wrong API.",
            "Schemas share one projection with TypeScript type declarations (FMT-8.1), so a "
            "module modelled from Zod and the same shapes written as TypeScript types produce "
            "the same records, unions and names.",
            "Zod *output* is not implemented here, so a schema imported through this adapter is "
            "exported through another target's emitter and is not written back as Zod.",
        ],
    ),
    "typescript-types": _Seed(
        # TypeScript's payload analysis is the format-blind walk, so the first three fields
        # restate what derivation produces. The reviewed judgement is the projection statement:
        # FMT-8.1's acceptance criterion is that unresolvable generics, conditional and mapped
        # types are *declared parsing limits and never silently flattened to `any`*, and this is
        # where a reader is told which constructs model and which are declared.
        native_hierarchy=NativeHierarchy.GENERIC,
        native_hierarchy_note=(
            "The format-blind walk records containers, ordered collections and leaves. Nesting "
            "and ordering survive; this format's own semantics are not named, and their absence "
            "from the tree says nothing about the source."
        ),
        source_location=SourceLocationSupport(
            quality=SourceLocationQuality.NONE,
            note=(
                "Declarations locate by name (`Order`, `Order.lines`) rather than by line: the "
                "compiler reports positions, but a type reached through a re-export or an "
                "instantiated generic has no single line of its own, so the model does not "
                "pretend one."
            ),
        ),
        value_visibility=ValueVisibilitySupport(
            default=ValueVisibility.DEFAULT,
            maximum=ValueVisibility.NONE,
            note=(
                "A module of type declarations describes data without containing any: literal "
                "types and enum members are part of the schema and are modelled, and there are "
                "no runtime values for the analyzer to observe."
            ),
        ),
        canonical_projection=CanonicalProjectionSupport(
            coverage=ProjectionCoverage.PARTIAL,
            dropped_constructs=[
                "typescript.conditional_type",
                "typescript.declaration_merging",
                "typescript.function_type",
                "typescript.index_signature",
                "typescript.intersection",
                "typescript.lib_type",
                "typescript.mapped_type",
                "typescript.symbol_key",
                "typescript.template_literal_type",
                "typescript.tuple_positions",
                "typescript.type_query",
                "typescript.unmodelled_reference",
                "typescript.unresolved_generic",
            ],
            note=(
                "Every exported `interface`, `type` and `enum` becomes a canonical type. An "
                "interface is a `RECORD` with `extends` flattened (parents first, the child's "
                "members overriding); an object made only of an index signature, `Record<K, V>` "
                "and `Map<K, V>` are `MAP`s; a union of object shapes or named types is a "
                "`UNION` (inline variants named by their discriminant), a union of literals is "
                "an `ENUM`, and an intersection of object shapes is one merged `RECORD`. An "
                "optional member and a `| null` / `| undefined` both make the reference "
                "nullable, with the optional and readonly modifiers kept in extras. `Pick`, "
                "`Omit`, `Partial`, `Required`, `Readonly`, indexed access types and `keyof` "
                "are evaluated by the compiler and model as the shape they produce. Generics are "
                "resolved where they are instantiated: `type OrderPage = Page<Order>` is a "
                "concrete record. The listed constructs are *declared, never guessed*: a "
                "conditional, mapped or template-literal type, a function type, a symbol key, a "
                "`typeof` query, a library type with no data shape, an uninstantiated generic "
                "and a merged interface leave their declaration or member out of the model; a "
                "tuple's positions and an index signature beside named properties are recorded "
                "in extras; an intersection with a non-object member keeps its first member. "
                "Every occurrence is counted and located in "
                "`extras['typescript']['capability_limits']` — none is widened to `any`."
            ),
        ),
        notes=[
            "The module is read by the TypeScript compiler itself (the bundled, version-pinned "
            "`typescript` package), not by a Python approximation of the language: a reference "
            "resolves to the declaration the compiler resolves it to, across `import type` and "
            "re-exports, and a utility type is the shape the compiler computes.",
            "Only what the root module exports defines the model. A non-exported declaration "
            "appears only when an exported type refers to it, and a reference that resolves to "
            "nothing in the upload — an import from a module that was not included — rejects "
            "the import rather than being modelled as `any`.",
            "The model's identity is the root module's first exported interface (else its first "
            "export), never the filename, so a module pasted and the same module uploaded "
            "catalog as one API.",
            "A module that imports a code-first schema library (`zod`, `yup`, `io-ts`, "
            "`valibot`, `@sinclair/typebox`, …) declares its schemas as values this reader cannot "
            "see, and is rejected as a different format rather than imported empty.",
            "TypeScript *output* is not implemented here, so a schema imported through this "
            "adapter is exported through another target's emitter and is not written back as "
            "TypeScript declarations.",
        ],
    ),
    "cddl": _Seed(
        # CDDL's payload analysis is the format-blind walk, so the first three fields
        # restate what derivation produces. The reviewed judgement is the projection
        # statement below: FMT-4.4's acceptance criterion is that control operators map to
        # canonical constraints where an analogue exists and are *declared losses* where
        # none does, and this is where a reader is told which is which — and what sockets,
        # generics and tags cost on the way into the model.
        native_hierarchy=NativeHierarchy.GENERIC,
        native_hierarchy_note=(
            "The format-blind walk records containers, ordered collections and leaves. Nesting "
            "and ordering survive; this format's own semantics are not named, and their absence "
            "from the tree says nothing about the source."
        ),
        source_location=SourceLocationSupport(
            quality=SourceLocationQuality.PATH_ONLY,
            note=(
                "Rules locate by name and structural path only. A grammar split across files "
                "is composed into one namespace before normalization — CDDL has no include "
                "directive, so the set is the unit of import — and a rule's byte offset in one "
                "member does not identify it inside the composed grammar."
            ),
        ),
        value_visibility=ValueVisibilitySupport(
            default=ValueVisibility.DEFAULT,
            maximum=ValueVisibility.NONE,
            note=(
                "A CDDL grammar is a schema, not data: the analyzer observes no runtime values "
                "at any policy level. 'No value here' is the absence of data to observe, not a "
                "redaction. The literal values a grammar states — a member key, a type choice "
                "of strings — are part of the schema and are carried as constraints."
            ),
        ),
        canonical_projection=CanonicalProjectionSupport(
            coverage=ProjectionCoverage.PARTIAL,
            dropped_constructs=[
                "cddl.control_bits",
                "cddl.control_cbor",
                "cddl.control_intersection",
                "cddl.control_unmapped",
                "cddl.control_within",
                "cddl.generic_rule",
                "cddl.group_choice",
                "cddl.group_socket",
                "cddl.major_type",
                "cddl.open_map_entry",
                "cddl.tag",
                "cddl.type_socket",
                "cddl.unwrap",
            ],
            note=(
                "Every type rule becomes one canonical type: a map is a `RECORD` (a `MAP` when "
                "its whole body is a table), an array is a `RECORD` of positional members (an "
                "`ALIAS` to a list when it holds one repeated element), `&( … )` is an `ENUM`, a "
                "choice is a `UNION` (a `SCALAR` carrying `enum` when every branch is a "
                "literal), and everything else is a `SCALAR`. A group rule produces no type — it "
                "exists to be spliced, and every splice site carries its members. Occurrence "
                "indicators become nullability and lists, and an explicit `n*m` additionally "
                "bounds the list with `min_items`/`max_items`. Control operators become "
                "constraints wherever an analogue exists: `.size` becomes lengths (or, on an "
                "integer, the value range that many bytes admit), `.regexp` becomes `pattern`, "
                "`.lt`/`.le`/`.gt`/`.ge` become the numeric bounds, `.eq` becomes a "
                "single-valued `enum`, `.default` becomes the member's default, and `.and` "
                "merges both operands' constraints. The listed constructs are *carried but not "
                "fully expressible*: a CBOR tag and a major-type shorthand keep the type "
                "underneath and record the encoding slot, `~name` types the member by the rule "
                "it unwraps, a table entry beside named members becomes one open-content member "
                "named `*`, a group choice spliced into a larger group carries its first "
                "alternative (a group choice that is a whole map or array body is modelled "
                "exactly, as a union of one record per alternative), a socket is resolved to "
                "the plugs the document supplies and only its open-endedness is lost, a "
                "parameterised rule is instantiated once per use rather than typed in the "
                "abstract, and `.cbor`/`.cborseq`/`.bits`/`.within`/`.ne` are recorded on the "
                "member in `cddl_control` without being enforced. Every occurrence is counted "
                "and located in `extras['cddl']['capability_limits']`."
            ),
        ),
        notes=[
            "CDDL is read *and* written. The reader records each construct's source spelling — "
            "which prelude type a leaf used, a tag, an unmapped control operator, whether a "
            "record came from a map or an array — in `extras`, and the emitter writes every one "
            "of them back, so a grammar imported and re-exported is the grammar that arrived "
            "rather than a re-derivation of it.",
            "Sockets, plugs and generics are *composition*, and are resolved before "
            "normalization: a type socket's `/=` plugs become a choice, a group socket's `//=` "
            "plugs become a group choice, and a generic rule is instantiated once per distinct "
            "argument list. Instantiation is bounded and refuses to re-enter an identical "
            "instantiation, so a self-instantiating generic fails rather than running.",
            "CDDL has no include directive, so a grammar split across files composes as a "
            "*fileset*: the members are loaded together into one namespace. A reference that "
            "resolves in no member fails the import naming the missing rule, rather than being "
            "read as an open type — which would silently produce a smaller grammar than the "
            "author wrote.",
            "The `;` comment is CDDL's only documentation construct and binds to nothing. A "
            "comment block written directly above a rule becomes that rule's description, the "
            "same block separated by a blank line becomes the document's, and a comment sharing "
            "a line with a member becomes that member's. Anything else is left unattached "
            "rather than guessed at.",
        ],
    ),
    "cobolcopybook": _Seed(
        native_hierarchy=NativeHierarchy.NATIVE,
        native_hierarchy_note=(
            "Record → group → field → 88-level condition name, each carrying its level number, "
            "PICTURE, USAGE, OCCURS bounds, and the byte offset and length it occupies within "
            "the record."
        ),
        source_location=SourceLocationSupport(
            quality=SourceLocationQuality.LINE_NUMBERS,
            note=(
                "Every definition carries the 1-based source line it was declared on, recovered "
                "by scanning the copybook and matched in traversal order, so a repeated FILLER "
                "resolves to its own line. A name that cannot be placed carries no line rather "
                "than a guessed one."
            ),
        ),
        value_visibility=ValueVisibilitySupport(
            default=ValueVisibility.DEFAULT,
            maximum=ValueVisibility.NONE,
            note=(
                "A copybook is a record layout, not data: the analyzer observes no runtime "
                "values at any policy level. 'No value here' is the absence of data to observe, "
                "not a redaction."
            ),
        ),
        canonical_projection=CanonicalProjectionSupport(
            coverage=ProjectionCoverage.PARTIAL,
            dropped_constructs=[
                "copybook.computed_storage_length",
                "copybook.condition_names_88",
                "copybook.level_numbers",
                "copybook.occurs_bounds",
                "copybook.occurs_depending_on",
                "copybook.picture_clauses",
                "copybook.redefines",
                "copybook.storage_offsets",
                "copybook.usage_clauses",
            ],
            note=(
                "The canonical model keeps a field's name and inferred type. Everything that "
                "makes a copybook a *layout* — levels, PICTURE, USAGE, OCCURS bounds, "
                "88-conditions, byte offsets, and the fact that two items share one span of "
                "storage — survives only in the analysis. A REDEFINES overlay normalizes to an "
                "ordinary sibling field; representing it as a union is #3991's."
            ),
        ),
        notes=[
            "Byte offsets and lengths are computed from PICTURE and USAGE under assumptions the "
            "copybook does not state — a single-byte encoding, packed decimal at two digits per "
            "byte plus a sign nibble, the common binary width table, an overpunched rather than "
            "separate sign, and no SYNCHRONIZED slack. Every record names them, so a length is "
            "read as conditional rather than observed.",
            "An item whose PICTURE cannot be sized has no length, and nothing after it has an "
            "offset. An item after a variable-length table has a range of offsets rather than an "
            "offset, and carries none — a minimum presented as the offset would be worse than "
            "no answer.",
            "Level-66 RENAMES and COPY ... REPLACING are not read by the parser. They are "
            "detected by scanning the source, and each one found makes the record partial with a "
            "stated reason rather than presenting a partial layout as a complete one.",
        ],
    ),
    "nginx": _proxy_route_seed(
        location_note=(
            "Routes locate by `file:line` of their `location` block. An included file is spliced "
            "in where its `include` stands, so the line is the member file's own line."
        ),
        dropped=[f"nginx.{name}" for name in NGINX_DECLARED_DIRECTIVES],
        projection_note=(
            "Each externally reachable `location` becomes one operation: `=` an exact path, no "
            "modifier or `^~` a prefix, `~` / `~*` a regular expression whose segments become "
            "inferred path parameters. `server_name` gives the hosts, `listen … ssl` the scheme, "
            "`proxy_pass` / `grpc_pass` the backend (an `upstream` by name, else a direct "
            "address), and `limit_except … { deny all; }` the methods. "
            + _PROXY_SCHEMALESS
        ),
        notes=_NGINX_SUBSET_NOTES,
    ),
    "traefik": _proxy_route_seed(
        location_note=(
            "Routes locate by `file#http.routers.<name>` (file provider) or by the resource and "
            "route index of an `IngressRoute`."
        ),
        dropped=[f"traefik.{name}" for name in TRAEFIK_DECLARED_CONSTRUCTS],
        projection_note=(
            "A router's rule is put into disjunctive normal form; each alternative becomes one "
            "match: `Path` exact, `PathPrefix` prefix, `PathRegexp` regex, `Host` the hosts, "
            "`Method` the method, `Header` / `Query` (and `…Regexp`) match parameters. Negated "
            "matchers, `ClientIP` and `HostRegexp` stay on the route as unmodelled conditions. "
            "Middlewares (chains expanded) ride on the operations as policy. "
            + _PROXY_SCHEMALESS
        ),
        notes=[
            "A router naming a service or middleware that no supplied file declares is refused "
            "as `INPUT_REFERENCE_UNRESOLVED`; a reference to another provider (`name@docker`) "
            "is kept as written. Import a watched directory as a file set so its routers, "
            "services and middlewares resolve together.",
        ],
    ),
    "haproxy": _proxy_route_seed(
        location_note="Routes locate by `file:line` of their `use_backend` / `default_backend` line.",
        dropped=[f"haproxy.{name}" for name in HAPROXY_DECLARED_CONSTRUCTS],
        projection_note=(
            "Each `use_backend` rule becomes a route; its condition is put into disjunctive "
            "normal form and each alternative is one match: `path` exact, `path_beg` / "
            "`path_dir` prefix, `path_reg` regex, `method` methods, `hdr(host)` hosts, `hdr(x)` "
            "/ `urlp(x)` match parameters. `default_backend` is a catch-all and `http-request "
            "return … if <path ACL>` a route HAProxy answers itself. A computed backend is "
            "resolved through its map file when the file set supplies it. "
            + _PROXY_SCHEMALESS
        ),
        notes=[
            "A section in TCP mode — set on it or inherited from the nearest preceding "
            "`defaults` — routes connections, not requests, so it imports with no HTTP "
            "operation and is declared on the ledger.",
        ],
    ),
    "consul": _proxy_route_seed(
        location_note="Routes locate by the configuration entry (`service-router/<name>`) and route index.",
        dropped=[f"consul.{name}" for name in CONSUL_DECLARED_CONSTRUCTS],
        projection_note=(
            "Only a `service-router` carries paths: `PathExact` / `PathPrefix` / `PathRegex`, "
            "`Methods`, `Header` and `QueryParam` become operations, and the router's own "
            "service takes a fall-through catch-all. An `ingress-gateway` HTTP listener exposes "
            "a catch-all per service on its hosts. A registered HTTP service no router describes "
            "becomes one catch-all operation, or one per `urlprefix-` tag — a convention, "
            "recorded as such. "
            + _PROXY_SCHEMALESS
        ),
        notes=[
            "A catalog is a registry, not a route table, so most of a Consul import is "
            "inference. A service's `meta.openapi_url` points at a real specification — import "
            "that for schemas.",
        ],
    ),
    "tyk": _proxy_route_seed(
        location_note=(
            "Classic routes locate by `version_data.versions.<v>.extended_paths.<list>`; Tyk OAS "
            "operations locate by their OpenAPI path, as the OpenAPI adapter reads them."
        ),
        dropped=[f"tyk.{name}" for name in TYK_DECLARED_CONSTRUCTS],
        projection_note=(
            "A classic definition's white-listed (and ignored) paths become operations at "
            "`listen_path` + path, one per `method_actions` method, with `{param}` segments as "
            "inferred path parameters; per-path rules and auth flags ride as policy. Classic "
            "definitions carry no response schemas and their `validate_json` request schemas are "
            "carried as validation policy, so classic operations have no messages and are "
            "labelled inferred. A Tyk OAS definition is an OpenAPI document: its paths and "
            "schemas are read by the OpenAPI adapter as declared, and only the "
            "`x-tyk-api-gateway` middleware is attached as inferred gateway policy."
        ),
        notes=[
            "The adapter claims an OpenAPI document only because it carries "
            "`x-tyk-api-gateway`; the OpenAPI adapter steps down for such a document so the two "
            "never tie.",
        ],
    ),
}


# ===========================================================================
# Derivation (the safe fallback every registered format is guaranteed)
# ===========================================================================

#: Construct-key suffixes that, when *supported*, upgrade a derived entry's source-location
#: quality above the path-only default. Kept as a rule rather than a per-format table so a
#: future native extractor that records lines or offsets is described correctly the day it
#: registers, without a registry edit.
_LOCATION_SUFFIXES: Tuple[Tuple[str, SourceLocationQuality], ...] = (
    (".byte_offsets", SourceLocationQuality.BYTE_OFFSETS),
    (".source_offsets", SourceLocationQuality.BYTE_OFFSETS),
    (".source_lines", SourceLocationQuality.LINE_NUMBERS),
    (".line_numbers", SourceLocationQuality.LINE_NUMBERS),
)


def _derive_source_location(capabilities: AnalyzerCapabilities) -> SourceLocationSupport:
    """Derive the source-location quality a format's analyzer can offer.

    Path-only is the floor, because every analyzer builds a structural path as it walks. It is
    raised only when the analyzer *declares* it models a stronger pointer — and a suffix listed
    in :data:`_LOCATION_SUFFIXES` under ``unsupported`` is a positive statement that it does
    not, so it can never raise the floor.

    Args:
        capabilities: The analyzer's own declaration.

    Returns:
        The derived :class:`SourceLocationSupport`.
    """
    supported = set(capabilities.supported)
    for suffix, quality in _LOCATION_SUFFIXES:
        if any(key.endswith(suffix) for key in supported):
            return SourceLocationSupport(
                quality=quality,
                note=(
                    "The analyzer declares it records this pointer kind; nodes carry it where "
                    "the construct could be placed."
                ),
            )
    return SourceLocationSupport(
        quality=SourceLocationQuality.PATH_ONLY,
        note=(
            "Nodes locate by structural path and sibling ordinal only. A UI can identify the "
            "construct but cannot point at a line or byte range in the raw source."
        ),
    )


def _derive_conversion(
    formats: Iterable[str], *, available: bool, preview_only: bool
) -> ConversionSupportEntry:
    """Derive whether a format reaches the canonical model, and by which route.

    The only two things that genuinely stop a conversion are an adapter that never persists
    (nothing to convert *from*) and a missing toolchain (nothing can be imported here). Every
    other registered adapter reaches the canonical model, because :meth:`ImportSource.normalize`
    is abstract and an item that failed it would not be in the catalog to convert.

    A declared format key without a registered normalizer is therefore *not* reported as a gap:
    ``formats`` mixes normalizer keys with detection aliases (``edix12`` declares ``x12`` and
    ``edi`` too), and several adapters — JSON Schema, JSON Type Definition — build the canonical
    model in-adapter with no separate normalizer at all. Calling either case "unconvertible"
    would be exactly the kind of false negative this registry exists to prevent.

    Args:
        formats: The adapter's declared format keys.
        available: Whether the adapter is runnable in this runtime.
        preview_only: Whether the adapter never persists (nothing to convert *from*).

    Returns:
        The derived :class:`ConversionSupportEntry`.
    """
    from .normalizer import get_normalizer

    declared = sorted({key for key in formats if key})
    canonical = [key for key in declared if get_normalizer(key) is not None]

    if preview_only:
        support = ConversionSupport.UNSUPPORTED
        note = (
            "This adapter accepts a document without persisting it, so there is no catalog "
            "revision to convert from."
        )
    elif not available:
        support = ConversionSupport.TOOL_UNAVAILABLE
        note = (
            "A toolchain this format requires is missing in this runtime, so no import — and "
            "therefore no conversion — can run here."
        )
    elif canonical:
        support = ConversionSupport.SUPPORTED
        note = (
            f"An import normalizes onto the canonical model through {', '.join(canonical)}, and "
            "from there reaches every export destination."
        )
    else:
        support = ConversionSupport.SUPPORTED
        note = (
            "The adapter builds the canonical model itself rather than through a separately "
            "registered normalizer, and from there reaches every export destination."
        )
    return ConversionSupportEntry(
        support=support,
        canonical_formats=canonical,
        normalizes_in_adapter=support == ConversionSupport.SUPPORTED and not canonical,
        declared_formats=declared,
        note=note,
    )


# Built per call rather than shared, so the caller's (already validated) key can be echoed into
# it. Every other field is constant: an unknown format is described by the absence of every
# claim, not by a guess.
def _unknown_format_capability(format_key: str) -> FormatCapability:
    """Build the truthful "no adapter is registered under this key" entry.

    A catalog item can name a source format whose adapter was later retired, or a caller can
    ask about a key that never existed. Both must resolve — a UI that cannot resolve a format
    falls back to "no details", which is the failure this registry exists to remove.

    Args:
        format_key: The (already validated) key that was asked about.

    Returns:
        An entry that claims nothing about the format.
    """
    return FormatCapability(
        format=format_key,
        label=format_key,
        paradigm=None,
        provenance=CapabilityProvenance.UNKNOWN_FORMAT,
        availability=FormatAvailability.UNREGISTERED,
        unavailable_reason="No import-source adapter is registered under this format key.",
        native_hierarchy=NativeHierarchy.NONE,
        native_hierarchy_note=(
            "No adapter is registered for this format, so no analysis tree is produced for it."
        ),
        analyzer=AnalyzerEvidence(key="none", version="0.0.0", tool_versions={}),
        source_location=SourceLocationSupport(
            quality=SourceLocationQuality.NONE,
            note="No analyzer runs for this format, so no node carries a source pointer.",
        ),
        value_visibility=ValueVisibilitySupport(
            default=ValueVisibility.DEFAULT,
            maximum=ValueVisibility.NONE,
            note="Nothing is observed for this format, so there is no value material to govern.",
        ),
        supported_constructs=[],
        unsupported_constructs=[],
        limits={},
        canonical_projection=CanonicalProjectionSupport(
            coverage=ProjectionCoverage.NONE,
            dropped_constructs=[],
            note="No adapter normalizes this format onto the canonical model.",
        ),
        conversion=ConversionSupportEntry(
            support=ConversionSupport.UNSUPPORTED,
            canonical_formats=[],
            normalizes_in_adapter=False,
            declared_formats=[],
            note="No adapter is registered, so this format has no conversion route.",
        ),
        # Not an empty coverage — an *undeclared* one. "Reads no versions" would be a claim about
        # the format; the honest answer for a key nothing is registered under is that the question
        # has no answer here.
        version_coverage=UNDECLARED_VERSION_COVERAGE,
        notes=[
            "This format key is not one apiome currently imports. Anything a catalog item of "
            "this format does not show is unknown, not absent.",
        ],
        registry_version=REGISTRY_VERSION,
        review_date=REVIEW_DATE,
    )


def _analyzer_capabilities_of(source: "ImportSource") -> AnalyzerCapabilities:
    """Read an adapter's capability declaration, degrading to an empty one if it raises.

    An adapter whose declaration blows up must not take the whole registry — and therefore
    every format's explanation — down with it. An empty declaration is the safe answer: it
    claims nothing is modelled and nothing is ruled out, so every construct resolves to
    :attr:`AbsenceCategory.UNDECLARED`.

    Args:
        source: The adapter instance.

    Returns:
        Its :class:`~app.payload_analysis.AnalyzerCapabilities`, or an empty one.
    """
    try:
        return source.analysis_capabilities()
    except Exception:  # pragma: no cover - defensive; no shipped adapter raises here
        logger.warning(
            "format capability registry: %r could not declare its analyzer capabilities",
            getattr(source, "key", "?"),
            exc_info=True,
        )
        return AnalyzerCapabilities()


def _analyzer_evidence_of(source: "ImportSource") -> AnalyzerEvidence:
    """Read an adapter's analyzer identity and tool versions, degrading if the probe raises.

    Tool versions are read from the live parser libraries, which is exactly why the probe is
    guarded: an import error inside a version lookup must cost the entry its *evidence*, not
    its existence.

    Args:
        source: The adapter instance.

    Returns:
        The :class:`AnalyzerEvidence` for this adapter.
    """
    try:
        tool_versions = dict(source.analyzer_tool_versions())
    except Exception:  # pragma: no cover - defensive; no shipped adapter raises here
        logger.warning(
            "format capability registry: %r could not report its analyzer tool versions",
            getattr(source, "key", "?"),
            exc_info=True,
        )
        tool_versions = {}
    return AnalyzerEvidence(
        key=source.analyzer_key,
        version=source.analyzer_version,
        tool_versions={str(name): str(value) for name, value in sorted(tool_versions.items())},
    )


def _derive_capability(source: "ImportSource") -> FormatCapability:
    """Build a format's entry from the live adapter, applying its reviewed seed when one exists.

    Everything the code knows — analyzer key/version, tool versions, the declared construct
    lists, the numeric limits, the normalizer routes, runtime availability — is read from the
    adapter on every call, so it cannot drift. A seed supplies only the reviewed judgements no
    derivation can make: what the native hierarchy actually is, how good the source pointers
    are, where the value ceiling sits, and what normalization drops.

    Args:
        source: The registered adapter instance.

    Returns:
        Its :class:`FormatCapability`.
    """
    descriptor = source.descriptor()
    capabilities = _analyzer_capabilities_of(source)
    seed = _CAPABILITY_SEED.get(descriptor.key)

    if source.preview_only:
        availability = FormatAvailability.PREVIEW_ONLY
        unavailable_reason = (
            "This adapter accepts a document for validation without persisting it, so no "
            "analysis is ever stored for it."
        )
    elif not descriptor.available:
        availability = FormatAvailability.TOOL_UNAVAILABLE
        unavailable_reason = descriptor.unavailable_reason
    else:
        availability = FormatAvailability.AVAILABLE
        unavailable_reason = None

    if seed is not None:
        native_hierarchy = seed.native_hierarchy
        native_hierarchy_note = seed.native_hierarchy_note
        source_location = seed.source_location
        value_visibility = seed.value_visibility
        canonical_projection = seed.canonical_projection
        guide_statement = seed.implementation_guide
        notes = list(seed.notes)
    else:
        native = source.analyzer_key != GENERIC_ANALYZER_KEY
        native_hierarchy = NativeHierarchy.NATIVE if native else NativeHierarchy.GENERIC
        native_hierarchy_note = (
            "The analyzer emits its own format-specific node vocabulary; see the supported "
            "constructs below for what it names."
            if native
            else "The format-blind walk records containers, ordered collections and leaves. "
            "Nesting and ordering survive; this format's own semantics are not named, and "
            "their absence from the tree says nothing about the source."
        )
        source_location = _derive_source_location(capabilities)
        value_visibility = ValueVisibilitySupport(
            default=ValueVisibility.DEFAULT,
            maximum=ValueVisibility.FULL,
            note=(
                "Leaf values are observed, so the stored record carries whatever the "
                "value-visibility policy in force allows — the default keeps only presence and "
                "length."
            ),
        )
        canonical_projection = CanonicalProjectionSupport(
            coverage=ProjectionCoverage.UNKNOWN,
            dropped_constructs=[],
            note=(
                "This format's projection onto the canonical model has not been reviewed, so "
                "the registry makes no claim about what normalization keeps or drops."
            ),
        )
        guide_statement = None
        notes = [
            "This entry is derived from the adapter's own declarations rather than reviewed, so "
            "it states only what the adapter states.",
        ]

    return FormatCapability(
        format=descriptor.key,
        label=descriptor.label,
        paradigm=descriptor.paradigm.value,
        provenance=(
            CapabilityProvenance.REVIEWED if seed is not None else CapabilityProvenance.DERIVED
        ),
        availability=availability,
        unavailable_reason=unavailable_reason,
        native_hierarchy=native_hierarchy,
        native_hierarchy_note=native_hierarchy_note,
        analyzer=_analyzer_evidence_of(source),
        source_location=source_location,
        value_visibility=value_visibility,
        supported_constructs=list(capabilities.supported),
        unsupported_constructs=list(capabilities.unsupported),
        limits=dict(capabilities.limits),
        canonical_projection=canonical_projection,
        conversion=_derive_conversion(
            descriptor.formats,
            available=descriptor.available,
            preview_only=source.preview_only,
        ),
        # Read from the FMT-3.8 declaration rather than from the adapter: ``descriptor.formats``
        # mixes version keys with detection aliases (``cobol``, ``apib``), so it cannot answer
        # "which versions?" on its own. An adapter with no declaration resolves to the undeclared
        # coverage instead of an invented one.
        version_coverage=version_coverage_for(descriptor.key),
        implementation_guide=guide_statement,
        notes=notes,
        registry_version=REGISTRY_VERSION,
        review_date=REVIEW_DATE,
    )


# ===========================================================================
# Public resolution
# ===========================================================================


def is_valid_format_key(format_key: str) -> bool:
    """Return whether ``format_key`` has the shape of a registrable format key.

    Callers that accept a format key from a request validate it here first, so an arbitrary
    string is rejected at the boundary rather than echoed back inside a capability entry.

    Args:
        format_key: The candidate key.

    Returns:
        True when it matches :data:`FORMAT_KEY_PATTERN`.
    """
    return bool(FORMAT_KEY_PATTERN.match(format_key))


def capability_for(format_key: str) -> FormatCapability:
    """Return the capability entry for ``format_key`` — always, for any key.

    The guarantee the ticket's first acceptance criterion asks for: every catalog format
    resolves to a safe entry. A reviewed seed produces a ``reviewed`` entry, any other
    registered adapter produces a ``derived`` one read off the adapter itself, and an
    unregistered key produces an ``unknown_format`` entry that claims nothing. There is no
    input for which this returns nothing, because "the registry had no answer" is precisely
    the dead end that leaves a UI saying "no details".

    Args:
        format_key: The import-source key (aliases such as ``protobuf`` → ``grpc`` resolve).

    Returns:
        The format's :class:`FormatCapability`.
    """
    from .import_source import get_import_source

    normalized = (format_key or "").strip().lower()
    if not normalized or not is_valid_format_key(normalized):
        # Never echo an unvalidated string into an entry; a key that could not have been
        # registered is reported under a fixed placeholder instead.
        return _unknown_format_capability("unknown")
    source = get_import_source(normalized)
    if source is None:
        return _unknown_format_capability(normalized)
    return _derive_capability(source)


def format_capabilities() -> List[FormatCapability]:
    """Return one entry per registered import source, in key order.

    Returns:
        Every registered format's :class:`FormatCapability`, sorted by key.
    """
    from .import_source import available_import_sources

    return [capability_for(key) for key in available_import_sources()]


def registry_snapshot() -> FormatCapabilitySnapshot:
    """Build the deterministic, versioned snapshot of the whole registry (REST/UI contract).

    Pure and deterministic: the same adapter registry and the same seeds yield an identical
    snapshot, so the UI can fetch it once and cache it by
    :attr:`FormatCapabilitySnapshot.version`.

    Returns:
        The full :class:`FormatCapabilitySnapshot`.
    """
    return FormatCapabilitySnapshot(
        version=REGISTRY_VERSION,
        review_date=REVIEW_DATE,
        analysis_schema_version=PAYLOAD_ANALYSIS_SCHEMA_VERSION,
        absence_categories=sorted(category.value for category in AbsenceCategory),
        absences=absence_explanations(),
        reason_absence_categories={
            reason: REASON_ABSENCE_CATEGORIES[reason].value for reason in ANALYSIS_REASONS
        },
        formats=format_capabilities(),
    )
