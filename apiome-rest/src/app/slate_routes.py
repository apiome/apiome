"""Managed Slate hosting and deployment REST API — APX-3.1 (private-suite#2456).

The deployment control plane the Release Center (UXE-2.4) consumes:

* ``GET  /v1/slate/sites``
  — the tenant's managed sites with their environment lanes, optionally filtered by
  project. This is how the Release Center resolves a project to a site: it works in terms
  of a project and a version, not a site id.

* ``GET  /v1/slate/sites/{site_id}/releases``
  — the release timeline, newest first, optionally scoped to one environment. Each row
  carries everything blueprint §28.3 requires of it: status, environment, source
  commit/branch, artifact digest, actor, checks, created/active time, domains and traffic.

* ``GET  /v1/slate/releases/{release_id}``
  — one release with its full evidence: checks, phases, logs, changed pages, approvals,
  regions and append-only audit.

* ``POST /v1/slate/sites/{site_id}/releases``
  — record a built release. The artifact's signature is verified before the release is
  accepted, so unverifiable bytes never become routable.

* ``GET  /v1/slate/environments/{environment_id}``
  — lane state: active release, routing version, region rollout and the measured
  activation SLO.

* ``POST /v1/slate/environments/{environment_id}/promote``
  — route the lane to an already-built artifact. **Never rebuilds.** Every refusal is a
  named reason with an operator-facing sentence, and a refused promotion still writes an
  audit entry.

* ``POST /v1/slate/environments/{environment_id}/rollback``
  — route the lane back to the most recent retained artifact.

* ``POST /v1/slate/sites/{site_id}/retention``
  — run the retention sweep, reaping artifacts outside the site's rollback window.

Both mutating routes accept ``dryRun``, which runs every gate and returns the plan without
changing routing. That is what lets the Release Center show an accurate impact sheet before
an operator confirms, rather than describing an action it has not actually validated.

Authorization: reads require VERSIONS/VIEW; recording a release requires VERSIONS/EDIT;
promotion, rollback and retention require VERSIONS/PUBLISH. There is no separate
``deployments`` resource because publishing documentation to a production lane *is* a
publish action on the version being published, and inventing a permission dimension the
roles matrix does not render would leave it ungrantable in the UI.

Scope misses answer 404 (not 403) so cross-tenant probes cannot confirm that a site,
environment or release exists.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from .auth import get_authenticated_user_id, validate_authentication
from .config import settings
from .database import db
from .permissions import Action, Resource, enforce_permission
from .slate_artifacts import ArtifactDigests, SlateArtifactError, verify_signature
from .slate_deployment_store import (
    SlateActivationConflictError,
    activate,
    append_audit,
    find_rollback_target,
    get_environment,
    get_release,
    list_releases,
    list_sites,
    reap_artifacts,
    record_artifact,
)
from .slate_deployment_store import create_release as store_create_release
from .slate_releases import (
    SlateReleaseRefusedError,
    evaluate_region_rollout,
    measure_activation_slo,
    plan_promotion,
    plan_rollback,
    select_reapable_artifacts,
)

router = APIRouter(prefix="/v1/slate", tags=["slate"])


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


# ─── Request/response models ─────────────────────────────────────────────────


class ReleaseArtifactBody(_CamelModel):
    """The built, content-addressed artifact a release routes to."""

    digest: str = Field(description="Content digest; the artifact identity.")
    source_digest: Optional[str] = Field(
        default=None, description="Digest of the source inputs the build consumed."
    )
    config_digest: Optional[str] = Field(
        default=None, description="Digest of the build configuration applied."
    )
    page_count: int = Field(default=0, description="Rendered page count.")
    size_bytes: int = Field(default=0, description="Total artifact size in bytes.")
    built_at: Optional[str] = Field(
        default=None, description="When the build finished; absent while still building."
    )
    signature_verified: bool = Field(
        default=False,
        description="Whether the stored signature verifies against the stored digests.",
    )
    retained: bool = Field(
        default=True,
        description="False once retention has reaped the bytes; a reaped artifact is not a rollback target.",
    )


class ReleaseActorBody(_CamelModel):
    """Who or what caused the release to exist."""

    id: Optional[str] = Field(default=None, description="Acting user id, when a person acted.")
    name: str = Field(description="Display name of the actor.")
    kind: Literal["user", "automation"] = Field(
        description="Whether a person or a system acted."
    )


class ReleaseSourceBody(_CamelModel):
    """Where the release was built from."""

    commit: str = Field(description="Full commit sha.")
    ref: str = Field(description="Branch or tag the commit was taken from.")
    message: str = Field(description="First line of the commit message.")


class ReleaseBody(_CamelModel):
    """One immutable release, shaped to the Release Center's release record."""

    id: str
    release_ref: str
    environment: str
    environment_id: str
    status: str
    source: ReleaseSourceBody
    artifact: ReleaseArtifactBody
    actor: ReleaseActorBody
    created_at: str
    activated_at: Optional[str] = None
    activation_completed_at: Optional[str] = None
    deactivated_at: Optional[str] = None
    traffic: Optional[Dict[str, Any]] = None
    impact: Dict[str, Any] = Field(default_factory=dict)
    domains: List[Dict[str, Any]] = Field(default_factory=list)
    checks: List[Dict[str, Any]] = Field(default_factory=list)
    phases: List[Dict[str, Any]] = Field(default_factory=list)
    approvals: List[Dict[str, Any]] = Field(default_factory=list)
    changed_pages: List[Dict[str, Any]] = Field(default_factory=list)
    logs: List[Dict[str, Any]] = Field(default_factory=list)
    audit: List[Dict[str, Any]] = Field(default_factory=list)


