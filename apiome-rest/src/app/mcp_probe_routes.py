"""REST surface for consent-gated, sandboxed MCP dynamic probes (CLX-3.3, #4857).

Four capabilities, mapped to the acceptance criteria:

* ``GET  /v1/mcp/probes/catalog`` — the probe + profile + classification catalog (what a run *can*
  tell you, before you run anything).
* ``POST /v1/mcp/{tenant}/endpoints/{id}/probe-targets`` (+ list, retire) — the **allowlist** (AC2):
  enrolling a target, on the record, as one the operator owns/authorizes and names a dedicated test
  credential for.
* ``POST /v1/mcp/{tenant}/endpoints/{id}/versions/{vid}/probe`` — **run** a profile. The passive
  default is read-only and always available; active profiles pass every gate the engine enforces
  (kill switch, allowlist, consent, isolation, rate/concurrency) and are audited.
* ``GET  /v1/mcp/{tenant}/endpoints/{id}/probe-runs`` — the **audit trail** (AC5).

The bytes-on-the-wire runner is deliberately not shipped in this deployment (the isolation runtime is
an infrastructure decision the ticket defers; mcp-fence/agent-lint are evaluated only after a
threat-model). So an active run first passes every safety gate and records its audit row, and only
then, if no :data:`_PROBE_RUNNER` is registered, returns ``503`` — the gating is real and exercised
even though the sandboxed transport is pluggable. A deployment (or a test) supplies a runner via
:func:`register_probe_runner`.
"""

from __future__ import annotations

import uuid
from typing import Any, Awaitable, Callable, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from .auth import get_authenticated_user_id, validate_authentication, validate_session_credentials
from .config import settings
from .database import db
from .mcp_discovery_engine import reconstruct_surface
from .mcp_probe import (
    CLASSIFICATION_LABELS,
    DEFAULT_PROFILE,
    TRANSPORT_HTTP,
    TRANSPORT_STDIO,
    ConsentError,
    ConsentRecord,
    GovernorPolicy,
    IsolationError,
    IsolationSpec,
    KillSwitchError,
    LimitExceededError,
    ProbeLimits,
    ProbeTransport,
    RateLimitError,
    TenantUsage,
    UnknownProfileError,
    authorize_active_run,
    probe_catalog,
    require_isolation,
    resolve_profile,
    run_active_probes,
    run_passive_probes,
)
from .mcp_probe import PROFILES as PROBE_PROFILES
from .mcp_protocol_transcript import ProtocolTranscript

router = APIRouter(prefix="/v1/mcp", tags=["mcp-probe"])


# =================================================================================================
# Runner registry — the injected boundary to the sandboxed transport.
# =================================================================================================

#: Builds the :class:`ProbeTransport` for a run, given the endpoint row, the validated consent, and
#: the isolation spec (for stdio). ``None`` in a deployment with no probe runtime configured — the
#: default. A test or a runner-enabled deployment registers one with :func:`register_probe_runner`.
ProbeRunnerFactory = Callable[
    [Dict[str, Any], ConsentRecord, Optional[IsolationSpec]], Awaitable[ProbeTransport]
]

_PROBE_RUNNER: Optional[ProbeRunnerFactory] = None


def register_probe_runner(factory: Optional[ProbeRunnerFactory]) -> None:
    """Register (or clear, with ``None``) the factory that builds a run's sandboxed transport.

    Kept out of the request path deliberately: whether a deployment can run active probes at all is a
    property of its infrastructure, not of any one request. With no runner registered, active runs
    return 503 after passing every safety gate.
    """
    global _PROBE_RUNNER
    _PROBE_RUNNER = factory


# =================================================================================================
# Helpers.
# =================================================================================================


def _require_tenant_endpoint(auth_data: Dict[str, Any], endpoint_id: uuid.UUID) -> Dict[str, Any]:
    """Load an endpoint scoped to the caller's token tenant, or raise 404 (mirrors the catalog guard)."""
    tenant_id = str(auth_data["tenant_id"])
    endpoint = db.get_mcp_endpoint(tenant_id, str(endpoint_id))
    if not endpoint:
        raise HTTPException(status_code=404, detail="MCP endpoint not found")
    return endpoint


def _probe_transport_kind(endpoint: Dict[str, Any]) -> str:
    """Map an endpoint's MCP transport to the probe transport axis (stdio vs everything-remote)."""
    return TRANSPORT_STDIO if endpoint.get("transport") == "stdio" else TRANSPORT_HTTP


def _governor_policy() -> GovernorPolicy:
    """Build the governor policy from settings (the kill switch and per-tenant caps)."""
    return GovernorPolicy(
        enabled=bool(settings.mcp_probe_enabled),
        max_concurrent_per_tenant=int(settings.mcp_probe_max_concurrent_per_tenant),
        max_runs_per_hour_per_tenant=int(settings.mcp_probe_max_runs_per_hour_per_tenant),
    )


