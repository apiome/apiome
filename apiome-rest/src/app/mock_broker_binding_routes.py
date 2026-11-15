"""Mock broker binding endpoints — XPC-2.1 (#5735).

Five routes over a version's broker bindings (:mod:`app.mock_broker_bindings`):

```
GET    /v1/versions/{t}/{project}/{version}/mock/broker-bindings
POST   /v1/versions/{t}/{project}/{version}/mock/broker-bindings
POST   /v1/versions/{t}/{project}/{version}/mock/broker-bindings/{id}/rotate
POST   /v1/versions/{t}/{project}/{version}/mock/broker-bindings/{id}/test
DELETE /v1/versions/{t}/{project}/{version}/mock/broker-bindings/{id}
```

**Write-only credential.** Create and rotate accept a SASL credential; every response is
metadata. No route reads a credential back, and the router uses
:class:`~app.redacted_validation_route.RedactedValidationRoute`, so a malformed request's ``422``
doesn't echo the credential it carried either.

**SSRF-guarded.** Every bootstrap host is resolved and checked on create and again on every test;
a host that reaches a private or otherwise non-public address is ``422 broker-address-disallowed``
(see :mod:`app.mock_broker_addresses` for the dev-broker exemption and the local escape hatch).

**Permissions reuse** ``versions``, **and no new RBAC resource is added.** Listing is
``versions:view`` like every other ``…/mock/*`` read; create, rotate, test and delete are
``versions:edit`` and, like every other mock-settings write, need the version's creator or a tenant
administrator.

**Every mutation is audited, and no audit row carries a credential.** Create, rotate, test and
delete write ``mock.broker_binding.*`` rows to the tenant's access audit with the binding id,
version, protocol, bootstrap, flags, mechanism and key version (and, for a test, its outcome).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from .auth import get_authenticated_user_id, validate_authentication
from .database import db
from .envelope_crypto import EnvelopeEncryptionError
from .mock_broker_addresses import dev_broker_bootstrap
from .mock_broker_bindings import (
    BROKER_BINDING_SCHEMA_VERSION,
    CODE_BINDING_EXISTS,
    CODE_BINDING_NOT_FOUND,
    PROTOCOL_KAFKA,
    PROTOCOLS_RESERVED,
    SASL_MECHANISMS,
    BrokerBindingCreate,
    BrokerBindingError,
    BrokerBindingOut,
    BrokerBindingRotate,
    broker_encryption_configured,
    create_binding,
    delete_binding,
    describe_row,
    get_binding,
    list_bindings,
    rotate_binding,
)
from .mock_broker_probe import BrokerProbeResult, probe_binding
from .permissions import Action, Resource, enforce_permission
from .redacted_validation_route import RedactedValidationRoute

logger = logging.getLogger(__name__)

__all__ = [
    "AUDIT_CREATE",
    "AUDIT_DELETE",
    "AUDIT_ROTATE",
    "AUDIT_TEST",
    "BrokerBindingListResponse",
    "router",
]

router = APIRouter(prefix="/v1/versions", tags=["mock-server"], route_class=RedactedValidationRoute)

#: Audit actions this module writes to ``apiome.access_audit``.
AUDIT_CREATE = "mock.broker_binding.create"
AUDIT_ROTATE = "mock.broker_binding.rotate"
AUDIT_TEST = "mock.broker_binding.test"
AUDIT_DELETE = "mock.broker_binding.delete"

_BASE = "/{tenant_slug}/{project_id}/{version_record_id}/mock/broker-bindings"

#: HTTP status per refusal code; anything else is a 422.
_STATUS_BY_CODE = {CODE_BINDING_EXISTS: 409, CODE_BINDING_NOT_FOUND: 404}

_WRITE_ONLY = (
    "The SASL credential is **write-only**: it is stored envelope-encrypted and no route ever "
    "returns it. Responses carry metadata only: the bootstrap hosts, TLS flags, SASL mechanism, "
    "the master-key version that sealed the credential, whether it currently opens (`readable`), "
    "and when it was created and rotated."
)

_ADDRESS_RULE = (
    "Every bootstrap host is resolved, and a host that reaches a private, loopback, link-local or "
    "otherwise non-public address is refused `422 broker-address-disallowed`. The dev broker "
    "named by `APIOME_MOCK_DEV_BROKER_BOOTSTRAP` (the `docker compose --profile broker` Redpanda) "
    "is exempt; `APIOME_MOCK_BROKER_ALLOW_PRIVATE=true` lifts the check for local development."
)


class BrokerBindingListResponse(BaseModel):
    """A version's broker bindings, described.

    Attributes:
        schema_version: The projection's shape.
        version_id: The version addressed.
        encryption_configured: Whether this deployment can store a SASL credential.
        protocols: The protocols a binding can be created for now.
        reserved_protocols: Protocols reserved for a later release.
        sasl_mechanisms: The SASL mechanisms accepted.
        dev_broker_bootstrap: The dev broker's ``host:port`` entries when the compose profile is
            active, else ``None``.
        bindings: One entry per stored binding.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: str = Field(
        default=BROKER_BINDING_SCHEMA_VERSION, serialization_alias="schemaVersion"
    )
    version_id: str = Field(serialization_alias="versionId")
    encryption_configured: bool = Field(serialization_alias="encryptionConfigured")
    protocols: List[str]
    reserved_protocols: List[str] = Field(serialization_alias="reservedProtocols")
    sasl_mechanisms: List[str] = Field(serialization_alias="saslMechanisms")
    dev_broker_bootstrap: Optional[List[str]] = Field(
        default=None, serialization_alias="devBrokerBootstrap"
    )
    bindings: List[BrokerBindingOut]


