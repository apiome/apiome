"""Protocol-conformance rule pack for the MCP conformance engine (CLX-3.1, #4855).

The first of the two packs that plug into :mod:`app.mcp_conformance`. It asks: **did the
server behave like an MCP server?** — as distinct from the surface linter's "is what it
advertised well-formed?".

The pack has two halves, and the split is the determinism contract the engine enforces:

* **Surface-derived rules** (the majority) read only the persisted
  :class:`~app.mcp_client.normalize.DiscoverySurface`: the negotiated protocol version, the
  server identity, and — the highest-signal check here — whether the capabilities the server
  *declared* in its handshake match the capabilities it actually *listed*. These are
  deterministic and recomputable offline from the database at any time.
* **Transcript-derived rules** (``requires_transcript=True``) read the redacted
  :class:`~app.mcp_protocol_transcript.ProtocolTranscript` and judge behaviour only visible on
  the wire: JSON-RPC envelope validity, error-code discipline, and whether pagination actually
  terminated. When no transcript was captured the engine skips them and reports them as
  skipped — an unobserved behaviour never reads as a pass.

Severity encodes normative force, so the score weights a real interoperability break above a
stylistic one:

* ``error``   — a normative **MUST** is violated and interoperability is genuinely at risk (a
  malformed JSON-RPC envelope, an unusable protocol version, a capability listed but never
  declared, pagination that cannot be proven to terminate).
* ``warning`` — a **SHOULD**, or behaviour that works but will surprise a client (a
  non-standard error code inside the reserved range, a list endpoint answering with an error).
* ``info``    — advisory (a declared-but-empty capability, a protocol-version downgrade).

What is deliberately *not* a rule here
--------------------------------------

Several textbook protocol violations are conspicuously absent, and their absence is
intentional. **The MCP client is already a strict protocol enforcer**, and every one of these
defects makes it abort discovery *before* a surface exists:

* a malformed envelope or a bad ``jsonrpc`` version —
  :meth:`app.mcp_client.transport_http.StreamableHttpTransport._parse_json_rpc` raises
  ``McpProtocolError``;
* a non-terminating cursor or a page-limit overrun —
  :func:`app.mcp_client.discovery.paginate` raises ``McpPaginationError``;
* a list method answering with a JSON-RPC error — ``paginate`` raises ``McpDiscoveryError``.

A snapshot exhibiting any of them is therefore never persisted, so a rule for it could never
fire on a lintable version: it would sit in the catalog reporting "pass" forever, which is
exactly the false assurance this work exists to prevent — an unobserved behaviour must never
read as clean. Relaxing the client so these defects *could* be linted would be a bad trade: it
would admit malformed servers in order to describe them. They are defended by the client's
guards, and a run that trips one surfaces as a **failed discovery job**, not as a clean report.

What remains lintable is therefore narrower, and is precisely what the client tolerates but an
agent still suffers from: capability negotiation that does not match what was actually served,
a silent protocol downgrade, wasteful or malformed pagination, a response id that was never
echoed, and an error code squatting on reserved space. Should the hard-failure cases ever need
to be findings, the home for them is a transcript from a *failed* discovery (CLX-3.3's dynamic
probes), which needs a report subject that does not depend on a persisted surface.

References (MCP 2025-06-18):
  * lifecycle / initialize — https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle
  * transports & envelopes — https://modelcontextprotocol.io/specification/2025-06-18/basic/transports
  * pagination             — https://modelcontextprotocol.io/specification/2025-06-18/server/utilities/pagination

The module self-registers on import from :mod:`app.mcp_conformance`.
"""

from __future__ import annotations

from typing import Any, List, Mapping, Optional, Tuple

from .mcp_client.handshake import SUPPORTED_PROTOCOL_VERSIONS
from .mcp_conformance import (
    CATEGORY_PROTOCOL,
    MCP_SPEC_VERSION,
    SPEC_LIFECYCLE,
    SPEC_PAGINATION,
    SPEC_TRANSPORTS,
    ConformanceContext,
    ConformanceFinding,
    ConformanceRule,
    conformance_rule,
    make_finding,
    register_rules,
)
from .mcp_protocol_transcript import LIST_METHODS, METHOD_INITIALIZE

# --- Protocol constants -----------------------------------------------------------------------

#: Capability keys a server may declare in its ``initialize`` result. Anything outside this set
#: is not part of the specification's capability vocabulary (``experimental`` is the spec's own
#: escape hatch for vendor extensions, so it is accepted).
KNOWN_CAPABILITIES: frozenset = frozenset(
    {"tools", "resources", "prompts", "logging", "completions", "experimental"}
)

