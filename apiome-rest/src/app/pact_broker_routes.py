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
  content address (also with a ``/metadata/{m}`` suffix, the form for-verification links take).

PFX-1.3 (#6916) adds what a verifier and a person ask for without knowing a version:

* ``POST …/pact-broker/pacts/provider/{p}/for-verification`` — the pacts a provider build must
  verify, chosen by consumer-version selectors, each with the notices saying why
  (:mod:`app.pact_selectors`); also as ``GET`` with the selectors in the query string, which the
  Rust verifier fetches first (PFX-1.8, #6921);
* ``GET  …/consumer/{c}/latest/{tag}`` and ``…/consumer/{c}/branch/{branch}/latest`` — the latest
  pact of a pair from a tag or a branch;
* ``GET  …/pacts/provider/{p}/latest`` and ``…/latest/{tag}`` — the latest pact of every consumer.

The base URL a client is given is ``https://<api>/v1/tenants/<tenant>/pact-broker``, or — where the
operator configured it — the tenant-host alias ``https://<tenant>.<suffix>``
(:mod:`app.pact_broker_host`). Links in a response lead back to whichever the client used.

PFX-1.5 (#6918) adds environments and deployment records (:mod:`app.pact_broker_environment_routes`);
the index links them (``pb:environments``, ``pb:environment``) and a version's document carries one
``pb:record-deployment`` and one ``pb:record-release`` link per environment.

Reads need ``pacts:view`` and publishing needs ``pacts:create``. A workspace API key may be sent
as ``Authorization: Bearer <key>`` here (:mod:`app.pact_broker_auth`), because that is the only
credential Pact tooling sends.

Responses are ``application/hal+json`` in the Pact Broker's shape. Refusals keep Apiome's shape:
``{"detail": {"code", "message", "pointer"}}``, where ``pointer`` locates the problem.
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable, Dict, List, Optional, Sequence
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from .bidirectional_store import compare_published_pacts
from .bidirectional_verification import ComparisonRun, run_notices
from .config import settings
from .consumer_contract_store import actor_from_auth
from .pact_consumer_sync import ConsumerRefreshRun, refresh_consumer_contracts, refresh_notices
from .database import db
from .pact_audit import audited_write
from .pact_broker_auth import validate_broker_authentication
from .pact_broker_host import alias_base_url
from .pact_commit_status_store import post_publish_statuses
from .pact_environment import (
    CODE_DEPLOYED_VERSION_NOT_FOUND,
    CODE_DEPLOYMENT_INVALID,
    CODE_ENVIRONMENT_INVALID,
    CODE_ENVIRONMENT_NAME_TAKEN,
    CODE_ENVIRONMENT_NOT_FOUND,
    CODE_RELEASED_VERSION_NOT_FOUND,
    EnvironmentRecord,
)
from .pact_environment_store import list_environments
from .pact_pending_store import load_pending_evidence
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
    list_pact_candidates,
    publish_pacts,
)
from .pact_selectors import (
    CODE_SELECTOR_INVALID,
    ForVerificationQuery,
    PactCandidate,
    VerifiablePact,
    build_notices,
    encode_metadata,
    for_verification_body_from_query,
    latest_per_consumer,
    parse_for_verification_request,
    select_verifiable_pacts,
    short_description,
    verification_metadata,
)
from .pact_webhook import (
    CODE_TRIGGERED_WEBHOOK_NOT_FOUND,
    CODE_WEBHOOK_INVALID,
    CODE_WEBHOOK_LIMIT,
    CODE_WEBHOOK_NOT_FOUND,
    CODE_WEBHOOK_SECRETS_UNAVAILABLE,
)
from .pact_webhook_events import fire_publish_events
from .pact_wip import select_wip_pacts
from .pacticipant import (
    CODE_LABEL_NOT_FOUND,
    CODE_NOT_DELETED,
    CODE_NOT_FOUND,
    CODE_RESTORE_CONFLICT,
    CODE_VERSION_IN_USE,
    CODE_VERSION_NOT_FOUND,
    PacticipantRecord,
    PacticipantValidationError,
    PacticipantVersionRecord,
    slugify_pacticipant_name,
)
from .pacticipant_store import get_pacticipant, get_version
from .permissions import Action, Resource, enforce_permission
from .provider_contract import (
    CODE_CONTRACT_CONFLICT,
    CODE_CONTRACT_INVALID,
    CODE_CONTRACT_NOT_FOUND,
    CODE_CONTRACT_TOO_LARGE,
    CODE_REQUEST_INVALID,
    CODE_SOURCE_NOT_FOUND,
    CODE_UNSUPPORTED,
)
from .provider_contract_evidence import (
    CODE_EVIDENCE_INVALID,
    CODE_EVIDENCE_REPORT_NOT_FOUND,
    CODE_EVIDENCE_TOO_LARGE,
    CODE_EVIDENCE_UNSUPPORTED,
)
from .rate_limit import FixedWindowRateLimiter
from .verification_result import CODE_REPORT_NOT_FOUND, CODE_VERIFICATION_INVALID, CODE_VERIFICATION_NOT_FOUND

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
    CODE_SELECTOR_INVALID: 400,
    CODE_VERIFICATION_INVALID: 422,
    CODE_REPORT_NOT_FOUND: 422,
    CODE_VERIFICATION_NOT_FOUND: 404,
    CODE_ENVIRONMENT_INVALID: 422,
    CODE_ENVIRONMENT_NAME_TAKEN: 409,
    CODE_ENVIRONMENT_NOT_FOUND: 404,
    CODE_DEPLOYMENT_INVALID: 422,
    CODE_DEPLOYED_VERSION_NOT_FOUND: 404,
    CODE_RELEASED_VERSION_NOT_FOUND: 404,
    CODE_WEBHOOK_INVALID: 422,
    CODE_WEBHOOK_NOT_FOUND: 404,
    CODE_TRIGGERED_WEBHOOK_NOT_FOUND: 404,
    CODE_WEBHOOK_SECRETS_UNAVAILABLE: 503,
    CODE_WEBHOOK_LIMIT: 409,
    # PFX-1.11 (#6924): labels and deletes.
    CODE_LABEL_NOT_FOUND: 404,
    CODE_NOT_DELETED: 409,
    CODE_RESTORE_CONFLICT: 409,
    CODE_VERSION_IN_USE: 409,
    # PFX-2.1 (#6925): provider contracts.
    CODE_CONTRACT_INVALID: 422,
    CODE_REQUEST_INVALID: 422,
    CODE_UNSUPPORTED: 422,
    CODE_SOURCE_NOT_FOUND: 422,
    CODE_CONTRACT_TOO_LARGE: 413,
    CODE_CONTRACT_CONFLICT: 409,
    CODE_CONTRACT_NOT_FOUND: 404,
    # PFX-2.4 (#6928): self-verification evidence.
    CODE_EVIDENCE_INVALID: 422,
    CODE_EVIDENCE_UNSUPPORTED: 422,
    CODE_EVIDENCE_REPORT_NOT_FOUND: 422,
    CODE_EVIDENCE_TOO_LARGE: 413,
}

_publish_limiter = FixedWindowRateLimiter()

#: The ``logs`` level of each ``notices`` type in a publish result.
_LOG_LEVEL_BY_NOTICE = {"debug": "debug", "success": "info", "warning": "warn", "error": "error"}

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
        Its name, repository and main branch, its labels embedded (PFX-1.11), with a ``self`` link,
        the ``pb:label`` template, and the two templates a Pact verifier records the provider's
        branch and tags with before it publishes a result (``pb:branch-version``,
        ``pb:version-tag``).
    """
    url = _pacticipant_url(base, pacticipant.slug)
    return {
        "name": pacticipant.name,
        "displayName": pacticipant.name,
        "repositoryUrl": pacticipant.repository_url,
        "mainBranch": pacticipant.main_branch,
        "createdAt": pacticipant.created_at,
        "updatedAt": pacticipant.updated_at,
        "_embedded": {
            "labels": [
                {
                    "name": label,
                    "_links": {
                        "self": {"title": "Label", "name": label, "href": f"{url}/labels/{quote(label, safe='')}"}
                    },
                }
                for label in pacticipant.labels
            ]
        },
        "_links": {
            "self": {"title": "Pacticipant", "name": pacticipant.name, "href": url},
            "pb:label": {
                "title": f"Get, create or delete a label for {pacticipant.name}",
                "href": url + "/labels/{label}",
                "templated": True,
            },
            "pb:branch-version": {
                "title": "Get or add/create a version for a branch of this pacticipant",
                "href": url + "/branches/{branch}/versions/{version}",
                "templated": True,
            },
            "pb:version-tag": {
                "title": "Get, create or delete a tag for a version of this pacticipant",
                "href": url + "/versions/{version}/tags/{tag}",
                "templated": True,
            },
        },
    }


def _environment_links(
    base: str, slug: str, number: str, environments: Sequence[EnvironmentRecord]
) -> Dict[str, List[Dict[str, str]]]:
    """The ``pb:record-deployment`` and ``pb:record-release`` links of a version, one per environment.

    ``pact-broker record-deployment --environment production`` picks the link whose ``name`` is
    ``production``, so every environment of the workspace is offered.

    Args:
        base: The broker base URL.
        slug: The pacticipant's handle.
        number: The version number.
        environments: The workspace's environments.

    Returns:
        The two link arrays (empty when the workspace has no environment).
    """
    version = _version_url(base, slug, number)
    return {
        "pb:record-deployment": [
            {
                "title": f"Record deployment to {environment.display_name}",
                "name": environment.name,
                "href": f"{version}/deployed-versions/environment/{environment.id}",
            }
            for environment in environments
        ],
        "pb:record-release": [
            {
                "title": f"Record release to {environment.display_name}",
                "name": environment.name,
                "href": f"{version}/released-versions/environment/{environment.id}",
            }
            for environment in environments
        ],
    }


def _version_document(
    base: str,
    pacticipant: PacticipantRecord,
    version: PacticipantVersionRecord,
    environments: Optional[Sequence[EnvironmentRecord]] = None,
) -> Dict[str, Any]:
    """Render a pacticipant version the way a Pact Broker returns one.

    Args:
        base: The broker base URL.
        pacticipant: The owning pacticipant.
        version: The version.
        environments: The workspace's environments, for the ``pb:record-deployment`` and
            ``pb:record-release`` links; ``None`` leaves those links out.

    Returns:
        Its number and build URL, its branches and tags embedded, and links to itself, its owner
        and — when ``environments`` is given — recording a deployment or release of it.
    """
    document: Dict[str, Any] = {
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
    if environments is not None:
        document["_links"].update(_environment_links(base, pacticipant.slug, version.number, environments))
    return document


def _pair_url(base: str, provider_slug: str, consumer_slug: str) -> str:
    """The URL prefix of the pacts between one provider and one consumer."""
    return f"{base}/pacts/provider/{quote(provider_slug, safe='')}/consumer/{quote(consumer_slug, safe='')}"


def _pact_url(base: str, pact: PactRecord) -> str:
    """The URL of the pact one consumer version published."""
    return f"{_pair_url(base, pact.provider_slug, pact.consumer_slug)}/version/{quote(pact.consumer_version, safe='')}"


def _pact_title(pact: PactRecord) -> str:
    """How a pact is named in a link: both applications and the consumer version."""
    return f"Pact between {pact.consumer_name} ({pact.consumer_version}) and {pact.provider_name}"


def _pact_document(base: str, pact: PactRecord, metadata: Optional[str] = None) -> Dict[str, Any]:
    """Render a stored pact the way a Pact Broker returns one.

    The published document is returned as it is, with three additions a client relies on: the two
    pacticipant names (when the document left them out), ``createdAt``, and ``_links``.

    Args:
        base: The broker base URL.
        pact: The stored pact.
        metadata: The for-verification metadata segment the pact was fetched with, if any; the
            ``pb:publish-verification-results`` link carries it, so the result can be traced back.

    Returns:
        The response body.
    """
    pair = _pair_url(base, pact.provider_slug, pact.consumer_slug)
    pact_version = f"{pair}/pact-version/{pact.sha}"
    publish_at = f"{pact_version}/metadata/{quote(metadata, safe='')}" if metadata else pact_version
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
            "href": pact_version,
        },
        "pb:publish-verification-results": {
            "title": "Publish verification results",
            "href": f"{publish_at}/verification-results",
        },
        "pb:latest-verification-results": {
            "title": "Latest verification results",
            "href": f"{pact_version}/verification-results/latest",
        },
        "pb:latest-pact-version": {
            "title": "Latest version of this pact",
            "href": f"{pair}/latest",
        },
        "pb:latest-tagged-pact-version": {
            "title": "Latest version of this pact for a tag",
            "href": pair + "/latest/{tag}",
            "templated": True,
        },
        "pb:pact-webhooks": {
            "title": "Webhooks for the pact between consumer and provider",
            "href": f"{pair}/webhooks",
        },
        "pb:pact-webhooks-status": {
            "title": "Webhooks status",
            "href": f"{pair}/webhooks/status",
        },
        "pb:triggered-webhooks": {
            "title": "Webhooks triggered by the publication of this pact",
            "href": f"{_pact_url(base, pact)}/triggered-webhooks",
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


def _publish_result(
    base: str,
    outcome: PublishOutcome,
    comparisons: Optional[ComparisonRun] = None,
    consumer_contracts: Optional[ConsumerRefreshRun] = None,
) -> Dict[str, Any]:
    """Render a bulk publish result the way a Pact Broker returns one.

    Args:
        base: The broker base URL.
        outcome: What the request stored.
        comparisons: The bi-directional comparisons the publish ran (PFX-2.3), if any.
        consumer_contracts: How the publish refreshed the consumer's declared surface (PFX-7.1).

    Returns:
        The response body: ``notices`` (and the same lines as ``logs``), the embedded pacticipant
        and version, a link per pact and, when any provider has a contract, Apiome's
        ``comparisons``.
    """
    version = outcome.version.version
    consumer = outcome.consumer
    notices = _publish_notices(base, outcome)
    if comparisons is not None:
        notices += run_notices(comparisons)
    if consumer_contracts is not None:
        notices += refresh_notices(consumer_contracts)
    body: Dict[str, Any] = {
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
    if comparisons is not None and comparisons.entries:
        body["comparisons"] = comparisons.to_dict()
    if consumer_contracts is not None and consumer_contracts.entries:
        body["consumerContracts"] = consumer_contracts.to_dict()
    return body


def _read(
    request: Request,
    tenant_slug: str,
    auth_data: Dict[str, Any],
    load: Callable[[str], PactRecord],
    metadata: Optional[str] = None,
) -> HalJSONResponse:
    """Run one pact read behind ``pacts:view`` and render it.

    Args:
        request: The request.
        tenant_slug: The tenant in the URL.
        auth_data: The authenticated principal.
        load: Reads the pact for a tenant id.
        metadata: The for-verification metadata segment of the URL, if any.

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
    return HalJSONResponse(_pact_document(_base_url(request, tenant_slug), pact, metadata))


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
        "`pb:provider-pacts-for-verification` is what a Pact verifier posts its consumer-version "
        "selectors to. `pb:publish-pact`, `pb:latest-pact-version`, `pb:pact-version`, "
        "`pb:latest-provider-pacts` and the others are URI templates. `pb:environments` lists the "
        "environments `pact-broker record-deployment` looks an environment up in. "
        "`pb:can-i-deploy-pacticipant-version-to-environment` and `…-to-tag` answer whether a version "
        "can be deployed; `pact-broker can-i-deploy` asks `…/pact-broker/matrix`. `pb:webhooks` and "
        "`pb:webhook` are what `pact-broker create-webhook` and `create-or-update-webhook` use.\n\n"
        "A workspace API key may be sent as `Authorization: Bearer <key>`, or as the password of "
        "basic auth (any username), on every route under `/pact-broker`. A restricted key needs a "
        "Pact scope: `pact:read` for reads, `pact:publish` to publish pacts and record "
        "deployments, `pact:verify` to publish verification results. Requires `pacts:view`."
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
                "pb:provider-pacts-for-verification": {
                    "href": base + "/pacts/provider/{provider}/for-verification",
                    "title": "Pact versions to be verified for the specified provider",
                    "templated": True,
                },
                # The name the first Pact clients with selector support look for.
                "beta:provider-pacts-for-verification": {
                    "name": "beta",
                    "href": base + "/pacts/provider/{provider}/for-verification",
                    "title": "DEPRECATED - please use pb:provider-pacts-for-verification",
                    "templated": True,
                },
                "pb:latest-provider-pacts": {
                    "href": base + "/pacts/provider/{provider}/latest",
                    "title": "Latest pacts by provider",
                    "templated": True,
                },
                "pb:latest-provider-pacts-with-tag": {
                    "href": base + "/pacts/provider/{provider}/latest/{tag}",
                    "title": "Latest pacts for provider with the specified tag",
                    "templated": True,
                },
                "pb:environments": {
                    "href": base + "/environments",
                    "title": "Environments",
                    "templated": False,
                },
                "pb:environment": {
                    "href": base + "/environments/{uuid}",
                    "title": "Environment",
                    "templated": True,
                },
                "pb:webhooks": {
                    "href": base + "/webhooks",
                    "title": "Webhooks",
                    "templated": False,
                },
                "pb:webhook": {
                    "href": base + "/webhooks/{uuid}",
                    "title": "Webhook",
                    "templated": True,
                },
                "pb:can-i-deploy-pacticipant-version-to-tag": {
                    "href": base + "/can-i-deploy?pacticipant={pacticipant}&version={version}&to={tag}",
                    "title": (
                        "Determine if an application version can be safely deployed to an environment "
                        "identified by the given tag"
                    ),
                    "templated": True,
                },
                "pb:can-i-deploy-pacticipant-version-to-environment": {
                    "href": (
                        base + "/can-i-deploy?pacticipant={pacticipant}&version={version}&environment={environment}"
                    ),
                    "title": "Determine if an application version can be safely deployed to an environment",
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
        "nothing. Publishing a *different* pact for a version that already has one is `409`.\n"
        "- **One consumer model.** Each new pact refreshes the consumer's declared surface in the "
        "provider's project (its next contract revision) when the provider pacticipant is bound to "
        "a project; interactions that cannot be placed stay on the revision with reason codes. The "
        "response lists the outcome in `consumerContracts` and as notices; a pact that cannot be "
        "placed is reported with a reason, never dropped.\n"
        "- **Bi-directional comparison.** When a provider has published a provider contract, each pact "
        "is compared with the contracts of its latest provider version, the head of each provider "
        "branch and every provider version deployed or released. Each comparison is stored as a "
        "verification result with `kind: bidirectional`; the response lists them in `comparisons` "
        "and as notices.\n\n"
        "Pact specification 1.x to 4.x is accepted and stored as published. `merge` conflict "
        "handling and non-Pact specifications are refused with `422 pact-publish-unsupported`.\n\n"
        "The response carries `notices` (the lines the CLI prints) and a `pb:contracts` link per "
        "pact. Requires `pacts:create`."
    ),
    openapi_extra={"requestBody": _PUBLISH_BODY},
    responses={409: _CONFLICT_409, 413: _TOO_LARGE_413, 422: _LOCATED_422, 429: _RATE_429},
)
@audited_write("pacts.publication.create", "pact-broker/contracts/publish")
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
    base = _base_url(request, tenant_slug)
    fire_publish_events(db, tenant_id, base, outcome)
    post_publish_statuses(db, tenant_id, base, outcome)
    comparisons = compare_published_pacts(db, tenant_id, outcome, actor=actor_from_auth(auth_data, user_id))
    consumer_contracts = refresh_consumer_contracts(
        db, tenant_id, tenant_slug, outcome, actor=actor_from_auth(auth_data, user_id)
    )
    return HalJSONResponse(_publish_result(base, outcome, comparisons, consumer_contracts))


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
@audited_write("pacts.publication.create", "pact/provider/{provider}/consumer/{consumer}/version/{consumer_version}")
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
    base = _base_url(request, tenant_slug)
    fire_publish_events(db, tenant_id, base, outcome)
    post_publish_statuses(db, tenant_id, base, outcome)
    # The comparisons are read in the matrix; this response stays the pact, as on a Pact Broker.
    compare_published_pacts(db, tenant_id, outcome, actor=actor_from_auth(auth_data, user_id))
    refresh_consumer_contracts(db, tenant_id, tenant_slug, outcome, actor=actor_from_auth(auth_data, user_id))
    return HalJSONResponse(
        _pact_document(base, published.pact),
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


# The form a for-verification response links to: the same pact, with the selection it was chosen
# by encoded in the last segment, for the verification result to be traced back (PFX-1.4).
@router.get(
    "/{tenant_slug}/pact-broker" + _PAIR_PATH + "/pact-version/{sha}/metadata/{metadata}",
    response_class=HalJSONResponse,
    summary="Read a pact by its content version (for-verification link)",
    description=(
        "The same pact as `…/pact-version/{sha}`. The last segment is the metadata a "
        "for-verification response encodes in its links (which selectors chose the pact, for which "
        "consumer version, whether it was pending); it does not change the pact returned, and "
        "`pb:publish-verification-results` carries it on, so the result records it.\n\n" + _READ_NOTE
    ),
)
def read_pact_version_with_metadata(
    tenant_slug: str,
    provider: str,
    consumer: str,
    sha: str,
    request: Request,
    metadata: str = Path(
        description="The selection metadata of a for-verification link (URL-safe base64); kept for the result."
    ),
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> HalJSONResponse:
    """Read a pact version through the link a for-verification response gave.

    Args:
        tenant_slug: The tenant in the URL.
        provider: The provider's handle, id or name.
        consumer: The consumer's handle, id or name.
        sha: The pact version's SHA-256.
        metadata: The encoded selection metadata; passed on to ``pb:publish-verification-results``.
        request: The request.
        auth_data: The authenticated principal.

    Returns:
        The pact.

    Raises:
        HTTPException: 404 for an unknown pacticipant or SHA, 403 without ``pacts:view``.
    """
    return _read(
        request,
        tenant_slug,
        auth_data,
        lambda tenant_id: get_pact_by_sha(db, tenant_id, provider, consumer, sha),
        metadata,
    )


@router.get(
    "/{tenant_slug}/pact-broker" + _PAIR_PATH + "/latest/{tag}",
    response_class=HalJSONResponse,
    summary="Read the latest pact for a consumer tag",
    description=(
        "The pact of the latest consumer version tagged `{tag}` that published one for the "
        "provider. Latest means recorded last.\n\n" + _READ_NOTE
    ),
)
def read_latest_tagged_pact(
    tenant_slug: str,
    provider: str,
    consumer: str,
    tag: str,
    request: Request,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> HalJSONResponse:
    """Read the latest pact of a pair from consumer versions with a tag.

    Args:
        tenant_slug: The tenant in the URL.
        provider: The provider's handle, id or name.
        consumer: The consumer's handle, id or name.
        tag: The consumer version tag, exactly as recorded.
        request: The request.
        auth_data: The authenticated principal.

    Returns:
        The pact.

    Raises:
        HTTPException: 404 for an unknown pacticipant or when no tagged version has a pact, 403
            without ``pacts:view``.
    """
    return _read(
        request,
        tenant_slug,
        auth_data,
        lambda tenant_id: get_latest_pact(db, tenant_id, provider, consumer, tag=tag),
    )


@router.get(
    "/{tenant_slug}/pact-broker" + _PAIR_PATH + "/branch/{branch:path}/latest",
    response_class=HalJSONResponse,
    summary="Read the latest pact for a consumer branch",
    description=(
        "The pact of the latest consumer version recorded on branch `{branch}` that published one "
        "for the provider. A branch name with a `/` (`feat/new-invoice`) is sent as it is or with "
        "the slash encoded.\n\n" + _READ_NOTE
    ),
)
def read_latest_branch_pact(
    tenant_slug: str,
    provider: str,
    consumer: str,
    branch: str,
    request: Request,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> HalJSONResponse:
    """Read the latest pact of a pair from consumer versions on a branch.

    Args:
        tenant_slug: The tenant in the URL.
        provider: The provider's handle, id or name.
        consumer: The consumer's handle, id or name.
        branch: The consumer branch, exactly as recorded.
        request: The request.
        auth_data: The authenticated principal.

    Returns:
        The pact.

    Raises:
        HTTPException: 404 for an unknown pacticipant or when no version on the branch has a
            pact, 403 without ``pacts:view``.
    """
    return _read(
        request,
        tenant_slug,
        auth_data,
        lambda tenant_id: get_latest_pact(db, tenant_id, provider, consumer, branch=branch),
    )


# ---------------------------------------------------------------------------------------------
# The pacts of a provider: latest per consumer, and the pacts to verify
# ---------------------------------------------------------------------------------------------


def _provider_url(base: str, slug: str) -> str:
    """The URL prefix of a provider's pacts."""
    return f"{base}/pacts/provider/{quote(slug, safe='')}"


def _candidate_pact_url(base: str, provider: PacticipantRecord, candidate: PactCandidate) -> str:
    """The URL of the pact one consumer version published for the provider."""
    return (
        f"{_pair_url(base, provider.slug, candidate.consumer_slug)}/version/"
        f"{quote(candidate.version_number, safe='')}"
    )


def _candidate_title(provider: PacticipantRecord, candidate: PactCandidate) -> str:
    """How a selected pact is named: both applications and the consumer version."""
    return f"Pact between {candidate.consumer_name} ({candidate.version_number}) and {provider.name}"


def _verifiable_pact_document(
    base: str, provider: PacticipantRecord, pact: VerifiablePact, query: ForVerificationQuery
) -> Dict[str, Any]:
    """Render one pact of a for-verification response the way a Pact Broker does.

    Args:
        base: The broker base URL.
        provider: The verifying provider.
        pact: The selected pact.
        query: The request.

    Returns:
        ``shortDescription``, ``verificationProperties`` (``pending`` when asked for or for a WIP
        pact, ``wip`` when it is one, and ``notices``) and a ``self`` link to the pact version with its metadata.
    """
    candidate = pact.candidate
    pact_version_url = f"{_pair_url(base, provider.slug, candidate.consumer_slug)}/pact-version/{candidate.sha}"
    properties: Dict[str, Any] = {}
    if query.include_pending_status or pact.wip:
        properties["pending"] = pact.pending
    if pact.wip:
        properties["wip"] = True
    notice_url = f"{pact_version_url}/metadata/{encode_metadata({'w': True})}" if pact.wip else pact_version_url
    properties["notices"] = build_notices(pact, notice_url, query, provider.name)
    return {
        "shortDescription": short_description(pact),
        "verificationProperties": properties,
        "_links": {
            "self": {
                "href": f"{pact_version_url}/metadata/{encode_metadata(verification_metadata(pact))}",
                "name": _candidate_title(provider, candidate),
            }
        },
    }


def _parse_json_body(raw: bytes) -> Any:
    """Decode a JSON request body; ``None`` when it is empty.

    Args:
        raw: The body, already size-limited.

    Returns:
        The decoded value.

    Raises:
        HTTPException: 400 ``pact-selector-invalid`` for malformed JSON.
    """
    if not raw.strip():
        return None
    try:
        return json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": CODE_SELECTOR_INVALID, "message": f"the request body is not JSON: {exc}", "pointer": ""},
        ) from exc


@router.post(
    "/{tenant_slug}/pact-broker/pacts/provider/{provider}/for-verification",
    response_class=HalJSONResponse,
    summary="The pacts a provider must verify",
    description=(
        "What a Pact verifier calls before it verifies: the pacts a provider build must verify, "
        "chosen by **consumer-version selectors**. One entry per distinct pact; a pact chosen by "
        "several selectors appears once, with every reason in its notices.\n\n"
        "Selectors (`consumerVersionSelectors`, each optionally narrowed by `consumer`):\n\n"
        '- `{"mainBranch": true}` — the latest version from each consumer\'s main branch;\n'
        '- `{"branch": "x"}` — the latest version from branch `x`, with `fallbackBranch` or '
        "`fallbackToMainBranch` for a consumer that has none there;\n"
        '- `{"matchingBranch": true}` — `branch` set to the request\'s `providerVersionBranch`;\n'
        '- `{"tag": "x"}` — every version tagged `x`; with `"latest": true` the latest one, and '
        "`fallbackTag` for a consumer that has none;\n"
        '- `{"latest": true}` — the latest version of each consumer;\n'
        "- `deployed`, `released`, `deployedOrReleased`, `environment` — versions in an "
        "environment. Accepted; they select nothing until environments are recorded.\n\n"
        "No selectors means the broker's defaults: each consumer's main branch (or its latest "
        "version), and whatever is deployed or released.\n\n"
        "`includePendingStatus: true` adds `pending` and the pending notices. A pact is pending "
        "until the provider has verified its content successfully — from `providerVersionBranch` "
        "(or on any branch before that branch was created), with each of `providerVersionTags`, "
        "or, with neither, at all. A failure of a pending pact does not fail the provider build.\n\n"
        "`includeWipPactsSince: <date>` (with a `providerVersionBranch` or `providerVersionTags`) "
        "adds **work-in-progress** pacts after the selected ones: the latest pact of each consumer "
        "branch and tag, published on or after the date, that no selector chose and that is still "
        "pending. They carry `wip: true` and `pending: true`, so they never fail the build.\n\n"
        "An ambiguous selector (for example `tag` with `branch`, or `mainBranch` with `latest: "
        "false`) is `400 pact-selector-invalid` with the pointer of the selector. Requires "
        "`pacts:view`."
    ),
    openapi_extra={
        "requestBody": {
            "required": False,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "consumerVersionSelectors": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "mainBranch": {"type": "boolean", "enum": [True]},
                                        "branch": {"type": "string"},
                                        "matchingBranch": {"type": "boolean", "enum": [True]},
                                        "fallbackBranch": {"type": "string"},
                                        "fallbackToMainBranch": {"type": "boolean", "enum": [True]},
                                        "tag": {"type": "string"},
                                        "fallbackTag": {"type": "string"},
                                        "latest": {"type": "boolean"},
                                        "consumer": {"type": "string"},
                                        "deployed": {"type": "boolean", "enum": [True]},
                                        "released": {"type": "boolean", "enum": [True]},
                                        "deployedOrReleased": {"type": "boolean", "enum": [True]},
                                        "environment": {"type": "string"},
                                    },
                                },
                            },
                            "providerVersionBranch": {"type": "string"},
                            "providerVersionTags": {"type": "array", "items": {"type": "string"}},
                            "includePendingStatus": {"type": "boolean", "default": False},
                            "includeWipPactsSince": {"type": "string", "format": "date"},
                        },
                    },
                    "example": {
                        "consumerVersionSelectors": [
                            {"mainBranch": True},
                            {"matchingBranch": True},
                            {"deployedOrReleased": True},
                        ],
                        "providerVersionBranch": "main",
                        "includePendingStatus": True,
                        "includeWipPactsSince": "2026-11-01",
                    },
                }
            },
        }
    },
    responses={
        400: {"description": "`pact-selector-invalid`: a selector is ambiguous or malformed; see `detail.pointer`."},
        404: {"description": "`pacticipant-not-found`: the workspace has no such provider."},
    },
)
def pacts_for_verification(
    tenant_slug: str,
    provider: str,
    request: Request,
    raw: bytes = Depends(_read_pact_body),
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> HalJSONResponse:
    """Return the pacts a provider build must verify.

    Args:
        tenant_slug: The tenant in the URL.
        provider: The provider's handle, id or name.
        request: The request.
        raw: The JSON body carrying the selectors, already size-limited.
        auth_data: The authenticated principal.

    Returns:
        ``_embedded.pacts`` (one entry per distinct pact) and a ``self`` link.

    Raises:
        HTTPException: 400 for an ambiguous or malformed selector, 404 for an unknown provider,
            403 without ``pacts:view``.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    try:
        body = _parse_json_body(raw)
    except PactPublicationError as exc:
        raise _http_error(exc) from exc
    return _pacts_for_verification(request, tenant_slug, provider, auth_data, body)


@router.get(
    "/{tenant_slug}/pact-broker/pacts/provider/{provider}/for-verification",
    response_class=HalJSONResponse,
    summary="The pacts a provider must verify (query-string form)",
    description=(
        "The `GET` form of `POST …/for-verification`, which the Pact Broker keeps for its first "
        "clients — and which the Rust verifier inside pact-js, pact-python and pact-go fetches "
        "before it posts its selectors. Same answer as the `POST`; the parameters are the broker's "
        "snake-case Rack query parameters: `provider_version_branch`, `provider_version_tags[]`, "
        "`include_pending_status`, `include_wip_pacts_since` and "
        "`consumer_version_selectors[][<field>]` (`main_branch`, `branch`, `matching_branch`, "
        "`fallback_branch`, `fallback_to_main_branch`, `tag`, `fallback_tag`, `latest`, `consumer`, "
        "`deployed`, `released`, `deployed_or_released`, `environment`). A field that repeats starts "
        "the next selector. Without parameters, the broker's default selectors apply. Prefer the "
        "`POST`. Requires `pacts:view`."
    ),
    responses={
        400: {"description": "`pact-selector-invalid`: a selector is ambiguous or malformed; see `detail.pointer`."},
        404: {"description": "`pacticipant-not-found`: the workspace has no such provider."},
    },
)
def pacts_for_verification_by_query(
    tenant_slug: str,
    provider: str,
    request: Request,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> HalJSONResponse:
    """Return the pacts a provider build must verify, with the selectors in the query string.

    Args:
        tenant_slug: The tenant in the URL.
        provider: The provider's handle, id or name.
        request: The request (its query string carries the selectors).
        auth_data: The authenticated principal.

    Returns:
        The same document as :func:`pacts_for_verification`.

    Raises:
        HTTPException: 400 for an ambiguous or malformed selector, 404 for an unknown provider,
            403 without ``pacts:view``.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    body = for_verification_body_from_query(request.query_params.multi_items())
    return _pacts_for_verification(request, tenant_slug, provider, auth_data, body)


def _pacts_for_verification(
    request: Request, tenant_slug: str, provider: str, auth_data: Dict[str, Any], body: Any
) -> HalJSONResponse:
    """Select the pacts to verify — the shared work of the ``POST`` and ``GET`` forms.

    Args:
        request: The request (its origin shapes the links).
        tenant_slug: The tenant in the URL.
        provider: The provider's handle, id or name.
        auth_data: The authenticated principal (``pacts:view`` already enforced).
        body: The request in the ``POST`` body shape (``None`` for none).

    Returns:
        ``_embedded.pacts`` (one entry per distinct pact) and a ``self`` link.

    Raises:
        HTTPException: 400 for an ambiguous or malformed selector, 404 for an unknown provider.
    """
    try:
        query = parse_for_verification_request(body)
        record, candidates = list_pact_candidates(db, _tenant_id(auth_data), provider)
    except (PactPublicationError, PacticipantValidationError) as exc:
        raise _http_error(exc) from exc
    base = _base_url(request, tenant_slug)
    evidence = load_pending_evidence(db, _tenant_id(auth_data), record.id, query.provider_version_branch)
    pacts = select_verifiable_pacts(candidates, query, evidence)
    pacts += select_wip_pacts(candidates, pacts, query, evidence)
    return HalJSONResponse(
        {
            "_embedded": {"pacts": [_verifiable_pact_document(base, record, pact, query) for pact in pacts]},
            "_links": {
                "self": {
                    "href": f"{_provider_url(base, record.slug)}/for-verification",
                    "title": "Pacts to be verified",
                }
            },
        }
    )


def _latest_provider_pacts(
    request: Request, tenant_slug: str, provider: str, auth_data: Dict[str, Any], tag: Optional[str]
) -> HalJSONResponse:
    """The latest pact of each consumer of a provider, optionally from tagged versions only.

    Args:
        request: The request.
        tenant_slug: The tenant in the URL.
        provider: The provider's handle, id or name.
        auth_data: The authenticated principal.
        tag: Only consumer versions with this tag, when set.

    Returns:
        The Pact Broker's provider-pacts shape: ``pb:provider`` and one ``pb:pacts`` link per
        consumer (with the deprecated ``provider`` and ``pacts`` spellings older clients read).

    Raises:
        HTTPException: 404 for an unknown provider, 403 without ``pacts:view``.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    try:
        record, candidates = list_pact_candidates(db, _tenant_id(auth_data), provider)
    except PacticipantValidationError as exc:
        raise _http_error(exc) from exc
    base = _base_url(request, tenant_slug)
    latest = latest_per_consumer(candidates, lambda c: tag is None or tag in c.tags)
    latest.sort(key=lambda c: c.consumer_name.casefold())
    links = [
        {
            "href": _candidate_pact_url(base, record, candidate),
            "title": _candidate_title(record, candidate),
            "name": candidate.consumer_name,
        }
        for candidate in latest
    ]
    self_url = f"{_provider_url(base, record.slug)}/latest" + (f"/{quote(tag, safe='')}" if tag else "")
    title = f"Latest pact versions for the provider {record.name}" + (
        f" with consumer version tag '{tag}'" if tag else ""
    )
    return HalJSONResponse(
        {
            "_links": {
                "self": {"href": self_url, "title": title},
                "pb:provider": {"href": _pacticipant_url(base, record.slug), "name": record.name},
                "pb:pacts": links,
                "provider": {
                    "href": _pacticipant_url(base, record.slug),
                    "title": record.name,
                    "name": "DEPRECATED - please use the pb:provider relation",
                },
                "pacts": [
                    {**link, "title": f"DEPRECATED - please use the pb:pacts relation. {link['title']}"}
                    for link in links
                ],
            }
        }
    )


@router.get(
    "/{tenant_slug}/pact-broker/pacts/provider/{provider}/latest",
    response_class=HalJSONResponse,
    summary="The latest pact of every consumer of a provider",
    description=(
        "One `pb:pacts` link per consumer: the pact of its latest-recorded version that published "
        "one for the provider. `{provider}` is a pacticipant's handle, id or name. Requires "
        "`pacts:view`."
    ),
)
def read_latest_provider_pacts(
    tenant_slug: str,
    provider: str,
    request: Request,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> HalJSONResponse:
    """List the latest pact of each consumer of a provider.

    Args:
        tenant_slug: The tenant in the URL.
        provider: The provider's handle, id or name.
        request: The request.
        auth_data: The authenticated principal.

    Returns:
        The links to the pacts.

    Raises:
        HTTPException: 404 for an unknown provider, 403 without ``pacts:view``.
    """
    return _latest_provider_pacts(request, tenant_slug, provider, auth_data, None)


@router.get(
    "/{tenant_slug}/pact-broker/pacts/provider/{provider}/latest/{tag}",
    response_class=HalJSONResponse,
    summary="The latest pact of every consumer of a provider, for a tag",
    description=(
        "One `pb:pacts` link per consumer that has a version tagged `{tag}` with a pact for the "
        "provider: the pact of the latest such version. Requires `pacts:view`."
    ),
)
def read_latest_tagged_provider_pacts(
    tenant_slug: str,
    provider: str,
    tag: str,
    request: Request,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> HalJSONResponse:
    """List the latest tagged pact of each consumer of a provider.

    Args:
        tenant_slug: The tenant in the URL.
        provider: The provider's handle, id or name.
        tag: The consumer version tag, exactly as recorded.
        request: The request.
        auth_data: The authenticated principal.

    Returns:
        The links to the pacts.

    Raises:
        HTTPException: 404 for an unknown provider, 403 without ``pacts:view``.
    """
    return _latest_provider_pacts(request, tenant_slug, provider, auth_data, tag)


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
        "`pb:pacticipant-version` links of this API lead to. `pb:record-deployment` and "
        "`pb:record-release` list one link per environment of the workspace, named after it — what "
        "`pact-broker record-deployment` and `record-release` post to.\n\n"
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
        tenant_id = _tenant_id(auth_data)
        record = get_pacticipant(db, tenant_id, pacticipant)
        version = get_version(db, record, number)
    except PacticipantValidationError as exc:
        raise _http_error(exc) from exc
    environments = list_environments(db, tenant_id)
    return HalJSONResponse(_version_document(_base_url(request, tenant_slug), record, version, environments))
