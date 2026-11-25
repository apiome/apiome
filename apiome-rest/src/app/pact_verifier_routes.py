"""``POST …/pact-verifier/pacts/provider/{provider}/verify`` — the hosted Pact verifier, PFX-3.2 (#6932).

One request does what a provider's Pact verifier does in CI: it selects the pacts the provider
must honour, replays every interaction against a registered verification target, and publishes a
verification result per pact, so the matrix and can-i-deploy answer from it. The work is
:func:`app.pact_verifier_service.verify_provider_pacts`; this module is its HTTP face.

It lives beside the Pact Broker surface, not under ``…/pact-broker``, because no Pact Broker or
PactFlow client knows it; that surface stays the catalogued, PactFlow-compatible one
(:mod:`app.pact_broker_compat`). The results it publishes are read there.

**Permissions.** The run publishes verification results (``pacts:create`` on the provider) and
writes verification evidence (``verification_evidence:create``); both are required. A workspace
API key is accepted as a bearer token, as on the broker surface. Every lookup is scoped to the
authenticated tenant, so a provider or target of another workspace is a ``404``.

**Status codes.** A run that happened is ``200`` whatever it found — ``success`` and ``outcome``
say how it went. Only a run that could not start is an error.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request

from .consumer_contract_store import actor_from_auth
from .database import db
from .pact_broker_auth import validate_broker_authentication
from .pact_broker_routes import _base_url, _http_error
from .pact_publication import PactPublicationError
from .pact_verifier_service import (
    CODE_TARGET_AUTH_UNAVAILABLE,
    CODE_TOO_MANY_PACTS,
    PactVerifierError,
    PactVerifyRequest,
    PactVerifyResponse,
    verify_provider_pacts,
)
from .pacticipant import PacticipantValidationError
from .permissions import Action, Resource, enforce_permission
from .verification_target import CODE_NOT_FOUND as CODE_TARGET_NOT_FOUND
from .verification_target import TargetValidationError

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["pact-broker"])

_VERIFIER_STATUS = {CODE_TOO_MANY_PACTS: 422, CODE_TARGET_AUTH_UNAVAILABLE: 422}


def _tenant_id(auth_data: Dict[str, Any]) -> str:
    """The authenticated tenant id, or a 403."""
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this credential.")
    return str(tenant_id)


@router.post(
    "/{tenant_slug}/pact-verifier/pacts/provider/{provider}/verify",
    response_model=PactVerifyResponse,
    summary="Verify a provider against its pacts (hosted verifier)",
    description=(
        "Run provider verification from Apiome (PFX-3.2): select the pacts the provider must "
        "honour, replay each interaction against a registered verification target, and publish a "
        "verification result per pact — no Pact library on the provider's side.\n\n"
        "**Selection.** `selection` is the body of `…/pact-broker/pacts/provider/{provider}/"
        "for-verification`, unchanged (consumer-version selectors, pending and work-in-progress "
        "pacts). At most 25 pacts per run.\n\n"
        "**Replay.** Each pact is compiled into its contract suite (the manifest and digest of "
        "`POST …/pact-suites/…`) and replayed on the contract runner under the target's policy: "
        "SSRF guard, timeouts, retries (transport failures only) and credentials come from the "
        "target, never from this request.\n\n"
        "**Matching.** The status, the recorded headers and the body are compared under the "
        "pact's matching rules. Each mismatch names the interaction, the field (a JSON Pointer "
        "into the response body, or the header), the rule that failed, and the expected and "
        "actual values. A rule the verifier cannot apply fails the interaction; it never passes "
        "silently.\n\n"
        "**Mutating interactions** (`POST`, `PUT`, `PATCH`, `DELETE`) are sent only when the "
        "target's policy allows mutating methods **and** `verification.allow_mutating` is true. "
        "A run cannot widen the target's policy.\n\n"
        "**Provider states.** An interaction that names a provider state is skipped with "
        "`provider-state-not-set-up` unless `verification.replay_without_state_setup` is true "
        "(the target already holds the data).\n\n"
        "**Publishing.** A pact is `passed` when every interaction was replayed and matched, "
        "`failed` when one did not match, and `incomplete` when nothing failed but something "
        "was skipped, unreachable or cannot be replayed. `passed` and `failed` are published as "
        "verification results against `provider_version` (and `provider_branch`), and show in the "
        "matrix and can-i-deploy; `incomplete` publishes nothing. `publish: false` is a dry run.\n\n"
        "The answer is `200` for any run that happened; read `success` and `outcome`. Requires "
        "`pacts:create` and `verification_evidence:create`."
    ),
    responses={
        400: {"description": "`pact-selector-invalid`, or a malformed provider version, branch or build URL."},
        404: {"description": "`pacticipant-not-found` or `target-not-found` in this workspace."},
        422: {
            "description": (
                "`pact-verify-too-many-pacts`, `pact-verify-target-auth-unavailable`, or a target "
                "that cannot be used (`target-disabled`, `target-protocol-mismatch`, a URL refusal)."
            )
        },
    },
)
def verify_provider(
    request: Request,
    tenant_slug: str,
    provider: str,
    body: PactVerifyRequest,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> PactVerifyResponse:
    """Verify one provider against the pacts its selection chooses.

    Args:
        request: The request (its origin shapes the published results' links).
        tenant_slug: The tenant in the URL (the authenticated tenant scopes every lookup).
        provider: The provider's handle, id or name.
        body: Target, provider version, selection and what the run may send.
        auth_data: The authenticated principal.

    Returns:
        The run, one entry per pact.

    Raises:
        HTTPException: 403 without ``pacts:create`` or ``verification_evidence:create``; 400, 404
            and 422 as the route documents.
    """
    user_id = enforce_permission(db, auth_data, Resource.PACTS, Action.CREATE, target=provider)
    enforce_permission(db, auth_data, Resource.VERIFICATION_EVIDENCE, Action.CREATE)
    try:
        return verify_provider_pacts(
            db,
            _tenant_id(auth_data),
            provider,
            body,
            actor=actor_from_auth(auth_data, user_id),
            broker_base=_base_url(request, tenant_slug),
        )
    except (PactPublicationError, PacticipantValidationError) as exc:
        raise _http_error(exc) from exc
    except TargetValidationError as exc:
        status = 404 if exc.code == CODE_TARGET_NOT_FOUND else 422
        raise HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)}) from exc
    except PactVerifierError as exc:
        raise HTTPException(
            status_code=_VERIFIER_STATUS.get(exc.code, 422), detail={"code": exc.code, "message": str(exc)}
        ) from exc
