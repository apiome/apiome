"""WADL lint pack — MFI-21.3 (#3993).

Native, deterministic quality rules for WADL REST service descriptions, layered on the canonical
lint engine (MFI-4.1 :mod:`app.lint_engine`) the way the XML-RPC pack (:mod:`app.xmlrpc_lint`) is.
The :class:`WadlRulePack` is registered under the ``wadl`` format key, so it runs with the
always-on common pack on every WADL artifact. The rules read only the canonical model
:class:`~app.wadl_normalizer.WadlNormalizer` builds.

WADL is a legacy description: the reason to import one is usually to leave it for OpenAPI (the
``wadl`` conversion pack, :mod:`app.conversion_packs`). So beside the structural checks, several
rules flag what will not survive that migration cleanly:

* **wadl.reference-resolved** (error) — a ``method`` / ``param`` / ``representation`` ``href``
  or a resource ``type`` names no element of the document (or an external WADL, which is not
  fetched): what it describes is missing from the import.
* **wadl.template-param-declared** (error) — a ``{name}`` in a resource path with no
  ``template`` param declaring it: the path variable has no type and OpenAPI requires one.
* **wadl.template-param-used** (warning) — a ``template`` param that no ``{name}`` in the path
  uses: callers have nowhere to put it.
* **wadl.method-id-unique** (error) — two methods share an ``id``: ``href="#id"`` is ambiguous
  and the OpenAPI ``operationId`` s collide.
* **wadl.method-id-present** (info) — a method without an ``id``: the OpenAPI migration has to
  invent an ``operationId``, and generated clients name their methods after it.
* **wadl.method-name-standard** (warning) — a method whose name is not a standard HTTP verb:
  WADL allows any token, OpenAPI 3.1 has a slot only for GET, PUT, POST, DELETE, OPTIONS, HEAD,
  PATCH and TRACE.
* **wadl.body-on-safe-method** (warning) — a GET, HEAD or DELETE whose request carries a
  representation: HTTP gives such a body no defined meaning and many intermediaries drop it.
* **wadl.response-declared** (warning) — a method with no ``response``: nothing says what a
  caller gets back.
* **wadl.response-status-valid** (warning) — a ``status`` that is not a three-digit HTTP code.
* **wadl.type-resolved** (warning) — a param, element or representation whose XSD type is
  neither a built-in nor declared by the grammars (an ``include`` not uploaded, a typo): the
  catalog keeps the bare name and the OpenAPI schema has nothing to point at.
* **wadl.representation-typed** (info) — an XML or JSON representation with no ``element``
  (or ``type``): it converts as an untyped body.
* **wadl.representation-media-type** (info) — a representation with a grammar type but no
  ``mediaType``: the migration has to assume one.
* **wadl.base-uri-present** (info) — no ``resources/@base``: the OpenAPI document gets no
  server.
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

from .canonical_model import (
    CanonicalApi,
    MessageRole,
    Operation,
    ParameterLocation,
    TypeRef,
)
from .lint_engine import LintRule, RulePack
from .wadl_normalizer import CANONICAL_PRIMITIVES, explicit_method_id

__all__ = [
    "STANDARD_HTTP_METHODS",
    "WadlRulePack",
]

#: The HTTP methods OpenAPI 3.1 has a Path Item slot for.
STANDARD_HTTP_METHODS = frozenset({"GET", "PUT", "POST", "DELETE", "OPTIONS", "HEAD", "PATCH", "TRACE"})

#: Methods whose request body has no defined semantics (RFC 9110 §9.3.1, §9.3.2, §9.3.5).
_SAFE_BODYLESS_METHODS = frozenset({"GET", "HEAD", "DELETE"})

_TEMPLATE_VARIABLE = re.compile(r"\{([^{}]+)\}")
_STATUS_CODE = re.compile(r"^[1-5][0-9]{2}$")

#: A finding: ``(path, message)``.
Finding = Tuple[str, str]


def _operations(api: CanonicalApi) -> Iterator[Operation]:
    for service in api.services:
        yield from service.operations


def _leaf_names(ref: Optional[TypeRef]) -> Iterator[str]:
    """The named type(s) a reference points at, through list wrappers."""
    while ref is not None and ref.item is not None:
        ref = ref.item
    if ref is not None and ref.name:
        yield ref.name


def _check_reference_resolved(api: CanonicalApi) -> Iterable[Finding]:
    """Every ``href`` / resource ``type`` must name an element of the document."""
    for reference in api.extras.get("wadl_unresolved_refs") or []:
        kind, _, target = str(reference).partition(" ")
        yield (
            f"references.{target or kind}",
            f"The {kind} reference {target!r} names no element of this document (an external "
            "WADL is not fetched); what it describes is missing from the import. Inline it, or "
            "add the element it names.",
        )


def _check_template_param_declared(api: CanonicalApi) -> Iterable[Finding]:
    """Every ``{name}`` in a path must have a ``template`` param."""
    for operation in _operations(api):
        declared = {p.name for p in operation.parameters if p.location is ParameterLocation.PATH}
        for variable in _TEMPLATE_VARIABLE.findall(operation.http_path or ""):
            if variable not in declared:
                yield (
                    operation.key,
                    f"Path variable {{{variable}}} has no template param; declare "
                    f'<param name="{variable}" style="template" type="xsd:string"/> on its '
                    "resource so it has a type (OpenAPI requires every path variable to be "
                    "declared).",
                )


def _check_template_param_used(api: CanonicalApi) -> Iterable[Finding]:
    """Every ``template`` param must appear as ``{name}`` in the path."""
    for operation in _operations(api):
        used = set(_TEMPLATE_VARIABLE.findall(operation.http_path or ""))
        for param in operation.parameters:
            if param.location is not ParameterLocation.PATH or param.extras.get("wadl_style"):
                continue  # a matrix param is not a template variable
            if param.name not in used:
                yield (
                    param.key,
                    f"Template param {param.name!r} is not used by the path {operation.http_path!r}; "
                    f"add {{{param.name}}} to a resource path or change its style.",
                )


def _check_method_id_unique(api: CanonicalApi) -> Iterable[Finding]:
    """No two methods may share an ``id``."""
    seen: Dict[str, str] = {}
    for operation in _operations(api):
        method_id = explicit_method_id(operation)
        if method_id is None:
            continue
        if method_id in seen:
            yield (
                operation.key,
                f"Method id {method_id!r} is also used by {seen[method_id]!r}; an href to it is "
                "ambiguous and the OpenAPI operationIds collide.",
            )
        else:
            seen[method_id] = operation.key


def _check_method_id_present(api: CanonicalApi) -> Iterable[Finding]:
    """A method should declare an ``id``."""
    for operation in _operations(api):
        if explicit_method_id(operation) is None:
            yield (
                operation.key,
                f"Method {operation.key!r} has no id; the OpenAPI migration has to invent an "
                "operationId, and generated clients are named after it.",
            )


def _check_method_name_standard(api: CanonicalApi) -> Iterable[Finding]:
    """A method's name should be a verb OpenAPI 3.1 can describe."""
    for operation in _operations(api):
        method = (operation.http_method or "").upper()
        if method and method not in STANDARD_HTTP_METHODS:
            yield (
                operation.key,
                f"Method {method!r} is not a standard HTTP method; OpenAPI 3.1 has no slot for it, "
                "so the migration drops it. Map it to a standard verb.",
            )