#: Maps a capability key to the surface attribute holding the items it gates, plus the label
#: used in messages. Resource *templates* are gated by the single ``resources`` capability, so
#: both resource collections appear under it.
CAPABILITY_COLLECTIONS: Tuple[Tuple[str, Tuple[str, ...], str], ...] = (
    ("tools", ("tools",), "tools"),
    ("resources", ("resources", "resource_templates"), "resources"),
    ("prompts", ("prompts",), "prompts"),
)

#: The JSON-RPC 2.0 pre-defined error codes. A code inside the reserved band that is not one of
#: these — and is not in the implementation-defined server-error band — is non-standard.
JSONRPC_PREDEFINED_CODES: frozenset = frozenset({-32700, -32600, -32601, -32602, -32603})

#: The reserved error-code band (JSON-RPC 2.0 §5.1). Codes outside it are application-defined
#: and entirely legitimate, so they are never flagged.
JSONRPC_RESERVED_MIN = -32768
JSONRPC_RESERVED_MAX = -32000

#: Within the reserved band, this sub-range is explicitly set aside for implementation-defined
#: server errors and is therefore legitimate.
JSONRPC_SERVER_ERROR_MIN = -32099
JSONRPC_SERVER_ERROR_MAX = -32000


# --- Rule descriptors -------------------------------------------------------------------------
# Declared once, centrally. Every rule cites the specification revision it derives from and a
# resolvable reference, so a finding always traces back to a normative statement (CLX-3.1 AC-1).


def _rule(
    rule_id: str,
    severity: str,
    reference: str,
    rationale: str,
    *,
    requires_transcript: bool = False,
) -> ConformanceRule:
    """Build one protocol-category descriptor against the current spec revision."""
    return ConformanceRule(
        rule_id=rule_id,
        category=CATEGORY_PROTOCOL,
        severity=severity,
        spec_version=MCP_SPEC_VERSION,
        spec_reference=reference,
        rationale=rationale,
        requires_transcript=requires_transcript,
    )


PROTOCOL_RULES: Tuple[ConformanceRule, ...] = (
    # -- Initialize & capability negotiation (surface-derived, deterministic) ------------------
    _rule(
        "protocol.missing-protocol-version",
        "error",
        SPEC_LIFECYCLE,
        "The initialize result MUST carry a protocolVersion; without one no version is agreed.",
    ),
    _rule(
        "protocol.unsupported-protocol-version",
        "error",
        SPEC_LIFECYCLE,
        "The negotiated protocol version MUST be a revision this client speaks.",
    ),
    _rule(
        "protocol.missing-server-name",
        "error",
        SPEC_LIFECYCLE,
        "serverInfo.name identifies the server to the host and MUST be present.",
    ),
    _rule(
        "protocol.missing-server-version",
        "warning",
        SPEC_LIFECYCLE,
        "serverInfo.version lets a host pin and audit a server build; it should be declared.",
    ),
    _rule(
        "protocol.undeclared-capability-listed",
        "error",
        SPEC_LIFECYCLE,
        "A server MUST NOT serve a capability it did not declare during initialize.",
    ),
    _rule(
        "protocol.declared-capability-empty",
        "info",
        SPEC_LIFECYCLE,
        "A declared capability that lists nothing gives an agent a dead end.",
    ),
    _rule(
        "protocol.unknown-capability-declared",
        "info",
        SPEC_LIFECYCLE,
        "A capability key outside the spec's vocabulary belongs under 'experimental'.",
    ),
    # -- JSON-RPC envelopes & errors (transcript-derived, live evidence) ----------------------
    _rule(
        "protocol.response-id-not-echoed",
        "error",
        SPEC_TRANSPORTS,
        "A response MUST echo the id of the request it answers, or it cannot be correlated.",
        requires_transcript=True,
    ),
    _rule(
        "protocol.error-code-non-standard",
        "warning",
        SPEC_TRANSPORTS,
        "An error code inside the JSON-RPC reserved band must be a defined code.",
        requires_transcript=True,
    ),
    _rule(
        "protocol.protocol-version-downgraded",
        "info",
        SPEC_LIFECYCLE,
        "The server negotiated an older revision than the client offered.",
        requires_transcript=True,
    ),
    # -- Pagination (transcript-derived, live evidence) ----------------------------------------
    _rule(
        "protocol.list-result-missing-items",
        "error",
        SPEC_PAGINATION,
        "A list result MUST carry its item array, even when empty.",
        requires_transcript=True,
    ),
    _rule(
        "protocol.empty-page-with-next-cursor",
        "warning",
        SPEC_PAGINATION,
        "An empty page that still advertises nextCursor wastes a round trip per page.",
        requires_transcript=True,
    ),
)

