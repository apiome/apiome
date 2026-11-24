"""``/v1/tenants/{tenant_slug}/pact-broker`` — Pact publication and retrieval, PFX-1.2 (#6915).

The part of Apiome that speaks the Pact Broker's API, so the ``pact-broker`` CLI and the Pact
libraries publish to it by changing only their broker base URL and token:

* ``GET  …/pact-broker`` — the index: the HAL links a client discovers the other routes from;
* ``POST …/pact-broker/contracts/publish`` — publish the pacts of one consumer version, with its
  branch, tags and build URL (what ``pact-broker publish`` and pact-js ``publishPacts`` call);
* ``PUT  …/pact-broker/pacts/provider/{p}/consumer/{c}/version/{v}`` — publish one pact;
* ``GET  …/pact-broker/pacts/provider/{p}/consumer/{c}/version/{v}`` — the pact of that version;
* ``GET  …/pact-broker/pacts/provider/{p}/consumer/{c}/latest`` — the latest pact of the pair;
* ``GET  …/pact-broker/pacts/provider/{p}/consumer/{c}/pact-version/{sha}`` — a pact by its
  content address.

The base URL a client is given is ``https://<api>/v1/tenants/<tenant>/pact-broker``, or — where the
operator configured it — the tenant-host alias ``https://<tenant>.<suffix>``
(:mod:`app.pact_broker_host`). Links in a response lead back to whichever the client used.

Reads need ``pacts:view`` and publishing needs ``pacts:create``. A workspace API key may be sent
as ``Authorization: Bearer <key>`` here (:mod:`app.pact_broker_auth`), because that is the only
credential Pact tooling sends.

Responses are ``application/hal+json`` in the Pact Broker's shape. Refusals keep Apiome's shape:
``{"detail": {"code", "message", "pointer"}}``, where ``pointer`` locates the problem.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from .config import settings
from .consumer_contract_store import actor_from_auth
from .database import db
from .pact_broker_auth import validate_broker_authentication
from .pact_broker_host import alias_base_url
from .pact_publication import (
    CODE_PACT_CONFLICT,
    CODE_PACT_INVALID,
    CODE_PACT_NOT_FOUND,
    CODE_PACT_TOO_LARGE,
    CODE_PUBLISH_INVALID,
    CODE_PUBLISH_RATE_LIMITED,
    CODE_PUBLISH_UNSUPPORTED,
    MAX_CONTRACTS_PER_REQUEST,
    PactPublicationError,
    PactRecord,
    PublishContractsRequest,
    PublishedPact,
    decode_contract_content,
    prepare_pact,
)
from .pact_publication_store import (
    PublishOutcome,
    get_latest_pact,
    get_pact,
    get_pact_by_sha,
    publish_pacts,
)
from .pacticipant import (
    CODE_NOT_FOUND,
    CODE_VERSION_NOT_FOUND,
    PacticipantRecord,
    PacticipantValidationError,
    PacticipantVersionRecord,
    slugify_pacticipant_name,
)
from .pacticipant_store import get_pacticipant, get_version
from .permissions import Action, Resource, enforce_permission
from .rate_limit import FixedWindowRateLimiter

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["pact-broker"])

HAL_JSON = "application/hal+json"

#: The HTTP status of each refusal code; anything else is a 400.
_STATUS_BY_CODE = {
    CODE_PACT_INVALID: 422,
    CODE_PUBLISH_INVALID: 422,
    CODE_PUBLISH_UNSUPPORTED: 422,
    CODE_PACT_TOO_LARGE: 413,
    CODE_PACT_CONFLICT: 409,
    CODE_PACT_NOT_FOUND: 404,
    CODE_NOT_FOUND: 404,
    CODE_VERSION_NOT_FOUND: 404,
}

_publish_limiter = FixedWindowRateLimiter()

#: The ``logs`` level of each ``notices`` type in a publish result.
_LOG_LEVEL_BY_NOTICE = {"debug": "debug", "success": "info", "warning": "warn"}

_PAIR_PATH = "/pacts/provider/{provider}/consumer/{consumer}"

_LOCATED_422 = {
    "description": (
        "`pact-invalid`: the document is not a pact. `detail.pointer` is the JSON Pointer of the "
        "first problem in the document (for example `/interactions/2/request/method`) and "
        "`detail.message` says what is wrong there."
    )
}
_RATE_429 = {"description": "`pact-publish-rate-limited`: over the workspace's publish budget; see `Retry-After`."}
_TOO_LARGE_413 = {"description": "`pact-too-large`: the document or the request is over the size limit."}
_CONFLICT_409 = {
    "description": (
        "`pact-content-conflict`: this consumer version already published a different pact for the "
        "provider. Nothing of the request was stored. Publish under a new consumer version number."
    )
}

_PACT_EXAMPLE = {
    "consumer": {"name": "Billing Service"},
    "provider": {"name": "Ledger API"},
    "interactions": [
        {
            "description": "a request for an invoice",
            "request": {"method": "GET", "path": "/invoices/42"},
            "response": {"status": 200, "body": {"id": 42, "total": 1999}},
        }
    ],
    "metadata": {"pactSpecification": {"version": "2.0.0"}},
}

_PACT_BODY = {
    "required": True,
    "description": "The Pact document (specification 1.x to 4.x), exactly as the consumer's tests wrote it.",
    "content": {
        "application/json": {"schema": {"type": "object", "additionalProperties": True}, "example": _PACT_EXAMPLE}
    },
}

_PUBLISH_BODY = {
    "required": True,
    "content": {
        "application/json": {
            "schema": {
                "type": "object",
                "required": ["pacticipantName", "pacticipantVersionNumber", "contracts"],
                "properties": {
                    "pacticipantName": {"type": "string", "description": "The consumer publishing."},
                    "pacticipantVersionNumber": {
                        "type": "string",
                        "description": "Its application version, as the build reports it (a commit SHA).",
                    },
                    "branch": {"type": "string", "description": "The repository branch the version was built from."},
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tags for the version (at most 50).",
                    },
                    "buildUrl": {"type": "string", "description": "http(s) URL of the CI build."},
                    "contracts": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": MAX_CONTRACTS_PER_REQUEST,
                        "items": {
                            "type": "object",
                            "required": ["consumerName", "providerName", "content"],
                            "properties": {
                                "consumerName": {"type": "string", "description": "Must equal `pacticipantName`."},
                                "providerName": {"type": "string", "description": "The provider the pact is with."},
                                "specification": {"type": "string", "enum": ["pact"], "default": "pact"},
                                "contentType": {
                                    "type": "string",
                                    "enum": ["application/json"],
                                    "default": "application/json",
                                },
                                "content": {"type": "string", "description": "The Pact document, base64-encoded."},
                                "onConflict": {
                                    "type": "string",
                                    "enum": ["overwrite"],
                                    "description": "`merge` is not supported and is refused.",
                                },
                            },
                        },
                    },
                },
            },
            "example": {
                "pacticipantName": "Billing Service",
                "pacticipantVersionNumber": "2f4c1a9",
                "branch": "main",
                "tags": [],
                "buildUrl": "https://ci.example.com/builds/4812",
                "contracts": [
                    {
                        "consumerName": "Billing Service",
                        "providerName": "Ledger API",
                        "specification": "pact",
                        "contentType": "application/json",
                        "content": "eyJjb25zdW1lciI6eyJuYW1lIjoiQmlsbGluZyBTZXJ2aWNlIn0sIC4uLn0=",
                    }
                ],
            },
        }
    },
}


class HalJSONResponse(JSONResponse):
    """A JSON response labelled ``application/hal+json``, as a Pact Broker answers."""

    media_type = HAL_JSON


# ---------------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------------


def _tenant_id(auth_data: Dict[str, Any]) -> str:
    """Return the authenticated tenant id, or refuse.

    Args:
        auth_data: The resolved auth context.

    Returns:
        The tenant id.

    Raises:
        HTTPException: 403 when the credential carries no tenant.
    """
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this credential.")
    return str(tenant_id)


def _http_error(exc: Exception) -> HTTPException:
    """Translate a publication or registry refusal into the HTTP error a client sees.

    Args:
        exc: A :class:`PactPublicationError` or :class:`PacticipantValidationError`.

    Returns:
        The ``HTTPException`` to raise, carrying ``{"code", "message"}`` and, when the refusal is
        about one place, ``"pointer"``.
    """
    code = getattr(exc, "code", "")
    detail: Dict[str, Any] = {"code": code, "message": str(exc)}
    pointer = getattr(exc, "pointer", None)
    if pointer is not None:
        detail["pointer"] = pointer
    return HTTPException(status_code=_STATUS_BY_CODE.get(code, 400), detail=detail)


def _base_url(request: Request, tenant_slug: str) -> str:
    """The broker base URL the client used, which every link in a response starts with.

    Args:
        request: The request.
        tenant_slug: The tenant in the URL.

    Returns:
        The alias host when the request came through it; otherwise the path form under
        ``APIOME_API_PUBLIC_URL`` (when set) or the request's own origin. No trailing slash.
    """
    alias = alias_base_url(request.scope)
    if alias:
        return alias
    root = (settings.api_public_url or "").rstrip("/") or str(request.base_url).rstrip("/")
    return f"{root}/v1/tenants/{quote(tenant_slug, safe='')}/pact-broker"


def _pacticipant_url(base: str, slug: str) -> str:
    """The URL of a pacticipant on the broker surface."""
    return f"{base}/pacticipants/{quote(slug, safe='')}"


def _version_url(base: str, slug: str, number: str) -> str:
    """The URL of one version of a pacticipant on the broker surface."""
    return f"{_pacticipant_url(base, slug)}/versions/{quote(number, safe='')}"


def _pacticipant_document(base: str, pacticipant: PacticipantRecord) -> Dict[str, Any]:
    """Render a pacticipant the way a Pact Broker returns one.

    Args:
        base: The broker base URL.
        pacticipant: The pacticipant.

    Returns:
        Its name, repository and main branch, with a ``self`` link.
    """
    return {
        "name": pacticipant.name,
        "displayName": pacticipant.name,
        "repositoryUrl": pacticipant.repository_url,
        "mainBranch": pacticipant.main_branch,
        "createdAt": pacticipant.created_at,
        "updatedAt": pacticipant.updated_at,
        "_links": {
            "self": {"title": "Pacticipant", "name": pacticipant.name, "href": _pacticipant_url(base, pacticipant.slug)}
        },
    }


def _version_document(base: str, pacticipant: PacticipantRecord, version: PacticipantVersionRecord) -> Dict[str, Any]:
    """Render a pacticipant version the way a Pact Broker returns one.

    Args:
        base: The broker base URL.
        pacticipant: The owning pacticipant.
        version: The version.

    Returns:
        Its number and build URL, its branches and tags embedded, and links to itself and its owner.
    """
    return {
        "number": version.number,
        "buildUrl": version.build_url,
        "createdAt": version.created_at,
        "_embedded": {
            "branchVersions": [{"name": name} for name in version.branches],
            "tags": [{"name": name} for name in version.tags],
        },
        "_links": {
            "self": {
                "title": "Version",
                "name": version.number,
                "href": _version_url(base, pacticipant.slug, version.number),
            },
            "pb:pacticipant": {
                "title": "Pacticipant",
                "name": pacticipant.name,
                "href": _pacticipant_url(base, pacticipant.slug),
            },
        },
    }


def _pair_url(base: str, provider_slug: str, consumer_slug: str) -> str:
    """The URL prefix of the pacts between one provider and one consumer."""
    return f"{base}/pacts/provider/{quote(provider_slug, safe='')}/consumer/{quote(consumer_slug, safe='')}"


def _pact_url(base: str, pact: PactRecord) -> str:
    """The URL of the pact one consumer version published."""
    return f"{_pair_url(base, pact.provider_slug, pact.consumer_slug)}/version/{quote(pact.consumer_version, safe='')}"


def _pact_title(pact: PactRecord) -> str:
    """How a pact is named in a link: both applications and the consumer version."""
    return f"Pact between {pact.consumer_name} ({pact.consumer_version}) and {pact.provider_name}"


def _pact_document(base: str, pact: PactRecord) -> Dict[str, Any]:
    """Render a stored pact the way a Pact Broker returns one.

    The published document is returned as it is, with three additions a client relies on: the two
    pacticipant names (when the document left them out), ``createdAt``, and ``_links``.

    Args:
        base: The broker base URL.
        pact: The stored pact.

    Returns:
        The response body.
    """
    pair = _pair_url(base, pact.provider_slug, pact.consumer_slug)
    body = dict(pact.content)
    body.setdefault("consumer", {"name": pact.consumer_name})
    body.setdefault("provider", {"name": pact.provider_name})
    body["createdAt"] = pact.created_at
    body["_links"] = {
        "self": {"title": "Pact", "name": _pact_title(pact), "href": _pact_url(base, pact)},
        "pb:consumer": {
            "title": "Consumer",
            "name": pact.consumer_name,
            "href": _pacticipant_url(base, pact.consumer_slug),
        },
        "pb:consumer-version": {
            "title": "Consumer version",
            "name": pact.consumer_version,
            "href": _version_url(base, pact.consumer_slug, pact.consumer_version),
        },
        "pb:provider": {
            "title": "Provider",
            "name": pact.provider_name,
            "href": _pacticipant_url(base, pact.provider_slug),
        },
        "pb:pact-version": {
            "title": "Pact content version permalink",
            "name": pact.sha,
            "href": f"{pair}/pact-version/{pact.sha}",
        },
        "pb:latest-pact-version": {
            "title": "Latest version of this pact",
            "href": f"{pair}/latest",
        },
    }
    return body


def _enforce_publish_budget(tenant_id: str) -> None:
    """Count one publish request against the workspace's budget.

    Args:
        tenant_id: The caller's tenant.

    Raises:
        HTTPException: 429 ``pact-publish-rate-limited`` with ``Retry-After`` when over
            ``pact_publish_rate_limit_per_minute``.
    """
    if not settings.rate_limit_enabled:
        return
    limit = max(1, settings.pact_publish_rate_limit_per_minute)
    window = max(1, settings.rate_limit_window_seconds)
    allowed, _remaining, _reset_after, retry_after = _publish_limiter.check(
        f"pactpub:{tenant_id}", limit, window, time.monotonic()
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={
                "code": CODE_PUBLISH_RATE_LIMITED,
                "message": f"this workspace may publish {limit} times per {window} seconds; retry later",
            },
            headers={"Retry-After": str(retry_after)},
        )


def _body_reader(multiplier: int) -> Callable[..., Any]:
    """Build the dependency that reads a request body up to ``multiplier`` × the pact size limit.

    The body is read as a stream and abandoned at the limit, so an oversized upload is refused
    without being held in memory.

    Args:
        multiplier: 1 for a single pact; 2 for a bulk request, whose pacts are base64-encoded.

    Returns:
        An async dependency returning the body bytes, or raising 413 ``pact-too-large``.
    """

    async def read_body(request: Request) -> bytes:
        limit = max(1, settings.pact_max_bytes) * multiplier
        too_large = HTTPException(
            status_code=413,
            detail={"code": CODE_PACT_TOO_LARGE, "message": f"the request body is over the limit of {limit} bytes"},
        )
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > limit:
            raise too_large
        chunks: List[bytes] = []
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > limit:
                raise too_large
            chunks.append(chunk)
        return b"".join(chunks)

    return read_body


_read_pact_body = _body_reader(1)
_read_publish_body = _body_reader(2)


def _parse_publish_request(raw: bytes) -> PublishContractsRequest:
    """Parse and check the envelope of a bulk publish.

    Args:
        raw: The request body.

    Returns:
        The request.

    Raises:
        PactPublicationError: ``pact-publish-invalid`` with the pointer of the first malformed
            field, when a contract names another consumer, or when there are no or too many
            contracts.
    """
    try:
        body = PublishContractsRequest.model_validate_json(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        pointer = "".join(f"/{part}" for part in first.get("loc", ()))
        raise PactPublicationError(
            CODE_PUBLISH_INVALID, f"{pointer or '(request body)'}: {first.get('msg', 'invalid')}", pointer=pointer
        ) from exc
    if not 1 <= len(body.contracts) <= MAX_CONTRACTS_PER_REQUEST:
        raise PactPublicationError(
            CODE_PUBLISH_INVALID,
            f"a publish request carries 1 to {MAX_CONTRACTS_PER_REQUEST} contracts; this one has {len(body.contracts)}",
            pointer="/contracts",
        )
    consumer = slugify_pacticipant_name(body.pacticipant_name)
    seen: Dict[str, int] = {}
    for index, contract in enumerate(body.contracts):
        if slugify_pacticipant_name(contract.consumer_name) != consumer:
            raise PactPublicationError(
                CODE_PUBLISH_INVALID,
                f"contract {index} names the consumer '{contract.consumer_name}', but the request "
                f"publishes for '{body.pacticipant_name}'",
                pointer=f"/contracts/{index}/consumerName",
            )
        provider = slugify_pacticipant_name(contract.provider_name)
        if provider in seen:
            raise PactPublicationError(
                CODE_PUBLISH_INVALID,
                f"contracts {seen[provider]} and {index} are both for the provider "
                f"'{contract.provider_name}'; send one pact per provider",
                pointer=f"/contracts/{index}/providerName",
            )
        seen[provider] = index
    return body


def _notice(kind: str, text: str) -> Dict[str, str]:
    """One line of a publish result, in the Pact Broker's ``notices`` shape."""
    return {"type": kind, "text": text}


