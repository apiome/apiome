"""Agentic-web site manifest parser — MFI-18.3 (#3976).

A site that speaks to agents publishes a small, site-level manifest that names the agent protocols
it supports and where their descriptors live. They are the agentic web's ``robots.txt``: crawl
seeds that point at every other agent descriptor (A2A cards, ACP listings, MCP servers). This
module reads four such **dialects** into one typed :class:`AgentsManifest`:

* ``agents-json`` — the ``/agents.json`` companion of agents.txt (https://agents-txt.com):
  ``{version, site: {name, url}, mcp: [{url}], a2a: [{url, description}], skills: [...],
  ucp: [...], webmcp: [...], payments: {x402: {...}, ap2: {...}}}``;
* ``awp`` — the Agent Web Protocol manifest at ``/.well-known/agent.json``
  (https://www.agentwebprotocol.org): ``{awp_version, domain, intent, protocols: {a2a:
  {version, endpoint, agent_card}, mcp: {...}, x402: {...}}, actions: [{id, method, endpoint,
  via}], auth: {...}}``;
* ``agents-txt`` — ``/agents.txt``: ``Directive: value`` lines (``MCP:``, ``A2A:``, ``Skills:``,
  ``UCP:``, ``WebMCP:``, ``Protocols:``, ``Authorization:``) with ``#`` comments;
* ``llms-txt`` — ``/llms.txt`` (https://llmstxt.org): an H1 title, an optional ``>`` summary
  and H2 sections of ``- [name](url): notes`` links. Each link is classified by its URL
  (an Agent Card, an MCP endpoint, an OpenAPI document, another manifest, or plain docs).

Every declared address becomes a :class:`ManifestEndpoint` (its protocol, the URL as written and
the URL resolved against the site). Payment layers — x402, AP2, MPP and the like — are kept as
:class:`PaymentDeclaration` metadata only, never as endpoints of their own: they say how a site is
paid, not what it serves. :func:`discovery_seeds` lists the endpoints another importer can follow
(an A2A card, an ACP server, an MCP server, a nested manifest), which is how a manifest seeds
discovery of the descriptors it references.

Failures carry the shared intake-taxonomy codes, exactly as the A2A and ACP parsers do.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urljoin, urlsplit

from .intake_resource_guard import IntakeLimitError, guard_document_text, guard_parsed_document
from .mcp_manifest_parser import is_unclosed_json

__all__ = [
    "DIALECTS",
    "PAYMENT_PROTOCOLS",
    "SEED_IMPORTERS",
    "AgentsManifest",
    "AgentsManifestParseError",
    "DiscoverySeed",
    "ManifestAction",
    "ManifestEndpoint",
    "PaymentDeclaration",
    "classify_link",
    "detect_dialect",
    "discovery_seeds",
    "dumps_manifest_for_raw",
    "is_agents_json_document",
    "is_awp_document",
    "parse_agents_manifest",
]

#: The four dialects this parser reads.
DIALECTS: Tuple[str, ...] = ("agents-json", "awp", "agents-txt", "llms-txt")

#: Protocol ids that describe how a site is *paid*, not what it serves. They are captured as
#: payment metadata, never as endpoints (MFI-18.3 scope: "AP2 / x402 … endpoint metadata only").
PAYMENT_PROTOCOLS: Tuple[str, ...] = ("x402", "ap2", "mpp", "payment", "skyfire")

#: Endpoint protocols an apiome importer can follow, and how: an import source key for a
#: descriptor the catalog imports live, or ``mcp-probe`` for an MCP server (which is probed, not
#: imported as a file). Every other protocol is recorded but seeds nothing.
SEED_IMPORTERS: Dict[str, str] = {
    "a2a": "a2a",
    "acp": "acp",
    "mcp": "mcp-probe",
    "manifest": "agents-manifest",
}

#: Endpoint list keys of an ``agents.json`` (agents-txt.com) document, in the order they are read.
_AGENTS_JSON_ENDPOINT_KEYS: Tuple[str, ...] = ("a2a", "mcp", "acp", "skills", "ucp", "webmcp")

#: ``agents.txt`` directives that declare an endpoint, by lower-cased name → protocol id.
_TXT_ENDPOINT_DIRECTIVES: Dict[str, str] = {
    "a2a": "a2a",
    "mcp": "mcp",
    "acp": "acp",
    "skills": "skills",
    "ucp": "ucp",
    "webmcp": "webmcp",
}

#: ``agents.txt`` directives that carry a policy hint rather than an address.
_TXT_POLICY_DIRECTIVES: Tuple[str, ...] = ("payments", "identity")

#: Root keys that prove a JSON document is another format, so failures read ``FORMAT_MISMATCH``.
#: ``skills`` is *not* here — agents.json lists skills too; an A2A card is told apart by its
#: card-only keys (:data:`_A2A_CARD_MARKERS`).
_FOREIGN_FORMAT_MARKERS: Tuple[str, ...] = (
    "openapi",
    "swagger",
    "asyncapi",
    "arazzo",
    "openrpc",
    "discoveryVersion",
    "mcpVersion",
    "input_content_types",
    "output_content_types",
)

#: Keys only an A2A Agent Card carries; a document with one of them is a card, not a manifest.
_A2A_CARD_MARKERS: Tuple[str, ...] = (
    "protocolVersion",
    "preferredTransport",
    "defaultInputModes",
    "defaultOutputModes",
    "securitySchemes",
)

#: ``Directive: value`` — an agents.txt line.
_DIRECTIVE_LINE = re.compile(r"^([A-Za-z][A-Za-z0-9-]*)\s*:\s*(.*)$")

#: ``- [name](url)`` optionally followed by ``: notes`` — an llms.txt link item.
_LINK_ITEM = re.compile(r"^\s*[-*+]\s+\[([^\]]*)\]\(\s*([^)\s]*)\s*\)\s*(?::\s*(.*))?$")


class AgentsManifestParseError(ValueError):
    """Raised when a site manifest cannot be parsed.

    Args:
        message: Human-readable description of the failure.
        code: Stable intake-taxonomy code (see :mod:`app.intake_error_taxonomy`).
    """

    def __init__(self, message: str, *, code: Optional[str] = None) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ManifestEndpoint:
    """One address a manifest declares.

    Attributes:
        protocol: Protocol id — ``a2a``, ``mcp``, ``acp``, ``skills``, ``ucp``, ``webmcp``,
            ``openapi``, ``manifest`` (another site manifest), ``docs`` (an llms.txt link), or an
            ``x-`` experimental id.
        url: The address exactly as written (may be relative, empty or malformed).
        resolved_url: ``url`` made absolute against the site URL, or ``None`` when it cannot be
            (no site URL to resolve a relative reference against, or not a URL at all).
        title: A display name, when the manifest gives one (an llms.txt link's text).
        description: What the endpoint is, when given.
        attributes: Protocol-specific extras (``version``, ``transport``, ``agent_card``,
            ``section``, ``optional`` …), verbatim.
    """

    protocol: str
    url: str
    resolved_url: Optional[str]
    title: Optional[str] = None
    description: Optional[str] = None
    attributes: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ManifestAction:
    """One AWP action (``actions[]``) — a site operation an agent may call.

    Attributes:
        id: The action id.
        description: What it does, when given.
        method: HTTP method, when given.
        endpoint: The endpoint as written.
        resolved_endpoint: ``endpoint`` resolved against the site URL, when possible.
        via: The protocol id the action is routed through, when given (must be declared in
            ``protocols``).
        operation: The protocol-specific operation name used with ``via``.
        auth_required: Whether the action requires authentication.
        inputs: The declared inputs, verbatim.
    """

    id: str
    description: Optional[str]
    method: Optional[str]
    endpoint: Optional[str]
    resolved_endpoint: Optional[str]
    via: Optional[str]
    operation: Optional[str]
    auth_required: Optional[bool]
    inputs: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PaymentDeclaration:
    """A payment layer the site accepts — metadata only.

    Attributes:
        protocol: ``x402``, ``ap2``, ``mpp``, ``payment``, ``skyfire`` or an ``x-`` id.
        attributes: Whatever the manifest says about it (chains, methods, wallet, endpoint …).
    """

    protocol: str
    attributes: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DiscoverySeed:
    """An endpoint another importer can follow from this manifest.

    Attributes:
        protocol: The endpoint's protocol id.
        url: The absolute URL to follow.
        importer: How to follow it: an import source key (``a2a``, ``acp``,
            ``agents-manifest``) or ``mcp-probe``.
    """

    protocol: str
    url: str
    importer: str

    def as_dict(self) -> Dict[str, str]:
        """Return the seed as a JSON-ready dict."""
        return {"protocol": self.protocol, "url": self.url, "importer": self.importer}


@dataclass(frozen=True)
class AgentsManifest:
    """A parsed site manifest, whichever dialect it came in.

    Attributes:
        dialect: One of :data:`DIALECTS`.
        title: Display title — the site's name, domain, or llms.txt H1.
        description: The site's summary (AWP ``intent``, llms.txt blockquote), when given.
        site_url: The site's absolute origin URL, when the manifest or its label gives one.
        spec_version: The manifest's own version (``version``, ``awp_version``), when given.
        endpoints: Declared endpoints, in source order.
        actions: AWP actions, in source order (empty for the other dialects).
        payments: Payment layers, in source order.
        authorization: Authorization scheme ids (agents.txt ``Authorization:``, AWP ``auth.type``).
        policies: Policy hints (``payments: required``, ``identity: required``).
        unknown: Directives / keys the parser does not interpret, kept for display.
        raw: The document text verbatim.
        source_label: Filename / URL the document came from, when known.
    """

    dialect: str
    title: str
    description: Optional[str]
    site_url: Optional[str]
    spec_version: Optional[str]
    endpoints: Tuple[ManifestEndpoint, ...]
    actions: Tuple[ManifestAction, ...]
    payments: Tuple[PaymentDeclaration, ...]
    authorization: Tuple[str, ...]
    policies: Dict[str, str]
    unknown: Dict[str, Any]
    raw: str
    source_label: Optional[str] = None


# ===========================================================================
# Detection
# ===========================================================================


def is_awp_document(document: Any) -> bool:
    """Return ``True`` for an Agent Web Protocol ``agent.json`` (an ``awp_version`` string).

    Args:
        document: Any parsed JSON value.

    Returns:
        Whether the value carries AWP's version marker and no other format's root marker.
    """
    return (
        isinstance(document, Mapping)
        and isinstance(document.get("awp_version"), (str, int, float))
        and not _has_foreign_marker(document)
    )


def is_agents_json_document(document: Any) -> bool:
    """Return ``True`` for an agents.txt-companion ``agents.json``.

    The test is at least one endpoint list (``mcp``, ``a2a``, ``skills``, ``ucp``, ``webmcp``,
    ``acp`` — a list of URL strings or ``{url}`` objects) beside a manifest marker: a ``site``
    object, a ``standard`` / ``$schema`` naming agents.txt, or a ``payments`` object. An A2A card
    (``protocolVersion`` …) or another format's root never matches.

    Args:
        document: Any parsed JSON value.

    Returns:
        Whether the value is shaped like an agents.json manifest.
    """
    if not isinstance(document, Mapping) or _has_foreign_marker(document):
        return False
    if any(marker in document for marker in _A2A_CARD_MARKERS) or "awp_version" in document:
        return False
    has_list = any(
        isinstance(document.get(key), list)
        and all(_url_of(item) is not None for item in document[key])
        for key in _AGENTS_JSON_ENDPOINT_KEYS
        if key in document
    )
    if not has_list:
        return False
    marker_text = " ".join(
        str(document.get(key) or "") for key in ("standard", "$schema")
    ).lower()
    return (
        isinstance(document.get("site"), Mapping)
        or "agents-txt" in marker_text
        or "agents.txt" in marker_text
        or isinstance(document.get("payments"), Mapping)
    )


def detect_dialect(content: str, *, filename: Optional[str] = None) -> Optional[str]:
    """Return the dialect ``content`` is written in, or ``None``. Never raises.

    JSON text is an ``awp`` or ``agents-json`` document by shape. Other text is ``agents-txt``
    when it carries an endpoint directive with a value, and ``llms-txt`` when it opens with an H1
    and lists at least one link under an H2 — or opens with an H1 and is *named* ``llms.txt``.

    Args:
        content: Raw document text.
        filename: Optional filename / URL hint.

    Returns:
        The dialect, or ``None`` when the text is none of them.
    """
    if not content or not isinstance(content, str) or not content.strip():
        return None
    if "\x00" in content[:256]:
        return None
    stripped = content.lstrip("﻿").lstrip()
    if stripped[:1] in ("{", "["):
        try:
            document = json.loads(stripped)
        except (json.JSONDecodeError, RecursionError, ValueError):
            return None
        if is_awp_document(document):
            return "awp"
        if is_agents_json_document(document):
            return "agents-json"
        return None
    lines = stripped.splitlines()
    if _txt_endpoint_directives(lines):
        return "agents-txt"
    if _llms_title(lines) is not None:
        name = _basename(filename)
        if name.endswith(("llms.txt", "llms-full.txt")) or _llms_has_link_section(lines):
            return "llms-txt"
    return None


# ===========================================================================
# Parsing
# ===========================================================================


def parse_agents_manifest(content: str, *, source_label: Optional[str] = None) -> AgentsManifest:
    """Parse a site manifest in any of the four dialects.

    Args:
        content: The raw document text.
        source_label: Optional filename / URL; a URL label also supplies the site URL relative
            references resolve against when the manifest names none.

    Returns:
        The parsed manifest.

    Raises:
        AgentsManifestParseError: With a taxonomy ``code`` — ``INPUT_EMPTY``,
            ``INPUT_ENCODING_INVALID``, ``INPUT_TRUNCATED``, ``INPUT_MALFORMED``,
            ``FORMAT_MISMATCH`` for another format, and ``INPUT_SEMANTIC_INVALID`` for a manifest
            that declares nothing (no endpoint, action or payment layer).
    """
    where = f" ({source_label})" if source_label else ""
    if not content or not content.strip():
        raise AgentsManifestParseError(f"Site manifest is empty{where}", code="INPUT_EMPTY")
    if "\x00" in content or "�" in content[:64]:
        raise AgentsManifestParseError(
            f"Site manifest is not UTF-8 text{where} — it looks like UTF-16 or binary content",
            code="INPUT_ENCODING_INVALID",
        )
    try:
        guard_document_text(content, source_label=source_label)
    except IntakeLimitError as exc:
        raise AgentsManifestParseError(str(exc), code=getattr(exc, "code", None)) from exc

    text = content.lstrip("﻿")
    label_origin = _origin_of(source_label)
    if text.lstrip()[:1] in ("{", "["):
        manifest = _parse_json(text, where=where, source_label=source_label, origin=label_origin)
    else:
        lines = text.splitlines()
        if _txt_endpoint_directives(lines) or _txt_any_known_directive(lines):
            manifest = _parse_agents_txt(lines, origin=label_origin)
        elif _llms_title(lines) is not None:
            manifest = _parse_llms_txt(lines, origin=label_origin)
        else:
            raise AgentsManifestParseError(
                f"Content is not an agents.json, agent.json, agents.txt or llms.txt manifest"
                f"{where}",
                code="FORMAT_MISMATCH",
            )
    if not (manifest["endpoints"] or manifest["actions"] or manifest["payments"]):
        raise AgentsManifestParseError(
            f"Site manifest{where} declares no endpoints, actions or payment layers",
            code="INPUT_SEMANTIC_INVALID",
        )
    title = manifest.pop("title") or _title_from_label(source_label, manifest["dialect"])
    return AgentsManifest(title=title, raw=content, source_label=source_label, **manifest)


def discovery_seeds(manifest: AgentsManifest) -> List[DiscoverySeed]:
    """Return the endpoints of ``manifest`` another importer can follow, de-duplicated in order.

    An endpoint seeds discovery when its protocol has an importer (:data:`SEED_IMPORTERS`) and its
    URL resolves to an absolute ``http``/``https`` URL. An AWP ``a2a`` entry seeds its
    ``agent_card`` URL when it names one, else its endpoint.

    Args:
        manifest: The parsed manifest.

    Returns:
        The seeds, in source order.
    """
    seeds: List[DiscoverySeed] = []
    seen: set = set()
    for endpoint in manifest.endpoints:
        importer = SEED_IMPORTERS.get(endpoint.protocol)
        if importer is None:
            continue
        url = endpoint.resolved_url
        card = endpoint.attributes.get("agent_card")
        if endpoint.protocol == "a2a" and isinstance(card, str):
            url = _resolve(card, manifest.site_url) or url
        if url is None or (endpoint.protocol, url) in seen:
            continue
        seen.add((endpoint.protocol, url))
        seeds.append(DiscoverySeed(protocol=endpoint.protocol, url=url, importer=importer))
    return seeds


def classify_link(url: str, title: Optional[str] = None) -> str:
    """Classify an llms.txt link by what it points at.

    Args:
        url: The link target.
        title: The link text (``MCP server`` / ``ACP agents`` are named rather than pathed).

    Returns:
        ``a2a`` for an Agent Card, ``manifest`` for another site manifest, ``openapi`` for an
        OpenAPI document, ``skills`` for a ``SKILL.md``, ``mcp`` / ``acp`` for an endpoint so
        named or pathed, else ``docs``.
    """
    path = urlsplit(url).path.lower().rstrip("/")
    name = (title or "").lower()
    if path.endswith(("agent-card.json", "/.well-known/agent.json")):
        return "a2a"
    if path.endswith(("/agents.json", "/agents.txt", "/llms.txt", "/llms-full.txt")) or path in (
        "agents.json",
        "agents.txt",
        "llms.txt",
    ):
        return "manifest"
    if path.endswith(("openapi.json", "openapi.yaml", "openapi.yml", "swagger.json")):
        return "openapi"
    if path.endswith("skill.md"):
        return "skills"
    if path.endswith(("/mcp", "/sse")) or re.search(r"\bmcp\b", name):
        return "mcp"
    if re.search(r"\bacp\b", name):
        return "acp"
    return "docs"


def dumps_manifest_for_raw(manifest: AgentsManifest) -> Any:
    """Return the manifest as a JSON value for the canonical model's ``raw`` fidelity bag.

    Args:
        manifest: The parsed manifest.

    Returns:
        The decoded JSON for the JSON dialects; the text itself for agents.txt / llms.txt.
    """
    if manifest.dialect in ("agents-json", "awp"):
        return json.loads(manifest.raw.lstrip("﻿"))
    return manifest.raw


# ===========================================================================
# JSON dialects
# ===========================================================================


def _parse_json(
    text: str, *, where: str, source_label: Optional[str], origin: Optional[str]
) -> Dict[str, Any]:
    """Decode and dispatch a JSON manifest (``agents-json`` or ``awp``).

    Args:
        text: The document text (BOM stripped).
        where: Pre-formatted ``" (label)"`` suffix for messages.
        source_label: Label for the intake resource guards.
        origin: The label's origin, the fallback site URL.

    Returns:
        The manifest fields (see :func:`_fields`).

    Raises:
        AgentsManifestParseError: For undecodable JSON or a document of another shape.
    """
    try:
        document: Any = json.loads(text)
    except json.JSONDecodeError as exc:
        if is_unclosed_json(text):
            raise AgentsManifestParseError(
                f"Site manifest is truncated{where}: {exc.msg} at line {exc.lineno}",
                code="INPUT_TRUNCATED",
            ) from exc
        raise AgentsManifestParseError(
            f"Site manifest is not valid JSON{where}: {exc.msg} at line {exc.lineno} "
            f"column {exc.colno}",
            code="INPUT_MALFORMED",
        ) from exc
    try:
        guard_parsed_document(document, source_label=source_label)
    except IntakeLimitError as exc:
        raise AgentsManifestParseError(str(exc), code=getattr(exc, "code", None)) from exc

    if not isinstance(document, Mapping):
        raise AgentsManifestParseError(
            f"Site manifest must be a JSON object{where}, not a {type(document).__name__}",
            code="FORMAT_MISMATCH",
        )
    if is_awp_document(document):
        return _parse_awp(document, origin=origin, where=where)
    if _has_foreign_marker(document) or any(m in document for m in _A2A_CARD_MARKERS):
        raise AgentsManifestParseError(
            f"Content looks like another format (OpenAPI/A2A/ACP/MCP/…){where}, not a site "
            "manifest",
            code="FORMAT_MISMATCH",
        )
    if not (
        any(key in document for key in _AGENTS_JSON_ENDPOINT_KEYS)
        or isinstance(document.get("site"), Mapping)
        or isinstance(document.get("payments"), Mapping)
    ):
        raise AgentsManifestParseError(
            f"Content is not an agents.json or agent.json manifest{where}: it has no `site`, "
            "endpoint list or `awp_version`",
            code="FORMAT_MISMATCH",
        )
    return _parse_agents_json(document, origin=origin)


def _parse_agents_json(document: Mapping[str, Any], *, origin: Optional[str]) -> Dict[str, Any]:
    """Read an agents.txt-companion ``agents.json``.

    Args:
        document: The decoded object.
        origin: Fallback site URL (the label's origin).

    Returns:
        The manifest fields.
    """
    site = document.get("site") if isinstance(document.get("site"), Mapping) else {}
    site_url = _absolute_http(_optional_str(site.get("url"))) or origin
    endpoints: List[ManifestEndpoint] = []
    keys = list(_AGENTS_JSON_ENDPOINT_KEYS) + sorted(
        key for key in document if key.startswith("x-") and isinstance(document[key], list)
    )
    for key in keys:
        items = document.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            endpoints.append(_endpoint_from_item(key, item, site_url))
    payments = _payments_from_mapping(document.get("payments"))
    authorization = _str_list(document.get("authorization"))
    known = set(_AGENTS_JSON_ENDPOINT_KEYS) | {
        "$schema", "version", "standard", "site", "payments", "authorization",
    }
    return _fields(
        dialect="agents-json",
        title=_optional_str(site.get("name")),
        description=_optional_str(site.get("description")),
        site_url=site_url,
        spec_version=_optional_scalar(document.get("version")),
        endpoints=endpoints,
        payments=payments,
        authorization=authorization,
        unknown={k: v for k, v in document.items() if k not in known and not k.startswith("x-")},
    )


def _parse_awp(
    document: Mapping[str, Any], *, origin: Optional[str], where: str
) -> Dict[str, Any]:
    """Read an Agent Web Protocol ``agent.json``.

    Args:
        document: The decoded object.
        origin: Fallback site URL (the label's origin).
        where: Location suffix for messages.

    Returns:
        The manifest fields.

    Raises:
        AgentsManifestParseError: ``INPUT_SEMANTIC_INVALID`` when ``actions`` is present but not
            a list, or an action has no ``id``.
    """
    domain = _optional_str(document.get("domain"))
    site_url = _site_from_domain(domain) or origin
    endpoints: List[ManifestEndpoint] = []
    payments: List[PaymentDeclaration] = []
    protocols = document.get("protocols")
    if isinstance(protocols, Mapping):
        for protocol_id, entry in protocols.items():
            attributes = dict(entry) if isinstance(entry, Mapping) else {}
            pid = str(protocol_id).strip().lower()
            if pid in PAYMENT_PROTOCOLS:
                payments.append(PaymentDeclaration(protocol=pid, attributes=attributes))
                continue
            raw_url = _optional_str(attributes.get("endpoint")) or _optional_str(
                attributes.get("agent_card")
            ) or ""
            endpoints.append(
                ManifestEndpoint(
                    protocol=pid,
                    url=raw_url,
                    resolved_url=_resolve(raw_url, site_url),
                    description=_optional_str(attributes.get("description")),
                    attributes={k: v for k, v in attributes.items() if k != "endpoint"},
                )
            )
    raw_actions = document.get("actions", [])
    if not isinstance(raw_actions, list):
        raise AgentsManifestParseError(
            f"AWP manifest{where} has an `actions` value that is not a list",
            code="INPUT_SEMANTIC_INVALID",
        )
    actions = [
        _parse_action(item, site_url, where=f"{where} action at index {index}")
        for index, item in enumerate(raw_actions)
    ]
    auth = document.get("auth") if isinstance(document.get("auth"), Mapping) else {}
    known = {
        "awp_version", "domain", "intent", "protocols", "actions", "auth",
    }
    return _fields(
        dialect="awp",
        title=domain,
        description=_optional_str(document.get("intent")),
        site_url=site_url,
        spec_version=_optional_scalar(document.get("awp_version")),
        endpoints=endpoints,
        actions=actions,
        payments=payments,
        authorization=_str_list(auth.get("type")),
        unknown={k: v for k, v in document.items() if k not in known},
    )


def _parse_action(item: Any, site_url: Optional[str], *, where: str) -> ManifestAction:
    """Parse one AWP action.

    Args:
        item: The raw action.
        site_url: The site URL relative endpoints resolve against.
        where: Location suffix for messages.

    Returns:
        The parsed action.

    Raises:
        AgentsManifestParseError: ``INPUT_SEMANTIC_INVALID`` for a non-object or an action
            without an ``id``.
    """
    if not isinstance(item, Mapping):
        raise AgentsManifestParseError(
            f"AWP action{where} is not an object", code="INPUT_SEMANTIC_INVALID"
        )
    action_id = _optional_str(item.get("id"))
    if action_id is None:
        raise AgentsManifestParseError(
            f"AWP action{where} has no `id`", code="INPUT_SEMANTIC_INVALID"
        )
    endpoint = _optional_str(item.get("endpoint"))
    method = _optional_str(item.get("method"))
    auth_required = item.get("auth_required")
    return ManifestAction(
        id=action_id,
        description=_optional_str(item.get("description")),
        method=method.upper() if method else None,
        endpoint=endpoint,
        resolved_endpoint=_resolve(endpoint, site_url) if endpoint else None,
        via=(_optional_str(item.get("via")) or "").lower() or None,
        operation=_optional_str(item.get("operation")),
        auth_required=auth_required if isinstance(auth_required, bool) else None,
        inputs=dict(item["inputs"]) if isinstance(item.get("inputs"), Mapping) else {},
    )


# ===========================================================================
# Text dialects
# ===========================================================================


def _parse_agents_txt(lines: Sequence[str], *, origin: Optional[str]) -> Dict[str, Any]:
    """Read ``agents.txt`` directive lines.

    Endpoint directives repeat; ``Protocols:`` (payment ids) and ``Authorization:`` (auth ids)
    are comma lists; ``Payments:`` / ``Identity:`` are policy hints; an ``X-…`` directive whose
    value is a URL is an experimental endpoint. Anything else is kept under ``unknown``.

    Args:
        lines: The document's lines.
        origin: The label's origin — relative references resolve against it.

    Returns:
        The manifest fields.
    """
    endpoints: List[ManifestEndpoint] = []
    payments: List[PaymentDeclaration] = []
    authorization: List[str] = []
    policies: Dict[str, str] = {}
    unknown: Dict[str, Any] = {}
    spec_version: Optional[str] = None
    title: Optional[str] = None
    for number, line in enumerate(lines, start=1):
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        match = _DIRECTIVE_LINE.match(text)
        if match is None:
            unknown.setdefault("unparsed_lines", []).append(number)
            continue
        name, value = match.group(1).lower(), match.group(2).strip()
        if name in _TXT_ENDPOINT_DIRECTIVES:
            endpoints.append(
                ManifestEndpoint(
                    protocol=_TXT_ENDPOINT_DIRECTIVES[name],
                    url=value,
                    resolved_url=_resolve(value, origin),
                )
            )
        elif name == "protocols":
            payments.extend(PaymentDeclaration(protocol=p.lower()) for p in _comma_list(value))
        elif name == "authorization":
            authorization.extend(_comma_list(value))
        elif name in _TXT_POLICY_DIRECTIVES:
            policies[name] = value
        elif name == "version":
            spec_version = value or None
        elif name in ("site-name", "site"):
            title = value or None
        elif name.startswith("x-") and _absolute_http(value):
            endpoints.append(
                ManifestEndpoint(
                    protocol=name,
                    url=value,
                    resolved_url=_resolve(value, origin),
                )
            )
        else:
            unknown.setdefault(match.group(1), []).append(value)
    return _fields(
        dialect="agents-txt",
        title=title,
        site_url=origin,
        spec_version=spec_version,
        endpoints=endpoints,
        payments=payments,
        authorization=authorization,
        policies=policies,
        unknown=unknown,
    )


def _parse_llms_txt(lines: Sequence[str], *, origin: Optional[str]) -> Dict[str, Any]:
    """Read an ``llms.txt``: H1 title, ``>`` summary, H2 sections of link items.

    Args:
        lines: The document's lines.
        origin: The label's origin — relative links resolve against it.

    Returns:
        The manifest fields; every link is an endpoint classified by :func:`classify_link`,
        tagged with its ``section`` (and ``optional`` under ``## Optional``).
    """
    title = _llms_title(lines)
    summary: List[str] = []
    endpoints: List[ManifestEndpoint] = []
    section: Optional[str] = None
    for line in lines:
        text = line.strip()
        if text.startswith("## "):
            section = text[3:].strip()
            continue
        if section is None and text.startswith(">"):
            summary.append(text.lstrip(">").strip())
            continue
        match = _LINK_ITEM.match(line)
        if match is None:
            continue
        name, url, notes = match.group(1).strip(), match.group(2).strip(), match.group(3)
        attributes: Dict[str, Any] = {}
        if section:
            attributes["section"] = section
            if section.lower() == "optional":
                attributes["optional"] = True
        endpoints.append(
            ManifestEndpoint(
                protocol=classify_link(url, name),
                url=url,
                resolved_url=_resolve(url, origin),
                title=name or None,
                description=_optional_str(notes),
                attributes=attributes,
            )
        )
    return _fields(
        dialect="llms-txt",
        title=title,
        description=" ".join(part for part in summary if part) or None,
        site_url=origin,
        endpoints=endpoints,
    )


def _txt_endpoint_directives(lines: Sequence[str]) -> int:
    """Count agents.txt endpoint directive lines that carry a value."""
    count = 0
    for line in lines:
        match = _DIRECTIVE_LINE.match(line.strip())
        if match and match.group(1).lower() in _TXT_ENDPOINT_DIRECTIVES and match.group(2).strip():
            count += 1
    return count


def _txt_any_known_directive(lines: Sequence[str]) -> bool:
    """Whether any line is an agents.txt directive (endpoint, payments or authorization)."""
    names = set(_TXT_ENDPOINT_DIRECTIVES) | {"protocols", "authorization"}
    for line in lines:
        match = _DIRECTIVE_LINE.match(line.strip())
        if match and match.group(1).lower() in names:
            return True
    return False


def _llms_title(lines: Sequence[str]) -> Optional[str]:
    """The H1 an llms.txt opens with (first non-blank line ``# Title``), else ``None``."""
    for line in lines:
        text = line.strip()
        if not text:
            continue
        if text.startswith("# ") and not text.startswith("## "):
            return text[2:].strip() or None
        return None
    return None


def _llms_has_link_section(lines: Sequence[str]) -> bool:
    """Whether an H2 section is followed by at least one ``- [name](url)`` link item."""
    in_section = False
    for line in lines:
        if line.strip().startswith("## "):
            in_section = True
        elif in_section and _LINK_ITEM.match(line):
            return True
    return False


# ===========================================================================
# Helpers
# ===========================================================================


def _fields(
    *,
    dialect: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    site_url: Optional[str] = None,
    spec_version: Optional[str] = None,
    endpoints: Sequence[ManifestEndpoint] = (),
    actions: Sequence[ManifestAction] = (),
    payments: Sequence[PaymentDeclaration] = (),
    authorization: Sequence[str] = (),
    policies: Optional[Mapping[str, str]] = None,
    unknown: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Collect one dialect reader's output into :class:`AgentsManifest` keyword arguments."""
    return {
        "dialect": dialect,
        "title": title,
        "description": description,
        "site_url": site_url,
        "spec_version": spec_version,
        "endpoints": tuple(endpoints),
        "actions": tuple(actions),
        "payments": tuple(payments),
        "authorization": tuple(dict.fromkeys(authorization)),
        "policies": dict(policies or {}),
        "unknown": dict(unknown or {}),
    }


def _endpoint_from_item(protocol: str, item: Any, site_url: Optional[str]) -> ManifestEndpoint:
    """An agents.json list entry — a URL string or ``{url, description, …}`` — as an endpoint."""
    attributes = dict(item) if isinstance(item, Mapping) else {}
    url = _url_of(item) or ""
    return ManifestEndpoint(
        protocol=protocol,
        url=url,
        resolved_url=_resolve(url, site_url),
        title=_optional_str(attributes.get("name")),
        description=_optional_str(attributes.get("description")),
        attributes={k: v for k, v in attributes.items() if k not in ("url", "name", "description")},
    )


def _payments_from_mapping(value: Any) -> List[PaymentDeclaration]:
    """agents.json ``payments`` — ``{protocol: {details}}`` — as payment declarations."""
    if not isinstance(value, Mapping):
        return []
    return [
        PaymentDeclaration(
            protocol=str(key).strip().lower(),
            attributes=dict(details) if isinstance(details, Mapping) else {},
        )
        for key, details in value.items()
    ]


def _url_of(item: Any) -> Optional[str]:
    """The URL of an endpoint list entry (a string, or an object's ``url``), else ``None``."""
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, Mapping) and isinstance(item.get("url"), str):
        return item["url"].strip()
    return None


def _resolve(url: Optional[str], base: Optional[str]) -> Optional[str]:
    """Resolve ``url`` to an absolute http(s) URL against ``base``, or ``None`` if it cannot be."""
    if not url:
        return None
    absolute = _absolute_http(url)
    if absolute:
        return absolute
    if base and not urlsplit(url).scheme:
        return _absolute_http(urljoin(base.rstrip("/") + "/", url))
    return None


def _absolute_http(url: Optional[str]) -> Optional[str]:
    """``url`` when it is an absolute http(s) URL with a host (and no whitespace), else ``None``."""
    if not url or any(ch.isspace() for ch in url):
        return None
    parts = urlsplit(url)
    if parts.scheme.lower() in ("http", "https") and parts.hostname:
        return url
    return None


def _origin_of(label: Optional[str]) -> Optional[str]:
    """``scheme://host`` of a URL label, else ``None`` (a filename carries no site)."""
    if not label:
        return None
    parts = urlsplit(label)
    if parts.scheme.lower() in ("http", "https") and parts.netloc:
        return f"{parts.scheme.lower()}://{parts.netloc}"
    return None


def _site_from_domain(domain: Optional[str]) -> Optional[str]:
    """An AWP ``domain`` (``example.com`` or a full URL) as an ``https://`` origin."""
    if not domain:
        return None
    if "://" in domain:
        return _origin_of(domain)
    host = domain.strip().strip("/")
    return f"https://{host}" if host and " " not in host else None


def _has_foreign_marker(document: Mapping[str, Any]) -> bool:
    """Whether the object carries another format's root marker."""
    return any(marker in document for marker in _FOREIGN_FORMAT_MARKERS)


def _title_from_label(source_label: Optional[str], dialect: str) -> str:
    """A title for a manifest that names no site: the label's host, else the dialect's file name."""
    origin = _origin_of(source_label)
    if origin:
        return urlsplit(origin).netloc
    return {
        "agents-json": "agents.json",
        "awp": "agent.json",
        "agents-txt": "agents.txt",
        "llms-txt": "llms.txt",
    }[dialect]


def _basename(name: Optional[str]) -> str:
    """The lower-cased last path segment of a filename or URL."""
    return (name or "").rstrip("/").rsplit("/", 1)[-1].lower()


def _comma_list(value: str) -> List[str]:
    """Split ``a, b, c`` into its non-empty items."""
    return [item.strip() for item in value.split(",") if item.strip()]


def _str_list(value: Any) -> List[str]:
    """A string or list of strings as a list of non-empty strings."""
    if isinstance(value, str):
        return _comma_list(value)
    if isinstance(value, list):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return []


def _optional_str(value: Any) -> Optional[str]:
    """Return a stripped non-empty string, else ``None``."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _optional_scalar(value: Any) -> Optional[str]:
    """A version-ish scalar (``"1.0"``, ``0.2``) as a string, else ``None``."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return str(value)
    return _optional_str(value)
