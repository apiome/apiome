"""Postman collection export of a pact — PFX-4.7 (#6944).

``POST /v1/tenants/{tenant}/pact-postman-collections`` writes a Postman Collection v2.1 from a pact
(:func:`app.pact_postman.pact_to_postman`): one request per HTTP interaction, a saved example of the
expected response, and test scripts that check it. The pact is either

* **stored** in the workspace's Pact Broker — ``provider`` and ``consumer``, plus at most one of
  ``consumerVersion``, ``tag``, ``branch`` or ``pactVersionSha`` (none: the latest pact), or
* **inline** — ``pact``, a Pact document not yet published (the names default to its own), or
* **every consumer** of a provider — ``provider`` with ``allConsumers`` (PFX-8.18, #7315), and at
  most one of ``tag`` or ``branch``: the latest such pact of each consumer, one folder each.

``stateSetup`` (PFX-8.18) gives each request that needs provider states a pre-request script that
sets them up through a ``{{stateChangeUrl}}`` variable (``stateChangeUrl`` fills it in).

The call is stateless: nothing is stored. It needs ``pacts:view`` and reads only the caller's
tenant. What the collection cannot carry (message and gRPC interactions, non-text bodies, values
governed by matching rules, generators) comes back as ``notices`` with a reason; a pact with no
HTTP interaction to export is a ``422`` that lists them.

The schema side — a collection from an Apiome version's OpenAPI or other specification — is the
``postman`` export target (``apiome export postman``); this route covers pacts.

It lives beside the Pact Broker surface, not under ``…/pact-broker``, because no Pact Broker or
PactFlow client knows it.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .auth import validate_authentication
from .config import settings
from .database import db
from .pact_contract_import import pact_consumer_name, pact_provider_name, pact_specification_version
from .pact_postman import OUTCOME_LEFT_OUT, POSTMAN_SCHEMA_URL, pact_to_postman
from .pact_publication import (
    CODE_PACT_INVALID,
    CODE_PACT_NOT_FOUND,
    CODE_PACT_TOO_LARGE,
    PactPublicationError,
    PactRecord,
    pact_content_sha,
    validate_pact_document,
)
from .pact_publication_store import get_latest_pact, get_pact, get_pact_by_sha, list_latest_pact_candidates
from .pacticipant import CODE_NOT_FOUND, PacticipantValidationError
from .permissions import Action, Resource, enforce_permission

__all__ = [
    "CODE_CONSUMER_NO_PACT",
    "CODE_EXPORT_INVALID",
    "CODE_NO_HTTP_INTERACTIONS",
    "PactPostmanRequest",
    "router",
]

router = APIRouter(prefix="/v1/tenants", tags=["pact-broker"])

#: The request names no pact, or names it two ways, or carries a bad option.
CODE_EXPORT_INVALID = "pact-postman-export-invalid"
#: The pact has no HTTP interaction the collection could carry.
CODE_NO_HTTP_INTERACTIONS = "pact-postman-no-http-interactions"
#: With ``allConsumers``: a consumer of the provider has no pact matching the tag or branch.
CODE_CONSUMER_NO_PACT = "pact-postman-consumer-no-pact"

_STATUS_BY_CODE = {
    CODE_EXPORT_INVALID: 422,
    CODE_PACT_INVALID: 422,
    CODE_PACT_TOO_LARGE: 413,
    CODE_PACT_NOT_FOUND: 404,
    CODE_NOT_FOUND: 404,
}


class PactPostmanRequest(BaseModel):
    """What to export: a stored pact (by pair and selection) or an inline Pact document."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    provider: Optional[str] = Field(
        None, description="The provider pacticipant (handle, id or name). Required for a stored pact."
    )
    consumer: Optional[str] = Field(
        None, description="The consumer pacticipant (handle, id or name). Required for a stored pact."
    )
    consumer_version: Optional[str] = Field(
        None, alias="consumerVersion", description="The pact this consumer version published."
    )
    tag: Optional[str] = Field(None, description="The latest pact of consumer versions with this tag.")
    branch: Optional[str] = Field(None, description="The latest pact of consumer versions on this branch.")
    pact_version_sha: Optional[str] = Field(
        None, alias="pactVersionSha", description="The pact with this content address (64 hex characters)."
    )
    pact: Optional[Dict[str, Any]] = Field(
        None,
        description="An inline Pact document (specification 1–4) instead of a stored pact. "
        "`consumer` and `provider` then only name the collection, and default to the document's own.",
    )
    base_url: Optional[str] = Field(
        None,
        alias="baseUrl",
        description="The value of the `{{baseUrl}}` collection variable (an http or https URL). "
        "Omitted: empty, to fill in (Newman: `--env-var baseUrl=…`).",
    )
    tests: bool = Field(True, description="Give each request a test script that checks the expected response.")
    all_consumers: bool = Field(
        False,
        alias="allConsumers",
        description="Export the latest pact of every consumer of `provider` (with `tag` or `branch`: the latest "
        "such pact), one folder per consumer. Leave `consumer`, `consumerVersion`, `pactVersionSha` and `pact` out.",
    )
    state_setup: bool = Field(
        False,
        alias="stateSetup",
        description="Give each request that needs provider states a pre-request script that first POSTs "
        '`{"state", "params", "action": "setup"}` per state to the `{{stateChangeUrl}}` variable.',
    )
    state_change_url: Optional[str] = Field(
        None,
        alias="stateChangeUrl",
        description="The value of the `{{stateChangeUrl}}` variable (an http or https URL; only with `stateSetup`). "
        "Omitted: empty, to fill in.",
    )


