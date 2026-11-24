"""The tenant-host alias of the Pact Broker surface — PFX-1.2 (#6915).

Pact tooling is configured with one string, the broker base URL. The path form
``https://<api>/v1/tenants/<tenant>/pact-broker`` is such a string; this middleware adds a
second, shorter one for deployments that want it: ``https://<tenant>.<suffix>``.

With ``APIOME_PACT_BROKER_HOST_SUFFIX=pact.example.com``, a request whose ``Host`` is
``acme.pact.example.com`` has its path rewritten from ``/<path>`` to
``/v1/tenants/acme/pact-broker/<path>`` before anything else sees it — the rate limiter, the router
and the access log all work on the real path. The public base the client used is kept on the
request (:func:`alias_base_url`) so the links in a response lead back to the same host.

The alias only chooses a path. Authentication is unchanged: the credential must still belong to
the tenant the host names, so a forged ``Host`` header reaches nothing its key could not already
reach by path. A host under the suffix can reach the Pact Broker routes only — every path on it is
prefixed, so no other part of the API is exposed there.
"""

from __future__ import annotations

import re
from typing import Any, Awaitable, Callable, Dict, MutableMapping, Optional

from .config import settings

__all__ = ["PactBrokerHostAliasMiddleware", "alias_base_url", "tenant_from_host"]

#: Key in the ASGI scope's ``state`` holding the public base URL of an aliased request.
_STATE_KEY = "pact_broker_alias_base"

#: One DNS label that is a plausible tenant slug.
_TENANT_LABEL = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")

Scope = MutableMapping[str, Any]


def tenant_from_host(host: str, suffix: str) -> Optional[str]:
    """Read the tenant a host names under the alias suffix.

    Args:
        host: The request's ``Host`` header (a port is ignored).
        suffix: The configured suffix (``pact.example.com``); empty disables the alias.

    Returns:
        The tenant slug for ``<tenant>.<suffix>``, or ``None`` when the alias is off, the host is
        not directly under the suffix, or the label is not a slug.
    """
    wanted = (suffix or "").strip().strip(".").lower()
    name = (host or "").strip().lower().split(":")[0].rstrip(".")
    if not wanted or not name.endswith("." + wanted):
        return None
    label = name[: -len(wanted) - 1]
    return label if _TENANT_LABEL.match(label) else None


def alias_base_url(scope: Scope) -> Optional[str]:
    """The public base URL of a request that arrived through the alias.

    Args:
        scope: The request's ASGI scope.

    Returns:
        ``https://<tenant>.<suffix>`` (no trailing slash), or ``None`` for a request by path.
    """
    state = scope.get("state")
    return state.get(_STATE_KEY) if isinstance(state, dict) else None


class PactBrokerHostAliasMiddleware:
    """ASGI middleware mapping ``<tenant>.<suffix>/<path>`` onto the tenant's Pact Broker routes."""

    def __init__(self, app: Callable[..., Awaitable[None]], suffix: Optional[str] = None) -> None:
        """Wrap the application.

        Args:
            app: The ASGI application.
            suffix: The alias suffix; ``None`` reads ``settings.pact_broker_host_suffix`` on every
                request, so a test can change the setting.
        """
        self._app = app
        self._suffix = suffix

    async def __call__(self, scope: Scope, receive: Any, send: Any) -> None:
        """Rewrite the path of an aliased HTTP request, then pass it on.

        Args:
            scope: The ASGI scope.
            receive: The ASGI receive channel.
            send: The ASGI send channel.
        """
        if scope.get("type") == "http":
            suffix = self._suffix if self._suffix is not None else settings.pact_broker_host_suffix
            headers: Dict[bytes, bytes] = dict(scope.get("headers") or [])
            host = headers.get(b"host", b"").decode("latin-1")
            tenant = tenant_from_host(host, suffix) if suffix else None
            if tenant:
                prefix = f"/v1/tenants/{tenant}/pact-broker"
                path = scope.get("path") or "/"
                scope = dict(scope)
                scope["path"] = prefix + ("" if path == "/" else path)
                raw_path = scope.get("raw_path")
                if isinstance(raw_path, (bytes, bytearray)):
                    scope["raw_path"] = prefix.encode("ascii") + (b"" if raw_path == b"/" else bytes(raw_path))
                state = dict(scope.get("state") or {})
                state[_STATE_KEY] = f"{scope.get('scheme') or 'https'}://{host.strip().lower()}"
                scope["state"] = state
        await self._app(scope, receive, send)
