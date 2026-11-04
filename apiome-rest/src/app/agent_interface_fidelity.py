"""Agent-interface fidelity rules — MFX-32.4 (#4298).

Exporting an API as an agent interface — MCP tools (MFX-32.1, :mod:`app.mcp_emitter`) or an A2A
Agent Card (MFX-32.2, :mod:`app.a2a_emitter`) — turns operations into tools or skills, and that
conversion loses protocol detail. This module holds the rules both fidelity packs share, so each
loss is **reported with its reason** instead of silently dropped:

* **HTTP semantics** (verb, path, status codes, response headers) have no tool field. They are
  written into the tool's description as text (:func:`http_binding_note`) and reported ``APPROX``
  (:func:`http_binding_verdict`).
* **Authentication** (:func:`auth_scheme_verdicts`): MCP authorization is OAuth 2.1 with bearer
  tokens. A bearer or OAuth 2 scheme maps onto it (``OK``); OpenID Connect, an API key, HTTP
  basic or digest auth and the OAuth 2 implicit and password flows (which OAuth 2.1 removed) are
  ``APPROX`` — the server that serves the tools must hold the credential; mutual TLS, a cookie key
  and any other scheme are ``DROP``.
* **Streaming and events** (:func:`streaming_drop_reason`): a tool returns one result, so an
  event or streaming operation is ``DROP``ped, with a note on what MCP's SSE transport can and
  cannot do.
* **Constraint keywords** (minimum, pattern, format …) survive as JSON Schema keywords
  (:func:`constraints_verdict`, ``OK``).
* **Names and grouping** are synthesized (``SYNTH``) — the packs report each decision.
* **The grouping guard** (:func:`grouping_guard_verdicts`): a single tool or skill surface larger
  than :data:`MAX_AGENT_SURFACE` is an *explosion* — reported at ``critical`` severity, so the
  MFX-3.3 transcoding guard (:mod:`app.transcoding_guards`) classifies the conversion ``severe``
  and the export needs an explicit confirmation. An export that keeps under a quarter of the
  source's surface (:data:`NEAR_EMPTY_SHARE`) is *near-empty* and gets a warning.

Everything here is pure and deterministic: no I/O, and the same model gives the same verdicts.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple

from .canonical_model import CanonicalApi, Constraints, MessageRole, Operation, StreamingMode
from .canonical_security import declared_security_schemes
from .fidelity_rulepack import FidelityVerdict
from .lossiness import LossinessSeverity
from .security_scheme_stubs import SECURITY_SCHEMES_EXTRAS_KEY, scheme_stub
from .tool_projection import EVENT_OPERATION_KINDS

__all__ = [
    "GROUPING_GUARD_MAPPING",
    "MAX_AGENT_SURFACE",
    "NEAR_EMPTY_MAPPING",
    "NEAR_EMPTY_SHARE",
    "auth_scheme_verdicts",
    "classify_auth_scheme",
    "constraints_verdict",
    "declared_auth_schemes",
    "grouping_guard_verdicts",
    "http_binding_note",
    "http_binding_verdict",
    "streaming_drop_reason",
]

#: The largest tool (or skill) surface one descriptor or card should offer. Model providers cap
#: the tools one request may carry (commonly at 128) and hosts trim long tool lists, so a larger
#: surface is not usable as one unit: it must be split (grouped) first.
MAX_AGENT_SURFACE = 128
#: Below this share of the source's operations and channels, an export is *near-empty*.
NEAR_EMPTY_SHARE = 0.25
#: ``target_mapping`` of the explosion advisory — what tests and the UI key on.
GROUPING_GUARD_MAPPING = "grouping guard: surface too large"
#: ``target_mapping`` of the near-empty advisory.
NEAR_EMPTY_MAPPING = "grouping guard: near-empty"

#: The OAuth 2 flows OAuth 2.1 (which MCP authorization builds on) no longer defines.
_REMOVED_OAUTH_FLOWS = ("implicit", "password")


# ===========================================================================
# HTTP semantics → description text
# ===========================================================================


def http_binding_note(operation: Operation) -> Optional[str]:
    """The operation's HTTP binding as one sentence for a tool description.

    Args:
        operation: The operation a tool is made of.

    Returns:
        ``"HTTP: GET /pets/{petId} — returns 200; errors 404; response headers X-Rate-Limit."``,
        or ``None`` when the operation has no HTTP verb and path (gRPC, GraphQL, an MCP source).
    """
    if not operation.http_method or not operation.http_path:
        return None
    success = _status_codes(operation, MessageRole.RESPONSE)
    errors = _status_codes(operation, MessageRole.ERROR)
    headers = sorted({
        header.name
        for message in operation.messages
        if message.role in (MessageRole.RESPONSE, MessageRole.ERROR)
        for header in message.headers
        if header.name
    })
    parts = [f"HTTP: {operation.http_method.upper()} {operation.http_path}"]
    details = []
    if success:
        details.append(f"returns {', '.join(success)}")
    if errors:
        details.append(f"errors {', '.join(errors)}")
    if headers:
        details.append(f"response headers {', '.join(headers)}")
    if details:
        parts.append(" — " + "; ".join(details))
    return "".join(parts) + "."


def _status_codes(operation: Operation, role: MessageRole) -> List[str]:
    """The distinct status codes of the operation's messages in ``role``, in declaration order."""
    codes: List[str] = []
    for message in operation.messages:
        if message.role is role and message.status_code and message.status_code not in codes:
            codes.append(message.status_code)
    return codes


