"""External ``$ref`` hygiene routes — COA-2.8 (#7051).

The Versions screen's **References** tab:

* ``GET    /v1/projects/{tenant}/{project}/references?version=…`` — every external ``$ref`` of the
  version's OpenAPI document (grouped by URL, with where each is used), its last refresh, status
  and pin; the document's circular internal references; and the external-ref policy in force.
* ``POST   …/references/refresh`` — fetch every external reference (or the ``urls`` given) now,
  under the tenant's external-ref policy, the deployment kill switch
  (``remote_ref_resolution_allowed``) and the SSRF guard. Each fetch bypasses the resolver's
  cache, so a change on the remote host is seen. A changed document is reported as a JSON Pointer
  diff against the pin (when pinned) or the previous snapshot (:mod:`app.project_references`).
* ``PUT    …/references/pin`` ``{url}`` — accept the last fetched snapshot; ``DELETE`` removes the pin.

And the policy itself, which had no API before (REPO-3.9 kept it in the database only):

* ``GET    /v1/tenants/{tenant}/governance/external-ref-policy`` — any member.
* ``PUT    /v1/tenants/{tenant}/governance/external-ref-policy`` — tenant administrators only,
  audit-logged (``governance.external_ref_policy.update``). It governs repository scans too.

Permissions: reading references needs ``projects:view`` and ``imports:view`` (it reads the captured
source, as the spec upgrade assistant does); refresh and pin need ``projects:edit``.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

from . import project_external_ref_store as store
from .auth import get_authenticated_user_id, validate_authentication
from .config import settings
from .database import db
from .openapi_ref_hygiene import external_ref_groups, find_ref_cycles
from .openapi_upgrade_routes import load_version_source
from .permissions import Action, Resource, enforce_permission
from .project_references import classify_fetch, reference_view, summarize
from .remote_ref_resolver import RemoteRefCache, fetch_remote_documents
from .repository_external_ref_policy import (
    ExternalRefPolicy,
    _normalize_pattern,
    build_gate,
    load_tenant_policy,
    normalize_allowlist,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["project-references"])

#: Workflow-audit action written when a refresh finds a changed reference.
AUDIT_REF_CHANGED = "project.external_ref.changed"
#: Workflow-audit action written for every refresh run.
AUDIT_REFRESHED = "project.external_refs.refreshed"
#: Access-audit action written when an administrator changes the policy.
AUDIT_POLICY_UPDATE = "governance.external_ref_policy.update"
#: Most allowlist patterns a tenant may store.
MAX_ALLOWLIST = 100

_BASE = "/v1/projects/{tenant_slug}/{project_id}/references"
_POLICY = "/v1/tenants/{tenant_slug}/governance/external-ref-policy"


# ---------------------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------------------


class ExternalRefPolicyOut(BaseModel):
    """The external-ref policy in force, and whether the caller may change it."""

    mode: Literal["block", "inline", "proxy-fetch"] = Field(
        description="`block` fetches nothing; `inline` fetches (only allowlisted hosts when the allowlist "
        "is not empty); `proxy-fetch` fetches only allowlisted hosts."
    )
    allowlist: List[str] = Field(description="Hostname patterns: `schemas.acme.com`, `*.acme.com` or `*`.")
    resolution_allowed: bool = Field(
        description="The deployment kill switch; false refuses every fetch whatever the mode."
    )
    fetches: bool = Field(description="Whether this policy can fetch anything at all.")
    can_edit: bool = Field(description="Whether the caller is a tenant administrator.")


class ExternalRefPolicyWrite(BaseModel):
    """Body of ``PUT …/governance/external-ref-policy``."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["block", "inline", "proxy-fetch"]
    allowlist: List[str] = Field(default_factory=list, max_length=MAX_ALLOWLIST)


class RefLocation(BaseModel):
    """One place an external reference is used."""

    location: str = Field(description="JSON Pointer of the `$ref`, e.g. `#/components/schemas/Money`.")
    ref: str = Field(description="The reference as written.")


class RefPin(BaseModel):
    """The accepted snapshot of a pinned reference."""

    digest: str
    at: Optional[datetime] = None


