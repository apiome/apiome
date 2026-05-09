"""
Public browse directory endpoints (no authentication).

Mirrors the data surfaced by ``objectified-browse`` ``getPublicTenants`` and
``getDirectoryStats`` for CLI and API consumers.
"""

from __future__ import annotations

import re
from functools import cmp_to_key
from datetime import datetime
from typing import Any, Dict, List, Literal

from fastapi import APIRouter, Header, HTTPException, Query

from .auth import resolve_optional_tenant_member_auth
from .browse_change_summary import browse_version_changes_summary
from .database import db
from .models import (
    BrowseDirectoryStats,
    BrowsePublicProjectRow,
    BrowsePublicProjectsResponse,
    BrowsePublicTenantRow,
    BrowsePublicTenantsResponse,
    BrowsePublicVersionRow,
    BrowsePublicVersionsResponse,
)

router = APIRouter(prefix="/v1/browse", tags=["browse"])


_SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


def _parse_semver(version_slug: str) -> tuple[int, int, int, tuple[str, ...]] | None:
    s = (version_slug or "").strip().lstrip("vV")
    m = _SEMVER_RE.match(s)
    if not m:
        return None
    prerelease = tuple((m.group(4) or "").split(".")) if m.group(4) else ()
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), prerelease)


def _cmp_prerelease(a: tuple[str, ...], b: tuple[str, ...]) -> int:
    if not a and not b:
        return 0
    if not a:
        return 1
    if not b:
        return -1
    for ai, bi in zip(a, b):
        if ai == bi:
            continue
        ai_num = ai.isdigit()
        bi_num = bi.isdigit()
        if ai_num and bi_num:
            return 1 if int(ai) > int(bi) else -1
        if ai_num != bi_num:
            return -1 if ai_num else 1
        return 1 if ai > bi else -1
    if len(a) == len(b):
        return 0
    return 1 if len(a) > len(b) else -1


def _compare_version_slug_desc(a_slug: str, b_slug: str) -> int:
    a_parsed = _parse_semver(a_slug)
    b_parsed = _parse_semver(b_slug)
    if a_parsed and b_parsed:
        if a_parsed[:3] != b_parsed[:3]:
            return -1 if a_parsed[:3] > b_parsed[:3] else 1
        prerelease_cmp = _cmp_prerelease(a_parsed[3], b_parsed[3])
        if prerelease_cmp != 0:
            return -1 if prerelease_cmp > 0 else 1
        a_lower = a_slug.lower()
        b_lower = b_slug.lower()
        if a_lower == b_lower:
            return 0
        return -1 if a_lower > b_lower else 1
    if a_parsed and not b_parsed:
        return -1
    if b_parsed and not a_parsed:
        return 1
    a_lower = a_slug.lower()
    b_lower = b_slug.lower()
    if a_lower == b_lower:
        return 0
    return -1 if a_lower > b_lower else 1


def _sort_versions_semver_desc(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        rows,
        key=cmp_to_key(
            lambda a, b: _compare_version_slug_desc(
                str(a.get("version_id") or ""),
                str(b.get("version_id") or ""),
            )
        ),
    )


def _browse_project_domain_label(metadata: Any) -> str:
    """Human-facing domain/category cell (matches CLI ``domainDisplay`` semantics)."""
    if not metadata or not isinstance(metadata, dict):
        return "—"
    d_raw = metadata.get("domain")
    if isinstance(d_raw, str):
        d = d_raw.strip()
        if d:
            return d
    c_raw = metadata.get("domainCategory")
    if isinstance(c_raw, str):
        c = c_raw.strip()
        if c and c.lower() != "none":
            return c
    return "—"


@router.get("/tenants", response_model=BrowsePublicTenantsResponse)
async def list_public_browse_tenants(
    search: str | None = Query(
        None,
        description="Case-insensitive substring filter on tenant name and slug.",
    ),
    sort: Literal["latest", "name", "projects"] = Query(
        "name",
        description="Sort order: name (default), projects (desc), or latest activity (desc).",
    ),
) -> BrowsePublicTenantsResponse:
    stats = db.get_public_browse_directory_stats()
    rows = db.list_public_browse_tenants(search=search, sort=sort)
    tenants = [BrowsePublicTenantRow.model_validate(r) for r in rows]
    return BrowsePublicTenantsResponse(
        directory_stats=BrowseDirectoryStats.model_validate(stats),
        tenants=tenants,
        filtered_count=len(tenants),
    )


