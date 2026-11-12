"""Operational component library — pure domain logic (DCW-3.1, private-suite#2353).

Tenant-scoped reusable *operational* components — parameters, headers, request
bodies, responses, and security bundles — plus schema entries that pin existing
Type Registry (``apiome.primitives``) revisions. This module is side-effect
free: payload validation, semver revision ordering, canonical payload digests,
and the deterministic single-file materializer that projects pinned published
revisions into a document's standard local ``components`` sections with
collision-safe naming and optional ``x-apiome-origin`` provenance.

The transactional lifecycle (draft → publish, immutable published revisions,
pin bookkeeping) lives in :mod:`app.database`; the HTTP surface lives in
:mod:`app.component_library_routes`. Mirroring the DCW-2.3 split, everything
here is deterministic and unit-testable without a database.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

#: Supported component kinds and the local ``components`` section each
#: materializes under. Security bundles expand into individual
#: ``securitySchemes`` entries; schema-kind components materialize the JSON
#: Schema snapshotted from their pinned Type Registry entry.
KIND_SECTIONS: Dict[str, str] = {
    "parameter": "parameters",
    "header": "headers",
    "requestBody": "requestBodies",
    "response": "responses",
    "securityBundle": "securitySchemes",
    "schema": "schemas",
}

COMPONENT_KINDS = frozenset(KIND_SECTIONS)

#: OpenAPI component keys must match ``^[a-zA-Z0-9._-]+$``; the library is
#: stricter (leading letter, bounded length) so materialized names are always
#: valid local component keys without further escaping.
COMPONENT_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")

#: Semver-like revision string: MAJOR.MINOR.PATCH.
SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")

#: The optional provenance extension a materialized component carries.
ORIGIN_KEY = "x-apiome-origin"

_PARAMETER_LOCATIONS = frozenset({"query", "header", "path", "cookie"})
_SECURITY_SCHEME_TYPES = frozenset(
    {"apiKey", "http", "oauth2", "openIdConnect", "mutualTLS"}
)

# ---------------------------------------------------------------------------
# Revisions
# ---------------------------------------------------------------------------


def parse_semver(revision: Any) -> Optional[Tuple[int, int, int]]:
    """Parse ``revision`` as a MAJOR.MINOR.PATCH tuple, or ``None``.

    Args:
        revision: The candidate revision string.

    Returns:
        The numeric ``(major, minor, patch)`` tuple, or ``None`` when the
        value is not a well-formed semver string.
    """
    if not isinstance(revision, str):
        return None
    match = SEMVER_RE.match(revision)
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def semver_greater(candidate: str, baseline: Optional[str]) -> bool:
    """True when ``candidate`` is a strictly higher semver than ``baseline``.

    Publishing uses this as the no-unsafe-downgrade rule: a revision may only
    be published when it is strictly greater than the component's highest
    already-published revision. ``baseline`` of ``None`` (nothing published
    yet) always passes.

    Args:
        candidate: The revision being published.
        baseline: The highest published revision, or ``None``.

    Returns:
        Whether ``candidate`` may be published after ``baseline``.
    """
    parsed = parse_semver(candidate)
    if parsed is None:
        return False
    if baseline is None:
        return True
    parsed_baseline = parse_semver(baseline)
    if parsed_baseline is None:
        return True
    return parsed > parsed_baseline


def payload_digest(payload: Any) -> str:
    """Algorithm-prefixed digest of a canonical payload (``sha256:<hex>``).

    The payload is serialized canonically (sorted keys, compact separators)
    so equal payloads always digest identically regardless of key order.

    Args:
        payload: Any JSON-serializable payload.

    Returns:
        The ``sha256:``-prefixed hex digest string.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Payload validation
# ---------------------------------------------------------------------------


def _error(code: str, message: str, pointer: str = "") -> Dict[str, str]:
    """One structured validation error (mirrors the preservation error shape)."""
    return {"code": code, "message": message, "pointer": pointer}


def validate_component_name(name: Any) -> bool:
    """True when ``name`` is a valid library/local component name."""
    return isinstance(name, str) and bool(COMPONENT_NAME_RE.match(name))


