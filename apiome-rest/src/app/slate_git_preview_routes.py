"""Git-triggered immutable preview builds and provider status — APX-3.3 (private-suite#2458).

The REST surface that turns a signed provider event into an immutable preview and records the
status a provider check would carry. It sits alongside the other ``/v1/slate`` routers and shares
their posture: reads require VERSIONS/VIEW, mutations require VERSIONS/PUBLISH, and a scope miss
answers 404 (not 403) so a cross-tenant probe cannot confirm a resource exists.

Endpoints:

* ``POST /v1/slate/git/connections`` (PUBLISH) — register a repository connection. The webhook
  secret and repository token are write-only: sealed at rest and never returned.
* ``GET  /v1/slate/git/connections`` (VIEW) — the tenant's connections, without their secrets.
* ``POST /v1/slate/git/events`` — the **webhook receiver**. It carries no tenant credential;
  instead it resolves the connection from the payload's repository, verifies the
  ``X-Hub-Signature-256`` header against the **raw** body, and creates exactly one preview per
  source digest. A redelivered event is a no-op; a bad signature is 401; a non-buildable event
  (a tag, a branch deletion, a ping) is accepted and ignored.
* ``GET  /v1/slate/git/previews`` / ``/{build_id}`` (VIEW) — previews with their changed-page
  links, expiry/access state and provider-status payload.
* ``POST /v1/slate/git/previews/{build_id}/checks`` (PUBLISH) — record a check outcome; a pass
  advances the branch alias.
* ``POST /v1/slate/git/previews/{build_id}/retry`` (PUBLISH) — request a build retry (audited).
* ``POST /v1/slate/git/connections/{id}/cleanup`` (PUBLISH) — reap expired previews (audited).

The honesty boundary of V191 is carried through to the wire: every preview reports
``buildDispatched: false`` and every status ``statusDispatched: false``, each with the reason
naming the tier that is not yet attached.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from .config import settings
from .database import db
from .permissions import Action, Resource, enforce_permission
from .push_webhook_crypto import decrypt_signing_secret
from .slate_auth import validate_slate_authentication
from .slate_git_preview import (
    SlatePreviewEventError,
    describe_provider_status,
    parse_push_event,
    verify_github_signature,
)
from .slate_git_preview_store import (
    SlatePreviewStoreError,
    find_connections_by_repo,
    get_connection,
    get_preview,
    ingest_preview_event,
    list_connections,
    list_previews,
    reap_expired_previews,
    record_checks,
    retry_build,
    upsert_connection,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/slate", tags=["slate-git-preview"])


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


# ─── Request/response models ─────────────────────────────────────────────────


class CreateConnectionRequest(_CamelModel):
    """Register (or update) a git provider connection for a site."""

    site_id: str = Field(description="Site the connection builds previews for.")
    repo_owner: str = Field(description="Repository owner (organisation or user).")
    repo_name: str = Field(description="Repository name.")
    provider: Literal["github"] = Field(default="github", description="Git provider.")
    default_branch: str = Field(default="main", description="The repository's default branch.")
    preview_host: str = Field(
        description="Base host the immutable and alias preview URLs are derived from."
    )
    webhook_secret: Optional[str] = Field(
        default=None,
        description="Webhook signing secret. Write-only: sealed at rest and never returned.",
    )
    token: Optional[str] = Field(
        default=None,
        description="Repository token. Write-only: envelope-sealed at rest and never returned.",
    )


class ConnectionBody(_CamelModel):
    """A git provider connection, without its secret or token."""

    id: str
    site_id: str
    provider: str
    repo_owner: str
    repo_name: str
    repo_full_name: str
    default_branch: str
    preview_host: str
    has_webhook_secret: bool
    has_token: bool
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ConnectionListResponse(_CamelModel):
    connections: List[ConnectionBody]


class ChangedPageBody(_CamelModel):
    route: str
    kind: str
    link_url: str
    path_id: Optional[str] = None
    source_path: Optional[str] = None


class PreviewBody(_CamelModel):
    """One immutable preview and its provider-status payload."""

    id: str
    connection_id: str
    site_id: str
    environment_id: Optional[str] = None
    source_commit: str
    source_ref: str
    source_message: str
    source_digest: str
    status: str
    checks_state: str
    immutable_url: str
    alias_url: Optional[str] = None
    access_policy: str
    robots_excluded: bool
    build_dispatched: bool
    retry_count: int
    expires_at: Optional[str] = None
    created_at: Optional[str] = None
    changed_pages: List[ChangedPageBody] = Field(default_factory=list)
    provider_status: Dict[str, Any] = Field(default_factory=dict)


class PreviewListResponse(_CamelModel):
    previews: List[PreviewBody]


class EventReceiptResponse(_CamelModel):
    """The outcome of a webhook delivery."""

    accepted: bool
    ignored: bool = False
    reason: Optional[str] = None
    created: bool = False
    preview: Optional[PreviewBody] = None


class RecordChecksRequest(_CamelModel):
    """Record the outcome of the checks a preview must pass before its alias advances."""

    passed: bool = Field(description="Whether the checks passed.")
    failure_evidence: Optional[Dict[str, Any]] = Field(
        default=None, description="Evidence surfaced in the provider status on failure."
    )


class CleanupResponse(_CamelModel):
    reaped: int


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _preview_body(build: Dict[str, Any]) -> PreviewBody:
    """Shape a preview row (with its changed pages and alias) into the wire model."""
    changed = build.get("changed_pages") or []
    alias_url = build.get("alias_url")
    status_payload = describe_provider_status(
        build=build, changed_pages=changed, alias_url=alias_url
    )
    return PreviewBody(
        id=str(build["id"]),
        connection_id=str(build["connection_id"]),
        site_id=str(build["site_id"]),
        environment_id=(str(build["environment_id"]) if build.get("environment_id") else None),
        source_commit=str(build["source_commit"]),
        source_ref=str(build["source_ref"]),
        source_message=str(build.get("source_message") or ""),
        source_digest=str(build["source_digest"]),
        status=str(build["status"]),
        checks_state=str(build["checks_state"]),
        immutable_url=str(build["immutable_url"]),
        alias_url=(str(alias_url) if alias_url else None),
        access_policy=str(build["access_policy"]),
        robots_excluded=bool(build["robots_excluded"]),
        build_dispatched=bool(build["build_dispatched"]),
        retry_count=int(build.get("retry_count") or 0),
        expires_at=_iso(build.get("expires_at")),
        created_at=_iso(build.get("created_at")),
        changed_pages=[
            ChangedPageBody(
                route=str(page["route"]),
                kind=str(page["kind"]),
                link_url=str(page["link_url"]),
                path_id=(str(page["path_id"]) if page.get("path_id") else None),
                source_path=(str(page["source_path"]) if page.get("source_path") else None),
            )
            for page in changed
        ],
        provider_status=status_payload,
    )


def _connection_body(row: Dict[str, Any]) -> ConnectionBody:
    return ConnectionBody(
        id=str(row["id"]),
        site_id=str(row["site_id"]),
        provider=str(row["provider"]),
        repo_owner=str(row["repo_owner"]),
        repo_name=str(row["repo_name"]),
        repo_full_name=str(row["repo_full_name"]),
        default_branch=str(row["default_branch"]),
        preview_host=str(row["preview_host"]),
        has_webhook_secret=bool(row.get("has_webhook_secret")),
        has_token=bool(row.get("has_token")),
        created_at=_iso(row.get("created_at")),
        updated_at=_iso(row.get("updated_at")),
    )


# ─── Connection routes ───────────────────────────────────────────────────────


@router.post(
    "/git/connections",
    response_model=ConnectionBody,
    response_model_by_alias=True,
    status_code=201,
)
async def create_git_connection(
    request: CreateConnectionRequest,
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> ConnectionBody:
    """Register or update a git provider connection. Secret and token are write-only."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    tenant_id = auth_data["tenant_id"]
    row = upsert_connection(
        db,
        tenant_id=tenant_id,
        site_id=request.site_id,
        repo_owner=request.repo_owner,
        repo_name=request.repo_name,
        default_branch=request.default_branch,
        preview_host=request.preview_host,
        webhook_secret=request.webhook_secret,
        token=request.token,
        provider=request.provider,
    )
    return _connection_body(row)


