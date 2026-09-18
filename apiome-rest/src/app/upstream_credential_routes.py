"""Upstream credential endpoints — AGX-2.2 (#4534).

Four routes over the upstream auth vault (:mod:`app.upstream_credentials`):

```
GET    /v1/tenants/{t}/agent-toolsets/{toolset}/upstream-credentials
POST   /v1/tenants/{t}/agent-toolsets/{toolset}/upstream-credentials
POST   /v1/tenants/{t}/agent-toolsets/{toolset}/upstream-credentials/{id}/rotate
DELETE /v1/tenants/{t}/agent-toolsets/{toolset}/upstream-credentials/{id}
```

**Write-only.** Create and rotate accept a secret; every response, including the ones those two
routes return, is metadata: the binding, the kind and placement, which master key sealed it,
whether it still opens, and timestamps. No route reads a secret back, and the router uses
:class:`~app.redacted_validation_route.RedactedValidationRoute`, so a malformed request's ``422``
doesn't echo the secret it carried either.

**Scoped by the authenticated tenant.** As on every ``/v1/tenants/{t}`` surface, the tenant in the
URL is informational; the caller's authenticated tenant scopes every read and write, so one
tenant can never address another's credential by id. The toolset id is not yet checked against
``agent_toolsets``: that table is AGX-1.2 (#4530), which adds the foreign key and the check.

**Permissions reuse** ``api_keys``, **and no new RBAC resource is added.** Listing is
``api_keys:view``; create, rotate and delete are ``api_keys:create`` / ``edit`` / ``delete``. An
upstream credential is the other half of an agent's access, and AGX-3.1's agent keys are
``api_keys`` too.

**Every mutation is audited, and no audit row carries a secret.** Create, rotate and delete write
``agent.upstream_credential.*`` rows to the tenant's access audit with the credential id, toolset,
server URL, kind and key version. Uses are recorded separately, by the vault, in
``upstream_credential_uses``.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from .auth import validate_authentication
from .database import db
from .envelope_crypto import EnvelopeEncryptionError
from .permissions import Action, Resource, enforce_permission
from .redacted_validation_route import RedactedValidationRoute
from .upstream_credential_binding import API_KEY_LOCATIONS, KINDS
from .upstream_credentials import (
    CODE_CREDENTIAL_EXISTS,
    CODE_CREDENTIAL_NOT_FOUND,
    UPSTREAM_CREDENTIAL_SCHEMA_VERSION,
    UpstreamCredentialCreate,
    UpstreamCredentialError,
    UpstreamCredentialOut,
    UpstreamCredentialRotate,
    create_credential,
    credential_encryption_configured,
    delete_credential,
    list_credentials,
    rotate_credential,
)

logger = logging.getLogger(__name__)

__all__ = [
    "AUDIT_CREATE",
    "AUDIT_DELETE",
    "AUDIT_ROTATE",
    "UpstreamCredentialListResponse",
    "router",
]

router = APIRouter(
    prefix="/v1/tenants", tags=["agent-access"], route_class=RedactedValidationRoute
)

#: Audit actions this module writes to ``apiome.access_audit``.
AUDIT_CREATE = "agent.upstream_credential.create"
AUDIT_ROTATE = "agent.upstream_credential.rotate"
AUDIT_DELETE = "agent.upstream_credential.delete"

_BASE = "/{tenant_slug}/agent-toolsets/{toolset_id}/upstream-credentials"

#: HTTP status per refusal code; anything else is a 422.
_STATUS_BY_CODE = {CODE_CREDENTIAL_EXISTS: 409, CODE_CREDENTIAL_NOT_FOUND: 404}

_WRITE_ONLY = (
    "A credential is **write-only**: the secret is stored envelope-encrypted and no route ever "
    "returns it. Responses carry metadata only: the server URL it is bound to, its kind and "
    "placement, the master-key version that sealed it, whether it currently opens (`readable`), "
    "and when it was created, rotated and last used."
)

_KINDS_DESCRIPTION = (
    "Kinds: `apiKey` (sent as the header or query parameter named by `in` / `name`, secret "
    "`{value}`), `bearer` (`Authorization: Bearer`, secret `{token}`) and `basic` "
    "(`Authorization: Basic`, secret `{username, password}`)."
)


class UpstreamCredentialListResponse(BaseModel):
    """A toolset's upstream credentials, described.

    Attributes:
        schema_version: The projection's shape.
        toolset_id: The toolset addressed.
        encryption_configured: Whether this deployment can store credentials at all.
        kinds: The credential kinds the vault accepts.
        api_key_locations: Where an ``apiKey`` credential may be sent.
        credentials: One entry per stored credential, by server URL.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: str = Field(
        default=UPSTREAM_CREDENTIAL_SCHEMA_VERSION, serialization_alias="schemaVersion"
    )
    toolset_id: str = Field(serialization_alias="toolsetId")
    encryption_configured: bool = Field(serialization_alias="encryptionConfigured")
    kinds: List[str]
    api_key_locations: List[str] = Field(serialization_alias="apiKeyLocations")
    credentials: List[UpstreamCredentialOut]


