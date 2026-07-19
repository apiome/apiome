"""Source-to-model change review — DCW-2.3 (private-suite#2360).

Valid source text may not silently mutate the canonical model. This module is
the **pure classification engine** behind the review/apply endpoints: it diffs
an edited source document (the *candidate*) against the revision's current
merged document (server-generated canonical + live preservation envelope,
DCW-2.1) and produces a deterministic, structured change set:

* every change is an **addition**, **update**, or **deletion**, or an
  **unsupported-preserved** change when the DCW-0.1 capability matrix says the
  pointer lives outside the visually-editable model and round-trips through
  the preservation envelope instead;
* every change is grouped by **document**, **path**, **operation**,
  **component**, or **schema**, with a stable group key and a human label;
* **blockers** explain, before anything is written, why an apply cannot
  proceed: deleting a component that is still referenced (with every
  referencing pointer listed), changing model-owned values that the server
  generates from project/version records, or response shapes the relational
  model cannot represent;
* the same **dialect validation** (:mod:`app.openapi_validator` meta-schemas)
  and **local ``$ref`` integrity** checks the export surface applies run here,
  so review and export can never disagree about validity.

The **change-set digest** binds a reviewed candidate to the base revision it
was reviewed against; the apply transaction records it for idempotent replay.

Everything here is pure and side-effect free: no DB, no network, inputs are
never mutated. Persistence lives in ``database.py`` / ``source_review_routes.py``.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Literal, Tuple

from pydantic import BaseModel, ConfigDict, Field

from .oas_resource_limits import capability_for_pointer
from .preservation_envelope import (
    format_pointer,
    parse_pointer,
    pointer_exists,
    semantic_fingerprint,
)

__all__ = [
    "CHANGE_SET_DIGEST_ALGORITHM",
    "SourceChange",
    "SourceChangeBlocker",
    "SourceChangeCounts",
    "SourceChangeSet",
    "RefIntegrityError",
    "build_source_change_set",
    "change_set_digest",
    "diff_documents",
    "ref_integrity_errors",
    "scope_for_pointer",
]

#: Identifier of the change-set digest scheme; bump when its inputs change.
CHANGE_SET_DIGEST_ALGORITHM = "sha256-source-change-set-v1"

#: HTTP methods that identify an operation key under a path item (OAS 3.2
#: adds ``query``; ``paths_generator`` emits every one of these).
_OPERATION_METHODS = {
    "get",
    "put",
    "post",
    "delete",
    "options",
    "head",
    "patch",
    "trace",
    "query",
}

#: Capability classes that round-trip through the preservation envelope
#: rather than the relational canonical model (DCW-0.1 capability matrix).
_PRESERVED_CAPABILITIES = {"preserved-read-only", "unsupported", "converted-with-review"}

#: Top-level document keys the server generates from project/version records.
#: Changing or deleting their existing values through source apply would be a
#: cross-surface mutation (the metadata inspector owns /info and /x-metadata,
#: DCW-1.2; the dialect capability contract owns /openapi, DCW-0.1), so the
#: review reports a blocker instead of allowing a silent overwrite.
_MODEL_OWNED_PREFIXES = ("/openapi", "/info", "/x-metadata")

ChangeKind = Literal["addition", "update", "deletion", "unsupported-preserved"]
ChangeScope = Literal["document", "path", "operation", "component", "schema"]


class SourceChange(BaseModel):
    """One reviewed difference between the base document and the candidate."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    kind: ChangeKind = Field(description="addition | update | deletion | unsupported-preserved.")
    scope: ChangeScope = Field(
        description="Grouping surface: document, path, operation, component, or schema."
    )
    group: str = Field(description="Stable group key within the scope (e.g. 'GET /pets').")
    pointer: str = Field(description="RFC 6901 JSON Pointer of the changed value.")
    label: str = Field(description="Human-readable one-line description of the change.")
    before: Any = Field(default=None, description="Base value (updates and deletions).")
    after: Any = Field(default=None, description="Candidate value (additions and updates).")