class ProjectReference(BaseModel):
    """One external reference: where it is used and what the last refresh found."""

    url: str = Field(description="The URL the reference fetches (fragment removed).")
    host: str
    locations: List[RefLocation]
    status: Literal["not-fetched", "ok", "changed", "unreachable", "blocked"] = Field(
        description="`not-fetched` until the first refresh; `changed` when the document differs from "
        "its pin (or, unpinned, from the previous fetch)."
    )
    reason: Optional[str] = Field(default=None, description="Why a fetch was refused or failed.")
    detail: Optional[str] = None
    digest: Optional[str] = Field(default=None, description="sha-256 of the last fetched document.")
    fetched_at: Optional[datetime] = Field(default=None, description="When the document was last fetched.")
    checked_at: Optional[datetime] = Field(default=None, description="When the reference was last refreshed.")
    pinned: Optional[RefPin] = None
    diff: Optional[Dict[str, Any]] = Field(
        default=None,
        description="The last change found: `{changes: [{pointer, kind, before?, after?}], total, truncated, "
        "against: pin|previous, from_digest, to_digest}`.",
    )


class RefCycle(BaseModel):
    """References that reach each other through internal `$ref`s."""

    refs: List[str] = Field(description="Every reference in the loop, sorted.")
    path: List[str] = Field(description="One way round the loop, ending where it starts.")


class ProjectReferencesOut(BaseModel):
    """``GET …/references``."""

    project_id: str
    version_record_id: str
    version_label: Optional[str] = None
    references: List[ProjectReference]
    summary: Dict[str, int] = Field(description="References per status.")
    cycles: List[RefCycle]
    cycle_total: int
    cycles_truncated: bool
    policy: ExternalRefPolicyOut
    refreshed: Optional[int] = Field(default=None, description="References fetched by this refresh (refresh only).")


class RefreshRequest(BaseModel):
    """Body of ``POST …/references/refresh``."""

    model_config = ConfigDict(extra="forbid")

    version: Optional[str] = Field(default=None, description="Version id or label; default the latest.")
    urls: Optional[List[str]] = Field(
        default=None, max_length=200, description="Refresh only these URLs (default: every external reference)."
    )


class PinRequest(BaseModel):
    """Body of ``PUT …/references/pin``."""

    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, max_length=2048)


# ---------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------


def _refuse(status: int, code: str, message: str) -> HTTPException:
    """A structured ``{code, message}`` refusal."""
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _policy_out(policy: ExternalRefPolicy, *, can_edit: bool) -> ExternalRefPolicyOut:
    """Project the policy and the kill switch onto the wire model."""
    allowed = bool(settings.remote_ref_resolution_allowed)
    return ExternalRefPolicyOut(
        mode=policy.mode.value,  # type: ignore[arg-type]
        allowlist=list(policy.allowlist),
        resolution_allowed=allowed,
        fetches=allowed and policy.fetches,
        can_edit=can_edit,
    )


def _is_admin(tenant_id: str, auth_data: Dict[str, Any]) -> bool:
    """Whether the caller is a tenant administrator (never raises)."""
    user_id = get_authenticated_user_id(auth_data)
    try:
        return bool(user_id) and bool(db.is_user_tenant_admin(tenant_id, user_id))
    except Exception:  # noqa: BLE001 - an unreadable role reads as "not an administrator"
        logger.warning("tenant admin check failed tenant=%s", tenant_id, exc_info=True)
        return False


def _view(
    tenant_id: str,
    project_id: str,
    document: Dict[str, Any],
    meta: Dict[str, Any],
    auth_data: Dict[str, Any],
) -> ProjectReferencesOut:
    """Build the panel's view of a version's document and the project's stored references."""
    groups = external_ref_groups(document)
    rows = store.list_refs(tenant_id, project_id)
    references = [reference_view(group, rows.get(group["url"])) for group in groups]
    cycles = find_ref_cycles(document)
    policy = load_tenant_policy(tenant_id)
    return ProjectReferencesOut(
        project_id=project_id,
        version_record_id=str(meta["version_record_id"]),
        version_label=meta.get("version_label"),
        references=[ProjectReference(**reference) for reference in references],
        summary=summarize(references),
        cycles=[RefCycle(**cycle) for cycle in cycles["cycles"]],
        cycle_total=cycles["total"],
        cycles_truncated=cycles["truncated"],
        policy=_policy_out(policy, can_edit=_is_admin(tenant_id, auth_data)),
    )


def _audit(tenant_id: str, project_id: str, action: str, actor_id: Optional[str], detail: Dict[str, Any]) -> None:
    """Write a workflow-audit row; an audit failure never fails the request."""
    try:
        db.insert_workflow_audit(tenant_id, project_id, None, action, "success", actor_id, detail)
    except Exception:  # noqa: BLE001
        logger.exception("audit %s failed project=%s", action, project_id)


# ---------------------------------------------------------------------------------------
# References
# ---------------------------------------------------------------------------------------


