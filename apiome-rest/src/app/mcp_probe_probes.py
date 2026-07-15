"""The probe pack: the concrete passive / safe-active / payload-fuzzing probes (CLX-3.3, #4857).

Registered on import by :mod:`app.mcp_probe`, exactly as the conformance and trust-posture rule packs
register themselves. Each probe is small, does one thing, and declares up front the strongest
classification tier it can reach — so the engine's registration check can refuse a probe that claims
more proof than its profile allows.

The tiering discipline, restated at the point it is applied:

* **Passive** probes read the transcript ordinary discovery already captured and emit only
  :data:`~app.mcp_probe.CLASS_OBSERVED` — they witnessed behaviour, they did not exploit it, and they
  sent nothing to witness it.
* **Safe-active** probes speak to the *protocol* layer (unknown methods, unauthenticated reads) and
  never invoke a business tool with a side-effecting payload. Most emit ``observed``; the auth-boundary
  probe can emit :data:`~app.mcp_probe.CLASS_EXPLOITED_IN_TEST` because serving a privileged listing to
  an unauthorized identity *is* a demonstrated bypass, and reading a listing has no side effect.
* **Payload-fuzzing** probes send crafted, benign-but-hostile canary payloads to tool parameters to
  demonstrate reachability. A reflected canary is a demonstrated injection — an exploit-in-test.

Canaries are generated deterministically from the target's own identifiers (never randomly), so a
run is reproducible and a test can assert on it. They are prober-generated tokens, never server data.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, List, Mapping, Optional, Tuple

from .mcp_client.normalize import DiscoverySurface
from .mcp_owasp import (
    MCP01_PROMPT_INJECTION,
    MCP03_EXCESSIVE_PERMISSIONS,
    MCP07_AUTH_FAILURE,
    MCP10_INSUFFICIENT_AUDIT,
)
from .mcp_probe import (
    CLASS_EXPLOITED_IN_TEST,
    CLASS_OBSERVED,
    PROFILE_PASSIVE,
    PROFILE_PAYLOAD_FUZZING,
    PROFILE_SAFE_ACTIVE,
    ActiveContext,
    PassiveContext,
    Probe,
    ProbeFinding,
    bind_active_profile,
    make_exploited,
    make_observed,
    passive_probe,
    register_probes,
)

# =================================================================================================
# Descriptors — registered first, so make_observed / make_exploited can resolve their OWASP mapping.
# =================================================================================================

PROBE_ID_NOT_ECHOED = "passive.protocol.id-not-echoed"
PROBE_MALFORMED_ENVELOPE = "passive.protocol.malformed-envelope"
PROBE_UNKNOWN_METHOD = "active.protocol.unknown-method"
PROBE_UNAUTHENTICATED_READ = "active.auth.unauthenticated-read"
PROBE_PARAMETER_INJECTION = "fuzz.parameter-injection"
PROBE_OVERSIZED_PARAMETER = "fuzz.oversized-parameter"

register_probes(
    (
        Probe(
            probe_id=PROBE_ID_NOT_ECHOED,
            profile=PROFILE_PASSIVE,
            title="Response did not echo the request id",
            rationale=(
                "JSON-RPC requires a response to echo the id of the request it answers. A server that "
                "does not lets a client mis-correlate responses to requests — the basis of response "
                "confusion and, with a shared transport, cross-session leakage."
            ),
            owasp_ids=(MCP07_AUTH_FAILURE,),
            emits=CLASS_OBSERVED,
        ),
        Probe(
            probe_id=PROBE_MALFORMED_ENVELOPE,
            profile=PROFILE_PASSIVE,
            title="Response envelope was not well-formed JSON-RPC 2.0",
            rationale=(
                "A response whose 'jsonrpc' member is absent or not '2.0' is not a conformant "
                "envelope. A client that trusts such a server cannot rely on the envelope's integrity, "
                "which undermines every downstream authorization decision keyed off it."
            ),
            owasp_ids=(MCP07_AUTH_FAILURE,),
            emits=CLASS_OBSERVED,
        ),
        Probe(
            probe_id=PROBE_UNKNOWN_METHOD,
            profile=PROFILE_SAFE_ACTIVE,
            title="Server accepted an unknown JSON-RPC method",
            rationale=(
                "A conformant server answers an unknown method with error -32601 (method not found). "
                "One that returns a success instead is handling input laxly — a signal it may accept "
                "other things it should reject."
            ),
            owasp_ids=(MCP07_AUTH_FAILURE,),
            emits=CLASS_OBSERVED,
        ),
        Probe(
            probe_id=PROBE_UNAUTHENTICATED_READ,
            profile=PROFILE_SAFE_ACTIVE,
            title="Privileged listing served without authentication",
            rationale=(
                "The server advertised an authentication requirement, yet returned its capability "
                "listing to a request carrying only the dedicated (unprivileged) test identity. "
                "Serving privileged data to an unauthorized caller is a demonstrated authorization "
                "bypass — no side effect, but real unauthorized access."
            ),
            owasp_ids=(MCP07_AUTH_FAILURE,),
            emits=CLASS_EXPLOITED_IN_TEST,
        ),
        Probe(
            probe_id=PROBE_PARAMETER_INJECTION,
            profile=PROFILE_PAYLOAD_FUZZING,
            title="Injected canary reflected in tool output",
            rationale=(
                "A canary token placed in a tool parameter was reflected back in the tool's output, "
                "demonstrating that attacker-controlled input reaches the tool's response path "
                "unescaped — the reachable form of a prompt-injection or output-contamination defect."
            ),
            owasp_ids=(MCP01_PROMPT_INJECTION,),
            emits=CLASS_EXPLOITED_IN_TEST,
        ),
        Probe(
            probe_id=PROBE_OVERSIZED_PARAMETER,
            profile=PROFILE_PAYLOAD_FUZZING,
            title="Server accepted an oversized parameter without bound",
            rationale=(
                "An over-large parameter value was accepted and processed rather than rejected, "
                "indicating the server enforces no input-size bound — a resource-exhaustion and "
                "excessive-processing risk."
            ),
            owasp_ids=(MCP03_EXCESSIVE_PERMISSIONS, MCP10_INSUFFICIENT_AUDIT),
            emits=CLASS_OBSERVED,
        ),
    )
)


# =================================================================================================
# Passive probes — read the captured transcript, emit observed. Send nothing.
# =================================================================================================


@passive_probe
def _passive_id_not_echoed(context: PassiveContext, findings: List[ProbeFinding]) -> None:
    """Flag any recorded exchange whose response failed to echo the request id."""
    transcript = context.transcript
    if transcript is None:
        return
    offenders = [x for x in transcript.exchanges if not x.id_echoed]
    if not offenders:
        return
    methods = sorted({x.method for x in offenders})
    findings.append(
        make_observed(
            PROBE_ID_NOT_ECHOED,
            "protocol.response-correlation",
            "The server returned one or more responses that did not echo the request id.",
            observed=(
                f"{len(offenders)} recorded exchange(s) across method(s) {', '.join(methods)} "
                f"returned a response whose id did not match the request."
            ),
            severity="warning",
            remediation=(
                "Ensure every response echoes the id of the request it answers, per JSON-RPC 2.0."
            ),
        )
    )


@passive_probe
def _passive_malformed_envelope(context: PassiveContext, findings: List[ProbeFinding]) -> None:
    """Flag any recorded exchange whose response envelope was not well-formed JSON-RPC 2.0."""
    transcript = context.transcript
    if transcript is None:
        return
    offenders = [x for x in transcript.exchanges if x.jsonrpc not in ("2.0",)]
    if not offenders:
        return
    methods = sorted({x.method for x in offenders})
    findings.append(
        make_observed(
            PROBE_MALFORMED_ENVELOPE,
            "protocol.envelope-integrity",
            "The server returned one or more responses whose JSON-RPC envelope was malformed.",
            observed=(
                f"{len(offenders)} recorded exchange(s) across method(s) {', '.join(methods)} "
                f"carried a 'jsonrpc' member that was absent or not '2.0'."
            ),
            severity="warning",
            remediation="Emit a well-formed '\"jsonrpc\": \"2.0\"' envelope on every response.",
        )
    )


# =================================================================================================
# Safe-active probes — protocol-layer, never a side-effecting business-tool call.
# =================================================================================================

#: A method name no conformant server implements — the unknown-method probe's request.
_UNKNOWN_METHOD = "$apiome.probe/does-not-exist"

#: JSON-RPC "method not found". A conformant server answers the unknown method with exactly this.
_METHOD_NOT_FOUND = -32601


async def _active_unknown_method(context: ActiveContext, findings: List[ProbeFinding]) -> None:
    """Send an unknown method; observe whether the server rejects it as it should.

    Sends nothing that touches business logic — an unknown method cannot invoke a real tool. A
    server that answers with anything other than method-not-found is handling input laxly.
    """
    response = await context.transport.send(_UNKNOWN_METHOD, {})
    rejected_correctly = (not response.ok) or response.error_code == _METHOD_NOT_FOUND
    if rejected_correctly:
        return
    findings.append(
        make_observed(
            PROBE_UNKNOWN_METHOD,
            "protocol.method-dispatch",
            "The server did not reject an unknown JSON-RPC method with a method-not-found error.",
            observed=(
                f"A request for method '{_UNKNOWN_METHOD}' returned "
                + (
                    f"error code {response.error_code}"
                    if response.error_code is not None
                    else "a success result"
                )
                + f" rather than {_METHOD_NOT_FOUND} (method not found)."
            ),
            severity="warning",
            remediation="Reject unknown methods with JSON-RPC error -32601.",
        )
    )


async def _active_unauthenticated_read(context: ActiveContext, findings: List[ProbeFinding]) -> None:
    """Demonstrate an auth bypass: a privileged listing served to the unprivileged test identity.

    The transport handed to this probe carries only the dedicated, unprivileged test identity named
    in the consent record. If the server nonetheless returns its capability listing, an unauthorized
    caller obtained privileged data — a demonstrated bypass, with no side effect. Only run when the
    server actually advertised an auth requirement (otherwise a public listing is not a bypass).
    """
    advertises_auth = _advertises_authentication(context.surface.capabilities)
    if not advertises_auth:
        return
    response = await context.transport.send("tools/list", {})
    served = response.ok and response.error_code is None and bool(response.result_keys)
    if not served:
        return
    findings.append(
        make_exploited(
            PROBE_UNAUTHENTICATED_READ,
            "protocol.authorization-boundary",
            "protocol.authorization-boundary",
            "The server returned its capability listing to an unauthorized identity.",
            observed=(
                "A 'tools/list' request carrying only the dedicated unprivileged test identity "
                f"({context.consent.test_identity or 'anonymous'}) returned a result "
                f"(keys: {', '.join(response.result_keys)}), despite the server advertising an "
                "authentication requirement."
            ),
            severity="error",
            remediation=(
                "Enforce authorization on every method, including capability listings; do not serve "
                "any data to an unauthenticated or unauthorized caller."
            ),
        )
    )


# =================================================================================================
# Payload-fuzzing probes — crafted hostile payloads to tool parameters. Emit exploited-in-test.
# =================================================================================================


def _canary(tool_name: str) -> str:
    """Derive a deterministic, unique canary token for a tool (never random, so runs reproduce)."""
    digest = hashlib.sha256(f"apiome-probe-canary|{tool_name}".encode("utf-8")).hexdigest()[:16]
    return f"APIOME-CANARY-{digest}"


async def _fuzz_parameter_injection(context: ActiveContext, findings: List[ProbeFinding]) -> None:
    """Place a canary in a tool parameter; a reflected canary demonstrates reachable injection.

    Targets the first string-typed parameter of the first tool that has one. The payload is a benign
    canary — it triggers no action, it only reveals whether attacker-controlled input reaches the
    output path. A reflected canary is a demonstrated exploit.
    """
    target = _first_tool_with_string_param(context.surface)
    if target is None:
        return
    tool_name, param_name = target
    canary = _canary(tool_name)
    response = await context.transport.send(
        "tools/call", {"name": tool_name, "arguments": {param_name: canary}}
    )
    if canary not in response.reflected_canaries:
        return
    findings.append(
        make_exploited(
            PROBE_PARAMETER_INJECTION,
            "protocol.input-injection",
            f"tools.{tool_name}",
            "A canary placed in a tool parameter was reflected in the tool's output.",
            observed=(
                f"Canary '{canary}' supplied to parameter '{param_name}' of tool '{tool_name}' "
                "appeared unescaped in the tool's response, demonstrating that attacker-controlled "
                "input reaches the output path."
            ),
            severity="error",
            remediation=(
                "Escape or reject untrusted input in tool output; never echo caller-supplied strings "
                "into model-visible content without sanitization."
            ),
        )
    )


async def _fuzz_oversized_parameter(context: ActiveContext, findings: List[ProbeFinding]) -> None:
    """Send an oversized parameter; observe whether the server bounds it or accepts it unchecked."""
    target = _first_tool_with_string_param(context.surface)
    if target is None:
        return
    tool_name, param_name = target
    # A large but bounded payload — the transport's own max-response-bytes cap protects the prober.
    oversized = "A" * 65_536
    response = await context.transport.send(
        "tools/call", {"name": tool_name, "arguments": {param_name: oversized}}
    )
    accepted = response.ok and response.error_code is None
    if not accepted:
        return
    findings.append(
        make_observed(
            PROBE_OVERSIZED_PARAMETER,
            f"tools.{tool_name}",
            "The server accepted a 64 KiB parameter value without rejecting it as too large.",
            observed=(
                f"A 65536-byte value on parameter '{param_name}' of tool '{tool_name}' was processed "
                "without an input-size rejection."
            ),
            severity="info",
            remediation="Enforce an input-size bound on tool parameters and reject over-large values.",
        )
    )


# Register the active probes under their profiles (safe-active vs payload-fuzzing), so the engine
# selects the right set for a run. Done via bind_active_profile so each function's profile is a fact
# the engine can read rather than something each function must re-declare.
bind_active_profile(_active_unknown_method, PROFILE_SAFE_ACTIVE)
bind_active_profile(_active_unauthenticated_read, PROFILE_SAFE_ACTIVE)
bind_active_profile(_fuzz_parameter_injection, PROFILE_PAYLOAD_FUZZING)
bind_active_profile(_fuzz_oversized_parameter, PROFILE_PAYLOAD_FUZZING)


# =================================================================================================
# Small surface helpers.
# =================================================================================================

#: Capability keys / auth markers that indicate the server requires authentication. Matched loosely
#: because servers advertise auth in several shapes; a false positive only *adds* an auth-boundary
#: probe, and that probe is a no-op unless data is actually served unauthenticated.
_AUTH_MARKERS = ("auth", "authentication", "oauth", "bearer", "apikey", "api_key", "token")


def _advertises_authentication(capabilities: Mapping[str, Any]) -> bool:
    """Heuristically decide whether the server advertised an authentication requirement."""
    haystack = _json_lower(capabilities)
    return any(marker in haystack for marker in _AUTH_MARKERS)


def _json_lower(value: Any) -> str:
    """Lower-cased flattened text of a JSON-ish value, for cheap substring checks."""
    try:
        return json.dumps(value, sort_keys=True).lower()
    except (TypeError, ValueError):
        return str(value).lower()


def _first_tool_with_string_param(surface: DiscoverySurface) -> Optional[Tuple[str, str]]:
    """Return the (tool_name, first string parameter name) of the first eligible tool, or ``None``.

    "Eligible" means the tool declares an object input schema with at least one string-typed property.
    A tool with no such parameter offers no place to put a canary, so it is skipped.
    """
    for tool in surface.tools:
        schema = tool.input_schema or {}
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            continue
        for param_name, spec in properties.items():
            if isinstance(spec, dict) and spec.get("type") == "string":
                return (tool.name, param_name)
    return None