def _version(project_id: str, version_record_id: str, tenant_id: str) -> Dict[str, Any]:
    """Return the version row, 404ing when it is not in this tenant and project."""
    existing = db.get_version_by_id(version_record_id, tenant_id)
    if not existing or str(existing.get("project_id")) != project_id:
        raise HTTPException(status_code=404, detail=f"Version not found: {version_record_id}")
    return existing


def _require_owner(project_id: str, version_record_id: str, auth_data: Dict[str, Any]) -> str:
    """Confirm the caller may change this version's mock configuration, and return their id.

    The same rule as every other mock-settings write: an identifiable user who created the version
    or administers the tenant.

    Raises:
        HTTPException: 404 when the version does not exist; 403 otherwise refused.
    """
    tenant_id = str(auth_data["tenant_id"])
    _version(project_id, version_record_id, tenant_id)
    user_id = get_authenticated_user_id(auth_data)
    if not user_id:
        raise HTTPException(
            status_code=403,
            detail="Mock settings require user authentication (JWT token or API key with attribution)",
        )
    if not db.user_owns_version_mock_settings(version_record_id, tenant_id, user_id):
        raise HTTPException(
            status_code=403,
            detail="Only the version creator or a tenant administrator can change mock settings",
        )
    return user_id


def _refusal(exc: BrokerBindingError) -> HTTPException:
    """Map a binding refusal onto its status, listing every problem."""
    return HTTPException(
        status_code=_STATUS_BY_CODE.get(exc.code, 422),
        detail={"code": exc.code, "errors": list(exc.errors)},
    )


def _not_found() -> HTTPException:
    """The 404 for a binding id that is not on this version."""
    return HTTPException(
        status_code=404,
        detail={"code": CODE_BINDING_NOT_FOUND, "errors": ["no such broker binding for this version"]},
    )


def _unconfigured(exc: EnvelopeEncryptionError) -> HTTPException:
    """Map "no master key" onto 503, naming the variable to set. Fail closed: nothing is stored."""
    return HTTPException(
        status_code=503,
        detail={
            "code": "broker-credential-encryption-unconfigured",
            "message": (
                f"Broker credentials cannot be stored on this deployment: {exc}. Set "
                "APIOME_BROKER_CREDENTIAL_ENCRYPTION_KEYS and restart."
            ),
        },
    )


