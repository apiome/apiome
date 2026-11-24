"""``…/pact-broker`` labels and deletes, in the Pact Broker's shape — PFX-1.11 (#6924).

The Pact Broker API resources for grouping pacticipants and removing them, so a client written
against a Pact Broker works unchanged:

* ``GET …/labels`` — every distinct label (``_embedded.labels``);
* ``GET …/pacticipants/label/{label}`` — the pacticipants carrying a label;
* ``GET``/``PUT``/``DELETE …/pacticipants/{p}/labels/{label}`` — one label of a pacticipant
  (``PUT`` answers ``201`` with a ``Location`` when the label is new);
* ``DELETE …/pacticipants/{p}`` and ``DELETE …/pacticipants/{p}/versions/{v}`` — ``204``.

Two differences from the Pact Broker, both on the side of not losing data, and both on the
compatibility page:

* a delete is **soft** — hidden at once, restorable through Apiome's own API
  (``POST /v1/tenants/{t}/pacticipants/{p}/restore``) until it is purged — and refused with ``409``
  while a version is deployed or released, unless ``?force=true``;
* ``PUT`` of a label on an unknown pacticipant is ``404``; the Pact Broker would create the
  pacticipant.

``GET`` needs ``pacts:view``; a label change ``pacts:edit``; a delete ``pacts:delete``.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response

from .consumer_contract_store import actor_from_auth
from .database import db
from .pact_broker_auth import validate_broker_authentication
from .pact_broker_routes import (
    HalJSONResponse,
    _base_url,
    _http_error,
    _pacticipant_document,
    _pacticipant_url,
    _tenant_id,
)
from .pact_cleanup_store import (
    add_label,
    delete_pacticipant,
    delete_version,
    get_label,
    list_labels,
    remove_label,
)
from .pacticipant import PacticipantLabelRecord, PacticipantValidationError
from .pacticipant_store import get_pacticipant, list_pacticipants
from .permissions import Action, Resource, enforce_permission

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["pact-broker"])

_PREFIX = "/{tenant_slug}/pact-broker"

_REASON_QUERY = Query(default=None, max_length=500, description="Why; stored with the delete and audited.")
_FORCE_QUERY = Query(default=False, description="Delete even when a version is currently deployed or released.")


def _label_url(base: str, slug: str, name: str) -> str:
    """The URL of one label of a pacticipant on the broker surface."""
    return f"{_pacticipant_url(base, slug)}/labels/{quote(name, safe='')}"


def _label_document(base: str, label: PacticipantLabelRecord) -> Dict[str, Any]:
    """Render a label the way a Pact Broker returns one (``LabelDecorator``).

    Args:
        base: The broker base URL.
        label: The label.

    Returns:
        Its name and creation time, with links to itself and its pacticipant.
    """
    return {
        "name": label.name,
        "createdAt": label.created_at,
        "_links": {
            "self": {
                "title": "Label",
                "name": label.name,
                "href": _label_url(base, label.pacticipant_slug, label.name),
            },
            "pacticipant": {
                "title": "Pacticipant",
                "name": label.pacticipant_name,
                "href": _pacticipant_url(base, label.pacticipant_slug),
            },
        },
    }


@router.get(
    _PREFIX + "/labels",
    response_class=HalJSONResponse,
    summary="List every label (Pact Broker shape)",
    description=(
        "Every distinct label on the workspace's pacticipants, by name, under `_embedded.labels`. "
        "Requires `pacts:view`."
    ),
)
def read_broker_labels(
    tenant_slug: str,
    request: Request,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> HalJSONResponse:
    """List every label in the Pact Broker's shape.

    Args:
        tenant_slug: The tenant in the URL.
        request: The request.
        auth_data: The authenticated principal.

    Returns:
        ``{"_embedded": {"labels": [{"name": …}]}, "_links": {"self": …}}``.

    Raises:
        HTTPException: 403 without ``pacts:view``.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    base = _base_url(request, tenant_slug)
    names = list_labels(db, _tenant_id(auth_data))
    return HalJSONResponse(
        {
            "_embedded": {"labels": [{"name": row["name"]} for row in names]},
            "_links": {"self": {"title": "Labels", "href": f"{base}/labels"}},
        }
    )


