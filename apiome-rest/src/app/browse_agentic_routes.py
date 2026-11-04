"""Public agentic-web manifests for a tenant's published surface — MFX-32.3 (#4297).

Two anonymous, read-only routes beside the browse directory (:mod:`app.browse_public_routes`):

* **``GET /v1/browse/tenants/{tenant_slug}/agents.json``** — the tenant's ``agents.json``;
* **``GET /v1/browse/tenants/{tenant_slug}/llms.txt``** — the tenant's ``llms.txt``.

Both are built by :mod:`app.agentic_web_manifest` over the tenant's **published, public**
artifacts only: the same public browse queries anonymous visitors get
(``published IS TRUE AND visibility = 'public'``, undeleted), whoever calls — a member's
credentials never add a private or draft artifact to a manifest meant for the open web. Each
project contributes its latest published public version; an agent artifact's own endpoint is read
from its source through :func:`app.export_source.load_public_export_source`, the public export gate.

Links point at apiome-browse, whose address the REST service does not know by itself: the caller
passes it as ``site_url`` (apiome-browse's ``/tenant/{slug}/agents.json`` and ``/llms.txt`` routes
pass their own origin), else ``APIOME_PUBLIC_BROWSE_URL`` is used, else links are site-relative.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from .agentic_web_manifest import (
    AGENT_PROTOCOLS,
    PublishedArtifact,
    agent_endpoint,
    build_agents_json,
    build_llms_txt,
    render_agents_json,
)
from .browse_public_routes import _sort_versions_semver_desc
from .config import settings
from .database import db
from .export_source import ExportSourceError, load_public_export_source
from .public_export_guards import enforce_public_export_rate_limit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/browse", tags=["browse"])

#: How long a client or CDN may reuse a manifest (the browse changelog feeds use the same).
CACHE_CONTROL = "public, max-age=300"

_SITE_URL_DESCRIPTION = (
    "The apiome-browse site root (origin plus base path, e.g. `https://browse.example.com`) the "
    "manifest's links point at. Defaults to `APIOME_PUBLIC_BROWSE_URL`; without either, links are "
    "site-relative."
)
_RESPONSES = {
    404: {"description": "Tenant not found."},
    422: {"description": "`site_url` is not an absolute http(s) URL."},
    429: {"description": "Public export rate limit exceeded."},
}


def _require_rate_limit(request: Request) -> None:
    """FastAPI dependency: the public-export per-IP rate limit (agent sources are loaded)."""
    enforce_public_export_rate_limit(request)


def resolve_site_url(site_url: Optional[str]) -> str:
    """The Browse site root the links use: ``site_url``, else the setting, else ``""``.

    Args:
        site_url: The caller's ``site_url`` query parameter.

    Returns:
        The root without a trailing slash, or ``""``.

    Raises:
        HTTPException: 422 when the chosen value is not an absolute http(s) URL without a query or
            fragment.
    """
    value = (site_url or settings.public_browse_url or "").strip()
    if not value:
        return ""
    parts = urlsplit(value)
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc or parts.query or parts.fragment:
        raise HTTPException(status_code=422, detail="site_url must be an absolute http(s) URL with no query.")
    return value.rstrip("/")


def _agent_url(tenant_slug: str, project_slug: str, version: str, source_format: Optional[str]) -> Optional[str]:
    """The endpoint an agent artifact's source declares; ``None`` for others or when unreadable."""
    if (source_format or "").lower() not in AGENT_PROTOCOLS:
        return None
    try:
        source = load_public_export_source(tenant_slug, project_slug, version)
    except ExportSourceError as exc:
        logger.info("agentic manifest: no source for %s/%s@%s (%s)", tenant_slug, project_slug, version, exc)
        return None
    return agent_endpoint(source_format, source.api)