def http_binding_verdict(operation: Operation, *, target_label: str, unit: str) -> Optional[FidelityVerdict]:
    """``APPROX``: the operation's HTTP binding survives only as description text.

    Args:
        operation: An operation that is written (as a tool or skill).
        target_label: The target's label (``"MCP server descriptor"``).
        unit: What the operation becomes (``"tool"``, ``"skill"``).

    Returns:
        The verdict, or ``None`` when the operation has no HTTP binding.
    """
    note = http_binding_note(operation)
    if note is None:
        return None
    binding = note.removeprefix("HTTP: ").rstrip(".")
    return FidelityVerdict.approx(
        message=f"{target_label}: a {unit} has no HTTP fields, so the binding ({binding}) is written into "
        f"the {unit}'s description as text; the server that serves the {unit} makes the HTTP call",
        severity=LossinessSeverity.INFO,
        target_mapping=f"HTTP binding → {unit} description text",
    )


# ===========================================================================
# Authentication
# ===========================================================================


def declared_auth_schemes(api: CanonicalApi) -> List[Tuple[str, Dict[str, Any]]]:
    """Every authentication scheme the model declares, with its definition.

    Read from, in order (the first definition of a name wins): the source document's own
    ``components.securitySchemes`` (OpenAPI 3, AsyncAPI) or ``securityDefinitions`` (Swagger 2) on
    ``api.raw``; the stubs an import recorded on ``api.extras["security_schemes"]``; each agent's
    security schemes; and any scheme an operation or an inferred import names without a definition
    (:func:`app.canonical_security.declared_security_schemes`), as its stub.

    Args:
        api: The model to read.

    Returns:
        ``(name, definition)`` pairs sorted by name; a definition has at least ``type``.
    """
    found: Dict[str, Dict[str, Any]] = {}

    def adopt(name: Any, definition: Any) -> None:
        if isinstance(name, str) and name and isinstance(definition, Mapping) and name not in found:
            found[name] = dict(definition)

    raw = api.raw if isinstance(api.raw, Mapping) else {}
    components = raw.get("components") if isinstance(raw.get("components"), Mapping) else {}
    for source in (components.get("securitySchemes"), raw.get("securityDefinitions"),
                   (api.extras or {}).get(SECURITY_SCHEMES_EXTRAS_KEY)):
        if isinstance(source, Mapping):
            for name, definition in source.items():
                adopt(name, definition)
    for agent in api.agents:
        for scheme in agent.security_schemes:
            adopt(scheme.name, {"type": scheme.type, "scheme": scheme.scheme, "in": scheme.location,
                                "flows": scheme.flows})
    for name in declared_security_schemes(api):
        adopt(name, scheme_stub(name))
    return sorted(found.items())