register_rules(PROTOCOL_RULES)


# --- Helpers ------------------------------------------------------------------------------------


def _is_blank(value: Any) -> bool:
    """True when ``value`` is absent or an empty/whitespace-only string."""
    return not (isinstance(value, str) and value.strip())


def _declared(capabilities: Any, key: str) -> bool:
    """True when the server declared capability ``key`` in its handshake.

    A capability is declared by the *presence* of its key in the ``capabilities`` object; its
    value is a (possibly empty) object of sub-capabilities, so ``{"tools": {}}`` declares tools
    just as much as ``{"tools": {"listChanged": true}}`` does.
    """
    return isinstance(capabilities, Mapping) and key in capabilities


def _items_for(context: ConformanceContext, attributes: Tuple[str, ...]) -> int:
    """Total items the surface holds across ``attributes`` (e.g. resources + templates)."""
    return sum(len(getattr(context.surface, attr)) for attr in attributes)


def _error_code_problem(code: Optional[int]) -> Optional[str]:
    """Return why a JSON-RPC error ``code`` is non-standard, or ``None`` when it is fine.

    Codes *outside* the reserved band (:data:`JSONRPC_RESERVED_MIN` …
    :data:`JSONRPC_RESERVED_MAX`) are application-defined and always legitimate. Inside the
    band, only the pre-defined codes and the implementation-defined server-error sub-range are
    permitted; anything else squats on space the specification reserves.

    Args:
        code: The error code the server returned, or ``None`` when it returned a non-integer
            code (itself a defect — JSON-RPC requires an integer).

    Returns:
        A reason string, or ``None`` when the code is acceptable.
    """
    if code is None:
        return "error code is missing or not an integer"
    if not (JSONRPC_RESERVED_MIN <= code <= JSONRPC_RESERVED_MAX):
        return None  # application-defined, legitimate
    if code in JSONRPC_PREDEFINED_CODES:
        return None
    if JSONRPC_SERVER_ERROR_MIN <= code <= JSONRPC_SERVER_ERROR_MAX:
        return None  # implementation-defined server error, legitimate
    return (
        f"error code {code} lies in the JSON-RPC reserved band "
        f"({JSONRPC_RESERVED_MIN}..{JSONRPC_RESERVED_MAX}) but is not a defined code"
    )


def _transcript_path(method: str) -> str:
    """Finding path addressing a method's exchanges within the transcript."""
    return f"transcript.{method}"


# --- Surface-derived rules ------------------------------------------------------------------------


@conformance_rule()
def _rule_protocol_version(
    context: ConformanceContext, findings: List[ConformanceFinding]
) -> None:
    """Check the negotiated protocol version is present and one this client speaks.

    The version is the contract every later message is interpreted under, so an absent or
    unspeakable one is an ``error``. Both are checked from the persisted surface, so the rule
    is deterministic and needs no transcript.
    """
    version = context.surface.protocol_version
    if _is_blank(version):
        findings.append(
            make_finding(
                "surface.protocolVersion",
                "protocol.missing-protocol-version",
                "Server did not report a negotiated protocolVersion in its initialize result.",
            )
        )
        return
    if version not in SUPPORTED_PROTOCOL_VERSIONS:
        findings.append(
            make_finding(
                "surface.protocolVersion",
                "protocol.unsupported-protocol-version",
                f"Server negotiated protocol version '{version}', which is not a supported "
                f"revision ({', '.join(SUPPORTED_PROTOCOL_VERSIONS)}).",
            )
        )


@conformance_rule()
def _rule_server_identity(
    context: ConformanceContext, findings: List[ConformanceFinding]
) -> None:
    """Check the server identified itself: ``serverInfo.name`` (MUST) and ``version`` (SHOULD).

    A host displays and pins a server by this identity; an unnamed server cannot be
    distinguished from another, and an unversioned one cannot be audited across upgrades.
    """
    info = context.surface.server_info
    if _is_blank(getattr(info, "name", None)):
        findings.append(
            make_finding(
                "surface.serverInfo.name",
                "protocol.missing-server-name",
                "Server did not declare a serverInfo.name.",
            )
        )
    if _is_blank(getattr(info, "version", None)):
        findings.append(
            make_finding(
                "surface.serverInfo.version",
                "protocol.missing-server-version",
                "Server did not declare a serverInfo.version, so a host cannot pin its build.",
            )
        )


