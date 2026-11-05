"""Export history & audit ledger — MFX-46.1 (#4379).

"Who exported what, where, with how much loss?" is answered from ``apiome.export_run_ledger``
(``V360__export_run_ledger_4379.sql``): one row per export job, written when the job reaches a terminal
state (:func:`record_export_run`), kept for the async-job history window (90 days by default) after the
live job is gone.

A row holds the source and revision, the target, the **actor**, the outcome, the headline numbers the
history screen filters on — preserved %, the validation and lint verdicts, the delivery decision — and
the **stored reports** its read-only detail renders (per target: the fidelity envelope, the validation
report, the delivery-gate report). A multi-target job's headline is its weakest target's.

Delivery outcomes are not copied into the ledger: each git, webhook and object-storage delivery already
records its run by ``job_id`` (MFX-38.x), so :func:`deliveries_by_job` reads them at list time and
:func:`delivery_outcome` normalizes each channel's status vocabulary to ``delivered`` / ``failed`` /
``in_progress``.

Everything here is pure except :func:`record_export_run`, which never raises: recording history must not
disturb an export.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

__all__ = [
    "DELIVERY_CHANNELS",
    "ExportRunActor",
    "ExportRunActorsResponse",
    "ExportRunDelivery",
    "ExportRunDetail",
    "ExportRunListResponse",
    "ExportRunSummary",
    "ExportRunTargetReport",
    "actor_from_auth",
    "build_ledger_row",
    "deliveries_by_job",
    "delivery_outcome",
    "record_export_run",
    "run_detail",
    "run_summary",
]

#: The delivery channels a run can have been delivered through (the history's channel filter adds
#: ``none``: never delivered anywhere).
DELIVERY_CHANNELS: Tuple[str, ...] = ("git", "webhook", "object-storage")

#: Worst-first rank of each validation verdict (a multi-target job takes its worst).
_VALIDATION_RANK = {"invalid": 0, "skipped": 1, "not_applicable": 2, "valid": 3}
#: Worst-first rank of each delivery decision.
_DECISION_RANK = {"block": 0, "allow_with_warning": 1, "allow": 2}
#: Worst-first rank of each lint verdict.
_LINT_RANK = {"block": 0, "warn": 1, "pass": 2}
#: Each channel's statuses that mean the artifact reached its destination (or already held it).
_DELIVERED = {
    "git": {"opened", "updated", "unchanged", "up_to_date", "committed"},
    "webhook": {"delivered"},
    "object-storage": {"delivered"},
}


# ===========================================================================
# Building a row
# ===========================================================================


def actor_from_auth(auth_data: Optional[Mapping[str, Any]]) -> Tuple[Optional[str], str]:
    """The user who started a job, and a display label that is never empty.

    Args:
        auth_data: The submitter's authenticated context (``None`` for a job with none, e.g. an
            automatic export with no recorded publisher).

    Returns:
        ``(user_id, label)`` — the authenticated user's id (``None`` for an API key with no user, or no
        context), and their email or name, the API key's name, or ``"Unknown"``.
    """
    if not auth_data:
        return None, "Unknown"
    # The authenticated user only — never the tenant-admin fallback an API key without a creator gets for
    # authorship elsewhere: the history must not attribute an export to someone who did not run it.
    raw = auth_data.get("user_id")
    user_id = str(raw).strip() if raw is not None and str(raw).strip() else None
    label = (
        auth_data.get("user_email")
        or auth_data.get("email")
        or auth_data.get("user_name")
        or auth_data.get("name")
        or (f"API key {auth_data.get('api_key_name')}" if auth_data.get("api_key_name") else None)
        or ("API key" if auth_data.get("auth_method") == "api_key" else None)
        or "Unknown"
    )
    return (str(user_id) if user_id else None), str(label)[:320]


def _worst(values: Iterable[Optional[str]], rank: Mapping[str, int]) -> Optional[str]:
    """The worst of ``values`` by ``rank`` (unknown values rank last), or ``None`` when there are none."""
    present = [v for v in values if v]
    if not present:
        return None
    return min(present, key=lambda v: rank.get(v, len(rank)))


def _value(field: Any) -> Any:
    """An enum's value, or the field itself."""
    return getattr(field, "value", field)


