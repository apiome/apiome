"""``/v1/tenants/{tenant}/pact-environments`` — environments and deployments, PFX-5.7 (#6951).

What the **Environments** pages of the Contracts workspace read beside the Pact Broker's
environment routes (PFX-1.5):

* ``GET …/pact-environments`` — every environment with what is deployed to it now and the
  releases it supports (the dashboard's grid);
* ``GET …/pact-environments/{environment}/deployments`` — the environment's deployment history,
  newest first, narrowed by ``pacticipant``, one page at a time (``cursor``, ``limit``);
* ``GET …/pact-environments/board`` — the what-is-where board (PFX-8.13): pacticipants ×
  environments, each cell the running version(s) with a verdict, and whether the next version can go;
* ``GET …/pact-environments/history`` — the workspace's deployments, undeployments, releases and
  ends of support, newest first, with who and the verdict at the time (PFX-8.13);
* ``GET …/pact-environments/{environment}/simulate`` — the deploy simulator: *what if
  ``pacticipant`` ``version`` were deployed here?* The candidate's can-i-deploy verdict and how the
  verdict of each counterpart version changes (running here: breaks / fixes; deployed elsewhere:
  clears / blocks). It records nothing.

``{environment}`` is the environment's **name** (``production``), the address people read. They
live beside the Pact Broker surface, not under ``…/pact-broker``, because no Pact Broker or
PactFlow client knows them; that surface stays the catalogued, PactFlow-compatible one.

All need ``pacts:view``. Only the caller's tenant is read.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from .auth import validate_authentication
from .database import db
from .pact_deployments import (
    CODE_DEPLOYMENT_CURSOR_INVALID,
    CODE_SIMULATION_INVALID,
    DEFAULT_HISTORY_PAGE,
    MAX_HISTORY_PAGE,
    Check,
    Impact,
    NotChecked,
    Placement,
    TopologyEntry,
    list_deployment_history,
    read_topology,
    simulate_deployment,
)
from .pact_environment import CODE_ENVIRONMENT_NOT_FOUND, EnvironmentRecord
from .pact_environment_board import (
    CODE_HISTORY_CURSOR_INVALID,
    MAX_BOARD_CHECKS,
    BoardRow,
    HistoryEvent,
    list_history,
    read_board,
)
from .pact_environment_board import DEFAULT_HISTORY_PAGE as DEFAULT_EVENTS_PAGE
from .pact_environment_board import MAX_HISTORY_PAGE as MAX_EVENTS_PAGE
from .pact_matrix import CODE_MATRIX_INVALID
from .pact_publication import PactPublicationError
from .pacticipant import CODE_NOT_FOUND, CODE_VERSION_NOT_FOUND, PacticipantValidationError
from .permissions import Action, Resource, enforce_permission

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["pact-broker"])

_PREFIX = "/{tenant_slug}/pact-environments"

_STATUS_BY_CODE = {
    CODE_DEPLOYMENT_CURSOR_INVALID: 400,
    CODE_HISTORY_CURSOR_INVALID: 400,
    CODE_SIMULATION_INVALID: 400,
    CODE_MATRIX_INVALID: 400,
    CODE_ENVIRONMENT_NOT_FOUND: 404,
    CODE_NOT_FOUND: 404,
    CODE_VERSION_NOT_FOUND: 404,
}

_ENVIRONMENT_NOT_FOUND = {404: {"description": "`pact-environment-not-found`: no environment with that name here."}}


def _http_error(exc: Exception) -> HTTPException:
    """Translate a refusal into ``{"detail": {"code", "message"[, "pointer"]}}`` with its status."""
    code = getattr(exc, "code", "")
    detail: Dict[str, Any] = {"code": code, "message": str(exc)}
    pointer = getattr(exc, "pointer", None)
    if pointer is not None:
        detail["pointer"] = pointer
    return HTTPException(status_code=_STATUS_BY_CODE.get(code, 400), detail=detail)


def _tenant_id(auth_data: Dict[str, Any]) -> str:
    """The authenticated tenant id, or a 403."""
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this credential.")
    return str(tenant_id)


def _environment_document(environment: EnvironmentRecord) -> Dict[str, Any]:
    """``uuid``, ``name``, ``displayName``, ``production``, ``contractRequired``."""
    return {
        "uuid": environment.id,
        "name": environment.name,
        "displayName": environment.display_name,
        "production": environment.production,
        "contractRequired": environment.contract_required,
    }


def _entry_document(entry: TopologyEntry, deployed: bool) -> Dict[str, Any]:
    """One version in an environment now."""
    document: Dict[str, Any] = {
        "pacticipant": {"name": entry.pacticipant_name, "slug": entry.pacticipant_slug},
        "version": entry.version_number,
    }
    if deployed:
        document["applicationInstance"] = entry.application_instance
        document["deployedAt"] = entry.recorded_at
    else:
        document["releasedAt"] = entry.recorded_at
    return document


def _check_document(check: Check) -> Dict[str, Any]:
    """A verdict: ``deployable``, ``reason`` (one per line), ``reasons``, ``counts``."""
    return {
        "deployable": check.deployable,
        "reason": "\n".join(reason["text"] for reason in check.reasons),
        "reasons": check.reasons,
        "counts": check.counts,
    }


def _placement_document(placement: Placement) -> Dict[str, Any]:
    """A counterpart version: pacticipant, version, placement and (pending) where it is now."""
    return {
        "pacticipant": {"name": placement.pacticipant_name, "slug": placement.pacticipant_slug},
        "version": placement.version_number,
        "placement": placement.placement,
        "environments": list(placement.environments),
    }


def _impact_document(impact: Impact) -> Dict[str, Any]:
    """One checked counterpart version: before, after and the effect."""
    return {
        **_placement_document(impact.placement),
        "roles": list(impact.roles),
        "before": _check_document(impact.before),
        "after": _check_document(impact.after),
        "effect": impact.effect,
    }


def _not_checked_document(item: NotChecked) -> Dict[str, Any]:
    """One counterpart version not checked, with the reason."""
    return {**_placement_document(item.placement), "code": item.code, "reason": item.reason}


@router.get(
    _PREFIX,
    summary="Environments and what is deployed to them",
    description=(
        "Every Pact environment of the workspace (by name) with each pacticipant version currently "
        "deployed to it (`deployed`: pacticipant, version, application instance, when) and each "
        "release it currently supports (`released`). `truncated` is true when either list stopped "
        "at 2000 entries. Requires `pacts:view`."
    ),
)
def read_environment_topology(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, Any]:
    """Read every environment and what is in it now.

    Args:
        tenant_slug: The tenant in the URL.
        auth_data: The authenticated principal.

    Returns:
        ``{"environments": [{..., "deployed": [...], "released": [...]}], "truncated": bool}``.
    """
    del tenant_slug
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    topology = read_topology(db, _tenant_id(auth_data))
    by_environment: Dict[str, Dict[str, List[Dict[str, Any]]]] = {
        environment.id: {"deployed": [], "released": []} for environment in topology.environments
    }
    for entry in topology.deployed:
        if entry.environment_id in by_environment:
            by_environment[entry.environment_id]["deployed"].append(_entry_document(entry, True))
    for entry in topology.released:
        if entry.environment_id in by_environment:
            by_environment[entry.environment_id]["released"].append(_entry_document(entry, False))
    return {
        "environments": [
            {**_environment_document(environment), **by_environment[environment.id]}
            for environment in topology.environments
        ],
        "truncated": topology.truncated,
    }


def _verdict_document(check: Optional[Check], not_checked: Optional[str]) -> Dict[str, Any]:
    """A board verdict: ``checked``, and either the verdict or ``notChecked`` (the reason)."""
    if check is None:
        return {"checked": False, "notChecked": not_checked or "Not checked."}
    return {"checked": True, **_check_document(check)}


def _board_row_document(row: BoardRow) -> Dict[str, Any]:
    """One pacticipant's row of the board."""
    return {
        "pacticipant": {"name": row.pacticipant_name, "slug": row.pacticipant_slug},
        "idle": row.idle,
        "cells": [
            {
                "environment": cell.environment_id,
                "deployed": [
                    {
                        "version": version.version_number,
                        "applicationInstances": list(version.application_instances),
                        "deployedAt": version.deployed_at,
                        "verdict": _verdict_document(version.check, version.not_checked),
                    }
                    for version in cell.deployed
                ],
                "next": (
                    {
                        "version": cell.next.version_number,
                        "from": cell.next.from_environment,
                        "verdict": _verdict_document(cell.next.check, cell.next.not_checked),
                    }
                    if cell.next is not None
                    else None
                ),
            }
            for cell in row.cells
        ],
        "released": [
            {
                "version": release.version_number,
                "environment": release.environment_name,
                "releasedAt": release.released_at,
                "verdict": _verdict_document(release.check, release.not_checked),
            }
            for release in row.released
        ],
    }