def _refuse(code: str, message: str, **extra: Any) -> HTTPException:
    """An ``HTTPException`` carrying ``{"code", "message", …}`` with the status of its code."""
    return HTTPException(status_code=_STATUS_BY_CODE.get(code, 422), detail={"code": code, "message": message, **extra})


def _tenant_id(auth_data: Dict[str, Any]) -> str:
    """The authenticated tenant id, or a 403."""
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this credential.")
    return str(tenant_id)


def _check_request(body: PactPostmanRequest) -> None:
    """Refuse a request that names no pact, names it two ways, or carries a bad base URL.

    Args:
        body: The request.

    Raises:
        HTTPException: 422 ``pact-postman-export-invalid`` with the reason.
    """
    selections = [
        name
        for name, value in (
            ("consumerVersion", body.consumer_version),
            ("tag", body.tag),
            ("branch", body.branch),
            ("pactVersionSha", body.pact_version_sha),
        )
        if value is not None
    ]
    if body.all_consumers:
        if body.pact is not None or (body.consumer or "").strip():
            raise _refuse(
                CODE_EXPORT_INVALID,
                "'allConsumers' exports every consumer of 'provider': leave 'consumer' and 'pact' out",
            )
        if not (body.provider or "").strip():
            raise _refuse(CODE_EXPORT_INVALID, "'allConsumers' needs 'provider'")
        pinned = [name for name in selections if name in ("consumerVersion", "pactVersionSha")]
        if pinned:
            raise _refuse(
                CODE_EXPORT_INVALID,
                f"'allConsumers' takes 'tag' or 'branch', not {', '.join(pinned)}: those name one consumer's pact",
            )
        if len(selections) > 1:
            raise _refuse(CODE_EXPORT_INVALID, f"choose one of {', '.join(selections)}, not several")
    elif body.pact is not None:
        if selections:
            raise _refuse(
                CODE_EXPORT_INVALID,
                f"an inline pact cannot be combined with {', '.join(selections)}: those select a stored pact",
            )
    else:
        if not (body.provider or "").strip() or not (body.consumer or "").strip():
            raise _refuse(CODE_EXPORT_INVALID, "name the stored pact with 'provider' and 'consumer', or send 'pact'")
        if len(selections) > 1:
            raise _refuse(CODE_EXPORT_INVALID, f"choose one of {', '.join(selections)}, not several")
    if body.base_url is not None and not _is_http_url(body.base_url):
        raise _refuse(CODE_EXPORT_INVALID, "'baseUrl' must be an absolute http or https URL")
    if body.state_change_url is not None:
        if not body.state_setup:
            raise _refuse(CODE_EXPORT_INVALID, "'stateChangeUrl' is only used with 'stateSetup'")
        if not _is_http_url(body.state_change_url):
            raise _refuse(CODE_EXPORT_INVALID, "'stateChangeUrl' must be an absolute http or https URL")


def _is_http_url(value: str) -> bool:
    """Whether ``value`` is an absolute http or https URL."""
    parts = urlsplit(value.strip())
    return parts.scheme in ("http", "https") and bool(parts.netloc)


def _load_stored(tenant_id: str, body: PactPostmanRequest) -> PactRecord:
    """Read the stored pact the request selects.

    Args:
        tenant_id: The caller's tenant.
        body: The checked request.

    Returns:
        The pact.

    Raises:
        PactPublicationError: ``pact-not-found``.
        PacticipantValidationError: ``pacticipant-not-found``.
    """
    provider, consumer = str(body.provider), str(body.consumer)
    if body.consumer_version is not None:
        return get_pact(db, tenant_id, provider, consumer, body.consumer_version)
    if body.pact_version_sha is not None:
        return get_pact_by_sha(db, tenant_id, provider, consumer, body.pact_version_sha)
    return get_latest_pact(db, tenant_id, provider, consumer, tag=body.tag, branch=body.branch)


