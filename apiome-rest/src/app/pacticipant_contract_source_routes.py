"""``/v1/tenants/{tenant_slug}/pacticipants/{p}/contract-sources`` — PFX-8.7 (#7304).

Where a provider's contract is published from automatically (:mod:`app.pacticipant_contract_sources`):

* ``GET`` — the standing sources, with a warning for each that will not fire right now. ``pacts:view``.
* ``PUT`` — replace them. ``pacts:edit``; audited as ``pacts.contract_source.update``. A repository
  source also needs ``imports:view``, since it names a registered repository.

Every automatic publish they cause is audited as ``pacts.contract.auto_publish``
(:mod:`app.provider_contract_auto_publish`).
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends

from .auth import validate_authentication
from .database import db
from .pact_audit import audited_write
from .pacticipant import PacticipantValidationError
from .pacticipant_contract_sources import (
    CODE_NO_PROJECT,
    CODE_REPOSITORY_NOT_FOUND,
    CODE_REPOSITORY_UNSUPPORTED,
    ContractSourcesInput,
    ContractSourcesRecord,
    get_contract_sources,
    put_contract_sources,
)
from .pacticipant_routes import STATUS_BY_CODE, _http_error, _tenant_id
from .pacticipant_store import get_pacticipant
from .permissions import Action, Resource, enforce_permission

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["pacticipants"])

STATUS_BY_CODE.update(
    {
        CODE_REPOSITORY_NOT_FOUND: 404,
        CODE_NO_PROJECT: 409,
        CODE_REPOSITORY_UNSUPPORTED: 422,
    }
)

_PATH = "/{tenant_slug}/pacticipants/{pacticipant_ref}/contract-sources"

_DOCUMENT = (
    "- `onProjectPublish` — each time a version of the project the pacticipant is bound to is published, "
    "it is rendered (OpenAPI 3.1, as `apiomeVersion` renders it) and published as the contract of provider "
    "version `<version label>` on the pacticipant's main branch. Drafts are never published.\n"
    "- `repository` — on every push to `branch` of a registered repository (`repositoryId`), the file at "
    "`path` is published with the pushed commit as the provider version. The repository needs a push webhook.\n\n"
    "Each automatic publish is compared with the pacts that need it, as a publish is, and audited as "
    "`pacts.contract.auto_publish` with its outcome and reason. A provider version's contract is write-once, "
    "so a repeated trigger records nothing new. Turning a source off stops new publishes only."
)


@router.get(
    _PATH,
    response_model=ContractSourcesRecord,
    response_model_by_alias=True,
    summary="Read a provider's standing contract sources",
    description="Where this provider's contract is published from automatically.\n\n"
    + _DOCUMENT
    + "\n\n`warnings` names each source that will not fire right now. Requires `pacts:view`.",
)
def read_contract_sources(
    tenant_slug: str,
    pacticipant_ref: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ContractSourcesRecord:
    """Read a provider's standing contract sources.

    Args:
        tenant_slug: The tenant in the URL.
        pacticipant_ref: Handle, id or display name.
        auth_data: The authenticated principal.

    Returns:
        The sources.

    Raises:
        HTTPException: 404 for an unknown pacticipant, 403 without ``pacts:view``.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    try:
        return get_contract_sources(db, tenant_id, get_pacticipant(db, tenant_id, pacticipant_ref))
    except PacticipantValidationError as exc:
        raise _http_error(exc) from exc


@router.put(
    _PATH,
    response_model=ContractSourcesRecord,
    response_model_by_alias=True,
    summary="Set a provider's standing contract sources",
    description="Replace where this provider's contract is published from automatically; both off removes "
    "the setting.\n\n"
    + _DOCUMENT
    + "\n\nRefused with a reason, never ignored: `409 contract-source-no-project` for `onProjectPublish` on a "
    "pacticipant bound to no project, `404 contract-source-repository-not-found` for a repository of another "
    "workspace, `422 contract-source-repository-unsupported` for a repository whose files cannot be read on "
    "a push (only GitHub's can), `400 contract-source-invalid-path` for a path that is not a "
    "repository-relative `.yaml` / `.yml` / `.json` file.\n\n"
    "Requires `pacts:edit`, and `imports:view` with `repository`.",
)
@audited_write("pacts.contract_source.update", "pacticipant/{pacticipant_ref}/contract-sources")
def put_contract_sources_route(
    tenant_slug: str,
    pacticipant_ref: str,
    body: ContractSourcesInput,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ContractSourcesRecord:
    """Replace a provider's standing contract sources.

    Args:
        tenant_slug: The tenant in the URL.
        pacticipant_ref: Handle, id or display name.
        body: The new sources.
        auth_data: The authenticated principal.

    Returns:
        The sources as stored.

    Raises:
        HTTPException: 400 / 404 / 409 / 422 as described; 403 without ``pacts:edit`` (or
            ``imports:view`` with a repository).
    """
    user_id = enforce_permission(db, auth_data, Resource.PACTS, Action.EDIT, target=pacticipant_ref)
    if body.repository is not None:
        enforce_permission(db, auth_data, Resource.IMPORTS, Action.VIEW, target=body.repository.repository_id)
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    try:
        pacticipant = get_pacticipant(db, tenant_id, pacticipant_ref)
        return put_contract_sources(db, tenant_id, pacticipant, body, user_id=user_id)
    except PacticipantValidationError as exc:
        raise _http_error(exc) from exc
