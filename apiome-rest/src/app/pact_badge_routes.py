"""``/v1/browse/tenants/{t}/projects/{p}/pact-badges`` — public pact badges, PFX-1.10 (#6923).

Anonymous, read-only status endpoints for a **public** project (one with a published, public
version). They let a README or the browse project page show whether the pacts of an application
are verified:

* ``GET …/pact-badges`` — the state of every pacticipant bound to the project, with the badge URLs.
  The browse project page embeds from this; it is an empty list when nothing is bound.
* ``GET …/pact-badges/pacticipants/{slug}/badge.svg`` and ``…/shields.json`` — one pacticipant:
  ``failing`` when any of its pacts is failing, ``verified`` when all are, else ``unknown``.
* ``GET …/pact-badges/pacts/provider/{provider}/consumer/{consumer}/badge.svg`` and
  ``…/shields.json`` — the latest pact between the pair.

The shields document is for ``https://img.shields.io/endpoint?url=…``. Anything that is not public
— a private project, an unbound or unknown pacticipant — is one uniform ``404`` that never reveals
a pact exists. Only a status word and names bound to a public project are exposed.
"""

from __future__ import annotations

from typing import Any, Dict
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from .database import db
from .pact_badge import badge_svg, shields_endpoint
from .pact_badge_store import find_public_project, pacticipant_badge, pair_badge, project_statuses

__all__ = ["router"]

router = APIRouter(prefix="/v1/browse", tags=["browse"])

_PATH = "/tenants/{tenant_slug}/projects/{project_slug}/pact-badges"
_NOT_FOUND = {404: {"description": "No such public project, or nothing bound to it by that name."}}

#: Badges are embedded by third parties and fetched often; a state that is five minutes old is fine.
_CACHE = "public, max-age=300"


def _not_found() -> HTTPException:
    """The one 404 every refusal shares."""
    return HTTPException(status_code=404, detail="No pact badge found.")


def _project(tenant_slug: str, project_slug: str) -> Dict[str, str]:
    """The public project, or the uniform 404."""
    project = find_public_project(db, tenant_slug, project_slug)
    if project is None:
        raise _not_found()
    return project


def _svg(label: str, status: str) -> Response:
    """A cacheable SVG badge response."""
    return Response(badge_svg(label, status), media_type="image/svg+xml", headers={"Cache-Control": _CACHE})


def _shields(label: str, status: str) -> JSONResponse:
    """A cacheable shields.io endpoint response."""
    return JSONResponse(shields_endpoint(label, status), headers={"Cache-Control": _CACHE})


def _urls(request: Request, tenant_slug: str, project_slug: str, slug: str) -> Dict[str, str]:
    """The badge and shields URLs of one pacticipant."""
    root = str(request.base_url).rstrip("/")
    project = f"{quote(tenant_slug)}/projects/{quote(project_slug)}"
    base = f"{root}/v1/browse/tenants/{project}/pact-badges/pacticipants/{quote(slug)}"
    return {"badge_url": f"{base}/badge.svg", "shields_url": f"{base}/shields.json"}


@router.get(_PATH, summary="Pact status of a public project", responses=_NOT_FOUND)
def project_pact_status(request: Request, tenant_slug: str, project_slug: str) -> Dict[str, Any]:
    """The state of every pacticipant bound to a public project, with badge URLs."""
    project = _project(tenant_slug, project_slug)
    items = project_statuses(db, project)
    return {
        "tenant_slug": tenant_slug,
        "project_slug": project_slug,
        "pacticipants": [{**item, **_urls(request, tenant_slug, project_slug, item["slug"])} for item in items],
    }


@router.get(
    _PATH + "/pacticipants/{pacticipant_slug}/badge.svg",
    summary="SVG badge of a pacticipant",
    response_class=Response,
    responses={**_NOT_FOUND, 200: {"content": {"image/svg+xml": {}}}},
)
def pacticipant_badge_svg(tenant_slug: str, project_slug: str, pacticipant_slug: str) -> Response:
    """``pact: <pacticipant> | verified / failing / unknown``."""
    found = pacticipant_badge(db, _project(tenant_slug, project_slug), pacticipant_slug)
    if found is None:
        raise _not_found()
    return _svg(f"pact: {found['slug']}", found["status"])


@router.get(
    _PATH + "/pacticipants/{pacticipant_slug}/shields.json",
    summary="shields.io endpoint of a pacticipant",
    responses=_NOT_FOUND,
)
def pacticipant_badge_shields(tenant_slug: str, project_slug: str, pacticipant_slug: str) -> JSONResponse:
    """The shields.io endpoint document of a pacticipant."""
    found = pacticipant_badge(db, _project(tenant_slug, project_slug), pacticipant_slug)
    if found is None:
        raise _not_found()
    return _shields(f"pact: {found['slug']}", found["status"])


@router.get(
    _PATH + "/pacts/provider/{provider_slug}/consumer/{consumer_slug}/badge.svg",
    summary="SVG badge of one pact",
    response_class=Response,
    responses={**_NOT_FOUND, 200: {"content": {"image/svg+xml": {}}}},
)
def pact_badge_svg(tenant_slug: str, project_slug: str, provider_slug: str, consumer_slug: str) -> Response:
    """``pact: <consumer> → <provider> | verified / failing / unknown``."""
    found = pair_badge(db, _project(tenant_slug, project_slug), provider_slug, consumer_slug)
    if found is None:
        raise _not_found()
    return _svg(f"pact: {consumer_slug} → {provider_slug}", found["status"])


@router.get(
    _PATH + "/pacts/provider/{provider_slug}/consumer/{consumer_slug}/shields.json",
    summary="shields.io endpoint of one pact",
    responses=_NOT_FOUND,
)
def pact_badge_shields(tenant_slug: str, project_slug: str, provider_slug: str, consumer_slug: str) -> JSONResponse:
    """The shields.io endpoint document of one pact."""
    found = pair_badge(db, _project(tenant_slug, project_slug), provider_slug, consumer_slug)
    if found is None:
        raise _not_found()
    return _shields(f"pact: {consumer_slug} → {provider_slug}", found["status"])
