"""Annotation-consistency & security-posture rules for the MCP lint engine (V2-MCP-21.3).

This is the second concrete *rule pack* (after :mod:`app.mcp_lint_hygiene`) that plugs
into the deterministic engine in :mod:`app.mcp_lint`. Where the hygiene pack asks "is each
item structurally well-formed and well-described?", this pack asks the two highest-signal
MCP-specific questions: **are a tool's behavioural annotations internally consistent**, and
**does the surface leak a security-posture gap** an agent host should know about before it
trusts the server? Every rule registers its ``(category, severity)`` via
:func:`~app.mcp_lint.register_rule_metadata` and appends findings through the shared
:func:`~app.mcp_lint.lint_rule` registry, so the engine's ordering, hashing, and
determinism guarantees apply unchanged — and, like the engine, every rule here is *pure*
(no DNS resolution, no network, no I/O), so it stays cheap to run at version-creation time.

Three rule groups (``category``) carry this pack, two of them new:

* ``annotation`` *(new)* — contradictions **within** a tool's ``annotations`` hint set. A
  host uses these hints to decide whether a tool is safe to auto-approve, so a self-
  contradictory set (``readOnlyHint:true`` alongside ``destructiveHint:true`` or
  ``idempotentHint:false``) is actively misleading and is flagged ``warning``.
* ``security`` *(new)* — posture gaps an operator should review before trusting the
  server: a tool that accepts a raw credential as an argument (the *token-passthrough*
  anti-pattern), an advertised OAuth scope that is over-broad, and a resource/template URI
  that points at internal infrastructure (an *SSRF*-risky target). All ``warning`` —
  signals to review, not hard protocol failures.
* ``quality`` *(reused from the hygiene pack)* — a server that advertises no free-text
  ``instructions`` gives an agent no guidance on how to drive it; advisory only (``info``).

Severity reflects normative force, so downstream scoring (V2-MCP-21.4) weights a real
posture gap above an advisory nit: nothing here is an ``error`` (these are SHOULD-level
safety/consistency signals, not malformed-on-the-wire MUST violations), the contradictions
and posture gaps are ``warning``, and the missing-instructions hint is ``info``.

References (2025-06-18):
  * security best practices — https://modelcontextprotocol.io/specification/2025-06-18/basic/security_best_practices
  * tool annotations       — https://modelcontextprotocol.io/specification/2025-06-18/server/tools
  * writing tools for agents — https://www.anthropic.com/engineering/writing-tools-for-agents

The module is imported (and therefore self-registers) by :mod:`app.mcp_lint` at load time,
after the hygiene pack, so any caller of :func:`app.mcp_lint.lint_mcp_surface` gets these
rules with no extra wiring.
"""

from __future__ import annotations

import ipaddress
from typing import Any, Iterator, List, Mapping, Optional
from urllib.parse import urlsplit

from .mcp_client.normalize import CapabilityItem, DiscoverySurface
from .mcp_lint import (
    LintFinding,
    item_path,
    lint_rule,
    make_finding,
    register_rule_metadata,
)
from .mcp_lint_hygiene import _is_blank
from .ssrf_guard import _ip_is_disallowed

# --- Rule metadata registration -------------------------------------------------------------
# Declared once, centrally, so the engine and every consumer agree on each rule's group and
# weight. ``annotation``/``security`` rules are SHOULD-level safety signals (warning);
# the reused ``quality`` rule is advisory (info).

#: Rule id -> (category, severity) for every rule defined in this pack.
ANNOTATION_RULES = {
    # annotation: a tool's own hint set contradicts itself.
    "annotation.read-only-contradicts-destructive": ("annotation", "warning"),
    "annotation.read-only-contradicts-non-idempotent": ("annotation", "warning"),
    # security: posture gaps to review before trusting the server.
    "security.tool-token-passthrough-parameter": ("security", "warning"),
    "security.over-broad-auth-scope": ("security", "warning"),
    "security.ssrf-risky-resource-uri": ("security", "warning"),
    # quality: advisory service-usability signal (group reused from the hygiene pack).
    "quality.server-missing-instructions": ("quality", "info"),
}

for _rule, (_category, _severity) in ANNOTATION_RULES.items():
    register_rule_metadata(_rule, _category, _severity)


# --- Annotation-consistency helpers ---------------------------------------------------------


def _bool_hint(annotations: Optional[Mapping[str, Any]], key: str) -> Optional[bool]:
    """Return a tool annotation hint as a strict ``bool``, or ``None`` if not a clean bool.

    MCP behavioural hints (``readOnlyHint``, ``destructiveHint``, ``idempotentHint``,
    ``openWorldHint``) are JSON booleans. A missing key, a non-mapping ``annotations``, or
    a non-boolean value (e.g. the string ``"true"``) is treated as *unset* (``None``) so the
    consistency rules never read a contradiction into a value the server did not actually
    assert as a boolean.

    Args:
        annotations: The tool's normalized ``annotations`` object (may be ``None``).
        key: The hint name to read.

    Returns:
        ``True``/``False`` only when the hint is present and is a JSON boolean; else ``None``.
    """
    if not isinstance(annotations, Mapping):
        return None
    value = annotations.get(key)
    return value if isinstance(value, bool) else None


