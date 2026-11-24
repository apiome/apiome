"""A documented ``501`` for the Pact Broker API Apiome does not serve — PFX-1.8 (#6921).

A Pact client that reaches a resource Apiome has not built must learn that from the answer, not
from a bare ``404`` it would read as "that pact does not exist". So under ``…/pact-broker`` every
request no real route serves is answered:

.. code-block:: text

    HTTP/1.1 501 Not Implemented
    Link: <https://docs.apiome.dev/ship/pact-broker/compatibility>; rel="help"

    {"detail": {"code": "pact-broker-not-implemented",
                "message": "PUT is not supported on “A pacticipant” …",
                "pointer": "/v1/tenants/acme/pact-broker/pacticipants/web",
                "endpoint": "/pacticipants/{pacticipant}", "status": "partial",
                "supported_methods": ["GET", "DELETE"],
                "alternative": "/v1/tenants/{tenant}/pacticipants/{pacticipant}",
                "documentation": "https://docs.apiome.dev/ship/pact-broker/compatibility",
                "pact_broker_version": "2.124.0"}}

Two routers do it, and :mod:`app.main` mounts them around the real Pact Broker routers:

* :data:`router` goes **first**. It has one route per catalog endpoint with unsupported methods,
  for those methods only. Most are reached anyway by the catch-all, but a few unsupported paths are
  also valid values of a supported template — ``…/latest/badge`` is ``…/latest/{tag}`` with the
  tag ``badge`` — and must be claimed before the real route sees them, as the Pact Broker's own
  router does.
* :data:`fallback_router` goes **last**: any method on any path under ``…/pact-broker``. It answers
  a path that is a catalogued endpoint asked with a method Apiome lacks, and a path that is no Pact
  Broker resource at all.

The caller must still authenticate as for any Pact Broker route; the body names nothing of the
tenant's.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from .pact_broker_auth import validate_broker_authentication
from .pact_broker_compat import (
    ENDPOINTS,
    PACT_BROKER_VERSION,
    BrokerEndpoint,
    compatibility_url,
    find_endpoint,
    issue_url,
)

__all__ = ["CODE_NOT_IMPLEMENTED", "fallback_router", "not_implemented_body", "router"]

#: The ``detail.code`` of every 501 from the Pact Broker surface.
CODE_NOT_IMPLEMENTED = "pact-broker-not-implemented"

#: Every method the catch-all claims. ``OPTIONS`` stays with the CORS middleware, and ``HEAD`` on a
#: real ``GET`` route keeps its ``405``.
_ALL_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]

router = APIRouter(prefix="/v1/tenants", tags=["pact-broker"])
fallback_router = APIRouter(prefix="/v1/tenants", tags=["pact-broker"])


def _broker_path(request: Request, tenant_slug: str) -> str:
    """The request path below the broker base URL (``""`` for the index).

    Args:
        request: The request (after the tenant-host alias rewrote its path, if it applies).
        tenant_slug: The tenant in the URL.

    Returns:
        The rest of the path, starting with ``/``, or ``""``.
    """
    base = f"/v1/tenants/{tenant_slug}/pact-broker"
    path = request.url.path
    return path[len(base) :] if path.startswith(base) else path


def _message(method: str, endpoint: Optional[BrokerEndpoint]) -> str:
    """The sentence a person reads in the CLI's error output.

    Args:
        method: The request method.
        endpoint: The catalog entry of the path, or ``None``.

    Returns:
        What is missing, what is there instead and where it is tracked.
    """
    if endpoint is None:
        return (
            "This path is not part of the Pact Broker API Apiome serves. "
            "The compatibility page lists every Pact Broker endpoint and its status."
        )
    if method in endpoint.supported:
        # Only reached for a method the catalog and the app disagree on; the tests prevent it.
        return f"“{endpoint.title}” is supported, but this request did not reach it."
    parts = [f"{method} is not supported on “{endpoint.title}” ({endpoint.status})."]
    if endpoint.supported:
        parts.append(f"Supported: {', '.join(endpoint.supported)}.")
    if endpoint.note:
        parts.append(endpoint.note.replace("`", ""))
    if endpoint.alternative:
        parts.append(f"Apiome route: {endpoint.alternative}.")
    if endpoint.tracking:
        parts.append(f"Tracked in {issue_url(endpoint.tracking)}.")
    return " ".join(parts)


def not_implemented_body(request: Request, tenant_slug: str) -> Dict[str, Any]:
    """The ``detail`` of a 501 for this request.

    Args:
        request: The request no real route serves.
        tenant_slug: The tenant in the URL.

    Returns:
        ``code``, ``message``, ``pointer`` (the request path) and, when the path is a catalogued
        endpoint, its template, status, supported methods, tracking issue and Apiome alternative;
        always the compatibility page and the Pact Broker version the catalog follows.
    """
    endpoint = find_endpoint(_broker_path(request, tenant_slug))
    detail: Dict[str, Any] = {
        "code": CODE_NOT_IMPLEMENTED,
        "message": _message(request.method, endpoint),
        "pointer": request.url.path,
    }
    if endpoint is not None:
        detail["endpoint"] = endpoint.path or "/"
        detail["status"] = endpoint.status
        detail["supported_methods"] = list(endpoint.supported)
        if endpoint.tracking:
            detail["tracking"] = issue_url(endpoint.tracking)
        if endpoint.alternative:
            detail["alternative"] = endpoint.alternative
    detail["documentation"] = compatibility_url()
    detail["pact_broker_version"] = PACT_BROKER_VERSION
    return detail


def pact_broker_not_implemented(
    tenant_slug: str,
    request: Request,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> JSONResponse:
    """Answer a Pact Broker request Apiome does not serve with a documented 501.

    Args:
        tenant_slug: The tenant in the URL.
        request: The request.
        auth_data: The authenticated principal (only authentication is required).

    Returns:
        ``501`` with :func:`not_implemented_body` and a ``Link`` header to the compatibility page.

    Raises:
        HTTPException: 401 / 403 from authentication, as on every Pact Broker route.
    """
    del auth_data  # authentication is the only requirement
    return JSONResponse(
        status_code=501,
        content={"detail": not_implemented_body(request, tenant_slug)},
        headers={"Link": f'<{compatibility_url()}>; rel="help"'},
    )


def _register_catalogued_routes() -> List[str]:
    """Add one route per catalog endpoint with unsupported methods, for those methods.

    Returns:
        The paths registered (for the tests).
    """
    paths: List[str] = []
    for endpoint in ENDPOINTS:
        if not endpoint.unsupported:
            continue
        path = "/{tenant_slug}/pact-broker" + endpoint.path
        router.add_api_route(
            path,
            pact_broker_not_implemented,
            methods=list(endpoint.unsupported),
            include_in_schema=False,
        )
        paths.append(path)
    return paths


_register_catalogued_routes()

fallback_router.add_api_route(
    "/{tenant_slug}/pact-broker/{rest:path}",
    pact_broker_not_implemented,
    methods=_ALL_METHODS,
    include_in_schema=False,
)