class SourceChangeBlocker(BaseModel):
    """A structural reason the candidate cannot be applied as-is."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    code: Literal[
        "REFERENCED_COMPONENT_DELETION",
        "MODEL_OWNED_VALUE",
        "SHARED_RESPONSE_COLLISION",
        "SHARED_PARAMETER_COLLISION",
    ] = Field(description="Machine-readable blocker class.")
    pointer: str = Field(description="Pointer of the blocked change.")
    message: str = Field(description="Human-readable explanation of the blocker.")
    referenced_by: List[str] = Field(
        default_factory=list,
        alias="referencedBy",
        description="For referenced-component deletions: every pointer that "
        "still references the deleted component.",
    )


class SourceChangeCounts(BaseModel):
    """Per-kind change totals for at-a-glance review."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    additions: int = 0
    updates: int = 0
    deletions: int = 0
    unsupported_preserved: int = Field(default=0, alias="unsupportedPreserved")
    total: int = 0


class SourceChangeSet(BaseModel):
    """The full classified diff between a base revision and a candidate."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    base_digest: str = Field(
        alias="baseDigest",
        description="Semantic fingerprint of the base merged document the "
        "candidate was reviewed against (the optimistic-concurrency token).",
    )
    candidate_digest: str = Field(
        alias="candidateDigest",
        description="Semantic fingerprint of the parsed candidate document.",
    )
    change_set_digest: str = Field(
        alias="changeSetDigest",
        description="Digest binding this candidate to this base revision; the "
        "apply transaction records it so replays are idempotent.",
    )
    changes: List[SourceChange] = Field(default_factory=list)
    counts: SourceChangeCounts = Field(default_factory=SourceChangeCounts)
    blockers: List[SourceChangeBlocker] = Field(default_factory=list)


class RefIntegrityError(BaseModel):
    """A local ``$ref`` that does not resolve inside the candidate document."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    pointer: str = Field(description="Pointer of the '$ref' key itself.")
    ref: str = Field(description="The unresolvable reference string.")
    message: str


def _segment_label(segments: List[str]) -> str:
    return format_pointer(segments) or "/"


def scope_for_pointer(pointer: str) -> Tuple[ChangeScope, str]:
    """Map a change pointer to its review scope and stable group key.

    Returns:
        ``(scope, group)`` where scope is one of document/path/operation/
        component/schema and group is the stable key changes are grouped
        under in the review UI (e.g. ``"GET /pets"`` for an operation).
    """
    segments = parse_pointer(pointer)
    if not segments:
        return "document", "document"
    head = segments[0]
    if head == "paths":
        if len(segments) == 1:
            return "document", "paths"
        pathname = segments[1]
        if len(segments) >= 3 and segments[2].lower() in _OPERATION_METHODS:
            return "operation", f"{segments[2].upper()} {pathname}"
        return "path", pathname
    if head == "webhooks":
        if len(segments) == 1:
            return "document", "webhooks"
        return "path", f"webhooks {segments[1]}"
    if head == "components":
        if len(segments) == 1:
            return "document", "components"
        family = segments[1]
        if family == "schemas":
            if len(segments) >= 3:
                return "schema", segments[2]
            return "document", "components/schemas"
        if len(segments) >= 3:
            return "component", f"{family}/{segments[2]}"
        return "document", f"components/{family}"
    return "document", head


def _kind_verb(kind: ChangeKind) -> str:
    return {
        "addition": "Added",
        "update": "Changed",
        "deletion": "Removed",
        "unsupported-preserved": "Preserved",
    }[kind]


def _change_label(kind: ChangeKind, scope: ChangeScope, group: str, pointer: str) -> str:
    verb = _kind_verb(kind)
    if scope == "operation":
        return f"{verb} operation {group} at {pointer}"
    if scope == "path":
        return f"{verb} path {group} at {pointer}"
    if scope == "schema":
        return f"{verb} schema {group} at {pointer}"
    if scope == "component":
        return f"{verb} component {group} at {pointer}"
    return f"{verb} {pointer or '/'}"