def _publish_notices(base: str, outcome: PublishOutcome) -> List[Dict[str, str]]:
    """The lines ``pact-broker publish`` prints for a result.

    Args:
        base: The broker base URL.
        outcome: What the request stored.

    Returns:
        One notice for the version and two per pact (what happened, and where to read it).
    """
    version = outcome.version.version
    described = f"{outcome.consumer.name} version {version.number}"
    extras = []
    if version.branches:
        extras.append("branch " + ", ".join(version.branches))
    if version.tags:
        extras.append("tags " + ", ".join(version.tags))
    notices = [
        _notice(
            "debug",
            f"{'Created' if outcome.version.created else 'Updated'} {described}"
            + (f" with {' and '.join(extras)}" if extras else ""),
        )
    ]
    for published in outcome.pacts:
        pact = published.pact
        target = f"for {described} and provider {pact.provider_name}"
        if published.replaced:
            notices.append(_notice("warning", f"Pact with changed content published {target}."))
        elif published.created:
            notices.append(_notice("success", f"Pact successfully published {target}."))
        else:
            notices.append(_notice("success", f"Pact successfully republished {target} with no content changes."))
        notices.append(_notice("debug", f"  View the published pact at {_pact_url(base, pact)}"))
    return notices


def _publish_result(base: str, outcome: PublishOutcome) -> Dict[str, Any]:
    """Render a bulk publish result the way a Pact Broker returns one.

    Args:
        base: The broker base URL.
        outcome: What the request stored.

    Returns:
        The response body: ``notices`` (and the same lines as ``logs``), the embedded pacticipant
        and version, and a link per pact.
    """
    version = outcome.version.version
    consumer = outcome.consumer
    notices = _publish_notices(base, outcome)
    return {
        "notices": notices,
        # The older spelling of the same lines, which some Pact clients still read.
        "logs": [
            {
                "level": _LOG_LEVEL_BY_NOTICE.get(notice["type"], "info"),
                "message": notice["text"],
                "deprecationWarning": "Replaced by notices",
            }
            for notice in notices
        ],
        "_embedded": {
            "pacticipant": _pacticipant_document(base, consumer),
            "version": _version_document(base, consumer, version),
        },
        "_links": {
            "pb:pacticipant": {
                "title": "Pacticipant",
                "name": consumer.name,
                "href": _pacticipant_url(base, consumer.slug),
            },
            "pb:pacticipant-version": {
                "title": "Pacticipant version",
                "name": version.number,
                "href": _version_url(base, consumer.slug, version.number),
            },
            "pb:pacticipant-version-tags": [
                {"title": "Tag", "name": tag, "href": _version_url(base, consumer.slug, version.number)}
                for tag in version.tags
            ],
            "pb:contracts": [
                {
                    "title": "Pact",
                    "name": _pact_title(published.pact),
                    "href": _pact_url(base, published.pact),
                    "pactVersionSha": published.pact.sha,
                }
                for published in outcome.pacts
            ],
        },
    }