@router.get(
    _PREFIX + "/board",
    summary="What is running where",
    description=(
        "The Environments page's board (PFX-8.13): one row per pacticipant (by name), one cell per "
        "environment — non-production first, production last — and every release it supports.\n\n"
        "- Each running version carries can-i-deploy's `verdict` for that environment "
        "(`deployable` true, false, or null while a verification is missing).\n"
        "- `next` is the version that could go next: the newest version in the nearest environment "
        "to the left that runs the pacticipant, when it is newer than anything here, with its "
        "verdict — the deploy simulator's answer to the same question.\n"
        "- `idle` rows have nothing deployed or released anywhere (at most 50 are listed).\n\n"
        f"At most {MAX_BOARD_CHECKS} verdicts are asked per read; the rest say `checked: false` and why "
        "(`notChecked`). `truncated` is true when a read stopped at its cap. Requires `pacts:view`."
    ),
)
def read_environment_board(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, Any]:
    """Read the what-is-where board.

    Args:
        tenant_slug: The tenant in the URL.
        auth_data: The authenticated principal.

    Returns:
        ``{"environments", "rows", "truncated", "checks", "notChecked", "evaluatedAt"}``.
    """
    del tenant_slug
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    board = read_board(db, _tenant_id(auth_data))
    return {
        "environments": [_environment_document(environment) for environment in board.environments],
        "rows": [_board_row_document(row) for row in board.rows],
        "truncated": board.truncated,
        "checks": board.checks,
        "notChecked": board.not_checked,
        "evaluatedAt": board.evaluated_at,
    }


