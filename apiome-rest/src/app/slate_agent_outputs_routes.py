"""APX-3.4 agent-output read API (#2459).

Serves the deterministic, machine-readable agent outputs for one **published** version
of a project — the ``llms.txt`` index, the catalog / format-capability manifest, the
release manifest, ``robots.txt`` and the versioned index that lists them. The heavy
lifting (and every determinism/privacy guarantee) lives in the pure
:mod:`app.slate_agent_outputs` generator; this module only resolves the project/version,
loads the approved canonical content, applies the portal policy and adds HTTP caching.

* ``GET /v1/versions/{tenant_slug}/{project_id}/{version_record_id}/agent-outputs``
  returns the JSON **index** by default, or one raw output when ``?output=`` selects
  ``llms.txt`` / ``robots.txt`` / ``catalog`` / ``release`` (served with that output's
  real media type).

Authentication matches the sibling changelog API (JWT or API key, tenant-scoped): the
URL ``tenant_slug`` is ignored and the token's ``tenant_id`` scopes every read, so a
cross-tenant id resolves to 404. Only published revisions are eligible (400 otherwise),
and the generator withholds all content for private / robots-excluded portals, so
private or unauthorized content is never emitted.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response

from .auth import validate_authentication
from .canonical_model import ApiIdentity, ApiParadigm, CanonicalApi
from .canonical_persistence import load_canonical_api
from .config import settings
from .database import db
from .revision_deprecation import is_uuid_string
from .slate_agent_outputs import (
    AGENT_OUTPUT_MEDIA_TYPES,
    ChangelogSummary,
    PortalContext,
    build_agent_outputs,
)

router = APIRouter(prefix="/v1/versions", tags=["agent-outputs"])

# Shorter than an immutable-content cache would allow, but the ETag makes repeat reads
# free (304) and lets a re-publish of a moving alias propagate promptly.
_AGENT_OUTPUT_MAX_AGE = 300

# Selectable raw outputs (``index`` is the default JSON envelope; ``None`` means index).
_SELECTABLE_OUTPUTS = ("index", "llms.txt", "robots.txt", "catalog", "release")


def _require_project(project_id: str, tenant_id: str) -> Dict[str, Any]:
    """Resolve a project by id within the token's tenant, or raise 400/404."""
    ref = (project_id or "").strip()
    if not is_uuid_string(ref):
        raise HTTPException(status_code=400, detail=f"Invalid project id: {project_id}")
    project = db.get_project_by_id(ref, tenant_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    return project


def _if_none_match_hit(if_none_match: Optional[str], etag: str) -> bool:
    """Return ``True`` when the client's ``If-None-Match`` already holds ``etag``.

    Tolerates the weak-validator ``W/`` prefix and the ``*`` wildcard, and a
    comma-separated list of candidate tags.
    """
    if not if_none_match:
        return False
    for candidate in if_none_match.split(","):
        token = candidate.strip()
        if token == "*":
            return True
        if token.startswith("W/"):
            token = token[2:].strip()
        if token == etag:
            return True
    return False


def _empty_canonical(project_name: str) -> CanonicalApi:
    """A minimal, empty canonical API for a published revision with no stored artifact.

    Keeps the outputs well-formed (an empty catalog) instead of failing when a published
    version has no persisted canonical content.
    """
    return CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="unknown",
        identity=ApiIdentity(name=project_name or "API"),
        title=project_name or None,
    )


