"""Round-trip preservation envelope — DCW-2.1 (private-suite#2352).

A visual editor cannot be a trustworthy source of truth if save/export drops
valid OpenAPI data it has not normalized. The **preservation envelope** is the
version-scoped payload that carries every unknown-but-valid field and ``x-*``
extension of an imported document, keyed by RFC 6901 JSON Pointer, with optional
source-file/digest provenance — so the canonical model plus its envelope
reconstruct the source **semantically unchanged**.

The three core operations are pure functions over plain JSON values:

* :func:`extract_envelope` — walk an imported source document against the
  canonical document the model can represent and collect everything the model
  did *not* absorb (unknown fields anywhere, including under arrays; ``$ref``
  siblings; extensions whose value is ``null`` / ``false`` / empty).
* :func:`validate_envelope` — validate an envelope against the DCW-0.1
  capability matrix and a canonical document: unsupported dialects, malformed
  or duplicate pointers, claims nested inside other claims, canonical/preserved
  collisions for the same pointer, and an oversized envelope all yield
  **structured, deterministic** errors (sorted by pointer, then code) and never
  a partial result.
* :func:`apply_envelope` — deterministically merge an envelope back into a
  canonical document: parents before children, array insertions in ascending
  index order (numeric-aware, so ``/a/10`` follows ``/a/2``), missing
  intermediate containers created by segment shape, insertion indices clamped
  to the array length. All-or-nothing: any collision returns the canonical
  document **unchanged** plus the structured errors.

Envelope maintenance mirrors the editing operations DCW-2.3 will feed it:

* :func:`move_claims` — relocate every claim under one pointer prefix to
  another (a rename/move in the visual editor), rejecting collisions.
* :func:`delete_canonical_subtree` — a canonical deletion at a pointer drops
  the claims inside the deleted subtree and **rebases the array indices** of
  sibling claims after a deleted array element, so preserved data neither leaks
  into the wrong slot nor silently survives its parent.

:func:`semantic_fingerprint` hashes the canonical JSON form (sorted keys,
compact separators) and always reports the **intentionally excluded lexical
differences** (comments, anchors, key order, quoting, whitespace, multi-file
layout) from the DCW-0.1 fidelity contract, so "unchanged" is never over-claimed.

Everything here is pure and side-effect free: no DB, no network, inputs are
never mutated. Persistence lives in ``database.py`` / ``preservation_routes.py``.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

from pydantic import BaseModel, ConfigDict, Field

from .oas_resource_limits import (
    capability_for_pointer,
    lexical_exclusions,
    resource_limit_values,
    supported_dialects,
)

__all__ = [
    "ENVELOPE_VERSION",
    "SEMANTIC_FINGERPRINT_ALGORITHM",
    "PreservationClaim",
    "PreservationEnvelope",
    "EnvelopeError",
    "ClaimClassification",
    "EnvelopeValidationReport",
    "SemanticFingerprint",
    "parse_pointer",
    "format_pointer",
    "pointer_exists",
    "extract_envelope",
    "validate_envelope",
    "apply_envelope",
    "move_claims",
    "delete_canonical_subtree",
    "semantic_fingerprint",
]

#: Version of the envelope payload contract, stored with every envelope.
ENVELOPE_VERSION = "1.0.0"

#: Identifier of the fingerprint canonicalization; bump when its rules change.
SEMANTIC_FINGERPRINT_ALGORITHM = "sha256-oas-semantic-v1"


class PreservationClaim(BaseModel):
    """One preserved value: an RFC 6901 pointer and the subtree it carries."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    pointer: str = Field(description="RFC 6901 JSON Pointer of the preserved value.")
    value: Any = Field(
        default=None,
        description="The preserved subtree verbatim. null, false, and empty "
        "containers are all legal preserved values.",
    )
    source_file: Optional[str] = Field(
        default=None,
        alias="sourceFile",
        description="Original file path within a multi-file source layout, when known.",
    )
    source_digest: Optional[str] = Field(
        default=None,
        alias="sourceDigest",
        description="Algorithm-prefixed digest (e.g. sha256:<hex>) of the "
        "originating source file at import time, when known.",
    )