@conformance_rule()
def _rule_capability_negotiation(
    context: ConformanceContext, findings: List[ConformanceFinding]
) -> None:
    """Cross-check declared capabilities against the capabilities actually listed.

    This is the core of capability negotiation, and it is checkable purely from the stored
    snapshot because the surface holds both halves: what ``initialize`` *declared*, and what
    the ``*/list`` calls actually *returned*.

    Two directions, with deliberately different severities:

    * **Listed but not declared** (``error``) — the server served a capability it never
      negotiated. A conformant client only calls a list method for a declared capability, so
      such items are reachable only by a client that ignores the handshake; the server is
      relying on undefined behaviour.
    * **Declared but empty** (``info``) — the capability was negotiated but exposes nothing.
      Legal, and legitimately transient (a server may populate tools later), so advisory only.
    """
    capabilities = context.surface.capabilities
    for key, attributes, label in CAPABILITY_COLLECTIONS:
        declared = _declared(capabilities, key)
        count = _items_for(context, attributes)
        if count and not declared:
            findings.append(
                make_finding(
                    f"surface.capabilities.{key}",
                    "protocol.undeclared-capability-listed",
                    f"Server listed {count} {label} but never declared the '{key}' capability "
                    f"during initialize.",
                )
            )
        elif declared and not count:
            findings.append(
                make_finding(
                    f"surface.capabilities.{key}",
                    "protocol.declared-capability-empty",
                    f"Server declared the '{key}' capability but listed no {label}.",
                )
            )


@conformance_rule()
def _rule_unknown_capability(
    context: ConformanceContext, findings: List[ConformanceFinding]
) -> None:
    """Flag declared capability keys outside the specification's vocabulary.

    The spec defines a closed set of capability keys plus ``experimental`` as the escape hatch
    for vendor extensions. A bare vendor key at the top level is not wrong enough to break a
    client (which ignores what it does not know), but it is a portability trap — hence
    ``info``, one finding per unknown key, in sorted order for determinism.
    """
    capabilities = context.surface.capabilities
    if not isinstance(capabilities, Mapping):
        return
    for key in sorted(str(k) for k in capabilities):
        if key not in KNOWN_CAPABILITIES:
            findings.append(
                make_finding(
                    f"surface.capabilities.{key}",
                    "protocol.unknown-capability-declared",
                    f"Server declares capability '{key}', which is not a specification "
                    f"capability; vendor extensions belong under 'experimental'.",
                )
            )


# --- Transcript-derived rules ---------------------------------------------------------------------


@conformance_rule(requires_transcript=True)
def _rule_response_id_echo(
    context: ConformanceContext, findings: List[ConformanceFinding]
) -> None:
    """Flag responses that did not echo the id of the request they answer.

    JSON-RPC requires a response to carry the id it is answering; without it a client cannot
    correlate response to request, and on a multiplexed connection it may attribute one call's
    result to another — an ``error``.

    This is the one envelope defect the client tolerates: it validates the ``jsonrpc`` member
    and the presence of ``result``/``error`` (raising on either), but on the plain-JSON path
    :meth:`~app.mcp_client.transport_http.StreamableHttpTransport._coerce_response` accepts the
    body without comparing ids — so a non-echoing server sails through discovery and produces a
    perfectly normal-looking surface. Only the transcript reveals it.

    Reported once per method rather than once per page, so a server that never echoes an id on
    a long paginated list yields one actionable finding instead of fifty.
    """
    transcript = context.transcript
    assert transcript is not None  # guaranteed by requires_transcript

    offenders: dict = {}
    for exchange in transcript.exchanges:
        if not exchange.id_echoed:
            offenders.setdefault(exchange.method, exchange.request_id)

    for method in sorted(offenders):
        findings.append(
            make_finding(
                _transcript_path(method),
                "protocol.response-id-not-echoed",
                f"Response to '{method}' did not echo the request id "
                f"({offenders[method]!r}), so it cannot be correlated to its request.",
            )
        )


