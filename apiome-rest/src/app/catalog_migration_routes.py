"""Backstage and Compass import — REST — CDG-5.5 (#5983).

Under ``/v1/tenants/{tenant_slug}``:

* ``GET /catalog-migrations`` — every import report (repository scans' ``catalog-info`` files and
  Compass uploads), newest first.
* ``POST /catalog-migrations/compass`` — upload a Compass export; returns its report.
* ``GET /catalog-migrations/{run_id}`` — one report with its suggestions and unmapped fields.
* ``POST /catalog-migration-suggestions/{id}/accept`` · ``…/dismiss`` — the click.
* ``GET /catalog-components/{slug}`` — an accepted component.

Imports are catalog data, so the routes use the ``imports`` RBAC resource: ``view`` to read,
``create`` to upload and to decide. Accepting a team suggestion also needs ``teams:create``.
Uploads and decisions are audited (``catalog.migration.*``); a report never stores a field's value.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from . import catalog_migration_store as store
from .auth import validate_authentication
from .catalog_migration_models import (
    CODE_COMPONENT_NOT_FOUND,
    CODE_DECIDED,
    CODE_RUN_NOT_FOUND,
    CODE_SLUG_TAKEN,
    CODE_SUGGESTION_NOT_FOUND,
    CODE_TOO_LARGE,
    AcceptInput,
    CompassUploadInput,
    ComponentOut,
    MigrationError,
    MigrationRun,
    MigrationRunList,
    MigrationSuggestion,
)
from .consumer_contract_store import actor_from_auth
from .database import db
from .permissions import Action, Resource, enforce_permission

router = APIRouter(prefix="/v1/tenants", tags=["catalog-migrations"])

_RUNS = "/{tenant_slug}/catalog-migrations"
_SUGGESTIONS = "/{tenant_slug}/catalog-migration-suggestions"
_COMPONENTS = "/{tenant_slug}/catalog-components"

#: Refusal code → HTTP status (anything else is a 400).
_STATUS = {
    CODE_RUN_NOT_FOUND: 404,
    CODE_SUGGESTION_NOT_FOUND: 404,
    CODE_COMPONENT_NOT_FOUND: 404,
    CODE_DECIDED: 409,
    CODE_SLUG_TAKEN: 409,
    CODE_TOO_LARGE: 413,
}


def _tenant_id(auth_data: Dict[str, Any]) -> str:
    """The authenticated tenant id, or a 403."""
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this credential.")
    return str(tenant_id)


def _http(exc: MigrationError) -> HTTPException:
    """Translate a refusal into ``{code, message}`` with its status."""
    return HTTPException(status_code=_STATUS.get(exc.code, 400), detail={"code": exc.code, "message": str(exc)})


def _permit(auth_data: Dict[str, Any], action: str, target: str) -> Any:
    """Require ``imports:<action>`` and return the actor."""
    user_id = enforce_permission(db, auth_data, Resource.IMPORTS, action, target=target)
    return actor_from_auth(auth_data, user_id)


@router.get(_RUNS, response_model=MigrationRunList, response_model_by_alias=True, summary="List import reports")
async def list_catalog_migrations(
    tenant_slug: str, auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> MigrationRunList:
    """Every Backstage and Compass import report, most recently updated first (`imports:view`).

    A repository branch with `catalog-info.yaml` files has one report, rewritten by each scan; each
    Compass upload has its own. `pending` counts the suggestions still waiting for a decision.
    """
    _ = tenant_slug
    _permit(auth_data, Action.VIEW, "catalog-migrations")
    return MigrationRunList(runs=store.list_runs(_tenant_id(auth_data)))


@router.post(
    _RUNS + "/compass",
    response_model=MigrationRun,
    response_model_by_alias=True,
    status_code=201,
    summary="Import a Compass export",
)
async def import_compass_export(
    tenant_slug: str, body: CompassUploadInput, auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> MigrationRun:
    """Stage an Atlassian Compass export (`imports:create`).

    `content` is the export's JSON: `{components, teams}`, a GraphQL `searchComponents` response, or
    a list of components (at most 5 MB). Components become component suggestions (links,
    `DEPENDS_ON` relationships as declared references), owners become team suggestions, and every
    field that has no Apiome equivalent is listed in `unmapped`. Nothing is created until a
    suggestion is accepted.
    """
    _ = tenant_slug
    actor = _permit(auth_data, Action.CREATE, "catalog-migrations")
    try:
        return store.import_compass_export(
            _tenant_id(auth_data), body.filename, body.content.encode("utf-8"), actor=actor
        )
    except MigrationError as exc:
        raise _http(exc) from exc


@router.get(
    _RUNS + "/{run_id}", response_model=MigrationRun, response_model_by_alias=True, summary="Read an import report"
)
async def read_catalog_migration(
    tenant_slug: str, run_id: str, auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> MigrationRun:
    """One report: counts, suggestions (teams, then components) and unmapped fields (`imports:view`)."""
    _ = tenant_slug
    _permit(auth_data, Action.VIEW, f"catalog-migration:{run_id}")
    try:
        return store.read_run(_tenant_id(auth_data), run_id)
    except MigrationError as exc:
        raise _http(exc) from exc


@router.post(
    _SUGGESTIONS + "/{suggestion_id}/accept",
    response_model=MigrationSuggestion,
    response_model_by_alias=True,
    summary="Accept a suggestion",
)
async def accept_catalog_migration_suggestion(
    tenant_slug: str,
    suggestion_id: str,
    body: AcceptInput,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> MigrationSuggestion:
    """Accept a suggestion (`imports:create`; a team also needs `teams:create`).

    * **Team** — creates the team with the imported name, description, email and links (or links the
      live team that already has the slug), then suggests it as the owner of everything the import
      said it owns. It is never confirmed as an owner here.
    * **Component** matched to a Project or catalog item — applies the owner suggestion (and, for
      Compass, the declared dependencies) to that entity. `asComponent: true` registers it as a
      component of its own instead.
    * **Component** — registers a `component` entity with its links and declared dependencies;
      references to it that were unresolved resolve now.

    `name` and `slug` override what was imported. 409 `migration-slug-taken` when a component has
    the slug already; 409 `migration-suggestion-decided` when it was decided before.
    """
    _ = tenant_slug
    actor = _permit(auth_data, Action.CREATE, f"catalog-migration-suggestion:{suggestion_id}")
    tenant_id = _tenant_id(auth_data)
    try:
        current = store.read_suggestion(tenant_id, suggestion_id)
        if current.kind == "team":
            enforce_permission(db, auth_data, Resource.TEAMS, Action.CREATE, target=current.slug)
        return store.accept_suggestion(tenant_id, suggestion_id, body, actor=actor)
    except MigrationError as exc:
        raise _http(exc) from exc


@router.post(
    _SUGGESTIONS + "/{suggestion_id}/dismiss",
    response_model=MigrationSuggestion,
    response_model_by_alias=True,
    summary="Dismiss a suggestion",
)
async def dismiss_catalog_migration_suggestion(
    tenant_slug: str, suggestion_id: str, auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> MigrationSuggestion:
    """Dismiss a suggestion (`imports:create`); later scans and uploads keep it dismissed."""
    _ = tenant_slug
    actor = _permit(auth_data, Action.CREATE, f"catalog-migration-suggestion:{suggestion_id}")
    try:
        return store.dismiss_suggestion(_tenant_id(auth_data), suggestion_id, actor=actor)
    except MigrationError as exc:
        raise _http(exc) from exc


@router.get(
    _COMPONENTS + "/{slug}", response_model=ComponentOut, response_model_by_alias=True, summary="Read a component"
)
async def read_catalog_component(
    tenant_slug: str, slug: str, auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> ComponentOut:
    """An accepted Backstage or Compass component, system or domain (`imports:view`).

    Its owner, facts and dependencies are read through the owners, entity-facts and graph routes
    with kind `component`.
    """
    _ = tenant_slug
    _permit(auth_data, Action.VIEW, f"catalog-component:{slug}")
    try:
        return store.read_component(_tenant_id(auth_data), slug)
    except MigrationError as exc:
        raise _http(exc) from exc