def _audit(
    *,
    tenant_id: str,
    action: str,
    auth_data: Dict[str, Any],
    actor_id: str,
    binding: BrokerBindingOut,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Write one metadata-only access-audit row (best-effort).

    Args:
        tenant_id: The tenant the action belongs to.
        action: One of the ``AUDIT_*`` actions.
        auth_data: The authenticated principal.
        actor_id: The acting user id.
        binding: The binding acted on. Only its metadata is recorded.
        extra: More metadata (a test's outcome).
    """
    try:
        db.write_access_audit(
            tenant_id=tenant_id,
            action=action,
            actor_id=actor_id,
            actor_label=auth_data.get("user_email") or auth_data.get("user_name"),
            target=binding.id,
            source="api",
            detail={
                "versionId": binding.version_id,
                "protocol": binding.protocol,
                "bootstrap": binding.bootstrap,
                "tls": binding.tls.enabled,
                "tlsVerify": binding.tls.verify,
                "saslMechanism": binding.sasl_mechanism,
                "keyVersion": binding.key_version,
                **(extra or {}),
            },
        )
    except Exception:  # noqa: BLE001 - auditing never fails the governed action
        logger.warning("Failed to audit %s for tenant %s", action, tenant_id, exc_info=True)


@router.get(
    _BASE,
    response_model=BrokerBindingListResponse,
    summary="List a version's mock broker bindings (metadata only)",
    description=(
        "Where the version's hosted mock publishes AsyncAPI events, beyond WebSocket/SSE. A "
        "version with event channels and no binding is served over WebSocket/SSE only.\n\n"
        + _WRITE_ONLY
        + "\n\nRequires `versions:view`."
    ),
)
async def list_mock_broker_bindings(
    tenant_slug: str,
    project_id: str,
    version_record_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> BrokerBindingListResponse:
    """Describe a version's broker bindings.

    Raises:
        HTTPException: 403 without ``versions:view``; 404 when the version does not exist.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    _ = tenant_slug
    tenant_id = str(auth_data["tenant_id"])
    _version(project_id, version_record_id, tenant_id)
    dev = [entry.render() for entry in dev_broker_bootstrap()]
    return BrokerBindingListResponse(
        version_id=version_record_id,
        encryption_configured=broker_encryption_configured(),
        protocols=[PROTOCOL_KAFKA],
        reserved_protocols=list(PROTOCOLS_RESERVED),
        sasl_mechanisms=list(SASL_MECHANISMS),
        dev_broker_bootstrap=dev or None,
        bindings=list_bindings(tenant_id, version_record_id),
    )


@router.post(
    _BASE,
    response_model=BrokerBindingOut,
    status_code=201,
    summary="Bind a version's mock to a broker",
    description=(
        "Bind the version's hosted mock to a Kafka broker: `bootstrap` hosts, `tls` flags, an "
        "optional `saslMechanism` (`PLAIN`, `SCRAM-SHA-256`, `SCRAM-SHA-512`) with its "
        "`credential`, and a `clientIdPrefix`. `mqtt` and `amqp` are reserved and refused.\n\n"
        + _ADDRESS_RULE
        + "\n\n"
        + _WRITE_ONLY
        + "\n\nOne binding per version and protocol: a second is a `409`.\n\nRequires "
        "`versions:edit` (version creator or tenant administrator). Audited as "
        "`mock.broker_binding.create`, with metadata only."
    ),
    responses={
        404: {"description": "No such version in this project."},
        409: {"description": "This version already has a binding for that protocol."},
        422: {
            "description": (
                "`broker-binding-invalid`, `broker-protocol-unsupported`, or "
                "`broker-address-disallowed`."
            )
        },
        503: {"description": "A credential was given and no broker encryption key is configured."},
    },
)
async def create_mock_broker_binding(
    tenant_slug: str,
    project_id: str,
    version_record_id: str,
    body: BrokerBindingCreate,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> BrokerBindingOut:
    """Validate, seal and store a binding, then audit it.

    Raises:
        HTTPException: 403 / 404 / 409 / 422 / 503 as documented on the route.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.EDIT)
    _ = tenant_slug
    actor_id = _require_owner(project_id, version_record_id, auth_data)
    tenant_id = str(auth_data["tenant_id"])
    try:
        stored = create_binding(tenant_id, version_record_id, body, actor_id=actor_id)
    except BrokerBindingError as exc:
        raise _refusal(exc) from exc
    except EnvelopeEncryptionError as exc:
        raise _unconfigured(exc) from exc
    _audit(tenant_id=tenant_id, action=AUDIT_CREATE, auth_data=auth_data, actor_id=actor_id, binding=stored)
    return stored


@router.post(
    _BASE + "/{binding_id}/rotate",
    response_model=BrokerBindingOut,
    summary="Rotate a broker binding's SASL credential",
    description=(
        "Replace the SASL credential in place, atomically. The binding keeps its id, address and "
        "flags. The body is `{credential: {username, password}}`. " + _WRITE_ONLY + "\n\n"
        "Requires `versions:edit`. Audited as `mock.broker_binding.rotate`."
    ),
    responses={
        404: {"description": "No such binding on this version."},
        422: {"description": "The binding has no SASL mechanism, or the credential is not acceptable."},
        503: {"description": "No broker encryption key is configured."},
    },
)
async def rotate_mock_broker_binding(
    tenant_slug: str,
    project_id: str,
    version_record_id: str,
    binding_id: str,
    body: BrokerBindingRotate,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> BrokerBindingOut:
    """Rotate a binding's credential, then audit it."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.EDIT)
    _ = tenant_slug
    actor_id = _require_owner(project_id, version_record_id, auth_data)
    tenant_id = str(auth_data["tenant_id"])
    try:
        rotated = rotate_binding(tenant_id, version_record_id, binding_id, body, actor_id=actor_id)
    except BrokerBindingError as exc:
        raise _refusal(exc) from exc
    except EnvelopeEncryptionError as exc:
        raise _unconfigured(exc) from exc
    _audit(tenant_id=tenant_id, action=AUDIT_ROTATE, auth_data=auth_data, actor_id=actor_id, binding=rotated)
    return rotated


@router.post(
    _BASE + "/{binding_id}/test",
    response_model=BrokerProbeResult,
    summary="Test a broker binding (connect and read metadata)",
    description=(
        "Connect to one bootstrap host, complete TLS and SASL, and read cluster metadata — "
        "nothing is produced, consumed or created. The answer is `reachable` or `unreachable` "
        "with a `reason`: `auth`, `credential-unavailable`, `address-disallowed`, `tls`, "
        "`timeout`, `connect` or `protocol`. A wrong password is `unreachable: auth`; the "
        "broker's own error text is never returned. Every host is SSRF-checked again first.\n\n"
        "The result is cached for 60 seconds per binding state (`cached: true`); a rotation "
        "tests afresh.\n\nRequires `versions:edit`. Audited as `mock.broker_binding.test`."
    ),
    responses={404: {"description": "No such binding on this version."}},
)
async def probe_mock_broker_binding(
    tenant_slug: str,
    project_id: str,
    version_record_id: str,
    binding_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> BrokerProbeResult:
    """Probe a binding, then audit the outcome."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.EDIT)
    _ = tenant_slug
    actor_id = _require_owner(project_id, version_record_id, auth_data)
    tenant_id = str(auth_data["tenant_id"])
    row = get_binding(tenant_id, version_record_id, binding_id)
    if row is None:
        raise _not_found()
    result = await probe_binding(row)
    _audit(
        tenant_id=tenant_id,
        action=AUDIT_TEST,
        auth_data=auth_data,
        actor_id=actor_id,
        binding=describe_row(row),
        extra={"status": result.status, "reason": result.reason, "cached": result.cached},
    )
    return result


@router.delete(
    _BASE + "/{binding_id}",
    status_code=204,
    response_class=Response,
    summary="Delete a broker binding",
    description=(
        "Remove the binding and its sealed credential. The version's events go back to "
        "WebSocket/SSE only.\n\nRequires `versions:edit`. Audited as "
        "`mock.broker_binding.delete`."
    ),
    responses={404: {"description": "No such binding on this version."}},
)
async def delete_mock_broker_binding(
    tenant_slug: str,
    project_id: str,
    version_record_id: str,
    binding_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Response:
    """Delete a binding, then audit it."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.EDIT)
    _ = tenant_slug
    actor_id = _require_owner(project_id, version_record_id, auth_data)
    tenant_id = str(auth_data["tenant_id"])
    removed = delete_binding(tenant_id, version_record_id, binding_id)
    if removed is None:
        raise _not_found()
    _audit(tenant_id=tenant_id, action=AUDIT_DELETE, auth_data=auth_data, actor_id=actor_id, binding=removed)
    return Response(status_code=204)