def published_artifacts(tenant_slug: str, tenant_id: str) -> List[PublishedArtifact]:
    """The tenant's published, public artifacts: each project's latest published public version.

    Always the anonymous (public) slice, whatever the caller's credentials.

    Args:
        tenant_slug: The tenant's slug.
        tenant_id: The tenant's id.

    Returns:
        One artifact per project with a public published version, by name then slug.
    """
    artifacts: List[PublishedArtifact] = []
    projects = db.list_public_browse_projects_for_tenant(tenant_id, require_published=True)
    for project in sorted(projects, key=lambda row: (str(row.get("name") or "").lower(), str(row["slug"]))):
        slug = str(project["slug"])
        versions = _sort_versions_semver_desc(db.list_public_browse_versions_for_project(tenant_id, slug))
        if not versions:
            continue
        latest = str(project.get("latest_version") or "")
        row: Dict[str, Any] = next((v for v in versions if str(v.get("version_id")) == latest), versions[0])
        version = str(row["version_id"])
        source_format = row.get("source_format")
        artifacts.append(
            PublishedArtifact(
                project_slug=slug,
                name=str(project.get("name") or slug),
                version=version,
                protocol=row.get("protocol"),
                source_format=source_format,
                description=row.get("description"),
                agent_url=_agent_url(tenant_slug, slug, version, source_format),
            )
        )
    return artifacts


def _tenant(tenant_slug: str) -> Dict[str, Any]:
    """The tenant row, or a 404."""
    tenant = db.get_tenant_row_by_slug(tenant_slug)
    if tenant is None:
        raise HTTPException(status_code=404, detail=f"Tenant not found: {tenant_slug}")
    return tenant


@router.get(
    "/tenants/{tenant_slug}/agents.json",
    summary="The tenant's agents.json over its published public artifacts (no auth)",
    description=(
        "An agents.txt-companion `agents.json` listing every published public artifact of the tenant "
        "(its latest published version): its Browse page under `x-apiome-apis`, and for an A2A, MCP "
        "or ACP artifact the agent endpoint its source declares under `a2a` / `mcp` / `acp` "
        "(MFX-32.3). Private and draft artifacts are never listed. Re-imports as an Agentic-web Site "
        "Manifest."
    ),
    response_class=Response,
    responses={200: {"content": {"application/json": {}}}, **_RESPONSES},
    dependencies=[Depends(_require_rate_limit)],
)
async def get_tenant_agents_json(
    tenant_slug: str,
    site_url: Optional[str] = Query(None, description=_SITE_URL_DESCRIPTION),
) -> Response:
    """Serve the tenant's ``agents.json``.

    Args:
        tenant_slug: The tenant's slug.
        site_url: The Browse site root the links use (see :func:`resolve_site_url`).

    Returns:
        The JSON document, cacheable for five minutes.

    Raises:
        HTTPException: 404 for an unknown tenant; 422 for a bad ``site_url``.
    """
    tenant = _tenant(tenant_slug)
    root = resolve_site_url(site_url)
    document = build_agents_json(
        tenant_slug=str(tenant["slug"]), tenant_name=str(tenant["name"]), site_url=root,
        artifacts=published_artifacts(str(tenant["slug"]), str(tenant["id"])),
    )
    return Response(
        content=render_agents_json(document),
        media_type="application/json",
        headers={"Cache-Control": CACHE_CONTROL},
    )


@router.get(
    "/tenants/{tenant_slug}/llms.txt",
    summary="The tenant's llms.txt over its published public artifacts (no auth)",
    description=(
        "An `llms.txt` (llmstxt.org) for the tenant: an `## APIs` section linking every published "
        "public artifact's Browse page, an `## Agents` section with each agent artifact's endpoint, "
        "and the matching agents.json under `## Optional` (MFX-32.3). Private and draft artifacts "
        "are never listed."
    ),
    response_class=Response,
    responses={200: {"content": {"text/plain": {}}}, **_RESPONSES},
    dependencies=[Depends(_require_rate_limit)],
)
async def get_tenant_llms_txt(
    tenant_slug: str,
    site_url: Optional[str] = Query(None, description=_SITE_URL_DESCRIPTION),
) -> Response:
    """Serve the tenant's ``llms.txt``.

    Args:
        tenant_slug: The tenant's slug.
        site_url: The Browse site root the links use (see :func:`resolve_site_url`).

    Returns:
        The Markdown text as ``text/plain``, cacheable for five minutes.

    Raises:
        HTTPException: 404 for an unknown tenant; 422 for a bad ``site_url``.
    """
    tenant = _tenant(tenant_slug)
    root = resolve_site_url(site_url)
    slug = str(tenant["slug"])
    text = build_llms_txt(
        tenant_slug=slug, tenant_name=str(tenant["name"]), site_url=root,
        artifacts=published_artifacts(slug, str(tenant["id"])),
        agents_json_url=f"{root}/tenant/{quote(slug, safe='')}/agents.json",
    )
    return Response(
        content=text,
        media_type="text/plain; charset=utf-8",
        headers={"Cache-Control": CACHE_CONTROL},
    )
