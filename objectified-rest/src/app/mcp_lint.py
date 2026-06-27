"""
Deterministic lint rule engine over a normalized MCP capability surface (V2-MCP-21.1).

This is the MCP counterpart to :mod:`app.schema_lint`. Where ``schema_lint`` walks a
reconstructed OpenAPI/JSON-Schema document, this engine walks a
:class:`~app.mcp_client.normalize.DiscoverySurface` — the canonical, version-tolerant
shape produced by MCP discovery (server identity plus normalized tools, resources,
resource templates, and prompts) — and emits an ordered, deterministic set of
:class:`LintFinding` objects.

It deliberately mirrors ``schema_lint``'s structure for consistency:

* **Deterministic** — the same surface always produces the same findings in the same
  order. Findings are sorted by ``(path, rule, id)`` and every finding ``id`` is a
  stable hash of ``path|rule|message`` (prefixed ``mcp-lint-``), so a re-run over an
  unchanged surface yields identical ids.
* **Pure** — no database or network access; callers pass a fully built surface. The
  engine never performs I/O, so it is cheap to call at version-creation time.
* **Extensible** — rules register themselves with :func:`lint_rule` and declare their
  ``(category, severity)`` in :data:`RULE_CATALOGUE`. The concrete MCP hygiene rules
  (V2-MCP-21.2) and annotation/security rules (V2-MCP-21.3) plug into this same
  registry without touching the engine itself.

Scoring, grading, and fingerprint persistence are intentionally *not* part of this
module — they belong to V2-MCP-21.4, which consumes the findings produced here.

Rule groups (``category``):

* ``naming``    — capability item identifier hygiene (e.g. a missing programmatic name).
* ``structure`` — surface-level integrity (duplicate item names, an empty surface).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Tuple

from .mcp_client.normalize import (
    ITEM_TYPE_PROMPT,
    ITEM_TYPE_RESOURCE,
    ITEM_TYPE_RESOURCE_TEMPLATE,
    ITEM_TYPE_TOOL,
    CapabilityItem,
    DiscoverySurface,
)

# --- Severity model -------------------------------------------------------------------------

Severity = str  # "error" | "warning" | "info"

#: Score penalty applied per finding of each severity. Mirrors :mod:`app.schema_lint` so the
#: MCP score (computed downstream in V2-MCP-21.4) stays on the same 0-100 scale as the OpenAPI
#: lint score. Kept here with the engine so rule authors can reason about a rule's weight from
#: its severity alone.
SEVERITY_PENALTY: Mapping[str, float] = {
    "error": 10.0,
    "warning": 4.0,
    "info": 1.0,
}

# --- Path scheme ----------------------------------------------------------------------------
# Findings carry a stable, human-readable path so the UI can deep-link and so finding ids stay
# stable across re-discovery. Item paths key on the item *name* (the programmatic identifier,
# stable across runs) rather than its ordinal (which shifts when the server reorders its list);
# a blank name falls back to the ordinal so the path is still unique and never empty.

#: Maps an MCP ``item_type`` to the surface-level collection name used in finding paths.
ITEM_TYPE_PATH_SEGMENT: Mapping[str, str] = {
    ITEM_TYPE_TOOL: "tools",
    ITEM_TYPE_RESOURCE: "resources",
    ITEM_TYPE_RESOURCE_TEMPLATE: "resourceTemplates",
    ITEM_TYPE_PROMPT: "prompts",
}


def item_path(item: CapabilityItem) -> str:
    """Return the canonical finding path for a capability ``item``.

    The path is ``<collection>.<name>`` (e.g. ``tools.search``). When the item has no
    programmatic name — which a non-conformant server can produce — the ordinal is used
    instead (e.g. ``tools.#2``) so the path remains unique and non-empty.

    Args:
        item: The normalized capability item to address.

    Returns:
        A stable, dotted path string identifying the item within its surface.
    """
    segment = ITEM_TYPE_PATH_SEGMENT.get(item.item_type, item.item_type)
    key = item.name if item.name else f"#{item.ordinal}"
    return f"{segment}.{key}"


# --- Finding model --------------------------------------------------------------------------


@dataclass(frozen=True)
class LintFinding:
    """One itemized MCP lint result.

    ``id`` is a stable hash of ``path|rule|message`` (prefixed ``mcp-lint-``); equal inputs
    always yield the same id, so findings can be de-duplicated and referenced across runs.

    Attributes:
        path: The surface location the finding refers to (see :func:`item_path`).
        category: The rule group (``naming``/``structure``/…) from :data:`RULE_CATALOGUE`.
        rule: The dotted rule id (e.g. ``structure.duplicate-item-name``).
        severity: One of ``error``/``warning``/``info``.
        message: Human-readable description of the defect.
        id: Stable identifier; auto-derived from ``path|rule|message`` when not supplied.
    """

    path: str
    category: str
    rule: str
    severity: Severity
    message: str
    id: str = field(default="", compare=True)

    def __post_init__(self) -> None:
        if not self.id:
            digest = hashlib.sha256(
                f"{self.path}|{self.rule}|{self.message}".encode("utf-8")
            ).hexdigest()[:16]
            object.__setattr__(self, "id", f"mcp-lint-{digest}")

    def as_dict(self) -> Dict[str, str]:
        """Return a JSON-ready dict of this finding (stable key set)."""
        return {
            "id": self.id,
            "path": self.path,
            "category": self.category,
            "rule": self.rule,
            "severity": self.severity,
            "message": self.message,
        }


# --- Rule catalogue & registry --------------------------------------------------------------
# Every rule declares its (category, severity) once, centrally, so the engine and any consumer
# (API, CLI, scoring in V2-MCP-21.4) agree on a rule's group and weight. The catalogue is a
# plain mutable mapping so later rule packs (V2-MCP-21.2 / 21.3) extend it via
# :func:`register_rule_metadata` from their own modules without editing this file.

RULE_CATALOGUE: Dict[str, Tuple[str, Severity]] = {
    "naming.item-name-missing": ("naming", "error"),
    "structure.duplicate-item-name": ("structure", "warning"),
    "structure.empty-surface": ("structure", "info"),
}

#: A rule function inspects the surface and appends any findings it detects, in any order
#: (the engine sorts deterministically afterwards). Rules must be pure: no I/O, no surface
#: mutation.
LintRule = Callable[[DiscoverySurface, List[LintFinding]], None]

#: Ordered registry of rule functions. Foundational rules register below; later rule packs
#: append to it via the :func:`lint_rule` decorator on import.
_RULE_FUNCTIONS: List[LintRule] = []


def register_rule_metadata(rule: str, category: str, severity: Severity) -> None:
    """Register a rule's ``(category, severity)`` in :data:`RULE_CATALOGUE`.

    Rule packs call this (typically at import time) before emitting findings for ``rule``
    so :func:`make_finding` can resolve the rule's group and severity. Re-registering the
    same rule with identical metadata is a no-op; changing the metadata of an already
    registered rule raises, to catch accidental divergence between rule packs.

    Args:
        rule: The dotted rule id (e.g. ``tool.missing-description``).
        category: The rule group this rule belongs to.
        severity: One of ``error``/``warning``/``info``.

    Raises:
        ValueError: If ``rule`` is already registered with different metadata.
    """
    existing = RULE_CATALOGUE.get(rule)
    metadata = (category, severity)
    if existing is not None and existing != metadata:
        raise ValueError(
            f"rule '{rule}' already registered as {existing}, cannot redefine as {metadata}"
        )
    RULE_CATALOGUE[rule] = metadata


def lint_rule(func: LintRule) -> LintRule:
    """Register ``func`` as a lint rule and return it unchanged (decorator form).

    The function is appended to the ordered :data:`_RULE_FUNCTIONS` registry and invoked by
    :func:`lint_mcp_surface`. Registration order does not affect output order (findings are
    sorted), so rule packs may register in any order.
    """
    _RULE_FUNCTIONS.append(func)
    return func


def make_finding(path: str, rule: str, message: str) -> LintFinding:
    """Build a :class:`LintFinding`, resolving its category/severity from the catalogue.

    Args:
        path: The finding's surface location.
        rule: A rule id that MUST be present in :data:`RULE_CATALOGUE`.
        message: Human-readable defect description.

    Returns:
        A fully populated finding with a stable, auto-derived id.

    Raises:
        KeyError: If ``rule`` is not registered in :data:`RULE_CATALOGUE`.
    """
    category, severity = RULE_CATALOGUE[rule]
    return LintFinding(
        path=path, category=category, rule=rule, severity=severity, message=message
    )


# --- Foundational rules ---------------------------------------------------------------------
# Engine-level, kind-agnostic integrity checks. The MCP-specific hygiene rules (per-kind
# description/schema/title/uri checks) and annotation/security rules arrive in V2-MCP-21.2 /
# 21.3 as additional registered rules; these three establish the engine and give it findings
# to exercise on their own.


@lint_rule
def _rule_item_name_missing(surface: DiscoverySurface, findings: List[LintFinding]) -> None:
    """Flag any capability item that lacks a programmatic ``name``.

    ``name`` is required for every MCP item kind on the wire and is the primary key clients
    use to invoke a tool / read a resource / get a prompt; an empty name makes the item
    unusable, so it is an ``error``.
    """
    for item in surface.all_items():
        if not item.name:
            findings.append(
                make_finding(
                    item_path(item),
                    "naming.item-name-missing",
                    f"{item.item_type} at ordinal {item.ordinal} has no name.",
                )
            )


@lint_rule
def _rule_duplicate_item_name(surface: DiscoverySurface, findings: List[LintFinding]) -> None:
    """Flag duplicate ``name`` values within a single capability kind.

    Names must be unique within a kind so a client can address an item unambiguously; two
    tools sharing a name means one shadows the other. Reported once per duplicated name on
    the *second and later* occurrences, in ordinal order, so the canonical first definition
    is left unflagged.
    """
    for items in (
        surface.tools,
        surface.resources,
        surface.resource_templates,
        surface.prompts,
    ):
        seen: set = set()
        for item in items:
            if not item.name:
                continue  # blank names are handled by naming.item-name-missing
            if item.name in seen:
                findings.append(
                    make_finding(
                        item_path(item),
                        "structure.duplicate-item-name",
                        f"Duplicate {item.item_type} name '{item.name}'.",
                    )
                )
            else:
                seen.add(item.name)


@lint_rule
def _rule_empty_surface(surface: DiscoverySurface, findings: List[LintFinding]) -> None:
    """Flag a surface that advertises no capabilities at all.

    A server exposing zero tools, resources, resource templates, and prompts offers nothing
    actionable; this is a low-severity (``info``) service-quality signal rather than a defect
    in any one item.
    """
    if not surface.all_items():
        findings.append(
            make_finding(
                "surface",
                "structure.empty-surface",
                "Surface exposes no tools, resources, resource templates, or prompts.",
            )
        )


# --- Engine entry point ---------------------------------------------------------------------


def lint_mcp_surface(
    surface: DiscoverySurface,
    extra_findings: Optional[Iterable[LintFinding]] = None,
) -> Tuple[LintFinding, ...]:
    """Run every registered rule over ``surface`` and return ordered, deterministic findings.

    The engine invokes each rule in :data:`_RULE_FUNCTIONS`, collects their findings together
    with any ``extra_findings`` the caller supplies, and sorts the result by
    ``(path, rule, id)`` so the output order is fully deterministic regardless of rule
    registration order or the order rules append within themselves.

    Args:
        surface: The normalized MCP capability surface to lint. Not mutated.
        extra_findings: Optional pre-built findings to fold into the report (e.g. findings a
            caller derived out of band). They participate in the same ordering.

    Returns:
        A tuple of :class:`LintFinding`, sorted by ``(path, rule, id)``.
    """
    findings: List[LintFinding] = list(extra_findings or [])
    for rule in _RULE_FUNCTIONS:
        rule(surface, findings)
    findings.sort(key=lambda finding: (finding.path, finding.rule, finding.id))
    return tuple(findings)


def finding_dicts(findings: Iterable[LintFinding]) -> List[Dict[str, str]]:
    """Convenience: render an iterable of findings to a list of JSON-ready dicts."""
    return [finding.as_dict() for finding in findings]
