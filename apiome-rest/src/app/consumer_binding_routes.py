"""``…/consumers/{consumer_ref}/bindings`` and ``…/runtime`` — RDG-1.8 (#5765).

How a consumer is recognised in usage traffic (its **bindings**), and what that traffic shows next
to what the consumer declared (its **runtime** edges). Mounted beside the CTG-4.1 routes, under the
same ``consumer_contracts`` permissions:

* ``GET …/bindings`` — ``consumer_contracts:view``;
* ``POST …/bindings`` — ``consumer_contracts:create``. The value is accepted once, hashed before the
  transaction opens, and never stored or returned;
* ``DELETE …/bindings/{binding_id}`` — ``consumer_contracts:delete`` (Owner and Admin), because
  unbinding removes a signal other people's changes are judged by. History stays attributed;
* ``GET …/runtime`` — ``consumer_contracts:view``. ``anonymous`` is accepted as the consumer: it
  reports the traffic no binding attributes.

"Add to contract" on a ``used_undeclared`` operation is not a new writer: the client submits the
consumer's current selection plus that operation to the existing ``PUT …/contract``.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from .auth import validate_authentication
from .consumer_binding import (
    ANONYMOUS_CONSUMER_SLUG,
    BindingError,
    BindingInput,
    BindingRecord,
)
from .consumer_binding_store import create_binding, delete_binding, list_bindings, usage_by_consumer
from .consumer_contract import ConsumerContractSurface, ConsumerSummary, ConsumerValidationError
from .consumer_contract_routes import _http_error, _tenant_id
from .consumer_contract_store import actor_from_auth, current_contract, get_consumer, resolve_project
from .consumer_runtime_edges import ConsumerRuntime, RuntimeConsumer, build_runtime
from .database import db
from .permissions import Action, Resource, enforce_permission
from .redacted_validation_route import RedactedValidationRoute

__all__ = ["DEFAULT_RUNTIME_DAYS", "MAX_RUNTIME_DAYS", "attach_runtime_summaries", "router", "runtime_window"]

_logger = logging.getLogger(__name__)

#: A malformed create would otherwise echo the bound value back in its 422 (pydantic errors carry the
#: input), so validation errors on these routes keep only ``type``, ``loc`` and ``msg``.
router = APIRouter(prefix="/v1/tenants", tags=["consumer-contracts"], route_class=RedactedValidationRoute)

#: The runtime window when none is asked for, and the longest one (a Paid tier's rollup retention).
DEFAULT_RUNTIME_DAYS = 30
MAX_RUNTIME_DAYS = 395


class BindingListResponse(BaseModel):
    """A consumer's bindings."""

    model_config = ConfigDict(extra="forbid")

    bindings: List[BindingRecord] = Field(default_factory=list, description="Newest first.")
    count: int = Field(description="How many bindings were returned.")


def _binding_error(exc: BindingError) -> HTTPException:
    """Translate a binding refusal into its HTTP error (``{code, message}``)."""
    return HTTPException(status_code=exc.status, detail=exc.detail())


def runtime_window(days: int, *, today: Optional[date] = None) -> Tuple[date, date]:
    """``(since, until)`` for a window of ``days`` UTC days ending today.

    Args:
        days: Window length, at least 1.
        today: The current UTC day (for tests).

    Returns:
        The first and last day, both inclusive.
    """
    until = today or datetime.now(timezone.utc).date()
    return until - timedelta(days=max(days, 1) - 1), until


def attach_runtime_summaries(
    tenant_id: str, project_id: str, summaries: Sequence[ConsumerSummary], *, days: int = DEFAULT_RUNTIME_DAYS
) -> List[ConsumerSummary]:
    """Add each row's declared-versus-observed counts (one ``usage_daily`` read for the page).

    A usage index that cannot be read leaves ``runtime`` null rather than failing the list.

    Args:
        tenant_id: The tenant.
        project_id: The project.
        summaries: The consumer rows.
        days: The window.

    Returns:
        The rows with ``runtime`` set.
    """
    if not summaries:
        return list(summaries)
    since, until = runtime_window(days)
    try:
        rows = usage_by_consumer(
            db, tenant_id, project_id, since=since, until=until, consumer_ids=[s.consumer.id for s in summaries]
        )
    except Exception:  # noqa: BLE001 - the list must stay readable without the usage index
        _logger.warning("consumer list: usage index unreadable; runtime omitted", exc_info=True)
        return list(summaries)
    out: List[ConsumerSummary] = []
    for summary in summaries:
        report = build_runtime(
            RuntimeConsumer(
                consumer_id=summary.consumer.id,
                slug=summary.consumer.slug,
                name=summary.consumer.name,
                contract=summary.contract.surface if summary.contract else None,
            ),
            rows,
            since=since,
            until=until,
        )
        out.append(summary.model_copy(update={"runtime": report.summary}))
    return out