def _read(
    request: Request, tenant_slug: str, auth_data: Dict[str, Any], load: Callable[[str], PactRecord]
) -> HalJSONResponse:
    """Run one pact read behind ``pacts:view`` and render it.

    Args:
        request: The request.
        tenant_slug: The tenant in the URL.
        auth_data: The authenticated principal.
        load: Reads the pact for a tenant id.

    Returns:
        The pact as ``application/hal+json``.

    Raises:
        HTTPException: 404 for an unknown pacticipant or pact, 403 without ``pacts:view``.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    try:
        pact = load(_tenant_id(auth_data))
    except (PactPublicationError, PacticipantValidationError) as exc:
        raise _http_error(exc) from exc
    return HalJSONResponse(_pact_document(_base_url(request, tenant_slug), pact))


# ---------------------------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------------------------


@router.get(
    "/{tenant_slug}/pact-broker",
    response_class=HalJSONResponse,
    summary="Pact Broker index",
    description=(
        "The entry point of the Pact Broker–compatible API: the links a Pact client discovers the "
        "other routes from. Give a Pact client this URL as its **broker base URL** and a workspace "
        "API key as its **token**.\n\n"
        "`pb:publish-contracts` is what `pact-broker publish` and the Pact libraries post to; "
        "`pb:publish-pact`, `pb:latest-pact-version` and `pb:pact-version` are URI templates.\n\n"
        "A workspace API key may be sent as `Authorization: Bearer <key>` on every route under "
        "`/pact-broker`. Requires `pacts:view`."
    ),
)
def pact_broker_index(
    tenant_slug: str,
    request: Request,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> HalJSONResponse:
    """Return the HAL index of the tenant's Pact Broker surface.

    Args:
        tenant_slug: The tenant in the URL.
        request: The request (its origin shapes the links).
        auth_data: The authenticated principal.

    Returns:
        The index links.

    Raises:
        HTTPException: 403 without ``pacts:view``.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    base = _base_url(request, tenant_slug)
    pair = base + _PAIR_PATH
    return HalJSONResponse(
        {
            "_links": {
                "self": {"href": base, "title": "Index", "templated": False},
                "pb:publish-contracts": {
                    "href": f"{base}/contracts/publish",
                    "title": "Publish contracts",
                    "templated": False,
                },
                "pb:publish-pact": {
                    "href": pair + "/version/{consumerApplicationVersion}",
                    "title": "Publish a pact",
                    "templated": True,
                },
                "pb:latest-pact-version": {
                    "href": pair + "/latest",
                    "title": "Latest pact between a consumer and a provider",
                    "templated": True,
                },
                "pb:pact-version": {
                    "href": pair + "/pact-version/{pactVersion}",
                    "title": "A pact by its content version",
                    "templated": True,
                },
                "pb:pacticipant": {
                    "href": base + "/pacticipants/{pacticipant}",
                    "title": "A pacticipant",
                    "templated": True,
                },
                "pb:pacticipant-version": {
                    "href": base + "/pacticipants/{pacticipant}/versions/{version}",
                    "title": "A version of a pacticipant",
                    "templated": True,
                },
            }
        }
    )


