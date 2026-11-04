"""Read-only xRegistry API over a tenant's published artifacts — MFX-34.2 (#4307).

An xRegistry-aware client points at Apiome instead of downloading an export. Two mounts serve the
same xRegistry core API (``GET`` only):

* **``/v1/browse/tenants/{tenant_slug}/xregistry``** — anonymous, the **published, public** slice
  only (``published IS TRUE AND visibility = 'public'``, undeleted), whoever calls: a member's
  credentials never add a private artifact here. Sources load through
  :func:`app.export_source.load_public_export_source`, which re-checks that gate.
* **``/v1/xregistry/{tenant_slug}``** — authenticated (JWT or API key) for a member of that tenant:
  the tenant's **published** versions of any visibility, as the member Browse directory lists them.
  Drafts are never served, and another tenant's artifacts never are.

Each project contributes its latest published version, projected by MFX-34.1 and merged by
:func:`app.xregistry_registry.compose_registry`. Both mounts are capped by the public-export per-IP
rate limit (MFX-7.3). The composed registry is cached per slice and per exact set of versions, so a
client walking the API does not rebuild every model on every request, and a newly published version
is served at once.

Paths under either mount::

    GET /                                      the registry (?inline=* embeds everything)
    GET /capabilities, /model
    GET /{groups}                              schemagroups | messagegroups
    GET /{groups}/{gid}
    GET /{groups}/{gid}/{resources}            schemas | messages
    GET /{groups}/{gid}/{resources}/{rid}      a schema's document; a message's attributes
    GET /{groups}/{gid}/{resources}/{rid}$details
    GET /{groups}/{gid}/{resources}/{rid}/versions[/{vid}[$details]]
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse

from .auth import validate_authentication
from .browse_public_routes import _sort_versions_semver_desc
from .database import db
from .export_source import ExportSourceError, load_export_source, load_public_export_source
from .public_export_guards import enforce_public_export_rate_limit
from .xregistry_registry import (
    GROUP_KINDS,
    ComposedRegistry,
    RegistryArtifact,
    XRegistryNotFoundError,
    XRegistryView,
    compose_registry,
    split_details,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["xregistry"])

#: Public mount prefix and the tenant (member) one.
PUBLIC_PREFIX = "/v1/browse/tenants/{tenant_slug}/xregistry"
TENANT_PREFIX = "/v1/xregistry/{tenant_slug}"
#: Cache policy of each mount's responses.
PUBLIC_CACHE_CONTROL = "public, max-age=300"
TENANT_CACHE_CONTROL = "private, max-age=60"
#: How long a composed registry is reused, and how many are kept.
CACHE_TTL_SECONDS = 300
CACHE_MAX_ENTRIES = 32

_RESPONSES = {
    404: {"description": "Unknown tenant, or the path names no entity of the registry."},
    429: {"description": "Public export rate limit exceeded."},
}
_INLINE = Query(None, description="`*` (any value) embeds every collection below the requested entity.")


# ===========================================================================
# The artifacts and the cache
# ===========================================================================


def _latest(project: Dict[str, Any], versions: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The project's latest published version row (its ``latest_version``, else the highest semver)."""
    ordered = _sort_versions_semver_desc(versions)
    if not ordered:
        return None
    latest = str(project.get("latest_version") or "")
    return next((v for v in ordered if str(v.get("version_id")) == latest), ordered[0])


def _published(tenant_id: str, *, member: bool) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """``(project, latest published version)`` per project of the slice, sorted by slug."""
    if member:
        projects = db.list_member_browse_projects_for_tenant(tenant_id, require_published=True)
    else:
        projects = db.list_public_browse_projects_for_tenant(tenant_id, require_published=True)
    chosen = []
    for project in sorted(projects, key=lambda row: str(row["slug"])):
        slug = str(project["slug"])
        if member:
            versions = db.list_member_browse_versions_for_project(tenant_id, slug)
        else:
            versions = db.list_public_browse_versions_for_project(tenant_id, slug)
        row = _latest(project, versions)
        if row is not None:
            chosen.append((project, row))
    return chosen


def _load_api(tenant: Dict[str, Any], project: Dict[str, Any], version: str, *, member: bool) -> Any:
    """The version's canonical model through the slice's own gate, or ``None`` when it cannot load."""
    slug = str(project["slug"])
    try:
        if member:
            row = db.get_project_by_slug(slug, str(tenant["id"]))
            if row is None:
                return None
            return load_export_source(str(tenant["id"]), str(row["id"]), version).api
        return load_public_export_source(str(tenant["slug"]), slug, version).api
    except ExportSourceError as exc:
        logger.info("xregistry: no source for %s/%s@%s (%s)", tenant["slug"], slug, version, exc)
        return None


