"""Destination capability & technical-documentation registry — EFP-1.2 (#4811).

EFP-1.1 (:mod:`app.export_projection`) can already predict *what* an export loses and
attach a truthful cause category (:class:`~app.projection_taxonomy.ProjectionReason`) to
each non-preserved construct. What it seeded only ad hoc was the *documentation* side:
a hard-coded map from a format prefix to a specification landing page, and a single
"capability-driven loss is a destination limitation" rule. That is not enough to tell a
user, reliably and per reason, *why* something changed and *where the authoritative
reference lives* — and it blurs a real destination-specification limit together with an
apiome emitter gap, a parser gap, an unavailable toolchain, a redaction, or a chosen
option.

This module is the versioned registry that fixes that. For every runtime-available
emitter it provides a :class:`DestinationCapability` entry — a display label, an
availability state, and reviewed destination-documentation metadata with an
**authoritative, host-allowlisted URL** where one applies and an explicit
``documentation_unavailable`` fallback where it does not. Independently, it owns one
reviewed :class:`ReasonExplanation` per :class:`ProjectionReason`, so the eight cause
categories are represented *separately*: a ``destination_unsupported`` limit reads
differently from an ``emitter_unsupported`` gap, a ``source_parse_limit``, a
``security_redacted`` construct, or an ``option_excluded`` one — and only a genuine
destination-specification limit is ever paired with a destination-format link.

**Safety.** Every documentation URL is validated against a scheme + host allowlist
(:func:`validate_documentation_url`) at model-construction time, so an unsafe or
off-allowlist URL cannot enter the registry, the projection manifest, or the API
contract. The whole registry is exposed as a deterministic
:class:`CapabilityRegistrySnapshot` (versioned by :data:`REGISTRY_VERSION`) for the REST
contract and the UI, so the UI renders reviewed data instead of hard-coding links in
components. :mod:`app.export_projection` consumes :func:`documentation_for`,
:func:`explanation_for`, and :data:`REGISTRY_VERSION` to stamp registry/tool versions and
per-reason documentation into projection evidence.
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .emitter import Emitter
from .projection_taxonomy import ProjectionReason

__all__ = [
    "REGISTRY_VERSION",
    "REVIEW_DATE",
    "ALLOWED_DOCUMENTATION_HOSTS",
    "UnsafeDocumentationUrlError",
    "validate_documentation_url",
    "is_safe_documentation_url",
    "DestinationAvailability",
    "DocumentationEvidence",
    "ReasonExplanation",
    "DestinationCapability",
    "CapabilityRegistrySnapshot",
    "capability_for",
    "documentation_for",
    "explanation_for",
    "reason_explanation",
    "reason_explanations",
    "registry_snapshot",
    "REASON_CODES",
]

#: The registry contract version. Bumped whenever an entry, a reason template, or a
#: documentation link changes, so a projection manifest built against it is a distinct
#: snapshot and the UI can detect a stale contract. Stamped into projection evidence.
REGISTRY_VERSION = "1"

#: The date the current registry links and explanations were last reviewed. Recorded as
#: provenance on every entry (the roadmap's documentation-governance requirement).
REVIEW_DATE = "2026-07-15"

#: The canonical set of valid reason-code strings (from the shared taxonomy). The API and
#: UI contract tests assert that no manifest or drawer ever uses a code outside this set.
REASON_CODES = frozenset(reason.value for reason in ProjectionReason)


# ===========================================================================
# URL allowlist validation
# ===========================================================================


class UnsafeDocumentationUrlError(ValueError):
    """Raised when a documentation URL is not an ``https`` link to an allowlisted host.

    The registry never carries a link that fails this check, so an unsafe URL cannot
    reach the projection manifest, the REST contract, or the UI. The API/UI contract
    tests assert both that every registered link passes and that a crafted unsafe URL
    (``javascript:``, ``http://``, an off-allowlist host, embedded credentials) is
    rejected.
    """


#: Authoritative documentation hosts the registry is allowed to link to. An exact,
#: lowercased host match is required — no subdomain wildcards, no ports, no credentials —
#: so a look-alike host (``spec.openapis.org.evil.test``) is rejected. Every host here
#: backs a reviewed link in :data:`_DOCUMENTATION_SEED`.
ALLOWED_DOCUMENTATION_HOSTS: frozenset[str] = frozenset(
    {
        "spec.openapis.org",
        "www.asyncapi.com",
        "spec.graphql.org",
        "protobuf.dev",
        "avro.apache.org",
        "json-schema.org",
        "datatracker.ietf.org",
        "www.w3.org",
        "cloudevents.io",
        "smithy.io",
        "typespec.io",
        "www.odata.org",
        "www.hl7.org",
        "capnproto.org",
        "thrift.apache.org",
        "flatbuffers.dev",
        "connectrpc.com",
        "spec.open-rpc.org",
        "learning.postman.com",
        "raml.org",
        "apiblueprint.org",
        "www.omg.org",
        "www.itu.int",
        "www.iso20022.org",
        "www.fixtrading.org",
    }
)


def validate_documentation_url(url: str) -> str:
    """Return ``url`` unchanged if it is a safe documentation link, else raise.

    A safe link is an absolute ``https`` URL whose host is an exact, lowercased member of
    :data:`ALLOWED_DOCUMENTATION_HOSTS`, with no embedded credentials (userinfo) and no
    explicit port. Anything else — a non-``https`` scheme (including ``javascript:`` /
    ``data:``), a missing host, an off-allowlist host, a look-alike host, credentials, or
    a port — raises :class:`UnsafeDocumentationUrlError`.

    Args:
        url: The candidate documentation URL.

    Returns:
        The same ``url`` string when it passes validation.

    Raises:
        UnsafeDocumentationUrlError: When ``url`` is not a safe allowlisted https link.
    """
    if not isinstance(url, str) or not url:
        raise UnsafeDocumentationUrlError("documentation URL must be a non-empty string")
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise UnsafeDocumentationUrlError(
            f"documentation URL must use https, not {parts.scheme or '(none)'!r}: {url!r}"
        )
    if parts.username or parts.password or "@" in parts.netloc:
        raise UnsafeDocumentationUrlError(f"documentation URL must not embed credentials: {url!r}")
    if parts.port is not None:
        raise UnsafeDocumentationUrlError(f"documentation URL must not specify a port: {url!r}")
    host = parts.hostname
    if not host:
        raise UnsafeDocumentationUrlError(f"documentation URL has no host: {url!r}")
    if host.lower() not in ALLOWED_DOCUMENTATION_HOSTS:
        raise UnsafeDocumentationUrlError(
            f"documentation host {host!r} is not on the authoritative allowlist: {url!r}"
        )
    return url


def is_safe_documentation_url(url: Optional[str]) -> bool:
    """Return ``True`` when ``url`` passes :func:`validate_documentation_url`, else ``False``."""
    if url is None:
        return False
    try:
        validate_documentation_url(url)
        return True
    except UnsafeDocumentationUrlError:
        return False


# ===========================================================================
# Value types
# ===========================================================================


class DestinationAvailability(str, Enum):
    """Whether a destination emitter can be relied on in the current runtime (EFP-1.2)."""

    AVAILABLE = "available"  # registered and runnable in this runtime
    EXPERIMENTAL = "experimental"  # registered but not production-guaranteed (e.g. a sample target)
    UNAVAILABLE = "unavailable"  # registered but a required toolchain is missing in this runtime


class DocumentationEvidence(BaseModel):
    """Reviewed destination-format documentation metadata for a target (EFP-1.2).

    A validated pointer to the authoritative specification for a destination format,
    with an explicit ``documentation_unavailable`` fallback so a target with no known —
    or no *applicable* — link says so truthfully rather than inventing one. When
    :attr:`url` is present it is validated against the host allowlist at construction
    time (:func:`validate_documentation_url`), so an unsafe link can never enter a model
    instance. This supersedes EFP-1.1's per-target seed; it is now sourced per
    destination (and, on a projection edge, per reason code) from this registry.
    """

    model_config = ConfigDict(extra="forbid")

    specification: Optional[str] = Field(
        default=None, description="Human label of the destination specification (e.g. 'OpenAPI 3.1')."
    )
    version: Optional[str] = Field(
        default=None, description="Specification version the link refers to, when versioned."
    )
    url: Optional[str] = Field(
        default=None,
        description="Authoritative, host-allowlisted https documentation URL, or null when unavailable.",
    )
    anchor: Optional[str] = Field(
        default=None, description="Optional URL fragment/anchor for a specific capability or reason."
    )
    documentation_unavailable: bool = Field(
        default=False,
        description="True when no authoritative link applies; the UI explains the limitation "
        "without inventing a URL.",
    )
    note: Optional[str] = Field(
        default=None, description="Short reviewed note about the documentation, when present."
    )

    @field_validator("url")
    @classmethod
    def _validate_url(cls, value: Optional[str]) -> Optional[str]:
        """Reject any URL that is not a safe, allowlisted https link (unsafe-URL guard)."""
        if value is None:
            return None
        return validate_documentation_url(value)


class ReasonExplanation(BaseModel):
    """A reviewed, reason-specific explanation template (EFP-1.2).

    One per :class:`~app.projection_taxonomy.ProjectionReason`, so the eight cause
    categories are represented and rendered *separately* — a specification limit, an
    emitter gap, a source-parse gap, a redaction, an excluded option, and an unavailable
    toolchain each get their own honest wording and remediation. :attr:`summary_template`
    may contain a single ``{construct}`` slot, substituted only with the (safe) canonical
    construct key by :func:`explanation_for`.
    """

    model_config = ConfigDict(extra="forbid")

    reason: ProjectionReason = Field(description="The cause category this explanation is for.")
    category_label: str = Field(description="Short human label for the category (e.g. 'Destination limit').")
    summary_template: str = Field(
        description="Reviewed one-line explanation, optionally with a single ``{construct}`` slot."
    )
    remediation: str = Field(description="Short, safe remediation guidance for this category.")
    destination_documentation_applies: bool = Field(
        description="True only for a genuine destination-specification limit — the one category "
        "for which an authoritative destination-format link is meaningful.",
    )


class DestinationCapability(BaseModel):
    """The versioned capability + documentation entry for one destination target (EFP-1.2)."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(description="Stable emitter target key (e.g. ``openapi``).")
    format: str = Field(description="Output format key the emitter produces (e.g. ``openapi-3.1``).")
    label: str = Field(description="Human label for the destination.")
    availability: DestinationAvailability = Field(
        description="Whether this destination is available / experimental / unavailable here.",
    )
    documentation: DocumentationEvidence = Field(
        description="Reviewed destination-documentation metadata, with a safe fallback.",
    )
    emitter_version: str = Field(description="The emitter implementation version this entry describes.")
    registry_version: str = Field(description="The registry contract version this entry belongs to.")
    review_date: str = Field(description="When this entry's link/explanation was last reviewed.")


class CapabilityRegistrySnapshot(BaseModel):
    """The full, deterministic registry view exposed to the REST contract + UI (EFP-1.2).

    Carries the :attr:`version`, the reviewed :class:`ReasonExplanation` for every reason
    code (the drawer's honest wording), and a :class:`DestinationCapability` for every
    runtime-available emitter, all in a stable order. Because it is derived from the
    static registry and the (deterministic) emitter registry, identical inputs yield an
    identical snapshot — safe to cache and to mirror in a TypeScript contract.
    """

    model_config = ConfigDict(extra="forbid")

    version: str = Field(description="The registry contract version (``REGISTRY_VERSION``).")
    review_date: str = Field(description="When the registry links/explanations were last reviewed.")
    reason_codes: List[str] = Field(
        description="The canonical set of valid reason-code strings, sorted. Contract tests reject "
        "any reason code outside this set.",
    )
    reasons: List[ReasonExplanation] = Field(
        description="The reviewed explanation for each reason code, in taxonomy order.",
    )
    destinations: List[DestinationCapability] = Field(
        description="One capability entry per registered destination, in key order.",
    )


# ===========================================================================
# Reason explanations (one reviewed template per cause category)
# ===========================================================================

# The single source of the eight cause categories' honest wording. Only
# ``destination_unsupported`` marks the destination documentation as applicable — a link
# to a format spec explains a specification limit, never an apiome emitter/source gap.
_REASON_EXPLANATIONS: Dict[ProjectionReason, ReasonExplanation] = {
    ProjectionReason.DESTINATION_UNSUPPORTED: ReasonExplanation(
        reason=ProjectionReason.DESTINATION_UNSUPPORTED,
        category_label="Destination limit",
        summary_template="The destination format cannot represent {construct}; its specification "
        "has no equivalent construct.",
        remediation="Choose a destination format that supports this construct, or accept the loss.",
        destination_documentation_applies=True,
    ),
    ProjectionReason.EMITTER_UNSUPPORTED: ReasonExplanation(
        reason=ProjectionReason.EMITTER_UNSUPPORTED,
        category_label="Not yet emitted",
        summary_template="apiome's emitter does not yet produce {construct} for this destination, "
        "even though the format could carry it.",
        remediation="Track emitter support; this is an apiome limitation, not a format limit.",
        destination_documentation_applies=False,
    ),
    ProjectionReason.SOURCE_INCOMPLETE: ReasonExplanation(
        reason=ProjectionReason.SOURCE_INCOMPLETE,
        category_label="Source incomplete",
        summary_template="The source did not provide enough detail about {construct} to export it "
        "faithfully.",
        remediation="Complete the source definition and re-export.",
        destination_documentation_applies=False,
    ),
    ProjectionReason.SOURCE_PARSE_LIMIT: ReasonExplanation(
        reason=ProjectionReason.SOURCE_PARSE_LIMIT,
        category_label="Parser limit",
        summary_template="apiome's parser could not fully capture {construct} from the source, so "
        "its export cannot be determined.",
        remediation="This is an apiome parser limitation; the source data itself may be intact.",
        destination_documentation_applies=False,
    ),
    ProjectionReason.OPTION_EXCLUDED: ReasonExplanation(
        reason=ProjectionReason.OPTION_EXCLUDED,
        category_label="Option excluded",
        summary_template="A selected export option excluded {construct} from this export.",
        remediation="Change the export option and preview again to include it.",
        destination_documentation_applies=False,
    ),
    ProjectionReason.SECURITY_REDACTED: ReasonExplanation(
        reason=ProjectionReason.SECURITY_REDACTED,
        category_label="Redacted",
        summary_template="{construct} was redacted by a security or privacy policy and is not "
        "exported.",
        remediation="Adjust the redaction policy if this construct should be exported.",
        destination_documentation_applies=False,
    ),
    ProjectionReason.TARGET_TOOL_UNAVAILABLE: ReasonExplanation(
        reason=ProjectionReason.TARGET_TOOL_UNAVAILABLE,
        category_label="Toolchain unavailable",
        summary_template="The external toolchain this destination requires is unavailable, so "
        "{construct} could not be emitted.",
        remediation="Install or enable the destination's toolchain and re-export.",
        destination_documentation_applies=False,
    ),
    ProjectionReason.NOT_APPLICABLE: ReasonExplanation(
        reason=ProjectionReason.NOT_APPLICABLE,
        category_label="Not applicable",
        summary_template="{construct} does not apply to this destination or source shape.",
        remediation="No action needed.",
        destination_documentation_applies=False,
    ),
}


def reason_explanation(reason: ProjectionReason) -> ReasonExplanation:
    """Return the reviewed :class:`ReasonExplanation` for ``reason``."""
    return _REASON_EXPLANATIONS[reason]


def reason_explanations() -> List[ReasonExplanation]:
    """Return every reason's reviewed explanation, in taxonomy (enum) order."""
    return [_REASON_EXPLANATIONS[reason] for reason in ProjectionReason]


def explanation_for(reason: ProjectionReason, construct: Optional[str] = None) -> str:
    """Render the reviewed one-line explanation for ``reason``, naming ``construct`` safely.

    Substitutes only the ``{construct}`` slot with the canonical construct key (a safe,
    apiome-controlled string). When ``construct`` is omitted, a neutral "this construct"
    is used so the sentence still reads.

    Args:
        reason: The cause category to explain.
        construct: The canonical construct key to name, or ``None`` for a generic phrasing.

    Returns:
        The rendered explanation sentence.
    """
    template = _REASON_EXPLANATIONS[reason].summary_template
    return template.format(construct=f"`{construct}`" if construct else "this construct")


# ===========================================================================
# Destination documentation seed
# ===========================================================================


class _DocSeed:
    """A reviewed documentation seed for one destination key (spec label/version/url)."""

    __slots__ = ("specification", "version", "url", "anchor", "note")

    def __init__(
        self,
        specification: str,
        *,
        version: Optional[str] = None,
        url: Optional[str] = None,
        anchor: Optional[str] = None,
        note: Optional[str] = None,
    ) -> None:
        self.specification = specification
        self.version = version
        self.url = url
        self.anchor = anchor
        self.note = note


# Reviewed, authoritative documentation per destination *key*. Every ``url`` is on the
# host allowlist and is validated when the :class:`DocumentationEvidence` is built. A
# destination absent here (or one whose spec is not published at a stable https link)
# still gets an entry — with a truthful ``documentation_unavailable`` fallback.
_DOCUMENTATION_SEED: Dict[str, _DocSeed] = {
    "openapi": _DocSeed(
        "OpenAPI Specification", version="3.1.0", url="https://spec.openapis.org/oas/v3.1.0.html"
    ),
    "asyncapi": _DocSeed(
        "AsyncAPI Specification",
        version="3.0.0",
        url="https://www.asyncapi.com/docs/reference/specification/v3.0.0",
    ),
    "graphql": _DocSeed(
        "GraphQL Specification", version="October 2021", url="https://spec.graphql.org/October2021/"
    ),
    "protobuf": _DocSeed(
        "Protocol Buffers Language Guide (proto3)", url="https://protobuf.dev/programming-guides/proto3/"
    ),
    "avro": _DocSeed(
        "Apache Avro Specification",
        version="1.11.1",
        url="https://avro.apache.org/docs/1.11.1/specification/",
    ),
    "json-schema": _DocSeed(
        "JSON Schema Core", version="2020-12", url="https://json-schema.org/draft/2020-12/json-schema-core"
    ),
    "jtd": _DocSeed("JSON Type Definition (RFC 8927)", url="https://datatracker.ietf.org/doc/html/rfc8927"),
    "wsdl": _DocSeed("Web Services Description Language 2.0", url="https://www.w3.org/TR/wsdl20/"),
    "xsd": _DocSeed("W3C XML Schema Definition Language 1.1", url="https://www.w3.org/TR/xmlschema11-1/"),
    "wadl": _DocSeed("Web Application Description Language", url="https://www.w3.org/submissions/wadl/"),
    "cloudevents": _DocSeed("CloudEvents", version="1.0", url="https://cloudevents.io/"),
    "smithy": _DocSeed("Smithy", version="2.0", url="https://smithy.io/2.0/spec/"),
    "typespec": _DocSeed("TypeSpec Language", url="https://typespec.io/docs/"),
    "odata": _DocSeed("OData", version="4.01", url="https://www.odata.org/documentation/"),
    "fhir": _DocSeed("HL7 FHIR", url="https://www.hl7.org/fhir/"),
    "capnproto": _DocSeed("Cap'n Proto Schema Language", url="https://capnproto.org/language.html"),
    "thrift": _DocSeed("Apache Thrift IDL", url="https://thrift.apache.org/docs/idl"),
    "flatbuffers": _DocSeed("FlatBuffers", url="https://flatbuffers.dev/"),
    "connectrpc": _DocSeed("Connect Protocol", url="https://connectrpc.com/docs/"),
    "openrpc": _DocSeed("OpenRPC Specification", url="https://spec.open-rpc.org/"),
    "postman": _DocSeed(
        "Postman Collection Format", url="https://learning.postman.com/docs/collections/collections-overview/"
    ),
    "raml": _DocSeed("RAML", version="1.0", url="https://raml.org/"),
    "apiblueprint": _DocSeed(
        "API Blueprint", url="https://apiblueprint.org/documentation/specification.html"
    ),
    "arazzo": _DocSeed("Arazzo Specification", url="https://spec.openapis.org/arazzo/latest.html"),
    "corbaidl": _DocSeed("OMG IDL", url="https://www.omg.org/spec/IDL/"),
    "oncrpc": _DocSeed("ONC RPC / XDR (RFC 5531)", url="https://datatracker.ietf.org/doc/html/rfc5531"),
    "asn1": _DocSeed("ITU-T X.680 (ASN.1)", url="https://www.itu.int/rec/T-REC-X.680"),
    "iso20022": _DocSeed("ISO 20022", url="https://www.iso20022.org/"),
    "fix": _DocSeed("FIX Trading Standards", url="https://www.fixtrading.org/standards/"),
}

# Destinations we do not link to a stable, authoritative https specification page (behind
# membership, unversioned, or http-only). They still get a full entry — with a reviewed
# note explaining the absence — so no entry silently invents a link.
_DOCUMENTATION_UNAVAILABLE_NOTE: Dict[str, str] = {
    "edix12": "The ASC X12 EDI standard is published to members; no public authoritative link.",
    "iso8583": "ISO 8583 is a paywalled ISO standard; no public authoritative link.",
    "hl7v2": "The HL7 v2.x messaging standard is distributed to members; no public authoritative link.",
    "cobolcopybook": "COBOL copybook layout has no single authoritative public specification page.",
    "xmlrpc": "The XML-RPC specification is published only over http; no authoritative https link.",
    "zosconnect": "IBM z/OS Connect documentation is versioned per release; no stable authoritative link.",
    "sample": "The sample no-op target is for testing and has no destination specification.",
}

# Destinations whose availability is not simply "runnable" — a test/sample target is
# explicitly experimental so it never masquerades as a production destination.
_EXPERIMENTAL_KEYS: frozenset[str] = frozenset({"sample"})


def _availability_for(descriptor_available: bool, key: str) -> DestinationAvailability:
    """Classify a destination's availability from its runtime state and explicit overrides."""
    if not descriptor_available:
        return DestinationAvailability.UNAVAILABLE
    if key in _EXPERIMENTAL_KEYS:
        return DestinationAvailability.EXPERIMENTAL
    return DestinationAvailability.AVAILABLE


def _documentation_evidence_for_key(key: str) -> DocumentationEvidence:
    """Build reviewed :class:`DocumentationEvidence` for a destination key, or a fallback."""
    seed = _DOCUMENTATION_SEED.get(key)
    if seed is not None:
        return DocumentationEvidence(
            specification=seed.specification,
            version=seed.version,
            url=seed.url,
            anchor=seed.anchor,
            note=seed.note,
        )
    note = _DOCUMENTATION_UNAVAILABLE_NOTE.get(
        key, "No authoritative specification link is registered for this destination yet."
    )
    return DocumentationEvidence(documentation_unavailable=True, note=note)


# ===========================================================================
# Public resolution
# ===========================================================================


def capability_for(emitter: type[Emitter]) -> DestinationCapability:
    """Return the versioned :class:`DestinationCapability` entry for ``emitter``.

    Every registered emitter resolves to an entry: a reviewed documentation seed where
    one exists, or a truthful ``documentation_unavailable`` fallback otherwise, with the
    destination's availability state and the emitter/registry versions for provenance.

    Args:
        emitter: The destination :class:`~app.emitter.Emitter` class.

    Returns:
        The destination's capability entry.
    """
    descriptor = emitter.descriptor()
    return DestinationCapability(
        key=descriptor.key,
        format=descriptor.format,
        label=descriptor.label,
        availability=_availability_for(descriptor.available, descriptor.key),
        documentation=_documentation_evidence_for_key(descriptor.key),
        emitter_version=emitter.version,
        registry_version=REGISTRY_VERSION,
        review_date=REVIEW_DATE,
    )


def documentation_for(
    emitter: type[Emitter], reason: Optional[ProjectionReason] = None
) -> DocumentationEvidence:
    """Return the documentation evidence to show for ``emitter`` and a given ``reason``.

    The distinction the ticket requires: a destination-format link is meaningful **only**
    for a genuine destination-specification limit
    (:attr:`~app.projection_taxonomy.ProjectionReason.DESTINATION_UNSUPPORTED`) — and for a
    ``reason``-less, target-level lookup (the manifest's :class:`ManifestTarget`
    documentation). For any *other* reason — an emitter gap, a source/parser gap, a
    redaction, an excluded option, an unavailable toolchain — the destination spec does not
    explain the loss, so this returns a ``documentation_unavailable`` evidence that says so,
    rather than a misleading link to the format specification.

    Args:
        emitter: The destination emitter class.
        reason: The cause category the documentation is being shown for, or ``None`` for the
            target-level destination documentation.

    Returns:
        The documentation evidence to render for this (emitter, reason) pair.
    """
    if reason is not None and not _REASON_EXPLANATIONS[reason].destination_documentation_applies:
        return DocumentationEvidence(
            documentation_unavailable=True,
            note="This limitation does not come from the destination specification, so no "
            "destination-format documentation link applies.",
        )
    return _documentation_evidence_for_key(emitter.descriptor().key)


def registry_snapshot() -> CapabilityRegistrySnapshot:
    """Build the deterministic, versioned snapshot of the whole registry (REST/UI contract).

    Walks the emitter registry for a :class:`DestinationCapability` per registered target
    (in key order) and pairs it with the reviewed :class:`ReasonExplanation` for every
    reason code. Pure and deterministic — identical registries yield an identical snapshot.
    """
    # Imported here (not at module top) to avoid importing the emitter registry loader
    # until a snapshot is actually requested, keeping this module import-light.
    from .emitter import describe_emit_targets, get_emitter

    destinations: List[DestinationCapability] = []
    for target in describe_emit_targets():
        emitter_cls = get_emitter(target.descriptor.format)
        if emitter_cls is None:  # pragma: no cover - registry/describe are always in sync
            continue
        destinations.append(capability_for(emitter_cls))
    return CapabilityRegistrySnapshot(
        version=REGISTRY_VERSION,
        review_date=REVIEW_DATE,
        reason_codes=sorted(REASON_CODES),
        reasons=reason_explanations(),
        destinations=destinations,
    )