class PreservationEnvelope(BaseModel):
    """The version-scoped set of preservation claims for one revision."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    envelope_version: str = Field(
        default=ENVELOPE_VERSION,
        alias="envelopeVersion",
        description="Version of the envelope payload contract.",
    )
    dialect: str = Field(
        description="The OAS dialect the claims were extracted under (e.g. 3.1.0)."
    )
    claims: List[PreservationClaim] = Field(
        default_factory=list,
        description="Preserved values, sorted deterministically by pointer.",
    )


class EnvelopeError(BaseModel):
    """One structured envelope validation/apply error (never a raw exception)."""

    model_config = ConfigDict(extra="forbid")

    code: Literal[
        "PRESERVATION_DIALECT_UNSUPPORTED",
        "PRESERVATION_POINTER_INVALID",
        "PRESERVATION_DUPLICATE_POINTER",
        "PRESERVATION_NESTED_CLAIM",
        "PRESERVATION_POINTER_COLLISION",
        "PRESERVATION_ENVELOPE_TOO_LARGE",
        "PRESERVATION_ARRAY_INDEX_INVALID",
    ] = Field(description="Stable machine-readable code for the failure class.")
    pointer: str = Field(default="", description="The claim pointer the error concerns.")
    message: str = Field(description="Human-readable explanation.")


class ClaimClassification(BaseModel):
    """A claim's capability classification under the DCW-0.1 matrix."""

    model_config = ConfigDict(extra="forbid")

    pointer: str = Field(description="The claim pointer.")
    capability: str = Field(
        description="Capability state from the matrix (extension claims resolve "
        "to the matrix extensionCapability; unmatched pointers to defaultCapability)."
    )


class EnvelopeValidationReport(BaseModel):
    """Deterministic validation outcome: errors sorted by (pointer, code)."""

    model_config = ConfigDict(extra="forbid")

    ok: bool = Field(description="True iff the envelope has no errors.")
    errors: List[EnvelopeError] = Field(default_factory=list)
    classifications: List[ClaimClassification] = Field(
        default_factory=list,
        description="Per-claim capability classification, sorted by pointer.",
    )