@router.get(
    "/git/connections",
    response_model=ConnectionListResponse,
    response_model_by_alias=True,
)
async def list_git_connections(
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> ConnectionListResponse:
    """List the tenant's git provider connections, without their secrets."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = auth_data["tenant_id"]
    rows = list_connections(db, tenant_id=tenant_id)
    return ConnectionListResponse(connections=[_connection_body(r) for r in rows])


@router.post(
    "/git/connections/{connection_id}/cleanup",
    response_model=CleanupResponse,
    response_model_by_alias=True,
)
async def cleanup_previews(
    connection_id: str,
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> CleanupResponse:
    """Reap the tenant's expired previews (audited)."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    tenant_id = auth_data["tenant_id"]
    if not get_connection(db, tenant_id=tenant_id, connection_id=connection_id):
        raise HTTPException(
            status_code=404,
            detail={"code": "connection_not_found", "message": "Connection not found."},
        )
    reaped = reap_expired_previews(db, tenant_id=tenant_id)
    return CleanupResponse(reaped=reaped)


# ─── Webhook receiver (signature-verified, no tenant credential) ──────────────


@router.post("/git/events", response_model=EventReceiptResponse, response_model_by_alias=True)
async def receive_git_event(
    request: Request,
    x_github_event: Optional[str] = Header(default=None, alias="X-GitHub-Event"),
    x_github_delivery: Optional[str] = Header(default=None, alias="X-GitHub-Delivery"),
    x_hub_signature_256: Optional[str] = Header(default=None, alias="X-Hub-Signature-256"),
) -> EventReceiptResponse:
    """Receive a signed GitHub webhook and create one immutable preview per source digest.

    The signature is verified over the **raw** request body — never a re-serialisation of the
    parsed JSON — against the resolved connection's secret. A ping is answered, a non-push event
    or a non-buildable push is accepted and ignored, a bad signature is 401, and a genuine branch
    push idempotently yields a preview.
    """
    raw = await request.body()

    # A GitHub "ping" confirms the webhook is wired up; there is nothing to build.
    if x_github_event == "ping":
        return EventReceiptResponse(accepted=True, ignored=True, reason="ping acknowledged")
    if x_github_event and x_github_event != "push":
        return EventReceiptResponse(
            accepted=True, ignored=True, reason=f"event {x_github_event!r} is not a push"
        )

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(
            status_code=400,
            detail={"code": "malformed_payload", "message": "Body is not valid JSON."},
        )
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=400,
            detail={"code": "malformed_payload", "message": "Body is not a JSON object."},
        )

    repo_full_name = ((payload.get("repository") or {}).get("full_name") or "").lower()
    if not repo_full_name:
        raise HTTPException(
            status_code=400,
            detail={"code": "missing_repository", "message": "No repository in payload."},
        )

    connections = find_connections_by_repo(
        db, provider="github", repo_full_name=repo_full_name
    )
    if not connections:
        # Not an error: this repository simply has no preview connection here. Ignoring rather
        # than 404-ing avoids leaking which repositories are connected and stops GitHub retrying.
        return EventReceiptResponse(
            accepted=True, ignored=True, reason="no connection for this repository"
        )

    # Verify the signature against each connection's secret; the first that verifies owns the
    # event. A connection whose secret cannot be recovered (no encryption key) never verifies.
    connection: Optional[Dict[str, Any]] = None
    for candidate in connections:
        blob = candidate.get("webhook_secret_enc")
        secret = decrypt_signing_secret(bytes(blob)) if blob else None
        if verify_github_signature(secret, raw, x_hub_signature_256):
            connection = candidate
            break
    if connection is None:
        raise HTTPException(
            status_code=401,
            detail={
                "code": "signature_invalid",
                "message": "X-Hub-Signature-256 did not verify against any connection secret.",
            },
        )

    try:
        event = parse_push_event(payload)
    except SlatePreviewEventError as exc:
        if exc.code in ("not_a_branch", "branch_deleted"):
            # A tag push or a branch deletion is legitimate but not something to preview.
            return EventReceiptResponse(accepted=True, ignored=True, reason=str(exc))
        raise HTTPException(
            status_code=400, detail={"code": exc.code, "message": str(exc)}
        )

    build, created = ingest_preview_event(
        db,
        connection,
        event,
        delivery_id=x_github_delivery,
        ttl_hours=settings.slate_preview_default_ttl_hours,
    )
    full = get_preview(db, tenant_id=str(connection["tenant_id"]), build_id=str(build["id"]))
    return EventReceiptResponse(
        accepted=True,
        created=created,
        preview=_preview_body(full or build),
    )


