"""
Version quality API — on-demand schema quality scoring.

A "Compute quality" run loads the version's classes and properties, applies a
small set of structural heuristics, and persists one row in
`odb.version_quality_scores`. The four sub-scores (completeness, consistency,
descriptions, examples) are surfaced on the Versions tab and the version
detail page; the trajectory chart consumes the project-wide history list.

The scorer is intentionally simple for v1 — it answers "how complete and
self-describing is this schema?" without needing a full lint engine. The lint
engine (separate subsystem, planned next) will subsume the structural
checks; the quality scorer stays focused on aggregate signal.
"""

from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query

from .auth import validate_authentication, get_authenticated_user_id
from .database import db
from .models import VersionQualityScoreSchema, VersionQualityRunResponse

router = APIRouter(prefix="/v1/version-quality", tags=["version-quality"])


# ---------- Internal helpers ----------


def _tenant_id(auth_data: Dict[str, Any]) -> str:
    tid = auth_data.get("tenant_id")
    if not tid:
        raise HTTPException(status_code=500, detail="Missing tenant context")
    return str(tid)


def _resolve_version(
    tenant_id: str,
    project_id: str,
    version_record_id: str,
) -> Dict[str, Any]:
    """Tenant-scoped version lookup with the project-membership check the rest of
    the API enforces. Raises 404 on either project or version miss."""
    project = db.get_project_by_id(project_id, tenant_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    version = db.get_version_by_id(version_record_id, tenant_id)
    if not version or str(version.get("project_id")) != str(project_id):
        raise HTTPException(status_code=404, detail="Version not found")
    return version


def _has_text(value: Any) -> bool:
    """Truth test for description-style fields: present, a string, non-empty
    after stripping. Mirrors how the frontend renders these fields."""
    return isinstance(value, str) and value.strip() != ""


def _property_has_example(prop: Dict[str, Any]) -> bool:
    """A property "has an example" when its `data` blob carries a non-empty
    `example` (or `examples`) field — the same shape the studio editor writes."""
    data = prop.get("data")
    if not isinstance(data, dict):
        return False
    if _has_text(data.get("example")):
        return True
    examples = data.get("examples")
    if isinstance(examples, list) and len(examples) > 0:
        return True
    if isinstance(examples, dict) and len(examples) > 0:
        return True
    return False


def _is_camel_or_snake(name: str) -> bool:
    """Loose name-style check: name is either lowerCamelCase or snake_case
    throughout. Used to estimate consistency without enforcing a project-wide
    convention (the lint engine will do that properly)."""
    if not name:
        return False
    if name != name.strip():
        return False
    has_upper = any(c.isupper() for c in name)
    has_underscore = "_" in name
    if has_upper and has_underscore:
        return False
    if name[0].isdigit():
        return False
    return True


def _percent(numerator: int, denominator: int) -> int:
    """Integer percentage with a sensible "no data" floor of 100 (an empty
    schema isn't penalized for missing descriptions on classes that don't
    exist)."""
    if denominator <= 0:
        return 100
    return max(0, min(100, round((numerator / denominator) * 100)))


def _load_classes_and_properties(
    version_id: str,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Two bulk queries: classes for the version, then properties for those
    classes. Avoids the N+1 pattern of looping over `get_properties_for_class`
    when a version has many classes."""
    classes: List[Dict[str, Any]] = db.get_classes_for_version(version_id) or []
    if not classes:
        return [], []
    class_ids = [str(c["id"]) for c in classes]
    placeholders = ",".join(["%s"] * len(class_ids))
    rows = db.execute_query(
        f"""
        SELECT cp.id, cp.class_id, cp.name, cp.description, cp.data
        FROM odb.class_properties cp
        WHERE cp.class_id IN ({placeholders})
        """,
        tuple(class_ids),
    )
    return classes, rows or []


def _compute_quality(version_id: str) -> Tuple[Dict[str, int], Dict[str, Any]]:
    """Apply the v1 heuristics to one version. Returns:

      (
        {overall, completeness, consistency, descriptions, examples,
         class_count, property_count},
        detail dict with per-bucket breakdowns for UI drilldown,
      )
    """
    classes, properties = _load_classes_and_properties(version_id)
    class_count = len(classes)
    property_count = len(properties)

    classes_with_description = sum(1 for c in classes if _has_text(c.get("description")))
    classes_named_consistently = sum(
        1 for c in classes if _is_camel_or_snake(str(c.get("name") or ""))
    )
    properties_with_description = sum(1 for p in properties if _has_text(p.get("description")))
    properties_with_example = sum(1 for p in properties if _property_has_example(p))
    properties_named_consistently = sum(
        1 for p in properties if _is_camel_or_snake(str(p.get("name") or ""))
    )
    classes_with_properties = {str(p.get("class_id")) for p in properties}
    classes_no_properties = sum(
        1 for c in classes if str(c["id"]) not in classes_with_properties
    )

    descriptions_total = class_count + property_count
    descriptions_filled = classes_with_description + properties_with_description
    descriptions_pct = _percent(descriptions_filled, descriptions_total)
    examples_pct = _percent(properties_with_example, property_count)
    consistency_total = class_count + property_count
    consistency_filled = classes_named_consistently + properties_named_consistently
    consistency_pct = _percent(consistency_filled, consistency_total)
    completeness_signals = max(1, class_count + property_count)
    completeness_filled = (
        (class_count - classes_no_properties)
        + properties_with_description
    )
    completeness_pct = _percent(completeness_filled, completeness_signals)

    overall = round(
        0.30 * completeness_pct
        + 0.25 * descriptions_pct
        + 0.25 * consistency_pct
        + 0.20 * examples_pct
    )
    overall = max(0, min(100, overall))

    scores = {
        "overall": int(overall),
        "completeness": int(completeness_pct),
        "consistency": int(consistency_pct),
        "descriptions": int(descriptions_pct),
        "examples": int(examples_pct),
        "class_count": int(class_count),
        "property_count": int(property_count),
    }
    detail = {
        "classes_with_description": classes_with_description,
        "classes_named_consistently": classes_named_consistently,
        "classes_no_properties": classes_no_properties,
        "properties_with_description": properties_with_description,
        "properties_with_example": properties_with_example,
        "properties_named_consistently": properties_named_consistently,
        "weights": {
            "completeness": 0.30,
            "descriptions": 0.25,
            "consistency": 0.25,
            "examples": 0.20,
        },
    }
    return scores, detail


# ---------- Routes ----------
#
# Route registration order matters: FastAPI matches in declaration order, so
# every route whose third path segment is the literal `history` MUST be
# declared before the catch-all `/{tenant_slug}/{project_id}/{version_record_id}`
# route below — otherwise "history" gets bound to `version_record_id` and the
# version-lookup throws 404.


@router.get(
    "/{tenant_slug}/{project_id}/history",
    response_model=List[VersionQualityScoreSchema],
)
async def list_project_quality_history(
    tenant_slug: str,
    project_id: str,
    limit: int = Query(200, ge=1, le=1000),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> List[VersionQualityScoreSchema]:
    """Cross-version snapshot history for a project. Drives the trajectory
    chart on the project Versions tab."""
    tenant_id = _tenant_id(auth_data)
    project = db.get_project_by_id(project_id, tenant_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    rows = db.list_project_quality_history(project_id, tenant_id, limit=limit)
    return [VersionQualityScoreSchema(**dict(r)) for r in rows]


@router.get(
    "/{tenant_slug}/{project_id}/{version_record_id}/history",
    response_model=List[VersionQualityScoreSchema],
)
async def list_quality_history(
    tenant_slug: str,
    project_id: str,
    version_record_id: str,
    limit: int = Query(50, ge=1, le=500),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> List[VersionQualityScoreSchema]:
    """Snapshot history for a single version, newest first."""
    tenant_id = _tenant_id(auth_data)
    _resolve_version(tenant_id, project_id, version_record_id)
    rows = db.list_version_quality_history(version_record_id, tenant_id, limit=limit)
    return [VersionQualityScoreSchema(**dict(r)) for r in rows]


@router.get(
    "/{tenant_slug}/{project_id}/{version_record_id}",
    response_model=Optional[VersionQualityScoreSchema],
)
async def get_latest_quality(
    tenant_slug: str,
    project_id: str,
    version_record_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Optional[VersionQualityScoreSchema]:
    """Latest quality snapshot for a version, or `null` when it's never been
    measured (the UI shows a "Compute quality" CTA in that case)."""
    tenant_id = _tenant_id(auth_data)
    _resolve_version(tenant_id, project_id, version_record_id)
    row = db.get_latest_version_quality_score(version_record_id, tenant_id)
    if not row:
        return None
    return VersionQualityScoreSchema(**dict(row))


@router.post(
    "/{tenant_slug}/{project_id}/{version_record_id}/run",
    response_model=VersionQualityRunResponse,
)
async def run_quality(
    tenant_slug: str,
    project_id: str,
    version_record_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> VersionQualityRunResponse:
    """Compute and persist a fresh snapshot. Runs synchronously; the response
    includes the new snapshot plus the prior one (when present) so callers can
    show a delta without a follow-up GET."""
    tenant_id = _tenant_id(auth_data)
    _resolve_version(tenant_id, project_id, version_record_id)
    actor_id = get_authenticated_user_id(auth_data)
    previous_row = db.get_latest_version_quality_score(version_record_id, tenant_id)

    scores, detail = _compute_quality(version_record_id)
    inserted = db.insert_version_quality_score(
        tenant_id=tenant_id,
        project_id=project_id,
        version_id=version_record_id,
        overall=scores["overall"],
        completeness=scores["completeness"],
        consistency=scores["consistency"],
        descriptions=scores["descriptions"],
        examples=scores["examples"],
        class_count=scores["class_count"],
        property_count=scores["property_count"],
        computed_by=actor_id,
        detail=detail,
    )
    if not inserted:
        raise HTTPException(status_code=500, detail="Failed to persist quality snapshot")

    return VersionQualityRunResponse(
        snapshot=VersionQualityScoreSchema(**dict(inserted)),
        previous=VersionQualityScoreSchema(**dict(previous_row)) if previous_row else None,
    )
