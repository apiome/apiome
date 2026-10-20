"""Agentic-web site manifest lint pack — MFI-18.3 (#3976).

Hygiene rules for imported site manifests (agents.json, AWP agent.json, agents.txt, llms.txt),
run by the shared lint engine (:func:`app.lint_engine.lint_canonical_model`) beside its common
pack. Each rule reads the model the normalizer produced (:mod:`app.agents_manifest_normalizer`):
protocols as services, endpoints and AWP actions as operations (their URLs on ``extras``).

* ``agents-manifest.broken-endpoint-ref`` — an endpoint or action address that is empty, not a
  URL, or relative with no site URL to resolve it against; no agent can follow it.
* ``agents-manifest.undeclared-via`` — an AWP action routed ``via`` a protocol the manifest does
  not declare in ``protocols`` (the AWP specification requires it).
* ``agents-manifest.insecure-endpoint`` — an agent endpoint served over plain ``http`` (agents.txt
  and AWP require HTTPS). llms.txt documentation links are exempt.
* ``agents-manifest.duplicate-endpoint`` — the same protocol and URL declared twice.
* ``agents-manifest.duplicate-action-id`` — two AWP actions share an ``id``.
* ``agents-manifest.no-agent-endpoints`` — the manifest declares no A2A, ACP or MCP endpoint, so
  it seeds no descriptor discovery.
"""

from __future__ import annotations

from typing import Iterable, List, Tuple
from urllib.parse import urlsplit

from .canonical_model import CanonicalApi, Operation
from .lint_engine import LintRule, RulePack, lint_canonical_model
from .schema_lint import LintResult

__all__ = ["AgentsManifestRulePack", "lint_agents_manifest", "lint_agents_manifest_result"]

#: Protocols whose endpoints seed descriptor discovery.
_AGENT_PROTOCOLS = ("a2a", "acp", "mcp")


def _operations(api: CanonicalApi) -> List[Operation]:
    """Every endpoint and action operation, in key order."""
    return sorted(api.operations(), key=lambda op: op.key)


def _where(op: Operation) -> str:
    return f"operations.{op.key}"


def _what(op: Operation) -> str:
    """How a message names the operation: ``action 'search'`` or ``mcp endpoint '…'``."""
    if op.extras.get("action"):
        return f"Action {op.name!r}"
    return f"{op.extras.get('protocol')} endpoint {op.extras.get('url') or '(empty)'!r}"


def _check_broken_endpoint_ref(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    for op in _operations(api):
        if op.extras.get("action") and not op.extras.get("url"):
            continue  # An action routed via a protocol need not name its own endpoint.
        if not op.extras.get("resolved_url"):
            yield (
                _where(op),
                f"{_what(op)} is not a reachable URL (empty, malformed, or relative with no site "
                "URL to resolve it against).",
            )


def _check_undeclared_via(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    for op in _operations(api):
        if op.extras.get("action") and not op.extras.get("via_declared", True):
            yield (
                _where(op),
                f"Action {op.name!r} is routed via {op.extras.get('via')!r}, which the manifest "
                "does not declare under `protocols`.",
            )


def _check_insecure_endpoint(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    for op in _operations(api):
        if op.extras.get("protocol") == "docs":
            continue
        resolved = op.extras.get("resolved_url")
        if resolved and urlsplit(resolved).scheme.lower() == "http":
            yield (_where(op), f"{_what(op)} is served over plain http; use https.")


def _check_duplicate_endpoint(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    for op in _operations(api):
        if op.extras.get("endpoint") and op.extras.get("duplicate_of"):
            yield (_where(op), f"{_what(op)} is declared more than once.")


def _check_duplicate_action_id(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    for op in _operations(api):
        if op.extras.get("action") and op.extras.get("duplicate_of"):
            yield (_where(op), f"Action id {op.name!r} is used by more than one action.")


def _check_no_agent_endpoints(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    if not any(service.key in _AGENT_PROTOCOLS for service in api.services):
        yield (
            "api",
            "The manifest declares no A2A, ACP or MCP endpoint, so it seeds no agent descriptor "
            "discovery.",
        )


class AgentsManifestRulePack(RulePack, register=True):
    """Hygiene rules for agentic-web site manifests."""

    format = "agents-manifest"
    pack_id = "agents-manifest"

    _RULES: Tuple[LintRule, ...] = (
        LintRule(
            rule_id="agents-manifest.broken-endpoint-ref",
            category="structure",
            severity="error",
            description="Flag endpoint and action addresses that do not resolve to a URL.",
            check=_check_broken_endpoint_ref,
        ),
        LintRule(
            rule_id="agents-manifest.undeclared-via",
            category="structure",
            severity="error",
            description="Flag AWP actions routed via a protocol the manifest does not declare.",
            check=_check_undeclared_via,
        ),
        LintRule(
            rule_id="agents-manifest.insecure-endpoint",
            category="security",
            severity="warning",
            description="Flag agent endpoints served over plain http.",
            check=_check_insecure_endpoint,
        ),
        LintRule(
            rule_id="agents-manifest.duplicate-endpoint",
            category="naming",
            severity="warning",
            description="Flag a protocol endpoint declared more than once.",
            check=_check_duplicate_endpoint,
        ),
        LintRule(
            rule_id="agents-manifest.duplicate-action-id",
            category="naming",
            severity="warning",
            description="Flag AWP action ids used by more than one action.",
            check=_check_duplicate_action_id,
        ),
        LintRule(
            rule_id="agents-manifest.no-agent-endpoints",
            category="quality",
            severity="info",
            description="Flag manifests that declare no A2A, ACP or MCP endpoint.",
            check=_check_no_agent_endpoints,
        ),
    )

    def rules(self) -> List[LintRule]:
        """Return the pack's rules."""
        return list(self._RULES)


def lint_agents_manifest_result(model: CanonicalApi) -> LintResult:
    """Lint a normalized site manifest through the shared engine (common + manifest packs).

    Args:
        model: The canonical model the site-manifest adapter produced.

    Returns:
        The engine's deterministic lint result.
    """
    return lint_canonical_model(model)


def lint_agents_manifest(raw: str, *, source_label: str | None = None) -> LintResult:
    """Parse, normalize and lint raw manifest text end to end.

    Args:
        raw: The manifest text, in any dialect.
        source_label: Optional filename / URL (a URL gives relative references a base).

    Returns:
        The lint result.

    Raises:
        app.import_source.ImportSourceError: When the manifest cannot be parsed.
    """
    from .agents_manifest_import_source import AgentsManifestImportSource

    adapter = AgentsManifestImportSource()
    return lint_agents_manifest_result(adapter.normalize(adapter.parse(raw, source_label=source_label)))