class ReleaseListResponse(_CamelModel):
    """The release timeline."""

    releases: List[ReleaseBody]


class CreateReleaseRequest(_CamelModel):
    """Record a built release and its artifact."""

    environment_id: str = Field(description="Lane the release targets.")
    release_ref: str = Field(description="Short human-quotable id, unique per site.")
    source: ReleaseSourceBody
    content_digest: str = Field(description="Digest of the rendered bytes.")
    source_digest: str = Field(description="Digest of the source inputs.")
    config_digest: str = Field(description="Digest of the build configuration.")
    signature: str = Field(description="Detached signature over the three digests.")
    signature_key_id: str = Field(description="Id of the signing key.")
    storage_uri: str = Field(description="Where the artifact bytes live.")
    manifest: Dict[str, Any] = Field(default_factory=dict, description="Build manifest / SBOM.")
    page_count: int = Field(default=0, description="Rendered page count.")
    size_bytes: int = Field(default=0, description="Total artifact size in bytes.")
    status: Literal["ready", "review"] = Field(
        default="ready", description="Initial state of the built release."
    )
    impact: Dict[str, Any] = Field(
        default_factory=dict, description="Cache/security consequences of activation."
    )


class ActivationRequest(_CamelModel):
    """Promote or roll back a lane."""

    release_id: Optional[str] = Field(
        default=None,
        description="Release to promote. Ignored by rollback, which selects its own target.",
    )
    dry_run: bool = Field(
        default=False,
        description="Run every gate and return the plan without changing routing.",
    )
    require_approval: bool = Field(
        default=False, description="Enforce this lane's approval policy for the promotion."
    )


class ActivationResponse(_CamelModel):
    """Outcome of a promotion or rollback."""

    applied: bool
    dry_run: bool
    plan: Dict[str, Any]
    activation_id: Optional[str] = None
    routing_version: Optional[int] = None
    activated_at: Optional[str] = None


class EnvironmentResponse(_CamelModel):
    """Lane state: what is serving, how far it reached, and against what budget."""

    id: str
    site_id: str
    kind: str
    name: str
    active_release_id: Optional[str]
    routing_version: int
    robots_excluded: bool
    access_policy: str
    expires_at: Optional[str] = None
    rollout: Dict[str, Any] = Field(default_factory=dict)
    activation_slo: Dict[str, Any] = Field(default_factory=dict)
    domains: List[Dict[str, Any]] = Field(default_factory=list)


class SiteEnvironmentBody(_CamelModel):
    """One lane, as reported in the site inventory."""

    id: str
    kind: str
    name: str
    active_release_id: Optional[str] = None
    routing_version: int = 0
    robots_excluded: bool = False
    access_policy: str = "public"
    expires_at: Optional[str] = None