def _tenant_id(auth_data: Dict[str, Any]) -> str:
    """Return the authenticated tenant id, or refuse with 403."""
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this credential.")
    return str(tenant_id)


def _refusal(exc: UpstreamCredentialError) -> HTTPException:
    """Map a vault refusal onto its status, listing every problem."""
    return HTTPException(
        status_code=_STATUS_BY_CODE.get(exc.code, 422),
        detail={"code": exc.code, "errors": list(exc.errors)},
    )


def _unconfigured(exc: EnvelopeEncryptionError) -> HTTPException:
    """Map "no master key" onto 503, naming the variable to set. Fail closed: nothing is stored."""
    return HTTPException(
        status_code=503,
        detail={
            "code": "upstream-credential-encryption-unconfigured",
            "message": (
                f"Upstream credentials cannot be stored on this deployment: {exc}. Set "
                "APIOME_UPSTREAM_CREDENTIAL_ENCRYPTION_KEYS and restart."
            ),
        },
    )


def _audit(
    *,
    tenant_id: str,
    action: str,
    auth_data: Dict[str, Any],
    actor_id: str,
    credential: UpstreamCredentialOut,
) -> None:
    """Write one metadata-only access-audit row (best-effort).

    An audit failure is logged and swallowed: a mutation that succeeded must not be reported as
    a failure because its audit row could not be appended.

    Args:
        tenant_id: The tenant the action belongs to.
        action: One of the ``AUDIT_*`` actions.
        auth_data: The authenticated principal.
        actor_id: The acting user id :func:`enforce_permission` resolved.
        credential: The credential acted on. Only its metadata is recorded.
    """
    try:
        db.write_access_audit(
            tenant_id=tenant_id,
            action=action,
            actor_id=actor_id,
            actor_label=auth_data.get("user_email") or auth_data.get("user_name"),
            target=credential.id,
            source="api",
            detail={
                "toolsetId": credential.toolset_id,
                "serverUrl": credential.server_url,
                "kind": credential.kind,
                "in": credential.api_key_in,
                "name": credential.api_key_name,
                "keyVersion": credential.key_version,
            },
        )
    except Exception:  # noqa: BLE001 - auditing never fails the governed action
        logger.warning("Failed to audit %s for tenant %s", action, tenant_id, exc_info=True)


