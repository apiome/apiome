"""``/v1/tenants/{tenant_slug}/pact-secrets`` — workspace secrets, PFX-6.5 (#6957).

The HTTP face of :mod:`app.pact_secret_store`. Outside ``…/pact-broker``, because no Pact Broker
client knows it (the broker surface stays the catalogued, compatible one, :mod:`app.pact_broker_compat`):

* ``GET …/pact-secrets`` — every secret of the workspace, by name, with what refers to it;
* ``POST …/pact-secrets`` — create one (``name``, ``value``, optional ``description``);
* ``GET …/pact-secrets/{id}`` — one secret;
* ``PUT …/pact-secrets/{id}`` — change the description and, with ``value``, rotate the value;
* ``DELETE …/pact-secrets/{id}`` — delete one nothing refers to.

A webhook refers to a secret as ``${user.<name>}``; a verification target with ``auth.kind`` ``secret``
and ``auth.ref`` the name.

**No response ever carries a value**, and no refusal repeats one: bodies are read by
:func:`app.pact_secret.parse_secret_create` / :func:`~app.pact_secret.parse_secret_update`, whose
messages name the field, never its content.

**Permissions.** Reads need ``pacts:view``, creating ``pacts:create``, changing ``pacts:edit``,
deleting ``pacts:delete``. Every write appends an ``access_audit`` row
(:func:`app.pact_audit.audited_write`) — never with the body. Every lookup is scoped to the
authenticated tenant: another workspace's secret is a ``404``.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Response

from .consumer_contract_store import actor_from_auth
from .database import db
from .pact_audit import audited_write
from .pact_broker_auth import validate_broker_authentication
from .pact_broker_routes import _read_pact_body
from .pact_secret import (
    MAX_SECRETS_PER_TENANT,
    STATUS_BY_CODE,
    PactSecretError,
    SecretList,
    SecretRecord,
    parse_secret_create,
    parse_secret_update,
)
from .pact_secret_store import (
    KEYS_SETTING,
    create_secret,
    delete_secret,
    get_secret,
    list_secrets,
    update_secret,
)
from .permissions import Action, Resource, enforce_permission

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["pact-broker"])

_SECRETS = "/{tenant_slug}/pact-secrets"
_SECRET = _SECRETS + "/{secret_id}"

_NAME_RULE = "a letter, then up to 63 letters, digits and underscores"

_CREATE_BODY = {
    "required": True,
    "content": {
        "application/json": {
            "schema": {
                "type": "object",
                "required": ["name", "value"],
                "additionalProperties": False,
                "properties": {
                    "name": {
                        "type": "string",
                        "pattern": "^[A-Za-z][A-Za-z0-9_]{0,63}$",
                        "description": f"What references use: {_NAME_RULE}. Never changes.",
                    },
                    "description": {"type": "string", "maxLength": 1000},
                    "value": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 4096,
                        "writeOnly": True,
                        "description": "The secret, one line. Sealed; never returned.",
                    },
                },
            },
            "example": {
                "name": "ciToken",
                "description": "Token the provider's CI accepts for verification builds",
                "value": "ci-token-value",
            },
        }
    },
}

_UPDATE_BODY = {
    "required": True,
    "content": {
        "application/json": {
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string", "description": "Ignored when it repeats the stored name."},
                    "description": {"type": "string", "maxLength": 1000, "description": "Omit or null to clear."},
                    "value": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 4096,
                        "writeOnly": True,
                        "description": "A new value (rotation). Omit to keep the stored one.",
                    },
                },
            },
            "example": {"description": "Token the provider's CI accepts", "value": "rotated-ci-token"},
        }
    },
}

_INVALID = {422: {"description": "`pact-secret-invalid`: the body is malformed; `detail.pointer` names the field."}}
_NOT_FOUND = {404: {"description": "`pact-secret-not-found`: no such secret in this workspace."}}
_VAULT = {
    503: {
        "description": (
            f"`pact-secret-vault-unavailable`: the server has no key to seal the value with ({KEYS_SETTING})."
        )
    }
}


def _tenant_id(auth_data: Dict[str, Any]) -> str:
    """The authenticated tenant id, or a 403."""
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this credential.")
    return str(tenant_id)


def _error(exc: PactSecretError) -> HTTPException:
    """The HTTP error for a refusal, carrying ``{"code", "message"}`` and, when known, ``"pointer"``.

    Args:
        exc: The refusal.

    Returns:
        The exception to raise.
    """
    detail: Dict[str, Any] = {"code": exc.code, "message": str(exc)}
    if exc.pointer is not None:
        detail["pointer"] = exc.pointer
    return HTTPException(status_code=STATUS_BY_CODE.get(exc.code, 422), detail=detail)


@router.get(
    _SECRETS,
    response_model=SecretList,
    summary="List the workspace's secrets",
    description=(
        "Every secret of the workspace by name (PFX-6.5): its description, the reference a webhook "
        "writes (`${user.<name>}`), when its value was last set, and the webhooks and verification "
        "targets that use it. **Values are never returned.** Requires `pacts:view`."
    ),
)
def read_secrets(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> SecretList:
    """List the workspace's secrets.

    Args:
        tenant_slug: The tenant in the URL (the authenticated tenant scopes every lookup).
        auth_data: The authenticated principal.

    Returns:
        The secrets, without values.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW, target="pact-secrets")
    _ = tenant_slug
    return SecretList(secrets=list_secrets(db, _tenant_id(auth_data)))


