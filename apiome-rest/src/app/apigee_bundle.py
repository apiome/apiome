"""Apigee proxy bundles: reading, condition reduction and policy interpretation — FMT-7.3 (#5457).

An Apigee proxy bundle is a zip of ``apiproxy/`` XML::

    apiproxy/<name>.xml            APIProxy manifest: name, revision, base paths, inventories
    apiproxy/proxies/<pe>.xml      ProxyEndpoint: HTTPProxyConnection base path, flows, route rules
    apiproxy/targets/<te>.xml      TargetEndpoint: HTTPTargetConnection URL or load balancer
    apiproxy/policies/<p>.xml      one file per policy, root element = the policy type

This module is the pure half of the ``apigee`` adapter (:mod:`app.apigee_import_source`): it reads
member texts into an :class:`ApigeeBundle` and answers the questions the adapter asks of it. No
canonical-model construction, no I/O.

**Conditions are boolean expressions, not path matches.** :func:`reduce_condition` splits a
condition on its top-level ``and`` and keeps the parts it understands — ``proxy.pathsuffix
MatchesPath "/orders/*"`` (or ``=``) and ``request.verb = "GET"`` — as a path and a verb. Everything
else (a header test, a variable comparison, an ``or``, a ``not``) is returned as *unreduced* text, so
the adapter records it as a **declared condition** instead of dropping it.

**Policies** become canonical shapes by type (:func:`interpret_policy`): ``VerifyAPIKey`` and
``OAuthV2`` → security records, ``SpikeArrest`` and ``Quota`` → rate-limit records, an
``AssignMessage`` that sets ``Access-Control-*`` headers → CORS. Any other policy is preserved
verbatim. Every record carries ``provenance: "declared"``.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .secure_xml import SecureXmlError, parse_xml

__all__ = [
    "BUNDLE_ROOTS",
    "MAPPED_POLICY_TYPES",
    "ApigeeBundle",
    "BundleError",
    "Endpoint",
    "ReducedCondition",
    "Step",
    "classify_xml_root",
    "interpret_policy",
    "path_template",
    "read_bundle",
    "reduce_condition",
]

#: Root elements a member may have, and what each one is.
BUNDLE_ROOTS = {
    "APIProxy": "manifest",
    "ProxyEndpoint": "proxy",
    "TargetEndpoint": "target",
    "SharedFlow": "shared-flow",
    "SharedFlowBundle": "shared-flow-manifest",
}

#: Policy types the adapter maps onto canonical constructs.
MAPPED_POLICY_TYPES = frozenset({"VerifyAPIKey", "OAuthV2", "SpikeArrest", "Quota", "AssignMessage"})

_TRUNCATION_MARKERS = ("unclosed token", "no element found", "unexpected end of data")
_LEADING_NOISE_RE = re.compile(r"^(?:\s|<\?xml[^>]*\?>|<!--.*?-->)*", re.DOTALL)
_ROOT_TAG_RE = re.compile(r"<([A-Za-z][\w.-]*)")
_PATH_RE = re.compile(r'^proxy\.pathsuffix\s+(MatchesPath|~/|=|==|Equals)\s+"([^"]*)"$', re.IGNORECASE)
_VERB_RE = re.compile(r'^request\.verb\s+(=|==|Equals)\s+"([A-Za-z]+)"$', re.IGNORECASE)


class BundleError(ValueError):
    """A bundle (or a loose endpoint file) could not be read.

    Attributes:
        code: The intake error-taxonomy code.
    """

    def __init__(self, message: str, *, code: str = "INPUT_MALFORMED") -> None:
        super().__init__(message)
        self.code = code


@dataclass
class Step:
    """One ``<Step>``: the policy it runs and the condition it runs under, if any."""

    name: str
    condition: Optional[str] = None


@dataclass
class Endpoint:
    """A ``ProxyEndpoint`` or ``TargetEndpoint`` (only the parts the adapter reads).

    Attributes:
        name: The endpoint's ``name``.
        root: Its parsed element.
    """

    name: str
    root: ET.Element


@dataclass
class ApigeeBundle:
    """Everything a bundle (or a fileset of loose files) carries.

    Attributes:
        manifest: The ``APIProxy`` element, when the input is a bundle.
        proxies: ProxyEndpoints by name.
        targets: TargetEndpoints by name.
        policies: Policy elements by policy name.
        shared_flows: SharedFlow elements by name (a fileset may carry one).
        resources: Paths of non-XML resources (``resources/jsc/*.js``…), listed, never interpreted.
        members: Member path → member kind, for the report.
    """

    manifest: Optional[ET.Element] = None
    proxies: Dict[str, Endpoint] = field(default_factory=dict)
    targets: Dict[str, Endpoint] = field(default_factory=dict)
    policies: Dict[str, ET.Element] = field(default_factory=dict)
    shared_flows: Dict[str, ET.Element] = field(default_factory=dict)
    resources: List[str] = field(default_factory=list)
    members: Dict[str, str] = field(default_factory=dict)


@dataclass
class ReducedCondition:
    """What a condition says about the request, and what it says that cannot be reduced.

    Attributes:
        path: The ``proxy.pathsuffix`` pattern, when one conjunct names it.
        verb: The ``request.verb``, when one conjunct names it.
        unreduced: The conjuncts (or the whole expression) that are not a path or verb match.
    """

    path: Optional[str] = None
    verb: Optional[str] = None
    unreduced: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------------------


def classify_xml_root(text: Optional[str]) -> Optional[str]:
    """The bundle kind of an XML text from its root element name (``manifest``, ``proxy``…).

    A cheap sniff for detection: it never parses, so it cannot raise.
    """
    if not text:
        return None
    head = _LEADING_NOISE_RE.sub("", text[:65536], count=1)
    match = _ROOT_TAG_RE.match(head)
    return BUNDLE_ROOTS.get(match.group(1)) if match else None


def _parse(text: str, label: str) -> ET.Element:
    if "\x00" in text or "�" in text:
        raise BundleError(f"{label} is not UTF-8 text (UTF-16 or binary content?)", code="INPUT_ENCODING_INVALID")
    try:
        return parse_xml(text.lstrip("﻿"), source_label=label)
    except SecureXmlError as exc:
        code = getattr(exc, "code", None) or "INPUT_MALFORMED"
        if code == "INPUT_MALFORMED" and any(marker in str(exc).lower() for marker in _TRUNCATION_MARKERS):
            raise BundleError(f"{label} ends unexpectedly: {exc}", code="INPUT_TRUNCATED") from exc
        raise BundleError(str(exc), code=code) from exc


def read_bundle(members: Mapping[str, str]) -> ApigeeBundle:
    """Read member texts (a bundle's, or a fileset of loose files) into an :class:`ApigeeBundle`.

    A member is classified by its root element; a member under ``policies/`` (or any other XML
    member whose root is not an endpoint) is a policy named by its ``name`` attribute (else its file
    stem). Non-XML members are resources.

    Raises:
        BundleError: For a member that is not well-formed or not UTF-8.
    """
    bundle = ApigeeBundle()
    for path in sorted(members):
        text = members[path]
        if not path.lower().endswith(".xml"):
            bundle.resources.append(path)
            bundle.members[path] = "resource"
            continue
        root = _parse(text, path)
        tag = _local(root.tag)
        kind = BUNDLE_ROOTS.get(tag, "policy")
        name = root.get("name") or PurePosixPath(path).stem
        bundle.members[path] = kind
        if kind == "manifest":
            bundle.manifest = root
        elif kind == "proxy":
            bundle.proxies[name] = Endpoint(name, root)
        elif kind == "target":
            bundle.targets[name] = Endpoint(name, root)
        elif kind == "shared-flow":
            bundle.shared_flows[name] = root
        elif kind == "policy":
            bundle.policies[name] = root
    return bundle


# ---------------------------------------------------------------------------------------
# Conditions
# ---------------------------------------------------------------------------------------


def _split_top(expression: str, word: str) -> List[str]:
    """Split ``expression`` on a top-level boolean ``word`` (outside quotes and parentheses)."""
    parts: List[str] = []
    depth, quoted, start, i = 0, False, 0, 0
    lowered = expression.lower()
    while i < len(expression):
        char = expression[i]
        if char == '"':
            quoted = not quoted
        elif not quoted and char == "(":
            depth += 1
        elif not quoted and char == ")":
            depth -= 1
        elif not quoted and depth == 0 and lowered.startswith(f" {word} ", i):
            parts.append(expression[start:i])
            i += len(word) + 2
            start = i
            continue
        i += 1
    parts.append(expression[start:])
    return [p.strip() for p in parts if p.strip()]


def _unwrap(text: str) -> str:
    text = text.strip()
    while text.startswith("(") and text.endswith(")") and _balanced(text[1:-1]):
        text = text[1:-1].strip()
    return text


def _balanced(text: str) -> bool:
    depth, quoted = 0, False
    for char in text:
        if char == '"':
            quoted = not quoted
        elif not quoted and char == "(":
            depth += 1
        elif not quoted and char == ")":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def reduce_condition(expression: Optional[str]) -> ReducedCondition:
    """Reduce a flow or route-rule condition to a path and a verb where it can be.

    Args:
        expression: The ``<Condition>`` text, or ``None``.

    Returns:
        The :class:`ReducedCondition`. An expression with a top-level ``or``, or a ``not``, is
        unreduced as a whole: neither half can be relied on alone.
    """
    reduced = ReducedCondition()
    text = _unwrap(" ".join((expression or "").split()))
    if not text:
        return reduced
    if len(_split_top(text, "or")) > 1 or re.search(r"(^|[\s(])(not|!)[\s(]", text, re.IGNORECASE):
        reduced.unreduced.append(text)
        return reduced
    for conjunct in _split_top(text, "and"):
        part = _unwrap(conjunct)
        path_match = _PATH_RE.match(part)
        verb_match = _VERB_RE.match(part)
        if path_match and reduced.path is None and path_match.group(1) != "~/":
            reduced.path = path_match.group(2)
        elif verb_match and reduced.verb is None:
            reduced.verb = verb_match.group(2).upper()
        else:
            reduced.unreduced.append(part)
    return reduced


def path_template(base_path: str, suffix: Optional[str]) -> Tuple[str, List[Tuple[str, bool]]]:
    """Join a base path and a ``MatchesPath`` pattern into a path template.

    ``*`` (one segment) becomes ``{segment1}``, ``{segment2}``…; ``**`` (any number of segments)
    becomes ``{path}``.

    Returns:
        ``(template, parameters)`` — each parameter is ``(name, greedy)``.
    """
    base = "/" + (base_path or "").strip("/")
    params: List[Tuple[str, bool]] = []
    segments: List[str] = []
    for segment in (suffix or "").strip("/").split("/"):
        if not segment:
            continue
        if segment == "**":
            params.append(("path", True))
            segments.append("{path}")
        elif segment == "*":
            name = f"segment{sum(1 for _, greedy in params if not greedy) + 1}"
            params.append((name, False))
            segments.append("{" + name + "}")
        else:
            segments.append(segment)
    joined = "/".join(([base.strip("/")] if base != "/" else []) + segments)
    return "/" + joined if joined else "/", params


# ---------------------------------------------------------------------------------------
# Endpoint reading helpers
# ---------------------------------------------------------------------------------------


def _local(tag: Any) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def child(element: Optional[ET.Element], name: str) -> Optional[ET.Element]:
    """The first direct child named ``name``."""
    if element is None:
        return None
    return next((c for c in element if _local(c.tag) == name), None)


def text_of(element: Optional[ET.Element], name: str) -> Optional[str]:
    """The stripped text of the first direct child named ``name``, or ``None``."""
    found = child(element, name)
    value = (found.text or "").strip() if found is not None else ""
    return value or None


def steps_of(phase: Optional[ET.Element]) -> List[Step]:
    """The ``<Step>`` elements directly under ``phase`` (a ``Request``/``Response``/``SharedFlow``)."""
    if phase is None:
        return []
    return [
        Step(name=text_of(step, "Name") or "", condition=text_of(step, "Condition"))
        for step in phase
        if _local(step.tag) == "Step" and text_of(step, "Name")
    ]


def verbatim_xml(element: ET.Element) -> str:
    """The element serialized as XML (its tail dropped)."""
    tail, element.tail = element.tail, None
    try:
        return ET.tostring(element, encoding="unicode")
    finally:
        element.tail = tail


# ---------------------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------------------


def _ref_location(ref: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """``request.header.x-api-key`` → ``("header", "x-api-key")``; ``request.queryparam.k`` → query."""
    text = (ref or "").strip()
    for prefix, where in (
        ("request.header.", "header"),
        ("request.queryparam.", "query"),
        ("request.formparam.", "form"),
    ):
        if text.lower().startswith(prefix):
            return where, text[len(prefix) :]
    return None, None


def interpret_policy(name: str, policy: ET.Element) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Map one policy onto a canonical shape.

    Args:
        name: The policy name (what a ``<Step>`` refers to).
        policy: The policy element (its tag is the policy type).

    Returns:
        ``(target, record)`` — ``target`` is ``security``, ``rate_limits``, ``cors`` or ``unmapped``;
        ``record`` is the canonical record (``None`` for ``unmapped``).
    """
    kind = _local(policy.tag)
    base = {"policy": name, "policyType": kind, "provenance": "declared"}
    if kind == "VerifyAPIKey":
        api_key = child(policy, "APIKey")
        where, param = _ref_location(api_key.get("ref") if api_key is not None else None)
        return "security", {
            "scheme": "apiKey",
            "name": name,
            "scopes": [],
            "in": where or "header",
            "parameterName": param,
            **base,
        }
    if kind == "OAuthV2":
        operation = text_of(policy, "Operation") or "VerifyAccessToken"
        if operation != "VerifyAccessToken":
            return "unmapped", None
        scopes = (text_of(policy, "Scope") or "").split()
        return "security", {
            "scheme": "oauth2",
            "name": name,
            "scopes": scopes,
            "in": "header",
            "parameterName": "Authorization",
            **base,
        }
    if kind == "SpikeArrest":
        identifier = child(policy, "Identifier")
        return "rate_limits", {
            "kind": "spike-arrest",
            "rate": text_of(policy, "Rate"),
            "identifier": identifier.get("ref") if identifier is not None else None,
            **base,
        }
    if kind == "Quota":
        allow = child(policy, "Allow")
        identifier = child(policy, "Identifier")
        count = allow.get("count") if allow is not None else None
        return "rate_limits", {
            "kind": "quota",
            "calls": int(count) if count and count.isdigit() else count,
            "interval": text_of(policy, "Interval"),
            "timeUnit": text_of(policy, "TimeUnit"),
            "identifier": identifier.get("ref") if identifier is not None else None,
            "distributed": (text_of(policy, "Distributed") or "").lower() == "true",
            **base,
        }
    if kind == "AssignMessage":
        headers = {}
        for container in (child(child(policy, "Set"), "Headers"), child(child(policy, "Add"), "Headers")):
            for header in container if container is not None else []:
                if _local(header.tag) == "Header" and (header.get("name") or "").lower().startswith("access-control-"):
                    headers[header.get("name").lower()] = (header.text or "").strip()
        if not headers:
            return "unmapped", None
        split = lambda key: [v.strip() for v in headers.get(key, "").split(",") if v.strip()]  # noqa: E731
        return "cors", {
            "allowOrigins": split("access-control-allow-origin"),
            "allowMethods": split("access-control-allow-methods"),
            "allowHeaders": split("access-control-allow-headers"),
            "exposeHeaders": split("access-control-expose-headers"),
            "allowCredentials": headers.get("access-control-allow-credentials", "").lower() == "true",
            "source": "assign-message",
            **base,
        }
    return "unmapped", None