class SiteBody(_CamelModel):
    """A managed site and its lanes."""

    id: str
    project_id: str
    name: str
    slug: str
    retained_releases: int
    activation_slo_seconds: int
    environments: List[SiteEnvironmentBody] = Field(default_factory=list)


class SiteListResponse(_CamelModel):
    """The tenant's managed sites."""

    sites: List[SiteBody]


class RetentionResponse(_CamelModel):
    """Outcome of a retention sweep."""

    reaped: int
    reaped_release_ids: List[str]
    retained_releases: int


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _iso(value: Any) -> Optional[str]:
    """Render a timestamp as ISO-8601, or None."""
    return None if value is None else (
        value.isoformat() if hasattr(value, "isoformat") else str(value)
    )


def _artifact_signature_verified(row: Dict[str, Any]) -> bool:
    """Verify a release's stored artifact signature.

    A malformed digest is treated as unverified rather than raised: the caller's question is
    "may this be routed", and the answer for an artifact whose digests do not parse is no.

    Args:
        row: A release row joined to its artifact.

    Returns:
        True when the signature verifies against the stored digests.
    """
    if not row.get("artifact_digest") or not row.get("signature"):
        return False
    try:
        digests = ArtifactDigests(
            content=str(row["artifact_digest"]),
            source=str(row.get("source_digest") or ""),
            config=str(row.get("config_digest") or ""),
        )
    except SlateArtifactError:
        return False
    return verify_signature(
        digests,
        str(row["signature"]),
        key=settings.effective_slate_artifact_signing_key,
        key_id=str(row.get("signature_key_id") or ""),
    )


def _release_body(row: Dict[str, Any], *, evidence: Optional[Dict[str, Any]] = None) -> ReleaseBody:
    """Shape a stored release row into the Release Center's release record.

    Args:
        row: Release row joined to its artifact.
        evidence: Optional related collections (checks, phases, logs, audit, and so on).

    Returns:
        The wire-ready release body.
    """
    evidence = evidence or {}
    traffic = None
    if row.get("traffic_percent") is not None:
        traffic = {
            "percent": row.get("traffic_percent"),
            "requestsPerMinute": row.get("traffic_requests_per_min") or 0,
            "regions": evidence.get("regions", []),
        }

    return ReleaseBody(
        id=str(row["id"]),
        release_ref=str(row["release_ref"]),
        environment=str(row.get("environment_kind") or row.get("environment_name") or ""),
        environment_id=str(row["environment_id"]),
        status=str(row["status"]),
        source=ReleaseSourceBody(
            commit=str(row["source_commit"]),
            ref=str(row["source_ref"]),
            message=str(row["source_message"]),
        ),
        artifact=ReleaseArtifactBody(
            digest=str(row.get("artifact_digest") or ""),
            source_digest=row.get("source_digest"),
            config_digest=row.get("config_digest"),
            page_count=int(row.get("page_count") or 0),
            size_bytes=int(row.get("size_bytes") or 0),
            built_at=_iso(row.get("built_at")),
            signature_verified=_artifact_signature_verified(row),
            retained=row.get("artifact_reaped_at") is None,
        ),
        actor=ReleaseActorBody(
            id=str(row["actor_id"]) if row.get("actor_id") else None,
            name=str(row["actor_name"]),
            kind=str(row["actor_kind"]),  # type: ignore[arg-type]
        ),
        created_at=_iso(row["created_at"]) or "",
        activated_at=_iso(row.get("activated_at")),
        activation_completed_at=_iso(row.get("activation_completed_at")),
        deactivated_at=_iso(row.get("deactivated_at")),
        traffic=traffic,
        impact=row.get("impact") or {},
        domains=evidence.get("domains", []),
        checks=evidence.get("checks", []),
        phases=evidence.get("phases", []),
        approvals=evidence.get("approvals", []),
        changed_pages=evidence.get("changed_pages", []),
        logs=evidence.get("logs", []),
        audit=evidence.get("audit", []),
    )