def validate_component_payload(kind: str, payload: Any) -> List[Dict[str, str]]:
    """Validate a canonical payload for ``kind``; return structured errors.

    Validation is intentionally the *minimal* shape contract each OAS kind
    needs to materialize as a standalone local component — full dialect
    validation happens where documents are validated (export/source review).

    Args:
        kind: One of :data:`COMPONENT_KINDS`.
        payload: The candidate canonical payload.

    Returns:
        A list of ``{code, message, pointer}`` errors; empty when valid.
    """
    if kind not in COMPONENT_KINDS:
        return [_error("COMPONENT_KIND_INVALID", f"Unknown component kind: {kind!r}")]
    if not isinstance(payload, dict):
        return [
            _error(
                "COMPONENT_PAYLOAD_TYPE",
                f"A {kind} payload must be a JSON object.",
            )
        ]

    errors: List[Dict[str, str]] = []
    if kind == "parameter":
        name = payload.get("name")
        location = payload.get("in")
        if not isinstance(name, str) or not name:
            errors.append(
                _error("PARAMETER_NAME_REQUIRED", "A parameter requires a name.", "/name")
            )
        if location not in _PARAMETER_LOCATIONS:
            errors.append(
                _error(
                    "PARAMETER_IN_INVALID",
                    "A parameter's 'in' must be query, header, path, or cookie.",
                    "/in",
                )
            )
        if location == "path" and payload.get("required") is not True:
            errors.append(
                _error(
                    "PARAMETER_PATH_REQUIRED",
                    "Path parameters must declare required: true.",
                    "/required",
                )
            )
    elif kind == "header":
        for forbidden in ("name", "in"):
            if forbidden in payload:
                errors.append(
                    _error(
                        "HEADER_FORBIDDEN_KEY",
                        f"A header object must not carry '{forbidden}' "
                        "(the components key names it).",
                        f"/{forbidden}",
                    )
                )
    elif kind == "requestBody":
        if not isinstance(payload.get("content"), dict) or not payload.get("content"):
            errors.append(
                _error(
                    "REQUEST_BODY_CONTENT_REQUIRED",
                    "A request body requires a non-empty content map.",
                    "/content",
                )
            )
    elif kind == "response":
        if not isinstance(payload.get("description"), str) or not payload.get("description"):
            errors.append(
                _error(
                    "RESPONSE_DESCRIPTION_REQUIRED",
                    "A response requires a description.",
                    "/description",
                )
            )
    elif kind == "securityBundle":
        schemes = payload.get("schemes")
        if not isinstance(schemes, dict) or not schemes:
            errors.append(
                _error(
                    "SECURITY_BUNDLE_SCHEMES_REQUIRED",
                    "A security bundle requires a non-empty schemes map.",
                    "/schemes",
                )
            )
        else:
            for scheme_name in sorted(schemes):
                scheme = schemes[scheme_name]
                if not validate_component_name(scheme_name):
                    errors.append(
                        _error(
                            "SECURITY_SCHEME_NAME_INVALID",
                            f"Scheme name {scheme_name!r} is not a valid component key.",
                            f"/schemes/{scheme_name}",
                        )
                    )
                if (
                    not isinstance(scheme, dict)
                    or scheme.get("type") not in _SECURITY_SCHEME_TYPES
                ):
                    errors.append(
                        _error(
                            "SECURITY_SCHEME_TYPE_INVALID",
                            f"Scheme {scheme_name!r} requires a valid type "
                            "(apiKey, http, oauth2, openIdConnect, mutualTLS).",
                            f"/schemes/{scheme_name}/type",
                        )
                    )
    # kind == "schema": the payload is the JSON Schema snapshotted from the
    # pinned Type Registry entry; any JSON object is acceptable here.
    return errors


# ---------------------------------------------------------------------------
# Deterministic materialization
# ---------------------------------------------------------------------------


@dataclass
class MaterializationEntry:
    """One materialized components entry (or the preview of one)."""

    section: str
    name: str
    requested_name: str
    collided: bool
    component_id: str
    revision_id: str
    component_name: str
    revision: str

    def as_dict(self) -> Dict[str, Any]:
        """The camelCase wire shape used by the preview endpoint."""
        return {
            "section": self.section,
            "name": self.name,
            "requestedName": self.requested_name,
            "collided": self.collided,
            "componentId": self.component_id,
            "revisionId": self.revision_id,
            "componentName": self.component_name,
            "revision": self.revision,
        }


@dataclass
class MaterializationResult:
    """The materialized document plus the deterministic naming record."""

    document: Dict[str, Any]
    entries: List[MaterializationEntry] = field(default_factory=list)

    @property
    def collisions(self) -> List[MaterializationEntry]:
        """The entries whose requested name was taken and were renamed."""
        return [entry for entry in self.entries if entry.collided]


def _origin_block(row: Dict[str, Any]) -> Dict[str, str]:
    """The ``x-apiome-origin`` provenance for one pinned revision."""
    return {
        "library": str(row.get("component_name") or ""),
        "revision": str(row.get("revision") or ""),
        "componentId": str(row.get("component_id") or ""),
        "revisionId": str(row.get("revision_id") or ""),
    }


def _sort_key(row: Dict[str, Any]) -> Tuple[str, str, Tuple[int, int, int], str]:
    """Deterministic materialization order: section, name, semver, revision id."""
    section = KIND_SECTIONS.get(str(row.get("kind")), "")
    requested = str(row.get("local_name") or row.get("component_name") or "")
    semver = parse_semver(row.get("revision")) or (0, 0, 0)
    return (section, requested, semver, str(row.get("revision_id") or ""))