# --- Token-passthrough helpers --------------------------------------------------------------
# A tool argument literally named for a credential is the lintable face of the "token
# passthrough" anti-pattern the security best practices warn against: the host should own
# authentication, never relay a raw token/secret through a tool's parameters. We match on the
# *normalized* parameter name (lowercased, separators removed) against a curated set of exact
# credential names, so "access_token"/"api-key" match while "tokenizer"/"passwordPolicyUrl"
# (which merely contain a credential word) do not — keeping false positives low.

#: Credential-style parameter names (in normalized form) that indicate token passthrough.
_CREDENTIAL_PARAM_NAMES = frozenset(
    {
        "token",
        "accesstoken",
        "refreshtoken",
        "idtoken",
        "sessiontoken",
        "bearer",
        "bearertoken",
        "authtoken",
        "authorization",
        "apikey",
        "apitoken",
        "secret",
        "clientsecret",
        "password",
        "passwd",
        "credential",
        "credentials",
        "privatekey",
    }
)


def _normalize_param_name(name: str) -> str:
    """Lowercase ``name`` and strip ``_``/``-``/whitespace, for credential-name matching.

    Collapses the common spellings of a credential parameter (``access_token``,
    ``access-token``, ``accessToken``) to a single comparable token so they all match the
    same entry in :data:`_CREDENTIAL_PARAM_NAMES`.
    """
    return "".join(ch for ch in name.lower() if ch.isalnum())


def _credential_parameters(tool: CapabilityItem) -> List[str]:
    """Return the names of ``tool``'s top-level input parameters that look like credentials.

    Inspects the ``properties`` map of the tool's ``inputSchema`` (the named-argument map a
    caller fills in). A property whose normalized name is in :data:`_CREDENTIAL_PARAM_NAMES`
    is reported under its *original* wire name (so the finding points at the real field).
    Only top-level properties are scanned — that is where a passthrough credential would be
    accepted; nested object schemas are out of scope to keep the signal high. Returns names
    in their declared order, de-duplicated.

    Args:
        tool: A normalized ``tool`` capability item.

    Returns:
        The offending parameter names, possibly empty.
    """
    schema = tool.input_schema
    if not isinstance(schema, Mapping):
        return []
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        return []
    flagged: List[str] = []
    for param_name in properties:
        if not isinstance(param_name, str):
            continue
        if _normalize_param_name(param_name) in _CREDENTIAL_PARAM_NAMES and param_name not in flagged:
            flagged.append(param_name)
    return flagged


# --- Over-broad-scope helpers ---------------------------------------------------------------
# MCP carries OAuth metadata largely out of band, but servers sometimes surface scope hints
# inside the declared ``capabilities`` object (e.g. a vendor/experimental auth block). Where
# they do, an over-broad scope ("*", "admin", "read:*") is a posture signal: it implies the
# server requests far more authority than a least-privilege integration should. We walk the
# capabilities tree for any ``scope``/``scopes`` value and test each against a small set of
# over-broad shapes.

#: Keys whose (string or list-of-string) values are treated as OAuth scope declarations.
_SCOPE_KEYS = frozenset({"scope", "scopes"})

#: Exact normalized scope tokens that always denote over-broad authority.
_OVERBROAD_SCOPE_TOKENS = frozenset(
    {"*", "all", "admin", "root", "superuser", "fullaccess", "fullcontrol", "writeall", "readall"}
)


def _is_overbroad_scope(scope: str) -> bool:
    """Return ``True`` when an OAuth ``scope`` string grants over-broad authority.

    Two shapes are flagged: a wildcard scope (any scope containing ``*`` — e.g. ``"*"``,
    ``"read:*"``, ``"repo:*"``), and an admin-level scope whose normalized form (lowercased,
    separators stripped) is a known all-authority token in :data:`_OVERBROAD_SCOPE_TOKENS`
    (e.g. ``"admin"``, ``"full_access"``, ``"superuser"``). A blank value is not a scope and
    is ignored.

    Args:
        scope: A single advertised scope string.

    Returns:
        ``True`` if the scope is wildcard or admin-level, else ``False``.
    """
    if _is_blank(scope):
        return False
    if "*" in scope:
        return True
    return _normalize_param_name(scope) in _OVERBROAD_SCOPE_TOKENS


