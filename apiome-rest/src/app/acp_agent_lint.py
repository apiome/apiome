"""ACP agent manifest lint pack — MFI-18.2 (#3975).

Descriptor hygiene rules for imported ACP agents, run by the shared lint engine
(:func:`app.lint_engine.lint_canonical_model`) beside its common pack. Each rule reads the model
the ACP normalizer produced (:mod:`app.acp_agent_normalizer`): agents as services (metadata on
``service.extras``), capabilities as operations.

* ``acp.duplicate-agent-name`` — two agents in one listing share a ``name``; ``POST /runs`` cannot
  tell them apart.
* ``acp.invalid-agent-name`` — a name that is not an RFC 1123 label (lower-case letters, digits
  and ``-``), so it cannot be used in ``/agents/{name}``.
* ``acp.agent-missing-description`` — a calling agent cannot tell when to delegate to it.
* ``acp.duplicate-capability-name`` — one agent declares a capability name twice.
* ``acp.capability-missing-description`` — a capability with no description.
* ``acp.no-capabilities`` — an agent that declares no capabilities says nothing about what it does.
* ``acp.untyped-content`` — an agent that does not declare its input or output content types (or
  declares only ``*/*``), so its message contract is unknown.
* ``acp.missing-tags`` — an agent with no tags and no domains cannot be found by either.
* ``acp.missing-license`` — no SPDX ``license`` in the metadata.
"""

from __future__ import annotations

import re
from typing import Iterable, List, Tuple

from .acp_agent_parser import ACP_AGENT_NAME_PATTERN
from .canonical_model import CanonicalApi, Service
from .lint_engine import LintRule, RulePack, lint_canonical_model
from .schema_lint import LintResult

__all__ = ["AcpRulePack", "lint_acp", "lint_acp_result"]

_AGENT_NAME = re.compile(ACP_AGENT_NAME_PATTERN)
_WILDCARD = "*/*"


def _agents(api: CanonicalApi) -> List[Service]:
    """Every agent service, in key order."""
    return sorted(api.services, key=lambda s: s.key)


def _path(agent: Service) -> str:
    return f"services.{agent.key}"


def _check_duplicate_agent_name(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    for agent in _agents(api):
        first = agent.extras.get("duplicate_of")
        if first:
            yield (
                _path(agent),
                f"Agent name {agent.name!r} is already used by {first!r}; agent names must be "
                "unique on a server.",
            )


def _check_invalid_agent_name(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    for agent in _agents(api):
        if agent.extras.get("duplicate_of"):
            continue
        if not _AGENT_NAME.match(agent.name):
            yield (
                _path(agent),
                f"Agent name {agent.name!r} is not an RFC 1123 label (lower-case letters, "
                "digits and '-'), so it cannot be used in /agents/{name}.",
            )


def _check_agent_missing_description(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    for agent in _agents(api):
        if not (agent.description or "").strip():
            yield (_path(agent), f"Agent {agent.name!r} has no description.")


def _check_duplicate_capability_name(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    for agent in _agents(api):
        for op in sorted(agent.operations, key=lambda o: o.key):
            first = op.extras.get("duplicate_of")
            if first:
                yield (
                    f"operations.{op.key}",
                    f"Agent {agent.name!r} declares capability {op.name!r} more than once.",
                )


def _check_capability_missing_description(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    for agent in _agents(api):
        for op in sorted(agent.operations, key=lambda o: o.key):
            if not (op.description or "").strip():
                yield (
                    f"operations.{op.key}",
                    f"Capability {op.name!r} of agent {agent.name!r} has no description.",
                )


def _check_no_capabilities(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    for agent in _agents(api):
        if not agent.operations:
            yield (
                _path(agent),
                f"Agent {agent.name!r} declares no capabilities in its metadata.",
            )


def _check_untyped_content(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    for agent in _agents(api):
        gaps = [
            direction
            for direction in ("input", "output")
            if not agent.extras.get("content_types_declared")
            or list(agent.extras.get(f"{direction}_content_types") or []) == [_WILDCARD]
        ]
        if gaps:
            yield (
                _path(agent),
                f"Agent {agent.name!r} accepts any content type for its {' and '.join(gaps)}; "
                "declare the MIME types it actually handles.",
            )


def _check_missing_tags(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    for agent in _agents(api):
        if not agent.extras.get("tags") and not agent.extras.get("domains"):
            yield (
                _path(agent),
                f"Agent {agent.name!r} has no tags or domains, so it cannot be found by either.",
            )


def _check_missing_license(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    for agent in _agents(api):
        if not agent.extras.get("license"):
            yield (_path(agent), f"Agent {agent.name!r} declares no SPDX license.")


class AcpRulePack(RulePack, register=True):
    """Descriptor hygiene rules for ACP agent manifests."""

    format = "acp"
    pack_id = "acp"

    _RULES: Tuple[LintRule, ...] = (
        LintRule(
            rule_id="acp.duplicate-agent-name",
            category="naming",
            severity="error",
            description="Flag agent names repeated within one listing.",
            check=_check_duplicate_agent_name,
        ),
        LintRule(
            rule_id="acp.invalid-agent-name",
            category="naming",
            severity="warning",
            description="Flag agent names that are not RFC 1123 labels.",
            check=_check_invalid_agent_name,
        ),
        LintRule(
            rule_id="acp.agent-missing-description",
            category="documentation",
            severity="warning",
            description="Flag agents with no description.",
            check=_check_agent_missing_description,
        ),
        LintRule(
            rule_id="acp.duplicate-capability-name",
            category="naming",
            severity="warning",
            description="Flag capability names repeated within one agent.",
            check=_check_duplicate_capability_name,
        ),
        LintRule(
            rule_id="acp.capability-missing-description",
            category="documentation",
            severity="warning",
            description="Flag capabilities with no description.",
            check=_check_capability_missing_description,
        ),
        LintRule(
            rule_id="acp.no-capabilities",
            category="quality",
            severity="info",
            description="Flag agents that declare no capabilities.",
            check=_check_no_capabilities,
        ),
        LintRule(
            rule_id="acp.untyped-content",
            category="structure",
            severity="info",
            description="Flag agents whose input or output content types are undeclared or */*.",
            check=_check_untyped_content,
        ),
        LintRule(
            rule_id="acp.missing-tags",
            category="quality",
            severity="info",
            description="Flag agents with no tags and no domains.",
            check=_check_missing_tags,
        ),
        LintRule(
            rule_id="acp.missing-license",
            category="quality",
            severity="info",
            description="Flag agents that declare no SPDX license.",
            check=_check_missing_license,
        ),
    )

    def rules(self) -> List[LintRule]:
        """Return the pack's rules."""
        return list(self._RULES)


def lint_acp_result(model: CanonicalApi) -> LintResult:
    """Lint a normalized ACP document through the shared engine (common + ``acp`` packs).

    Args:
        model: The canonical model the ACP adapter produced.

    Returns:
        The engine's deterministic lint result.
    """
    return lint_canonical_model(model)


def lint_acp(raw: str) -> LintResult:
    """Parse, normalize and lint raw ACP manifest / listing text end to end.

    Args:
        raw: The document JSON.

    Returns:
        The lint result.

    Raises:
        app.import_source.ImportSourceError: When the document cannot be parsed.
    """
    from .acp_import_source import AcpImportSource

    adapter = AcpImportSource()
    return lint_acp_result(adapter.normalize(adapter.parse(raw)))
