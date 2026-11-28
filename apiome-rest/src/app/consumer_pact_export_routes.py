"""Export, and publish, a Pact v4 file from a declared consumer surface — PFX-2.6 (#6930).

A consumer declared through the UI picker (CTG-4.1) has no Pact file of its own. These two
endpoints write one from its contract revision (:mod:`app.consumer_pact_export`) and, for the
second, publish it to the workspace's Pact Broker exactly as ``POST …/pact-broker/contracts/
publish`` would — so a picker-declared consumer takes part in the matrix, ``can-i-deploy`` and
bi-directional comparisons like any consumer with a contract test suite.

* ``GET  …/projects/{project}/consumers/{consumer}/pact`` — the generated pact and its findings.
  Requires ``consumer_contracts:view`` and ``pacts:view``.
* ``POST …/projects/{project}/consumers/{consumer}/pact/publish`` — generate, then publish for a
  consumer version. Requires ``consumer_contracts:view`` and ``pacts:create``.

Only a ``manual`` (picker) revision is exported. A revision imported from a Pact file already has
the pact it came from — publish that one — and an agent revision (CDG-5.2) declares tools, not
HTTP fields. Both are refused with a code rather than turned into a weaker copy.

Every read is scoped by the caller's tenant: a consumer, project or pacticipant binding in another
workspace answers 404 (or is simply not seen), never data.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from .auth import validate_authentication
from .bidirectional_store import compare_published_pacts
from .config import settings
from .consumer_contract import (
    SOURCE_MANUAL,
    ConsumerContractRecord,
    ConsumerRecord,
    ConsumerValidationError,
)
from .consumer_contract_routes import _http_error as _registry_error
from .consumer_contract_routes import _spec_index, _tenant_id
from .consumer_contract_store import (
    actor_from_auth,
    contract_revision,
    current_contract,
    get_consumer,
    resolve_project,
    resolve_version,
)
from .consumer_pact_export import (
    OUTCOME_OMITTED,
    OUTCOME_PLACEHOLDER,
    ExportFinding,
    PactExport,
    build_consumer_pact,
)
from .consumer_pact_export_store import CODE_PROVIDER_AMBIGUOUS, PactNames, resolve_pact_names
from .database import db
from .pact_audit import audited_write
from .pact_broker_routes import _base_url, _enforce_publish_budget, _publish_result
from .pact_broker_routes import _http_error as _broker_error
from .pact_commit_status_store import post_publish_statuses
from .pact_publication import PactPublicationError, prepare_pact
from .pact_publication_store import publish_pacts
from .pact_webhook_events import fire_publish_events
from .pacticipant import PacticipantValidationError
from .permissions import Action, Resource, enforce_permission

__all__ = [
    "CODE_EXPORT_EMPTY",
    "CODE_EXPORT_NO_VERSION",
    "CODE_EXPORT_SOURCE",
    "router",
]

router = APIRouter(prefix="/v1/tenants", tags=["consumer-contracts"])

#: The revision produced no interaction at all — there is nothing to export or publish.
CODE_EXPORT_EMPTY = "consumer-pact-export-empty"
#: The revision was not declared through the picker.
CODE_EXPORT_SOURCE = "consumer-pact-export-unsupported-source"
#: The revision records no specification version to read examples from.
CODE_EXPORT_NO_VERSION = "consumer-pact-export-no-version"

_CONSUMER_PATH = "/{tenant_slug}/projects/{project_ref}/consumers/{consumer_ref}"


# ---------------------------------------------------------------------------------------------
# Shapes
# ---------------------------------------------------------------------------------------------


class PactExportResponse(BaseModel):
    """A generated pact and what it could not say."""

    model_config = ConfigDict(extra="forbid")

    consumer_name: str = Field(description="`consumer.name` in the pact (the pacticipant it publishes as).")
    provider_name: str = Field(description="`provider.name` in the pact.")
    consumer_pacticipant_bound: bool = Field(
        description="Whether the consumer name is that of a pacticipant bound to this consumer."
    )
    provider_pacticipant_bound: bool = Field(
        description="Whether the provider name is that of the pacticipant bound to this project."
    )
    revision: int = Field(description="The contract revision the pact was generated from.")
    version_record_id: str = Field(description="The specification revision the examples were read from.")
    version_label: Optional[str] = Field(default=None, description="That revision's label.")
    interaction_count: int = Field(description="How many interactions the pact carries.")
    placeholder_count: int = Field(description="How many values were invented because no example exists.")
    omitted_count: int = Field(description="How many declared items could not be written at all.")
    findings: List[ExportFinding] = Field(
        default_factory=list,
        description="Every placeholder and omission, with a stable reason code. Never silently empty.",
    )
    pact: Dict[str, Any] = Field(description="The Pact v4 document.")


class PactExportPublishRequest(BaseModel):
    """Publish the generated pact for one consumer version."""

    model_config = ConfigDict(extra="forbid")

    consumer_version: str = Field(min_length=1, max_length=255, description="The consumer build's version.")
    branch: Optional[str] = Field(default=None, max_length=255, description="The branch it was built from.")
    tags: List[str] = Field(default_factory=list, max_length=50, description="Tags for the consumer version.")
    build_url: Optional[str] = Field(default=None, max_length=2048, description="http(s) URL of the CI build.")
    revision: Optional[int] = Field(default=None, ge=1, description="A contract revision; defaults to the current one.")
    provider: Optional[str] = Field(
        default=None, max_length=200, description="The provider pacticipant name; see the export endpoint."
    )


class PactExportPublishResponse(PactExportResponse):
    """The generated pact, plus what the broker stored and the comparisons it ran."""

    publish: Dict[str, Any] = Field(
        description=(
            "The Pact Broker publish result, exactly as `POST …/pact-broker/contracts/publish` returns it: "
            "`notices`, the embedded pacticipant and version, `pb:contracts` and, when the provider "
            "has a provider contract, `comparisons`."
        )
    )


# ---------------------------------------------------------------------------------------------
# Shared
# ---------------------------------------------------------------------------------------------


def _export(
    tenant_id: str,
    tenant_slug: str,
    project_ref: str,
    consumer_ref: str,
    revision: Optional[int],
    provider: Optional[str],
) -> Tuple[ConsumerRecord, ConsumerContractRecord, PactNames, PactExport, Dict[str, Any]]:
    """Resolve the contract revision and generate its pact.

    Args:
        tenant_id: The caller's tenant.
        tenant_slug: The tenant in the URL (the document renderer needs it).
        project_ref: Project slug or id.
        consumer_ref: Consumer slug or id.
        revision: A specific contract revision, or ``None`` for the current one.
        provider: A provider pacticipant name, or ``None`` to choose one.

    Returns:
        The consumer, the revision, the names, the export and the version row.

    Raises:
        HTTPException: 404 for an unknown project, consumer, revision or specification version;
            409 ``consumer-pact-export-provider-ambiguous``; 422 for a non-picker revision, one
            without a specification version, one that cannot be rendered, or one that yields
            no interaction.
    """
    try:
        project = resolve_project(tenant_id, project_ref)
        consumer = get_consumer(tenant_id, str(project["id"]), consumer_ref)
        contract = (
            current_contract(tenant_id, consumer.id)
            if revision is None
            else contract_revision(tenant_id, consumer.id, revision)
        )
    except ConsumerValidationError as exc:
        raise _registry_error(exc) from exc

    if contract.source != SOURCE_MANUAL:
        hint = (
            "publish the Pact file it was imported from instead"
            if contract.source == "pact"
            else "it declares an agent's tools, not HTTP fields"
        )
        raise HTTPException(
            status_code=422,
            detail={
                "code": CODE_EXPORT_SOURCE,
                "message": (
                    f"revision {contract.revision} came from '{contract.source}', not the picker; "
                    f"only a picker-declared surface is exported — {hint}"
                ),
            },
        )
    if not contract.version_id:
        raise HTTPException(
            status_code=422,
            detail={
                "code": CODE_EXPORT_NO_VERSION,
                "message": (
                    f"revision {contract.revision} records no specification version to read examples "
                    f"from; declare the contract again to export it"
                ),
            },
        )

    try:
        version_row = resolve_version(tenant_id, str(project["id"]), contract.version_id)
        names = resolve_pact_names(db, tenant_id, project, consumer, provider)
    except ConsumerValidationError as exc:
        if exc.code == CODE_PROVIDER_AMBIGUOUS:
            raise HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)}) from exc
        raise _registry_error(exc) from exc

    index = _spec_index(tenant_id, tenant_slug, version_row)
    export = build_consumer_pact(
        contract, index, consumer_name=names.consumer, provider_name=names.provider, consumer_slug=consumer.slug
    )
    if export.interaction_count == 0:
        raise HTTPException(
            status_code=422,
            detail={
                "code": CODE_EXPORT_EMPTY,
                "message": (
                    f"revision {contract.revision} produced no interaction to export; every declared "
                    f"operation was omitted (see findings)"
                ),
                "findings": [finding.model_dump() for finding in export.findings],
            },
        )
    return consumer, contract, names, export, version_row


def _response_fields(
    contract: ConsumerContractRecord, names: PactNames, export: PactExport, version_row: Dict[str, Any]
) -> Dict[str, Any]:
    """The fields both responses share."""
    return {
        "consumer_name": names.consumer,
        "provider_name": names.provider,
        "consumer_pacticipant_bound": names.consumer_bound,
        "provider_pacticipant_bound": names.provider_bound,
        "revision": contract.revision,
        "version_record_id": str(version_row["id"]),
        "version_label": str(version_row.get("version_id") or "") or None,
        "interaction_count": export.interaction_count,
        "placeholder_count": sum(1 for f in export.findings if f.outcome == OUTCOME_PLACEHOLDER),
        "omitted_count": sum(1 for f in export.findings if f.outcome == OUTCOME_OMITTED),
        "findings": export.findings,
        "pact": export.document,
    }


_FINDINGS_NOTE = (
    "Each declared operation becomes one `Synchronous/HTTP` interaction per response status the "
    "consumer reads, carrying only the declared fields. Sample values are the specification's own "
    "examples (media-type `example` / `examples`, then the schema's `example`, `examples`, "
    "`default`, `const` or first `enum` value, then a parameter's `example`). Response bodies carry "
    "a cascading `type` matcher at `$`, so the provider must return the same shape, not the same "
    "values.\n\n"
    "**Nothing is dropped silently.** `findings` lists every value that had to be invented "
    "(`placeholder`, e.g. `no-example`, `status-range`) and everything that could not be written "
    "(`omitted`, e.g. `field-not-found`, `status-default`, `media-type-not-json`, "
    "`contract-unresolved`).\n\n"
    "`consumer.name` is the pacticipant bound to this consumer, else the consumer's handle. "
    "`provider.name` is `provider` when given, else the one pacticipant bound to the project, else "
    "the project's handle; several bound pacticipants without `provider` is "
    "`409 consumer-pact-export-provider-ambiguous`.\n\n"
    "Only a picker-declared (`manual`) revision is exported: a revision from a Pact file or an agent "
    "is `422 consumer-pact-export-unsupported-source`, and a revision that yields no interaction is "
    "`422 consumer-pact-export-empty` with its findings."
)


# ---------------------------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------------------------


@router.get(
    _CONSUMER_PATH + "/pact",
    response_model=PactExportResponse,
    summary="Export a consumer's declared surface as a Pact v4 file",
    description="Generate a Pact v4 document from a consumer contract revision declared through the picker.\n\n"
    + _FINDINGS_NOTE
    + "\n\nRequires `consumer_contracts:view` and `pacts:view`.",
    responses={
        409: {"description": "Several pacticipants are bound to the project."},
        422: {"description": "Not exportable."},
    },
)
def export_consumer_pact(
    tenant_slug: str,
    project_ref: str,
    consumer_ref: str,
    revision: Optional[int] = Query(
        default=None, ge=1, description="A contract revision; defaults to the current one."
    ),
    provider: Optional[str] = Query(default=None, max_length=200, description="The provider pacticipant name."),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> PactExportResponse:
    """Generate the pact of one contract revision.

    Args:
        tenant_slug: The tenant in the URL.
        project_ref: Project slug or id.
        consumer_ref: Consumer slug or id.
        revision: A specific revision, or the current one.
        provider: The provider pacticipant name to write.
        auth_data: The authenticated principal.

    Returns:
        The pact, the names it carries and its findings.

    Raises:
        HTTPException: 403 without ``consumer_contracts:view`` and ``pacts:view``; see
            :func:`_export` for the rest.
    """
    enforce_permission(db, auth_data, Resource.CONSUMER_CONTRACTS, Action.VIEW)
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    tenant_id = _tenant_id(auth_data)
    _consumer, contract, names, export, version_row = _export(
        tenant_id, tenant_slug, project_ref, consumer_ref, revision, provider
    )
    return PactExportResponse(**_response_fields(contract, names, export, version_row))


@router.post(
    _CONSUMER_PATH + "/pact/publish",
    response_model=PactExportPublishResponse,
    summary="Publish a consumer's declared surface to the Pact Broker",
    description="Generate the Pact v4 document of a picker-declared contract revision (as `GET …/pact` does) "
    "and publish it for a consumer version, exactly as `POST …/pact-broker/contracts/publish` would: the "
    "consumer and provider are registered as pacticipants on first use, the version is recorded with its "
    "branch and tags, identical content is stored once, a different pact for a version that already has "
    "one is `409 pact-content-conflict`, and bi-directional comparisons run against the provider's "
    "contracts. The workspace's publish rate limit applies.\n\n"
    + _FINDINGS_NOTE
    + "\n\nRequires `consumer_contracts:view` and `pacts:create`.",
    responses={
        409: {"description": "Ambiguous provider, or changed content for a published version."},
        422: {"description": "Not exportable."},
        429: {"description": "Over the publish budget."},
    },
)
@audited_write("pacts.publication.create", "project/{project_ref}/consumer/{consumer_ref}")
def publish_consumer_pact(
    tenant_slug: str,
    project_ref: str,
    consumer_ref: str,
    body: PactExportPublishRequest,
    request: Request,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> PactExportPublishResponse:
    """Generate the pact of one contract revision and publish it.

    Args:
        tenant_slug: The tenant in the URL.
        project_ref: Project slug or id.
        consumer_ref: Consumer slug or id.
        body: The consumer version, branch, tags, build URL, revision and provider.
        request: The request (for the broker links).
        auth_data: The authenticated principal.

    Returns:
        The pact, its findings and the broker's publish result.

    Raises:
        HTTPException: 403 without ``consumer_contracts:view`` and ``pacts:create``; 400 for a
            malformed version, branch, tag or URL; 409 for changed content; 429 over the publish
            budget; see :func:`_export` for the rest.
    """
    enforce_permission(db, auth_data, Resource.CONSUMER_CONTRACTS, Action.VIEW)
    user_id = enforce_permission(db, auth_data, Resource.PACTS, Action.CREATE)
    tenant_id = _tenant_id(auth_data)
    _consumer, contract, names, export, version_row = _export(
        tenant_id, tenant_slug, project_ref, consumer_ref, body.revision, body.provider
    )
    _enforce_publish_budget(tenant_id)
    actor = actor_from_auth(auth_data, user_id)
    try:
        pact = prepare_pact(
            json.dumps(export.document).encode("utf-8"),
            consumer_name=names.consumer,
            provider_name=names.provider,
            max_bytes=settings.pact_max_bytes,
        )
        outcome = publish_pacts(
            db,
            tenant_id,
            consumer_name=names.consumer,
            version_number=body.consumer_version,
            pacts=[pact],
            actor=actor,
            branch=body.branch,
            tags=body.tags,
            build_url=body.build_url,
            allow_modification=settings.pact_allow_contract_modification,
        )
    except (PactPublicationError, PacticipantValidationError) as exc:
        raise _broker_error(exc) from exc
    base = _base_url(request, tenant_slug)
    fire_publish_events(db, tenant_id, base, outcome)
    post_publish_statuses(db, tenant_id, base, outcome)
    comparisons = compare_published_pacts(db, tenant_id, outcome, actor=actor, base=base)
    return PactExportPublishResponse(
        **_response_fields(contract, names, export, version_row),
        publish=_publish_result(base, outcome, comparisons),
    )
