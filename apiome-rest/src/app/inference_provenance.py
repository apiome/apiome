"""Inference provenance vocabulary — declared, inferred, synthesized — FMT-8.6 (#5467).

Every code-first and traffic-shaped source *infers* part of what it hands the canonical model.
An ``.http`` file asserts nothing — Apiome deduces a REST surface from the requests in it. A
Postman collection declares its requests, but the request and response *schemas* are guessed
from example bodies. An Envoy route table is evidence of an API rather than a statement of
one. A TypeScript, Zod or Pydantic module declares its types, but an inline object or a generic
instantiation only becomes a *named* type because Apiome names it.

Before this module each adapter labelled that difference its own way (a ``_PROVENANCE`` constant
here, a ``DECLARED`` / ``INFERRED`` pair there). This is the one vocabulary they all use now:

* :data:`DECLARED` — the source stated the construct. **The default**: a construct whose
  ``extras`` carry no stamp is declared, which is the convention the gateway family set
  (IXH-7.8) and what keeps every declarative format — OpenAPI, protobuf, GraphQL … — correct
  without touching it.
* :data:`INFERRED` — Apiome deduced the construct from an instance or from code: a path
  template generalized from sample URLs, a schema widened from example bodies, a route table
  read as an API.
* :data:`SYNTHESIZED` — Apiome supplied it: a name for an anonymous type, a materialized
  generic instantiation, a type minted for an inline procedure payload. The shape may be
  declared; the construct as a named, addressable thing is Apiome's.

A stamp is two ``extras`` keys on the construct: :data:`PROVENANCE_KEY` (the class) and,
optionally, :data:`PROVENANCE_EVIDENCE_KEY` (one sentence saying what produced it). Adapters
that already record structured evidence (the inferred-spec engine's ``inference_evidence``,
``sample_count``; the gateway family's regex ``pattern``) keep it, and
:func:`provenance_evidence` reads it into the same sentence shape.

Consumers:

* the catalog detail's parsed view (:mod:`app.catalog_parsed_model`) badges each entity and
  reports :func:`summarize_provenance` for the provenance filter;
* the lint engine's ``provenance`` pack (:mod:`app.provenance_lint`) reports the inferred-
  construct ratio, which a style guide can raise to ``error`` to gate publication;
* the import preview ledger (:mod:`app.import_preview_manifest`) classifies an inferred
  entity as ``inferred`` coverage.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Iterator, List, Mapping, Optional, Tuple

from .canonical_model import CanonicalApi

__all__ = [
    "DECLARED",
    "INFERRED",
    "SYNTHESIZED",
    "PROVENANCE_CLASSES",
    "PROVENANCE_KEY",
    "PROVENANCE_EVIDENCE_KEY",
    "PROVENANCE_STAMP_KEYS",
    "INFERENCE_BASED_ADAPTERS",
    "ProvenanceClass",
    "ConstructProvenance",
    "ProvenanceSummary",
    "provenance_extras",
    "provenance_of",
    "provenance_evidence",
    "without_provenance_stamp",
    "iter_construct_provenance",
    "summarize_provenance",
    "non_declared_constructs",
]


class ProvenanceClass(str, Enum):
    """Where a construct in the canonical model came from."""

    DECLARED = "declared"
    INFERRED = "inferred"
    SYNTHESIZED = "synthesized"


#: The source stated the construct (the default for an unstamped construct).
DECLARED = ProvenanceClass.DECLARED.value

#: Apiome deduced the construct from an instance or from code.
INFERRED = ProvenanceClass.INFERRED.value

#: Apiome supplied the construct (a name, an instantiation, a default).
SYNTHESIZED = ProvenanceClass.SYNTHESIZED.value

#: Every class, in the order the UI lists them.
PROVENANCE_CLASSES: Tuple[str, ...] = (DECLARED, INFERRED, SYNTHESIZED)

#: The ``extras`` key carrying a construct's class.
PROVENANCE_KEY = "provenance"

#: The ``extras`` key carrying the one-sentence evidence for a non-declared construct.
PROVENANCE_EVIDENCE_KEY = "provenance_evidence"

#: Both stamp keys — Apiome's bookkeeping, never a source attribute, so an emitter that copies
#: ``extras`` into its output must leave them out.
PROVENANCE_STAMP_KEYS = frozenset({PROVENANCE_KEY, PROVENANCE_EVIDENCE_KEY})

#: The adapters that infer or synthesize part of their model, and what each one stamps. FMT-8.6
#: requires every one of them to stamp the constructs it does not read verbatim; the corpus test
#: (``tests/test_inference_provenance.py``) checks each against its examples.
INFERENCE_BASED_ADAPTERS: Mapping[str, str] = {
    "http-file": "Every construct is inferred from the requests in the file.",
    "postman": "Request and response schemas are inferred from example bodies.",
    "hoppscotch": "Every construct is inferred from the saved requests in the collection.",
    "thunder-client": "Every construct is inferred from the saved requests in the collection.",
    "har": "Every construct is inferred from the captured traffic.",
    "insomnia": "Every construct is inferred from the saved requests in the export.",
    "soapui": "REST interfaces are inferred from their saved requests and mock responses; WSDL "
    "interfaces are declared by their WSDL.",
    "kong": "Paths recovered from regex patterns are inferred.",
    "gateway-api": "Paths recovered from regex patterns are inferred.",
    "envoy-xds": "Every route is inferred from the route table.",
    "istio": "Every route is inferred from the VirtualService.",
    "traefik": "Every route is inferred from the router rules.",
    "nginx": "Every route is inferred from the location blocks.",
    "haproxy": "Every route is inferred from the ACLs.",
    "consul": "Every route is inferred from the service definitions.",
    "tyk": "Every route of a Classic API definition is inferred; a Tyk OAS document is declared.",
    "typescript-types": "Anonymous types and generic instantiations are synthesized.",
    "zod": "Anonymous schemas and generic instantiations are synthesized.",
    "trpc": "Inline procedure payload types are synthesized.",
    "pydantic": "Anonymous types and generic instantiations are synthesized.",
    "cue": "Anonymous types are synthesized.",
    "pkl": "Anonymous types are synthesized.",
    "dhall": "Anonymous types are synthesized.",
    "opcua-nodeset": "The request and response records a method's arguments become are synthesized.",
    "sparkplug": "Every construct of a payload-only import is inferred: a payload does not carry its topic.",
    "ros2": "The enum grouping an interface's constants and an action's feedback channel are synthesized.",
    "lwm2m": "The Objlnk record an object-link resource is typed as is synthesized.",
    "shacl": "The types of anonymous (blank-node) shapes are synthesized.",
    "owl": "A class's asserted individuals listed as an enum (no owl:oneOf closes it) are inferred.",
    "jsonld": "The types of scoped contexts and container maps are synthesized.",
}


def provenance_extras(provenance: str, evidence: Optional[str] = None) -> Dict[str, str]:
    """Build the ``extras`` stamp for one construct.

    Args:
        provenance: One of :data:`PROVENANCE_CLASSES`.
        evidence: One sentence saying what produced the construct; omitted when ``None`` or blank.

    Returns:
        ``{"provenance": …}`` plus ``{"provenance_evidence": …}`` when evidence is given.

    Raises:
        ValueError: For a class outside the vocabulary — a programming error.
    """
    if provenance not in PROVENANCE_CLASSES:
        raise ValueError(f"{provenance!r} is not a provenance class {PROVENANCE_CLASSES}")
    stamp = {PROVENANCE_KEY: provenance}
    if evidence and evidence.strip():
        stamp[PROVENANCE_EVIDENCE_KEY] = evidence.strip()
    return stamp


def provenance_of(extras: Optional[Mapping[str, Any]]) -> str:
    """Read a construct's class from its ``extras``.

    Args:
        extras: The construct's ``extras`` bag (``None`` is an empty bag).

    Returns:
        The stamped class, or :data:`DECLARED` when the construct is unstamped or carries a value
        outside the vocabulary (other subsystems use ``provenance`` for their own words — an
        AWS export's ``"declared"`` policy records, a manifest's ``"declared"`` entities — and
        none of them claims inference).
    """
    value = (extras or {}).get(PROVENANCE_KEY)
    return value if value in (INFERRED, SYNTHESIZED) else DECLARED


def provenance_evidence(extras: Optional[Mapping[str, Any]]) -> Optional[str]:
    """The one-sentence evidence behind a non-declared construct, or ``None``.

    An explicit :data:`PROVENANCE_EVIDENCE_KEY` wins. Otherwise the structured evidence the
    older adapters already record is read into a sentence: the inferred-spec engine's path
    template and sample URLs, its sample count, and the gateway family's regex pattern.

    Args:
        extras: The construct's ``extras`` bag.

    Returns:
        The evidence sentence, or ``None`` for a declared construct or one with no evidence.
    """
    bag = extras or {}
    if provenance_of(bag) == DECLARED:
        return None
    explicit = bag.get(PROVENANCE_EVIDENCE_KEY)
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    path = bag.get("inference_evidence")
    if isinstance(path, Mapping) and path.get("template"):
        samples = path.get("sample_urls") or []
        return f"Path template {path['template']} generalized from {len(samples)} sample URL(s)."
    pattern = bag.get("pattern")
    if isinstance(pattern, str) and pattern:
        return f"Path recovered from the regex pattern {pattern}."
    count = bag.get("sample_count")
    if isinstance(count, int) and not isinstance(count, bool):
        return f"Observed in {count} sample(s)."
    return None


def without_provenance_stamp(extras: Mapping[str, Any]) -> Dict[str, Any]:
    """A copy of ``extras`` without the stamp keys — for emitters that copy extras verbatim.

    Args:
        extras: The construct's ``extras`` bag.

    Returns:
        A new dict holding every key except :data:`PROVENANCE_STAMP_KEYS`.
    """
    return {key: value for key, value in extras.items() if key not in PROVENANCE_STAMP_KEYS}


@dataclass(frozen=True)
class ConstructProvenance:
    """The provenance of one construct in a canonical model.

    Attributes:
        kind: ``service`` | ``operation`` | ``parameter`` | ``message`` | ``type`` | ``channel``.
        key: The construct's canonical key.
        provenance: Its class (:data:`PROVENANCE_CLASSES`).
        evidence: What produced it, for a non-declared construct (see :func:`provenance_evidence`).
    """

    kind: str
    key: str
    provenance: str
    evidence: Optional[str]


def _construct(
    kind: str,
    key: str,
    extras: Mapping[str, Any],
    *,
    parent: Optional[ConstructProvenance] = None,
    fallback_evidence: Optional[str] = None,
) -> ConstructProvenance:
    """Classify one construct from its ``extras``.

    Args:
        kind: The construct kind.
        key: Its canonical key.
        extras: Its ``extras`` bag.
        parent: The enclosing construct, for a parameter or message. An unstamped part of an
            inferred or synthesized operation shares its operation's class and evidence — a
            path parameter of a route Apiome reconstructed is no more declared than the route.
        fallback_evidence: The adapter's own description (:data:`INFERENCE_BASED_ADAPTERS`), used
            when a non-declared construct records no evidence of its own.

    Returns:
        The construct's provenance.
    """
    if PROVENANCE_KEY not in extras and parent is not None and parent.provenance != DECLARED:
        return ConstructProvenance(kind, key, parent.provenance, parent.evidence)
    provenance = provenance_of(extras)
    evidence = provenance_evidence(extras)
    if evidence is None and provenance != DECLARED:
        evidence = fallback_evidence
    return ConstructProvenance(kind, key, provenance, evidence)


def iter_construct_provenance(api: CanonicalApi) -> Iterator[ConstructProvenance]:
    """Walk every construct a provenance ratio counts, in model order.

    The constructs are the addressable ones a user reads in a catalog item: services, their
    operations, each operation's parameters and messages, the named types and the channels.
    Fields, enum values and servers are parts of those and are not counted on their own.

    Args:
        api: The canonical model.

    Yields:
        One :class:`ConstructProvenance` per construct.
    """
    fallback = INFERENCE_BASED_ADAPTERS.get(api.format)
    for service in api.services:
        yield _construct("service", service.key, service.extras, fallback_evidence=fallback)
        for operation in service.operations:
            op = _construct("operation", operation.key, operation.extras, fallback_evidence=fallback)
            yield op
            for parameter in operation.parameters:
                yield _construct(
                    "parameter", parameter.key, parameter.extras, parent=op, fallback_evidence=fallback
                )
            for message in operation.messages:
                yield _construct(
                    "message", message.key, message.extras, parent=op, fallback_evidence=fallback
                )
    for type_ in api.types:
        yield _construct("type", type_.key, type_.extras, fallback_evidence=fallback)
    for channel in api.channels:
        yield _construct("channel", channel.key, channel.extras, fallback_evidence=fallback)


@dataclass(frozen=True)
class ProvenanceSummary:
    """How many of a model's constructs fall in each provenance class.

    Attributes:
        declared: Constructs the source stated.
        inferred: Constructs Apiome deduced.
        synthesized: Constructs Apiome supplied.
    """

    declared: int = 0
    inferred: int = 0
    synthesized: int = 0

    @property
    def total(self) -> int:
        """Every counted construct."""
        return self.declared + self.inferred + self.synthesized

    @property
    def inferred_ratio(self) -> float:
        """The share of constructs that are inferred, ``0.0`` for an empty model."""
        return self.inferred / self.total if self.total else 0.0

    @property
    def inferred_percent(self) -> int:
        """:attr:`inferred_ratio` as a whole percentage (rounded half up)."""
        return int(self.inferred_ratio * 100 + 0.5)

    def as_dict(self) -> Dict[str, Any]:
        """The JSON shape the catalog detail read carries."""
        return {
            "declared": self.declared,
            "inferred": self.inferred,
            "synthesized": self.synthesized,
            "total": self.total,
            "inferred_ratio": round(self.inferred_ratio, 4),
        }


def summarize_provenance(api: Optional[CanonicalApi]) -> ProvenanceSummary:
    """Count a model's constructs per provenance class.

    Args:
        api: The canonical model, or ``None`` (an empty summary).

    Returns:
        The per-class counts.
    """
    if api is None:
        return ProvenanceSummary()
    counts: Dict[str, int] = {name: 0 for name in PROVENANCE_CLASSES}
    for construct in iter_construct_provenance(api):
        counts[construct.provenance] += 1
    return ProvenanceSummary(**counts)


def non_declared_constructs(api: CanonicalApi) -> List[ConstructProvenance]:
    """The inferred and synthesized constructs of a model, in model order.

    Args:
        api: The canonical model.

    Returns:
        Every construct whose class is not :data:`DECLARED`.
    """
    return [c for c in iter_construct_provenance(api) if c.provenance != DECLARED]
