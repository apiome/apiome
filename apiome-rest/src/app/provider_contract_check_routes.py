"""``POST …/contracts/provider/{p}/version/{v}/check`` — check a provider contract first, PFX-8.6 (#7303).

The **Publish a provider contract** page's *Compare only* and its live *If you publish now* aside:
the body a publish would send (``PUT …/contracts/provider/{p}/version/{v}``) — or, instead of
``content``, a ``contentUrl`` to read the document from once — and the answer is what that
publish would record: per consumer pact, the verdict and its failures; the operations no compared
pact uses; the evidence as read; and whether the version already has a different contract (a
publish would be ``409``). **Nothing is written** (:mod:`app.provider_contract_check`).

The route sits under the broker base URL beside the publish route, so a pipeline reaches it with
the same base URL and token. It is not a Pact Broker endpoint; the compatibility catalog lists it
as an Apiome addition.

Requires ``pacts:view``; ``apiomeVersion`` also needs ``versions:view`` and a cited Apiome report
``verification_evidence:view``. Budgeted with the pre-publish pact check
(``pact_check_rate_limit_per_minute``).
"""

from __future__ import annotations

import json
from typing import Any, Dict

from fastapi import APIRouter, Depends

from .config import settings
from .database import db
from .pact_broker_auth import validate_broker_authentication
from .pact_broker_routes import _body_reader, _http_error, _tenant_id
from .pact_check_routes import _enforce_check_budget
from .pacticipant import PacticipantValidationError
from .permissions import Action, Resource, enforce_permission
from .provider_contract import CODE_REQUEST_INVALID, ProviderContractError
from .provider_contract_check import FetchedContract, fetch_contract_url, run_contract_check
from .provider_contract_routes import parse_publish_body, prepare_request_contract, self_verification_document

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["pact-broker"])

#: As the publish route: a base64 document is 4/3 of its size, and the results ride along.
_read_check_body = _body_reader(2)

#: Fields a publish sends that a check accepts and does not use; named back in ``ignored``.
_UNUSED_FIELDS = ("tags", "buildUrl")

_BODY = {
    "required": True,
    "content": {
        "application/json": {
            "schema": {
                "type": "object",
                "description": (
                    "The body of `PUT …/contracts/provider/{provider}/version/{providerVersion}` — `content`, "
                    "`contractType`, `contentType`, `apiomeVersion`, `branch`, `verificationResults` — or "
                    "`contentUrl` in place of `content`. `tags` and `buildUrl` are accepted and listed in `ignored`."
                ),
                "properties": {
                    "content": {"type": "string", "description": "The document, base64-encoded."},
                    "contentUrl": {
                        "type": "string",
                        "format": "uri",
                        "description": "Read the document from this http(s) URL, once, instead of `content`. "
                        "The bytes come back in `fetched.content` to publish inline.",
                    },
                    "contractType": {"type": "string", "enum": ["oas", "asyncapi"]},
                    "contentType": {"type": "string"},
                    "apiomeVersion": {"type": "string", "description": "`<project>@<version>`."},
                    "branch": {"type": "string", "description": "Selects the branch's pacts, as a publish does."},
                    "verificationResults": {
                        "type": "object",
                        "description": "As for the publish: read into `selfVerification`, never stored.",
                    },
                },
            },
            "example": {"apiomeVersion": "billing-api@2.7.0", "branch": "main"},
        }
    },
}


def _with_fetched_content(raw: bytes) -> tuple[bytes, FetchedContract | None]:
    """Replace a ``contentUrl`` with the ``content`` read from it.

    Args:
        raw: The request body.

    Returns:
        The body to parse as a publish request, and what was fetched (``None`` without a URL).

    Raises:
        ProviderContractError: a body that is not a JSON object, ``contentUrl`` sent with
            ``content`` or ``apiomeVersion`` or not a string, or a URL that cannot be read.
    """
    try:
        body = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, RecursionError) as exc:
        raise ProviderContractError(CODE_REQUEST_INVALID, "the request body is not valid JSON", pointer="") from exc
    if not isinstance(body, dict) or "contentUrl" not in body:
        return raw, None
    url = body.pop("contentUrl")
    if not isinstance(url, str) or not url.strip():
        raise ProviderContractError(CODE_REQUEST_INVALID, "contentUrl must be an http(s) URL", pointer="/contentUrl")
    if body.get("content") is not None or body.get("apiomeVersion") is not None:
        raise ProviderContractError(
            CODE_REQUEST_INVALID,
            "send one of 'content', 'contentUrl' and 'apiomeVersion'",
            pointer="/contentUrl",
        )
    fetched = fetch_contract_url(url.strip(), max_bytes=settings.pact_max_bytes)
    body["content"] = fetched.to_dict()["content"]
    return json.dumps(body).encode("utf-8"), fetched