def _event_document(event: HistoryEvent) -> Dict[str, Any]:
    """One history event."""
    return {
        "kind": event.kind,
        "uuid": event.id,
        "at": event.at,
        "pacticipant": {"name": event.pacticipant_name, "slug": event.pacticipant_slug},
        "version": event.version_number,
        "environment": _environment_document(event.environment),
        "applicationInstance": event.application_instance,
        "actor": event.actor,
        "verdict": event.verdict,
        "replaces": event.replaces,
    }


@router.get(
    _PREFIX + "/history",
    summary="History of every environment",
    description=(
        "What happened in the workspace's environments, newest first (PFX-8.13): `kind` is "
        "`deployed`, `undeployed`, `released` or `support-ended`, with the pacticipant, version, "
        "environment, application instance and `actor` (who recorded it, when known). A `deployed` "
        "event names the version it `replaces`; the replaced deployment has no event of its own. "
        "`deployed` and `released` carry `verdict` — can-i-deploy's answer when it was recorded "
        "(`deployable`, `not-deployable`, `unknown`), or null when not known (recorded before "
        "this was kept, or imported). `environment` (a name) and `pacticipant` (handle or name) "
        "narrow it. Pass `nextCursor` back as `cursor` for the next page. Requires `pacts:view`."
    ),
    responses={
        400: {"description": "`pact-history-cursor-invalid`."},
        404: {"description": "`pact-environment-not-found` or `pacticipant-not-found`."},
    },
)
def read_environment_history(
    tenant_slug: str,
    environment: Optional[str] = Query(None, max_length=255, description="Only this environment (its name)."),
    pacticipant: Optional[str] = Query(None, max_length=255, description="Only this pacticipant (handle or name)."),
    cursor: Optional[str] = Query(None, max_length=200, description="The `nextCursor` of the previous page."),
    limit: int = Query(DEFAULT_EVENTS_PAGE, ge=1, le=MAX_EVENTS_PAGE, description="The page size."),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, Any]:
    """Read one page of the environments' history.

    Args:
        tenant_slug: The tenant in the URL.
        environment: Only this environment.
        pacticipant: Only this pacticipant.
        cursor: Where the page starts.
        limit: The page size.
        auth_data: The authenticated principal.

    Returns:
        ``{"events": [...], "nextCursor": str | None}``.
    """
    del tenant_slug
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    try:
        page = list_history(
            db,
            _tenant_id(auth_data),
            environment_name=environment,
            pacticipant_ref=pacticipant,
            cursor=cursor,
            limit=limit,
        )
    except (PactPublicationError, PacticipantValidationError) as exc:
        raise _http_error(exc) from exc
    return {"events": [_event_document(event) for event in page.events], "nextCursor": page.next_cursor}