def _run_limits() -> ProbeLimits:
    """Build the per-run limits from settings."""
    return ProbeLimits(max_requests=int(settings.mcp_probe_max_requests_per_run))


def _load_transcript(version_id: str) -> Optional[ProtocolTranscript]:
    """Reconstruct the stored protocol transcript for a snapshot, or ``None`` when none was captured."""
    row = db.get_mcp_protocol_transcript(version_id)
    if not row or not row.get("transcript"):
        return None
    try:
        return ProtocolTranscript.from_dict(row["transcript"])
    except (ValueError, KeyError):
        return None


# =================================================================================================
# Catalog.
# =================================================================================================


@router.get("/probes/catalog", response_model=None)
async def get_mcp_probe_catalog(
    profile: Optional[str] = Query(
        default=None, description="Restrict the probe list to this profile's probes."
    ),
    auth_data: Dict[str, Any] = Depends(validate_session_credentials),
) -> Dict[str, Any]:
    """Return the probe catalog: every probe, the three profiles, and the classification tiers.

    Registry-level (describes the engine, not any endpoint), authenticated like the other MCP rule
    catalogs. Lets a consumer see, before running anything, which probe belongs to which profile,
    the strongest classification each can reach, and what the three tiers mean.
    """
    _ = auth_data
    try:
        probes = probe_catalog(profile)
    except UnknownProfileError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "profiles": [PROBE_PROFILES[key].as_dict() for key in sorted(PROBE_PROFILES)],
        "classifications": [
            {"value": value, "label": CLASSIFICATION_LABELS[value]}
            for value in CLASSIFICATION_LABELS
        ],
        "probes": probes,
    }


# =================================================================================================
# Allowlist (probe targets).
# =================================================================================================


@router.post(
    "/{tenant_slug}/endpoints/{endpoint_id}/probe-targets",
    response_model=None,
    status_code=201,
)
async def enroll_probe_target(
    tenant_slug: str,
    endpoint_id: uuid.UUID,
    body: Dict[str, Any],
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, Any]:
    """Enrol an endpoint on the active-probe allowlist.

    The operator asserts ownership/authorization (``ownership_declared: true``, required) and may name
    the dedicated test credential (``test_credential_id``) a probe authenticates as. Refuses without
    the ownership assertion — probing a system nobody vouched for is exactly what the allowlist
    exists to prevent. Idempotent per ``(endpoint, transport)``. 404 for a cross-tenant endpoint.
    """
    _ = tenant_slug
    endpoint = _require_tenant_endpoint(auth_data, endpoint_id)
    if not bool(body.get("ownership_declared")):
        raise HTTPException(
            status_code=400,
            detail=(
                "enrolling a probe target requires 'ownership_declared: true' — an assertion that you "
                "own or are authorized to probe this target"
            ),
        )
    transport = _probe_transport_kind(endpoint)
    row = db.enroll_mcp_probe_target(
        tenant_id=str(endpoint["tenant_id"]),
        endpoint_id=str(endpoint_id),
        transport=transport,
        locator=str(endpoint.get("endpoint_url") or ""),
        test_credential_id=body.get("test_credential_id"),
        enrolled_by=get_authenticated_user_id(auth_data),
    )
    if row is None:
        raise HTTPException(status_code=500, detail="failed to enrol probe target")
    return {"target": _target_out(row)}


@router.get("/{tenant_slug}/endpoints/{endpoint_id}/probe-targets", response_model=None)
async def list_probe_targets(
    tenant_slug: str,
    endpoint_id: uuid.UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, Any]:
    """List an endpoint's live allowlist entries. 404 for a cross-tenant endpoint."""
    _ = tenant_slug
    _require_tenant_endpoint(auth_data, endpoint_id)
    rows = db.list_mcp_probe_targets(str(endpoint_id))
    return {"targets": [_target_out(r) for r in rows]}


@router.delete(
    "/{tenant_slug}/endpoints/{endpoint_id}/probe-targets/{target_id}",
    response_model=None,
)
async def retire_probe_target(
    tenant_slug: str,
    endpoint_id: uuid.UUID,
    target_id: uuid.UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, Any]:
    """Retire an allowlist entry (soft; historical audit rows citing it stay interpretable).

    404 for a cross-tenant endpoint or a target id that is not this endpoint's live entry.
    """
    _ = tenant_slug
    _require_tenant_endpoint(auth_data, endpoint_id)
    if not db.retire_mcp_probe_target(str(endpoint_id), str(target_id)):
        raise HTTPException(status_code=404, detail="probe target not found")
    return {"retired": True}


# =================================================================================================
# Run a probe.
# =================================================================================================