@router.get(
    _PREFIX + "/pacticipants/label/{label:path}",
    response_class=HalJSONResponse,
    summary="List the pacticipants with a label (Pact Broker shape)",
    description=(
        "The pacticipants carrying `{label}`, under `_embedded.pacticipants` and `pb:pacticipants`; "
        "an empty list when none does. Requires `pacts:view`."
    ),
)
def read_broker_pacticipants_with_label(
    tenant_slug: str,
    label: str,
    request: Request,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> HalJSONResponse:
    """List the pacticipants carrying a label, in the Pact Broker's shape.

    Args:
        tenant_slug: The tenant in the URL.
        label: The label.
        request: The request.
        auth_data: The authenticated principal.

    Returns:
        The pacticipants collection document.

    Raises:
        HTTPException: 403 without ``pacts:view``.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    base = _base_url(request, tenant_slug)
    records = list_pacticipants(db, _tenant_id(auth_data), label=label)
    collection = f"{base}/pacticipants"
    return HalJSONResponse(
        {
            "_embedded": {"pacticipants": [_pacticipant_document(base, record) for record in records]},
            "_links": {
                "self": {"href": f"{collection}/label/{quote(label, safe='')}"},
                "pb:pacticipants-with-label": {
                    "title": "Find pacticipants by label",
                    "href": collection + "/label/{label}",
                    "templated": True,
                },
                "pb:pacticipants": [
                    {"href": _pacticipant_url(base, record.slug), "title": "Pacticipant", "name": record.name}
                    for record in records
                ],
            },
        }
    )


@router.get(
    _PREFIX + "/pacticipants/{pacticipant}/labels/{label:path}",
    response_class=HalJSONResponse,
    summary="Read a label (Pact Broker shape)",
    description="One label of a pacticipant; 404 when it does not carry it. Requires `pacts:view`.",
)
def read_broker_label(
    tenant_slug: str,
    pacticipant: str,
    label: str,
    request: Request,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> HalJSONResponse:
    """Read one label in the Pact Broker's shape.

    Args:
        tenant_slug: The tenant in the URL.
        pacticipant: The pacticipant's handle, id or name.
        label: The label.
        request: The request.
        auth_data: The authenticated principal.

    Returns:
        The label document.

    Raises:
        HTTPException: 404 for an unknown pacticipant or label, 403 without ``pacts:view``.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    try:
        record = get_pacticipant(db, _tenant_id(auth_data), pacticipant)
        found = get_label(db, record, label)
    except PacticipantValidationError as exc:
        raise _http_error(exc) from exc
    return HalJSONResponse(_label_document(_base_url(request, tenant_slug), found))


@router.put(
    _PREFIX + "/pacticipants/{pacticipant}/labels/{label:path}",
    response_class=HalJSONResponse,
    summary="Label a pacticipant (Pact Broker shape)",
    description=(
        "Put a label on a pacticipant. `201` with a `Location` header when the label is new, `200` "
        "when the pacticipant already had it. Unlike the Pact Broker, an unknown pacticipant is "
        "`404`, not created. Requires `pacts:edit`."
    ),
)
def put_broker_label(
    tenant_slug: str,
    pacticipant: str,
    label: str,
    request: Request,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> HalJSONResponse:
    """Label a pacticipant through the Pact Broker API.

    Args:
        tenant_slug: The tenant in the URL.
        pacticipant: The pacticipant's handle, id or name.
        label: The label.
        request: The request.
        auth_data: The authenticated principal.

    Returns:
        The label document.

    Raises:
        HTTPException: 400 for a malformed label, 404 for an unknown pacticipant, 403 without
            ``pacts:edit``.
    """
    user_id = enforce_permission(db, auth_data, Resource.PACTS, Action.EDIT, target=pacticipant)
    try:
        tenant_id = _tenant_id(auth_data)
        record = get_pacticipant(db, tenant_id, pacticipant)
        found, created = add_label(db, tenant_id, record, label, actor=actor_from_auth(auth_data, user_id))
    except PacticipantValidationError as exc:
        raise _http_error(exc) from exc
    base = _base_url(request, tenant_slug)
    headers = {"Location": _label_url(base, found.pacticipant_slug, found.name)} if created else None
    return HalJSONResponse(_label_document(base, found), status_code=201 if created else 200, headers=headers)


@router.delete(
    _PREFIX + "/pacticipants/{pacticipant}/labels/{label:path}",
    status_code=204,
    summary="Remove a label (Pact Broker shape)",
    description="Take a label off a pacticipant; 404 when it does not carry it. Requires `pacts:edit`.",
)
def delete_broker_label(
    tenant_slug: str,
    pacticipant: str,
    label: str,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> Response:
    """Remove a label through the Pact Broker API.

    Args:
        tenant_slug: The tenant in the URL.
        pacticipant: The pacticipant's handle, id or name.
        label: The label.
        auth_data: The authenticated principal.

    Returns:
        An empty 204.

    Raises:
        HTTPException: 404 for an unknown pacticipant or label, 403 without ``pacts:edit``.
    """
    user_id = enforce_permission(db, auth_data, Resource.PACTS, Action.EDIT, target=pacticipant)
    _ = tenant_slug
    try:
        tenant_id = _tenant_id(auth_data)
        record = get_pacticipant(db, tenant_id, pacticipant)
        remove_label(db, tenant_id, record, label, actor=actor_from_auth(auth_data, user_id))
    except PacticipantValidationError as exc:
        raise _http_error(exc) from exc
    return Response(status_code=204)


@router.delete(
    _PREFIX + "/pacticipants/{pacticipant}",
    status_code=204,
    summary="Delete a pacticipant (Pact Broker shape)",
    description=(
        "Delete a pacticipant with its versions, pacts, verification results and deployments. Soft: "
        "it can be restored through `POST /v1/tenants/{tenant_slug}/pacticipants/{p}/restore` until "
        "it is purged (`APIOME_PACT_DELETION_GRACE_DAYS`, default 30). `409 "
        "pacticipant-version-in-use` while a version is deployed or released, unless `force=true`. "
        "Requires `pacts:delete`."
    ),
)
def delete_broker_pacticipant(
    tenant_slug: str,
    pacticipant: str,
    reason: Optional[str] = _REASON_QUERY,
    force: bool = _FORCE_QUERY,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> Response:
    """Soft-delete a pacticipant through the Pact Broker API.

    Args:
        tenant_slug: The tenant in the URL.
        pacticipant: The pacticipant's handle, id or name.
        reason: Why.
        force: Delete even when a version is deployed or released.
        auth_data: The authenticated principal.

    Returns:
        An empty 204.

    Raises:
        HTTPException: 404 for an unknown pacticipant, 409 when a version is in use, 403 without
            ``pacts:delete``.
    """
    user_id = enforce_permission(db, auth_data, Resource.PACTS, Action.DELETE, target=pacticipant)
    _ = tenant_slug
    try:
        tenant_id = _tenant_id(auth_data)
        record = get_pacticipant(db, tenant_id, pacticipant)
        delete_pacticipant(
            db, tenant_id, record, actor=actor_from_auth(auth_data, user_id), reason=reason, force=force
        )
    except PacticipantValidationError as exc:
        raise _http_error(exc) from exc
    return Response(status_code=204)


@router.delete(
    _PREFIX + "/pacticipants/{pacticipant}/versions/{number}",
    status_code=204,
    summary="Delete a pacticipant version (Pact Broker shape)",
    description=(
        "Delete one version with its pacts, the verification results it published and its "
        "deployments. Soft: restorable through `POST "
        "/v1/tenants/{tenant_slug}/pacticipants/{p}/versions/{v}/restore` until it is purged. `409 "
        "pacticipant-version-in-use` while it is deployed or released, unless `force=true`. "
        "Requires `pacts:delete`."
    ),
)
def delete_broker_pacticipant_version(
    tenant_slug: str,
    pacticipant: str,
    number: str,
    reason: Optional[str] = _REASON_QUERY,
    force: bool = _FORCE_QUERY,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> Response:
    """Soft-delete a version through the Pact Broker API.

    Args:
        tenant_slug: The tenant in the URL.
        pacticipant: The pacticipant's handle, id or name.
        number: The version number.
        reason: Why.
        force: Delete even when it is deployed or released.
        auth_data: The authenticated principal.

    Returns:
        An empty 204.

    Raises:
        HTTPException: 404 for an unknown pacticipant or version, 409 when it is in use, 403
            without ``pacts:delete``.
    """
    user_id = enforce_permission(db, auth_data, Resource.PACTS, Action.DELETE, target=pacticipant)
    _ = tenant_slug
    try:
        tenant_id = _tenant_id(auth_data)
        record = get_pacticipant(db, tenant_id, pacticipant)
        delete_version(
            db, tenant_id, record, number, actor=actor_from_auth(auth_data, user_id), reason=reason, force=force
        )
    except PacticipantValidationError as exc:
        raise _http_error(exc) from exc
    return Response(status_code=204)
