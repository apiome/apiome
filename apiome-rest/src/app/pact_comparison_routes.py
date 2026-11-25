"""Bi-directional comparisons and their fidelity reports — PFX-2.5 (#6929).

A bi-directional verification result (PFX-2.3) says ``pass``, ``partial`` or ``fail``. These routes
say how much that verdict is worth: for every interaction, which checks ran, which matching rules
the comparison could not prove, and what it could not compare at all
(:func:`app.pact_comparison_fidelity.build_fidelity_report`).

* ``GET /v1/tenants/{tenant}/pact-comparisons`` — the workspace's most recent bi-directional
  results, each with its verdict, strength and counts, for the **Pact comparisons** page.
* ``GET /v1/tenants/{tenant}/pact-comparisons/{resultId}/fidelity`` — one result's report. The
  Pact Broker result document links it as ``apiome:comparison-fidelity``.

They live beside the Pact Broker surface, not under ``…/pact-broker``, because no Pact Broker or
PactFlow client knows them; that surface stays the catalogued, PactFlow-compatible one.

Both read only the caller's tenant and require ``pacts:view``. A native result (published by a Pact
verifier) has no comparison, and asking for its report is a ``404`` that says so.
"""

from __future__ import annotations

from typing import Any, Dict
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query

from .auth import validate_authentication
from .database import db
from .pact_comparison_fidelity import build_fidelity_report
from .pact_publication import PactPublicationError
from .permissions import Action, Resource, enforce_permission
from .verification_result import VerificationResultRecord
from .verification_result_store import (
    MAX_BIDIRECTIONAL_LIST,
    get_bidirectional_result,
    list_bidirectional_results,
)

__all__ = ["comparison_fidelity_path", "router"]

router = APIRouter(prefix="/v1/tenants", tags=["pact-broker"])

_NOT_FOUND = {
    404: {
        "description": (
            "`pact-verification-not-found`: no bi-directional result with that id in this workspace, "
            "or the result was published by a Pact verifier and has no comparison."
        )
    }
}


def comparison_fidelity_path(tenant_slug: str, result_id: str) -> str:
    """The API path of one result's fidelity report (without the API root).

    Args:
        tenant_slug: The tenant.
        result_id: The verification result's id.

    Returns:
        ``/v1/tenants/{tenant}/pact-comparisons/{resultId}/fidelity``.
    """
    return f"/v1/tenants/{quote(tenant_slug, safe='')}/pact-comparisons/{quote(result_id, safe='')}/fidelity"


def _tenant_id(auth_data: Dict[str, Any]) -> str:
    """The authenticated tenant id, or a 403."""
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this credential.")
    return str(tenant_id)


def _identity(result: VerificationResultRecord) -> Dict[str, Any]:
    """What names a result: the pair, the versions, the pact version and the result number."""
    return {
        "id": result.id,
        "number": result.number,
        "consumer": {"name": result.consumer_name, "slug": result.consumer_slug, "version": result.consumer_version},
        "provider": {
            "name": result.provider_name,
            "slug": result.provider_slug,
            "version": result.provider_version,
            "branch": result.provider_branch,
        },
        "pactVersionSha": result.sha,
        "success": result.success,
        "createdAt": result.created_at,
    }


def _list_entry(tenant_slug: str, result: VerificationResultRecord) -> Dict[str, Any]:
    """One row of the list: the identity, and the report's verdict, strength, statement and counts."""
    report = build_fidelity_report(result.comparison or {})
    return {
        **_identity(result),
        "verdict": report["verdict"],
        "comparisonVerdict": report["comparisonVerdict"],
        "strength": report["strength"],
        "statement": report["statement"],
        "selfVerification": report["selfVerification"],
        "summary": report["summary"],
        "fidelityPath": comparison_fidelity_path(tenant_slug, result.id),
    }


@router.get(
    "/{tenant_slug}/pact-comparisons",
    summary="List recent bi-directional comparisons",
    description=(
        "The workspace's most recent bi-directional verification results (PFX-2.3), newest first, "
        "each with its verdict, how strong it is (`full`, `partial`, `failed`, `none`), one sentence "
        "to read it by, and the counts of its fidelity report. Requires `pacts:view`."
    ),
)
def list_comparisons(
    tenant_slug: str,
    limit: int = Query(50, ge=1, le=MAX_BIDIRECTIONAL_LIST, description="How many to return."),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, Any]:
    """List the workspace's recent bi-directional results.

    Args:
        tenant_slug: The tenant in the URL.
        limit: How many to return (1 … 100).
        auth_data: The authenticated principal.

    Returns:
        ``{"comparisons": [...], "limit": n}``.

    Raises:
        HTTPException: 403 without ``pacts:view``.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    results = list_bidirectional_results(db, _tenant_id(auth_data), limit)
    return {"comparisons": [_list_entry(tenant_slug, result) for result in results], "limit": limit}


@router.get(
    "/{tenant_slug}/pact-comparisons/{result_id}/fidelity",
    summary="Read the fidelity report of a bi-directional comparison",
    description=(
        "What a bi-directional comparison compared and what it could not: for every interaction the "
        "checks with their status (`compared`, `partial`, `failed`, `not-run` with the reason), the "
        "matching rules it could not prove, and the items it could not compare. A green verdict is "
        "only as strong as `strength` says. Requires `pacts:view`."
    ),
    responses=_NOT_FOUND,
)
def read_fidelity(
    tenant_slug: str,
    result_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, Any]:
    """Read one result's fidelity report.

    Args:
        tenant_slug: The tenant in the URL.
        result_id: The verification result's id.
        auth_data: The authenticated principal.

    Returns:
        The result's identity and :func:`~app.pact_comparison_fidelity.build_fidelity_report`.

    Raises:
        HTTPException: 404 for an unknown, foreign or native result; 403 without ``pacts:view``.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    try:
        result = get_bidirectional_result(db, _tenant_id(auth_data), result_id)
    except PactPublicationError as exc:
        raise HTTPException(status_code=404, detail={"code": exc.code, "message": str(exc)}) from exc
    return {"result": _identity(result), **build_fidelity_report(result.comparison or {})}
