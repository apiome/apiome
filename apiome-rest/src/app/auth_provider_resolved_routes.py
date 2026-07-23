"""Internal resolved-provider-config read path for the merge resolver (OLO-8.5, #4971).

The DB-over-env merge resolver in apiome-ui (``lib/auth/provider-config-resolver.ts``) needs the
*decrypted* provider config to build NextAuth providers — DB value where set, else ``process.env``.
That happens **during a login request**, a context with no user session and no admin session, so the
admin surface (OLO-8.4, masked + admin-session-gated) cannot serve it. This module adds the
server-to-server read path the OLO-8.3/8.4 design kept pointing at ("decryption happens server-side
only, the REST/8.5 read path"):

``GET /v1/internal/auth-providers/resolved`` → for every stored provider row, the resolved
``enabled`` / ``client_id`` / **decrypted** ``client_secret`` / ``config`` extras.

Security posture:

* **Service-token gated.** Because there is no user/admin identity at login time, the endpoint is
  gated by a shared secret both services hold (``INTERNAL_SERVICE_TOKEN``), presented in
  ``X-Internal-Service-Token`` and compared in constant time. It is **fail-closed**: with no token
  configured the endpoint returns ``503`` and never serves a decrypted secret.
* **Server-to-server only.** This is the one surface that returns decrypted secrets, so it must only
  ever be reached from apiome-ui server code holding the token — never proxied to a browser.
* **Degrade, don't break login.** A provider whose stored secret cannot be decrypted (missing /
  rotated-away KEK, corrupt blob) is *omitted* from the response and logged (secret-free) rather than
  failing the whole call — the resolver then falls back to env for that provider (OLO-8.6: a config
  fault degrades to env, it does not take down sign-in). A total DB failure surfaces as ``503`` and
  the resolver likewise degrades to env.
"""

from __future__ import annotations

import hmac
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from .auth_provider_secret_crypto import ProviderSecretDecryptionError, unseal_provider_secret
from .config import settings
from .database import db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/internal/auth-providers", tags=["internal-auth-providers"])


# ---------------------------------------------------------------------------
# Service-token gate
# ---------------------------------------------------------------------------


def require_internal_service(
    x_internal_service_token: Optional[str] = Header(default=None, alias="X-Internal-Service-Token"),
) -> None:
    """FastAPI dependency: allow only callers presenting the shared internal service token.

    Args:
        x_internal_service_token: Value of the ``X-Internal-Service-Token`` header, if present.

    Raises:
        HTTPException: ``503`` when no ``INTERNAL_SERVICE_TOKEN`` is configured (fail closed — the
            resolved read path is disabled and no decrypted secret is ever served); ``401`` when the
            header is absent; ``403`` when it is present but does not match.
    """
    configured = (settings.internal_service_token or "").strip()
    if not configured:
        raise HTTPException(
            status_code=503,
            detail=(
                "Resolved auth-provider read path is disabled: set INTERNAL_SERVICE_TOKEN to enable "
                "it (OLO-8.5)."
            ),
        )
    if not x_internal_service_token:
        raise HTTPException(
            status_code=401,
            detail="Internal service authentication required.",
        )
    # Constant-time comparison so a mismatch does not leak token bytes via timing.
    if not hmac.compare_digest(x_internal_service_token, configured):
        raise HTTPException(
            status_code=403,
            detail="Invalid internal service token.",
        )


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class ResolvedProviderConfig(BaseModel):
    """One provider's resolved DB config, secret decrypted, for the login-time resolver.

    Every field is the DB value or ``null`` when the DB has no value for it — the apiome-ui resolver
    overlays these onto ``process.env`` (DB value wins; ``null``/blank ⇒ env fallback).
    """

    enabled: Optional[bool] = Field(
        None, description="Explicit enable toggle; null ⇒ env-derived enablement (creds presence)."
    )
    client_id: Optional[str] = Field(None, description="OAuth client id, or null to fall back to env.")
    client_secret: Optional[str] = Field(
        None,
        description="Decrypted OAuth client secret, or null to fall back to env. Server-to-server only.",
    )
    config: Dict[str, Any] = Field(
        default_factory=dict,
        description="Non-secret provider extras (env-var-keyed JSONB); overlaid onto env by the resolver.",
    )


class ResolvedProviderConfigResponse(BaseModel):
    """Payload of ``GET /v1/internal/auth-providers/resolved``: stored providers only, by id."""

    providers: Dict[str, ResolvedProviderConfig] = Field(
        default_factory=dict,
        description="Map of provider_id → resolved DB config; a provider with no stored row is absent.",
    )


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.get(
    "/resolved",
    response_model=ResolvedProviderConfigResponse,
    responses={
        401: {"description": "No internal service token presented."},
        403: {"description": "Internal service token invalid."},
        503: {"description": "Resolved read path disabled (no INTERNAL_SERVICE_TOKEN configured)."},
    },
)
async def get_resolved_auth_providers(
    _: None = Depends(require_internal_service),
) -> ResolvedProviderConfigResponse:
    """Return decrypted DB provider config for the login-time merge resolver (OLO-8.5).

    Reads every stored provider row and decrypts its secret in-process. A provider whose secret
    cannot be decrypted is omitted (and logged secret-free) so one broken row degrades to env rather
    than breaking sign-in for every provider.

    Returns:
        A ``{provider_id: ResolvedProviderConfig}`` map for providers that have a stored row and
        whose secret (if any) decrypted successfully.
    """
    resolved: Dict[str, ResolvedProviderConfig] = {}
    for row in db.list_auth_provider_config_with_secret():
        provider_id = row["provider_id"]
        try:
            secret = unseal_provider_secret(row.get("client_secret_encrypted"), row.get("enc_key_id"))
        except ProviderSecretDecryptionError as exc:
            # Secret-free by construction (unseal never echoes plaintext). Omit → env fallback.
            logger.warning(
                "resolved provider config: omitting %s — its stored secret could not be decrypted: %s",
                provider_id,
                exc,
            )
            continue
        resolved[provider_id] = ResolvedProviderConfig(
            enabled=row.get("enabled"),
            client_id=row.get("client_id"),
            client_secret=secret,
            config=row.get("config") or {},
        )
    return ResolvedProviderConfigResponse(providers=resolved)
