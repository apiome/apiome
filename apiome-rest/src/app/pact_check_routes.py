"""``POST /v1/tenants/{tenant}/pact-broker/pacts/check`` — check a pact before publishing, PFX-8.4 (#7301).

A consumer sends an unpublished Pact document and the provider versions to compare it with —
``main``, ``deployed:<environment>``, ``version:<number>``, ``draft:<revision>`` — and reads, per
version and per interaction, whether the provider's contract matches, differs, or does not declare
the operation. It is the verdict a publish would record against that version
(:mod:`app.pact_check_store`), and **nothing is written**.

The route sits under the broker base URL so ``apiome pact check`` reaches it with the same
``PACT_BROKER_BASE_URL`` (and tenant-host alias) as every other ``apiome pact`` command. It is not
a Pact Broker endpoint; the compatibility catalog lists it as an Apiome addition.

Requires ``pacts:view``; a ``draft:`` selector also needs ``versions:view``. Bounded: one pact of
at most ``pact_max_bytes``, 1 to 10 selectors, at most 20 provider versions; budgeted per workspace
by ``pact_check_rate_limit_per_minute``.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from .config import settings
from .database import db
from .pact_broker_auth import validate_broker_authentication
from .pact_broker_routes import _body_reader, _http_error, _tenant_id
from .pact_check import (
    CODE_CHECK_RATE_LIMITED,
    KIND_DRAFT,
    MAX_SELECTORS,
    PactCheckError,
    parse_check_request,
)
from .pact_check_store import run_check
from .pact_publication import PactPublicationError, pact_provider_name, validate_pact_document
from .pacticipant import PacticipantValidationError
from .permissions import Action, Resource, enforce_permission
from .rate_limit import FixedWindowRateLimiter

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["pact-broker"])

_check_limiter = FixedWindowRateLimiter()

#: The envelope around the pact (``{"pact": …, "against": […]}``) gets a little room over the pact limit.
_read_check_body = _body_reader(1)

_EXAMPLE = {
    "pact": {
        "consumer": {"name": "Orders UI"},
        "provider": {"name": "Billing Service"},
        "interactions": [
            {
                "description": "a request for an invoice",
                "providerStates": [{"name": "an invoice exists"}],
                "request": {"method": "GET", "path": "/invoices/42"},
                "response": {"status": 200, "body": {"id": 42, "amount": 1200, "currency": "EUR"}},
            }
        ],
        "metadata": {"pactSpecification": {"version": "3.0.0"}},
    },
    "against": ["main", "deployed:production", "draft:latest"],
}

_BODY = {
    "required": True,
    "content": {
        "application/json": {
            "schema": {
                "type": "object",
                "required": ["pact", "against"],
                "additionalProperties": False,
                "properties": {
                    "pact": {"type": "object", "description": "The Pact document (v1 to v4), as a JSON object."},
                    "against": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": MAX_SELECTORS,
                        "items": {"type": "string"},
                        "description": (
                            "Provider-version selectors: `main`, `deployed:<environment>`, "
                            "`version:<number>`, `draft:<revision>` (a label, revision id or `latest`)."
                        ),
                    },
                },
            },
            "example": _EXAMPLE,
        }
    },
}


def _enforce_check_budget(tenant_id: str) -> None:
    """Count one check against the workspace's budget.

    Args:
        tenant_id: The caller's tenant.

    Raises:
        HTTPException: 429 ``pact-check-rate-limited`` with ``Retry-After``.
    """
    if not settings.rate_limit_enabled:
        return
    limit = max(1, settings.pact_check_rate_limit_per_minute)
    window = max(1, settings.rate_limit_window_seconds)
    allowed, _remaining, _reset_after, retry_after = _check_limiter.check(
        f"pactcheck:{tenant_id}", limit, window, time.monotonic()
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={
                "code": CODE_CHECK_RATE_LIMITED,
                "message": f"this workspace may run {limit} checks per {window} seconds; retry later",
            },
            headers={"Retry-After": str(retry_after)},
        )


def _refused(exc: PactCheckError) -> HTTPException:
    """A ``422 pact-check-invalid`` naming where the request is wrong."""
    return HTTPException(status_code=422, detail={"code": exc.code, "message": str(exc), "pointer": exc.pointer})


@router.post(
    "/{tenant_slug}/pact-broker/pacts/check",
    summary="Check a pact against provider versions before publishing",
    description=(
        "Compare an unpublished pact with the provider contracts of several provider versions at "
        "once, and store nothing. `against` names them: `main` (the newest version on the "
        "provider's main branch with a contract), `deployed:<environment>` (every version deployed "
        "to or released in it), `version:<number>`, and `draft:<revision>` (a revision of the "
        "Apiome project the provider is bound to, rendered as it stands).\n\n"
        "- **The verdict a publish would record.** Each version's `verdict` and `success` are what "
        "publishing this pact would store as its bi-directional verification result, evidence "
        "policy included (`unverified` when the contract has no passing self-verification).\n"
        "- **Per interaction**, `outcome` is `match`, `differs` or `not-in-spec`, with the "
        "failures; a row that does not match carries `expected` (what the pact needs) and "
        "`declared` (what the contract declares), each at most 8 KB.\n"
        "- **Nothing dropped.** A selector that names nothing is listed in `unresolved` with the "
        "reason; versions over the limit of 20 in `skipped`. `summary.success` is true only when "
        "every compared version passes and nothing is unresolved or skipped.\n\n"
        "Requires `pacts:view`; a `draft:` selector also needs `versions:view`. Not a Pact Broker "
        "endpoint."
    ),
    openapi_extra={"requestBody": _BODY},
    responses={
        413: {"description": "`pact-too-large`: the request is over the size limit."},
        422: {
            "description": (
                "`pact-check-invalid` or `pact-invalid`, with `pointer`: a malformed request, an unknown "
                "field or selector, or a document that is not a pact."
            )
        },
        429: {"description": "`pact-check-rate-limited`: over the workspace's check budget; see `Retry-After`."},
    },
)
def check_pact(
    tenant_slug: str,
    raw: bytes = Depends(_read_check_body),
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> Dict[str, Any]:
    """Check one pact against the provider versions the selectors name.

    Args:
        tenant_slug: The tenant in the URL.
        raw: The request body, already size-limited.
        auth_data: The authenticated principal.

    Returns:
        The provider, the pact's content address, ``summary``, one entry per version in
        ``results``, and ``unresolved`` / ``skipped``.

    Raises:
        HTTPException: 403 without ``pacts:view`` (or ``versions:view`` for a draft); 413 over the
            size limit; 422 for a malformed request or pact; 429 over the check budget.
    """
    del tenant_slug  # the tenant comes from the credential
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    tenant_id = _tenant_id(auth_data)
    _enforce_check_budget(tenant_id)
    try:
        try:
            body = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, RecursionError) as exc:
            raise PactCheckError("the request body is not valid JSON") from exc
        request = parse_check_request(body)
    except PactCheckError as exc:
        raise _refused(exc) from exc
    if any(selector.kind == KIND_DRAFT for selector in request.selectors):
        enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    try:
        interactions = validate_pact_document(request.pact)
    except PactPublicationError as exc:
        pointer = f"/pact{exc.pointer or ''}"
        raise HTTPException(
            status_code=422, detail={"code": exc.code, "message": f"/pact: {exc}", "pointer": pointer}
        ) from exc
    if not pact_provider_name(request.pact):
        raise _refused(
            PactCheckError("/pact/provider/name: the pact must name its provider", pointer="/pact/provider/name")
        )
    try:
        outcome = run_check(db, tenant_id, request, interactions=interactions)
    except PacticipantValidationError as exc:
        raise _http_error(exc) from exc
    return outcome.to_dict()