@router.post(
    _SECRETS,
    response_model=SecretRecord,
    status_code=201,
    summary="Create a workspace secret",
    description=(
        "Keep a secret once, sealed in the credential vault, for webhooks and verification targets to "
        f"refer to (PFX-6.5). `name` is {_NAME_RULE}, unique in the workspace and never changed; "
        "`value` is one line of up to 4,096 characters. A webhook refers to it as `${user.<name>}` in "
        "its URL path or query, headers, body, credentials, GitHub token or signing secret; a "
        "verification target with `auth.kind: secret` and `auth.ref: <name>`. A workspace keeps at most "
        f"{MAX_SECRETS_PER_TENANT} secrets. The answer never contains the value. Requires `pacts:create`."
    ),
    openapi_extra={"requestBody": _CREATE_BODY},
    responses={
        **_INVALID,
        409: {"description": "`pact-secret-name-taken` or `pact-secret-limit-reached`."},
        **_VAULT,
    },
)
@audited_write("pacts.secret.create", "pact-secrets")
def post_secret(
    tenant_slug: str,
    raw: bytes = Depends(_read_pact_body),
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> SecretRecord:
    """Create a secret.

    Args:
        tenant_slug: The tenant in the URL.
        raw: The body, already size-limited.
        auth_data: The authenticated principal.

    Returns:
        The stored secret, ``201``.
    """
    user_id = enforce_permission(db, auth_data, Resource.PACTS, Action.CREATE, target="pact-secrets")
    _ = tenant_slug
    try:
        secret = parse_secret_create(raw)
        return create_secret(db, _tenant_id(auth_data), secret, actor=actor_from_auth(auth_data, user_id))
    except PactSecretError as exc:
        raise _error(exc) from exc


@router.get(
    _SECRET,
    response_model=SecretRecord,
    summary="Read a workspace secret",
    description="One secret, without its value, and what refers to it (PFX-6.5). Requires `pacts:view`.",
    responses=_NOT_FOUND,
)
def read_secret(
    tenant_slug: str,
    secret_id: str,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> SecretRecord:
    """Read one secret.

    Args:
        tenant_slug: The tenant in the URL.
        secret_id: The secret's id.
        auth_data: The authenticated principal.

    Returns:
        The secret, without its value.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW, target="pact-secrets")
    _ = tenant_slug
    try:
        return get_secret(db, _tenant_id(auth_data), secret_id)
    except PactSecretError as exc:
        raise _error(exc) from exc


@router.put(
    _SECRET,
    response_model=SecretRecord,
    summary="Update or rotate a workspace secret",
    description=(
        "Replace the description and, when `value` is sent, rotate the value (PFX-6.5): every webhook "
        "and verification target that refers to the secret uses the new value from its next send or "
        "run. The name cannot change — references use it; `name` may be sent only as the stored one. "
        "Requires `pacts:edit`."
    ),
    openapi_extra={"requestBody": _UPDATE_BODY},
    responses={**_INVALID, **_NOT_FOUND, **_VAULT},
)
@audited_write("pacts.secret.update", "pact-secret/{secret_id}")
def put_secret(
    tenant_slug: str,
    secret_id: str,
    raw: bytes = Depends(_read_pact_body),
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> SecretRecord:
    """Update or rotate a secret.

    Args:
        tenant_slug: The tenant in the URL.
        secret_id: The secret's id.
        raw: The body, already size-limited.
        auth_data: The authenticated principal.

    Returns:
        The stored secret.
    """
    user_id = enforce_permission(db, auth_data, Resource.PACTS, Action.EDIT, target="pact-secrets")
    _ = tenant_slug
    try:
        change = parse_secret_update(raw)
        return update_secret(db, _tenant_id(auth_data), secret_id, change, actor=actor_from_auth(auth_data, user_id))
    except PactSecretError as exc:
        raise _error(exc) from exc


@router.delete(
    _SECRET,
    status_code=204,
    summary="Delete a workspace secret",
    description=(
        "Delete a secret (PFX-6.5). A secret a webhook or a verification target still refers to is not "
        "deleted: the answer is `409 pact-secret-in-use` naming them. Requires `pacts:delete`."
    ),
    responses={**_NOT_FOUND, 409: {"description": "`pact-secret-in-use`: names what still refers to it."}},
)
@audited_write("pacts.secret.delete", "pact-secret/{secret_id}")
def remove_secret(
    tenant_slug: str,
    secret_id: str,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> Response:
    """Delete a secret.

    Args:
        tenant_slug: The tenant in the URL.
        secret_id: The secret's id.
        auth_data: The authenticated principal.

    Returns:
        An empty ``204``.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.DELETE, target="pact-secrets")
    _ = tenant_slug
    try:
        delete_secret(db, _tenant_id(auth_data), secret_id)
    except PactSecretError as exc:
        raise _error(exc) from exc
    return Response(status_code=204)