def _iter_scope_values(value: Any) -> Iterator[str]:
    """Yield every advertised scope string found under a ``scope``/``scopes`` key in ``value``.

    Walks an arbitrary JSON value (the ``capabilities`` object) recursively. Whenever a
    mapping key is in :data:`_SCOPE_KEYS`, its value contributes scopes: a bare string is one
    scope; a list contributes each of its string elements. The walk also descends into every
    other mapping value and list element, so a scope block nested under a vendor capability is
    still found. Non-string scope entries are skipped. Order follows the natural traversal
    order, which is deterministic for a given object.
    """
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key in _SCOPE_KEYS:
                if isinstance(child, str):
                    yield child
                elif isinstance(child, (list, tuple)):
                    for element in child:
                        if isinstance(element, str):
                            yield element
            yield from _iter_scope_values(child)
    elif isinstance(value, (list, tuple)):
        for element in value:
            yield from _iter_scope_values(element)


# --- SSRF helpers ---------------------------------------------------------------------------
# A resource/template URI naming an internal host turns a server-side fetch of that resource
# into an SSRF primitive. We judge the *host literal as written* — purely, with no DNS
# resolution (the engine must stay I/O-free and deterministic) — by reusing
# :func:`app.ssrf_guard._ip_is_disallowed` for IP literals and matching internal hostnames
# textually. This is intentionally a static-analysis signal, not the runtime guard in
# :mod:`app.ssrf_guard`: it flags a *suspicious advertised target*, it does not gate a fetch.

#: Hostnames (exact, case-folded) that always denote an internal/metadata target.
_INTERNAL_HOST_NAMES = frozenset(
    {"localhost", "metadata", "metadata.google.internal", "metadata.goog"}
)

#: Hostname suffixes that denote private/internal DNS namespaces.
_INTERNAL_HOST_SUFFIXES = (".local", ".internal", ".localhost", ".lan", ".home.arpa", ".intranet")


def _host_ssrf_reason(host: str) -> Optional[str]:
    """Return why ``host`` is an SSRF-risky target, or ``None`` when it looks external.

    The host is judged as a literal — no name resolution — in two ways. If it parses as an
    IP address, it is rejected when :func:`app.ssrf_guard._ip_is_disallowed` deems it
    non-public (loopback, RFC1918 private, link-local incl. the ``169.254.169.254`` cloud
    metadata IP, multicast, reserved, or unspecified), so the two SSRF judgments in the
    codebase stay consistent. Otherwise it is matched as a hostname against the internal
    names/suffixes in :data:`_INTERNAL_HOST_NAMES` / :data:`_INTERNAL_HOST_SUFFIXES`.

    Args:
        host: The URI host literal (already lowercased by ``urlsplit``).

    Returns:
        A human-readable reason string, or ``None`` when the host appears public.
    """
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None:
        if _ip_is_disallowed(address):
            return f"host '{host}' is a non-public address"
        return None
    if host in _INTERNAL_HOST_NAMES:
        return f"host '{host}' is an internal/metadata hostname"
    if any(host.endswith(suffix) for suffix in _INTERNAL_HOST_SUFFIXES):
        return f"host '{host}' is in an internal DNS namespace"
    return None


def _uri_ssrf_reason(uri: Optional[str]) -> Optional[str]:
    """Return why a resource ``uri`` (or template) names an SSRF-risky host, else ``None``.

    The host is extracted with :func:`urllib.parse.urlsplit` and judged by
    :func:`_host_ssrf_reason`. A URI with no host (``None``/blank, a hostless ``file:`` URI,
    or a host that is still a template expression containing ``{``/``}``) yields ``None`` —
    there is no literal host to assess, and a missing/invalid host is already covered by the
    hygiene pack's URI rules.

    Args:
        uri: The resource ``uri`` or resource-template ``uriTemplate`` (may be ``None``).

    Returns:
        A reason string when the host is internal/metadata, else ``None``.
    """
    if _is_blank(uri):
        return None
    try:
        host = urlsplit(uri).hostname
    except ValueError:
        return None
    if not host or "{" in host or "}" in host:
        return None
    return _host_ssrf_reason(host)


# --- Rules ----------------------------------------------------------------------------------