@router.get(_BASE, response_model=ProjectReferencesOut, summary="List a version's external $refs and cycles")
async def list_project_references(
    tenant_slug: str,
    project_id: str,
    version: Optional[str] = Query(default=None, description="Version id or label; default the latest."),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ProjectReferencesOut:
    """List a version's external references, their last refresh and pin, and its `$ref` cycles.

    Raises:
        HTTPException: 404 unknown project / version; 409 when the version has no single-document
            source (``unsupported-source``, ``source-withheld``, ``no-source``); 422 unparseable.
    """
    _ = tenant_slug
    tenant_id = str(auth_data["tenant_id"])
    target = f"project:{project_id}:references"
    await run_in_threadpool(enforce_permission, db, auth_data, Resource.PROJECTS, Action.VIEW, target=target)
    await run_in_threadpool(enforce_permission, db, auth_data, Resource.IMPORTS, Action.VIEW, target=target)
    document, meta = await asyncio.to_thread(load_version_source, tenant_id, project_id, version)
    return await asyncio.to_thread(_view, tenant_id, project_id, document, meta, auth_data)


def _refresh(
    tenant_id: str,
    project_id: str,
    urls: List[str],
    actor_id: Optional[str],
) -> Dict[str, Any]:
    """Fetch ``urls`` now and record each outcome (blocking). Returns counts for the audit row."""
    policy = load_tenant_policy(tenant_id)
    gate = build_gate(policy, resolution_allowed=bool(settings.remote_ref_resolution_allowed))
    # A fresh, private cache: the shared one maps a URL to the digest first seen, so it would
    # hide exactly the remote change a refresh exists to find.
    fetched = fetch_remote_documents(urls, cache=RemoteRefCache(), gate=gate)
    rows = store.list_refs(tenant_id, project_id)
    counts: Dict[str, int] = {}
    for url in urls:
        outcome = classify_fetch(fetched[url], rows.get(url))
        store.record_check(
            tenant_id=tenant_id,
            project_id=project_id,
            url=url,
            status=outcome.status,
            actor_id=actor_id,
            reason=outcome.reason,
            detail=outcome.detail,
            digest=outcome.digest,
            document=outcome.document,
            diff=outcome.diff,
        )
        counts[outcome.status] = counts.get(outcome.status, 0) + 1
        if outcome.status == "changed" and outcome.diff:
            _audit(
                tenant_id,
                project_id,
                AUDIT_REF_CHANGED,
                actor_id,
                {
                    "url": url,
                    "against": outcome.diff.get("against"),
                    "fromDigest": outcome.diff.get("from_digest"),
                    "toDigest": outcome.diff.get("to_digest"),
                    "changes": outcome.diff.get("total"),
                },
            )
    _audit(
        tenant_id,
        project_id,
        AUDIT_REFRESHED,
        actor_id,
        {"urls": len(urls), "outcomes": counts, "policy": policy.mode.value},
    )
    return counts


@router.post(f"{_BASE}/refresh", response_model=ProjectReferencesOut, summary="Refresh a version's external $refs")
async def refresh_project_references(
    tenant_slug: str,
    project_id: str,
    body: RefreshRequest = Body(default_factory=RefreshRequest),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ProjectReferencesOut:
    """Fetch the version's external references now and report what changed.

    Raises:
        HTTPException: as :func:`list_project_references`; 422 ``unknown-reference`` when ``urls``
            names a URL the version does not reference.
    """
    _ = tenant_slug
    tenant_id = str(auth_data["tenant_id"])
    target = f"project:{project_id}:references"
    await run_in_threadpool(enforce_permission, db, auth_data, Resource.IMPORTS, Action.VIEW, target=target)
    actor_id = await run_in_threadpool(enforce_permission, db, auth_data, Resource.PROJECTS, Action.EDIT, target=target)
    document, meta = await asyncio.to_thread(load_version_source, tenant_id, project_id, body.version)
    known = [group["url"] for group in external_ref_groups(document)]
    if body.urls is not None:
        unknown = [url for url in body.urls if url not in known]
        if unknown:
            raise _refuse(422, "unknown-reference", f"This version does not reference {unknown[0]!r}.")
        urls = list(dict.fromkeys(body.urls))
    else:
        urls = known
    actor = str(actor_id) if actor_id else get_authenticated_user_id(auth_data)
    if urls:
        await asyncio.to_thread(_refresh, tenant_id, project_id, urls, actor)
    view = await asyncio.to_thread(_view, tenant_id, project_id, document, meta, auth_data)
    view.refreshed = len(urls)
    return view


@router.put(f"{_BASE}/pin", response_model=ProjectReference, summary="Pin an external $ref's last fetched snapshot")
async def pin_project_reference(
    tenant_slug: str,
    project_id: str,
    body: PinRequest = Body(...),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ProjectReference:
    """Accept the reference's last fetched snapshot; later refreshes compare against it.

    Raises:
        HTTPException: 409 ``ref-not-fetched`` when the reference has no fetched snapshot yet.
    """
    _ = tenant_slug
    tenant_id = str(auth_data["tenant_id"])
    actor_id = await run_in_threadpool(
        enforce_permission,
        db, auth_data, Resource.PROJECTS, Action.EDIT, target=f"project:{project_id}:references"
    )
    actor = str(actor_id) if actor_id else get_authenticated_user_id(auth_data)
    row = await asyncio.to_thread(
        store.set_pin, tenant_id=tenant_id, project_id=project_id, url=body.url, actor_id=actor
    )
    if row is None:
        raise _refuse(409, "ref-not-fetched", "Refresh this reference before pinning it; nothing has been fetched yet.")
    return ProjectReference(**reference_view({"url": body.url, "locations": []}, row))


@router.delete(f"{_BASE}/pin", response_model=ProjectReference, summary="Unpin an external $ref")
async def unpin_project_reference(
    tenant_slug: str,
    project_id: str,
    url: str = Query(..., min_length=1, max_length=2048),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ProjectReference:
    """Remove a reference's pin.

    Raises:
        HTTPException: 404 ``ref-not-found`` when the reference was never refreshed.
    """
    _ = tenant_slug
    tenant_id = str(auth_data["tenant_id"])
    await run_in_threadpool(
        enforce_permission, db, auth_data, Resource.PROJECTS, Action.EDIT, target=f"project:{project_id}:references"
    )
    row = await asyncio.to_thread(store.clear_pin, tenant_id=tenant_id, project_id=project_id, url=url)
    if row is None:
        raise _refuse(404, "ref-not-found", "This reference has never been refreshed.")
    return ProjectReference(**reference_view({"url": url, "locations": []}, row))


# ---------------------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------------------


@router.get(_POLICY, response_model=ExternalRefPolicyOut, summary="Get the tenant's external $ref policy")
async def get_external_ref_policy(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ExternalRefPolicyOut:
    """The external-ref policy in force (``block`` when never set). Readable by any member."""
    _ = tenant_slug
    tenant_id = str(auth_data["tenant_id"])
    policy = await asyncio.to_thread(load_tenant_policy, tenant_id)
    return _policy_out(policy, can_edit=await run_in_threadpool(_is_admin, tenant_id, auth_data))


@router.put(_POLICY, response_model=ExternalRefPolicyOut, summary="Set the tenant's external $ref policy")
async def put_external_ref_policy(
    tenant_slug: str,
    body: ExternalRefPolicyWrite = Body(...),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ExternalRefPolicyOut:
    """Change the external-ref policy (tenant administrators only; audit-logged).

    Raises:
        HTTPException: 403 for a non-administrator; 422 when an allowlist pattern is not a
            hostname pattern, or ``proxy-fetch`` comes with an empty allowlist.
    """
    _ = tenant_slug
    tenant_id = str(auth_data["tenant_id"])
    if not await run_in_threadpool(_is_admin, tenant_id, auth_data):
        raise HTTPException(status_code=403, detail="Only tenant administrators can change the external $ref policy")
    raw = [pattern.strip() for pattern in body.allowlist if pattern.strip()]
    for pattern in raw:
        if _normalize_pattern(pattern) is None:
            raise _refuse(
                422,
                "invalid-allowlist",
                f"{pattern!r} is not a hostname pattern. Use a hostname (schemas.acme.com), a subdomain "
                "wildcard (*.acme.com) or *.",
            )
    patterns = list(normalize_allowlist(raw))
    if body.mode == "proxy-fetch" and not patterns:
        raise _refuse(422, "allowlist-required", "proxy-fetch fetches only allowlisted hosts; add at least one.")
    before = await asyncio.to_thread(load_tenant_policy, tenant_id)
    await asyncio.to_thread(db.set_tenant_external_ref_policy, tenant_id, policy=body.mode, allowlist=patterns)
    try:
        await run_in_threadpool(
            db.write_access_audit,
            tenant_id=tenant_id,
            action=AUDIT_POLICY_UPDATE,
            actor_id=get_authenticated_user_id(auth_data),
            actor_label=auth_data.get("email") or auth_data.get("username"),
            target=None,
            source="api",
            detail={"before": before.as_dict(), "after": {"mode": body.mode, "allowlist": patterns}},
        )
    except Exception:  # noqa: BLE001 - auditing never fails the governed action
        logger.warning("Failed to audit %s for tenant %s", AUDIT_POLICY_UPDATE, tenant_id, exc_info=True)
    policy = await asyncio.to_thread(load_tenant_policy, tenant_id)
    return _policy_out(policy, can_edit=True)
