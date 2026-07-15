"""REST surface for MCP trust baselines, drift, and shadowing detection (CLX-3.4, #4858).

Maps directly to the acceptance criteria:

* ``POST /v1/mcp/{tenant}/endpoints/{id}/trust-baseline`` — **approve a baseline** (AC2). An
  administrator pins the trust manifest of an approved snapshot, on the record, *with a rationale*.
  The approval writes a policy event to the governance audit and supersedes the prior baseline.
* ``GET  /v1/mcp/{tenant}/endpoints/{id}/trust-baseline`` — the active baseline and approval history.
* ``GET  /v1/mcp/{tenant}/endpoints/{id}/trust-drift`` — **diff the current snapshot against the
  approved baseline** (AC1/AC4). Every material surface/source change is classified (normal change /
  quality regression / security regression / coverage loss) and carries an old→new evidence link; the
  gate reflects the baseline's configured risk deltas; with ``?notify=true`` a regression fans out an
  alert over the push-webhook channel (gated by the notification kill switch).
* ``GET  /v1/mcp/{tenant}/data-quality/shadowing`` — **duplicate/shadowed tool names across the
  enabled host scope** (AC3), the cross-endpoint sibling of the per-server surface diff.

The manifest reuses existing evidence (AC5): the capability/schema portion is the endpoint version's
``surface_fingerprint``, the source portion is ``mcp_endpoint_sources`` / ``mcp_source_sboms`` — this
module composes and diffs them, it does not re-discover anything.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from .auth import get_authenticated_user_id, validate_authentication
from .config import settings
from .database import db
from .mcp_discovery_engine import reconstruct_surface
from .mcp_trust_manifest import (
    DEFAULT_GATING_CATEGORIES,
    DRIFT_CATEGORIES,
    GATE_BLOCKED,
    TrustManifest,
    build_trust_manifest,
    diff_trust_manifests,
    shadow_report,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/mcp", tags=["mcp-trust-drift"])

#: The push-webhook event type a drift alert is delivered under.
EVENT_TYPE_TRUST_DRIFT = "mcp.trust.drift"

#: The governance-audit verb recorded when a baseline is approved (AC2 policy event).
ACTION_BASELINE_APPROVE = "mcp.trust_baseline.approve"


# =================================================================================================
# Helpers.
# =================================================================================================


def _require_tenant_endpoint(auth_data: Dict[str, Any], endpoint_id: uuid.UUID) -> Dict[str, Any]:
    """Load an endpoint scoped to the caller's token tenant, or raise 404 (mirrors the probe guard)."""
    tenant_id = str(auth_data["tenant_id"])
    endpoint = db.get_mcp_endpoint(tenant_id, str(endpoint_id))
    if not endpoint:
        raise HTTPException(status_code=404, detail="MCP endpoint not found")
    return endpoint


def _sbom_fingerprints(source_rows: List[Dict[str, Any]]) -> Dict[str, Optional[str]]:
    """Map each source id to its latest SBOM fingerprint (``None`` when a source has no inventory)."""
    fingerprints: Dict[str, Optional[str]] = {}
    for source in source_rows:
        source_id = str(source.get("id"))
        sbom = db.get_latest_mcp_source_sbom(source_id)
        fingerprints[source_id] = sbom.get("sbom_fingerprint") if sbom else None
    return fingerprints


def _manifest_for_version(
    endpoint: Dict[str, Any], version_row: Dict[str, Any]
) -> TrustManifest:
    """Compose the trust manifest for a specific version snapshot of an endpoint.

    Source facts are endpoint-level (not version-level), so the endpoint's current live source links
    are used for every version — the manifest pins the surface/identity/permissions of the chosen
    snapshot alongside the endpoint's current supply-chain state.
    """
    capability_rows = db.get_mcp_capability_items(str(version_row["id"]))
    source_rows = db.list_mcp_endpoint_sources(str(endpoint["id"]))
    return build_trust_manifest(
        endpoint_row=endpoint,
        version_row=version_row,
        capability_rows=capability_rows,
        source_rows=source_rows,
        sbom_fingerprints=_sbom_fingerprints(source_rows),
    )


def _version_ref(version_row: Dict[str, Any]) -> Dict[str, Any]:
    """Evidence reference for a snapshot: version id, human tag, seq, discovery time."""
    discovered = version_row.get("discovered_at")
    return {
        "version_id": str(version_row["id"]),
        "version_tag": version_row.get("version_tag"),
        "version_seq": version_row.get("version_seq"),
        "surface_fingerprint": version_row.get("surface_fingerprint"),
        "discovered_at": discovered.isoformat() if discovered else None,
    }


def _baseline_ref(baseline_row: Dict[str, Any]) -> Dict[str, Any]:
    """Evidence reference for the approved baseline side of a drift diff."""
    created = baseline_row.get("created_at")
    return {
        "baseline_id": str(baseline_row["id"]),
        "version_id": str(baseline_row["version_id"]),
        "manifest_fingerprint": baseline_row.get("manifest_fingerprint"),
        "approved_at": created.isoformat() if created else None,
        "approved_by": str(baseline_row["approved_by"]) if baseline_row.get("approved_by") else None,
    }