def _check_body_on_safe_method(api: CanonicalApi) -> Iterable[Finding]:
    """A GET, HEAD or DELETE should not carry a request representation."""
    for operation in _operations(api):
        if (operation.http_method or "").upper() not in _SAFE_BODYLESS_METHODS:
            continue
        if any(m.role is MessageRole.REQUEST for m in operation.messages):
            yield (
                operation.key,
                f"{operation.http_method} carries a request representation; HTTP gives it no "
                "defined meaning and intermediaries may drop it. Send the input as params.",
            )


def _check_response_declared(api: CanonicalApi) -> Iterable[Finding]:
    """A method should declare at least one response."""
    for operation in _operations(api):
        if not any(m.role is MessageRole.RESPONSE for m in operation.messages):
            yield (
                operation.key,
                f"Method {operation.key!r} declares no response; nothing says what a caller gets back.",
            )


def _check_response_status_valid(api: CanonicalApi) -> Iterable[Finding]:
    """A response status must be a three-digit HTTP code."""
    for operation in _operations(api):
        for message in operation.messages:
            status = message.status_code or message.extras.get("http_status")
            if message.role is MessageRole.RESPONSE and status and not _STATUS_CODE.match(str(status)):
                yield (
                    message.key,
                    f"Response status {status!r} is not a three-digit HTTP status code.",
                )


def _check_type_resolved(api: CanonicalApi) -> Iterable[Finding]:
    """Every referenced type must be a built-in or a grammar type."""
    known = CANONICAL_PRIMITIVES | {t.key for t in api.types}

    def unresolved(ref: Optional[TypeRef]) -> List[str]:
        return [name for name in _leaf_names(ref) if name not in known]

    def finding(where: str, name: str) -> Finding:
        return (
            where,
            f"Type {name!r} is neither an XSD built-in nor declared by the grammars (an include "
            "that was not uploaded, or a typo); the catalog keeps the bare name and the OpenAPI "
            "schema has nothing to point at.",
        )

    for type_ in api.types:
        for field in type_.fields:
            for name in unresolved(field.type):
                yield finding(field.key, name)
    for operation in _operations(api):
        for param in operation.parameters:
            for name in unresolved(param.type):
                yield finding(param.key, name)
        for message in operation.messages:
            for name in unresolved(message.payload):
                yield finding(message.key, name)