def _require_environment(tenant_id: str, environment_id: str) -> Dict[str, Any]:
    """Load an environment or answer 404.

    Args:
        tenant_id: Caller's tenant.
        environment_id: The lane.

    Returns:
        The environment row.

    Raises:
        HTTPException: 404 when the lane does not exist in this tenant. Deliberately not
            403: a cross-tenant probe must not be able to confirm the lane exists.
    """
    environment = get_environment(db, tenant_id=tenant_id, environment_id=environment_id)
    if not environment:
        raise HTTPException(
            status_code=404,
            detail={"code": "environment_not_found", "message": "Environment not found."},
        )
    return environment


def _refusal_http(error: SlateReleaseRefusedError) -> HTTPException:
    """Map a routing refusal to a 409 carrying its named reason and sentence."""
    return HTTPException(
        status_code=409,
        detail={
            "code": error.refusal.reason,
            "message": error.refusal.sentence,
            "reason": error.refusal.reason,
        },
    )


def _region_rows(tenant_id: str, release_id: Optional[str]) -> List[Dict[str, Any]]:
    """Load per-region activation rows for a release, or an empty list."""
    if not release_id:
        return []
    conn = db.connect()
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT region_id, label, status, reported_at
              FROM apiome.slate_release_regions
             WHERE release_id = %s::uuid
             ORDER BY label
            """,
            (release_id,),
        )
        return [dict(row) for row in (cursor.fetchall() or [])]


def _release_evidence(release_id: str) -> Dict[str, Any]:
    """Load every evidence collection attached to a release.

    Args:
        release_id: The release.

    Returns:
        A mapping of evidence collections keyed for :func:`_release_body`.
    """
    conn = db.connect()
    with conn.cursor() as cursor:

        def rows(query: str) -> List[Dict[str, Any]]:
            cursor.execute(query, (release_id,))
            return [dict(row) for row in (cursor.fetchall() or [])]

        return {
            "checks": rows(
                "SELECT check_key, label, status, detail FROM apiome.slate_release_checks "
                "WHERE release_id = %s::uuid ORDER BY ordinal, check_key"
            ),
            "phases": rows(
                "SELECT phase_key, label, status, started_at, completed_at "
                "FROM apiome.slate_release_phases WHERE release_id = %s::uuid "
                "ORDER BY ordinal, phase_key"
            ),
            "logs": rows(
                "SELECT at, phase_key, level, message FROM apiome.slate_release_logs "
                "WHERE release_id = %s::uuid ORDER BY id"
            ),
            "approvals": rows(
                "SELECT id, actor_name, actor_kind, approved_at, digest "
                "FROM apiome.slate_release_approvals WHERE release_id = %s::uuid "
                "ORDER BY approved_at DESC"
            ),
            "changed_pages": rows(
                "SELECT path_id, route, kind, before_text, after_text "
                "FROM apiome.slate_release_changed_pages WHERE release_id = %s::uuid "
                "ORDER BY route"
            ),
            "audit": rows(
                "SELECT id, at, actor_name, actor_kind, summary, detail "
                "FROM apiome.slate_release_audit WHERE release_id = %s::uuid ORDER BY at DESC"
            ),
            "regions": rows(
                "SELECT region_id, label, status FROM apiome.slate_release_regions "
                "WHERE release_id = %s::uuid ORDER BY label"
            ),
        }


def _environment_domains(environment_id: str) -> List[Dict[str, Any]]:
    """Load the domain inventory for a lane."""
    conn = db.connect()
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT host, is_primary, tls_status, verification_status,
                   certificate_issuer, certificate_expires_at
              FROM apiome.slate_domains
             WHERE environment_id = %s::uuid
             ORDER BY is_primary DESC, host
            """,
            (environment_id,),
        )
        return [dict(row) for row in (cursor.fetchall() or [])]


# ─── Routes ──────────────────────────────────────────────────────────────────