def _lint_verdict(gate: Optional[Mapping[str, Any]]) -> Optional[str]:
    """``block`` / ``warn`` / ``pass`` from a delivery-gate report's lint reasons, or ``None`` with no gate."""
    if not gate:
        return None
    severities = {str(r.get("severity")) for r in gate.get("reasons") or [] if r.get("dimension") == "lint"}
    if "blocking" in severities:
        return "block"
    if "warning" in severities:
        return "warn"
    return "pass"


def _target_reports(result: Optional[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Per target: the fidelity envelope, the validation report and the delivery-gate report."""
    if not result:
        return []
    if result.get("targets"):
        return [
            {
                "target": t.get("target"),
                "fidelity": t.get("fidelity"),
                "validation": t.get("validation"),
                "delivery_gate": t.get("delivery"),
            }
            for t in result["targets"]
        ]
    return [{
        "target": result.get("target"),
        "fidelity": result.get("fidelity"),
        "validation": result.get("validation"),
        "delivery_gate": result.get("delivery"),
    }]


def build_ledger_row(
    *,
    tenant_id: str,
    job_id: str,
    state: str,
    request: Mapping[str, Any],
    result: Optional[Mapping[str, Any]],
    error: Optional[Mapping[str, Any]],
    artifact_name: Optional[str],
    actor: Tuple[Optional[str], str],
    created_at: datetime,
    finished_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    """The ledger row of one finished job (pure).

    Args:
        tenant_id: The owning tenant id.
        job_id: The export job.
        state: Its terminal state (``completed`` / ``failed`` / ``canceled``).
        request: The submitted request (``model_dump(mode="json")`` of ``ExportJobStartRequest``).
        result: The job's ``result`` (JSON), when it completed.
        error: The job's ``error`` (JSON), when it failed.
        artifact_name: The source's name, when the job loaded it.
        actor: ``(user_id, label)`` from :func:`actor_from_auth`.
        created_at: When the job was submitted.
        finished_at: When it ended (now when omitted).

    Returns:
        The columns of ``export_run_ledger``; a multi-target job's headline numbers are its weakest
        target's, and the stored reports keep every target's.
    """
    reports = _target_reports(result)
    summaries = [((r.get("fidelity") or {}).get("summary") or {}) for r in reports]
    rollup = (result or {}).get("fidelity_rollup") or {}
    percents = [s["preserved_percent"] for s in summaries if isinstance(s.get("preserved_percent"), int)]
    if rollup.get("min_preserved_percent") is not None:
        preserved: Optional[int] = int(rollup["min_preserved_percent"])
    else:
        preserved = min(percents) if percents else None
    tier = rollup.get("tier") or next((s.get("tier") for s in summaries if s.get("tier")), None)
    gates = [r.get("delivery_gate") for r in reports if r.get("delivery_gate")]
    target = request.get("target") or ",".join(
        str(t.get("target")) for t in request.get("targets") or [] if t.get("target")
    )
    options = (result or {}).get("options")
    if options is None:
        options = request.get("options")
    return {
        "job_id": job_id,
        "tenant_id": tenant_id,
        "artifact_id": str(request.get("artifact") or (result or {}).get("artifact") or ""),
        "artifact_name": artifact_name,
        "version_record_id": (result or {}).get("version_record_id"),
        "version_label": (result or {}).get("version_label") or request.get("version"),
        "target": target or "",
        "actor_id": actor[0],
        "actor_label": actor[1],
        "state": state,
        "dry_run": bool(request.get("dry_run")),
        "preserved_percent": preserved,
        "fidelity_tier": tier,
        "validation_verdict": _worst(((r.get("validation") or {}).get("verdict") for r in reports),
                                     _VALIDATION_RANK),
        "lint_verdict": _worst((_lint_verdict(g) for g in gates), _LINT_RANK),
        "delivery_decision": _worst((g.get("decision") for g in gates), _DECISION_RANK),
        "error_code": (error or {}).get("code"),
        "error_message": (error or {}).get("message"),
        "options": options,
        "fidelity": [{"target": r["target"], "envelope": r["fidelity"]} for r in reports if r.get("fidelity")]
        or None,
        "validation": [{"target": r["target"], "report": r["validation"]} for r in reports if r.get("validation")]
        or None,
        "delivery_gate": [{"target": r["target"], "report": r["delivery_gate"]} for r in reports
                          if r.get("delivery_gate")] or None,
        "created_at": created_at,
        "finished_at": finished_at or datetime.now(timezone.utc),
    }


def record_export_run(row: Mapping[str, Any]) -> bool:
    """Write a finished job's ledger row once; never raises.

    Args:
        row: The row from :func:`build_ledger_row`.

    Returns:
        True when written; False when already recorded or the store refused it.
    """
    try:
        from .database import db

        return bool(db.insert_export_run(dict(row)))
    except Exception:  # noqa: BLE001 - history is best-effort; an export never fails over it
        logger.warning("Failed to record export job %s in the history ledger", row.get("job_id"), exc_info=True)
        return False


# ===========================================================================
# Reading rows
# ===========================================================================


class ExportRunDelivery(BaseModel):
    """One delivery of an export job (git, webhook or object storage)."""

    model_config = ConfigDict(extra="forbid")

    channel: str = Field(description="`git`, `webhook` or `object-storage`.")
    status: str = Field(description="The channel's own status, e.g. `opened`, `delivered`, `failed`.")
    outcome: str = Field(description="`delivered`, `failed` or `in_progress`, whatever the channel.")
    destination: Optional[str] = Field(default=None, description="The repository, URL or bucket.")
    error_code: Optional[str] = Field(default=None, description="Why a failed delivery failed.")
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class ExportRunSummary(BaseModel):
    """One export run in the history: who exported what, where, with how much loss."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    artifact_id: str = Field(description="The exported artifact (project or catalog item) id.")
    artifact_name: Optional[str] = Field(default=None, description="The source's name, when known.")
    version_record_id: Optional[str] = None
    version_label: Optional[str] = Field(default=None, description="The exported revision's version label.")
    target: str = Field(description="The requested target(s), comma-joined for a multi-target job.")
    actor_id: Optional[str] = Field(default=None, description="The user who started the job.")
    actor_label: str = Field(description="Their email or name (kept after the account is gone).")
    state: str = Field(description="`completed`, `failed` or `canceled`.")
    dry_run: bool = Field(description="True for a fidelity-only dry run (no artifact).")
    preserved_percent: Optional[int] = Field(
        default=None, description="Share of constructs preserved (the weakest target's for a multi-target job)."
    )
    fidelity_tier: Optional[str] = Field(default=None, description="The fidelity tier badge.")
    validation_verdict: Optional[str] = Field(
        default=None, description="`valid`, `invalid`, `skipped` or `not_applicable` (the worst target's)."
    )
    lint_verdict: Optional[str] = Field(default=None, description="`pass`, `warn` or `block` (the worst target's).")
    delivery_decision: Optional[str] = Field(
        default=None, description="The delivery gate: `allow`, `allow_with_warning` or `block` (the worst target's)."
    )
    error_code: Optional[str] = Field(default=None, description="Why a failed job failed.")
    error_message: Optional[str] = None
    options: Optional[Dict[str, Any]] = Field(
        default=None, description="The per-target options the job was submitted with (for a re-run)."
    )
    deliveries: List[ExportRunDelivery] = Field(
        default_factory=list, description="Every delivery of the job's artifact, newest first."
    )
    created_at: datetime
    finished_at: datetime


class ExportRunTargetReport(BaseModel):
    """The stored reports of one target of a run (read-only)."""

    model_config = ConfigDict(extra="forbid")

    target: Optional[str] = None
    fidelity: Optional[Dict[str, Any]] = Field(default=None, description="The fidelity envelope, as it was.")
    validation: Optional[Dict[str, Any]] = Field(default=None, description="The validation report, as it was.")
    delivery_gate: Optional[Dict[str, Any]] = Field(default=None, description="The delivery-gate report, as it was.")


class ExportRunDetail(ExportRunSummary):
    """One run with its stored reports, per target."""

    reports: List[ExportRunTargetReport] = Field(default_factory=list)


class ExportRunListResponse(BaseModel):
    """A page of the tenant's export history."""

    model_config = ConfigDict(extra="forbid")

    runs: List[ExportRunSummary]
    total: int = Field(0, ge=0, description="Runs matching the filters (not just this page).")
    limit: int = Field(50, ge=1, le=200)
    offset: int = Field(0, ge=0)


class ExportRunActor(BaseModel):
    """Someone who started a recorded export (for the history's actor filter)."""

    model_config = ConfigDict(extra="forbid")

    actor_id: str
    actor_label: str


class ExportRunActorsResponse(BaseModel):
    """Everyone who started a recorded export, most recent first."""

    model_config = ConfigDict(extra="forbid")

    actors: List[ExportRunActor]


def delivery_outcome(channel: str, status: str) -> str:
    """``delivered``, ``failed`` or ``in_progress`` for one channel's status.

    Args:
        channel: ``git``, ``webhook`` or ``object-storage``.
        status: That channel's status (``opened``, ``retrying``, ``delivered``…).

    Returns:
        The normalized outcome; anything not delivered or failed is still in progress.
    """
    if status == "failed":
        return "failed"
    if status in _DELIVERED.get(channel, set()):
        return "delivered"
    return "in_progress"


def deliveries_by_job(rows: Sequence[Mapping[str, Any]]) -> Dict[str, List[ExportRunDelivery]]:
    """Group delivery-run rows (``db.list_export_run_deliveries``) by job, keeping their order."""
    grouped: Dict[str, List[ExportRunDelivery]] = {}
    for row in rows:
        channel = str(row.get("channel"))
        status = str(row.get("status"))
        grouped.setdefault(str(row.get("job_id")), []).append(ExportRunDelivery(
            channel=channel,
            status=status,
            outcome=delivery_outcome(channel, status),
            destination=row.get("destination"),
            error_code=row.get("error_code"),
            started_at=row.get("started_at"),
            finished_at=row.get("finished_at"),
        ))
    return grouped


_SUMMARY_FIELDS = tuple(name for name in ExportRunSummary.model_fields if name != "deliveries")


def run_summary(row: Mapping[str, Any], deliveries: Sequence[ExportRunDelivery] = ()) -> ExportRunSummary:
    """A ledger row as its API summary."""
    return ExportRunSummary(**{k: row.get(k) for k in _SUMMARY_FIELDS}, deliveries=list(deliveries))


def run_detail(row: Mapping[str, Any], deliveries: Sequence[ExportRunDelivery] = ()) -> ExportRunDetail:
    """A ledger row with its stored reports regrouped per target."""
    by_target: Dict[Optional[str], Dict[str, Any]] = {}
    order: List[Optional[str]] = []
    for column, key, inner in (("fidelity", "fidelity", "envelope"), ("validation", "validation", "report"),
                               ("delivery_gate", "delivery_gate", "report")):
        for entry in row.get(column) or []:
            target = entry.get("target")
            if target not in by_target:
                by_target[target] = {"target": target}
                order.append(target)
            by_target[target][key] = entry.get(inner)
    summary = run_summary(row, deliveries)
    return ExportRunDetail(**summary.model_dump(), reports=[ExportRunTargetReport(**by_target[t]) for t in order])