@router.post(
    "/{tenant_slug}/endpoints/{endpoint_id}/versions/{version_id}/probe",
    response_model=None,
)
async def run_probe(
    tenant_slug: str,
    endpoint_id: uuid.UUID,
    version_id: uuid.UUID,
    body: Optional[Dict[str, Any]] = None,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, Any]:
    """Run a probe profile against one version snapshot.

    ``profile`` (body) defaults to ``passive``. The passive profile re-reads the captured transcript,
    sends nothing, needs no consent, and is always available (subject to nothing but the snapshot
    existing). Active profiles (``safe-active``, ``payload-fuzzing``) pass, in order: the global kill
    switch and this tenant's concurrency/rate budget, then consent (the target must be allowlisted,
    ownership declared, the run acknowledged, a dedicated identity used, and — for fuzzing — explicitly
    approved), then isolation (a stdio target needs a least-privilege sandbox). Every refusal and
    every completed active run is recorded in the audit trail.

    404 when the endpoint/version is not the caller's; 400 on an unknown profile; 403 when a gate
    refuses; 503 when active probing is requested but this deployment has no probe runner configured.
    """
    _ = tenant_slug
    endpoint = _require_tenant_endpoint(auth_data, endpoint_id)
    version = db.get_mcp_endpoint_version(str(endpoint_id), str(version_id))
    if version is None:
        raise HTTPException(status_code=404, detail="MCP endpoint version not found")

    payload = body or {}
    try:
        profile = resolve_profile(payload.get("profile") or DEFAULT_PROFILE)
    except UnknownProfileError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    items = db.get_mcp_capability_items(str(version_id))
    surface = reconstruct_surface(version, items)

    # --- Passive: read-only, no consent, no audit row (it sends nothing). ---
    if not profile.sends_requests:
        report = run_passive_probes(
            surface, _load_transcript(str(version_id)), target_endpoint_id=str(endpoint_id)
        )
        return report.as_dict()

    # --- Active: gate, audit, run. ---
    return await _run_active(auth_data, endpoint, version, profile.profile_id, surface, payload)


async def _run_active(
    auth_data: Dict[str, Any],
    endpoint: Dict[str, Any],
    version: Dict[str, Any],
    profile_id: str,
    surface: Any,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """Gate, audit, and execute an active probe run. Records a refused row on any gate refusal."""
    profile = resolve_profile(profile_id)
    tenant_id = str(endpoint["tenant_id"])
    endpoint_id = str(endpoint["id"])
    transport_kind = _probe_transport_kind(endpoint)
    target = db.get_mcp_probe_target(endpoint_id, transport_kind)
    locator = str(endpoint.get("endpoint_url") or "")

    # Build the consent record from the allowlist entry + this request's acknowledgements. A missing
    # allowlist entry yields a record with allowlisted=False, which consent.validate refuses — so the
    # "not enrolled" case flows through the same single consent gate as every other missing element.
    consent = ConsentRecord(
        target_endpoint_id=endpoint_id,
        target_locator=locator,
        transport=transport_kind,
        allowlisted=target is not None,
        ownership_declared=bool(target and target.get("ownership_declared")),
        acknowledged_by=str(get_authenticated_user_id(auth_data) or ""),
        acknowledged_at=_now_iso(),
        test_identity=(str(target["test_credential_id"]) if target and target.get("test_credential_id") else None),
        dedicated_credentials=bool(target and target.get("test_credential_id")),
        explicit_approval=bool(payload.get("explicit_approval")),
    )
    limits = _run_limits()
    isolation = (
        IsolationSpec.hardened(egress_allowlist=(locator,) if locator else ())
        if transport_kind == TRANSPORT_STDIO
        else None
    )
    policy = _governor_policy()
    usage_row = db.get_mcp_probe_tenant_usage(tenant_id)
    usage = TenantUsage(
        active_runs=usage_row["active_runs"], runs_last_hour=usage_row["runs_last_hour"]
    )

    # Pre-flight the refusable gates *before* opening an audit row, so a refusal is recorded as a
    # 'refused' run with its reason and no 'running' row is ever left dangling.
    try:
        authorize_active_run(profile, policy, usage)
        consent.validate(profile)
        require_isolation(consent, isolation)
    except (KillSwitchError, RateLimitError) as exc:
        _record_refusal(tenant_id, endpoint_id, version, profile_id, consent, limits, isolation,
                        auth_data, str(exc))
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (ConsentError, IsolationError) as exc:
        _record_refusal(tenant_id, endpoint_id, version, profile_id, consent, limits, isolation,
                        auth_data, str(exc))
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    if _PROBE_RUNNER is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "active MCP probing passed all safety gates but this deployment has no probe runner "
                "configured (the sandboxed transport is an infrastructure component that is not "
                "enabled here); only the read-only passive profile can execute"
            ),
        )

    run_id = db.start_mcp_probe_run(
        tenant_id=tenant_id,
        endpoint_id=endpoint_id,
        version_id=str(version["id"]),
        profile=profile_id,
        target_locator=locator,
        transport=transport_kind,
        consent=consent.as_dict(),
        limits=limits.as_dict(),
        isolation=isolation.as_dict() if isolation is not None else None,
        started_by=get_authenticated_user_id(auth_data),
    )
    try:
        transport = await _PROBE_RUNNER(endpoint, consent, isolation)
        report = await run_active_probes(
            surface,
            transport,
            profile=profile_id,
            consent=consent,
            policy=policy,
            usage=usage,
            limits=limits,
            isolation=isolation,
            probe_run_id=run_id,
        )
    except (KillSwitchError, RateLimitError, ConsentError, IsolationError) as exc:
        # A gate the engine re-checks (belt and braces) refused; record it.
        if run_id:
            db.refuse_mcp_probe_run(run_id, reason=str(exc))
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (LimitExceededError, Exception) as exc:  # noqa: BLE001 - audit any failure, then surface
        if run_id:
            db.fail_mcp_probe_run(run_id, reason=str(exc)[:500])
        raise HTTPException(status_code=502, detail=f"probe run failed: {exc}") from exc

    if run_id:
        classification_counts = report.classification_counts
        db.complete_mcp_probe_run(
            run_id,
            report=report.as_dict(),
            requests_sent=report.requests_sent,
            observed_count=classification_counts.get("observed", 0),
            exploited_count=report.exploited_count,
            report_fingerprint=report.report_fingerprint,
        )
    result = report.as_dict()
    result["run_id"] = run_id
    return result


