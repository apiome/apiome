"""REST calls for per-branch repository refresh rules (RAR-6.4, #3541).

``GET`` and ``PUT`` ``/v1/tenants/{slug}/repositories/{id}/branch-refresh-rules``. The server
replaces the whole rule set on ``PUT``, so :func:`upsert_rule` and :func:`remove_rule` read the
current rules, change one, and write the set back.
"""

from __future__ import annotations

from typing import Any

import typer

from apiome_cli.client import api_paths
from apiome_cli.client.http import RestClient
from apiome_cli.exit_codes import EXIT_ERROR, EXIT_USAGE

#: The fields of a rule the ``PUT`` body carries (the read adds audit fields).
_RULE_FIELDS = ("branchPattern", "refreshEnabled", "refreshIntervalSeconds", "targetVersionLine")


def _branch_refresh(payload: Any) -> dict[str, Any]:
    """Unwrap the ``branchRefresh`` projection, or exit when the response is malformed."""
    body = payload.get("branchRefresh") if isinstance(payload, dict) else None
    if not isinstance(body, dict):
        typer.echo("Branch refresh response was not the expected object.", err=True)
        raise typer.Exit(EXIT_ERROR)
    return body


def fetch_branch_rules(client: RestClient, tenant_slug: str, repository_id: str) -> dict[str, Any]:
    """Read a repository's branch rules and each tracked branch's effective settings.

    Args:
        client: Tenant-scoped REST client.
        tenant_slug: Tenant slug for the ``/v1`` path.
        repository_id: Repository UUID.

    Returns:
        The ``branchRefresh`` projection (``rules``, ``branches``, repository-wide fallback).
    """
    response = client.get(api_paths.tenant_repository_branch_refresh_rules(tenant_slug, repository_id))
    return _branch_refresh(response.json())


def replace_branch_rules(
    client: RestClient, tenant_slug: str, repository_id: str, rules: list[dict[str, Any]]
) -> dict[str, Any]:
    """Replace a repository's branch rules with ``rules``.

    Args:
        client: Tenant-scoped REST client.
        tenant_slug: Tenant slug.
        repository_id: Repository UUID.
        rules: The complete rule set (camelCase keys); ``[]`` removes every rule.

    Returns:
        The ``branchRefresh`` projection after the update.
    """
    body = {"rules": [{key: rule.get(key) for key in _RULE_FIELDS if key in rule} for rule in rules]}
    response = client.put(
        api_paths.tenant_repository_branch_refresh_rules(tenant_slug, repository_id), json=body
    )
    return _branch_refresh(response.json())


def upsert_rule(rules: list[dict[str, Any]], rule: dict[str, Any]) -> list[dict[str, Any]]:
    """Return ``rules`` with ``rule`` added, or replacing the rule with the same pattern.

    Args:
        rules: The current rules.
        rule: The rule to set (``branchPattern`` required).

    Returns:
        The new rule list, in the original order with a new rule appended.
    """
    pattern = rule["branchPattern"]
    out = [dict(r) for r in rules if r.get("branchPattern") != pattern]
    position = next((i for i, r in enumerate(rules) if r.get("branchPattern") == pattern), len(out))
    out.insert(position, dict(rule))
    return out


def remove_rule(rules: list[dict[str, Any]], pattern: str) -> list[dict[str, Any]]:
    """Return ``rules`` without the rule for ``pattern``, or exit when there is none.

    Args:
        rules: The current rules.
        pattern: The branch pattern to remove.

    Returns:
        The remaining rules.
    """
    remaining = [dict(r) for r in rules if r.get("branchPattern") != pattern]
    if len(remaining) == len(rules):
        typer.echo(f"No branch rule for {pattern!r}.", err=True)
        raise typer.Exit(EXIT_USAGE)
    return remaining