@router.get(
    "/tenants/{tenant_slug}/projects",
    response_model=BrowsePublicProjectsResponse,
    responses={
        401: {"description": "Missing or invalid authentication credentials"},
        403: {"description": "Authenticated user does not belong to this tenant"},
        404: {"description": "Tenant not found"},
    },
)
async def list_public_browse_projects(
    tenant_slug: str,
    search: str | None = Query(
        None,
        description="Case-insensitive substring filter on project slug and name.",
    ),
    domain: str | None = Query(
        None,
        description="Filter by project metadata domain or domainCategory (case-insensitive).",
    ),
    has_published: bool = Query(
        False,
        description="Only include projects with at least one published version (visibility rules apply).",
    ),
    authorization: str | None = Header(None),
    x_api_key: str | None = Header(None, alias="X-API-Key"),
) -> BrowsePublicProjectsResponse:
    tenant = db.get_tenant_row_by_slug(tenant_slug)
    if tenant is None:
        raise HTTPException(status_code=404, detail=f"Tenant not found: {tenant_slug}")

    is_member = resolve_optional_tenant_member_auth(
        tenant_slug,
        authorization=authorization,
        x_api_key=x_api_key,
    )
    tenant_id = tenant["id"]

    if is_member:
        raw_rows = db.list_member_browse_projects_for_tenant(
            tenant_id,
            search=search,
            domain=domain,
            require_published=has_published,
        )
    else:
        raw_rows = db.list_public_browse_projects_for_tenant(
            tenant_id,
            search=search,
            domain=domain,
            require_published=has_published,
        )

    projects = [
        BrowsePublicProjectRow(
            slug=row["slug"],
            name=row["name"],
            domain=_browse_project_domain_label(row.get("metadata")),
            published_versions=int(row["published_versions"] or 0),
            latest_version=row.get("latest_version"),
            latest_published_at=row.get("latest_published_at"),
        )
        for row in raw_rows
    ]

    return BrowsePublicProjectsResponse(
        tenant_slug=str(tenant["slug"]),
        tenant_name=str(tenant["name"]),
        projects=projects,
        filtered_count=len(projects),
    )


@router.get(
    "/tenants/{tenant_slug}/projects/{project_slug}/versions",
    response_model=BrowsePublicVersionsResponse,
    responses={
        401: {"description": "Missing or invalid authentication credentials"},
        403: {"description": "Authenticated user does not belong to this tenant"},
        404: {"description": "Tenant or project not found"},
    },
)
async def list_public_browse_versions(
    tenant_slug: str,
    project_slug: str,
    since: datetime | None = Query(
        None,
        description="Include only versions whose published_at is at or after this timestamp (ISO 8601).",
    ),
    authorization: str | None = Header(None),
    x_api_key: str | None = Header(None, alias="X-API-Key"),
) -> BrowsePublicVersionsResponse:
    tenant = db.get_tenant_row_by_slug(tenant_slug)
    if tenant is None:
        raise HTTPException(status_code=404, detail=f"Tenant not found: {tenant_slug}")

    is_member = resolve_optional_tenant_member_auth(
        tenant_slug,
        authorization=authorization,
        x_api_key=x_api_key,
    )
    tenant_id = tenant["id"]

    project = db.get_project_by_slug(project_slug, tenant_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_slug}")

    if not is_member:
        if not db.project_has_public_published_version(tenant_id, project_slug):
            raise HTTPException(status_code=404, detail=f"Project not found: {project_slug}")

    if is_member:
        raw_rows = db.list_member_browse_versions_for_project(tenant_id, project_slug, since=since)
    else:
        raw_rows = db.list_public_browse_versions_for_project(tenant_id, project_slug, since=since)

    rows_sorted = _sort_versions_semver_desc(raw_rows)

    versions_out: List[BrowsePublicVersionRow] = []
    for i, row in enumerate(rows_sorted):
        next_row = rows_sorted[i + 1] if i + 1 < len(rows_sorted) else None
        baseline_slug = str(next_row["version_id"]) if next_row else None

        tags_raw = row.get("tags") or []
        tags_list = [str(t) for t in tags_raw] if isinstance(tags_raw, list) else []

        desc = row.get("description")
        clog = row.get("change_log")
        summary = browse_version_changes_summary(
            change_model_json=row.get("change_model_json"),
            change_log=str(clog) if clog is not None else None,
            description=str(desc) if desc is not None else None,
            baseline_version_slug=baseline_slug,
        )

        versions_out.append(
            BrowsePublicVersionRow(
                id=str(row["id"]),
                version_id=str(row["version_id"]),
                published_at=row.get("published_at"),
                tags=tags_list,
                changes_summary=summary,
                description=str(desc) if desc is not None else None,
                change_log=str(clog) if clog is not None else None,
            )
        )

    return BrowsePublicVersionsResponse(
        tenant_slug=str(tenant["slug"]),
        tenant_name=str(tenant["name"]),
        project_slug=str(project["slug"]),
        project_name=str(project["name"]),
        versions=versions_out,
        filtered_count=len(versions_out),
    )