def _allocate_name(base: str, taken: set) -> Tuple[str, bool]:
    """Collision-safe local name: ``base``, else ``base_2``, ``base_3``, …

    Never returns a name already in ``taken`` — a pinned component can never
    overwrite a local component (or an earlier materialized entry).
    """
    if base not in taken:
        taken.add(base)
        return base, False
    suffix = 2
    while f"{base}_{suffix}" in taken:
        suffix += 1
    name = f"{base}_{suffix}"
    taken.add(name)
    return name, True


def materialize_pinned_components(
    document: Dict[str, Any],
    pin_rows: List[Dict[str, Any]],
    *,
    include_origin: bool = True,
) -> MaterializationResult:
    """Project pinned published revisions into local ``components`` sections.

    Deterministic single-file materialization (DCW-3.1): rows are processed in
    a stable order (section, requested name, semver, revision id), names are
    allocated collision-safely (a local component is never overwritten), the
    exported document resolves with standard local ``$ref`` values and no
    Apiome services, and each materialized object optionally carries an
    ``x-apiome-origin`` provenance block that can be stripped without
    invalidating the document.

    Args:
        document: The generated OpenAPI document. Not mutated — a deep copy
            is returned.
        pin_rows: Pin join rows, each with ``kind``, ``component_name``,
            ``local_name`` (optional), ``revision``, ``payload``,
            ``component_id``, and ``revision_id``.
        include_origin: Whether materialized objects carry ``x-apiome-origin``.

    Returns:
        A :class:`MaterializationResult` with the materialized document and
        the per-entry naming record (requested name, final name, collisions).
    """
    result_document = copy.deepcopy(document)
    result = MaterializationResult(document=result_document)
    if not pin_rows:
        return result

    components = result_document.setdefault("components", {})
    taken_by_section: Dict[str, set] = {}

    def _taken(section: str) -> set:
        if section not in taken_by_section:
            existing = components.get(section)
            taken_by_section[section] = set(existing) if isinstance(existing, dict) else set()
        return taken_by_section[section]

    for row in sorted(pin_rows, key=_sort_key):
        kind = str(row.get("kind"))
        section = KIND_SECTIONS.get(kind)
        payload = row.get("payload")
        if section is None or not isinstance(payload, dict):
            continue
        target = components.setdefault(section, {})

        if kind == "securityBundle":
            schemes = payload.get("schemes")
            if not isinstance(schemes, dict):
                continue
            for scheme_name in sorted(schemes):
                scheme = schemes[scheme_name]
                if not isinstance(scheme, dict):
                    continue
                name, collided = _allocate_name(scheme_name, _taken(section))
                materialized = copy.deepcopy(scheme)
                if include_origin:
                    materialized[ORIGIN_KEY] = _origin_block(row)
                target[name] = materialized
                result.entries.append(
                    MaterializationEntry(
                        section=section,
                        name=name,
                        requested_name=scheme_name,
                        collided=collided,
                        component_id=str(row.get("component_id") or ""),
                        revision_id=str(row.get("revision_id") or ""),
                        component_name=str(row.get("component_name") or ""),
                        revision=str(row.get("revision") or ""),
                    )
                )
            continue

        requested = str(row.get("local_name") or row.get("component_name") or "")
        if not requested:
            continue
        name, collided = _allocate_name(requested, _taken(section))
        materialized = copy.deepcopy(payload)
        if include_origin:
            materialized[ORIGIN_KEY] = _origin_block(row)
        target[name] = materialized
        result.entries.append(
            MaterializationEntry(
                section=section,
                name=name,
                requested_name=requested,
                collided=collided,
                component_id=str(row.get("component_id") or ""),
                revision_id=str(row.get("revision_id") or ""),
                component_name=str(row.get("component_name") or ""),
                revision=str(row.get("revision") or ""),
            )
        )

    return result


def strip_origin_metadata(document: Dict[str, Any]) -> int:
    """Remove every ``x-apiome-origin`` block under ``components`` in place.

    Re-import must retain origin metadata when present but stay valid when it
    is removed; this helper (and its tests) prove the removal side.

    Args:
        document: An OpenAPI document (mutated in place).

    Returns:
        The number of origin blocks removed.
    """
    components = document.get("components")
    if not isinstance(components, dict):
        return 0
    removed = 0
    for section_value in components.values():
        if not isinstance(section_value, dict):
            continue
        for entry in section_value.values():
            if isinstance(entry, dict) and ORIGIN_KEY in entry:
                del entry[ORIGIN_KEY]
                removed += 1
    return removed