def _baseline_out(row: Dict[str, Any]) -> Dict[str, Any]:
    """Serialize a baseline row to the camelCase wire shape."""
    superseded = row.get("superseded_at")
    created = row.get("created_at")
    updated = row.get("updated_at")
    return {
        "id": str(row["id"]),
        "endpointId": str(row["endpoint_id"]),
        "versionId": str(row["version_id"]),
        "manifestFingerprint": row.get("manifest_fingerprint"),
        "manifest": row.get("manifest") or {},
        "rationale": row.get("rationale"),
        "gatingCategories": row.get("gating_categories") or [],
        "approvedBy": str(row["approved_by"]) if row.get("approved_by") else None,
        "supersededAt": superseded.isoformat() if superseded else None,
        "createdAt": created.isoformat() if created else None,
        "updatedAt": updated.isoformat() if updated else None,
    }


def _drift_notification_payload(
    endpoint: Dict[str, Any], report: Dict[str, Any]
) -> Dict[str, Any]:
    """Build the camelCase drift-alert payload delivered to push-webhook subscribers."""
    return {
        "event": EVENT_TYPE_TRUST_DRIFT,
        "endpointId": str(endpoint["id"]),
        "endpointName": endpoint.get("name"),
        "endpointSlug": endpoint.get("slug"),
        "alertSeverity": report.get("alert_severity"),
        "gate": report.get("gate"),
        "categoryCounts": report.get("category_counts"),
        "baselineFingerprint": report.get("baseline_fingerprint"),
        "currentFingerprint": report.get("current_fingerprint"),
        "changeCount": len(report.get("changes") or []),
    }


def notify_trust_drift(
    *, tenant_id: str, endpoint: Dict[str, Any], report: Dict[str, Any]
) -> List[str]:
    """Fan a drift alert out over the push-webhook channel; best-effort, returns enqueued ids.

    Silent when the notification kill switch is off. Every subscription failure is logged and
    swallowed so a delivery problem can never fail the drift read.
    """
    if not settings.mcp_trust_drift_notify_enabled:
        return []
    payload = _drift_notification_payload(endpoint, report)
    enqueued: List[str] = []
    try:
        subscription_ids = db.list_active_push_webhook_subscription_ids(tenant_id)
    except Exception:  # pragma: no cover - defensive
        logger.exception("trust-drift: failed to list push-webhook subscriptions")
        return []
    for subscription_id in subscription_ids:
        try:
            delivery = db.enqueue_push_webhook_delivery(
                tenant_id, subscription_id, EVENT_TYPE_TRUST_DRIFT, payload
            )
            enqueued.append(str(delivery["id"]))
        except Exception:
            logger.exception(
                "trust-drift: failed to enqueue delivery for subscription %s", subscription_id
            )
    return enqueued


# =================================================================================================
# Routes.
# =================================================================================================


@router.post(
    "/{tenant_slug}/endpoints/{endpoint_id}/trust-baseline",
    response_model=None,
    status_code=201,
)
async def approve_trust_baseline(
    tenant_slug: str,
    endpoint_id: uuid.UUID,
    body: Dict[str, Any],
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, Any]:
    """Approve a new trust baseline for an endpoint (AC2).

    Body: ``version_id`` (optional; defaults to the latest snapshot), ``rationale`` (required,
    non-blank), and ``gating_categories`` (optional list of drift categories that block; defaults to
    security_regression + coverage_loss). Composes the approved snapshot's trust manifest, supersedes
    the prior baseline, and writes a policy event to the governance audit.
    """
    _ = tenant_slug
    endpoint = _require_tenant_endpoint(auth_data, endpoint_id)
    tenant_id = str(endpoint["tenant_id"])

    rationale = str(body.get("rationale") or "").strip()
    if not rationale:
        raise HTTPException(status_code=400, detail="A rationale is required to approve a baseline.")

    gating = body.get("gating_categories")
    if gating is None:
        gating_categories = list(DEFAULT_GATING_CATEGORIES)
    else:
        if not isinstance(gating, list) or not all(isinstance(g, str) for g in gating):
            raise HTTPException(status_code=400, detail="gating_categories must be a list of strings.")
        unknown = [g for g in gating if g not in DRIFT_CATEGORIES]
        if unknown:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown drift categories: {', '.join(sorted(unknown))}.",
            )
        gating_categories = list(gating)

    raw_version = body.get("version_id")
    if raw_version:
        version_row = db.get_mcp_endpoint_version(str(endpoint_id), str(raw_version))
        if not version_row:
            raise HTTPException(status_code=404, detail="Version snapshot not found for this endpoint.")
    else:
        version_row = db.get_latest_mcp_endpoint_version(str(endpoint_id))
        if not version_row:
            raise HTTPException(
                status_code=409,
                detail="Endpoint has no discovered snapshot to approve as a baseline.",
            )

    manifest = _manifest_for_version(endpoint, version_row)
    envelope = manifest.as_dict()

    row = db.approve_mcp_trust_baseline(
        tenant_id=tenant_id,
        endpoint_id=str(endpoint_id),
        version_id=str(version_row["id"]),
        manifest_fingerprint=envelope["fingerprint"],
        manifest=envelope,
        rationale=rationale,
        gating_categories=gating_categories,
        approved_by=get_authenticated_user_id(auth_data),
    )
    if not row:
        raise HTTPException(status_code=500, detail="Failed to record the trust baseline.")

    # AC2: the approval is also a governance policy event.
    db.insert_registry_audit(
        tenant_id,
        ACTION_BASELINE_APPROVE,
        "success",
        actor_id=get_authenticated_user_id(auth_data),
        detail={
            "endpoint_id": str(endpoint_id),
            "version_id": str(version_row["id"]),
            "manifest_fingerprint": envelope["fingerprint"],
            "gating_categories": gating_categories,
            "rationale": rationale,
        },
    )
    return {"baseline": _baseline_out(row)}