def diff_documents(base: Any, candidate: Any) -> List[Dict[str, Any]]:
    """Minimal deep diff between two JSON documents.

    Walks both values in parallel. A key or index present only in the
    candidate yields one ``addition`` for the whole subtree; present only in
    the base, one ``deletion``; present in both with different non-container
    values (or mismatched container shapes), one ``update``. Containers with
    the same shape recurse, so changes are reported at the deepest stable
    pointer. Results are deterministic (sorted keys; array order as-is).

    Returns:
        Dicts with ``pointer``, ``kind`` (addition/update/deletion),
        ``before`` and ``after`` values.
    """
    deltas: List[Dict[str, Any]] = []
    _diff_into(base, candidate, [], deltas)
    return deltas


def _diff_into(base: Any, candidate: Any, segments: List[str], out: List[Dict[str, Any]]) -> None:
    if isinstance(base, dict) and isinstance(candidate, dict):
        for key in sorted(set(base.keys()) | set(candidate.keys())):
            child = segments + [key]
            if key not in candidate:
                out.append(
                    {
                        "pointer": format_pointer(child),
                        "kind": "deletion",
                        "before": base[key],
                        "after": None,
                    }
                )
            elif key not in base:
                out.append(
                    {
                        "pointer": format_pointer(child),
                        "kind": "addition",
                        "before": None,
                        "after": candidate[key],
                    }
                )
            else:
                _diff_into(base[key], candidate[key], child, out)
        return
    if isinstance(base, list) and isinstance(candidate, list):
        common = min(len(base), len(candidate))
        for index in range(common):
            _diff_into(base[index], candidate[index], segments + [str(index)], out)
        for index in range(common, len(base)):
            out.append(
                {
                    "pointer": format_pointer(segments + [str(index)]),
                    "kind": "deletion",
                    "before": base[index],
                    "after": None,
                }
            )
        for index in range(common, len(candidate)):
            out.append(
                {
                    "pointer": format_pointer(segments + [str(index)]),
                    "kind": "addition",
                    "before": None,
                    "after": candidate[index],
                }
            )
        return
    if base != candidate or type(base) is not type(candidate):
        out.append(
            {
                "pointer": format_pointer(segments),
                "kind": "update",
                "before": base,
                "after": candidate,
            }
        )


def _collect_refs(value: Any, segments: List[str], out: List[Tuple[str, str]]) -> None:
    """Collect every ``$ref`` string with the pointer of its ``$ref`` key."""
    if isinstance(value, dict):
        for key in sorted(value.keys()):
            child = segments + [key]
            if key == "$ref" and isinstance(value[key], str):
                out.append((format_pointer(child), value[key]))
            else:
                _collect_refs(value[key], child, out)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _collect_refs(item, segments + [str(index)], out)


def ref_integrity_errors(candidate: Any) -> List[RefIntegrityError]:
    """Local ``$ref`` targets that do not resolve inside the candidate.

    Mirrors the export surface's re-import integrity rule: every local
    (``#/...``) reference must resolve to an existing location in the same
    document. External references are out of scope here (DCW-2.5 owns
    multi-file handoff) and are left untouched.
    """
    refs: List[Tuple[str, str]] = []
    _collect_refs(candidate, [], refs)
    errors: List[RefIntegrityError] = []
    for pointer, ref in refs:
        if not ref.startswith("#"):
            continue
        target = ref[1:]
        try:
            resolvable = pointer_exists(candidate, target)
        except ValueError:
            resolvable = False
        if not resolvable:
            errors.append(
                RefIntegrityError(
                    pointer=pointer,
                    ref=ref,
                    message=f"$ref '{ref}' does not resolve inside the document",
                )
            )
    return errors


def _referencing_pointers(candidate: Any, schema_name: str) -> List[str]:
    """Every candidate pointer whose ``$ref`` targets the named schema."""
    refs: List[Tuple[str, str]] = []
    _collect_refs(candidate, [], refs)
    target = f"#/components/schemas/{schema_name}"
    return [pointer for pointer, ref in refs if ref == target]


