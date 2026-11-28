"""Provider test scaffolding — PFX-8.19 (#7316).

``apiome pact scaffold-provider-tests`` calls ``GET /v1/tenants/{t}/pact-provider-tests/{provider}``.
The server writes a provider verification test in the chosen language (pact-js, pact-jvm, pact-go
or pact-python) from the provider's pacts, with one state handler stub per provider state, and
flags the states the provider has not registered in Apiome.

This module holds the pure parts — the path, the languages and the summary lines — so the command
stays thin and every rule here is unit-tested without HTTP.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote, urlencode

#: The languages the server writes, in the order the help lists them.
LANGUAGES = ("typescript", "java", "go", "python")


def scaffold_path(tenant_slug: str, provider: str, language: str) -> str:
    """``/v1/tenants/{t}/pact-provider-tests/{provider}?language=…``, each segment escaped."""
    return (
        f"/v1/tenants/{quote(tenant_slug, safe='')}/pact-provider-tests/{quote(provider, safe='')}"
        f"?{urlencode({'language': language})}"
    )


def has_unregistered(response: dict[str, Any]) -> bool:
    """Whether any state the file handles is not registered in Apiome."""
    return bool(response.get("unregistered"))


def summary_lines(response: dict[str, Any]) -> list[str]:
    """The human-readable summary of a scaffold.

    Args:
        response: The response body.

    Returns:
        Lines: the file and its library, the states (unregistered ones marked), what to install,
        the environment it reads, and one line per notice.
    """
    states = response.get("states") or []
    lines = [
        f"{response.get('file_name')} — {response.get('label')} for {response.get('provider_name')}: "
        f"{len(states)} provider state(s) from {response.get('pacts', 0)} pact(s), "
        f"{response.get('unregistered', 0)} not registered in Apiome",
    ]
    for state in states:
        params = ", ".join(state.get("params") or []) or "no parameters"
        mark = "" if state.get("registered") else " (not registered in Apiome)"
        lines.append(f"    {state.get('name')!r}: {params}{mark}")
    lines.append(f"  install: {response.get('dependency')}")
    lines.append("  set: PACT_BROKER_BASE_URL, PACT_BROKER_TOKEN, PROVIDER_BASE_URL (and GIT_COMMIT, GIT_BRANCH in CI)")
    for notice in response.get("notices") or []:
        lines.append(f"  notice [{notice.get('code')}]: {notice.get('message')}")
    return lines