@conformance_rule(requires_transcript=True)
def _rule_error_discipline(
    context: ConformanceContext, findings: List[ConformanceFinding]
) -> None:
    """Flag JSON-RPC errors whose code squats on the specification's reserved band.

    Codes outside the reserved band are application-defined and entirely legitimate; inside it,
    only the pre-defined codes and the implementation-defined server-error sub-range are
    permitted (see :func:`_error_code_problem`). A server returning, say, ``-32500`` is using
    space the specification reserves, so a client cannot interpret the code — a ``warning``.

    In practice the errors visible here are the ``initialize`` rejections that drive version
    negotiation: an errored *list* method aborts discovery outright (see the module docstring),
    so it never reaches a lintable surface. A rejected first ``initialize`` is the normal
    fallback path and is not itself a defect — only the shape of its error code is judged.
    """
    transcript = context.transcript
    assert transcript is not None  # guaranteed by requires_transcript

    for exchange in transcript.exchanges:
        if not exchange.is_error:
            continue
        problem = _error_code_problem(exchange.error_code)
        if problem is not None:
            findings.append(
                make_finding(
                    _transcript_path(exchange.method),
                    "protocol.error-code-non-standard",
                    f"Response to '{exchange.method}': {problem}.",
                )
            )


@conformance_rule(requires_transcript=True)
def _rule_version_downgrade(
    context: ConformanceContext, findings: List[ConformanceFinding]
) -> None:
    """Note when the server settled on an older revision than the client offered.

    Not a defect — negotiating down to a mutually supported revision is exactly what the
    lifecycle prescribes — but it is worth surfacing (``info``), because it silently withholds
    the newer revision's features (``title``, tool ``outputSchema``) from every agent using the
    server, which otherwise looks like the *server* simply not providing them.
    """
    transcript = context.transcript
    assert transcript is not None  # guaranteed by requires_transcript

    requested = transcript.requested_version
    negotiated = transcript.negotiated_version
    if not requested or not negotiated or requested == negotiated:
        return
    findings.append(
        make_finding(
            "transcript.initialize",
            "protocol.protocol-version-downgraded",
            f"Client offered protocol version '{requested}' but the server negotiated "
            f"'{negotiated}', so newer-revision fields are unavailable.",
        )
    )


@conformance_rule(requires_transcript=True)
def _rule_pagination(
    context: ConformanceContext, findings: List[ConformanceFinding]
) -> None:
    """Judge each list method's pagination walk from the recorded pages.

    Two checks, per list method, reading only the redacted per-page records (item counts and
    cursor *digests*) — never the opaque cursors themselves:

    * **Missing item array** (``error``) — a page's result omitted its item array. Per the
      pagination spec the array is always present, even when empty; a client that trusts an
      absent array reads a malformed page as "no items", so the omission silently shrinks the
      discovered surface rather than failing loudly.
    * **Empty page with a cursor** (``warning``) — a page returned zero items yet still
      advertised a further page, costing a full round trip that carried nothing.

    Each is reported once per method rather than once per page, so a server that malforms every
    page of a long list yields one actionable finding instead of fifty.

    Non-terminating pagination is *not* checked here — the client's own cursor-cycle and
    page-limit guards abort discovery before a surface exists (see the module docstring).
    Errored pages are skipped: an errored list method likewise never reaches a lintable surface.
    """
    transcript = context.transcript
    assert transcript is not None  # guaranteed by requires_transcript

    for method in LIST_METHODS:
        exchanges = [x for x in transcript.for_method(method) if not x.is_error]
        if not exchanges:
            continue

        if any(exchange.item_count is None for exchange in exchanges):
            findings.append(
                make_finding(
                    _transcript_path(method),
                    "protocol.list-result-missing-items",
                    f"A '{method}' page returned a result with no item array; the array must "
                    f"be present even when empty, or a client reads the page as 'no items'.",
                )
            )
        if any(
            exchange.item_count == 0 and exchange.next_cursor is not None
            for exchange in exchanges
        ):
            findings.append(
                make_finding(
                    _transcript_path(method),
                    "protocol.empty-page-with-next-cursor",
                    f"A '{method}' page returned no items yet advertised a nextCursor, "
                    f"costing a round trip that carried nothing.",
                )
            )


# Re-exported for the tests and for callers that want the initialize method name without
# reaching into the transcript module.
__all__ = [
    "CAPABILITY_COLLECTIONS",
    "JSONRPC_PREDEFINED_CODES",
    "KNOWN_CAPABILITIES",
    "METHOD_INITIALIZE",
    "PROTOCOL_RULES",
]