def _is_structured(media_type: str) -> bool:
    lowered = media_type.lower()
    return "xml" in lowered or "json" in lowered


def _check_representation_typed(api: CanonicalApi) -> Iterable[Finding]:
    """An XML or JSON representation should name its grammar element."""
    for operation in _operations(api):
        for message in operation.messages:
            structured = [m for m in message.content_types if _is_structured(m)]
            if structured and message.payload is None:
                yield (
                    message.key,
                    f"The {structured[0]} representation names no grammar element; it converts "
                    'as an untyped body. Add element="tns:…".',
                )


def _check_representation_media_type(api: CanonicalApi) -> Iterable[Finding]:
    """A typed representation should state its media type."""
    for operation in _operations(api):
        for message in operation.messages:
            if message.payload is not None and not message.content_types:
                yield (
                    message.key,
                    "The representation has a grammar type but no mediaType; the migration has "
                    'to assume one. Add mediaType="application/xml".',
                )


def _check_base_uri_present(api: CanonicalApi) -> Iterable[Finding]:
    """The description should state where its resources live."""
    if not api.servers and any(True for _ in _operations(api)):
        yield (
            "resources.base",
            'No <resources base="…">; the OpenAPI document gets no server and callers cannot tell where the API lives.',
        )


class WadlRulePack(RulePack, register=True):
    """Native rules for WADL artifacts (see the module docstring)."""

    format = "wadl"
    pack_id = "wadl"

    _RULES: Tuple[LintRule, ...] = (
        LintRule(
            rule_id="wadl.reference-resolved",
            category="structure",
            severity="error",
            description="Every href and resource type must name an element of the document.",
            check=_check_reference_resolved,
        ),
        LintRule(
            rule_id="wadl.template-param-declared",
            category="structure",
            severity="error",
            description="Every {name} in a resource path must have a template param.",
            check=_check_template_param_declared,
        ),
        LintRule(
            rule_id="wadl.template-param-used",
            category="structure",
            severity="warning",
            description="Every template param must appear as {name} in the path.",
            check=_check_template_param_used,
        ),
        LintRule(
            rule_id="wadl.method-id-unique",
            category="naming",
            severity="error",
            description="No two methods may share an id.",
            check=_check_method_id_unique,
        ),
        LintRule(
            rule_id="wadl.method-id-present",
            category="naming",
            severity="info",
            description="A method should declare an id (it becomes the OpenAPI operationId).",
            check=_check_method_id_present,
        ),
        LintRule(
            rule_id="wadl.method-name-standard",
            category="compatibility",
            severity="warning",
            description="A method's name should be a standard HTTP method.",
            check=_check_method_name_standard,
        ),
        LintRule(
            rule_id="wadl.body-on-safe-method",
            category="structure",
            severity="warning",
            description="A GET, HEAD or DELETE should not carry a request representation.",
            check=_check_body_on_safe_method,
        ),
        LintRule(
            rule_id="wadl.response-declared",
            category="structure",
            severity="warning",
            description="A method should declare at least one response.",
            check=_check_response_declared,
        ),
        LintRule(
            rule_id="wadl.response-status-valid",
            category="structure",
            severity="warning",
            description="A response status must be a three-digit HTTP code.",
            check=_check_response_status_valid,
        ),
        LintRule(
            rule_id="wadl.type-resolved",
            category="structure",
            severity="warning",
            description="Every referenced type must be an XSD built-in or declared by the grammars.",
            check=_check_type_resolved,
        ),
        LintRule(
            rule_id="wadl.representation-typed",
            category="compatibility",
            severity="info",
            description="An XML or JSON representation should name its grammar element.",
            check=_check_representation_typed,
        ),
        LintRule(
            rule_id="wadl.representation-media-type",
            category="compatibility",
            severity="info",
            description="A typed representation should state its media type.",
            check=_check_representation_media_type,
        ),
        LintRule(
            rule_id="wadl.base-uri-present",
            category="documentation",
            severity="info",
            description="The description should state its resources' base URI.",
            check=_check_base_uri_present,
        ),
    )

    def rules(self) -> List[LintRule]:
        """Return the WADL native rules in deterministic execution order."""
        return list(self._RULES)