# A client that joins paths onto a base URL may ask for the index with a trailing slash.
router.add_api_route(
    "/{tenant_slug}/pact-broker/",
    pact_broker_index,
    methods=["GET"],
    response_class=HalJSONResponse,
    include_in_schema=False,
)


# ---------------------------------------------------------------------------------------------
# Publishing
# ---------------------------------------------------------------------------------------------


@router.post(
    "/{tenant_slug}/pact-broker/contracts/publish",
    response_class=HalJSONResponse,
    summary="Publish the pacts of a consumer version",
    description=(
        "Publish every pact one build of a consumer produced, in one request — what "
        "`pact-broker publish` and pact-js `publishPacts` call. The body is the Pact Broker's: the "
        "consumer (`pacticipantName`), its version, optional `branch`, `tags` and `buildUrl`, and "
        "`contracts`, each with the provider's name and the Pact document base64-encoded in "
        "`content`.\n\n"
        "- **Applications are registered on first use.** A consumer or provider the workspace does "
        "not have yet becomes a pacticipant.\n"
        "- **The version is recorded with its branch and tags**, exactly as "
        "`PUT …/pacticipants/{ref}/versions/{number}` does.\n"
        "- **Content is stored once.** A pact identical to one an earlier consumer version "
        "published reuses that pact version (`pactVersionSha`), so the provider has one thing to "
        "verify.\n"
        "- **All or nothing.** If any contract is refused, nothing of the request is stored.\n"
        "- **Safe to repeat.** Publishing the same pacts for the same version again changes "
        "nothing. Publishing a *different* pact for a version that already has one is `409`.\n\n"
        "Pact specification 1.x to 4.x is accepted and stored as published. `merge` conflict "
        "handling and non-Pact specifications are refused with `422 pact-publish-unsupported`.\n\n"
        "The response carries `notices` (the lines the CLI prints) and a `pb:contracts` link per "
        "pact. Requires `pacts:create`."
    ),
    openapi_extra={"requestBody": _PUBLISH_BODY},
    responses={409: _CONFLICT_409, 413: _TOO_LARGE_413, 422: _LOCATED_422, 429: _RATE_429},
)
def publish_contracts(
    tenant_slug: str,
    request: Request,
    raw: bytes = Depends(_read_publish_body),
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> HalJSONResponse:
    """Publish the pacts of one consumer version.

    Args:
        tenant_slug: The tenant in the URL.
        request: The request.
        raw: The request body, already size-limited.
        auth_data: The authenticated principal.

    Returns:
        The publish result: notices, the version, and a link per pact.

    Raises:
        HTTPException: 400 for a malformed name, version, branch, tag or URL; 409 for changed
            content; 413 over the size limit; 422 with a pointer for a malformed request or pact;
            429 over the publish budget; 403 without ``pacts:create``.
    """
    user_id = enforce_permission(db, auth_data, Resource.PACTS, Action.CREATE)
    tenant_id = _tenant_id(auth_data)
    _enforce_publish_budget(tenant_id)
    try:
        body = _parse_publish_request(raw)
        pacts = []
        for index, contract in enumerate(body.contracts):
            try:
                pacts.append(
                    prepare_pact(
                        decode_contract_content(contract, index),
                        consumer_name=body.pacticipant_name,
                        provider_name=contract.provider_name,
                        max_bytes=settings.pact_max_bytes,
                    )
                )
            except PactPublicationError as exc:
                if exc.code == CODE_PACT_INVALID:
                    # Say which contract of the request the located problem is in.
                    raise PactPublicationError(
                        exc.code, f"contract {index} ({contract.provider_name}): {exc}", pointer=exc.pointer
                    ) from exc
                raise
        outcome = publish_pacts(
            db,
            tenant_id,
            consumer_name=body.pacticipant_name,
            version_number=body.pacticipant_version_number,
            pacts=pacts,
            actor=actor_from_auth(auth_data, user_id),
            branch=body.branch,
            tags=body.tags,
            build_url=body.build_url,
            allow_modification=settings.pact_allow_contract_modification,
        )
    except (PactPublicationError, PacticipantValidationError) as exc:
        raise _http_error(exc) from exc
    return HalJSONResponse(_publish_result(_base_url(request, tenant_slug), outcome))


@router.put(
    "/{tenant_slug}/pact-broker" + _PAIR_PATH + "/version/{consumer_version}",
    response_class=HalJSONResponse,
    summary="Publish one pact",
    description=(
        "Publish the pact between a consumer version and a provider. The body is the Pact document "
        "itself (specification 1.x to 4.x), stored as published. Both applications are registered "
        "as pacticipants if the workspace does not have them, and the consumer version is "
        "recorded.\n\n"
        "Answers `201` when this consumer version had no pact for the provider, `200` when it "
        "published the same pact before (nothing changes), and `409` when it published a "
        "different one. If the document names a consumer or provider, the names must match the "
        "URL.\n\n"
        "To record a branch, tags or a build URL with the pact, use "
        "`POST …/pact-broker/contracts/publish` instead. Requires `pacts:create`."
    ),
    openapi_extra={"requestBody": _PACT_BODY},
    responses={
        201: {"description": "The pact was published for this consumer version."},
        409: _CONFLICT_409,
        413: _TOO_LARGE_413,
        422: _LOCATED_422,
        429: _RATE_429,
    },
)
def publish_pact(
    tenant_slug: str,
    provider: str,
    consumer: str,
    consumer_version: str,
    request: Request,
    raw: bytes = Depends(_read_pact_body),
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> HalJSONResponse:
    """Publish one pact.

    Args:
        tenant_slug: The tenant in the URL.
        provider: The provider's name or handle.
        consumer: The consumer's name or handle.
        consumer_version: The consumer's application version.
        request: The request.
        raw: The Pact document, already size-limited.
        auth_data: The authenticated principal.

    Returns:
        The stored pact, with 201 when it is new for this consumer version.

    Raises:
        HTTPException: 400 for a malformed name or version; 409 for changed content; 413 over the
            size limit; 422 with a pointer for a malformed pact; 429 over the publish budget; 403
            without ``pacts:create``.
    """
    user_id = enforce_permission(db, auth_data, Resource.PACTS, Action.CREATE, target=consumer)
    tenant_id = _tenant_id(auth_data)
    _enforce_publish_budget(tenant_id)
    try:
        pact = prepare_pact(raw, consumer_name=consumer, provider_name=provider, max_bytes=settings.pact_max_bytes)
        outcome = publish_pacts(
            db,
            tenant_id,
            consumer_name=pact.consumer_name,
            version_number=consumer_version,
            pacts=[pact],
            actor=actor_from_auth(auth_data, user_id),
            allow_modification=settings.pact_allow_contract_modification,
        )
    except (PactPublicationError, PacticipantValidationError) as exc:
        raise _http_error(exc) from exc
    published: PublishedPact = outcome.pacts[0]
    return HalJSONResponse(
        _pact_document(_base_url(request, tenant_slug), published.pact),
        status_code=201 if published.created else 200,
    )


# ---------------------------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------------------------

_READ_NOTE = (
    "The body is the Pact document as published, plus `createdAt` and `_links`: `self`, "
    "`pb:pact-version` (the content address — the same for every consumer version that published "
    "this pact) and `pb:latest-pact-version`.\n\n"
    "`{provider}` and `{consumer}` are a pacticipant's handle, id or name. Requires `pacts:view`."
)


@router.get(
    "/{tenant_slug}/pact-broker" + _PAIR_PATH + "/version/{consumer_version}",
    response_class=HalJSONResponse,
    summary="Read the pact of a consumer version",
    description="The pact one consumer version published for a provider.\n\n" + _READ_NOTE,
)
def read_pact(
    tenant_slug: str,
    provider: str,
    consumer: str,
    consumer_version: str,
    request: Request,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> HalJSONResponse:
    """Read the pact of one consumer version.

    Args:
        tenant_slug: The tenant in the URL.
        provider: The provider's handle, id or name.
        consumer: The consumer's handle, id or name.
        consumer_version: The consumer version number, exactly as recorded.
        request: The request.
        auth_data: The authenticated principal.

    Returns:
        The pact.

    Raises:
        HTTPException: 404 for an unknown pacticipant or pact, 403 without ``pacts:view``.
    """
    return _read(
        request, tenant_slug, auth_data, lambda tenant_id: get_pact(db, tenant_id, provider, consumer, consumer_version)
    )


@router.get(
    "/{tenant_slug}/pact-broker" + _PAIR_PATH + "/latest",
    response_class=HalJSONResponse,
    summary="Read the latest pact",
    description=(
        "The pact of the latest consumer version that published one for the provider. Latest "
        "means recorded last, not highest version number.\n\n" + _READ_NOTE
    ),
)
def read_latest_pact(
    tenant_slug: str,
    provider: str,
    consumer: str,
    request: Request,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> HalJSONResponse:
    """Read the latest pact between a consumer and a provider.

    Args:
        tenant_slug: The tenant in the URL.
        provider: The provider's handle, id or name.
        consumer: The consumer's handle, id or name.
        request: The request.
        auth_data: The authenticated principal.

    Returns:
        The pact.

    Raises:
        HTTPException: 404 for an unknown pacticipant or when the pair has no pact, 403 without
            ``pacts:view``.
    """
    return _read(request, tenant_slug, auth_data, lambda tenant_id: get_latest_pact(db, tenant_id, provider, consumer))


@router.get(
    "/{tenant_slug}/pact-broker" + _PAIR_PATH + "/pact-version/{sha}",
    response_class=HalJSONResponse,
    summary="Read a pact by its content version",
    description=(
        "A pact by its content address: the SHA-256 (64 hex characters) of its interactions, "
        "messages and specification version. Every consumer version that published the same pact "
        "shares this URL, so it is the one target a provider verifies. `self` names the latest "
        "consumer version that carries it.\n\n" + _READ_NOTE
    ),
)
def read_pact_version(
    tenant_slug: str,
    provider: str,
    consumer: str,
    sha: str,
    request: Request,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> HalJSONResponse:
    """Read a pact version by its content address.

    Args:
        tenant_slug: The tenant in the URL.
        provider: The provider's handle, id or name.
        consumer: The consumer's handle, id or name.
        sha: The pact version's SHA-256.
        request: The request.
        auth_data: The authenticated principal.

    Returns:
        The pact.

    Raises:
        HTTPException: 404 for an unknown pacticipant or SHA, 403 without ``pacts:view``.
    """
    return _read(
        request, tenant_slug, auth_data, lambda tenant_id: get_pact_by_sha(db, tenant_id, provider, consumer, sha)
    )


# ---------------------------------------------------------------------------------------------
# What a pact's links lead to: its pacticipants and the consumer version
# ---------------------------------------------------------------------------------------------


@router.get(
    "/{tenant_slug}/pact-broker/pacticipants/{pacticipant}",
    response_class=HalJSONResponse,
    summary="Read a pacticipant (Pact Broker shape)",
    description=(
        "A pacticipant in the Pact Broker's shape (`name`, `repositoryUrl`, `mainBranch`, `_links`) "
        "— what the `pb:consumer`, `pb:provider` and `pb:pacticipant` links of this API lead to. "
        "To register or change a pacticipant, use `/v1/tenants/{tenant_slug}/pacticipants`.\n\n"
        "`{pacticipant}` is its handle, id or name. Requires `pacts:view`."
    ),
)
def read_broker_pacticipant(
    tenant_slug: str,
    pacticipant: str,
    request: Request,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> HalJSONResponse:
    """Read a pacticipant in the Pact Broker's shape.

    Args:
        tenant_slug: The tenant in the URL.
        pacticipant: Its handle, id or name.
        request: The request.
        auth_data: The authenticated principal.

    Returns:
        The pacticipant.

    Raises:
        HTTPException: 404 when nothing matches in this tenant, 403 without ``pacts:view``.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    try:
        record = get_pacticipant(db, _tenant_id(auth_data), pacticipant)
    except PacticipantValidationError as exc:
        raise _http_error(exc) from exc
    return HalJSONResponse(_pacticipant_document(_base_url(request, tenant_slug), record))


@router.get(
    "/{tenant_slug}/pact-broker/pacticipants/{pacticipant}/versions/{number}",
    response_class=HalJSONResponse,
    summary="Read a pacticipant version (Pact Broker shape)",
    description=(
        "One version of a pacticipant in the Pact Broker's shape: `number`, `buildUrl`, and its "
        "branches and tags under `_embedded` — what the `pb:consumer-version` and "
        "`pb:pacticipant-version` links of this API lead to.\n\n"
        "`{pacticipant}` is its handle, id or name. Requires `pacts:view`."
    ),
)
def read_broker_pacticipant_version(
    tenant_slug: str,
    pacticipant: str,
    number: str,
    request: Request,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> HalJSONResponse:
    """Read one version of a pacticipant in the Pact Broker's shape.

    Args:
        tenant_slug: The tenant in the URL.
        pacticipant: The pacticipant's handle, id or name.
        number: The version number, exactly as recorded.
        request: The request.
        auth_data: The authenticated principal.

    Returns:
        The version.

    Raises:
        HTTPException: 404 for an unknown pacticipant or version, 403 without ``pacts:view``.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    try:
        record = get_pacticipant(db, _tenant_id(auth_data), pacticipant)
        version = get_version(db, record, number)
    except PacticipantValidationError as exc:
        raise _http_error(exc) from exc
    return HalJSONResponse(_version_document(_base_url(request, tenant_slug), record, version))