class _RegistryCache:
    """A small LRU of composed registries, keyed by slice and by the exact versions they hold."""

    def __init__(self) -> None:
        self._entries: "OrderedDict[Tuple[Any, ...], Tuple[float, ComposedRegistry]]" = OrderedDict()
        self._lock = threading.Lock()

    def get_or_build(self, key: Tuple[Any, ...], build: Callable[[], ComposedRegistry]) -> ComposedRegistry:
        """The cached registry for ``key``, else ``build()`` (cached for :data:`CACHE_TTL_SECONDS`)."""
        now = time.monotonic()
        with self._lock:
            hit = self._entries.get(key)
            if hit is not None and now - hit[0] < CACHE_TTL_SECONDS:
                self._entries.move_to_end(key)
                return hit[1]
        registry = build()
        with self._lock:
            self._entries[key] = (now, registry)
            self._entries.move_to_end(key)
            while len(self._entries) > CACHE_MAX_ENTRIES:
                self._entries.popitem(last=False)
        return registry

    def clear(self) -> None:
        """Forget every entry (tests)."""
        with self._lock:
            self._entries.clear()


registry_cache = _RegistryCache()


def build_tenant_registry(tenant: Dict[str, Any], *, member: bool) -> ComposedRegistry:
    """The tenant's registry for one slice (public, or member), from the cache when it is current.

    Args:
        tenant: The tenant row (``id``, ``slug``, ``name``).
        member: ``True`` for the authenticated mount (published, any visibility); ``False`` for the
            public one (published and public only).

    Returns:
        The composed registry.
    """
    chosen = _published(str(tenant["id"]), member=member)
    key = ("member" if member else "public", str(tenant["id"]),
           tuple((str(p["slug"]), str(v["version_id"]), str(v.get("published_at"))) for p, v in chosen))

    def build() -> ComposedRegistry:
        artifacts = []
        for project, version in chosen:
            api = _load_api(tenant, project, str(version["version_id"]), member=member)
            if api is not None:
                artifacts.append(RegistryArtifact(
                    project_slug=str(project["slug"]), name=str(project.get("name") or project["slug"]),
                    version_label=str(version["version_id"]), published_at=version.get("published_at"), api=api,
                ))
        return compose_registry(str(tenant["slug"]), str(tenant.get("name") or tenant["slug"]), artifacts)

    return registry_cache.get_or_build(key, build)


# ===========================================================================
# Requests
# ===========================================================================


def _tenant(tenant_slug: str) -> Dict[str, Any]:
    """The tenant row, or a 404."""
    tenant = db.get_tenant_row_by_slug(tenant_slug)
    if tenant is None:
        raise HTTPException(status_code=404, detail=f"Tenant not found: {tenant_slug}")
    return tenant


def _view(request: Request, tenant_slug: str, *, member: bool) -> XRegistryView:
    """The view of the requested tenant's registry, rooted at the mount's absolute URL."""
    tenant = _tenant(tenant_slug)
    prefix = (TENANT_PREFIX if member else PUBLIC_PREFIX).format(tenant_slug=tenant_slug)
    base = str(request.base_url).rstrip("/") + prefix
    return XRegistryView(build_tenant_registry(tenant, member=member), base)


def _json(entity: Any, *, member: bool) -> JSONResponse:
    """An entity as JSON, with the mount's cache policy."""
    return JSONResponse(entity, headers={"Cache-Control": TENANT_CACHE_CONTROL if member else PUBLIC_CACHE_CONTROL})


def _document(document: Any, headers: Dict[str, str], *, member: bool) -> Response:
    """A resource document: JSON, a text, or a ``303`` to where it lives."""
    headers = {**headers, "Cache-Control": TENANT_CACHE_CONTROL if member else PUBLIC_CACHE_CONTROL}
    if document is None and "Location" in headers:
        return Response(status_code=303, headers=headers)
    if isinstance(document, str):
        return Response(content=document, media_type="text/plain; charset=utf-8", headers=headers)
    return Response(content=json.dumps(document, ensure_ascii=False, indent=2), media_type="application/json",
                    headers=headers)


def _serve(member: bool, render: Callable[[XRegistryView], Response], request: Request, tenant_slug: str) -> Response:
    """Render one entity, turning an unknown path into ``404``."""
    view = _view(request, tenant_slug, member=member)
    try:
        return render(view)
    except XRegistryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _rate_limit(request: Request) -> None:
    """FastAPI dependency: the public-export per-IP rate limit (MFX-7.3)."""
    enforce_public_export_rate_limit(request)