def _schema_names(document: Any) -> List[str]:
    schemas = (
        document.get("components", {}).get("schemas", {})
        if isinstance(document, dict)
        else {}
    )
    return sorted(schemas.keys()) if isinstance(schemas, dict) else []


def _shared_response_collisions(candidate: Any) -> List[SourceChangeBlocker]:
    """Same path + status code with different response bodies across operations.

    The relational path model stores one response row per (path, status code),
    shared by every operation on the path. Two operations that give the same
    status different bodies cannot both be represented; blocking with an
    explanation is honest, last-write-wins is not.
    """
    blockers: List[SourceChangeBlocker] = []
    paths = candidate.get("paths") if isinstance(candidate, dict) else None
    if not isinstance(paths, dict):
        return blockers
    for pathname in sorted(paths.keys()):
        item = paths[pathname]
        if not isinstance(item, dict):
            continue
        seen: Dict[str, Tuple[str, Any]] = {}
        for method in sorted(item.keys()):
            operation = item[method]
            if method.lower() not in _OPERATION_METHODS or not isinstance(operation, dict):
                continue
            responses = operation.get("responses")
            if not isinstance(responses, dict):
                continue
            for status in sorted(responses.keys()):
                body = responses[status]
                if status in seen and seen[status][1] != body:
                    first_method = seen[status][0]
                    pointer = format_pointer(
                        ["paths", pathname, method, "responses", status]
                    )
                    blockers.append(
                        SourceChangeBlocker(
                            code="SHARED_RESPONSE_COLLISION",
                            pointer=pointer,
                            message=(
                                f"Path '{pathname}' defines status {status} differently on "
                                f"{first_method.upper()} and {method.upper()}. Responses are "
                                "shared per path and status code, so give the operations "
                                "distinct status codes or identical response bodies."
                            ),
                        )
                    )
                elif status not in seen:
                    seen[status] = (method, body)
    return blockers


def _shared_parameter_collisions(candidate: Any) -> List[SourceChangeBlocker]:
    """Same path + parameter (name, in) with different definitions across
    operations. Parameter rows are shared per path, so two operations that
    disagree about a parameter cannot both be represented."""
    blockers: List[SourceChangeBlocker] = []
    paths = candidate.get("paths") if isinstance(candidate, dict) else None
    if not isinstance(paths, dict):
        return blockers
    for pathname in sorted(paths.keys()):
        item = paths[pathname]
        if not isinstance(item, dict):
            continue
        seen: Dict[Tuple[str, str], Tuple[str, Any]] = {}
        for method in sorted(item.keys()):
            operation = item[method]
            if method.lower() not in _OPERATION_METHODS or not isinstance(operation, dict):
                continue
            parameters = operation.get("parameters")
            if not isinstance(parameters, list):
                continue
            for index, parameter in enumerate(parameters):
                if not isinstance(parameter, dict):
                    continue
                name = parameter.get("name")
                if not isinstance(name, str):
                    continue
                key = (name, parameter.get("in") or "query")
                if key in seen and seen[key][1] != parameter:
                    first_method = seen[key][0]
                    pointer = format_pointer(
                        ["paths", pathname, method, "parameters", str(index)]
                    )
                    blockers.append(
                        SourceChangeBlocker(
                            code="SHARED_PARAMETER_COLLISION",
                            pointer=pointer,
                            message=(
                                f"Path '{pathname}' defines parameter '{name}' (in: {key[1]}) "
                                f"differently on {first_method.upper()} and {method.upper()}. "
                                "Parameters are shared per path and (name, in), so make the "
                                "definitions identical or rename one."
                            ),
                        )
                    )
                elif key not in seen:
                    seen[key] = (method, parameter)
    return blockers


