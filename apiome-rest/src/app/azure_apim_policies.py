"""Azure API Management policy documents: reading, scope composition and interpretation — FMT-7.2 (#5456).

An APIM API carries a separate XML **policy** document per scope (global, product, API,
operation). Each document has four pipeline sections — ``inbound``, ``backend``, ``outbound`` and
``on-error`` — and each section is an ordered list of policy elements. The policies express what
the gateway actually enforces: JWT validation, rate limits and quotas, IP filters, CORS, the
backend a request is sent to and how its URL is rewritten. Those facts exist nowhere in the API
definition.

This module is the pure half of the ``azure-apim`` adapter (:mod:`app.azure_apim_import_source`):
no canonical-model construction, no I/O.

* :func:`read_policy_xml` — hardened parse (:mod:`app.secure_xml`) with the intake error taxonomy:
  ``INPUT_TRUNCATED`` for a document that simply ends, ``INPUT_MALFORMED`` for a mis-structured
  one, ``INPUT_SEMANTIC_INVALID`` for a ``<policies>`` root with no pipeline section.
* :func:`compose` — scope composition. ``<base />`` is the composition operator: it is replaced by
  the parent scope's section, at the position it occupies, so the local fragment runs before or
  after the inherited one exactly as APIM evaluates it.
* :func:`interpret` — the policy → canonical mapping. Every record it returns carries
  ``provenance: "declared"`` (the gateway configuration states it), ``derivedFrom: "policy"`` and
  the ``policyScope`` it came from, so a reader can tell policy-derived facts from facts the API
  definition declares (``derivedFrom: "definition"``). A policy element the canonical model has
  no construct for is returned verbatim (as XML) in :attr:`PolicyFacts.unmapped` — never dropped.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .secure_xml import SecureXmlError, parse_xml

__all__ = [
    "COMPOSITION_ROOT",
    "KNOWN_POLICIES",
    "MAPPED_POLICIES",
    "POLICY_ROOT",
    "SCOPES",
    "SECTIONS",
    "PolicyError",
    "PolicyFacts",
    "PolicyItem",
    "ScopedPolicy",
    "compose",
    "is_policy_text",
    "interpret",
    "named_value_references",
    "read_composition",
    "read_policy_xml",
    "verbatim_xml",
]

#: Root element of one policy document.
POLICY_ROOT = "policies"
#: Root of a document carrying several scoped policy documents (``<policy scope="…">`` children).
COMPOSITION_ROOT = "policies-composition"
#: The four pipeline sections, in evaluation order.
SECTIONS: Tuple[str, ...] = ("inbound", "backend", "outbound", "on-error")
#: Policy scopes, outermost first — the order APIM inherits through ``<base />``.
SCOPES: Tuple[str, ...] = ("global", "workspace", "product", "api", "operation")

#: Policies the adapter maps onto canonical constructs (security, rate limits, backend, request
#: rewrite, CORS, access posture).
MAPPED_POLICIES = frozenset(
    {
        "validate-jwt",
        "validate-azure-ad-token",
        "check-header",
        "authentication-certificate",
        "authentication-basic",
        "authentication-managed-identity",
        "rate-limit",
        "rate-limit-by-key",
        "quota",
        "quota-by-key",
        "set-backend-service",
        "rewrite-uri",
        "set-method",
        "set-query-parameter",
        "cors",
        "ip-filter",
    }
)

#: Documented APIM policies with no canonical construct. They are kept verbatim and reported as
#: ``preserved``; any other element is reported as ``unknown`` (a vendor policy, a typo, a policy
#: newer than this list) and is kept verbatim just the same.
KNOWN_POLICIES = MAPPED_POLICIES | frozenset(
    {
        "base",
        "cache-lookup",
        "cache-lookup-value",
        "cache-remove-value",
        "cache-store",
        "cache-store-value",
        "choose",
        "emit-metric",
        "find-and-replace",
        "forward-request",
        "get-authorization-context",
        "include-fragment",
        "invoke-dapr-binding",
        "json-to-xml",
        "jsonp",
        "limit-concurrency",
        "log-to-eventhub",
        "mock-response",
        "proxy",
        "publish-to-dapr",
        "redirect-content-urls",
        "retry",
        "return-response",
        "send-one-way-request",
        "send-request",
        "set-body",
        "set-header",
        "set-status",
        "set-variable",
        "trace",
        "validate-client-certificate",
        "validate-content",
        "validate-graphql-request",
        "validate-headers",
        "validate-odata-request",
        "validate-parameters",
        "validate-status-code",
        "wait",
        "xml-to-json",
        "xsl-transform",
    }
)

#: Control-flow containers whose children are still policies: ``choose`` (through ``when`` and
#: ``otherwise``) and ``retry``. Mapped policies inside them are interpreted and marked
#: ``conditional``; the container itself is preserved verbatim.
_CONTAINERS = frozenset({"choose", "when", "otherwise", "retry"})

#: Attributes whose values are credentials. They are never copied into a record or into the
#: verbatim XML of a preserved policy.
_SECRET_ATTRIBUTES = frozenset({"password", "body", "client-secret", "secret"})
_REDACTED = "[redacted]"

#: ``ET.ParseError`` messages that mean the document ran out rather than being mis-structured.
_TRUNCATION_MARKERS = ("unclosed token", "no element found", "unexpected end of data")

#: A named-value reference: ``{{name}}``. APIM substitutes these textually before evaluation.
_NAMED_VALUE_RE = re.compile(r"\{\{\s*([A-Za-z0-9._\-]+)\s*\}\}")
_LEADING_NOISE_RE = re.compile(r"^(?:\s|<\?xml[^>]*\?>|<!--.*?-->)*", re.DOTALL)


class PolicyError(ValueError):
    """A policy document could not be read.

    Attributes:
        code: The intake error-taxonomy code (``INPUT_MALFORMED``, ``INPUT_TRUNCATED``,
            ``INPUT_SEMANTIC_INVALID``, ``INPUT_ENCODING_INVALID``, or the hardened reader's own).
    """

    def __init__(self, message: str, *, code: str = "INPUT_MALFORMED") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class PolicyItem:
    """One policy element at its place in a composed pipeline.

    Attributes:
        element: The policy element.
        scope: The scope whose document declared it (``global`` … ``operation``).
    """

    element: ET.Element
    scope: str


@dataclass
class ScopedPolicy:
    """One policy document and the scope it is attached to.

    Attributes:
        scope: ``global``, ``workspace``, ``product``, ``api`` or ``operation``.
        root: The ``<policies>`` element.
        name: The product or API name the document belongs to, when the source says.
        api: For an operation-scope document, the API that owns the operation.
        operation: For an operation-scope document, the operation name (its OpenAPI operationId).
    """

    scope: str
    root: ET.Element
    name: Optional[str] = None
    api: Optional[str] = None
    operation: Optional[str] = None


@dataclass
class PolicyFacts:
    """What a composed pipeline declares, in canonical shapes (see :func:`interpret`).

    Attributes:
        security: Caller-facing security records (``validate-jwt``, ``check-header``, …).
        rate_limits: ``rate-limit`` / ``quota`` records.
        backend: The backend the request is sent to (last ``set-backend-service`` wins), with the
            backend authentication policies folded in; ``None`` when no policy sets one.
        rewrite: The request rewrite toward the backend (``rewrite-uri``, ``set-method``,
            ``set-query-parameter``); ``None`` when there is none.
        cors: The ``cors`` policy; ``None`` when there is none.
        access: ``ip-filter`` records.
        mapped: ``{policy, scope, section}`` for every mapped element, in pipeline order.
        unmapped: ``{name, status, scope, section, xml}`` for every element the canonical model
            has no construct for — ``status`` is ``preserved`` (documented APIM policy) or
            ``unknown``.
        backend_ids: Every ``backend-id`` a ``set-backend-service`` names.
        inherits: Sections whose ``<base />`` could not be expanded (no parent scope supplied).
    """

    security: List[Dict[str, Any]] = field(default_factory=list)
    rate_limits: List[Dict[str, Any]] = field(default_factory=list)
    backend: Optional[Dict[str, Any]] = None
    rewrite: Optional[Dict[str, Any]] = None
    cors: Optional[Dict[str, Any]] = None
    access: List[Dict[str, Any]] = field(default_factory=list)
    mapped: List[Dict[str, Any]] = field(default_factory=list)
    unmapped: List[Dict[str, Any]] = field(default_factory=list)
    backend_ids: List[str] = field(default_factory=list)
    inherits: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------------------


def is_policy_text(text: Optional[str]) -> bool:
    """Whether ``text`` starts (after a prolog and comments) with a policy or composition root.

    A cheap sniff for detection: it never parses, so it cannot raise.
    """
    if not text:
        return False
    head = _LEADING_NOISE_RE.sub("", text[:65536], count=1)
    if head.startswith(f"<{COMPOSITION_ROOT}"):
        return True
    opener = f"<{POLICY_ROOT}"
    return head.startswith(opener) and head[len(opener) : len(opener) + 1] in (">", "/", " ", "\t", "\r", "\n")


def read_policy_xml(text: str, *, source_label: Optional[str] = None) -> ET.Element:
    """Parse a policy (or policy-composition) document and check its shape.

    Args:
        text: The XML text.
        source_label: The file name, for error messages.

    Returns:
        The root element — ``<policies>`` or ``<policies-composition>``.

    Raises:
        PolicyError: ``INPUT_ENCODING_INVALID`` for text that was not UTF-8 (replacement characters
            or NULs from a permissive decode), ``INPUT_TRUNCATED`` / ``INPUT_MALFORMED`` for XML that
            ends early / is mis-structured, ``FORMAT_MISMATCH`` for another root element,
            ``INPUT_SEMANTIC_INVALID`` for a policy document without any pipeline section.
    """
    where = f" ({source_label})" if source_label else ""
    if "\x00" in text or "�" in text or text.startswith("﻿﻿"):
        raise PolicyError(
            f"Policy document{where} is not UTF-8 text (UTF-16 or binary content?)",
            code="INPUT_ENCODING_INVALID",
        )
    try:
        root = parse_xml(text.lstrip("﻿"), source_label=source_label)
    except SecureXmlError as exc:
        code = getattr(exc, "code", None) or "INPUT_MALFORMED"
        if code == "INPUT_MALFORMED" and any(marker in str(exc).lower() for marker in _TRUNCATION_MARKERS):
            raise PolicyError(f"Policy document ends unexpectedly: {exc}", code="INPUT_TRUNCATED") from exc
        raise PolicyError(str(exc), code=code) from exc
    tag = _local(root.tag)
    if tag == POLICY_ROOT:
        _check_sections(root, where)
    elif tag == COMPOSITION_ROOT:
        policies = read_composition(root)
        if not policies:
            raise PolicyError(
                f'Policy composition{where} carries no <policy scope="…"><policies> document.',
                code="INPUT_SEMANTIC_INVALID",
            )
        for scoped in policies:
            _check_sections(scoped.root, where)
    else:
        raise PolicyError(
            f"Document{where} is XML with root <{tag}>, not an APIM <policies> document.",
            code="FORMAT_MISMATCH",
        )
    return root


def _check_sections(root: ET.Element, where: str) -> None:
    if not any(_local(child.tag) in SECTIONS for child in root):
        raise PolicyError(
            f"Policy document{where} has none of the pipeline sections "
            f"({', '.join(SECTIONS)}), so it defines no policy.",
            code="INPUT_SEMANTIC_INVALID",
        )


def read_composition(root: ET.Element) -> List[ScopedPolicy]:
    """The scoped documents of a ``<policies-composition>`` root, in document order.

    Each ``<policy>`` child names its ``scope`` and, depending on the scope, ``name`` (product or
    API), ``api`` and ``operation``.
    """
    found: List[ScopedPolicy] = []
    for child in root:
        if _local(child.tag) != "policy":
            continue
        inner = next((c for c in child if _local(c.tag) == POLICY_ROOT), None)
        if inner is None:
            continue
        scope = (child.get("scope") or "api").strip().lower()
        found.append(
            ScopedPolicy(
                scope=scope if scope in SCOPES else "api",
                root=inner,
                name=child.get("name"),
                api=child.get("api"),
                operation=child.get("operation"),
            )
        )
    return found


def named_value_references(text: str) -> List[str]:
    """Every ``{{named-value}}`` a policy text refers to, sorted and deduplicated."""
    return sorted({m.group(1) for m in _NAMED_VALUE_RE.finditer(text or "")})


# ---------------------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------------------


Pipeline = Dict[str, List[PolicyItem]]


def compose(local: Optional[ScopedPolicy], parent: Optional[Pipeline]) -> Tuple[Pipeline, List[str]]:
    """The effective pipeline of ``local`` with ``<base />`` replaced by the parent's section.

    Args:
        local: The scope's own document; ``None`` when the scope declares none, in which case the
            parent pipeline applies unchanged (APIM's implicit inheritance).
        parent: The parent scope's effective pipeline; ``None`` when no parent is known.

    Returns:
        ``(pipeline, unresolved)`` — the per-section items in evaluation order, and the sections
        whose ``<base />`` could not be expanded because no parent was supplied. An unexpanded
        ``<base />`` stays in the pipeline as an item so its position is not lost.
    """
    if local is None:
        return ({s: list(items) for s, items in (parent or {}).items()}, [])
    pipeline: Pipeline = {}
    unresolved: List[str] = []
    for section_el in local.root:
        section = _local(section_el.tag)
        if section not in SECTIONS:
            continue
        items: List[PolicyItem] = []
        for element in section_el:
            if not isinstance(element.tag, str):
                continue
            if _local(element.tag) == "base":
                if parent is not None:
                    items.extend(parent.get(section, []))
                else:
                    items.append(PolicyItem(element, local.scope))
                    if section not in unresolved:
                        unresolved.append(section)
            else:
                items.append(PolicyItem(element, local.scope))
        pipeline[section] = items
    return pipeline, unresolved


# ---------------------------------------------------------------------------------------
# Interpretation
# ---------------------------------------------------------------------------------------


def interpret(
    pipeline: Pipeline,
    *,
    backends: Optional[Mapping[str, Mapping[str, Any]]] = None,
    unresolved: Sequence[str] = (),
) -> PolicyFacts:
    """Map a composed pipeline onto canonical shapes.

    Args:
        pipeline: Section → items, from :func:`compose`.
        backends: Known APIM backends by id (``{"url": …, "protocol": …}``), used to resolve a
            ``set-backend-service backend-id``.
        unresolved: Sections whose ``<base />`` was not expanded (copied to ``facts.inherits``).

    Returns:
        The :class:`PolicyFacts`. Every record carries ``provenance: "declared"``,
        ``derivedFrom: "policy"`` and ``policyScope``; records found inside ``choose`` or
        ``retry`` also carry ``conditional: true``.
    """
    facts = PolicyFacts(inherits=list(unresolved))
    for section in SECTIONS:
        for item in pipeline.get(section, []):
            _visit(item.element, item.scope, section, facts, backends or {}, conditional=False)
    return facts


def _visit(
    element: ET.Element,
    scope: str,
    section: str,
    facts: PolicyFacts,
    backends: Mapping[str, Mapping[str, Any]],
    *,
    conditional: bool,
) -> None:
    name = _local(element.tag)
    if name == "base":
        return
    if name in MAPPED_POLICIES:
        record_base = {"provenance": "declared", "derivedFrom": "policy", "policyScope": scope}
        if conditional:
            record_base["conditional"] = True
        _map(name, element, section, facts, backends, record_base)
        facts.mapped.append({"policy": name, "scope": scope, "section": section})
        return
    facts.unmapped.append(
        {
            "name": name,
            "status": "preserved" if name in KNOWN_POLICIES else "unknown",
            "scope": scope,
            "section": section,
            "xml": verbatim_xml(element),
        }
    )
    if name in _CONTAINERS:
        for child in element:
            if isinstance(child.tag, str):
                child_name = _local(child.tag)
                if child_name in ("when", "otherwise"):
                    for grandchild in child:
                        if isinstance(grandchild.tag, str):
                            _visit(grandchild, scope, section, facts, backends, conditional=True)
                elif child_name in MAPPED_POLICIES:
                    _visit(child, scope, section, facts, backends, conditional=True)


def _map(
    name: str,
    element: ET.Element,
    section: str,
    facts: PolicyFacts,
    backends: Mapping[str, Mapping[str, Any]],
    base: Dict[str, Any],
) -> None:
    if name in ("validate-jwt", "validate-azure-ad-token"):
        facts.security.append({**_jwt_record(name, element), **base})
    elif name == "check-header":
        facts.security.append(
            {
                "scheme": "headerCheck",
                "name": name,
                "scopes": [],
                "in": "header",
                "parameterName": element.get("name"),
                "failedStatus": _int(element.get("failed-check-httpcode")),
                "valueCount": len([c for c in element if _local(c.tag) == "value"]),
                **base,
            }
        )
    elif name in ("authentication-certificate", "authentication-basic", "authentication-managed-identity"):
        backend = facts.backend or {"kind": "http", **base}
        backend["authentication"] = {"type": name.split("-", 1)[1], **_safe_attributes(element)}
        facts.backend = backend
    elif name in ("rate-limit", "rate-limit-by-key", "quota", "quota-by-key"):
        facts.rate_limits.append({**_limit_record(name, element), **base})
    elif name == "set-backend-service":
        backend = {"kind": "http", **base}
        if element.get("base-url"):
            backend["uri"] = element.get("base-url")
        backend_id = element.get("backend-id")
        if backend_id:
            backend["backendId"] = backend_id
            facts.backend_ids.append(backend_id)
            known = backends.get(backend_id)
            backend["resolved"] = known is not None
            if known is not None and known.get("url"):
                backend["uri"] = known["url"]
        previous = facts.backend or {}
        if "authentication" in previous:
            backend["authentication"] = previous["authentication"]
        facts.backend = backend
    elif name in ("rewrite-uri", "set-method", "set-query-parameter"):
        rewrite = facts.rewrite or {**base}
        if name == "rewrite-uri":
            rewrite["uriTemplate"] = element.get("template")
            if element.get("copy-unmatched-params") is not None:
                rewrite["copyUnmatchedParams"] = _bool(element.get("copy-unmatched-params"))
        elif name == "set-method":
            rewrite["method"] = (element.text or "").strip().upper() or None
        else:
            rewrite.setdefault("queryParameters", []).append(
                {
                    "name": element.get("name"),
                    "existsAction": element.get("exists-action"),
                    "values": [(c.text or "").strip() for c in element if _local(c.tag) == "value"],
                }
            )
        facts.rewrite = rewrite
    elif name == "cors":
        facts.cors = {**_cors_record(element), "source": "cors-policy", **base}
    elif name == "ip-filter":
        facts.access.append(
            {
                "kind": "ip-filter",
                "action": element.get("action"),
                "addresses": [(c.text or "").strip() for c in element if _local(c.tag) == "address"],
                "addressRanges": [
                    {"from": c.get("from"), "to": c.get("to")} for c in element if _local(c.tag) == "address-range"
                ],
                **base,
            }
        )


def _jwt_record(name: str, element: ET.Element) -> Dict[str, Any]:
    """A ``validate-jwt`` / ``validate-azure-ad-token`` element as a canonical security record.

    The scheme is ``openIdConnect`` when the policy names an OpenID configuration, else
    ``bearer``. Scopes are read from a required ``scp`` / ``scope`` / ``roles`` claim.
    """
    openid = next((c.get("url") for c in element if _local(c.tag) == "openid-config"), None)
    claims = []
    scopes: List[str] = []
    for container in element:
        if _local(container.tag) != "required-claims":
            continue
        for claim in container:
            if _local(claim.tag) != "claim":
                continue
            values = [(v.text or "").strip() for v in claim if _local(v.tag) == "value"]
            claims.append({"name": claim.get("name"), "match": claim.get("match") or "all", "values": values})
            if (claim.get("name") or "").lower() in ("scp", "scope", "roles"):
                scopes.extend(values)
    record: Dict[str, Any] = {
        "scheme": "openIdConnect" if openid else "bearer",
        "name": name,
        "scopes": scopes,
        "in": "query" if element.get("query-parameter-name") else "header",
        "parameterName": element.get("query-parameter-name") or element.get("header-name") or "Authorization",
    }
    if openid:
        record["openIdConnectUrl"] = openid
    if name == "validate-azure-ad-token" and element.get("tenant-id"):
        record["tenantId"] = element.get("tenant-id")
    audiences = _texts(element, "audiences", "audience")
    if audiences:
        record["audiences"] = audiences
    issuers = _texts(element, "issuers", "issuer")
    if issuers:
        record["issuers"] = issuers
    if claims:
        record["requiredClaims"] = claims
    status = _int(element.get("failed-validation-httpcode"))
    if status is not None:
        record["failedStatus"] = status
    return record


def _limit_record(name: str, element: ET.Element) -> Dict[str, Any]:
    """A ``rate-limit`` / ``quota`` element (``-by-key`` included) as a rate-limit record."""
    record: Dict[str, Any] = {
        "kind": "quota" if name.startswith("quota") else "rate-limit",
        "policy": name,
        "byKey": name.endswith("-by-key"),
        "calls": _int(element.get("calls")),
        "renewalPeriodSeconds": _int(element.get("renewal-period")),
    }
    if element.get("bandwidth") is not None:
        record["bandwidthKilobytes"] = _int(element.get("bandwidth"))
    if element.get("counter-key"):
        record["counterKey"] = element.get("counter-key")
    if element.get("increment-condition"):
        record["incrementCondition"] = element.get("increment-condition")
    nested = [
        {
            "element": _local(c.tag),
            "name": c.get("name") or c.get("id"),
            "calls": _int(c.get("calls")),
            "renewalPeriodSeconds": _int(c.get("renewal-period")),
        }
        for c in element
        if _local(c.tag) in ("api", "operation")
    ]
    if nested:
        record["nested"] = nested
    return record


def _cors_record(element: ET.Element) -> Dict[str, Any]:
    """A ``cors`` element in the CORS shape AWS imports also write (``allowOrigins`` …)."""
    record: Dict[str, Any] = {
        "allowOrigins": _texts(element, "allowed-origins", "origin"),
        "allowMethods": _texts(element, "allowed-methods", "method"),
        "allowHeaders": _texts(element, "allowed-headers", "header"),
        "exposeHeaders": _texts(element, "expose-headers", "header"),
        "allowCredentials": _bool(element.get("allow-credentials")),
    }
    methods = next((c for c in element if _local(c.tag) == "allowed-methods"), None)
    if methods is not None and methods.get("preflight-result-max-age") is not None:
        record["maxAge"] = _int(methods.get("preflight-result-max-age"))
    return record


# ---------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------


def verbatim_xml(element: ET.Element) -> str:
    """The element serialized as XML, with credential attributes redacted and its tail dropped."""
    clone = _redacted_copy(element)
    clone.tail = None
    return ET.tostring(clone, encoding="unicode")


def _redacted_copy(element: ET.Element) -> ET.Element:
    clone = ET.Element(
        element.tag, {k: (_REDACTED if k in _SECRET_ATTRIBUTES else v) for k, v in element.attrib.items()}
    )
    clone.text = element.text
    clone.tail = element.tail
    for child in element:
        if isinstance(child.tag, str):
            clone.append(_redacted_copy(child))
    return clone


def _safe_attributes(element: ET.Element) -> Dict[str, Any]:
    """The element's attributes in camelCase, credentials omitted (their presence is noted)."""
    out: Dict[str, Any] = {}
    for key, value in sorted(element.attrib.items()):
        if key in _SECRET_ATTRIBUTES:
            out["hasSecret"] = True
            continue
        out[_camel(key)] = value
    return out


def _camel(name: str) -> str:
    head, *rest = name.split("-")
    return head + "".join(part[:1].upper() + part[1:] for part in rest)


def _texts(element: ET.Element, container: str, item: str) -> List[str]:
    found = next((c for c in element if _local(c.tag) == container), None)
    if found is None:
        return []
    return [(c.text or "").strip() for c in found if _local(c.tag) == item]


def _local(tag: Any) -> str:
    """An element's local name (namespace dropped); empty for comments and processing instructions."""
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1]


def _int(value: Optional[str]) -> Optional[int]:
    try:
        return int(str(value).strip()) if value is not None else None
    except ValueError:
        return None


def _bool(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() == "true"
