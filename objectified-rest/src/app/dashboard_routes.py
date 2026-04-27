"""Dashboard API routes (REPO-10.3 / #2949: tenant-level repository corpus roll-up)."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from .auth import validate_authentication
from .repositories_routes import (
    _REPOSITORY_SCOPE_READ,
    _require_repository_scope,
    get_repository_corpus_rollup,
)

router = APIRouter(prefix="/v1/dashboard", tags=["dashboard"])


class RepositoryCorpusStatsResponse(BaseModel):
    """Cross-repository aggregate spec counts for the scanned report dashboard."""

    repositoriesTracked: int
    importableSpecs: int
    awaitingSelection: int
    parseErrors: int
    manifestErrors: int
    refreshedAt: str


@router.get(
    "/{tenant_slug}/repository_corpus_stats",
    response_model=RepositoryCorpusStatsResponse,
    summary="Tenant corpus stats for scan reports (rolled up server-side).",
)
async def read_repository_corpus_stats(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RepositoryCorpusStatsResponse:
    _ = tenant_slug
    _require_repository_scope(auth_data, _REPOSITORY_SCOPE_READ)
    tenant_id = str(auth_data["tenant_id"])
    data = get_repository_corpus_rollup(tenant_id)
    return RepositoryCorpusStatsResponse(**data)