def _changelog_summary(version_record_id: str, tenant_id: str, project_id: str) -> Optional[ChangelogSummary]:
    """Best-effort per-severity change counts for the revision (``None`` if unavailable)."""
    try:
        row = db.get_version_changelog(version_record_id, tenant_id, project_id)
    except Exception:  # pragma: no cover - defensive; changelog is a convenience link
        return None
    if not row:
        return None
    payload = row.get("changelog_json")
    counts = payload.get("counts") if isinstance(payload, dict) else None
    if not isinstance(counts, dict):
        return None

    def _count(key: str) -> int:
        try:
            return int(counts.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0

    return ChangelogSummary(
        breaking=_count("breaking"),
        non_breaking=_count("non-breaking"),
        docs_only=_count("docs-only"),
    )


@router.get(
    "/{tenant_slug}/{project_id}/{version_record_id}/agent-outputs",
    responses={
        304: {"description": "Not modified (ETag matched If-None-Match)."},
        400: {"description": "Malformed project id, unknown output, or unpublished revision."},
        404: {"description": "Project or version not found in tenant."},
    },
)
async def get_version_agent_outputs(
    tenant_slug: str,
    project_id: str,
    version_record_id: str,
    output: Optional[str] = Query(
        None,
        description=(
            "Which output to return: omit (or 'index') for the JSON index, or "
            "'llms.txt' / 'robots.txt' / 'catalog' / 'release' for one raw output."
        ),
    ),
    if_none_match: Optional[str] = Header(None, alias="If-None-Match"),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Response:
    """Return the deterministic agent outputs for one published revision.

    Resolves the project and version within the caller's tenant, requires the revision to
    be published, loads its approved canonical content, applies the portal's public/private
    policy, and renders the requested output with a content-addressed ``ETag`` and
    ``Cache-Control``. A matching ``If-None-Match`` short-circuits to ``304``.
    """
    _ = tenant_slug
    tenant_id = auth_data["tenant_id"]

    selected = (output or "index").strip()
    if selected not in _SELECTABLE_OUTPUTS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown output '{output}'; expected one of {', '.join(_SELECTABLE_OUTPUTS)}",
        )

    project = _require_project(project_id, tenant_id)

    if not is_uuid_string((version_record_id or "").strip()):
        raise HTTPException(status_code=404, detail=f"Version not found: {version_record_id}")
    version = db.get_version_by_id(version_record_id, tenant_id)
    if not version:
        raise HTTPException(status_code=404, detail=f"Version not found: {version_record_id}")
    if str(version.get("project_id")) != str(project["id"]):
        raise HTTPException(status_code=404, detail=f"Version not found in project: {project_id}")
    if not version.get("published"):
        raise HTTPException(
            status_code=400,
            detail="Agent outputs are only defined for published revisions",
        )

    project_slug = str(version.get("project_slug") or project.get("slug") or "")
    project_name = str(version.get("project_name") or project.get("name") or project_slug)
    visibility = str(version.get("visibility") or "private").lower()
    is_public = visibility == "public"

    published_at = version.get("published_at")
    published_at_iso = published_at.isoformat() if hasattr(published_at, "isoformat") else (
        str(published_at) if published_at else None
    )

    ctx = PortalContext(
        base_url=f"{settings.slate_portal_base_url.rstrip('/')}/{project_slug}",
        project_name=project_name,
        project_slug=project_slug,
        version_label=str(version.get("version_id") or ""),
        version_record_id=str(version["id"]),
        published_at=published_at_iso,
        indexable=is_public,  # published is already guaranteed above
        access="public" if is_public else "private",
    )

    canonical = load_canonical_api(db, tenant_id=tenant_id, version_id=str(version["id"]))
    if canonical is None:
        canonical = _empty_canonical(project_name)

    latest_label = db.get_latest_version_for_project(str(project["id"]), tenant_id)
    is_latest = bool(latest_label) and str(latest_label) == ctx.version_label

    changelog = _changelog_summary(str(version["id"]), tenant_id, str(project["id"]))

    bundle = build_agent_outputs(
        canonical,
        ctx,
        latest=is_latest,
        changelog=changelog,
    )

    chosen = bundle.get(selected)
    if chosen is None:  # pragma: no cover - selection is validated above
        raise HTTPException(status_code=400, detail=f"Unknown output '{output}'")

    headers = {"Cache-Control": f"private, max-age={_AGENT_OUTPUT_MAX_AGE}", "ETag": chosen.etag}
    if _if_none_match_hit(if_none_match, chosen.etag):
        return Response(status_code=304, headers=headers)
    return Response(
        content=chosen.body,
        media_type=AGENT_OUTPUT_MEDIA_TYPES[selected],
        headers=headers,
    )
