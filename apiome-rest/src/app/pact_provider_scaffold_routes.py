"""Provider test scaffolding route — PFX-8.19 (#7316).

``GET /v1/tenants/{tenant}/pact-provider-tests/{provider}?language=…`` writes a ready provider
verification test (pact-js, pact-jvm, pact-go or pact-python) from the provider's pacts: the broker
from ``PACT_BROKER_BASE_URL`` / ``PACT_BROKER_TOKEN``, the recommended consumer version selectors,
pending pacts on, and one state handler stub per provider state the pacts name, with the states the
provider has not registered in Apiome flagged (:mod:`app.pact_provider_scaffold`).

Nothing is stored and no secret is written into the file. Requires ``pacts:view``; every read is
scoped by the caller's tenant. It sits beside the Pact Broker surface, not under ``…/pact-broker``,
because no Pact Broker or PactFlow client knows it.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query

from .database import db
from .pact_broker_auth import validate_broker_authentication
from .pact_provider_scaffold import CODE_LANGUAGE_UNSUPPORTED, LANGUAGES, ScaffoldError
from .pact_provider_scaffold_service import scaffold_for_provider
from .pact_publication import PactPublicationError
from .pact_verifier_service import PactVerifierError
from .pacticipant import CODE_NOT_FOUND as CODE_PACTICIPANT_NOT_FOUND
from .pacticipant import PacticipantValidationError
from .permissions import Action, Resource, enforce_permission

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["pact-broker"])

_STATUS = {CODE_LANGUAGE_UNSUPPORTED: 422, CODE_PACTICIPANT_NOT_FOUND: 404}


def _tenant_id(auth_data: Dict[str, Any]) -> str:
    """The authenticated tenant id, or a 403."""
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this credential.")
    return str(tenant_id)


@router.get(
    "/{tenant_slug}/pact-provider-tests/{provider}",
    summary="Scaffold a provider verification test",
    description=(
        "Writes a provider verification test in `language` — `typescript` (pact-js), `java` (pact-jvm, "
        "JUnit 5), `go` (pact-go v2) or `python` (pact-python 2) — from the pacts the recommended "
        'selectors choose (`{"mainBranch": true}`, `{"deployedOrReleased": true}`, pending on). The '
        "file reads the broker from `PACT_BROKER_BASE_URL` and `PACT_BROKER_TOKEN`, so no secret is "
        "written into it, and carries one state handler stub per provider state with the parameters "
        "the pacts send (`EXAMPLE_PARAMETERS`).\n\n"
        "`states` lists each state with its parameters, an example, whether the provider registered "
        "it in Apiome and how many interactions name it; `unregistered` counts those it has not. "
        "`notices` lists every flagged state (`provider-scaffold-state-unregistered`), every state "
        "left out with the reason (`provider-scaffold-state-left-out`) and a provider without pacts "
        "(`provider-scaffold-no-pacts`). Nothing is stored. Requires `pacts:view`."
    ),
    responses={
        403: {"description": "The credential lacks `pacts:view`."},
        404: {"description": "`pacticipant-not-found`: no such provider in this workspace."},
        422: {
            "description": "`provider-scaffold-language-unsupported`, or `pact-verify-too-many-pacts` "
            "when the selectors choose more pacts than a run takes."
        },
    },
)
def scaffold_provider_tests(
    tenant_slug: str,
    provider: str,
    language: str = Query(..., max_length=20, description=f"One of: {', '.join(LANGUAGES)}."),
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> Dict[str, Any]:
    """Write a provider's verification test.

    Args:
        tenant_slug: The tenant in the URL (the tenant read is the credential's).
        provider: The provider's handle, id or name.
        language: The language.
        auth_data: The authenticated principal.

    Returns:
        The file, its states and notices.

    Raises:
        HTTPException: 403 without ``pacts:view``; 404 / 422 as documented.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    try:
        return scaffold_for_provider(db, _tenant_id(auth_data), provider, language).as_json()
    except (ScaffoldError, PacticipantValidationError, PactPublicationError, PactVerifierError) as exc:
        code = getattr(exc, "code", "")
        default = 422 if isinstance(exc, (ScaffoldError, PactVerifierError)) else 400
        raise HTTPException(status_code=_STATUS.get(code, default), detail={"code": code, "message": str(exc)}) from exc
