"""``/v1/tenants/{tenant_slug}/pact-broker`` — verification results, PFX-1.4 (#6917).

What a provider's Pact verifier calls after it has replayed a pact, so can-i-deploy (PFX-1.6) can
answer from recorded results:

* ``PUT  …/pacticipants/{p}/branches/{branch}/versions/{v}`` and
  ``PUT  …/pacticipants/{p}/versions/{v}/tags/{tag}`` — record the provider version's branch and
  tags; a verifier follows the ``pb:branch-version`` and ``pb:version-tag`` links of the provider
  before it publishes;
* ``POST …/pacts/provider/{p}/consumer/{c}/pact-version/{sha}[/metadata/{m}]/verification-results``
  — publish one result (the pact's ``pb:publish-verification-results`` link);
* ``GET  …/pact-version/{sha}/verification-results/latest`` and ``…/verification-results/{number}``
  — read one back.

Results are immutable and numbered 1, 2, 3 … per pact version (apiome-db V434). Publishing needs
``pacts:create``, reading ``pacts:view``; a workspace API key is accepted as a bearer token here as
on every broker route (:mod:`app.pact_broker_auth`). Responses are ``application/hal+json`` in the
Pact Broker's shape; refusals keep Apiome's ``{"detail": {"code", "message", "pointer"}}``.

The helpers (base URL, links, error mapping) are the ones :mod:`app.pact_broker_routes` uses, so
links and refusals read the same across the broker surface.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, Path, Query, Request

from .bidirectional_verification import KIND_BIDIRECTIONAL
from .config import settings
from .consumer_contract_store import actor_from_auth
from .database import db
from .pact_audit import audited_write
from .pact_broker_auth import validate_broker_authentication
from .pact_broker_routes import (
    _PAIR_PATH,
    HalJSONResponse,
    _base_url,
    _http_error,
    _pair_url,
    _read_pact_body,
    _tenant_id,
    _version_document,
)
from .pact_commit_status_store import post_verification_statuses
from .pact_comparison_routes import comparison_fidelity_path
from .pact_external_verification import (
    FORMAT_AUTO,
    FORMATS,
    notices_as_dicts,
    read_external_report,
)
from .pact_publication import PactPublicationError
from .pact_selectors import decode_metadata
from .pact_webhook_events import fire_verification_events
from .pacticipant import PacticipantValidationError
from .permissions import Action, Resource, enforce_permission
from .verification_result import VerificationRequest, VerificationResultRecord, parse_verification_request
from .verification_result_store import (
    get_latest_verification_result,
    get_verification_result,
    publish_verification_result,
    record_broker_version,
)

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["pact-broker"])

_PACT_VERSION_PATH = "/{tenant_slug}/pact-broker" + _PAIR_PATH + "/pact-version/{sha}"

_RESULT_EXAMPLE = {
    "success": False,
    "providerApplicationVersion": "4f1e2d0",
    "buildUrl": "https://ci.example.com/builds/77",
    "testResults": [
        {
            "interactionId": "a1b2c3",
            "interactionDescription": "a request for an invoice",
            "success": False,
            "mismatches": [{"attribute": "status", "description": "expected 200 but was 404"}],
        }
    ],
    "verifiedBy": {
        "implementation": "Pact-Rust",
        "version": "1.2.0",
        "clientLanguage": {"name": "pact-js", "version": "13.1.0", "testFramework": "jest"},
    },
}

_RESULT_BODY = {
    "required": True,
    "content": {
        "application/json": {
            "schema": {
                "type": "object",
                "required": ["success", "providerApplicationVersion"],
                "properties": {
                    "success": {"type": "boolean", "description": "Whether every interaction passed."},
                    "providerApplicationVersion": {
                        "type": "string",
                        "description": "The provider version that verified (a commit SHA).",
                    },
                    "buildUrl": {"type": "string", "description": "http(s) URL of the CI build."},
                    "testResults": {
                        "type": "array",
                        "items": {"type": "object", "additionalProperties": True},
                        "description": "Per-interaction results, stored as sent (at most 10,000).",
                    },
                    "verifiedBy": {
                        "type": "object",
                        "properties": {
                            "implementation": {"type": "string"},
                            "version": {"type": "string"},
                            "clientLanguage": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "version": {"type": "string"},
                                    "testFramework": {"type": "string"},
                                },
                            },
                        },
                    },
                    "providerVerificationReportId": {
                        "type": "string",
                        "format": "uuid",
                        "description": (
                            "Apiome only: the CTG-4.3 provider verification report this result was "
                            "produced with. Linked, not copied."
                        ),
                    },
                },
            },
            "example": _RESULT_EXAMPLE,
        }
    },
}

_RESULT_ERRORS = {
    404: {"description": "`pacticipant-not-found` or `pact-not-found`: no such pair or pact version."},
    422: {
        "description": (
            "`pact-verification-invalid`: the body is malformed (`detail.pointer` names the field); "
            "`pact-verification-report-not-found`: `providerVerificationReportId` is not this workspace's."
        )
    },
}


# ---------------------------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------------------------


def _result_url(base: str, result: VerificationResultRecord) -> str:
    """The URL of one result."""
    pair = _pair_url(base, result.provider_slug, result.consumer_slug)
    return f"{pair}/pact-version/{result.sha}/verification-results/{result.number}"


def _pact_name(result: VerificationResultRecord) -> str:
    """How the verified pact is named in a link."""
    version = f" ({result.consumer_version})" if result.consumer_version else ""
    return f"Pact between {result.consumer_name}{version} and {result.provider_name}"


def _api_root(request: Request) -> str:
    """The public root of the REST API, for links that lead outside the broker surface."""
    return (settings.api_public_url or "").rstrip("/") or str(request.base_url).rstrip("/")


def _result_document(request: Request, tenant_slug: str, base: str, result: VerificationResultRecord) -> Dict[str, Any]:
    """Render a result the way a Pact Broker returns one.

    Fields the broker leaves out when empty (``buildUrl``, the ``verifiedBy`` entries) are left out
    here too. Apiome adds ``providerVersionBranch`` when the branch is known, ``kind`` (``native``
    or ``bidirectional``) and, when a CTG-4.3 report is linked, a ``pb:provider-verification-report``
    link to it. A bi-directional result (PFX-2.3) also carries the ``comparison`` payload and a
    ``pb:provider-contract`` link to the contract it was compared with, and an
    ``apiome:comparison-fidelity`` link to its fidelity report (PFX-2.5).

    Args:
        request: The request (for the API root of the report link).
        tenant_slug: The tenant in the URL.
        base: The broker base URL.
        result: The stored result.

    Returns:
        The response body.
    """
    verified_by = {
        key: value
        for key, value in (
            ("implementation", result.verified_by.get("implementation")),
            ("version", result.verified_by.get("version")),
            ("client_implementation", result.verified_by.get("client_implementation")),
            ("client_test_framework", result.verified_by.get("client_test_framework")),
            ("client_version", result.verified_by.get("client_version")),
        )
        if value is not None
    }
    pair = _pair_url(base, result.provider_slug, result.consumer_slug)
    body: Dict[str, Any] = {
        "providerName": result.provider_name,
        "providerApplicationVersion": result.provider_version,
        "success": result.success,
        "verificationDate": result.created_at,
    }
    if result.build_url:
        body["buildUrl"] = result.build_url
    if result.provider_branch:
        body["providerVersionBranch"] = result.provider_branch
    body["testResults"] = result.test_results
    body["verifiedBy"] = verified_by
    body["kind"] = result.kind
    if result.comparison is not None:
        body["comparison"] = result.comparison
    links: Dict[str, Any] = {
        "self": {
            "title": "Verification result",
            "name": f"Verification result {result.number} for {_pact_name(result)}",
            "href": _result_url(base, result),
        },
        "pb:pact-version": {
            "title": "Pact",
            "name": _pact_name(result),
            "href": f"{pair}/pact-version/{result.sha}",
        },
        "pb:triggered-webhooks": {
            "title": "Webhooks triggered by the publication of this verification result",
            "href": f"{_result_url(base, result)}/triggered-webhooks",
        },
    }
    if result.kind == KIND_BIDIRECTIONAL:
        links["pb:provider-contract"] = {
            "title": "Provider contract",
            "name": f"{result.provider_name} {result.provider_version}",
            "href": (
                f"{base}/contracts/provider/{quote(result.provider_slug, safe='')}"
                f"/version/{quote(result.provider_version, safe='')}"
            ),
        }
        # PFX-2.5 (#6929): what the comparison compared, and what it could not.
        links["apiome:comparison-fidelity"] = {
            "title": "Comparison fidelity report (Apiome)",
            "href": f"{_api_root(request)}{comparison_fidelity_path(tenant_slug, result.id)}",
        }
    if result.report_id:
        links["pb:provider-verification-report"] = {
            "title": "Provider verification report (Apiome)",
            "href": (
                f"{_api_root(request)}/v1/tenants/{quote(tenant_slug, safe='')}/provider-verifications/"
                f"{result.report_id}"
            ),
        }
    body["_links"] = links
    return body


# ---------------------------------------------------------------------------------------------
# Provider version branch and tags
# ---------------------------------------------------------------------------------------------


def _record_version(
    request: Request,
    tenant_slug: str,
    pacticipant: str,
    version: str,
    auth_data: Dict[str, Any],
    *,
    branch: Optional[str] = None,
    tag: Optional[str] = None,
) -> HalJSONResponse:
    """Record a version on a branch or with a tag behind ``pacts:create``.

    Args:
        request: The request.
        tenant_slug: The tenant in the URL.
        pacticipant: The pacticipant's handle, id or name.
        version: The version number.
        auth_data: The authenticated principal.
        branch: The branch, for ``PUT …/branches/{branch}/versions/{v}``.
        tag: The tag, for ``PUT …/versions/{v}/tags/{tag}``.

    Returns:
        The version in the broker's shape: ``201`` when this request created it, else ``200``.

    Raises:
        HTTPException: 400 for a malformed name, version, branch or tag; 403 without
            ``pacts:create``.
    """
    user_id = enforce_permission(db, auth_data, Resource.PACTS, Action.CREATE, target=pacticipant)
    try:
        record, recorded = record_broker_version(
            db,
            _tenant_id(auth_data),
            pacticipant,
            version,
            actor=actor_from_auth(auth_data, user_id),
            branch=branch,
            tags=[tag] if tag else [],
        )
    except PacticipantValidationError as exc:
        raise _http_error(exc) from exc
    return HalJSONResponse(
        _version_document(_base_url(request, tenant_slug), record, recorded.version),
        status_code=201 if recorded.created else 200,
    )


@router.put(
    "/{tenant_slug}/pact-broker/pacticipants/{pacticipant}/branches/{branch:path}/versions/{version}",
    response_class=HalJSONResponse,
    summary="Record a version on a branch (Pact Broker shape)",
    description=(
        "Record a pacticipant version on a branch — the `pb:branch-version` link a Pact verifier "
        "follows to record the provider's branch before it publishes a result. The pacticipant "
        "and the version are registered when the workspace does not have them yet; the branch "
        "head moves only to a version recorded later. The body is ignored.\n\n"
        "Answers `201` when the version is new, `200` otherwise. `{branch}` may contain `/`. "
        "Requires `pacts:create`."
    ),
    responses={201: {"description": "The version was created and recorded on the branch."}},
)
@audited_write("pacts.version.record", "pacticipant/{pacticipant}/version/{version}")
def put_branch_version(
    tenant_slug: str,
    pacticipant: str,
    branch: str,
    version: str,
    request: Request,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> HalJSONResponse:
    """Record a version on a branch.

    Args:
        tenant_slug: The tenant in the URL.
        pacticipant: The pacticipant's handle, id or name.
        branch: The branch name.
        version: The version number.
        request: The request.
        auth_data: The authenticated principal.

    Returns:
        The version.
    """
    return _record_version(request, tenant_slug, pacticipant, version, auth_data, branch=branch)


@router.put(
    "/{tenant_slug}/pact-broker/pacticipants/{pacticipant}/versions/{version}/tags/{tag}",
    response_class=HalJSONResponse,
    summary="Tag a version (Pact Broker shape)",
    description=(
        "Put a tag on a pacticipant version — the `pb:version-tag` link a Pact verifier follows "
        "to record the provider's tags before it publishes a result. The pacticipant and the "
        "version are registered when the workspace does not have them yet. The body is ignored.\n\n"
        "Answers `201` when the version is new, `200` otherwise. Requires `pacts:create`."
    ),
    responses={201: {"description": "The version was created with the tag."}},
)
@audited_write("pacts.tag.add", "pacticipant/{pacticipant}/version/{version}/tag/{tag}")
def put_version_tag(
    tenant_slug: str,
    pacticipant: str,
    version: str,
    tag: str,
    request: Request,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> HalJSONResponse:
    """Put a tag on a version.

    Args:
        tenant_slug: The tenant in the URL.
        pacticipant: The pacticipant's handle, id or name.
        version: The version number.
        tag: The tag.
        request: The request.
        auth_data: The authenticated principal.

    Returns:
        The version.
    """
    return _record_version(request, tenant_slug, pacticipant, version, auth_data, tag=tag)


# ---------------------------------------------------------------------------------------------
# Publishing and reading results
# ---------------------------------------------------------------------------------------------


def _publish(
    request: Request,
    tenant_slug: str,
    provider: str,
    consumer: str,
    sha: str,
    raw: bytes,
    auth_data: Dict[str, Any],
    metadata: Optional[str],
) -> HalJSONResponse:
    """Publish one result behind ``pacts:create``.

    Args:
        request: The request.
        tenant_slug: The tenant in the URL.
        provider: The provider's handle, id or name.
        consumer: The consumer's handle, id or name.
        sha: The verified pact version.
        raw: The body, already size-limited.
        auth_data: The authenticated principal.
        metadata: The for-verification metadata segment, when the result was posted to that form.

    Returns:
        The stored result, ``201``, with its URL in ``Location``.

    Raises:
        HTTPException: 400 for a malformed version or URL; 404 for an unknown pair or pact
            version; 422 for a malformed body or an unknown report; 403 without ``pacts:create``.
    """
    user_id = enforce_permission(db, auth_data, Resource.PACTS, Action.CREATE, target=provider)
    try:
        checked = parse_verification_request(raw)
    except (PactPublicationError, PacticipantValidationError) as exc:
        raise _http_error(exc) from exc
    return _store_result(request, tenant_slug, provider, consumer, sha, checked, auth_data, user_id, metadata)


def _store_result(
    request: Request,
    tenant_slug: str,
    provider: str,
    consumer: str,
    sha: str,
    checked: VerificationRequest,
    auth_data: Dict[str, Any],
    user_id: Optional[str],
    metadata: Optional[str],
    *,
    branch: Optional[str] = None,
    tags: Optional[List[str]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> HalJSONResponse:
    """Store a checked result, fire its webhooks and render it.

    Shared by the Pact verifier's publish (:func:`_publish`) and the ingestion of a report
    produced elsewhere (:func:`ingest_external_result`).

    Args:
        request: The request.
        tenant_slug: The tenant in the URL.
        provider: The provider's handle, id or name.
        consumer: The consumer's handle, id or name.
        sha: The verified pact version.
        checked: The checked result.
        auth_data: The authenticated principal.
        user_id: The permission check's user id.
        metadata: The for-verification metadata segment, when the result was posted to that form.
        branch: A branch to record the provider version on first, when the caller names one.
        tags: Tags to put on the provider version first.
        extra: Fields added to the response body (the ingestion's ``ingestion`` report).

    Returns:
        The stored result, ``201``, with its URL in ``Location``.

    Raises:
        HTTPException: 400/404/422 for a refusal of the store.
    """
    selection = decode_metadata(metadata)
    actor = actor_from_auth(auth_data, user_id)
    try:
        if branch or tags:
            record_broker_version(
                db,
                _tenant_id(auth_data),
                provider,
                checked.provider_version,
                actor=actor,
                branch=branch,
                tags=tags or [],
            )
        result = publish_verification_result(
            db,
            _tenant_id(auth_data),
            provider,
            consumer,
            sha,
            checked,
            actor=actor,
            pact_pending=selection["pending"],
            wip=selection["wip"],
        )
    except (PactPublicationError, PacticipantValidationError) as exc:
        raise _http_error(exc) from exc
    base = _base_url(request, tenant_slug)
    fire_verification_events(db, _tenant_id(auth_data), base, result)
    post_verification_statuses(db, _tenant_id(auth_data), base, result)
    document = _result_document(request, tenant_slug, base, result)
    if extra:
        document.update(extra)
    return HalJSONResponse(document, status_code=201, headers={"Location": _result_url(base, result)})


_PUBLISH_DESCRIPTION = (
    "Publish the result of verifying this pact version — what a Pact verifier posts to the pact's "
    "`pb:publish-verification-results` link when it runs with `publishVerificationResult: true`.\n\n"
    "- `success` and `providerApplicationVersion` are required. The provider version is recorded "
    "if the workspace does not have it yet.\n"
    "- `testResults` is stored as sent, so a failed result keeps every mismatch.\n"
    "- The result is immutable and numbered 1, 2, 3 … per pact version; the answer is `201` with "
    "its URL in `Location`.\n"
    "- The provider branch recorded with it is the branch the provider version was recorded on "
    "last (verifiers record it with `pb:branch-version` just before publishing).\n"
    "- `providerVerificationReportId` (Apiome only) links the CTG-4.3 provider verification "
    "report the result was produced with.\n\n"
    "Requires `pacts:create`."
)


@router.post(
    _PACT_VERSION_PATH + "/verification-results",
    response_class=HalJSONResponse,
    status_code=201,
    summary="Publish a verification result",
    description=_PUBLISH_DESCRIPTION,
    openapi_extra={"requestBody": _RESULT_BODY},
    responses=_RESULT_ERRORS,
)
@audited_write("pacts.verification.publish", "pact/provider/{provider}/consumer/{consumer}/pact-version/{sha}")
def publish_result(
    tenant_slug: str,
    provider: str,
    consumer: str,
    sha: str,
    request: Request,
    raw: bytes = Depends(_read_pact_body),
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> HalJSONResponse:
    """Publish a verification result for a pact version.

    Args:
        tenant_slug: The tenant in the URL.
        provider: The provider's handle, id or name.
        consumer: The consumer's handle, id or name.
        sha: The pact version's SHA-256.
        request: The request.
        raw: The body, already size-limited.
        auth_data: The authenticated principal.

    Returns:
        The stored result.
    """
    return _publish(request, tenant_slug, provider, consumer, sha, raw, auth_data, None)


@router.post(
    _PACT_VERSION_PATH + "/metadata/{metadata}/verification-results",
    response_class=HalJSONResponse,
    status_code=201,
    summary="Publish a verification result (for-verification link)",
    description=(
        _PUBLISH_DESCRIPTION + "\n\nThis form carries the metadata of the for-verification link the "
        "pact was fetched with; the result records whether the pact was pending then."
    ),
    openapi_extra={"requestBody": _RESULT_BODY},
    responses=_RESULT_ERRORS,
)
@audited_write("pacts.verification.publish", "pact/provider/{provider}/consumer/{consumer}/pact-version/{sha}")
def publish_result_with_metadata(
    tenant_slug: str,
    provider: str,
    consumer: str,
    sha: str,
    request: Request,
    metadata: str = Path(description="The selection metadata of the for-verification link (URL-safe base64)."),
    raw: bytes = Depends(_read_pact_body),
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> HalJSONResponse:
    """Publish a verification result through the for-verification form of the link.

    Args:
        tenant_slug: The tenant in the URL.
        provider: The provider's handle, id or name.
        consumer: The consumer's handle, id or name.
        sha: The pact version's SHA-256.
        request: The request.
        metadata: The for-verification metadata segment.
        raw: The body, already size-limited.
        auth_data: The authenticated principal.

    Returns:
        The stored result.
    """
    return _publish(request, tenant_slug, provider, consumer, sha, raw, auth_data, metadata)


_INGEST_DESCRIPTION = (
    "Publish the result of a verification that ran **elsewhere** — the report a team's own CI "
    "already has — instead of asking Apiome's hosted verifier to replay the pact (PFX-3.5).\n\n"
    "The body is the report itself, not a Pact Broker result:\n\n"
    "- **`pact_verifier_cli --json`** output (`Content-Type: application/json`): the verifier's "
    "`result` / `errors` / `pendingErrors`, or a `pacts[].interactions[]` listing;\n"
    "- **JUnit XML** (`application/xml`): one `<testcase>` per interaction; a `<failure>` or "
    "`<error>` fails it, a `<skipped>` case is not verified and makes the result unsuccessful.\n\n"
    "The format is taken from `format`, else the content type, else the body. The report is mapped "
    "to the verification-result model of `POST …/verification-results` and stored as an ordinary "
    "result, so the matrix, can-i-deploy, pending pacts and webhooks see it. Nothing is dropped "
    "silently: the answer is the stored result plus an `ingestion` object whose `notices` name, "
    "with a JSON Pointer or location, every field the reader could not use and every judgement it "
    "made. A report with no interactions is refused (`422 pact-verification-invalid`) rather than "
    "published as a pass. The report is the verifier's word: it is not cross-checked against the "
    "interactions of the pact version.\n\n"
    "`providerApplicationVersion` is required because neither format carries it. `branch` and "
    "`tag` record the provider version first, as a verifier's `PUT` calls would. Requires "
    "`pacts:create`."
)

_INGEST_BODY = {
    "required": True,
    "content": {
        "application/json": {
            "schema": {"type": "object", "additionalProperties": True},
            "example": {
                "result": False,
                "errors": [
                    {
                        "interactionId": "a1b2c3",
                        "description": "a request for an invoice",
                        "mismatch": {"type": "StatusMismatch", "description": "expected 200 but was 404"},
                    }
                ],
            },
        },
        "application/xml": {
            "schema": {"type": "string"},
            "example": "<testsuite name='pact'><testcase name='a request'/></testsuite>",
        },
    },
}


@router.post(
    _PACT_VERSION_PATH + "/external-verification-results",
    response_class=HalJSONResponse,
    status_code=201,
    summary="Ingest a verification report produced elsewhere",
    description=_INGEST_DESCRIPTION,
    openapi_extra={"requestBody": _INGEST_BODY},
    responses={
        **_RESULT_ERRORS,
        201: {"description": "The stored result, with an `ingestion` object (`format`, `interactions`, `notices`)."},
    },
)
@audited_write("pacts.verification.publish", "pact/provider/{provider}/consumer/{consumer}/pact-version/{sha}")
def ingest_external_result(
    tenant_slug: str,
    provider: str,
    consumer: str,
    sha: str,
    request: Request,
    provider_application_version: str = Query(
        alias="providerApplicationVersion", description="The provider version the report verified (a commit SHA)."
    ),
    build_url: Optional[str] = Query(default=None, alias="buildUrl", description="http(s) URL of the CI build."),
    branch: Optional[str] = Query(default=None, description="Record the provider version on this branch first."),
    tag: Optional[List[str]] = Query(default=None, description="Tag the provider version first (repeatable)."),
    report_format: str = Query(
        default=FORMAT_AUTO,
        alias="format",
        description=f"One of {', '.join(FORMATS)}; `auto` reads the content type, then the body.",
    ),
    verifier: Optional[str] = Query(default=None, description="The verifier's name, recorded in `verifiedBy`."),
    verifier_version: Optional[str] = Query(
        default=None, alias="verifierVersion", description="The verifier's version, recorded in `verifiedBy`."
    ),
    report_id: Optional[str] = Query(
        default=None,
        alias="providerVerificationReportId",
        description="Link a CTG-4.3 provider verification report (a UUID).",
    ),
    raw: bytes = Depends(_read_pact_body),
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> HalJSONResponse:
    """Ingest a ``pact_verifier_cli`` JSON or JUnit report as a verification result.

    Args:
        tenant_slug: The tenant in the URL.
        provider: The provider's handle, id or name.
        consumer: The consumer's handle, id or name.
        sha: The pact version's SHA-256.
        request: The request.
        provider_application_version: The verified provider version.
        build_url: The CI build, when sent.
        branch: A branch to record the provider version on.
        tag: Tags to put on the provider version.
        report_format: ``auto``, ``pact-verifier-json`` or ``junit``.
        verifier: ``verifiedBy.implementation``; defaults to the format's.
        verifier_version: ``verifiedBy.version``.
        report_id: A linked CTG-4.3 report.
        raw: The report, already size-limited.
        auth_data: The authenticated principal.

    Returns:
        The stored result and its ``ingestion`` report, ``201``.

    Raises:
        HTTPException: 400/422 for a malformed version, URL, format or report; 404 for an unknown
            pair or pact version; 403 without ``pacts:create``.
    """
    user_id = enforce_permission(db, auth_data, Resource.PACTS, Action.CREATE, target=provider)
    try:
        report = read_external_report(raw, content_type=request.headers.get("content-type"), fmt=report_format)
        # The shared parser checks the version, URL and report id exactly as a verifier's publish does.
        checked = parse_verification_request(
            json.dumps(
                {
                    "success": report.success,
                    "providerApplicationVersion": provider_application_version,
                    "buildUrl": build_url,
                    "testResults": report.test_results,
                    "verifiedBy": {"implementation": verifier or report.implementation, "version": verifier_version},
                    "providerVerificationReportId": report_id,
                }
            ).encode("utf-8")
        )
    except (PactPublicationError, PacticipantValidationError) as exc:
        raise _http_error(exc) from exc
    ingestion = {
        "format": report.format,
        "interactions": len(report.test_results),
        "success": report.success,
        "notices": notices_as_dicts(report.notices),
    }
    return _store_result(
        request,
        tenant_slug,
        provider,
        consumer,
        sha,
        checked,
        auth_data,
        user_id,
        None,
        branch=branch,
        tags=tag,
        extra={"ingestion": ingestion},
    )


def _read_result(request: Request, tenant_slug: str, auth_data: Dict[str, Any], load: Any) -> HalJSONResponse:
    """Run one result read behind ``pacts:view`` and render it.

    Raises:
        HTTPException: 404 for an unknown pair, pact version or result; 403 without ``pacts:view``.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    try:
        result = load(_tenant_id(auth_data))
    except (PactPublicationError, PacticipantValidationError) as exc:
        raise _http_error(exc) from exc
    return HalJSONResponse(_result_document(request, tenant_slug, _base_url(request, tenant_slug), result))


# Registered before `/{number}` so `latest` is not read as a number.
@router.get(
    _PACT_VERSION_PATH + "/verification-results/latest",
    response_class=HalJSONResponse,
    summary="Read the latest verification result of a pact version",
    description="The result published last for this pact version, by any provider version. Requires `pacts:view`.",
    responses={404: {"description": "`pact-verification-not-found`: the pact version has no results."}},
)
def read_latest_result(
    tenant_slug: str,
    provider: str,
    consumer: str,
    sha: str,
    request: Request,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> HalJSONResponse:
    """Read the latest result of a pact version.

    Args:
        tenant_slug: The tenant in the URL.
        provider: The provider's handle, id or name.
        consumer: The consumer's handle, id or name.
        sha: The pact version's SHA-256.
        request: The request.
        auth_data: The authenticated principal.

    Returns:
        The result.
    """
    return _read_result(
        request,
        tenant_slug,
        auth_data,
        lambda tenant_id: get_latest_verification_result(db, tenant_id, provider, consumer, sha),
    )


@router.get(
    _PACT_VERSION_PATH + "/verification-results/{number}",
    response_class=HalJSONResponse,
    summary="Read a verification result",
    description="One result of a pact version, by its number (1, 2, 3 …). Requires `pacts:view`.",
    responses={404: {"description": "`pact-verification-not-found`: no result with that number."}},
)
def read_result(
    tenant_slug: str,
    provider: str,
    consumer: str,
    sha: str,
    request: Request,
    number: int = Path(ge=1, description="The result's number among the results of this pact version."),
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> HalJSONResponse:
    """Read one result of a pact version.

    Args:
        tenant_slug: The tenant in the URL.
        provider: The provider's handle, id or name.
        consumer: The consumer's handle, id or name.
        sha: The pact version's SHA-256.
        request: The request.
        number: The result's number.
        auth_data: The authenticated principal.

    Returns:
        The result.
    """
    return _read_result(
        request,
        tenant_slug,
        auth_data,
        lambda tenant_id: get_verification_result(db, tenant_id, provider, consumer, sha, number),
    )