@router.get(
    _PREFIX + "/{environment}/deployments",
    summary="Deployment history of an environment",
    description=(
        "Every deployment recorded to the environment, current or replaced, newest first: "
        "pacticipant, version, application instance, `currentlyDeployed`, `deployedAt`, "
        "`undeployedAt` and who recorded it. `pacticipant` narrows to one pacticipant (handle or "
        "name). Pass `nextCursor` back as `cursor` for the next page. Requires `pacts:view`."
    ),
    responses={
        400: {"description": "`pact-deployment-cursor-invalid`."},
        404: {"description": "`pact-environment-not-found` or `pacticipant-not-found`."},
    },
)
def read_deployment_history(
    tenant_slug: str,
    environment: str,
    pacticipant: Optional[str] = Query(None, description="Only this pacticipant's deployments (handle or name)."),
    cursor: Optional[str] = Query(None, description="The `nextCursor` of the previous page."),
    limit: int = Query(DEFAULT_HISTORY_PAGE, ge=1, le=MAX_HISTORY_PAGE, description="The page size."),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, Any]:
    """Read one page of an environment's deployment history.

    Args:
        tenant_slug: The tenant in the URL.
        environment: The environment's name.
        pacticipant: Only this pacticipant.
        cursor: Where the page starts.
        limit: The page size.
        auth_data: The authenticated principal.

    Returns:
        ``{"environment": {...}, "deployments": [...], "nextCursor": str | None}``.
    """
    del tenant_slug
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    try:
        page = list_deployment_history(
            db, _tenant_id(auth_data), environment, pacticipant_ref=pacticipant, cursor=cursor, limit=limit
        )
    except (PactPublicationError, PacticipantValidationError) as exc:
        raise _http_error(exc) from exc
    return {
        "environment": _environment_document(page.environment),
        "deployments": [
            {
                "uuid": item.id,
                "pacticipant": {"name": item.pacticipant_name, "slug": item.pacticipant_slug},
                "version": item.version_number,
                "applicationInstance": item.application_instance,
                "currentlyDeployed": item.currently_deployed,
                "deployedAt": item.deployed_at,
                "undeployedAt": item.undeployed_at,
                "recordedBy": item.recorded_by,
            }
            for item in page.deployments
        ],
        "nextCursor": page.next_cursor,
    }


@router.get(
    _PREFIX + "/{environment}/simulate",
    summary="Simulate a deployment",
    description=(
        "What would happen if `pacticipant` `version` were deployed to the environment (to "
        "`applicationInstance`, or the unnamed instance) — without recording anything. Answers the "
        "candidate's own can-i-deploy `verdict`, the version it would `replace`, and `impacts`: for "
        "each version of a pacticipant it has a pact with that is **running** in the environment "
        "or **pending** (deployed or released elsewhere, not here), its verdict `before` and "
        "`after` and the `effect` (`breaks`, `fixes`, `clears`, `blocks`, `changes`, `unchanged`). "
        "At most 20 versions are checked; the rest are in `notChecked` with the reason. Requires "
        "`pacts:view`."
    ),
    responses={
        400: {"description": "`pact-simulation-invalid`: a malformed `applicationInstance`."},
        404: {
            "description": ("`pact-environment-not-found`, `pacticipant-not-found` or `pacticipant-version-not-found`.")
        },
    },
)
def read_deployment_simulation(
    tenant_slug: str,
    environment: str,
    pacticipant: str = Query(
        ..., min_length=1, max_length=255, description="The pacticipant to deploy (handle or name)."
    ),
    version: str = Query(..., min_length=1, max_length=255, description="The version to deploy."),
    application_instance: Optional[str] = Query(
        None, alias="applicationInstance", description="The instance to deploy to; the unnamed one when omitted."
    ),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, Any]:
    """Simulate deploying one version to an environment.

    Args:
        tenant_slug: The tenant in the URL.
        environment: The environment's name.
        pacticipant: The candidate's pacticipant.
        version: The candidate version.
        application_instance: The instance it would go to.
        auth_data: The authenticated principal.

    Returns:
        The simulation document.
    """
    del tenant_slug
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    try:
        simulation = simulate_deployment(
            db, _tenant_id(auth_data), environment, pacticipant, version, application_instance=application_instance
        )
    except (PactPublicationError, PacticipantValidationError) as exc:
        raise _http_error(exc) from exc
    summary: Dict[str, int] = {}
    for impact in simulation.impacts:
        summary[impact.effect] = summary.get(impact.effect, 0) + 1
    return {
        "environment": _environment_document(simulation.environment),
        "pacticipant": {"name": simulation.pacticipant.name, "slug": simulation.pacticipant.slug},
        "version": simulation.version_number,
        "applicationInstance": simulation.application_instance,
        "replaces": simulation.replaces,
        "alreadyDeployed": simulation.already_deployed,
        "evaluatedAt": simulation.evaluated_at,
        "verdict": _check_document(simulation.verdict),
        "impacts": [_impact_document(impact) for impact in simulation.impacts],
        "notChecked": [_not_checked_document(item) for item in simulation.not_checked],
        "summary": summary,
    }