@router.get("/sites", response_model=SiteListResponse, response_model_by_alias=True)
async def list_managed_sites(
    project_id: Optional[str] = Query(
        default=None, alias="projectId", description="Restrict to one project's sites."
    ),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> SiteListResponse:
    """List the tenant's managed sites with their environment lanes.

    This is how the Release Center resolves a project to a site and its lanes; it works in
    terms of a project and a version, not a site id. An empty list is a legitimate answer
    meaning "this project is not hosted", which is different from an error.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = auth_data["tenant_id"]
    sites = list_sites(db, tenant_id=tenant_id, project_id=project_id)

    return SiteListResponse(
        sites=[
            SiteBody(
                id=str(site["id"]),
                project_id=str(site["project_id"]),
                name=str(site["name"]),
                slug=str(site["slug"]),
                retained_releases=int(site.get("retained_releases") or 10),
                activation_slo_seconds=int(site.get("activation_slo_seconds") or 300),
                environments=[
                    SiteEnvironmentBody(
                        id=str(env["id"]),
                        kind=str(env["kind"]),
                        name=str(env["name"]),
                        active_release_id=(
                            str(env["active_release_id"])
                            if env.get("active_release_id")
                            else None
                        ),
                        routing_version=int(env.get("routing_version") or 0),
                        robots_excluded=bool(env.get("robots_excluded")),
                        access_policy=str(env.get("access_policy") or "public"),
                        expires_at=_iso(env.get("expires_at")),
                    )
                    for env in site.get("environments", [])
                ],
            )
            for site in sites
        ]
    )


@router.get(
    "/sites/{site_id}/releases",
    response_model=ReleaseListResponse,
    response_model_by_alias=True,
)
async def list_site_releases(
    site_id: str,
    environment_id: Optional[str] = Query(
        default=None,
        alias="environmentId",
        description="Restrict the timeline to one environment.",
    ),
    limit: int = Query(default=50, ge=1, le=200, description="Maximum releases to return."),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ReleaseListResponse:
    """List a site's release timeline, newest first."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = auth_data["tenant_id"]
    rows = list_releases(
        db,
        tenant_id=tenant_id,
        site_id=site_id,
        environment_id=environment_id,
        limit=limit,
    )
    return ReleaseListResponse(releases=[_release_body(row) for row in rows])


@router.get(
    "/releases/{release_id}", response_model=ReleaseBody, response_model_by_alias=True
)
async def get_release_detail(
    release_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ReleaseBody:
    """Load one release with its full evidence."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = auth_data["tenant_id"]
    row = get_release(db, tenant_id=tenant_id, release_id=release_id)
    if not row:
        raise HTTPException(
            status_code=404,
            detail={"code": "release_not_found", "message": "Release not found."},
        )
    return _release_body(row, evidence=_release_evidence(release_id))


@router.post(
    "/sites/{site_id}/releases",
    response_model=ReleaseBody,
    response_model_by_alias=True,
    status_code=201,
)
async def create_site_release(
    site_id: str,
    request: CreateReleaseRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ReleaseBody:
    """Record a built release, refusing an artifact whose signature does not verify.

    Verification happens at *record* time as well as at activation. Storing an
    unverifiable artifact and only discovering it during an incident promotion would put
    the discovery at the worst possible moment.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.EDIT)
    tenant_id = auth_data["tenant_id"]
    actor_id = get_authenticated_user_id(auth_data)

    try:
        digests = ArtifactDigests(
            content=request.content_digest,
            source=request.source_digest,
            config=request.config_digest,
        )
    except SlateArtifactError as exc:
        raise HTTPException(
            status_code=422, detail={"code": exc.code, "message": str(exc)}
        ) from exc

    if not verify_signature(
        digests,
        request.signature,
        key=settings.effective_slate_artifact_signing_key,
        key_id=request.signature_key_id,
    ):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "signature_invalid",
                "message": (
                    "The artifact signature does not verify against its digests, so the "
                    "release is refused. The bytes do not match what the build signed."
                ),
            },
        )

    environment = _require_environment(tenant_id, request.environment_id)

    artifact = record_artifact(
        db,
        tenant_id=tenant_id,
        site_id=site_id,
        content_digest=request.content_digest,
        source_digest=request.source_digest,
        config_digest=request.config_digest,
        signature=request.signature,
        signature_key_id=request.signature_key_id,
        manifest=request.manifest,
        page_count=request.page_count,
        size_bytes=request.size_bytes,
        storage_uri=request.storage_uri,
    )

    release = store_create_release(
        db,
        tenant_id=tenant_id,
        site_id=site_id,
        environment_id=str(environment["id"]),
        release_ref=request.release_ref,
        source_commit=request.source.commit,
        source_ref=request.source.ref,
        source_message=request.source.message,
        actor_id=actor_id,
        actor_name=str(auth_data.get("email") or auth_data.get("name") or "Unknown"),
        actor_kind="user" if actor_id else "automation",
        artifact_id=str(artifact["id"]),
        status=request.status,
        impact=request.impact,
    )

    stored = get_release(db, tenant_id=tenant_id, release_id=str(release["id"]))
    return _release_body(stored or release)