def _inline(body: PactPostmanRequest) -> Dict[str, Any]:
    """Check an inline pact's size and shape.

    Args:
        body: The request, with ``pact`` set.

    Returns:
        The document.

    Raises:
        PactPublicationError: ``pact-too-large`` or ``pact-invalid``.
    """
    document = body.pact or {}
    size = len(json.dumps(document, ensure_ascii=False).encode("utf-8"))
    if size > settings.pact_max_bytes:
        raise PactPublicationError(
            CODE_PACT_TOO_LARGE, f"the Pact document is {size} bytes; the limit is {settings.pact_max_bytes}"
        )
    validate_pact_document(document)
    return document


@router.post(
    "/{tenant_slug}/pact-postman-collections",
    summary="Export a pact as a Postman collection",
    description=(
        "Writes a **Postman Collection v2.1** from a pact: one request per HTTP interaction against a "
        "`{{baseUrl}}` variable, a saved example of the expected response, and (`tests`, default on) a "
        "test script that checks the status, the expected headers and the body by Pact's default rules "
        "(extra object keys allowed, arrays of the same length, other values equal). Provider states are "
        "named in each request's description.\n\n"
        "Send `provider` + `consumer` and at most one of `consumerVersion`, `tag`, `branch`, "
        "`pactVersionSha` for a stored pact (none: the latest), or `pact` for an inline document. "
        "Nothing is stored.\n\n"
        "`notices` lists what the collection does not carry, each with a code, outcome "
        "(`left-out`, `not-asserted`, `not-applied`, `info`), JSON Pointer and reason: message and gRPC "
        "interactions, non-text bodies, values governed by matching rules, generators, and the provider "
        "states to set up. A pact with no HTTP interaction to export is `422 "
        "pact-postman-no-http-interactions`. Requires `pacts:view`."
    ),
    responses={
        404: {"description": "`pacticipant-not-found` or `pact-not-found`: no such stored pact in this workspace."},
        413: {"description": "`pact-too-large`: the inline pact is over the workspace's pact size limit."},
        422: {
            "description": (
                "`pact-postman-export-invalid` (no pact named, two selections, an inline pact with a "
                "selection, a bad `baseUrl`), `pact-invalid` (the inline document is not a pact) or "
                "`pact-postman-no-http-interactions` (with `notices`)."
            )
        },
    },
)
def export_pact_postman_collection(
    tenant_slug: str,
    body: PactPostmanRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, Any]:
    """Export a stored or inline pact as a Postman Collection v2.1.

    Args:
        tenant_slug: The tenant in the URL (the tenant read is the credential's).
        body: What to export, and the options.
        auth_data: The authenticated principal.

    Returns:
        ``{"collection", "pact", "counts", "notices"}``.

    Raises:
        HTTPException: 403 without ``pacts:view``; 404 / 413 / 422 as documented on the route.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    _check_request(body)
    if body.all_consumers:
        return _export_all_consumers(_tenant_id(auth_data), body)
    source: Dict[str, Any]
    try:
        if body.pact is not None:
            document = _inline(body)
            consumer = (body.consumer or "").strip() or pact_consumer_name(document) or "consumer"
            provider = (body.provider or "").strip() or pact_provider_name(document) or "provider"
            source = {"consumer": consumer, "provider": provider, "pactVersionSha": pact_content_sha(document)}
            described = f"Exported by Apiome from an inline pact between {consumer} and {provider}."
        else:
            record = _load_stored(_tenant_id(auth_data), body)
            document = record.content
            consumer, provider = record.consumer_name, record.provider_name
            source = {
                "consumer": consumer,
                "provider": provider,
                "consumerVersion": record.consumer_version,
                "pactVersionSha": record.sha,
            }
            described = (
                f"Exported by Apiome from the pact {consumer} version {record.consumer_version} published "
                f"for {provider} (pact version {record.sha})."
            )
    except (PactPublicationError, PacticipantValidationError) as exc:
        pointer = getattr(exc, "pointer", None)
        extra = {"pointer": pointer} if pointer is not None else {}
        raise _refuse(getattr(exc, "code", CODE_EXPORT_INVALID), str(exc), **extra) from exc

    export = pact_to_postman(
        document,
        consumer=consumer,
        provider=provider,
        base_url=body.base_url.strip() if body.base_url else None,
        tests=body.tests,
        description=described,
        state_setup=body.state_setup,
        state_change_url=body.state_change_url,
    )
    notices = [notice.as_json() for notice in export.notices]
    if export.exported_count == 0:
        raise _refuse(
            CODE_NO_HTTP_INTERACTIONS,
            "the pact has no HTTP interaction a Postman collection can carry",
            notices=notices,
        )
    source["specificationVersion"] = pact_specification_version(document)
    return {
        "collection": export.collection,
        "pact": source,
        "counts": {
            "interactions": export.interaction_count,
            "exported": export.exported_count,
            "leftOut": export.left_out_count,
        },
        "notices": notices,
    }


def _export_all_consumers(tenant_id: str, body: PactPostmanRequest) -> Dict[str, Any]:
    """One collection with a folder per consumer of the provider (``allConsumers``).

    Each consumer's pact is the latest it published for the provider (from consumer versions with
    ``tag`` or on ``branch``, when one is given). A consumer without such a pact is not dropped
    silently: it is a ``left-out`` notice. Every notice carries the ``consumer`` it is about.

    Args:
        tenant_id: The caller's tenant.
        body: The checked request.

    Returns:
        ``{"collection", "pact": {"provider", "consumers": [...]}, "counts", "notices"}``.

    Raises:
        HTTPException: 404 for an unknown provider or one no consumer published a pact for; 422
            ``pact-postman-no-http-interactions`` when no consumer's pact has an HTTP interaction.
    """
    provider_ref = str(body.provider).strip()
    try:
        provider, candidates = list_latest_pact_candidates(db, tenant_id, provider_ref)
    except PacticipantValidationError as exc:
        raise _refuse(getattr(exc, "code", CODE_NOT_FOUND), str(exc)) from exc
    if not candidates:
        raise _refuse(CODE_PACT_NOT_FOUND, f"no consumer has published a pact for provider '{provider.slug}'")

    qualifier = f" with tag '{body.tag}'" if body.tag else f" from branch '{body.branch}'" if body.branch else ""
    folders: List[Dict[str, Any]] = []
    consumers: List[Dict[str, Any]] = []
    notices: List[Dict[str, Any]] = []
    counts = {"interactions": 0, "exported": 0, "leftOut": 0}
    variables: List[Dict[str, Any]] = []
    for candidate in sorted(candidates, key=lambda c: c.consumer_name.casefold()):
        try:
            record = get_latest_pact(
                db, tenant_id, str(provider.id), str(candidate.consumer_id), tag=body.tag, branch=body.branch
            )
        except (PactPublicationError, PacticipantValidationError) as exc:
            notices.append(
                {
                    "code": CODE_CONSUMER_NO_PACT,
                    "outcome": OUTCOME_LEFT_OUT,
                    "pointer": "",
                    "message": f"{candidate.consumer_name} has no pact{qualifier} for {provider.name}: {exc}",
                    "consumer": candidate.consumer_name,
                }
            )
            continue
        export = pact_to_postman(
            record.content,
            consumer=record.consumer_name,
            provider=record.provider_name,
            base_url=body.base_url.strip() if body.base_url else None,
            tests=body.tests,
            state_setup=body.state_setup,
            state_change_url=body.state_change_url,
        )
        notices.extend({**notice.as_json(), "consumer": record.consumer_name} for notice in export.notices)
        counts["interactions"] += export.interaction_count
        counts["exported"] += export.exported_count
        counts["leftOut"] += export.left_out_count
        consumers.append(
            {
                "consumer": record.consumer_name,
                "consumerVersion": record.consumer_version,
                "pactVersionSha": record.sha,
                "specificationVersion": pact_specification_version(record.content),
            }
        )
        if export.collection["item"]:
            folders.append(
                {
                    "name": record.consumer_name,
                    "description": f"The pact {record.consumer_name} version {record.consumer_version} published "
                    f"(pact version {record.sha}).",
                    "item": export.collection["item"],
                }
            )
        variables = export.collection["variable"]

    if counts["exported"] == 0:
        raise _refuse(
            CODE_NO_HTTP_INTERACTIONS,
            f"no consumer's pact{qualifier} for {provider.name} has an HTTP interaction a Postman collection can carry",
            notices=notices,
        )
    collection = {
        "info": {
            "name": f"Pact: every consumer → {provider.name}",
            "schema": POSTMAN_SCHEMA_URL,
            "description": f"Exported by Apiome from the latest pact{qualifier} of each consumer of {provider.name}.",
        },
        "item": folders,
        "variable": variables,
    }
    return {
        "collection": collection,
        "pact": {"provider": provider.name, "consumers": consumers},
        "counts": counts,
        "notices": notices,
    }