def _record_refusal(tenant_id, endpoint_id, version, profile_id, consent, limits, isolation,
                    auth_data, reason: str) -> None:
    """Open and immediately refuse an audit row, so a gate-refused attempt is not lost."""
    run_id = db.start_mcp_probe_run(
        tenant_id=tenant_id,
        endpoint_id=endpoint_id,
        version_id=str(version["id"]),
        profile=profile_id,
        target_locator=consent.target_locator,
        transport=consent.transport,
        consent=consent.as_dict(),
        limits=limits.as_dict(),
        isolation=isolation.as_dict() if isolation is not None else None,
        started_by=get_authenticated_user_id(auth_data),
    )
    if run_id:
        db.refuse_mcp_probe_run(run_id, reason=reason)


# =================================================================================================
# Audit trail.
# =================================================================================================


@router.get("/{tenant_slug}/endpoints/{endpoint_id}/probe-runs", response_model=None)
async def list_probe_runs(
    tenant_slug: str,
    endpoint_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, Any]:
    """Return an endpoint's probe-run audit trail, newest first. 404 for a cross-tenant endpoint."""
    _ = tenant_slug
    _require_tenant_endpoint(auth_data, endpoint_id)
    rows = db.list_mcp_probe_runs(str(endpoint_id), limit=limit)
    return {"runs": [_run_out(r) for r in rows]}


# =================================================================================================
# Row serializers.
# =================================================================================================


def _target_out(row: Dict[str, Any]) -> Dict[str, Any]:
    """Serialize an allowlist row for the wire."""
    return {
        "id": str(row["id"]),
        "endpointId": str(row["endpoint_id"]),
        "transport": row["transport"],
        "locator": row["locator"],
        "ownershipDeclared": bool(row["ownership_declared"]),
        "testCredentialId": str(row["test_credential_id"]) if row.get("test_credential_id") else None,
        "enrolledBy": str(row["enrolled_by"]) if row.get("enrolled_by") else None,
        "createdAt": row["created_at"].isoformat() if row.get("created_at") else None,
    }


def _run_out(row: Dict[str, Any]) -> Dict[str, Any]:
    """Serialize a probe-run audit row for the wire."""
    return {
        "id": str(row["id"]),
        "endpointId": str(row["endpoint_id"]),
        "versionId": str(row["version_id"]) if row.get("version_id") else None,
        "profile": row["profile"],
        "targetLocator": row["target_locator"],
        "transport": row["transport"],
        "status": row["status"],
        "refusalReason": row.get("refusal_reason"),
        "requestsSent": row.get("requests_sent", 0),
        "observedCount": row.get("observed_count", 0),
        "exploitedCount": row.get("exploited_count", 0),
        "consent": row.get("consent"),
        "limits": row.get("limits"),
        "isolation": row.get("isolation"),
        "reportFingerprint": row.get("report_fingerprint"),
        "startedAt": row["started_at"].isoformat() if row.get("started_at") else None,
        "completedAt": row["completed_at"].isoformat() if row.get("completed_at") else None,
    }


def _now_iso() -> str:
    """Current UTC time as an ISO-8601 string (the consent acknowledgement timestamp)."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