@router.get(
    "/environments/{environment_id}",
    response_model=EnvironmentResponse,
    response_model_by_alias=True,
)
async def get_environment_state(
    environment_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> EnvironmentResponse:
    """Report what a lane is serving, how far it reached, and against what budget."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = auth_data["tenant_id"]
    environment = _require_environment(tenant_id, environment_id)

    active_id = environment.get("active_release_id")
    regions = _region_rows(tenant_id, str(active_id) if active_id else None)
    rollout = evaluate_region_rollout(regions)

    active = (
        get_release(db, tenant_id=tenant_id, release_id=str(active_id)) if active_id else None
    )
    slo = measure_activation_slo(
        started_at=active.get("activated_at") if active else None,
        completed_at=active.get("activation_completed_at") if active else None,
        budget_seconds=int(environment.get("activation_slo_seconds") or 300),
    )

    return EnvironmentResponse(
        id=str(environment["id"]),
        site_id=str(environment["site_id"]),
        kind=str(environment["kind"]),
        name=str(environment["name"]),
        active_release_id=str(active_id) if active_id else None,
        routing_version=int(environment.get("routing_version") or 0),
        robots_excluded=bool(environment.get("robots_excluded")),
        access_policy=str(environment.get("access_policy") or "public"),
        expires_at=_iso(environment.get("expires_at")),
        rollout={
            "state": rollout.state,
            "total": rollout.total,
            "active": rollout.active,
            "activating": rollout.activating,
            "failed": rollout.failed,
            "outstanding": list(rollout.outstanding),
        },
        activation_slo=slo,
        domains=_environment_domains(environment_id),
    )


def _run_activation(
    *,
    tenant_id: str,
    auth_data: Dict[str, Any],
    environment: Dict[str, Any],
    plan: Any,
    dry_run: bool,
) -> ActivationResponse:
    """Apply an activation plan, or return it unapplied for a dry run.

    Shared by promote and rollback so the two cannot drift in how they record outcomes.

    Args:
        tenant_id: Owning tenant.
        auth_data: Authenticated caller.
        environment: The lane.
        plan: The validated activation plan.
        dry_run: When true, nothing is written and the plan is returned as-is.

    Returns:
        The activation outcome.

    Raises:
        HTTPException: 409 when another activation won the routing race.
    """
    if dry_run:
        return ActivationResponse(applied=False, dry_run=True, plan=plan.as_dict())

    actor_id = get_authenticated_user_id(auth_data)
    actor_name = str(auth_data.get("email") or auth_data.get("name") or "Unknown")
    try:
        result = activate(
            db,
            plan,
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_kind="user" if actor_id else "automation",
        )
    except SlateActivationConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "concurrent-activation",
                "reason": "concurrent-activation",
                "message": str(exc),
                "expectedRoutingVersion": exc.expected_routing_version,
                "actualRoutingVersion": exc.actual_routing_version,
            },
        ) from exc

    return ActivationResponse(
        applied=True,
        dry_run=False,
        plan=plan.as_dict(),
        activation_id=result.get("activationId"),
        routing_version=result.get("routingVersion"),
        activated_at=_iso(result.get("activatedAt")),
    )


@router.post(
    "/environments/{environment_id}/promote",
    response_model=ActivationResponse,
    response_model_by_alias=True,
)
async def promote_release(
    environment_id: str,
    request: ActivationRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ActivationResponse:
    """Route a lane to an already-built artifact. Never rebuilds.

    A refused promotion still records an audit entry naming the reason, so an operator can
    later see what was attempted and why it was stopped.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    tenant_id = auth_data["tenant_id"]
    environment = _require_environment(tenant_id, environment_id)

    if not request.release_id:
        raise HTTPException(
            status_code=422,
            detail={"code": "release_required", "message": "releaseId is required to promote."},
        )

    release = get_release(db, tenant_id=tenant_id, release_id=request.release_id)
    if not release:
        raise HTTPException(
            status_code=404,
            detail={"code": "release_not_found", "message": "Release not found."},
        )

    release = {**release, "signature_verified": _artifact_signature_verified(release)}
    evidence = _release_evidence(str(release["id"]))
    active_id = environment.get("active_release_id")

    try:
        plan = plan_promotion(
            release=release,
            environment=environment,
            approvals=evidence["approvals"],
            active_regions=_region_rows(tenant_id, str(active_id) if active_id else None),
            require_approval=request.require_approval,
        )
    except SlateReleaseRefusedError as exc:
        if not request.dry_run:
            append_audit(
                db,
                tenant_id=tenant_id,
                release_id=str(release["id"]),
                actor_id=get_authenticated_user_id(auth_data),
                actor_name=str(auth_data.get("email") or "Unknown"),
                actor_kind="user",
                summary="Promotion refused",
                detail=f"{exc.refusal.reason}: {exc.refusal.sentence}",
            )
        raise _refusal_http(exc) from exc

    return _run_activation(
        tenant_id=tenant_id,
        auth_data=auth_data,
        environment=environment,
        plan=plan,
        dry_run=request.dry_run,
    )


@router.post(
    "/environments/{environment_id}/rollback",
    response_model=ActivationResponse,
    response_model_by_alias=True,
)
async def rollback_environment(
    environment_id: str,
    request: ActivationRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ActivationResponse:
    """Route a lane back to its most recent retained artifact.

    Deliberately does not consult approval freshness: requiring fresh sign-off to *stop*
    serving a bad release would make the approval policy an outage amplifier.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    tenant_id = auth_data["tenant_id"]
    environment = _require_environment(tenant_id, environment_id)

    target = find_rollback_target(db, tenant_id=tenant_id, environment_id=environment_id)
    if target is not None:
        target = {**target, "signature_verified": _artifact_signature_verified(target)}

    try:
        plan = plan_rollback(environment=environment, target=target)
    except SlateReleaseRefusedError as exc:
        active_id = environment.get("active_release_id")
        if not request.dry_run and active_id:
            append_audit(
                db,
                tenant_id=tenant_id,
                release_id=str(active_id),
                actor_id=get_authenticated_user_id(auth_data),
                actor_name=str(auth_data.get("email") or "Unknown"),
                actor_kind="user",
                summary="Rollback refused",
                detail=f"{exc.refusal.reason}: {exc.refusal.sentence}",
            )
        raise _refusal_http(exc) from exc

    return _run_activation(
        tenant_id=tenant_id,
        auth_data=auth_data,
        environment=environment,
        plan=plan,
        dry_run=request.dry_run,
    )


@router.post(
    "/sites/{site_id}/retention",
    response_model=RetentionResponse,
    response_model_by_alias=True,
)
async def run_retention(
    site_id: str,
    environment_id: str = Query(
        alias="environmentId", description="Environment whose history to sweep."
    ),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RetentionResponse:
    """Reap artifacts that have fallen outside the site's rollback window.

    Retention and rollback capability are the same setting, so the sweep is deliberately
    conservative: the active release is never reaped, and only releases that once served
    are candidates.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    tenant_id = auth_data["tenant_id"]
    environment = _require_environment(tenant_id, environment_id)

    releases = list_releases(
        db, tenant_id=tenant_id, site_id=site_id, environment_id=environment_id, limit=200
    )
    retained = int(environment.get("retained_releases") or 10)
    active_id = environment.get("active_release_id")
    reapable = select_reapable_artifacts(
        releases,
        retained_releases=retained,
        active_release_id=str(active_id) if active_id else None,
    )
    reaped = reap_artifacts(db, tenant_id=tenant_id, release_ids=reapable)

    return RetentionResponse(
        reaped=reaped, reaped_release_ids=reapable, retained_releases=retained
    )
