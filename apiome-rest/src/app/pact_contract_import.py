"""Import a Pact file into a consumer contract — CTG-4.1 (#4479).

A Pact file is the artifact a consumer-driven contract test already produces: every interaction
the consumer exercised, with the request it sent and the response it expected. That is precisely
the "what do you actually use" statement the registry wants, which is why importing one is the
first ingestion path rather than an integration.

What is read
------------
Pact specification 1.x through 4.x, in the shape the file actually takes:

* ``consumer.name`` / ``provider.name`` — provenance, and the name a consumer is created under
  when the caller does not supply one;
* each interaction's ``request.method`` / ``request.path`` — resolved onto the project's path
  *template* through :meth:`app.consumer_surface.SpecIndex.match_operation`, so ``/pets/42``
  becomes ``/pets/{petId}``;
* each interaction's ``request.query`` — declared as parameter usage (v2 spells it as a query
  string, v3+ as an object; both are read);
* each interaction's ``request.body`` and ``response.body`` — every key in the example body
  becomes a declared field, resolved against the operation's request/response schema at the
  interaction's own status code.

A v4 interaction that is not ``Synchronous/HTTP`` (a message interaction, for instance) has no
HTTP exchange to resolve and is reported as ``interaction-not-http`` rather than skipped.

What is *not* read
------------------
``matchingRules``, ``providerStates``, and generators. They describe *how* a value is compared,
not *which* fields are used, and the registry's question is only the second one. Reading them
would also mean taking a position on matcher semantics that CTG-4.2 does not need.

Nothing is dropped
------------------
Every interaction, and every field inside one, either lands in the surface or produces an
:class:`~app.consumer_contract.UnresolvedInteraction` with a stable reason. An import whose
interactions all name retired endpoints stores an empty surface with eleven unresolved entries —
which is the honest answer, and the one the acceptance criterion asks for.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import parse_qs

from .consumer_contract import (
    CODE_PACT_MALFORMED,
    CODE_PACT_TOO_LARGE,
    ConsumerContractField,
    ConsumerContractOperation,
    ConsumerContractSurface,
    ConsumerValidationError,
    UnresolvedInteraction,
    normalize_method,
    sort_operations,
)
from .consumer_surface import SpecIndex

__all__ = [
    "MAX_BODY_FIELDS",
    "MAX_BODY_DEPTH",
    "MAX_PACT_BYTES",
    "PactImportResult",
    "import_pact",
    "parse_pact_document",
    "pact_consumer_name",
    "pact_provider_name",
    "pact_specification_version",
]

#: Hard cap on the uploaded document, mirroring the CTG-1.2 inline-spec guard. A Pact file is a
#: test artifact, not a data set; anything larger is a mistake worth refusing by name.
MAX_PACT_BYTES = 10 * 1024 * 1024

#: How deep into an example body the field walk goes.
MAX_BODY_DEPTH = 8

#: How many distinct field paths one interaction body may contribute. A Pact body that lists a
#: thousand array elements describes the same handful of fields a thousand times; the walk is
#: deduplicated by path, and this is the backstop for the pathological case.
MAX_BODY_FIELDS = 500

#: Wrapper keys the Ruby and JVM Pact implementations use to embed a matcher around a value.
#: The registry wants the value, not the matcher, so these unwrap transparently.
_MATCHER_WRAPPERS = (
    ("json_class", "contents"),
    ("pact:matcher:type", "value"),
)

#: v4 interaction types that carry an HTTP request/response pair.
_HTTP_INTERACTION_TYPES = ("synchronous/http", "http")


def _as_dict(value: Any) -> Dict[str, Any]:
    """Coerce a node to a dict.

    Args:
        value: Any node.

    Returns:
        The dict, or an empty one for anything else.
    """
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> List[Any]:
    """Coerce a node to a list.

    Args:
        value: Any node.

    Returns:
        The list, or an empty one for anything else.
    """
    return value if isinstance(value, list) else []


@dataclass
class PactImportResult:
    """What an import produced.

    Attributes:
        surface: The resolved surface.
        unresolved: One entry per interaction or field that could not be placed.
        metadata: Pact provenance — consumer name, provider name, specification version, and
            how many interactions were read. The document's content digest is *not* here: it is
            :func:`parse_pact_document`'s to return, because that is the only thing that sees
            the bytes.
        interaction_count: How many interactions the document declared.
        resolved_count: How many of them resolved to an operation.
    """

    surface: ConsumerContractSurface
    unresolved: List[UnresolvedInteraction] = dataclass_field(default_factory=list)
    metadata: Dict[str, Any] = dataclass_field(default_factory=dict)
    interaction_count: int = 0
    resolved_count: int = 0


def parse_pact_document(raw: str) -> Tuple[Dict[str, Any], str]:
    """Validate the size of, and parse, an uploaded Pact document.

    Args:
        raw: The document as text (JSON).

    Returns:
        ``(document, digest)`` where the digest is ``sha256:<hex>`` of the UTF-8 bytes.

    Raises:
        ConsumerValidationError: ``consumer-pact-too-large`` past :data:`MAX_PACT_BYTES`,
            ``consumer-pact-malformed`` when the text is not a JSON object.
    """
    encoded = (raw or "").encode("utf-8")
    if len(encoded) > MAX_PACT_BYTES:
        raise ConsumerValidationError(
            CODE_PACT_TOO_LARGE,
            f"the Pact document is {len(encoded)} bytes; the limit is {MAX_PACT_BYTES}",
        )
    try:
        document = json.loads(encoded.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ConsumerValidationError(
            CODE_PACT_MALFORMED, f"the Pact document is not valid JSON: {exc}"
        ) from exc
    if not isinstance(document, dict):
        raise ConsumerValidationError(
            CODE_PACT_MALFORMED, "a Pact document must be a JSON object"
        )
    if not isinstance(document.get("interactions"), list):
        raise ConsumerValidationError(
            CODE_PACT_MALFORMED,
            "a Pact document must carry an 'interactions' array; this one does not",
        )
    digest = f"sha256:{hashlib.sha256(encoded).hexdigest()}"
    return document, digest


def pact_consumer_name(document: Mapping[str, Any]) -> Optional[str]:
    """The consumer the Pact document names.

    Args:
        document: The parsed Pact document.

    Returns:
        The name, or ``None`` when the document does not carry one.
    """
    name = _as_dict(document.get("consumer")).get("name")
    return str(name).strip() if isinstance(name, str) and name.strip() else None


def pact_provider_name(document: Mapping[str, Any]) -> Optional[str]:
    """The provider the Pact document names.

    Args:
        document: The parsed Pact document.

    Returns:
        The name, or ``None``.
    """
    name = _as_dict(document.get("provider")).get("name")
    return str(name).strip() if isinstance(name, str) and name.strip() else None


def pact_specification_version(document: Mapping[str, Any]) -> Optional[str]:
    """The Pact specification version the document declares.

    Both spellings are read: ``pactSpecification`` (v2+) and the hyphenated
    ``pact-specification`` some v1 writers emit.

    Args:
        document: The parsed Pact document.

    Returns:
        The version string, or ``None`` when the document declares none.
    """
    metadata = _as_dict(document.get("metadata"))
    for key in ("pactSpecification", "pact-specification"):
        version = _as_dict(metadata.get(key)).get("version")
        if isinstance(version, str) and version.strip():
            return version.strip()
    version = metadata.get("pactSpecificationVersion")
    return str(version).strip() if isinstance(version, str) and version.strip() else None


def _unwrap_matcher(node: Any) -> Any:
    """Strip a Pact matcher wrapper from a value, if there is one.

    Args:
        node: A node from an example body.

    Returns:
        The wrapped value, or the node unchanged.
    """
    current = node
    for _ in range(MAX_BODY_DEPTH):
        if not isinstance(current, dict):
            return current
        for marker, payload in _MATCHER_WRAPPERS:
            if marker in current and payload in current:
                current = current[payload]
                break
        else:
            return current
    return current


def _body_paths(body: Any) -> List[str]:
    """Every dotted data path a Pact example body names.

    Array levels are transparent — ``{"items": [{"id": 1}]}`` yields ``items`` and ``items.id``,
    not ``items.0.id`` — because a contract is about the *shape*, and an index is an artifact of
    the one example the test happened to send.

    Args:
        body: The example body.

    Returns:
        The distinct paths, sorted, including the intermediate object paths (a consumer that
        reads ``items.id`` also depends on ``items`` existing).
    """
    found: List[str] = []
    seen: set[str] = set()

    def walk(node: Any, prefix: str, depth: int) -> None:
        if depth > MAX_BODY_DEPTH or len(seen) >= MAX_BODY_FIELDS:
            return
        current = _unwrap_matcher(node)
        if isinstance(current, list):
            for element in current:
                walk(element, prefix, depth + 1)
            return
        if not isinstance(current, dict):
            return
        for key in sorted(str(k) for k in current):
            if len(seen) >= MAX_BODY_FIELDS:
                return
            path = f"{prefix}.{key}" if prefix else key
            if path not in seen:
                seen.add(path)
                found.append(path)
            walk(current[key], path, depth + 1)

    walk(body, "", 0)
    return found


def _query_names(query: Any) -> List[str]:
    """The query parameter names an interaction used.

    Pact v2 writes the query as a raw string; v3 and v4 write it as an object of name → values.
    Both are read, because a consumer's declared surface should not depend on which version of
    the test framework produced the file.

    Args:
        query: The interaction's ``request.query``.

    Returns:
        The distinct names, sorted.
    """
    if isinstance(query, str):
        return sorted(parse_qs(query, keep_blank_values=True).keys())
    if isinstance(query, dict):
        return sorted(str(name) for name in query)
    return []


def _interaction_is_http(interaction: Mapping[str, Any]) -> bool:
    """Whether a v4 interaction carries an HTTP exchange.

    Args:
        interaction: One interaction object.

    Returns:
        True for v1-v3 interactions (which are always HTTP) and for v4 ``Synchronous/HTTP``.
    """
    declared = interaction.get("type")
    if not isinstance(declared, str) or not declared.strip():
        return True
    return declared.strip().lower() in _HTTP_INTERACTION_TYPES


def import_pact(document: Mapping[str, Any], index: SpecIndex) -> PactImportResult:
    """Resolve a Pact document's interactions against a specification.

    Interactions are merged by operation: two interactions on ``GET /pets`` produce one declared
    operation carrying the union of their fields, because a contract is about the consumer, not
    about the test case. Fields are deduplicated by pointer, so the same field read at two
    different statuses is two entries and the same field read twice is one.

    Args:
        document: The parsed Pact document.
        index: The specification index to resolve against.

    Returns:
        The import result, including everything that could not be placed.
    """
    interactions = _as_list(document.get("interactions"))
    accumulated: Dict[Tuple[str, str], ConsumerContractOperation] = {}
    seen_pointers: Dict[Tuple[str, str], set[str]] = {}
    unresolved: List[UnresolvedInteraction] = []
    resolved_count = 0

    for raw_interaction in interactions:
        interaction = _as_dict(raw_interaction)
        description = interaction.get("description")
        description_text = str(description) if isinstance(description, str) else None

        if not _interaction_is_http(interaction):
            unresolved.append(
                UnresolvedInteraction(
                    reason="interaction-not-http",
                    message=(
                        f"interaction type '{interaction.get('type')}' carries no HTTP exchange; "
                        f"only Synchronous/HTTP interactions describe an operation"
                    ),
                    description=description_text,
                )
            )
            continue

        request = _as_dict(interaction.get("request"))
        method = normalize_method(str(request.get("method", "")))
        path = request.get("path")
        if not method or not isinstance(path, str) or not path.strip():
            unresolved.append(
                UnresolvedInteraction(
                    reason="interaction-malformed",
                    message="the interaction's request declares no method and path",
                    description=description_text,
                    method=method or None,
                    path=str(path) if isinstance(path, str) else None,
                )
            )
            continue

        entry = index.match_operation(method, path)
        if entry is None:
            unresolved.append(
                UnresolvedInteraction(
                    reason=(
                        "method-not-declared"
                        if index.matches_any_method(path)
                        else "operation-not-found"
                    ),
                    message=(
                        f"the specification declares no {method.upper()} {path} operation"
                    ),
                    description=description_text,
                    method=method,
                    path=path,
                )
            )
            continue

        resolved_count += 1
        key = (entry.method, entry.path)
        if key not in accumulated:
            summary = entry.operation.get("summary")
            accumulated[key] = ConsumerContractOperation(
                method=entry.method,
                path=entry.path,
                pointer=entry.pointer,
                operation_id=(
                    str(entry.operation["operationId"])
                    if isinstance(entry.operation.get("operationId"), str)
                    else None
                ),
                summary=str(summary) if isinstance(summary, str) else None,
                fields=[],
            )
            seen_pointers[key] = set()

        target = accumulated[key]
        pointers = seen_pointers[key]

        response = _as_dict(interaction.get("response"))
        status = response.get("status")
        status_text = str(status) if status is not None else None

        _collect(
            index,
            entry,
            location="parameter",
            paths=_query_names(request.get("query")),
            status=None,
            target=target,
            pointers=pointers,
            unresolved=unresolved,
            description=description_text,
        )
        _collect(
            index,
            entry,
            location="request",
            paths=_body_paths(request.get("body")),
            status=None,
            target=target,
            pointers=pointers,
            unresolved=unresolved,
            description=description_text,
        )
        _collect(
            index,
            entry,
            location="response",
            paths=_body_paths(response.get("body")),
            status=status_text,
            target=target,
            pointers=pointers,
            unresolved=unresolved,
            description=description_text,
        )

    surface = ConsumerContractSurface(operations=sort_operations(list(accumulated.values())))
    metadata: Dict[str, Any] = {
        "consumer": pact_consumer_name(document),
        "provider": pact_provider_name(document),
        "pactSpecification": pact_specification_version(document),
        "interactionCount": len(interactions),
        "resolvedInteractionCount": resolved_count,
    }
    return PactImportResult(
        surface=surface,
        unresolved=unresolved,
        metadata={k: v for k, v in metadata.items() if v is not None},
        interaction_count=len(interactions),
        resolved_count=resolved_count,
    )


def _collect(
    index: SpecIndex,
    entry: Any,
    *,
    location: str,
    paths: Sequence[str],
    status: Optional[str],
    target: ConsumerContractOperation,
    pointers: set[str],
    unresolved: List[UnresolvedInteraction],
    description: Optional[str],
) -> None:
    """Resolve a batch of named paths and merge them into an operation.

    A path that does not resolve produces an unresolved entry and is skipped; the operation
    itself stays, because "you call this operation but that field is gone" is the useful answer.

    Args:
        index: The specification index.
        entry: The resolved operation entry.
        location: ``response``, ``request``, or ``parameter``.
        paths: Dotted data paths (or parameter names) to resolve.
        status: The response status the fields were read at, for a response.
        target: The accumulating operation to merge into.
        pointers: Pointers already declared on that operation, for deduplication.
        unresolved: Accumulator for failures.
        description: The interaction's description, carried onto any failure.
    """
    for path in paths:
        field, reason = index.resolve_field(
            entry, location=location, path=path, status=status, media_type=None
        )
        if field is None:
            unresolved.append(
                UnresolvedInteraction(
                    reason=reason or "field-not-found",
                    message=(
                        f"{entry.method.upper()} {entry.path} does not declare "
                        f"{location} field '{path}'"
                        + (f" at status {status}" if status else "")
                    ),
                    description=description,
                    method=entry.method,
                    path=entry.path,
                    status=status,
                    field_path=path,
                )
            )
            continue
        _merge_field(target, pointers, field)


def _merge_field(
    target: ConsumerContractOperation, pointers: set[str], field: ConsumerContractField
) -> None:
    """Add a resolved field to an operation unless it is already declared.

    Args:
        target: The accumulating operation.
        pointers: Pointers already declared on it.
        field: The resolved field.
    """
    identity = f"{field.location}|{field.status or ''}|{field.pointer}"
    if identity in pointers:
        return
    pointers.add(identity)
    target.fields.append(field)