@router.get(
    _BASE,
    response_model=UpstreamCredentialListResponse,
    summary="List a toolset's upstream credentials (metadata only)",
    description=(
        "The credentials the AGX-2.1 invocation proxy injects when this toolset calls its "
        "upstream APIs.\n\n" + _WRITE_ONLY + "\n\nRequires `api_keys:view`."
    ),
)
async def list_upstream_credentials(
    tenant_slug: str,
    toolset_id: UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> UpstreamCredentialListResponse:
    """Describe a toolset's credentials.

    Args:
        tenant_slug: The tenant in the URL (the authenticated tenant is what scopes it).
        toolset_id: The agent toolset.
        auth_data: The authenticated principal.

    Returns:
        The toolset's credentials, as metadata.

    Raises:
        HTTPException: 403 without ``api_keys:view``.
    """
    enforce_permission(db, auth_data, Resource.API_KEYS, Action.VIEW)
    _ = tenant_slug
    return UpstreamCredentialListResponse(
        toolset_id=str(toolset_id),
        encryption_configured=credential_encryption_configured(),
        kinds=list(KINDS),
        api_key_locations=list(API_KEY_LOCATIONS),
        credentials=list_credentials(_tenant_id(auth_data), str(toolset_id)),
    )


@router.post(
    _BASE,
    response_model=UpstreamCredentialOut,
    status_code=201,
    summary="Store an upstream credential for a toolset",
    description=(
        "Bind a new credential to this toolset and one upstream server. The credential is only "
        "ever injected into requests under `serverUrl`: an `https://` origin plus an optional "
        "base path. `https://api.example.com/v1` covers `/v1` and `/v1/…` on that exact host and "
        "port, and nothing else.\n\n"
        + _KINDS_DESCRIPTION
        + "\n\n"
        + _WRITE_ONLY
        + "\n\nOne credential per toolset and server: storing a second is a `409`; rotate the "
        "existing one instead.\n\nRequires `api_keys:create`. Audited as "
        "`agent.upstream_credential.create`, with metadata only."
    ),
    responses={
        409: {"description": "This toolset already has a credential for that server."},
        422: {"description": "The server URL, placement or secret is not acceptable."},
        503: {"description": "No upstream-credential encryption key is configured."},
    },
)
async def create_upstream_credential(
    tenant_slug: str,
    toolset_id: UUID,
    body: UpstreamCredentialCreate,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> UpstreamCredentialOut:
    """Seal and store a new credential, then audit it.

    Args:
        tenant_slug: The tenant in the URL.
        toolset_id: The agent toolset.
        body: The binding, placement and secret.
        auth_data: The authenticated principal.

    Returns:
        The stored credential's metadata.

    Raises:
        HTTPException: 403 without ``api_keys:create``; 409 when the binding is taken; 422 on an
            invalid request; 503 when encryption is unconfigured.
    """
    actor_id = enforce_permission(db, auth_data, Resource.API_KEYS, Action.CREATE)
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    try:
        stored = create_credential(tenant_id, str(toolset_id), body, actor_id=actor_id)
    except UpstreamCredentialError as exc:
        raise _refusal(exc) from exc
    except EnvelopeEncryptionError as exc:
        raise _unconfigured(exc) from exc
    _audit(
        tenant_id=tenant_id,
        action=AUDIT_CREATE,
        auth_data=auth_data,
        actor_id=actor_id,
        credential=stored,
    )
    return stored


@router.post(
    _BASE + "/{credential_id}/rotate",
    response_model=UpstreamCredentialOut,
    summary="Rotate an upstream credential's secret",
    description=(
        "Replace the secret in place, atomically. The credential keeps its id, binding and "
        "placement. Invocations already in flight finish with the secret they opened, and the "
        "next invocation uses the new one: no window without a credential.\n\n"
        "The body is `{secret}`, in the same shape as at creation. " + _WRITE_ONLY + "\n\n"
        "Requires `api_keys:edit`. Audited as `agent.upstream_credential.rotate`."
    ),
    responses={
        404: {"description": "No such credential for this toolset."},
        422: {"description": "The secret does not fit the credential's kind."},
        503: {"description": "No upstream-credential encryption key is configured."},
    },
)
async def rotate_upstream_credential(
    tenant_slug: str,
    toolset_id: UUID,
    credential_id: UUID,
    body: UpstreamCredentialRotate,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> UpstreamCredentialOut:
    """Rotate a credential's secret, then audit it.

    Args:
        tenant_slug: The tenant in the URL.
        toolset_id: The agent toolset.
        credential_id: The credential to rotate.
        body: The replacement secret.
        auth_data: The authenticated principal.

    Returns:
        The credential's metadata after the rotation.

    Raises:
        HTTPException: 403 without ``api_keys:edit``; 404 when it does not exist; 422 when the
            secret does not fit; 503 when encryption is unconfigured.
    """
    actor_id = enforce_permission(db, auth_data, Resource.API_KEYS, Action.EDIT)
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    try:
        rotated = rotate_credential(
            tenant_id, str(toolset_id), str(credential_id), body, actor_id=actor_id
        )
    except UpstreamCredentialError as exc:
        raise _refusal(exc) from exc
    except EnvelopeEncryptionError as exc:
        raise _unconfigured(exc) from exc
    _audit(
        tenant_id=tenant_id,
        action=AUDIT_ROTATE,
        auth_data=auth_data,
        actor_id=actor_id,
        credential=rotated,
    )
    return rotated


@router.delete(
    _BASE + "/{credential_id}",
    status_code=204,
    response_class=Response,
    summary="Delete an upstream credential",
    description=(
        "Remove the credential. The toolset's next call to that server goes out without it. Its "
        "use history is kept.\n\nRequires `api_keys:delete`. Audited as "
        "`agent.upstream_credential.delete`."
    ),
    responses={404: {"description": "No such credential for this toolset."}},
)
async def delete_upstream_credential(
    tenant_slug: str,
    toolset_id: UUID,
    credential_id: UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Response:
    """Delete a credential, then audit it.

    Args:
        tenant_slug: The tenant in the URL.
        toolset_id: The agent toolset.
        credential_id: The credential to delete.
        auth_data: The authenticated principal.

    Returns:
        An empty ``204``.

    Raises:
        HTTPException: 403 without ``api_keys:delete``; 404 when it does not exist.
    """
    actor_id = enforce_permission(db, auth_data, Resource.API_KEYS, Action.DELETE)
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    removed = delete_credential(tenant_id, str(toolset_id), str(credential_id))
    if removed is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": CODE_CREDENTIAL_NOT_FOUND,
                "errors": ["no such upstream credential for this toolset"],
            },
        )
    _audit(
        tenant_id=tenant_id,
        action=AUDIT_DELETE,
        auth_data=auth_data,
        actor_id=actor_id,
        credential=removed,
    )
    return Response(status_code=204)