def change_set_digest(base_digest: str, candidate_digest: str) -> str:
    """Digest binding a reviewed candidate to the base it was reviewed against.

    Recorded by the apply transaction; replaying an applied change set matches
    on this digest and returns the recorded result instead of re-mutating.
    """
    payload = json.dumps(
        {
            "algorithm": CHANGE_SET_DIGEST_ALGORITHM,
            "baseDigest": base_digest,
            "candidateDigest": candidate_digest,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_source_change_set(
    base_merged: Any,
    candidate: Any,
    dialect: str,
) -> SourceChangeSet:
    """Classify a candidate document against the base merged document.

    Args:
        base_merged: The revision's current canonical document with its live
            preservation envelope applied (what the source editor started from).
        candidate: The parsed candidate document (already syntax-valid).
        dialect: The OAS dialect the revision is stored under (capability
            classification input).

    Returns:
        A :class:`SourceChangeSet` with deterministic ordering: changes sorted
        by (scope, group, pointer), blockers by (code, pointer).
    """
    base_fp = semantic_fingerprint(base_merged).fingerprint
    candidate_fp = semantic_fingerprint(candidate).fingerprint

    deltas = diff_documents(base_merged, candidate)
    changes: List[SourceChange] = []
    for delta in deltas:
        pointer = delta["pointer"]
        scope, group = scope_for_pointer(pointer)
        capability = capability_for_pointer(dialect, pointer)
        kind: ChangeKind = delta["kind"]
        if capability in _PRESERVED_CAPABILITIES:
            kind = "unsupported-preserved"
        changes.append(
            SourceChange(
                kind=kind,
                scope=scope,
                group=group,
                pointer=pointer,
                label=_change_label(kind, scope, group, pointer),
                before=delta["before"],
                after=delta["after"],
            )
        )
    changes.sort(key=lambda c: (c.scope, c.group, c.pointer))

    counts = SourceChangeCounts(
        additions=sum(1 for c in changes if c.kind == "addition"),
        updates=sum(1 for c in changes if c.kind == "update"),
        deletions=sum(1 for c in changes if c.kind == "deletion"),
        unsupported_preserved=sum(
            1 for c in changes if c.kind == "unsupported-preserved"
        ),
        total=len(changes),
    )

    blockers: List[SourceChangeBlocker] = []

    # Referenced-component deletion: a schema removed by the candidate while
    # other candidate pointers still $ref it. (A dangling $ref to a schema the
    # candidate keeps is a ref-integrity error, reported separately.)
    base_schemas = set(_schema_names(base_merged))
    candidate_schemas = set(_schema_names(candidate))
    for name in sorted(base_schemas - candidate_schemas):
        referencing = _referencing_pointers(candidate, name)
        if referencing:
            blockers.append(
                SourceChangeBlocker(
                    code="REFERENCED_COMPONENT_DELETION",
                    pointer=format_pointer(["components", "schemas", name]),
                    message=(
                        f"Schema '{name}' is deleted by this candidate but is still "
                        f"referenced from {len(referencing)} location(s). Update or "
                        "remove the references, or keep the schema."
                    ),
                    referenced_by=referencing,
                )
            )

    # Model-owned values: the server generates /openapi, /info, and
    # /x-metadata from project/version records; source edits to their
    # existing values would silently fight the metadata inspector (DCW-1.2)
    # or the dialect contract (DCW-0.1). Raw delta kinds are used here — the
    # capability matrix may reclassify these pointers as preserved, but an
    # update/deletion of an existing model-owned value stays blocked.
    for delta in deltas:
        if delta["kind"] not in ("update", "deletion"):
            continue
        pointer = delta["pointer"]
        if any(
            pointer == prefix or pointer.startswith(prefix + "/")
            for prefix in _MODEL_OWNED_PREFIXES
        ):
            blockers.append(
                SourceChangeBlocker(
                    code="MODEL_OWNED_VALUE",
                    pointer=pointer,
                    message=(
                        f"'{pointer}' is generated from project/version "
                        "metadata. Edit it in the metadata inspector instead of "
                        "the source view."
                    ),
                )
            )

    blockers.extend(_shared_response_collisions(candidate))
    blockers.extend(_shared_parameter_collisions(candidate))
    blockers.sort(key=lambda b: (b.code, b.pointer))

    return SourceChangeSet(
        base_digest=base_fp,
        candidate_digest=candidate_fp,
        change_set_digest=change_set_digest(base_fp, candidate_fp),
        changes=changes,
        counts=counts,
        blockers=blockers,
    )
