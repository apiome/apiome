"""REST hypermedia conventions: JSON:API, HAL, HAL-FORMS, JSON-LD and Hydra — MFI-19.6 (#3984).

These conventions are media types and document shapes layered on an ordinary REST API, not schema
languages of their own, so an artifact that uses them is an OpenAPI (or Swagger, RAML, …) document
like any other. This module reads what such a document **declares** and normalizes it:

=============  ======================================  =========================================
Convention     Declared by                             Normalized details
=============  ======================================  =========================================
``jsonapi``    ``application/vnd.api+json``            resource ``type`` names
``hal``        ``application/hal+json`` / ``+xml``     link relations (``_links``), ``_embedded``
``hal-forms``  ``application/prs.hal-forms+json``      template names (``_templates``)
``json-ld``    ``application/ld+json``                 ``@type`` names
``hydra``      JSON-LD that uses the Hydra vocabulary  ``@type`` names
=============  ======================================  =========================================

:func:`detect_conventions` and :func:`convention_details` feed the catalog (the revision's
``format_metadata.restConventions`` and the **convention** facet); :func:`iter_bodies` gives the
``rest-conventions`` lint pack (:mod:`app.rest_conventions_lint`) every request and response body
with the schema it declares. Bodies are read from the retained OpenAPI 3 / Swagger 2 document when
there is one (``$ref``\\ s resolved, ``allOf`` merged), else from the canonical messages.

Pure: a model in, facts out.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Mapping, Optional, Set, Tuple

from .canonical_model import CanonicalApi, MessageRole, TypeRef

__all__ = [
    "CONVENTIONS",
    "CONVENTION_LABELS",
    "Body",
    "convention_of_media_type",
    "detect_conventions",
    "convention_details",
    "iter_bodies",
    "properties_of",
    "required_of",
    "resolve",
]

#: The conventions, in the order they are presented.
CONVENTIONS: Tuple[str, ...] = ("jsonapi", "hal", "hal-forms", "json-ld", "hydra")

#: Display labels (the catalog facet's chips).
CONVENTION_LABELS: Mapping[str, str] = {
    "jsonapi": "JSON:API",
    "hal": "HAL",
    "hal-forms": "HAL-FORMS",
    "json-ld": "JSON-LD",
    "hydra": "Hydra",
}

#: Media type (no parameters, lower case) → convention.
_MEDIA_TYPES: Mapping[str, str] = {
    "application/vnd.api+json": "jsonapi",
    "application/hal+json": "hal",
    "application/hal+xml": "hal",
    "application/prs.hal-forms+json": "hal-forms",
    "application/ld+json": "json-ld",
}

_HYDRA_NAMESPACE = "http://www.w3.org/ns/hydra/core"
_HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")

#: How deep a schema is followed through ``$ref``\\ s and nested properties.
_MAX_DEPTH = 12


def convention_of_media_type(media_type: str) -> Optional[str]:
    """Return the convention a media type declares, or ``None``.

    Args:
        media_type: A media type, parameters allowed (``application/ld+json; profile="…hydra…"``).

    Returns:
        ``jsonapi`` / ``hal`` / ``hal-forms`` / ``json-ld``, or ``hydra`` for JSON-LD whose
        ``profile`` names the Hydra vocabulary.
    """
    base, _, params = (media_type or "").partition(";")
    convention = _MEDIA_TYPES.get(base.strip().lower())
    if convention == "json-ld" and "ns/hydra" in params.lower():
        return "hydra"
    return convention


@dataclass(frozen=True)
class Body:
    """One request or response body an operation declares.

    Attributes:
        location: Where it is, e.g. ``GET /orders#response.200 (application/hal+json)``.
        operation: The operation, e.g. ``GET /orders``.
        role: ``request``, ``response`` or ``error`` (a 4xx / 5xx response).
        status: The response status code (``None`` for a request).
        media_type: The media type as declared.
        convention: The convention the media type declares, if any.
        schema: The body's schema with its top-level ``$ref`` resolved (``None`` when it
            declares none).
    """

    location: str
    operation: str
    role: str
    status: Optional[str]
    media_type: str
    convention: Optional[str]
    schema: Optional[Dict[str, Any]]


# ===========================================================================
# Schemas
# ===========================================================================


def resolve(schema: Any, document: Mapping[str, Any], depth: int = 0) -> Any:
    """Follow a local ``$ref`` (``#/components/schemas/X``) to what it names.

    Args:
        schema: A schema (or any object that may be a ``$ref``).
        document: The document local references point into.
        depth: Guard against reference cycles.

    Returns:
        The referenced object, or ``schema`` itself when it is no local reference or cannot be
        resolved.
    """
    while isinstance(schema, Mapping) and isinstance(schema.get("$ref"), str) and depth < _MAX_DEPTH:
        ref = schema["$ref"]
        if not ref.startswith("#/"):
            return schema
        target: Any = document
        for part in ref[2:].split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            if not isinstance(target, Mapping) or part not in target:
                return schema
            target = target[part]
        schema, depth = target, depth + 1
    return schema


def _branches(schema: Any, document: Mapping[str, Any], depth: int) -> List[Mapping[str, Any]]:
    """The schema and the ``allOf`` / ``oneOf`` / ``anyOf`` parts it is built from, resolved."""
    schema = resolve(schema, document)
    if not isinstance(schema, Mapping) or depth > _MAX_DEPTH:
        return []
    parts: List[Mapping[str, Any]] = [schema]
    for key in ("allOf", "oneOf", "anyOf"):
        for part in schema.get(key) or []:
            parts += _branches(part, document, depth + 1)
    return parts


def properties_of(schema: Any, document: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """Return the properties a schema declares, merged across ``allOf`` / ``oneOf`` / ``anyOf``.

    Lenient on purpose: a property any branch declares counts, so a check only fires on what a
    schema certainly lacks.

    Args:
        schema: The schema.
        document: The document its references point into.

    Returns:
        Property name → its (resolved) schema; ``None`` when the schema says nothing about its
        properties (no ``properties`` anywhere), so a check cannot judge it.
    """
    found: Optional[Dict[str, Any]] = None
    for part in _branches(schema, document, 0):
        props = part.get("properties")
        if isinstance(props, Mapping):
            found = found or {}
            for name, sub in props.items():
                found.setdefault(str(name), resolve(sub, document))
    return found


def required_of(schema: Any, document: Mapping[str, Any]) -> Set[str]:
    """Return the property names a schema (or an ``allOf`` part of it) marks required."""
    required: Set[str] = set()
    resolved = resolve(schema, document)
    if not isinstance(resolved, Mapping):
        return required
    for part in [resolved] + [resolve(p, document) for p in resolved.get("allOf") or []]:
        if isinstance(part, Mapping):
            required |= {str(name) for name in part.get("required") or [] if isinstance(name, str)}
    return required


def _canonical_schema(api: CanonicalApi, ref: Optional[TypeRef], depth: int = 0) -> Optional[Dict[str, Any]]:
    """A JSON-Schema-shaped view of a canonical payload type (property names and nesting only)."""
    if ref is None or depth > 3:
        return None
    if ref.item is not None:
        return {"type": "array", "items": _canonical_schema(api, ref.item, depth + 1) or {}}
    named = api.type_by_key(ref.name) if ref.name else None
    if named is None or not named.fields:
        return {}
    return {
        "type": "object",
        "properties": {f.name: _canonical_schema(api, f.type, depth + 1) or {} for f in named.fields},
    }


# ===========================================================================
# Bodies
# ===========================================================================


def _role(status: Optional[str]) -> str:
    if status is None:
        return "request"
    return "error" if status[:1] in ("4", "5") else "response"


def _body(operation: str, status: Optional[str], media_type: str, schema: Any, document: Mapping[str, Any]) -> Body:
    where = f"{operation}#{'request' if status is None else f'response.{status}'} ({media_type})"
    resolved = resolve(schema, document) if schema is not None else None
    return Body(
        location=where,
        operation=operation,
        role=_role(status),
        status=status,
        media_type=media_type,
        convention=convention_of_media_type(media_type),
        schema=dict(resolved) if isinstance(resolved, Mapping) else None,
    )


def _openapi_bodies(document: Mapping[str, Any]) -> Iterator[Body]:
    for path, item in (document.get("paths") or {}).items():
        item = resolve(item, document)
        if not isinstance(item, Mapping):
            continue
        for method in _HTTP_METHODS:
            op = item.get(method)
            if not isinstance(op, Mapping):
                continue
            operation = f"{method.upper()} {path}"
            request = resolve(op.get("requestBody"), document)
            if isinstance(request, Mapping):
                for media_type, entry in (request.get("content") or {}).items():
                    yield _body(operation, None, str(media_type), (entry or {}).get("schema"), document)
            for status, response in (op.get("responses") or {}).items():
                response = resolve(response, document)
                if not isinstance(response, Mapping):
                    continue
                for media_type, entry in (response.get("content") or {}).items():
                    yield _body(operation, str(status), str(media_type), (entry or {}).get("schema"), document)


def _swagger_bodies(document: Mapping[str, Any]) -> Iterator[Body]:
    root_consumes = document.get("consumes") or []
    root_produces = document.get("produces") or []
    for path, item in (document.get("paths") or {}).items():
        if not isinstance(item, Mapping):
            continue
        for method in _HTTP_METHODS:
            op = item.get(method)
            if not isinstance(op, Mapping):
                continue
            operation = f"{method.upper()} {path}"
            for param in list(item.get("parameters") or []) + list(op.get("parameters") or []):
                param = resolve(param, document)
                if isinstance(param, Mapping) and param.get("in") == "body":
                    for media_type in op.get("consumes") or root_consumes:
                        yield _body(operation, None, str(media_type), param.get("schema"), document)
            for status, response in (op.get("responses") or {}).items():
                response = resolve(response, document)
                if isinstance(response, Mapping) and "schema" in response:
                    for media_type in op.get("produces") or root_produces:
                        yield _body(operation, str(status), str(media_type), response.get("schema"), document)


def _canonical_bodies(api: CanonicalApi) -> Iterator[Body]:
    for op in api.operations():
        operation = op.key
        for message in op.messages:
            status = message.status_code if message.role is not MessageRole.REQUEST else None
            schema = message.payload_schema or _canonical_schema(api, message.payload)
            for media_type in message.content_types:
                yield _body(operation, status, media_type, schema, {})


def _document(api: CanonicalApi) -> Optional[Mapping[str, Any]]:
    raw = api.raw if isinstance(api.raw, Mapping) else None
    if raw and (isinstance(raw.get("openapi"), str) or isinstance(raw.get("swagger"), str)):
        return raw
    return None


def iter_bodies(api: CanonicalApi) -> Iterator[Body]:
    """Yield every request and response body the artifact declares.

    Args:
        api: A REST canonical model.

    Yields:
        Each :class:`Body`, from the retained OpenAPI 3 / Swagger 2 document when there is one,
        else from the canonical messages.
    """
    document = _document(api)
    if document is not None and isinstance(document.get("swagger"), str):
        yield from _swagger_bodies(document)
    elif document is not None:
        yield from _openapi_bodies(document)
    else:
        yield from _canonical_bodies(api)


def document_of(api: CanonicalApi) -> Mapping[str, Any]:
    """The document a body's ``$ref``\\ s resolve against (empty for a canonical-only model)."""
    return _document(api) or {}


# ===========================================================================
# Detection and details
# ===========================================================================


def _uses_hydra(schema: Any, document: Mapping[str, Any], depth: int = 0) -> bool:
    """Whether a JSON-LD body schema uses Hydra terms (``hydra:member``, a Hydra ``@context``…)."""
    props = properties_of(schema, document) if depth <= 3 else None
    if not props:
        return False
    for name, sub in props.items():
        if name.startswith("hydra:"):
            return True
        if name == "@context" and _HYDRA_NAMESPACE in repr(sub):
            return True
        if isinstance(sub, Mapping) and _uses_hydra(sub, document, depth + 1):
            return True
    return False


def _body_conventions(body: Body, document: Mapping[str, Any]) -> Set[str]:
    found: Set[str] = set()
    if body.convention:
        found.add(body.convention)
    if body.convention in ("json-ld", "hydra") and body.schema is not None and _uses_hydra(body.schema, document):
        found |= {"json-ld", "hydra"}
    if body.convention == "hydra":
        found.add("json-ld")
    return found


def detect_conventions(api: CanonicalApi) -> List[str]:
    """Return the conventions an artifact declares, in :data:`CONVENTIONS` order.

    Args:
        api: The canonical model (any paradigm; only REST bodies carry these media types).

    Returns:
        The conventions — empty when it declares none.
    """
    document = document_of(api)
    found: Set[str] = set()
    for body in iter_bodies(api):
        found |= _body_conventions(body, document)
    return [c for c in CONVENTIONS if c in found]


def _names(schema: Any, document: Mapping[str, Any]) -> List[str]:
    """The literal values a schema allows (``const`` / ``enum``), as strings."""
    resolved = resolve(schema, document)
    if not isinstance(resolved, Mapping):
        return []
    if "const" in resolved:
        return [str(resolved["const"])]
    return [str(v) for v in resolved.get("enum") or [] if isinstance(v, (str, int))]


def _items(schema: Any, document: Mapping[str, Any]) -> Any:
    """A schema's array ``items`` (resolved), or the schema itself when it is not an array."""
    resolved = resolve(schema, document)
    if isinstance(resolved, Mapping) and resolved.get("type") == "array":
        return resolve(resolved.get("items"), document)
    return resolved


def convention_details(api: CanonicalApi) -> Dict[str, Dict[str, List[str]]]:
    """Normalize what each declared convention says about the API's resources and links.

    Args:
        api: The canonical model.

    Returns:
        Per convention: ``operations`` that use it, plus ``resourceTypes`` (JSON:API ``data.type``),
        ``linkRelations`` / ``embedded`` (HAL ``_links`` / ``_embedded``), ``templates``
        (HAL-FORMS ``_templates``) or ``types`` (JSON-LD / Hydra ``@type``), each sorted. Empty
        when the artifact declares no convention.
    """
    document = document_of(api)
    details: Dict[str, Dict[str, Set[str]]] = {}
    for body in iter_bodies(api):
        conventions = _body_conventions(body, document)
        props = properties_of(body.schema, document) if body.schema is not None else None
        for convention in conventions:
            entry = details.setdefault(convention, {"operations": set()})
            entry["operations"].add(body.operation)
            if not props:
                continue
            if convention == "jsonapi" and "data" in props:
                data = properties_of(_items(props["data"], document), document) or {}
                entry.setdefault("resourceTypes", set()).update(_names(data.get("type"), document))
            if convention in ("hal", "hal-forms"):
                for key, label in (("_links", "linkRelations"), ("_embedded", "embedded")):
                    nested = properties_of(props.get(key), document) if key in props else None
                    if nested:
                        entry.setdefault(label, set()).update(nested)
            if convention == "hal-forms" and "_templates" in props:
                entry.setdefault("templates", set()).update(properties_of(props["_templates"], document) or {})
            if convention in ("json-ld", "hydra") and "@type" in props:
                entry.setdefault("types", set()).update(_names(props["@type"], document))
    return {
        convention: {key: sorted(values) for key, values in details[convention].items() if values}
        for convention in CONVENTIONS
        if convention in details
    }
