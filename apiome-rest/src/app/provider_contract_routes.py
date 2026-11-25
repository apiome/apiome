"""``…/pact-broker/contracts/provider/{p}/version/{v}`` — provider contracts, PFX-2.1 (#6925).

Bi-directional contract testing needs the provider's OpenAPI document registered against a
provider version. These routes, on the tenant's Pact Broker surface, are where it is published and
read back:

* ``PUT …/pact-broker/contracts/provider/{provider}/version/{version}`` — publish the provider
  contract of a provider version: an OpenAPI 3.x document sent inline (base64 ``content``, JSON or
  YAML — PactFlow's shape) **or** named by ``apiomeVersion`` (``<project>@<version>``) and rendered
  from the canonical model; with the version's ``branch``, ``tags`` and ``buildUrl``, and the
  provider's self-verification results (``verificationResults``): a third-party report, or an
  Apiome provider-verification report named by id, read into ``selfVerification`` (PFX-2.4);
* ``GET …/pact-broker/contracts/provider/{provider}/version/{version}`` — the contract that
  version published.

A contract is write-once per provider version: ``201`` when it is new, ``200`` when the same
contract (same document, same self-verification results) is published again, ``409`` otherwise.
Content is stored once per provider by its SHA-256 (:mod:`app.provider_contract_store`).

Publishing needs ``pacts:create``, ``versions:view`` as well when it names an Apiome version, and
``verification_evidence:view`` when it cites an Apiome provider-verification report (the report is
read); reading needs ``pacts:view``. A workspace API key may be sent as ``Authorization: Bearer <key>``
(:mod:`app.pact_broker_auth`). Refusals are ``{"detail": {"code", "message", "pointer"}}``; the
pointer locates the problem in the OpenAPI document (``provider-contract-invalid``) or in the
request body.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError

from .bidirectional_store import compare_provider_contract
from .config import settings
from .consumer_contract_store import actor_from_auth
from .database import db
from .pact_broker_auth import validate_broker_authentication
from .pact_broker_routes import (
    HalJSONResponse,
    _base_url,
    _body_reader,
    _enforce_publish_budget,
    _http_error,
    _pacticipant_url,
    _tenant_id,
    _version_url,
)
from .pacticipant import PacticipantValidationError
from .permissions import Action, Resource, enforce_permission
from .provider_contract import (
    CODE_REQUEST_INVALID,
    ProviderContractError,
    ProviderContractRecord,
    PublishProviderContractRequest,
    SelfVerificationResults,
    check_request,
    decode_base64,
    parse_apiome_reference,
    parse_openapi,
    prepare_contract,
    stored_verification_results,
)
from .provider_contract_evidence import (
    CODE_EVIDENCE_REPORT_NOT_FOUND,
    SUPPORTED_CONTENT_TYPES,
    ContractSource,
    Evidence,
    decode_report,
    evidence_from_conformance_report,
    evidence_of,
    missing_evidence,
    read_uploaded_report,
    unsent_evidence,
)
from .provider_contract_source import ResolvedSource, render_apiome_contract, resolve_apiome_source
from .provider_contract_store import get_provider_contract, publish_provider_contract
from .provider_verification_store import ProviderVerificationStoreError, get_report

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["pact-broker"])

_PATH = "/{tenant_slug}/pact-broker/contracts/provider/{provider}/version/{provider_version}"

#: A base64 document is 4/3 of its size, and the results ride along: twice the document limit.
_read_contract_body = _body_reader(2)

_OAS_EXAMPLE = {
    "openapi": "3.1.0",
    "info": {"title": "Ledger API", "version": "1.4.0"},
    "paths": {"/invoices/{id}": {"get": {"responses": {"200": {"description": "The invoice"}}}}},
}

_PUBLISH_BODY = {
    "required": True,
    "content": {
        "application/json": {
            "schema": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "The OpenAPI 3.x document (JSON or YAML), base64-encoded. "
                        "Send this or `apiomeVersion`.",
                    },
                    "contractType": {"type": "string", "enum": ["oas"], "default": "oas"},
                    "contentType": {
                        "type": "string",
                        "description": "How `content` is encoded: `application/json` or `application/yaml`. "
                        "Sniffed when omitted.",
                    },
                    "apiomeVersion": {
                        "type": "string",
                        "description": "`<project>@<version>`: render the contract from an Apiome version "
                        "instead of sending it. `<version>` alone uses the project the provider is bound to; "
                        "`latest` is the project's newest version. Send this or `content`.",
                    },
                    "branch": {"type": "string", "description": "The repository branch the version was built from."},
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tags for the provider version (at most 50).",
                    },
                    "buildUrl": {"type": "string", "description": "http(s) URL of the CI build."},
                    "verificationResults": {
                        "type": "object",
                        "description": "The provider's self-verification (PFX-2.4): a report in `content`, or an "
                        "Apiome provider-verification report in `providerVerificationReportId` — not both. Read into "
                        "`selfVerification`; without passing evidence the contract is unverified.",
                        "properties": {
                            "success": {
                                "type": "boolean",
                                "description": "Required unless `providerVerificationReportId` is sent.",
                            },
                            "content": {"type": "string", "description": "The verifier's report, base64-encoded."},
                            "contentType": {
                                "type": "string",
                                "enum": list(SUPPORTED_CONTENT_TYPES),
                                "description": "The report's media type; sniffed when omitted. `text/plain` is "
                                "stored but cannot be read, so it is inconclusive.",
                            },
                            "verifier": {"type": "string", "examples": ["schemathesis", "dredd", "newman"]},
                            "verifierVersion": {"type": "string"},
                            "providerVerificationReportId": {
                                "type": "string",
                                "format": "uuid",
                                "description": "An Apiome provider-verification report of this workspace (CTG-4.3). "
                                "Needs `verification_evidence:view`.",
                            },
                        },
                    },
                },
            },
            "examples": {
                "inline": {
                    "summary": "An uploaded OpenAPI document",
                    "value": {
                        "contractType": "oas",
                        "contentType": "application/yaml",
                        "content": (
                            "b3BlbmFwaTogMy4xLjAKaW5mbzoKICB0aXRsZTogTGVkZ2VyIEFQSQog"
                            "IHZlcnNpb246IDEuNC4wCnBhdGhzOiB7fQo="
                        ),
                        "branch": "main",
                        "buildUrl": "https://ci.example.com/builds/4813",
                        "verificationResults": {
                            "success": True,
                            "verifier": "dredd",
                            "contentType": "application/xml",
                            "content": (
                                "PHRlc3RzdWl0ZSBuYW1lPSJEcmVkZCBUZXN0cyIgdGVzdHM9IjEiIGZhaWx1cmVzPSIwIj48dGVzdGNh"
                                "c2UgbmFtZT0iR0VUICgyMDApIC9pbnZvaWNlcy9hYmMxIi8+PC90ZXN0c3VpdGU+"
                            ),
                        },
                    },
                },
                "report": {
                    "summary": "Rendered from an Apiome version, with an Apiome provider-verification report",
                    "value": {
                        "apiomeVersion": "ledger-api@1.4.0",
                        "branch": "main",
                        "verificationResults": {"providerVerificationReportId": "6f1c2b3a-4d5e-4f60-8a7b-9c0d1e2f3a4b"},
                    },
                },
                "reference": {
                    "summary": "Rendered from an Apiome version",
                    "value": {"apiomeVersion": "ledger-api@1.4.0", "branch": "main"},
                },
            },
        }
    },
}

_RESPONSES: Dict[int | str, Dict[str, Any]] = {
    200: {
        "description": "The same contract was published again: nothing changed. `comparisons` reports the pacts "
        "compared with it, as for `201`."
    },
    201: {
        "description": "The contract was published for this provider version. `selfVerification` says what the "
        "evidence proved (`status` `verified`, `failed`, `inconclusive` or `missing`, with `kind`, `tool`, "
        "`digest`, `summary` and `reasons`) and whether the contract is `providerContractVerified`. `comparisons` "
        "reports the bi-directional comparisons the publish ran: the counts (`compared`, `alreadyCompared`, "
        "`errors`, `skipped`) and one entry per pact, with its `status`, `verdict` (`unverified` when the contract "
        "has no passing evidence), `success` and `verificationNumber`."
    },
    409: {
        "description": "`provider-contract-conflict`: this provider version already published a different "
        "contract (or the same one with different self-verification results). Nothing was stored."
    },
    413: {
        "description": "`provider-contract-too-large`: the document or the request is over the size limit. "
        "`provider-contract-evidence-too-large`: the self-verification report is over "
        "`APIOME_PACT_EVIDENCE_MAX_BYTES`."
    },
    422: {
        "description": "`provider-contract-invalid`: the document is not OpenAPI 3.0, 3.1 or 3.2 — `detail.pointer` "
        "is the JSON Pointer of the problem in the document (`/swagger` for Swagger 2.0, `/openapi`, or the first "
        "meta-schema error). `provider-contract-request-invalid` / `provider-contract-unsupported`: a field of the "
        "request (`detail.pointer` locates it). `provider-contract-source-not-found`: `apiomeVersion` names no "
        "project or version of this workspace. `provider-contract-evidence-unsupported`: the report's `contentType` "
        "is not one a report is read as. `provider-contract-evidence-invalid`: the report is not what its type says "
        "(XML that does not parse or is not JUnit, a DTD, JSON that is not JSON, text that is not UTF-8). "
        "`provider-contract-evidence-report-not-found`: `providerVerificationReportId` names no report of this "
        "workspace."
    },
    429: {"description": "`pact-publish-rate-limited`: over the workspace's publish budget; see `Retry-After`."},
}


def _self_verification(contract: ProviderContractRecord) -> Dict[str, Any]:
    """What the contract's self-verification evidence proved, for the response (PFX-2.4).

    Args:
        contract: The stored contract.

    Returns:
        The evidence (``status``, ``kind``, ``tool``, ``toolVersion``, ``digest``, ``summary``,
        ``reasons``, ``notes``, and for an Apiome report ``reportId``, ``target``, ``coverage``),
        ``providerContractVerified``, and the ``unverifiedPolicy`` its comparisons are held to.
    """
    evidence = evidence_of(contract.verification_results, max_bytes=settings.pact_evidence_max_bytes)
    return {
        **evidence.to_dict(),
        "providerContractVerified": evidence.verified,
        "unverifiedPolicy": settings.pact_unverified_provider_contract,
    }


def _contract_document(base: str, contract: ProviderContractRecord) -> Dict[str, Any]:
    """Render a stored provider contract as the response body.

    Args:
        base: The broker base URL.
        contract: The stored contract.

    Returns:
        The contract's metadata, its ``selfVerification``, the OpenAPI document in ``content``,
        and links to itself, the provider and the provider version.
    """
    self_url = (
        f"{base}/contracts/provider/{quote(contract.provider_slug, safe='')}"
        f"/version/{quote(contract.provider_version, safe='')}"
    )
    source: Dict[str, Any] = {"kind": contract.source}
    if contract.source_project_slug is not None:
        source.update(
            project=contract.source_project_slug,
            version=contract.source_version_label,
            projectId=contract.source_project_id,
            versionId=contract.source_version_id,
        )
    return {
        "provider": {"name": contract.provider_name},
        "providerVersion": contract.provider_version,
        "contractType": "oas",
        "contentType": contract.content_type,
        "contentSha": contract.sha,
        "oasVersion": contract.oas_version,
        "operationCount": contract.operation_count,
        "source": source,
        "verificationResults": contract.verification_results,
        "selfVerification": _self_verification(contract),
        "createdAt": contract.created_at,
        "content": contract.content,
        "_links": {
            "self": {
                "title": "Provider contract",
                "name": f"{contract.provider_name} {contract.provider_version}",
                "href": self_url,
            },
            "pb:provider": {
                "title": "Provider",
                "name": contract.provider_name,
                "href": _pacticipant_url(base, contract.provider_slug),
            },
            "pb:provider-version": {
                "title": "Provider version",
                "name": contract.provider_version,
                "href": _version_url(base, contract.provider_slug, contract.provider_version),
            },
        },
    }


def _parse_body(raw: bytes) -> PublishProviderContractRequest:
    """Parse the publish request, locating the first malformed field.

    Args:
        raw: The request body.

    Returns:
        The request, checked by :func:`app.provider_contract.check_request`.

    Raises:
        ProviderContractError: ``provider-contract-request-invalid`` or
            ``provider-contract-unsupported``, with a pointer into the body.
    """
    try:
        body = PublishProviderContractRequest.model_validate_json(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        pointer = "".join(f"/{part}" for part in first.get("loc", ()))
        raise ProviderContractError(
            CODE_REQUEST_INVALID, f"{pointer or '(request body)'}: {first.get('msg', 'invalid')}", pointer=pointer
        ) from exc
    check_request(body)
    return body


def _read_evidence(
    results: Optional[SelfVerificationResults],
    *,
    auth_data: Dict[str, Any],
    tenant_id: str,
    source: Optional[ResolvedSource],
) -> Evidence:
    """Read the self-verification evidence a publish request carries (PFX-2.4).

    Args:
        results: The request's ``verificationResults``, if any.
        auth_data: The authenticated principal (citing a report needs ``verification_evidence:view``).
        tenant_id: The caller's tenant; a cited report is looked up in it only.
        source: The Apiome version the contract is rendered from, or ``None`` for an inline one.

    Returns:
        The evidence: ``missing`` without results.

    Raises:
        ProviderContractError: the refusals of :func:`app.provider_contract_evidence.read_uploaded_report`,
            and ``provider-contract-evidence-report-not-found`` for a report id of no report of this
            workspace.
        HTTPException: 403 citing a report without ``verification_evidence:view``.
    """
    if results is None:
        return missing_evidence()
    if results.report_id is not None:
        enforce_permission(db, auth_data, Resource.VERIFICATION_EVIDENCE, Action.VIEW)
        try:
            record = get_report(tenant_id, results.report_id.strip().lower())
        except ProviderVerificationStoreError as exc:
            raise ProviderContractError(
                CODE_EVIDENCE_REPORT_NOT_FOUND,
                f"this workspace has no provider verification report '{results.report_id}'",
                pointer="/verificationResults/providerVerificationReportId",
            ) from exc
        contract_source = (
            ContractSource(source.project_id, source.project_slug, source.version_label) if source else None
        )
        return evidence_from_conformance_report(record, success=results.success, source=contract_source)
    if results.content is not None:
        return read_uploaded_report(
            decode_report(results.content),
            content_type=results.content_type,
            verifier=results.verifier,
            verifier_version=results.verifier_version,
            success=results.success,
            max_bytes=settings.pact_evidence_max_bytes,
        )
    return unsent_evidence(bool(results.success), verifier=results.verifier, verifier_version=results.verifier_version)


@router.put(
    _PATH,
    response_class=HalJSONResponse,
    summary="Publish a provider contract",
    description=(
        "Register the provider's OpenAPI document — its **provider contract** — against a provider version, "
        "for bi-directional contract testing. Send the document inline in `content` (base64; JSON or YAML, "
        "PactFlow's shape) **or** name an Apiome version in `apiomeVersion` (`ledger-api@1.4.0`) to render it "
        "from the canonical model with the exporter `GET /v1/schema/…` uses (OpenAPI 3.1). With a provider bound "
        "to its Apiome project, `apiomeVersion` may be just the version, and `latest` is the project's newest.\n\n"
        "- **Only OpenAPI 3.0, 3.1 and 3.2.** The document must validate against its version's meta-schema. "
        "Swagger 2.0, AsyncAPI and anything else are `422 provider-contract-invalid`, with `detail.pointer` "
        "locating the problem.\n"
        "- **The provider is registered on first use**, and the version is recorded with its `branch`, `tags` "
        "and `buildUrl`, as `PUT …/pacticipants/{ref}/versions/{number}` does.\n"
        "- **Content is stored once.** The document is addressed by the SHA-256 of its canonical JSON "
        "(`contentSha`), so JSON, YAML and a rendered copy of one document are one contract.\n"
        "- **Write-once.** `201` for a new contract, `200` when the same contract and self-verification results "
        "are published again (nothing changes), `409` for anything different.\n\n"
        "**Self-verification evidence.** The contract is trusted only when evidence says the provider matches it. "
        "`verificationResults` carries a report — JUnit XML (Schemathesis, Dredd, Newman or any JUnit writer), "
        "Newman JSON or Schemathesis NDJSON, at most `APIOME_PACT_EVIDENCE_MAX_BYTES` — or names an Apiome "
        "provider-verification report in `providerVerificationReportId`. The report is read and recorded with its "
        "kind, tool and SHA-256 digest in `selfVerification`: `verified`, `failed`, `inconclusive` (unreadable, "
        "nothing executed, or an Apiome report of another version) or `missing`. Without `verified` evidence the "
        "contract is unverified: its comparisons read verdict `unverified`, and under "
        "`APIOME_PACT_UNVERIFIED_PROVIDER_CONTRACT=fail` they fail.\n\n"
        "**Bi-directional comparison.** After the contract is stored it is compared with the pacts that need it "
        "— each consumer's main-branch pact, the pacts deployed or released, the latest pact of each consumer on "
        "the provider version's branch, and every pact compared before with a contract of that branch — and each "
        "comparison is stored as a verification result with `kind: bidirectional`, which the matrix and "
        "can-i-deploy read like a native one. `comparisons` in the response reports each pact. Requires "
        "`pacts:create`, `versions:view` with `apiomeVersion`, and `verification_evidence:view` with "
        "`providerVerificationReportId`."
    ),
    openapi_extra={"requestBody": _PUBLISH_BODY},
    responses=_RESPONSES,
)
def publish_contract(
    tenant_slug: str,
    provider: str,
    provider_version: str,
    request: Request,
    raw: bytes = Depends(_read_contract_body),
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> HalJSONResponse:
    """Publish the provider contract of one provider version.

    Args:
        tenant_slug: The tenant in the URL.
        provider: The provider's name or handle.
        provider_version: The provider's application version.
        request: The request.
        raw: The request body, already size-limited.
        auth_data: The authenticated principal.

    Returns:
        The stored contract, with 201 when it is new for this provider version.

    Raises:
        HTTPException: 400 for a malformed name, version, branch, tag or URL; 409 for a different
            contract; 413 over the size limit; 422 with a pointer for a non-OpenAPI document or a
            malformed request or an unreadable self-verification report; 429 over the publish
            budget; 403 without ``pacts:create`` (or ``versions:view`` when naming an Apiome
            version, or ``verification_evidence:view`` when citing an Apiome report).
    """
    user_id = enforce_permission(db, auth_data, Resource.PACTS, Action.CREATE, target=provider)
    tenant_id = _tenant_id(auth_data)
    _enforce_publish_budget(tenant_id)
    actor = actor_from_auth(auth_data, user_id)
    try:
        body = _parse_body(raw)
        source: Optional[ResolvedSource] = None
        if body.apiome_version is not None:
            enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW, target=body.apiome_version)
            source = resolve_apiome_source(db, tenant_id, provider, parse_apiome_reference(body.apiome_version))
        # PFX-2.4: read the evidence before anything is stored, so a bad report stores nothing.
        evidence = _read_evidence(body.verification_results, auth_data=auth_data, tenant_id=tenant_id, source=source)
        results = (
            stored_verification_results(body.verification_results, evidence.to_dict())
            if body.verification_results is not None
            else None
        )
        if source is not None:
            contract = render_apiome_contract(db, tenant_id, source, verification_results=results)
        else:
            document, content_type = parse_openapi(
                decode_base64(body.content or "", "/content", "the contract content"),
                content_type=body.content_type,
                max_bytes=settings.pact_max_bytes,
            )
            contract = prepare_contract(document, content_type=content_type, verification_results=results)
        outcome = publish_provider_contract(
            db,
            tenant_id,
            provider_name=provider,
            version_number=provider_version,
            contract=contract,
            actor=actor,
            branch=body.branch,
            tags=body.tags,
            build_url=body.build_url,
        )
    except (ProviderContractError, PacticipantValidationError) as exc:
        raise _http_error(exc) from exc
    # PFX-2.3: compare the contract with the pacts that need it; the results land in the matrix.
    comparisons = compare_provider_contract(
        db, tenant_id, outcome.contract.provider_slug, outcome.contract.provider_version, actor=actor
    )
    document = _contract_document(_base_url(request, tenant_slug), outcome.contract)
    document["comparisons"] = comparisons.to_dict()
    return HalJSONResponse(document, status_code=201 if outcome.created else 200)


@router.get(
    _PATH,
    response_class=HalJSONResponse,
    summary="Read a provider contract",
    description=(
        "The provider contract a provider version published: `contentSha`, `oasVersion`, `operationCount`, "
        "`contentType`, where it came from (`source`: `inline`, or `apiome` with the project and version it was "
        "rendered from), the `verificationResults` sent with it, and the OpenAPI document in `content`.\n\n"
        "`{provider}` is a pacticipant's handle, id or name. Requires `pacts:view`."
    ),
    responses={404: {"description": "`pacticipant-not-found` or `provider-contract-not-found`."}},
)
def read_contract(
    tenant_slug: str,
    provider: str,
    provider_version: str,
    request: Request,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> HalJSONResponse:
    """Read the provider contract of one provider version.

    Args:
        tenant_slug: The tenant in the URL.
        provider: The provider's handle, id or name.
        provider_version: The provider version number.
        request: The request.
        auth_data: The authenticated principal.

    Returns:
        The contract.

    Raises:
        HTTPException: 404 for an unknown provider or a version without a contract; 403 without
            ``pacts:view``.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    try:
        contract = get_provider_contract(db, _tenant_id(auth_data), provider, provider_version)
    except (ProviderContractError, PacticipantValidationError) as exc:
        raise _http_error(exc) from exc
    return HalJSONResponse(_contract_document(_base_url(request, tenant_slug), contract))