@lint_rule
def _rule_read_only_contradictions(
    surface: DiscoverySurface, findings: List[LintFinding]
) -> None:
    """Flag tools whose ``readOnlyHint`` contradicts ``destructiveHint``/``idempotentHint``.

    Per the tool-annotations spec, ``destructiveHint`` and ``idempotentHint`` only describe a
    *writing* tool; a tool that asserts ``readOnlyHint:true`` performs no modification, so it
    cannot also be destructive, and it is inherently idempotent. A host reads these hints to
    decide auto-approval, so a contradictory set is misleading (``warning``). Each
    contradiction is reported independently — a tool can trip both.
    """
    for tool in surface.tools:
        if _bool_hint(tool.annotations, "readOnlyHint") is not True:
            continue
        if _bool_hint(tool.annotations, "destructiveHint") is True:
            findings.append(
                make_finding(
                    item_path(tool),
                    "annotation.read-only-contradicts-destructive",
                    f"Tool '{tool.name or tool.ordinal}' declares readOnlyHint:true with "
                    f"destructiveHint:true; a read-only tool cannot be destructive.",
                )
            )
        if _bool_hint(tool.annotations, "idempotentHint") is False:
            findings.append(
                make_finding(
                    item_path(tool),
                    "annotation.read-only-contradicts-non-idempotent",
                    f"Tool '{tool.name or tool.ordinal}' declares readOnlyHint:true with "
                    f"idempotentHint:false; a read-only tool is inherently idempotent.",
                )
            )


@lint_rule
def _rule_tool_token_passthrough(
    surface: DiscoverySurface, findings: List[LintFinding]
) -> None:
    """Flag tools that accept a raw credential/token as an input parameter.

    A tool argument named for a credential (``token``, ``api_key``, ``password``, …) is the
    detectable signature of the token-passthrough anti-pattern: the host, not a tool
    parameter, should own authentication, and a tool that asks the model to supply a secret
    risks leaking it into prompts/logs. One finding per offending parameter, anchored at
    ``<tool path>.inputSchema.<param>`` so each is independently addressable (``warning``).
    """
    for tool in surface.tools:
        for param_name in _credential_parameters(tool):
            findings.append(
                make_finding(
                    f"{item_path(tool)}.inputSchema.{param_name}",
                    "security.tool-token-passthrough-parameter",
                    f"Tool '{tool.name or tool.ordinal}' accepts a credential-style parameter "
                    f"'{param_name}'; the host should manage auth rather than pass tokens through.",
                )
            )


@lint_rule
def _rule_over_broad_auth_scope(
    surface: DiscoverySurface, findings: List[LintFinding]
) -> None:
    """Flag over-broad OAuth scopes advertised anywhere in the server's ``capabilities``.

    Walks the declared ``capabilities`` object for ``scope``/``scopes`` values and flags each
    wildcard (``*``, ``read:*``) or admin-level (``admin``, ``full_access``) scope: requesting
    blanket authority violates least privilege and is a posture gap an operator should review
    (``warning``). Reported once per distinct offending scope string, in traversal order.
    """
    seen: set = set()
    for scope in _iter_scope_values(surface.capabilities):
        if scope in seen or not _is_overbroad_scope(scope):
            continue
        seen.add(scope)
        findings.append(
            make_finding(
                "surface.capabilities",
                "security.over-broad-auth-scope",
                f"Server advertises over-broad OAuth scope '{scope}'; prefer least-privilege scopes.",
            )
        )


@lint_rule
def _rule_ssrf_risky_resource_uri(
    surface: DiscoverySurface, findings: List[LintFinding]
) -> None:
    """Flag resource/template URIs whose host is an internal or cloud-metadata target.

    A resource a server offers for read is a fetch target; a URI naming ``localhost``, an
    RFC1918/loopback/link-local IP, the cloud metadata endpoint, or an internal DNS namespace
    turns that fetch into an SSRF primitive. Both concrete resource ``uri`` values and
    resource-template ``uriTemplate`` values (when their host is a literal, not a ``{}``
    expression) are checked, statically and without DNS resolution (``warning``).
    """
    for resource in surface.resources:
        reason = _uri_ssrf_reason(resource.uri)
        if reason is not None:
            findings.append(
                make_finding(
                    item_path(resource),
                    "security.ssrf-risky-resource-uri",
                    f"Resource '{resource.name or resource.ordinal}': {reason}; "
                    f"fetching it could enable SSRF.",
                )
            )
    for template in surface.resource_templates:
        reason = _uri_ssrf_reason(template.uri_template)
        if reason is not None:
            findings.append(
                make_finding(
                    item_path(template),
                    "security.ssrf-risky-resource-uri",
                    f"Resource template '{template.name or template.ordinal}': {reason}; "
                    f"fetching it could enable SSRF.",
                )
            )


@lint_rule
def _rule_server_missing_instructions(
    surface: DiscoverySurface, findings: List[LintFinding]
) -> None:
    """Flag a server that advertises no free-text ``instructions``.

    The handshake ``instructions`` field is how a server tells an agent how to drive it
    (ordering constraints, conventions, gotchas). It is optional, so its absence is purely
    advisory (``info``) — but a server that ships none gives the model no usage guidance.
    A single surface-level finding anchored at ``surface``.
    """
    if _is_blank(surface.instructions):
        findings.append(
            make_finding(
                "surface",
                "quality.server-missing-instructions",
                "Server advertises no instructions; agents get no usage guidance for the surface.",
            )
        )