@router.post(
    "/{tenant_slug}/pact-broker/contracts/provider/{provider}/version/{provider_version}/check",
    summary="Check a provider contract before publishing it",
    description=(
        "Say what publishing this provider contract would record, and store nothing. Send the body of the "
        "publish (`PUT …/contracts/provider/{provider}/version/{providerVersion}`) — or `contentUrl` instead "
        "of `content` to read the document from a URL once (public addresses only; the bytes come back in "
        "`fetched` so the same document can be published).\n\n"
        "- **The pacts a publish would compare with**: each consumer's main-branch pact, the pacts deployed "
        "or released, the latest pact of each consumer on `branch`, and the pacts compared before with a "
        "contract of that branch — compared with the same engine and evidence policy, so `results[].verdict` "
        "and `success` are what the publish would store (`unverified` when the evidence does not pass). Each "
        "result names the consumer version's `environments` and its first failures.\n"
        "- **`coverage`**: the contract's operations, and in `unused` the ones no compared pact touches "
        "(OpenAPI only; `coverageReason` says why it is `null`).\n"
        "- **`existing`**: the contract this version already published — `sameContent: false` means the "
        "publish would be refused with `409`; `summary.publishable` says so.\n"
        "- **`selfVerification`**: the evidence as a publish would read it.\n\n"
        "An unknown provider is not an error: it has no pacts yet (`provider.exists: false`). Requires "
        "`pacts:view`, `versions:view` with `apiomeVersion`, `verification_evidence:view` with "
        "`providerVerificationReportId`. Not a Pact Broker endpoint."
    ),
    openapi_extra={"requestBody": _BODY},
    responses={
        413: {"description": "`provider-contract-too-large`: the document or the request is over the size limit."},
        422: {
            "description": (
                "As for the publish (`provider-contract-invalid` with the pointer into the document, "
                "`provider-contract-request-invalid`, the evidence refusals), and "
                "`provider-contract-url-unreadable` for a `contentUrl` that is refused or cannot be read."
            )
        },
        429: {"description": "`pact-check-rate-limited`: over the workspace's check budget; see `Retry-After`."},
    },
)
def check_provider_contract(
    tenant_slug: str,
    provider: str,
    provider_version: str,
    raw: bytes = Depends(_read_check_body),
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> Dict[str, Any]:
    """Check one provider contract against the pacts a publish would compare it with.

    Args:
        tenant_slug: The tenant in the URL (the credential's tenant scopes the work).
        provider: The provider's name or handle.
        provider_version: The provider version it would be published for.
        raw: The request body, already size-limited.
        auth_data: The authenticated principal.

    Returns:
        ``provider``, ``providerVersion``, ``contract``, ``selfVerification``, ``existing``,
        ``summary``, ``results``, ``coverage`` and, as sent, ``fetched`` and ``ignored``.

    Raises:
        HTTPException: 403 without ``pacts:view`` (or the permission a source or report needs);
            413 over the size limit; 422 for an unreadable request, document, report or URL;
            429 over the check budget.
    """
    del tenant_slug  # the tenant comes from the credential
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    tenant_id = _tenant_id(auth_data)
    _enforce_check_budget(tenant_id)
    try:
        prepared, fetched = _with_fetched_content(raw)
        body = parse_publish_body(prepared)
        contract, evidence = prepare_request_contract(body, provider=provider, auth_data=auth_data, tenant_id=tenant_id)
        outcome = run_contract_check(
            db,
            tenant_id,
            provider_ref=provider,
            provider_version=provider_version,
            branch=(body.branch or "").strip() or None,
            contract=contract,
            evidence=evidence,
            self_verification=self_verification_document(contract),
            fetched=fetched,
        )
    except (ProviderContractError, PacticipantValidationError) as exc:
        raise _http_error(exc) from exc
    payload = outcome.to_dict()
    sent = json.loads(prepared.decode("utf-8"))
    ignored = [name for name in _UNUSED_FIELDS if isinstance(sent, dict) and sent.get(name)]
    if ignored:
        payload["ignored"] = [
            {"field": name, "reason": "a check records no version, so it is not used"} for name in ignored
        ]
    return payload