def _register(member: bool) -> None:
    """Register every xRegistry path on one mount."""
    prefix = TENANT_PREFIX if member else PUBLIC_PREFIX
    scope = "the tenant's published artifacts (members)" if member else "the tenant's published public artifacts"
    dependencies = [Depends(_rate_limit)] + ([Depends(validate_authentication)] if member else [])
    suffix = "member" if member else "public"

    def route(path: str, summary: str, name: str):
        return router.get(f"{prefix}{path}", summary=f"{summary} ({'members' if member else 'no auth'})",
                          description=f"xRegistry core API, read-only, over {scope} (MFX-34.2).",
                          responses=_RESPONSES, dependencies=dependencies, name=f"xregistry_{name}_{suffix}",
                          response_class=Response)

    @route("", "The xRegistry registry entity", "root")
    async def get_root(request: Request, tenant_slug: str, inline: Optional[str] = _INLINE) -> Response:
        """The registry: its attributes, each group collection's URL and count (``inline`` embeds all)."""
        return _serve(member, lambda v: _json(v.root(inline=inline is not None), member=member), request, tenant_slug)

    @route("/capabilities", "The xRegistry server capabilities", "capabilities")
    async def get_capabilities(request: Request, tenant_slug: str) -> Response:
        """What the façade supports: read-only, ``inline``, no pagination."""
        return _serve(member, lambda v: _json(v.capabilities(), member=member), request, tenant_slug)

    @route("/model", "The xRegistry model", "model")
    async def get_model(request: Request, tenant_slug: str) -> Response:
        """The two group types (schemagroups, messagegroups) and their resources."""
        return _serve(member, lambda v: _json(v.model(), member=member), request, tenant_slug)

    @route("/{groups}", "An xRegistry group collection", "groups")
    async def get_groups(request: Request, tenant_slug: str, groups: str, inline: Optional[str] = _INLINE) -> Response:
        """``schemagroups`` or ``messagegroups``: group id → group."""
        return _serve(member, lambda v: _json(v.groups(groups, inline=inline is not None), member=member),
                      request, tenant_slug)

    @route("/{groups}/{gid}", "An xRegistry group", "group")
    async def get_group(request: Request, tenant_slug: str, groups: str, gid: str,
                        inline: Optional[str] = _INLINE) -> Response:
        """One group, with its resource collection's URL and count."""
        return _serve(member, lambda v: _json(v.group(groups, gid, inline=inline is not None), member=member),
                      request, tenant_slug)

    @route("/{groups}/{gid}/{resources}", "An xRegistry resource collection", "resources")
    async def get_resources(request: Request, tenant_slug: str, groups: str, gid: str, resources: str) -> Response:
        """``schemas`` or ``messages``: resource id → its attributes."""
        return _serve(member, lambda v: _json(v.resources(groups, gid, resources), member=member),
                      request, tenant_slug)

    @route("/{groups}/{gid}/{resources}/{rid}", "An xRegistry resource (append $details for its attributes)",
           "resource")
    async def get_resource(request: Request, tenant_slug: str, groups: str, gid: str, resources: str,
                           rid: str) -> Response:
        """A schema's document (``xRegistry-*`` headers); a message's attributes; ``$details`` → attributes."""
        rid, details = split_details(rid)

        def render(view: XRegistryView) -> Response:
            if details or not _has_document(groups):
                return _json(view.details(groups, gid, resources, rid), member=member)
            document, headers = view.document(groups, gid, resources, rid)
            return _document(document, headers, member=member)

        return _serve(member, render, request, tenant_slug)

    @route("/{groups}/{gid}/{resources}/{rid}/versions", "An xRegistry resource's versions", "versions")
    async def get_versions(request: Request, tenant_slug: str, groups: str, gid: str, resources: str,
                           rid: str) -> Response:
        """Version id → version attributes (one version: the artifact's published one)."""
        return _serve(member, lambda v: _json(v.versions(groups, gid, resources, rid), member=member),
                      request, tenant_slug)

    @route("/{groups}/{gid}/{resources}/{rid}/versions/{vid}",
           "An xRegistry resource version (append $details for its attributes)", "version")
    async def get_version(request: Request, tenant_slug: str, groups: str, gid: str, resources: str, rid: str,
                          vid: str) -> Response:
        """A version's document, or its attributes (``$details``, or a message)."""
        vid, details = split_details(vid)

        def render(view: XRegistryView) -> Response:
            if details or not _has_document(groups):
                return _json(view.version_details(groups, gid, resources, rid, vid), member=member)
            document, headers = view.version_document(groups, gid, resources, rid, vid)
            return _document(document, headers, member=member)

        return _serve(member, render, request, tenant_slug)


def _has_document(groups: str) -> bool:
    """Whether the resources of a group collection have documents (schemas do, messages do not)."""
    return bool(GROUP_KINDS.get(groups, (None, None, None, False))[3])


_register(member=False)
_register(member=True)
