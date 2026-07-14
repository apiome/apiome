"""OWASP MCP Top 10 risk catalog and rule mapping (CLX-3.2, #4856).

Every trust-posture rule declares the OWASP MCP risk(s) it speaks to, so a finding always answers
"which recognized risk is this an instance of?" rather than standing as an isolated opinion. This
module is the single place those risk ids are defined; :mod:`app.mcp_trust_posture` validates every
registered rule's ``owasp_ids`` against it at import time, so a rule citing a risk that does not
exist is a startup failure, not a broken link discovered by a user later.

Why a local catalog
-------------------
The OWASP MCP Top 10 is a published, evolving community list. This module encodes the *risk
taxonomy* — ids, titles, and what each risk means for an MCP server — as Apiome's own transparent
reading of it, with a resolvable reference per entry. It deliberately does not vendor, mirror, or
claim to be the upstream document: :data:`CATALOG_REVISION` states which revision of the list this
reading tracks, so when the list moves, the divergence is visible rather than silent.

Coverage, honestly
------------------
:func:`coverage_summary` reports, for a set of rules, which risks are covered and which are not.
An uncovered risk is reported as uncovered — Apiome never implies that a risk it has no rule for is
a risk the server does not have. This is the same contract the evidence layer applies to absent
scans (:mod:`app.lint_evidence`): silence is a visible gap, never a pass.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

#: The revision of the OWASP MCP Top 10 this catalog's reading tracks. Stamped into every report so
#: a stored finding stays interpretable after the upstream list moves on.
CATALOG_REVISION = "2025"

#: Resolvable reference for the published list this catalog reads.
CATALOG_REFERENCE = "https://owasp.org/www-project-mcp-top-10/"

# --- Risk ids ----------------------------------------------------------------------------------
# Stable, never renamed once shipped: they are persisted on findings and hashed into report
# fingerprints, exactly like rule ids.

MCP01_PROMPT_INJECTION = "MCP01"
MCP02_TOOL_POISONING = "MCP02"
MCP03_EXCESSIVE_PERMISSIONS = "MCP03"
MCP04_SUPPLY_CHAIN = "MCP04"
MCP05_COMMAND_EXECUTION = "MCP05"
MCP06_SECRET_EXPOSURE = "MCP06"
MCP07_AUTH_FAILURE = "MCP07"
MCP08_CONTEXT_OVERSHARING = "MCP08"
MCP09_TOOL_SHADOWING = "MCP09"
MCP10_INSUFFICIENT_AUDIT = "MCP10"


@dataclass(frozen=True)
class OwaspRisk:
    """One risk in the OWASP MCP Top 10, as this catalog reads it.

    Attributes:
        risk_id: Stable id (``MCP01`` … ``MCP10``). Never renamed once shipped.
        title: Short human title.
        description: What the risk means concretely for an MCP server — written so a finding that
            cites it explains itself without the reader having to open the spec.
        reference: Resolvable URL for the risk.
    """

    risk_id: str
    title: str
    description: str
    reference: str = CATALOG_REFERENCE

    def as_dict(self) -> Dict[str, str]:
        """Return the risk as a JSON-ready dict (the catalog payload the API serves)."""
        return {
            "risk_id": self.risk_id,
            "title": self.title,
            "description": self.description,
            "reference": self.reference,
        }


#: The catalog, keyed by risk id. Ordered by id so every rendering of it is stable.
RISKS: Mapping[str, OwaspRisk] = {
    MCP01_PROMPT_INJECTION: OwaspRisk(
        risk_id=MCP01_PROMPT_INJECTION,
        title="Prompt injection",
        description=(
            "Text the server controls — a tool description, a prompt template, a resource body — "
            "reaches the model's context and can carry instructions the operator never authorized. "
            "The model cannot tell a description from a directive."
        ),
    ),
    MCP02_TOOL_POISONING: OwaspRisk(
        risk_id=MCP02_TOOL_POISONING,
        title="Tool poisoning",
        description=(
            "A tool definition is crafted to manipulate the agent rather than describe the tool: "
            "hidden instructions, invisible characters, or text that redirects the agent to other "
            "tools or to exfiltrate what it already holds."
        ),
    ),
    MCP03_EXCESSIVE_PERMISSIONS: OwaspRisk(
        risk_id=MCP03_EXCESSIVE_PERMISSIONS,
        title="Excessive permissions / scope creep",
        description=(
            "The server requests or exposes far more authority than its stated purpose needs — "
            "broad OAuth scopes, unconstrained filesystem roots, a tool that accepts an arbitrary "
            "command. The blast radius of a compromise is the authority granted, not the authority "
            "used."
        ),
    ),
    MCP04_SUPPLY_CHAIN: OwaspRisk(
        risk_id=MCP04_SUPPLY_CHAIN,
        title="Supply-chain compromise",
        description=(
            "The server's dependencies, base image, or install scripts carry known vulnerabilities "
            "or are pulled from unpinned, mutable references — so what runs in production is not "
            "necessarily what was reviewed."
        ),
    ),
    MCP05_COMMAND_EXECUTION: OwaspRisk(
        risk_id=MCP05_COMMAND_EXECUTION,
        title="Unsafe command execution",
        description=(
            "The server reaches a shell, an eval, or a dynamic import with data that an agent (and "
            "therefore, transitively, an untrusted prompt) can influence."
        ),
    ),
    MCP06_SECRET_EXPOSURE: OwaspRisk(
        risk_id=MCP06_SECRET_EXPOSURE,
        title="Secret exposure",
        description=(
            "Credential material is committed to the source, baked into config or an image layer, "
            "or echoed back through a tool description, an error message, or a resource."
        ),
    ),
    MCP07_AUTH_FAILURE: OwaspRisk(
        risk_id=MCP07_AUTH_FAILURE,
        title="Authentication and authorization failure",
        description=(
            "The server exposes state-changing or destructive capability without establishing who "
            "is calling, or transmits its credentials over a channel that does not protect them."
        ),
    ),
    MCP08_CONTEXT_OVERSHARING: OwaspRisk(
        risk_id=MCP08_CONTEXT_OVERSHARING,
        title="Context over-sharing",
        description=(
            "The server hands the agent more of the environment than the task needs — a resource "
            "template rooted at the filesystem, a tool returning whole records where a field would "
            "do — so ordinary use leaks data into the model's context."
        ),
    ),
    MCP09_TOOL_SHADOWING: OwaspRisk(
        risk_id=MCP09_TOOL_SHADOWING,
        title="Tool shadowing",
        description=(
            "A tool takes the name (or near-name) of a well-known tool from another server, so an "
            "agent resolving by name may invoke this one instead of the one it meant."
        ),
    ),
    MCP10_INSUFFICIENT_AUDIT: OwaspRisk(
        risk_id=MCP10_INSUFFICIENT_AUDIT,
        title="Insufficient audit and observability",
        description=(
            "Consequential actions leave no reviewable trace: destructive tools are undeclared, "
            "irreversible operations are indistinguishable from read-only ones, and nothing the "
            "agent did can be reconstructed afterwards."
        ),
    ),
}

#: Every known risk id, in stable catalog order.
RISK_IDS: Tuple[str, ...] = tuple(sorted(RISKS))


class UnknownRiskError(ValueError):
    """Raised when a rule cites an OWASP risk id that is not in :data:`RISKS`.

    Raised at rule-registration (import) time rather than at finding time: a rule pack citing a
    risk that does not exist is a bug in the pack, and failing at startup beats shipping a finding
    whose risk link resolves to nothing.
    """

    def __init__(self, risk_id: str) -> None:
        super().__init__(
            f"unknown OWASP MCP risk id '{risk_id}'; known risks: {list(RISK_IDS)}"
        )
        self.risk_id = risk_id


def validate_risk_ids(risk_ids: Iterable[str]) -> Tuple[str, ...]:
    """Validate that every id in ``risk_ids`` is a known risk, and return them sorted.

    Args:
        risk_ids: The risk ids a rule claims to cover.

    Returns:
        The ids, de-duplicated and sorted, so a rule's mapping renders identically every time.

    Raises:
        UnknownRiskError: If any id is not in :data:`RISKS`.
    """
    validated = set()
    for risk_id in risk_ids:
        if risk_id not in RISKS:
            raise UnknownRiskError(risk_id)
        validated.add(risk_id)
    return tuple(sorted(validated))


def risk_titles(risk_ids: Iterable[str]) -> List[str]:
    """Human titles for a rule's risk ids, in catalog order (unknown ids are skipped).

    Args:
        risk_ids: Risk ids to label.

    Returns:
        The titles, for rendering a finding's risk chips.
    """
    return [RISKS[r].title for r in sorted(set(risk_ids)) if r in RISKS]


def catalog() -> List[Dict[str, str]]:
    """Return the whole risk catalog as JSON-ready dicts, in stable id order."""
    return [RISKS[risk_id].as_dict() for risk_id in RISK_IDS]


def coverage_summary(
    rule_risk_ids: Sequence[Sequence[str]],
) -> Dict[str, Any]:
    """Report which OWASP risks a set of rules covers — and which it does not.

    The uncovered list is the point of this function. A catalog that only reported what it *does*
    check would let a reader infer that an unmentioned risk is a risk the server does not have.
    Naming the gaps keeps the report honest about the limits of its own coverage.

    Args:
        rule_risk_ids: One entry per rule — the risk ids that rule covers.

    Returns:
        ``{"revision", "reference", "covered": [...], "uncovered": [...], "rules_per_risk": {...}}``
        where ``rules_per_risk`` counts how many rules speak to each covered risk.
    """
    rules_per_risk: Dict[str, int] = {}
    for ids in rule_risk_ids:
        for risk_id in set(ids):
            if risk_id in RISKS:
                rules_per_risk[risk_id] = rules_per_risk.get(risk_id, 0) + 1

    covered = sorted(rules_per_risk)
    uncovered = [risk_id for risk_id in RISK_IDS if risk_id not in rules_per_risk]
    return {
        "revision": CATALOG_REVISION,
        "reference": CATALOG_REFERENCE,
        "covered": covered,
        "uncovered": uncovered,
        "rules_per_risk": dict(sorted(rules_per_risk.items())),
    }