class SemanticFingerprint(BaseModel):
    """A semantic fingerprint plus the lexical differences it does not see."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    fingerprint: str = Field(description="64-char lowercase hex SHA-256 digest.")
    algorithm: str = Field(default=SEMANTIC_FINGERPRINT_ALGORITHM)
    lexical_exclusions: List[str] = Field(
        alias="lexicalExclusions",
        description="Lexical characteristics intentionally excluded from the "
        "comparison (DCW-0.1 fidelity contract): equal fingerprints do NOT "
        "promise these were preserved.",
    )


# ===========================================================================
# JSON Pointer utilities (RFC 6901)
# ===========================================================================


def parse_pointer(pointer: str) -> List[str]:
    """Split an RFC 6901 pointer into unescaped segments.

    Args:
        pointer: ``""`` (the root) or a string starting with ``/``.

    Returns:
        The list of unescaped segments (empty for the root pointer).

    Raises:
        ValueError: If the pointer is non-empty and does not start with ``/``.
    """
    if pointer == "":
        return []
    if not pointer.startswith("/"):
        raise ValueError(f"invalid JSON Pointer {pointer!r}: must be '' or start with '/'")
    return [seg.replace("~1", "/").replace("~0", "~") for seg in pointer[1:].split("/")]


def format_pointer(segments: List[str]) -> str:
    """Join unescaped segments back into an RFC 6901 pointer string."""
    return "".join("/" + seg.replace("~", "~0").replace("/", "~1") for seg in segments)


def _resolve(document: Any, segments: List[str]) -> Tuple[bool, Any]:
    """Resolve segments against ``document``; return (found, value)."""
    node = document
    for seg in segments:
        if isinstance(node, dict):
            if seg not in node:
                return False, None
            node = node[seg]
        elif isinstance(node, list):
            if not _is_array_index(seg):
                return False, None
            idx = int(seg)
            if idx >= len(node):
                return False, None
            node = node[idx]
        else:
            return False, None
    return True, node


def pointer_exists(document: Any, pointer: str) -> bool:
    """Whether ``pointer`` resolves to a value inside ``document``."""
    try:
        segments = parse_pointer(pointer)
    except ValueError:
        return False
    found, _ = _resolve(document, segments)
    return found


def _is_array_index(segment: str) -> bool:
    """RFC 6901 array index: '0' or a nonzero digit string (no leading zeros)."""
    if not segment.isdigit():
        return False
    return segment == "0" or not segment.startswith("0")


def _pointer_sort_key(pointer: str) -> Tuple:
    """Deterministic, numeric-aware ordering key: parents first, ``/a/2`` < ``/a/10``."""
    segments = parse_pointer(pointer)
    key: List[Tuple[int, Union[int, str]]] = []
    for seg in segments:
        if _is_array_index(seg):
            key.append((0, int(seg)))
        else:
            key.append((1, seg))
    return (len(segments), tuple(key))


def _sorted_claims(claims: List[PreservationClaim]) -> List[PreservationClaim]:
    """Claims in the canonical deterministic order (parents first, numeric-aware)."""
    return sorted(claims, key=lambda c: _pointer_sort_key(c.pointer))


# ===========================================================================
# Extraction
# ===========================================================================


def extract_envelope(
    source_document: Any,
    canonical_document: Any,
    dialect: str,
    *,
    source_file: Optional[str] = None,
    source_digest: Optional[str] = None,
) -> PreservationEnvelope:
    """Collect everything ``source_document`` carries that the canonical model did not absorb.

    The walk descends both documents in parallel. A source mapping key missing
    from the canonical node — an unknown-but-valid field, an ``x-*`` extension,
    a ``$ref`` sibling — becomes one claim carrying its whole subtree. Source
    array elements beyond the canonical array's length become index claims, so
    unknown fields *under arrays* survive. Where both sides hold a value the
    canonical one is authoritative (it round-trips through the model itself),
    so no claim is recorded.

    Args:
        source_document: The parsed imported document (plain JSON values).
        canonical_document: The document the canonical model exports today.
        dialect: The OAS dialect the source declares (e.g. ``"3.1.0"``).
        source_file: Optional provenance file path stamped on every claim.
        source_digest: Optional provenance digest stamped on every claim.

    Returns:
        A :class:`PreservationEnvelope` with deterministically sorted claims.
        Inputs are not mutated.
    """
    claims: List[PreservationClaim] = []

    def _walk(src: Any, canon: Any, segments: List[str]) -> None:
        if isinstance(src, dict) and isinstance(canon, dict):
            for key in src:
                if key in canon:
                    _walk(src[key], canon[key], segments + [key])
                else:
                    claims.append(
                        PreservationClaim(
                            pointer=format_pointer(segments + [key]),
                            value=copy.deepcopy(src[key]),
                            source_file=source_file,
                            source_digest=source_digest,
                        )
                    )
            return
        if isinstance(src, list) and isinstance(canon, list):
            for idx, item in enumerate(src):
                if idx < len(canon):
                    _walk(item, canon[idx], segments + [str(idx)])
                else:
                    claims.append(
                        PreservationClaim(
                            pointer=format_pointer(segments + [str(idx)]),
                            value=copy.deepcopy(item),
                            source_file=source_file,
                            source_digest=source_digest,
                        )
                    )
            return
        # Scalar/mismatched nodes: the canonical value is authoritative.

    _walk(source_document, canonical_document, [])
    return PreservationEnvelope(dialect=dialect, claims=_sorted_claims(claims))


# ===========================================================================
# Validation
# ===========================================================================


def validate_envelope(
    envelope: PreservationEnvelope,
    canonical_document: Any,
) -> EnvelopeValidationReport:
    """Validate ``envelope`` against the capability matrix and a canonical document.

    Checks, in deterministic order (errors sorted by pointer, then code):

    * the dialect is one the DCW-0.1 matrix supports;
    * every pointer is well-formed and non-root;
    * no two claims share a pointer (``PRESERVATION_DUPLICATE_POINTER``);
    * no claim lies inside another claim's subtree (``PRESERVATION_NESTED_CLAIM``);
    * no claim collides with a canonical value at the same pointer
      (``PRESERVATION_POINTER_COLLISION`` — canonical and preserved claims for
      one pointer are always rejected, never merged silently);
    * the serialized envelope stays inside the DCW-0.2 document-size bound
      (``PRESERVATION_ENVELOPE_TOO_LARGE``).

    Args:
        envelope: The envelope to validate.
        canonical_document: The canonical document the claims would merge into.

    Returns:
        An :class:`EnvelopeValidationReport`; ``classifications`` carries every
        structurally valid claim's capability state. Inputs are not mutated.
    """
    errors: List[EnvelopeError] = []
    classifications: List[ClaimClassification] = []

    dialect_ok = envelope.dialect in supported_dialects()
    if not dialect_ok:
        errors.append(
            EnvelopeError(
                code="PRESERVATION_DIALECT_UNSUPPORTED",
                message=(
                    f"Dialect {envelope.dialect!r} is not a supported OAS dialect "
                    f"({', '.join(supported_dialects())})."
                ),
            )
        )

    seen: Dict[str, int] = {}
    valid_pointers: List[str] = []
    for claim in envelope.claims:
        try:
            segments = parse_pointer(claim.pointer)
        except ValueError:
            errors.append(
                EnvelopeError(
                    code="PRESERVATION_POINTER_INVALID",
                    pointer=claim.pointer,
                    message=f"Claim pointer {claim.pointer!r} is not a valid JSON Pointer.",
                )
            )
            continue
        if not segments:
            errors.append(
                EnvelopeError(
                    code="PRESERVATION_POINTER_INVALID",
                    pointer=claim.pointer,
                    message="A claim cannot target the document root.",
                )
            )
            continue
        if claim.pointer in seen:
            errors.append(
                EnvelopeError(
                    code="PRESERVATION_DUPLICATE_POINTER",
                    pointer=claim.pointer,
                    message=f"Pointer {claim.pointer!r} is claimed more than once.",
                )
            )
            continue
        seen[claim.pointer] = 1
        valid_pointers.append(claim.pointer)

    # Nested claims: a claim strictly inside another claim's subtree is ambiguous
    # (its value would be unreachable after the parent claim applies).
    pointer_set = set(valid_pointers)
    for pointer in valid_pointers:
        segments = parse_pointer(pointer)
        for cut in range(1, len(segments)):
            ancestor = format_pointer(segments[:cut])
            if ancestor in pointer_set:
                errors.append(
                    EnvelopeError(
                        code="PRESERVATION_NESTED_CLAIM",
                        pointer=pointer,
                        message=(
                            f"Claim {pointer!r} lies inside claimed subtree {ancestor!r}; "
                            "merge it into the ancestor claim."
                        ),
                    )
                )
                break

    # Canonical/preserved collision: same pointer claimed by both worlds.
    for pointer in valid_pointers:
        if pointer_exists(canonical_document, pointer):
            errors.append(
                EnvelopeError(
                    code="PRESERVATION_POINTER_COLLISION",
                    pointer=pointer,
                    message=(
                        f"Pointer {pointer!r} already holds a canonical value; canonical "
                        "and preserved claims for the same pointer are rejected."
                    ),
                )
            )

    limits = resource_limit_values()
    serialized_bytes = len(
        json.dumps(
            [claim.model_dump(mode="json", by_alias=True) for claim in envelope.claims],
            ensure_ascii=False,
        ).encode("utf-8")
    )
    if serialized_bytes > limits.max_document_bytes:
        errors.append(
            EnvelopeError(
                code="PRESERVATION_ENVELOPE_TOO_LARGE",
                message=(
                    f"Serialized envelope is {serialized_bytes} bytes; "
                    f"the limit is {limits.max_document_bytes} bytes."
                ),
            )
        )

    if dialect_ok:
        for pointer in sorted(valid_pointers, key=_pointer_sort_key):
            classifications.append(
                ClaimClassification(
                    pointer=pointer,
                    capability=capability_for_pointer(envelope.dialect, pointer),
                )
            )

    errors.sort(key=lambda e: (_safe_sort_key(e.pointer), e.code))
    return EnvelopeValidationReport(ok=not errors, errors=errors, classifications=classifications)


def _safe_sort_key(pointer: str) -> Tuple:
    """Sort key that tolerates malformed pointers (they sort by raw text)."""
    try:
        return (0,) + _pointer_sort_key(pointer)
    except ValueError:
        return (1, pointer)


# ===========================================================================
# Application (merge)
# ===========================================================================


def apply_envelope(
    canonical_document: Any,
    envelope: PreservationEnvelope,
) -> Tuple[Any, List[EnvelopeError]]:
    """Deterministically merge ``envelope`` into a copy of ``canonical_document``.

    Claims apply in the canonical order (parents before children, array indices
    numeric-ascending). Dictionary claims **insert** their key; a key that
    already exists is a collision. Array claims **insert at** their index,
    clamped to the array length (so ``/arr/7`` on a 3-element array appends
    deterministically); ascending order makes interleaved source/canonical
    array layouts reconstruct exactly. Missing intermediate containers are
    created by segment shape (numeric segment → list, otherwise dict).

    The merge is all-or-nothing: on any error the returned document is the
    canonical input **unchanged** (same content; the input object itself is
    never mutated either way).

    Args:
        canonical_document: The canonical document (not mutated).
        envelope: The claims to merge.

    Returns:
        ``(merged_document, errors)`` — ``errors`` is empty on success and the
        merged document is a deep copy with every claim applied; on failure the
        first document equals the canonical input and ``errors`` is sorted.
    """
    merged = copy.deepcopy(canonical_document)
    errors: List[EnvelopeError] = []

    for claim in _sorted_claims(envelope.claims):
        try:
            segments = parse_pointer(claim.pointer)
        except ValueError:
            errors.append(
                EnvelopeError(
                    code="PRESERVATION_POINTER_INVALID",
                    pointer=claim.pointer,
                    message=f"Claim pointer {claim.pointer!r} is not a valid JSON Pointer.",
                )
            )
            continue
        if not segments:
            errors.append(
                EnvelopeError(
                    code="PRESERVATION_POINTER_INVALID",
                    pointer=claim.pointer,
                    message="A claim cannot target the document root.",
                )
            )
            continue
        error = _insert_at(merged, segments, copy.deepcopy(claim.value), claim.pointer)
        if error is not None:
            errors.append(error)

    if errors:
        errors.sort(key=lambda e: (_safe_sort_key(e.pointer), e.code))
        return copy.deepcopy(canonical_document), errors
    return merged, []


def _insert_at(
    document: Any, segments: List[str], value: Any, pointer: str
) -> Optional[EnvelopeError]:
    """Insert ``value`` at ``segments`` inside ``document`` (mutating), or explain why not."""
    node = document
    for depth, seg in enumerate(segments[:-1]):
        next_seg = segments[depth + 1]
        if isinstance(node, dict):
            if seg not in node:
                node[seg] = [] if _is_array_index(next_seg) or next_seg == "-" else {}
            node = node[seg]
        elif isinstance(node, list):
            if not _is_array_index(seg):
                return EnvelopeError(
                    code="PRESERVATION_ARRAY_INDEX_INVALID",
                    pointer=pointer,
                    message=f"Segment {seg!r} of {pointer!r} indexes an array but is not numeric.",
                )
            idx = int(seg)
            if idx == len(node):
                # A fresh element this envelope is building up (e.g. /x-list/0/name
                # on an empty list): append a container shaped by the next segment.
                node.append([] if _is_array_index(next_seg) or next_seg == "-" else {})
            elif idx > len(node):
                # Beyond-the-end intermediate positions must exist; a claim cannot
                # invent canonical siblings it never preserved.
                return EnvelopeError(
                    code="PRESERVATION_ARRAY_INDEX_INVALID",
                    pointer=pointer,
                    message=(
                        f"Segment {seg!r} of {pointer!r} is beyond the end of its array "
                        f"(length {len(node)})."
                    ),
                )
            node = node[idx]
        else:
            return EnvelopeError(
                code="PRESERVATION_POINTER_COLLISION",
                pointer=pointer,
                message=(
                    f"Pointer {pointer!r} descends through a canonical scalar; canonical "
                    "and preserved claims for the same pointer are rejected."
                ),
            )

    last = segments[-1]
    if isinstance(node, dict):
        if last in node:
            return EnvelopeError(
                code="PRESERVATION_POINTER_COLLISION",
                pointer=pointer,
                message=(
                    f"Pointer {pointer!r} already holds a canonical value; canonical "
                    "and preserved claims for the same pointer are rejected."
                ),
            )
        node[last] = value
        return None
    if isinstance(node, list):
        if last == "-":
            node.append(value)
            return None
        if not _is_array_index(last):
            return EnvelopeError(
                code="PRESERVATION_ARRAY_INDEX_INVALID",
                pointer=pointer,
                message=f"Segment {last!r} of {pointer!r} indexes an array but is not numeric.",
            )
        node.insert(min(int(last), len(node)), value)
        return None
    return EnvelopeError(
        code="PRESERVATION_POINTER_COLLISION",
        pointer=pointer,
        message=(
            f"Pointer {pointer!r} descends through a canonical scalar; canonical "
            "and preserved claims for the same pointer are rejected."
        ),
    )


# ===========================================================================
# Envelope maintenance (move / canonical delete)
# ===========================================================================


def move_claims(
    envelope: PreservationEnvelope,
    from_pointer: str,
    to_pointer: str,
) -> Tuple[PreservationEnvelope, List[EnvelopeError]]:
    """Relocate every claim at/under ``from_pointer`` to live under ``to_pointer``.

    This is the envelope side of a rename/move in the editor: preserved data
    follows its canonical parent. The rewrite is all-or-nothing — if any moved
    pointer would collide with an existing claim, the returned envelope equals
    the input and the collisions are reported.

    Args:
        envelope: The envelope to rewrite (not mutated).
        from_pointer: Prefix to move (must be a valid non-root pointer).
        to_pointer: New prefix (must be a valid non-root pointer).

    Returns:
        ``(new_envelope, errors)`` with deterministically sorted claims/errors.
    """
    try:
        from_segments = parse_pointer(from_pointer)
        to_segments = parse_pointer(to_pointer)
    except ValueError as exc:
        return envelope, [
            EnvelopeError(
                code="PRESERVATION_POINTER_INVALID",
                pointer=from_pointer,
                message=str(exc),
            )
        ]
    if not from_segments or not to_segments:
        return envelope, [
            EnvelopeError(
                code="PRESERVATION_POINTER_INVALID",
                pointer=from_pointer if not from_segments else to_pointer,
                message="Move endpoints cannot be the document root.",
            )
        ]

    moved: List[PreservationClaim] = []
    kept: List[PreservationClaim] = []
    for claim in envelope.claims:
        if claim.pointer == from_pointer or claim.pointer.startswith(from_pointer + "/"):
            suffix = claim.pointer[len(from_pointer):]
            moved.append(claim.model_copy(update={"pointer": to_pointer + suffix}))
        else:
            kept.append(claim)

    kept_pointers = {c.pointer for c in kept}
    errors: List[EnvelopeError] = []
    for claim in moved:
        if claim.pointer in kept_pointers:
            errors.append(
                EnvelopeError(
                    code="PRESERVATION_DUPLICATE_POINTER",
                    pointer=claim.pointer,
                    message=(
                        f"Moving {from_pointer!r} to {to_pointer!r} collides with the "
                        f"existing claim at {claim.pointer!r}."
                    ),
                )
            )
    if errors:
        errors.sort(key=lambda e: (_safe_sort_key(e.pointer), e.code))
        return envelope, errors

    return (
        envelope.model_copy(update={"claims": _sorted_claims(kept + moved)}),
        [],
    )


def delete_canonical_subtree(
    envelope: PreservationEnvelope,
    pointer: str,
) -> Tuple[PreservationEnvelope, List[PreservationClaim]]:
    """Apply a canonical deletion at ``pointer`` to the envelope.

    Claims at/under the deleted pointer are dropped (preserved data does not
    outlive its parent) and returned so the caller can audit or offer recovery.
    When the deleted node is an **array element**, sibling claims at higher
    indices of the same array are rebased down by one, keeping insertion
    positions meaningful after the delete.

    Args:
        envelope: The envelope to rewrite (not mutated).
        pointer: The canonical pointer that was deleted (non-root).

    Returns:
        ``(new_envelope, dropped_claims)``; both deterministically sorted.

    Raises:
        ValueError: If ``pointer`` is malformed or the root.
    """
    segments = parse_pointer(pointer)
    if not segments:
        raise ValueError("cannot delete the document root")

    parent = format_pointer(segments[:-1])
    last = segments[-1]
    deleted_is_index = _is_array_index(last)
    deleted_index = int(last) if deleted_is_index else -1

    kept: List[PreservationClaim] = []
    dropped: List[PreservationClaim] = []
    for claim in envelope.claims:
        if claim.pointer == pointer or claim.pointer.startswith(pointer + "/"):
            dropped.append(claim)
            continue
        if deleted_is_index and (
            claim.pointer.startswith(parent + "/") or parent == ""
        ):
            claim_segments = parse_pointer(claim.pointer)
            prefix_len = len(segments) - 1
            if (
                len(claim_segments) > prefix_len
                and claim_segments[:prefix_len] == segments[:-1]
                and _is_array_index(claim_segments[prefix_len])
                and int(claim_segments[prefix_len]) > deleted_index
            ):
                rebased = list(claim_segments)
                rebased[prefix_len] = str(int(claim_segments[prefix_len]) - 1)
                kept.append(claim.model_copy(update={"pointer": format_pointer(rebased)}))
                continue
        kept.append(claim)

    return (
        envelope.model_copy(update={"claims": _sorted_claims(kept)}),
        _sorted_claims(dropped),
    )


# ===========================================================================
# Semantic fingerprint
# ===========================================================================


def semantic_fingerprint(document: Any) -> SemanticFingerprint:
    """Fingerprint the semantic content of a document, reporting lexical exclusions.

    Two documents that differ only lexically — key order, quoting, whitespace,
    comments, anchors, original file layout — hash identically, and the result
    names those exclusions explicitly so an equal fingerprint is never read as
    a lexical-fidelity promise (DCW-0.1 fidelity contract).

    Args:
        document: A parsed JSON-compatible document.

    Returns:
        A :class:`SemanticFingerprint` with a byte-stable SHA-256 digest
        (sorted keys, compact separators, no ASCII escaping).
    """
    serialized = json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return SemanticFingerprint(
        fingerprint=hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
        lexical_exclusions=lexical_exclusions(),
    )