@router.get(
    "/{tenant_slug}/projects/{project_ref}/consumers/{consumer_ref}/bindings",
    response_model=BindingListResponse,
    summary="List a consumer's bindings",
    description=(
        "How this consumer is recognised in usage traffic: a header, an API key, a JWT claim, or a "
        "user-agent glob. A bound value is never returned — not even as a hash.\n\n"
        "Deleted bindings are listed with `include_deleted=true`; they no longer match traffic but "
        "keep the history they attributed.\n\n"
        "Requires `consumer_contracts:view`."
    ),
)
async def list_consumer_bindings(
    tenant_slug: str,
    project_ref: str,
    consumer_ref: str,
    include_deleted: bool = Query(default=False, description="Also list deleted bindings."),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> BindingListResponse:
    """List a consumer's bindings.

    Args:
        tenant_slug: The tenant in the URL (the authenticated tenant scopes it).
        project_ref: Project slug or id.
        consumer_ref: Consumer slug or id.
        include_deleted: Also return deleted bindings.
        auth_data: The authenticated principal.

    Returns:
        The bindings.

    Raises:
        HTTPException: 404 for an unknown project or consumer, 403 without
            ``consumer_contracts:view``.
    """
    enforce_permission(db, auth_data, Resource.CONSUMER_CONTRACTS, Action.VIEW)
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    try:
        project = resolve_project(tenant_id, project_ref)
        consumer = get_consumer(tenant_id, str(project["id"]), consumer_ref)
    except ConsumerValidationError as exc:
        raise _http_error(exc) from exc
    bindings = list_bindings(db, tenant_id, consumer.id, include_deleted=include_deleted)
    return BindingListResponse(bindings=bindings, count=len(bindings))


@router.post(
    "/{tenant_slug}/projects/{project_ref}/consumers/{consumer_ref}/bindings",
    response_model=BindingRecord,
    status_code=201,
    summary="Bind a header, API key, JWT claim or user agent to a consumer",
    description=(
        "Attribute usage traffic to this consumer. `header`, `api_key` and `jwt_claim` take the "
        "`value` to recognise: it is accepted **once**, hashed (HMAC-SHA256 under a key derived "
        "for this workspace) before anything is stored, and never returned. `user_agent` takes no "
        "value; its `name` is a glob such as `billing-service/*`.\n\n"
        "Matching starts with the next ingested batch. One kind, name and value can identify only "
        "one consumer per workspace (`409 consumer-binding-exists`).\n\n"
        "Requires `consumer_contracts:create`."
    ),
    responses={
        409: {"description": "`consumer-binding-exists` or `consumer-binding-limit`."},
        503: {"description": "`consumer-binding-key-unavailable`: no envelope master key is configured."},
    },
)
async def create_consumer_binding(
    tenant_slug: str,
    project_ref: str,
    consumer_ref: str,
    body: BindingInput,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> BindingRecord:
    """Create a binding.

    Args:
        tenant_slug: The tenant in the URL.
        project_ref: Project slug or id.
        consumer_ref: Consumer slug or id.
        body: The binding (its value is hashed and dropped).
        auth_data: The authenticated principal.

    Returns:
        The stored binding.

    Raises:
        HTTPException: 400 for a malformed name, 404 for an unknown project or consumer, 409 when
            taken or over the limit, 503 when no key is configured, 403 without
            ``consumer_contracts:create``.
    """
    user_id = enforce_permission(
        db, auth_data, Resource.CONSUMER_CONTRACTS, Action.CREATE, target=consumer_ref
    )
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    try:
        project = resolve_project(tenant_id, project_ref)
        consumer = get_consumer(tenant_id, str(project["id"]), consumer_ref)
    except ConsumerValidationError as exc:
        raise _http_error(exc) from exc
    try:
        return create_binding(
            db,
            tenant_id=tenant_id,
            project_id=str(project["id"]),
            consumer_id=consumer.id,
            body=body,
            user_id=actor_from_auth(auth_data, user_id).user_id,
        )
    except BindingError as exc:
        raise _binding_error(exc) from exc


@router.delete(
    "/{tenant_slug}/projects/{project_ref}/consumers/{consumer_ref}/bindings/{binding_id}",
    status_code=204,
    summary="Delete a consumer binding",
    description=(
        "Stop attributing traffic through this binding, from the next ingested batch on. Traffic "
        "it already attributed **stays attributed** to the consumer.\n\n"
        "Requires `consumer_contracts:delete`."
    ),
)
async def delete_consumer_binding(
    tenant_slug: str,
    project_ref: str,
    consumer_ref: str,
    binding_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Response:
    """Delete a binding.

    Args:
        tenant_slug: The tenant in the URL.
        project_ref: Project slug or id.
        consumer_ref: Consumer slug or id.
        binding_id: The binding.
        auth_data: The authenticated principal.

    Returns:
        An empty 204.

    Raises:
        HTTPException: 404 for an unknown project, consumer or binding, 403 without
            ``consumer_contracts:delete``.
    """
    user_id = enforce_permission(
        db, auth_data, Resource.CONSUMER_CONTRACTS, Action.DELETE, target=consumer_ref
    )
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    try:
        project = resolve_project(tenant_id, project_ref)
        consumer = get_consumer(tenant_id, str(project["id"]), consumer_ref)
    except ConsumerValidationError as exc:
        raise _http_error(exc) from exc
    try:
        delete_binding(
            db, tenant_id=tenant_id, consumer_id=consumer.id, binding_id=binding_id,
            user_id=actor_from_auth(auth_data, user_id).user_id,
        )
    except BindingError as exc:
        raise _binding_error(exc) from exc
    return Response(status_code=204)


@router.get(
    "/{tenant_slug}/projects/{project_ref}/consumers/{consumer_ref}/runtime",
    response_model=ConsumerRuntime,
    summary="Compare a consumer's contract with its observed traffic",
    description=(
        "Per operation, what the consumer **declares** (its current contract) next to what its "
        "bindings show it **calls** (the usage index, by UTC day):\n\n"
        "* `declared_and_used` — declared and called in the window;\n"
        "* `declared_unused` — declared, never called in the window;\n"
        "* `used_undeclared` — called, not declared. To add one to the contract, submit the current "
        "selection plus that operation to `PUT …/consumers/{consumer_ref}/contract`.\n\n"
        "A consumer with no contract (`contract_state: undeclared`) reports everything it calls "
        "as `used_undeclared`. `anonymous` reports the traffic no binding attributes.\n\n"
        "Requires `consumer_contracts:view`."
    ),
)
async def read_consumer_runtime(
    tenant_slug: str,
    project_ref: str,
    consumer_ref: str,
    days: int = Query(
        default=DEFAULT_RUNTIME_DAYS, ge=1, le=MAX_RUNTIME_DAYS, description="Window in UTC days, ending today."
    ),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ConsumerRuntime:
    """Read a consumer's runtime edges.

    Args:
        tenant_slug: The tenant in the URL.
        project_ref: Project slug or id.
        consumer_ref: Consumer slug or id, or ``anonymous``.
        days: The window length.
        auth_data: The authenticated principal.

    Returns:
        The declared-versus-observed report.

    Raises:
        HTTPException: 404 for an unknown project or consumer, 403 without
            ``consumer_contracts:view``.
    """
    enforce_permission(db, auth_data, Resource.CONSUMER_CONTRACTS, Action.VIEW)
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    since, until = runtime_window(days)
    try:
        project = resolve_project(tenant_id, project_ref)
        project_id = str(project["id"])
        if consumer_ref == ANONYMOUS_CONSUMER_SLUG:
            subject = RuntimeConsumer(consumer_id=None, slug=ANONYMOUS_CONSUMER_SLUG, name="Anonymous", contract=None)
            rows = usage_by_consumer(db, tenant_id, project_id, since=since, until=until)
        else:
            consumer = get_consumer(tenant_id, project_id, consumer_ref)
            surface: Optional[ConsumerContractSurface]
            try:
                surface = current_contract(tenant_id, consumer.id).surface
            except ConsumerValidationError:
                surface = None
            subject = RuntimeConsumer(
                consumer_id=consumer.id, slug=consumer.slug, name=consumer.name, contract=surface
            )
            rows = usage_by_consumer(db, tenant_id, project_id, since=since, until=until, consumer_ids=[consumer.id])
    except ConsumerValidationError as exc:
        raise _http_error(exc) from exc
    return build_runtime(subject, rows, since=since, until=until)
