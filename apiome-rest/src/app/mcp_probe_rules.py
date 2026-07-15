"""The probe → trust-posture bridge: proven-exploit rules fed by dynamic probes (CLX-3.3, #4857).

CLX-3.2 reserved the ``protocol`` finding origin and the ``REQUIRES_PROBE`` evidence lane, and shipped
:func:`app.mcp_trust_posture.make_proven_finding` as a guarded door with no caller. This module is the
caller. It registers the trust-posture rules that turn an **exploited-in-test** probe finding into a
``proven`` posture finding — the one and only path by which ``proven_count`` on a posture report can
ever be non-zero.

Why this lives here and not in :mod:`app.mcp_trust_posture_rules`
----------------------------------------------------------------
The CLX-3.2 rule packs load *during* the trust-posture engine's own import (its bottom-of-file
``from . import mcp_trust_posture_rules``). This bridge, by contrast, needs the *probe* engine —
:data:`app.mcp_probe_probes.PROBE_UNAUTHENTICATED_READ` and friends — and the probe engine imports the
trust-posture engine for :class:`~app.mcp_trust_posture.ProbeEvidence`. Registering the bridge inside
the trust-posture packs would therefore close an import cycle. Loading it from the *probe* side
instead (this module is imported at the bottom of :mod:`app.mcp_probe`, after both engines are fully
built) keeps the graph acyclic, and has a deliberate second effect: the ``proven`` rules exist exactly
when the probe subsystem is loaded, so a trust-posture run in a context that never touched probing is
byte-identical to what CLX-3.2 produced.

The honesty contract, preserved
--------------------------------
A ``REQUIRES_PROBE`` rule is only *evaluated* when the :class:`~app.mcp_trust_posture.PostureContext`
actually carries probe evidence (:meth:`PostureContext.available_requirements`). With no probe run, it
is *skipped and reported* with the reason CLX-3.2 already wrote — never assumed to pass. And a rule
here mints a proven finding only from a :class:`~app.mcp_trust_posture.ProbeEvidence` whose probe id it
recognizes as an exploit-tier probe; an ``observed`` probe never produces evidence in the first place
(:meth:`app.mcp_probe.ProbeFinding.to_probe_evidence` refuses it), so it cannot reach here.
"""

from __future__ import annotations

from typing import Dict, List, NamedTuple, Tuple

from .mcp_owasp import MCP01_PROMPT_INJECTION, MCP07_AUTH_FAILURE
from .mcp_probe_probes import PROBE_PARAMETER_INJECTION, PROBE_UNAUTHENTICATED_READ
from .mcp_trust_posture import (
    ORIGIN_PROTOCOL,
    REQUIRES_PROBE,
    PostureContext,
    PostureFinding,
    PostureRule,
    make_proven_finding,
    posture_rule,
    register_rules,
)

# --- The proven rules ----------------------------------------------------------------------------
# One per exploit-capable probe. Each carries the OWASP mapping and severity a *demonstrated* instance
# of the defect deserves — an exploit that a probe reproduced is an error, not a signal.

RULE_PROVEN_AUTH_BYPASS = "protocol.proven-auth-bypass"
RULE_PROVEN_INPUT_INJECTION = "protocol.proven-input-injection"

register_rules(
    (
        PostureRule(
            rule_id=RULE_PROVEN_AUTH_BYPASS,
            origin=ORIGIN_PROTOCOL,
            severity="error",
            owasp_ids=(MCP07_AUTH_FAILURE,),
            rationale=(
                "A dynamic probe obtained privileged data from the server without authorization. "
                "This is not a signal to review — it is a reproduced authorization bypass."
            ),
            requires=REQUIRES_PROBE,
        ),
        PostureRule(
            rule_id=RULE_PROVEN_INPUT_INJECTION,
            origin=ORIGIN_PROTOCOL,
            severity="error",
            owasp_ids=(MCP01_PROMPT_INJECTION,),
            rationale=(
                "A dynamic probe demonstrated that attacker-controlled input reaches a tool's output "
                "path unescaped — a reproduced injection, not a static indicator."
            ),
            requires=REQUIRES_PROBE,
        ),
    )
)


class _ProvenMapping(NamedTuple):
    """How one exploit-tier probe maps onto a proven posture rule."""

    rule_id: str
    path: str
    message: str
    remediation: str


#: probe id -> the proven posture rule it produces. A probe id absent from this map produces no
#: posture finding, which is the correct behaviour for an ``observed`` probe that reached here by
#: mistake — it is simply ignored rather than silently upgraded to a proven finding.
_PROBE_TO_RULE: Dict[str, _ProvenMapping] = {
    PROBE_UNAUTHENTICATED_READ: _ProvenMapping(
        rule_id=RULE_PROVEN_AUTH_BYPASS,
        path="protocol.authorization-boundary",
        message="A dynamic probe retrieved privileged data from the server without authorization.",
        remediation=(
            "Enforce authorization on every method, including capability listings; serve no data to "
            "an unauthenticated or unauthorized caller."
        ),
    ),
    PROBE_PARAMETER_INJECTION: _ProvenMapping(
        rule_id=RULE_PROVEN_INPUT_INJECTION,
        path="protocol.input-injection",
        message="A dynamic probe demonstrated reachable input injection into a tool's output.",
        remediation=(
            "Escape or reject untrusted input in tool output; never echo caller-supplied strings into "
            "model-visible content without sanitization."
        ),
    ),
}


@posture_rule(requires=REQUIRES_PROBE)
def _proven_from_probe_evidence(context: PostureContext, findings: List[PostureFinding]) -> None:
    """Turn each recognized exploit-tier :class:`ProbeEvidence` into a ``proven`` posture finding.

    Iterates the context's probe evidence — present only after an active probe run demonstrated
    something — and, for every piece whose probe id maps to a proven rule, mints a proven finding
    carrying that exact evidence. The evidence's own ``observed`` string is threaded onto the finding
    (via :func:`make_proven_finding`), so the demonstration travels with the claim it justifies.
    """
    for evidence in context.probes:
        mapping = _PROBE_TO_RULE.get(evidence.probe_id)
        if mapping is None:
            continue
        findings.append(
            make_proven_finding(
                mapping.path,
                mapping.rule_id,
                mapping.message,
                probe=evidence,
                remediation=mapping.remediation,
            )
        )


def proven_rule_ids() -> Tuple[str, ...]:
    """Return the proven rule ids this bridge registers (for tests and documentation)."""
    return (RULE_PROVEN_AUTH_BYPASS, RULE_PROVEN_INPUT_INJECTION)
