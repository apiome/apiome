"""
Semantic OpenAPI diff: POST two resolved specs -> ChangeReportModel (#2699).
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends

from .auth import validate_authentication
from .models import ChangeReportModel, OpenApiChangeReportRequest
from .openapi_change_report import build_change_report

router = APIRouter(prefix="/v1/openapi", tags=["openapi-change-report"])


@router.post("/change-report", response_model=ChangeReportModel)
async def post_openapi_change_report(
    body: OpenApiChangeReportRequest,
    _auth: Dict[str, Any] = Depends(validate_authentication),
) -> ChangeReportModel:
    """
    Compare **baselineOpenApi** to **candidateOpenApi** and return a deterministic
    :class:`ChangeReportModel` (schemas, properties, references, relationships, documentation).
    Both bodies must be resolved OpenAPI 3.x JSON (internal ``components``, normalized ``$ref``).
    """
    raw = build_change_report(body.baseline_open_api, body.candidate_open_api)
    return ChangeReportModel.model_validate(raw)