@router.get(
    "/{tenant_slug}/endpoints/{endpoint_id}/trust-baseline",
    response_model=None,
)
async def get_trust_baseline(
    tenant_slug: str,
    endpoint_id: uuid.UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, Any]:
    """Return the endpoint's active trust baseline and its approval history."""
    _ = tenant_slug
    _require_tenant_endpoint(auth_data, endpoint_id)
    active = db.get_active_mcp_trust_baseline(str(endpoint_id))
    history = db.list_mcp_trust_baselines(str(endpoint_id))
    return {
        "baseline": _baseline_out(active) if active else None,
        "history": [_baseline_out(row) for row in history],
    }


@router.get(
    "/{tenant_slug}/endpoints/{endpoint_id}/trust-drift",
    response_model=None,
)
async def get_trust_drift(
    tenant_slug: str,
    endpoint_id: uuid.UUID,
    notify: bool = Query(False, description="Fan out a push-webhook alert when a regression is found."),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, Any]:
    """Diff the current snapshot against the approved baseline and classify the drift (AC1/AC4).

    Requires an approved baseline (404 otherwise) and a current discovered snapshot (409 otherwise).
    The response carries every classified change with old→new evidence, the drift gate over the
    baseline's configured risk deltas, and — when ``notify=true`` and the notification kill switch is
    on — the ids of any alerts fanned out.
    """
    _ = tenant_slug
    endpoint = _require_tenant_endpoint(auth_data, endpoint_id)
    tenant_id = str(endpoint["tenant_id"])

    baseline = db.get_active_mcp_trust_baseline(str(endpoint_id))
    if not baseline:
        raise HTTPException(status_code=404, detail="No approved trust baseline for this endpoint.")

    current_version = db.get_latest_mcp_endpoint_version(str(endpoint_id))
    if not current_version:
        raise HTTPException(status_code=409, detail="Endpoint has no discovered snapshot to diff.")

    baseline_version = db.get_mcp_endpoint_version(str(endpoint_id), str(baseline["version_id"]))
    if not baseline_version:
        raise HTTPException(
            status_code=409,
            detail="The approved baseline's snapshot is no longer available.",
        )

    baseline_surface = reconstruct_surface(
        baseline_version, db.get_mcp_capability_items(str(baseline["version_id"]))
    )
    current_manifest = _manifest_for_version(endpoint, current_version)
    current_surface = reconstruct_surface(
        current_version, db.get_mcp_capability_items(str(current_version["id"]))
    )

    gating = baseline.get("gating_categories") or list(DEFAULT_GATING_CATEGORIES)
    drift = diff_trust_manifests(
        baseline_manifest=baseline.get("manifest") or {},
        baseline_surface=baseline_surface,
        baseline_ref=_baseline_ref(baseline),
        current_manifest=current_manifest,
        current_surface=current_surface,
        current_ref=_version_ref(current_version),
        gating_categories=gating,
    )
    report = drift.as_dict()
    # The gate blocks only when enforcement is enabled; otherwise it is advisory (still reported).
    report["gate"]["enforced"] = bool(
        settings.mcp_trust_drift_gate_enabled and report["gate"]["status"] == GATE_BLOCKED
    )

    notified: List[str] = []
    if notify and drift.has_regression:
        notified = notify_trust_drift(tenant_id=tenant_id, endpoint=endpoint, report=report)

    return {"drift": report, "notified": notified}


@router.get(
    "/{tenant_slug}/data-quality/shadowing",
    response_model=None,
)
async def get_shadowing_report(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, Any]:
    """Report tool/resource/prompt names shadowed across the tenant's enabled host scope (AC3)."""
    _ = tenant_slug
    tenant_id = str(auth_data["tenant_id"])
    rows = db.list_mcp_enabled_capability_names(tenant_id)
    return shadow_report(rows)