def classify_auth_scheme(definition: Mapping[str, Any]) -> Tuple[str, str]:
    """How MCP authorization (OAuth 2.1 bearer tokens) carries one scheme.

    Args:
        definition: The scheme's definition (``type``, ``scheme``, ``in``, ``flows`` …).

    Returns:
        ``(outcome, reason)`` where outcome is ``"ok"``, ``"approx"`` or ``"drop"``.
    """
    kind = str(definition.get("type") or "").strip()
    http_scheme = str(definition.get("scheme") or "").strip().lower()
    location = str(definition.get("in") or "").strip().lower()
    if kind == "basic":  # Swagger 2 spells HTTP basic auth as its own type
        kind, http_scheme = "http", "basic"
    if kind == "http" and http_scheme == "bearer":
        return "ok", "a bearer token is what an MCP client sends (MCP authorization is OAuth 2.1 bearer tokens)"
    if kind == "oauth2":
        flows = definition.get("flows") if isinstance(definition.get("flows"), Mapping) else {}
        removed = [flow for flow in _REMOVED_OAUTH_FLOWS if flow in flows]
        if removed:
            return "approx", (f"OAuth 2.1, which MCP authorization builds on, removed the {' and '.join(removed)} "
                              "flow(s); clients must use the authorization-code (or client-credentials) flow")
        return "ok", "MCP authorization is OAuth 2.1, so the OAuth 2 scheme maps onto it"
    if kind == "openIdConnect":
        return "approx", ("MCP authorization keeps the OAuth 2 bearer token; the OpenID Connect identity "
                          "layer (ID token, discovery URL) is not part of a tool")
    if kind in ("apiKey", "httpApiKey") and location in ("header", "query", ""):
        return "approx", ("MCP clients authenticate with OAuth bearer tokens; the server that serves the tools "
                          "must hold the API key and send it upstream")
    if kind == "http" and http_scheme in ("basic", "digest"):
        return "approx", (f"MCP clients authenticate with OAuth bearer tokens; the server that serves the tools "
                          f"must hold the {http_scheme} credentials and send them upstream")
    if kind == "http":
        return "approx", (f"MCP clients authenticate with OAuth bearer tokens; HTTP {http_scheme or 'auth'} "
                          "must be handled by the server that serves the tools")
    if kind in ("apiKey", "httpApiKey") and location == "cookie":
        return "drop", "a cookie is transport state an MCP client does not keep"
    if kind in ("mutualTLS", "X509"):
        return "drop", "a client certificate has no place in MCP authorization"
    return "drop", f"MCP authorization has no equivalent for a {kind or 'untyped'} scheme"


def auth_scheme_verdicts(api: CanonicalApi, *, target_label: str) -> List[FidelityVerdict]:
    """One verdict per declared authentication scheme (``OK`` / ``APPROX`` / ``DROP``).

    Args:
        api: The source model.
        target_label: The target's label, woven into the messages.

    Returns:
        The verdicts in scheme-name order; ``[]`` when the model declares no authentication.
    """
    verdicts: List[FidelityVerdict] = []
    for name, definition in declared_auth_schemes(api):
        outcome, reason = classify_auth_scheme(definition)
        kind = definition.get("type") or "scheme"
        subject = f"auth scheme {name!r} ({kind})"
        if outcome == "ok":
            verdicts.append(FidelityVerdict.ok(
                message=f"{target_label}: {subject} — {reason}",
                target_mapping=f"auth {name} → MCP authorization (OAuth 2.1 bearer)",
            ))
        elif outcome == "approx":
            verdicts.append(FidelityVerdict.approx(
                message=f"{target_label}: {subject} is approximated — {reason}",
                target_mapping=f"auth {name} → server-held credential",
            ))
        else:
            verdicts.append(FidelityVerdict.drop(
                message=f"{target_label}: {subject} is dropped — {reason}; the server that serves the "
                "tools must establish it out of band",
                severity=LossinessSeverity.WARN,
                target_mapping=f"auth {name} → dropped",
            ))
    return verdicts