# ─── Preview routes ──────────────────────────────────────────────────────────


@router.get(
    "/git/previews",
    response_model=PreviewListResponse,
    response_model_by_alias=True,
)
async def list_git_previews(
    connection_id: Optional[str] = Query(
        default=None, alias="connectionId", description="Restrict to one connection's previews."
    ),
    limit: int = Query(default=50, ge=1, le=200, description="Maximum previews to return."),
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> PreviewListResponse:
    """List the tenant's previews, newest first."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = auth_data["tenant_id"]
    rows = list_previews(db, tenant_id=tenant_id, connection_id=connection_id, limit=limit)
    return PreviewListResponse(previews=[_preview_body(r) for r in rows])


@router.get(
    "/git/previews/{build_id}",
    response_model=PreviewBody,
    response_model_by_alias=True,
)
async def get_git_preview(
    build_id: str,
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> PreviewBody:
    """Load one preview with its changed-page links, expiry/access and provider-status payload."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = auth_data["tenant_id"]
    build = get_preview(db, tenant_id=tenant_id, build_id=build_id)
    if not build:
        raise HTTPException(
            status_code=404,
            detail={"code": "preview_not_found", "message": "Preview not found."},
        )
    return _preview_body(build)


@router.post(
    "/git/previews/{build_id}/checks",
    response_model=PreviewBody,
    response_model_by_alias=True,
)
async def record_preview_checks(
    build_id: str,
    request: RecordChecksRequest,
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> PreviewBody:
    """Record a check outcome; a pass advances the branch alias to this preview."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    tenant_id = auth_data["tenant_id"]
    actor_name = str(auth_data.get("email") or auth_data.get("user_id") or "checks")
    try:
        build = record_checks(
            db,
            tenant_id=tenant_id,
            build_id=build_id,
            passed=request.passed,
            failure_evidence=request.failure_evidence,
            actor_name=actor_name,
        )
    except SlatePreviewStoreError as exc:
        raise HTTPException(status_code=404, detail={"code": exc.code, "message": str(exc)})
    return _preview_body(build)


@router.post(
    "/git/previews/{build_id}/retry",
    response_model=PreviewBody,
    response_model_by_alias=True,
)
async def retry_preview_build(
    build_id: str,
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> PreviewBody:
    """Request a build retry (audited). No worker runs yet, so the honest boundary is unchanged."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    tenant_id = auth_data["tenant_id"]
    actor_name = str(auth_data.get("email") or auth_data.get("user_id") or "user")
    try:
        retry_build(db, tenant_id=tenant_id, build_id=build_id, actor_name=actor_name)
    except SlatePreviewStoreError as exc:
        raise HTTPException(status_code=404, detail={"code": exc.code, "message": str(exc)})
    build = get_preview(db, tenant_id=tenant_id, build_id=build_id)
    if not build:
        raise HTTPException(
            status_code=404,
            detail={"code": "preview_not_found", "message": "Preview not found."},
        )
    return _preview_body(build)
