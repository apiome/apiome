"""REST hypermedia convention conformance lint — MFI-19.6 (#3984).

The ``rest-conventions`` pack runs for every REST-paradigm artifact (OpenAPI, Swagger, RAML, …) and
checks each body against the convention its media type declares (:mod:`app.rest_conventions`). An
artifact that declares none gets no findings. A schema that says nothing about its properties is
not judged: every check fires only on what a body's schema certainly lacks.

==========================================  ====================================================
Rule                                        What the specification asks
==========================================  ====================================================
``rest-conventions.jsonapi-top-level``      A JSON:API document has ``data``, ``errors`` or
                                            ``meta`` (JSON:API 1.1 §7.1, MUST).
``rest-conventions.jsonapi-data-and-errors``  ``data`` and ``errors`` never coexist (§7.1,
                                            MUST NOT): a schema must not require both.
``rest-conventions.jsonapi-resource-object``  A resource object has ``type``, and ``id`` in a
                                            response (§7.2, MUST).
``rest-conventions.jsonapi-error-document``  A 4xx / 5xx JSON:API response is an error document
                                            with ``errors`` (§7.1, §11).
``rest-conventions.hal-self-link``          A HAL resource has ``_links.self`` (HAL draft §8.1,
                                            SHOULD).
``rest-conventions.hal-link-object``        Every HAL link object has ``href`` (§5.1, MUST).
``rest-conventions.hal-forms-template``     A HAL-FORMS document has ``_templates.default``
                                            (HAL-FORMS, MUST).
``rest-conventions.jsonld-context``         A JSON-LD body has ``@context`` (JSON-LD 1.1 §3.1),
                                            unless the response sends it in a ``Link`` header.
``rest-conventions.hydra-collection-member``  A Hydra collection's ``member`` is an array (Hydra
                                            Core §5.1).
==========================================  ====================================================

All are warnings: a schema describes a payload loosely, so a gap in it is a likely defect rather
than a proven one.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, List, Mapping, Optional, Tuple

from .canonical_model import ApiParadigm, CanonicalApi
from .lint_engine import LintRule, RulePack
from .rest_conventions import Body, document_of, iter_bodies, properties_of, required_of, resolve

__all__ = ["RestConventionsRulePack", "REST_CONVENTIONS_PACK_ID", "RULE_IDS"]

REST_CONVENTIONS_PACK_ID = "rest-conventions"
_PREFIX = "rest-conventions."

Finding = Tuple[str, str]
Check = Callable[[Body, Mapping[str, Any]], Iterable[Finding]]


def _props(schema: Any, document: Mapping[str, Any]) -> Optional[dict]:
    return properties_of(schema, document) if schema is not None else None


def _is_array(schema: Any, document: Mapping[str, Any]) -> bool:
    resolved = resolve(schema, document)
    return isinstance(resolved, Mapping) and resolved.get("type") == "array"


def _items(schema: Any, document: Mapping[str, Any]) -> Any:
    resolved = resolve(schema, document)
    if isinstance(resolved, Mapping) and resolved.get("type") == "array":
        return resolved.get("items")
    return resolved


def _jsonapi_top_level(body: Body, document: Mapping[str, Any]) -> Iterable[Finding]:
    props = _props(body.schema, document)
    if props is not None and not {"data", "errors", "meta"} & set(props):
        yield body.location, "A JSON:API document must contain at least one of `data`, `errors` or `meta`."


def _jsonapi_data_and_errors(body: Body, document: Mapping[str, Any]) -> Iterable[Finding]:
    if body.schema is not None and {"data", "errors"} <= required_of(body.schema, document):
        yield body.location, "A JSON:API document must not contain both `data` and `errors`, but both are required."


def _jsonapi_resource_object(body: Body, document: Mapping[str, Any]) -> Iterable[Finding]:
    props = _props(body.schema, document)
    if not props or "data" not in props:
        return
    resource = _props(_items(props["data"], document), document)
    if resource is None:
        return
    missing = [name for name in ("type", "id") if name not in resource and (name == "type" or body.role != "request")]
    if missing:
        listed = " and ".join(f"`{name}`" for name in missing)
        yield body.location, f"A JSON:API resource object in `data` must have {listed}."


def _jsonapi_error_document(body: Body, document: Mapping[str, Any]) -> Iterable[Finding]:
    props = _props(body.schema, document)
    if body.role == "error" and props is not None and "errors" not in props:
        yield body.location, "A JSON:API error response should be an error document with an `errors` array."


def _hal_self_link(body: Body, document: Mapping[str, Any]) -> Iterable[Finding]:
    if body.role != "response":
        return
    props = _props(body.schema, document)
    if props is None:
        return
    links = _props(props.get("_links"), document) if "_links" in props else None
    if "_links" not in props:
        yield body.location, "A HAL resource should have `_links` with a `self` link."
    elif links is not None and "self" not in links:
        yield body.location, "A HAL resource's `_links` should include `self`."


def _hal_link_object(body: Body, document: Mapping[str, Any]) -> Iterable[Finding]:
    props = _props(body.schema, document)
    links = _props(props.get("_links"), document) if props and "_links" in props else None
    for relation, schema in sorted((links or {}).items()):
        link = _props(_items(schema, document), document)
        if link is not None and "href" not in link:
            yield f"{body.location} _links.{relation}", f"The HAL link object `{relation}` must have `href`."


def _hal_forms_template(body: Body, document: Mapping[str, Any]) -> Iterable[Finding]:
    if body.role != "response":
        return
    props = _props(body.schema, document)
    if props is None:
        return
    templates = _props(props.get("_templates"), document) if "_templates" in props else None
    if "_templates" not in props:
        yield body.location, "A HAL-FORMS document must have `_templates` with a `default` template."
    elif templates is not None and "default" not in templates:
        yield body.location, "A HAL-FORMS document's `_templates` must include `default`."


def _jsonld_context(body: Body, document: Mapping[str, Any]) -> Iterable[Finding]:
    if body.role == "request":
        return
    props = _props(body.schema, document)
    if props is None or "@context" in props:
        return
    if _declares_link_header(body, document):
        return
    yield body.location, "A JSON-LD body should declare `@context` (or the response should send it in a `Link` header)."


def _declares_link_header(body: Body, document: Mapping[str, Any]) -> bool:
    """Whether the response declares a ``Link`` header (where JSON-LD may carry its context)."""
    if body.status is None:
        return False
    method, _, path = body.operation.partition(" ")
    op = resolve((document.get("paths") or {}).get(path), document)
    op = op.get(method.lower()) if isinstance(op, Mapping) else None
    response = resolve(((op or {}).get("responses") or {}).get(body.status), document)
    headers = response.get("headers") if isinstance(response, Mapping) else None
    return isinstance(headers, Mapping) and any(str(name).lower() == "link" for name in headers)


def _hydra_collection_member(body: Body, document: Mapping[str, Any]) -> Iterable[Finding]:
    props = _props(body.schema, document)
    if not props:
        return
    for member in ("member", "hydra:member"):
        if member in props and not _is_array(props[member], document):
            total = "totalItems" in props or "hydra:totalItems" in props
            if total or member.startswith("hydra:"):
                yield body.location, f"A Hydra collection's `{member}` must be an array."


#: Rule id → (conventions it checks, severity, category, description, check).
_RULES: Tuple[Tuple[str, Tuple[str, ...], str, str, str, Check], ...] = (
    ("jsonapi-top-level", ("jsonapi",), "warning", "structure",
     "A JSON:API document must contain `data`, `errors` or `meta`.", _jsonapi_top_level),
    ("jsonapi-data-and-errors", ("jsonapi",), "warning", "structure",
     "A JSON:API document must not contain both `data` and `errors`.", _jsonapi_data_and_errors),
    ("jsonapi-resource-object", ("jsonapi",), "warning", "structure",
     "A JSON:API resource object must have `type`, and `id` in a response.", _jsonapi_resource_object),
    ("jsonapi-error-document", ("jsonapi",), "warning", "structure",
     "A 4xx / 5xx JSON:API response should be an error document with `errors`.", _jsonapi_error_document),
    ("hal-self-link", ("hal", "hal-forms"), "warning", "structure",
     "A HAL resource should have a `_links.self` link.", _hal_self_link),
    ("hal-link-object", ("hal", "hal-forms"), "warning", "structure",
     "A HAL link object must have `href`.", _hal_link_object),
    ("hal-forms-template", ("hal-forms",), "warning", "structure",
     "A HAL-FORMS document must have a `_templates.default` template.", _hal_forms_template),
    ("jsonld-context", ("json-ld", "hydra"), "warning", "structure",
     "A JSON-LD body should declare `@context` (or send it in a `Link` header).", _jsonld_context),
    ("hydra-collection-member", ("json-ld", "hydra"), "warning", "structure",
     "A Hydra collection's `member` must be an array.", _hydra_collection_member),
)

#: Every rule id this pack defines.
RULE_IDS: Tuple[str, ...] = tuple(_PREFIX + rule[0] for rule in _RULES)


def _check(conventions: Tuple[str, ...], check: Check) -> Callable[[CanonicalApi], Iterable[Finding]]:
    """Run ``check`` over the bodies whose media type declares one of ``conventions``."""

    def run(api: CanonicalApi) -> Iterable[Finding]:
        document = document_of(api)
        for body in iter_bodies(api):
            if body.convention in conventions and body.schema is not None:
                yield from check(body, document)

    return run


class RestConventionsRulePack(RulePack, register_paradigm=True):
    """Convention conformance for REST artifacts (see the module docstring)."""

    paradigm = ApiParadigm.REST
    pack_id = REST_CONVENTIONS_PACK_ID

    _BUILT: Tuple[LintRule, ...] = tuple(
        LintRule(
            rule_id=_PREFIX + rule_id,
            category=category,
            severity=severity,
            description=description,
            check=_check(conventions, check),
        )
        for rule_id, conventions, severity, category, description, check in _RULES
    )

    def rules(self) -> List[LintRule]:
        """Return the convention rules in deterministic execution order."""
        return list(self._BUILT)