# ===========================================================================
# Streaming, events and constraints
# ===========================================================================


def streaming_drop_reason(operation: Operation) -> Optional[str]:
    """Why an event or streaming operation gets no tool, or ``None`` when it is a plain call.

    Args:
        operation: The operation.

    Returns:
        The reason — with the SSE note for a server stream, which MCP's Streamable HTTP transport
        can carry only as progress notifications of one call.
    """
    if operation.kind in EVENT_OPERATION_KINDS:
        return (f"a {operation.kind.value} operation is an event flow with no single reply, and a tool "
                "returns one result")
    if operation.streaming is StreamingMode.SERVER:
        return ("a server stream has no tool form: a tool returns one result — MCP's Streamable HTTP "
                "transport streams only progress notifications (SSE) while one call runs")
    if operation.streaming is not StreamingMode.NONE:
        return (f"a {operation.streaming.value}-streaming operation has no tool form: a tool takes one set "
                "of arguments and returns one result")
    return None


def constraints_verdict(constraints: Optional[Constraints], *, target_label: str) -> Optional[FidelityVerdict]:
    """``OK``: validation keywords survive as JSON Schema in the tool's schemas.

    Args:
        constraints: The constraints of a field or scalar type.
        target_label: The target's label.

    Returns:
        The verdict naming the keywords, or ``None`` when there are none.
    """
    if constraints is None:
        return None
    facets = sorted(constraints.model_dump(exclude={"extras"}, exclude_none=True))
    if not facets:
        return None
    return FidelityVerdict.ok(
        message=f"{target_label}: constraint keyword(s) {', '.join(facets)} survive as JSON Schema in the "
        "tool schemas",
        target_mapping="constraints → JSON Schema keywords",
    )


# ===========================================================================
# The grouping guard
# ===========================================================================


def grouping_guard_verdicts(
    api: CanonicalApi,
    surfaces: Mapping[str, int],
    *,
    covered: int,
    target_label: str,
    unit: str,
    split_hint: str,
) -> List[FidelityVerdict]:
    """The near-empty and explosion advisories for an agent-interface export.

    Args:
        api: The source model.
        surfaces: Each emitted descriptor or card (its name) → how many tools or skills it has.
        covered: How many of the source's operations the export writes (as, or inside, a tool or
            skill) — a tag-grouped skill covers several.
        target_label: The target's label.
        unit: ``"tool"`` or ``"skill"``.
        split_hint: The option that splits a surface (``"grouping=per-service"``).

    Returns:
        A ``critical`` ``APPROX`` per surface larger than :data:`MAX_AGENT_SURFACE` (so the
        transcoding guard requires confirmation), and a ``warn`` ``DROP`` when the export keeps
        less than :data:`NEAR_EMPTY_SHARE` of the source's operations and channels.
    """
    verdicts: List[FidelityVerdict] = []
    for name, count in sorted(surfaces.items()):
        if count > MAX_AGENT_SURFACE:
            verdicts.append(FidelityVerdict.approx(
                message=f"{target_label}: {name!r} would offer {count} {unit}s, more than the "
                f"{MAX_AGENT_SURFACE} an agent can be handed at once; hosts trim or reject a surface this "
                f"large — split it with {split_hint} (or curate the operations) before exporting",
                severity=LossinessSeverity.CRITICAL,
                target_mapping=GROUPING_GUARD_MAPPING,
            ))
    source = len(api.operations()) + len(api.channels)
    if covered and source and covered < source * NEAR_EMPTY_SHARE:
        verdicts.append(FidelityVerdict.drop(
            message=f"{target_label}: only {covered} of the source's {source} operations and channels are "
            f"written as {unit}s — the export is near-empty; most of the API has no "
            f"{unit} form (events, streams, deprecated operations)",
            severity=LossinessSeverity.WARN,
            target_mapping=NEAR_EMPTY_MAPPING,
        ))
    return verdicts
