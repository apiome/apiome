"""Auto-export on version publish: the rules — MFX-39.4 (#4336).

Downstream consumers drift the moment a new version publishes. An **auto-export subscription** binds an
export preset (MFX-39.3) to a project, so every publish runs the preset's export and delivers it through
the preset's delivery profile (MFX-38.4) — unless the export loses too much. This module is the pure half;
the queue and the sweep are :mod:`app.export_auto_worker`, the routes :mod:`app.export_auto_routes`.

* **The subscription** (:class:`AutoExportSubscriptionCreate`, :class:`AutoExportSubscriptionUpdate`) — a
  project, a preset, ``haltAt`` (``warn`` or ``critical``) and ``approveLoss``.
* **The export** (:func:`build_auto_request`) — the preset applied to the published revision, always with
  ``confirm`` (a severe conversion still produces its artifact, so the loss can be judged and a person can
  release it) and without delivery: the sweep delivers only after the loss check.
* **The loss** (:func:`measure_loss`) — the MFX-2.4 advisory made a gate. Each target's fidelity and
  transcoding guard fold into one severity: ``critical`` for a severe or near-empty conversion, a
  types-only result or any critical construct; ``warn`` for any other loss; ``info`` for none.
* **The decision** (:func:`should_halt`) — halt auto-delivery when the loss reaches ``haltAt`` and the
  subscription has not pre-approved it (``approveLoss``).
* **The notice** (:func:`halt_notice`) — the inbox sentence and deep link a halted or failed run sends.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Mapping, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field

from .export_job_engine import ExportJobResult, ExportJobStartRequest
from .export_presets import apply_preset

__all__ = [
    "HALT_LEVELS",
    "RUN_STATUSES",
    "SEVERITIES",
    "AutoExportSubscriptionCreate",
    "AutoExportSubscriptionUpdate",
    "build_auto_request",
    "halt_notice",
    "measure_loss",
    "severity_rank",
    "should_halt",
]

#: The loss vocabulary (MFX-2.4 ``LossinessSeverity``), mildest first.
SEVERITIES = ("info", "warn", "critical")
#: What a subscription may halt at.
HALT_LEVELS = ("warn", "critical")
#: A run's lifecycle: queued, running, then one terminal outcome.
RUN_STATUSES = ("pending", "running", "delivered", "exported", "halted", "delivery_failed", "failed")
#: The terminal statuses.
TERMINAL_STATUSES = frozenset(RUN_STATUSES[2:])

#: Transcode bands (MFX-3.3) that are a critical loss on their own.
_CRITICAL_VERDICTS = frozenset({"severe", "near-empty"})


class AutoExportSubscriptionCreate(BaseModel):
    """Subscribe a preset to a project's publishes: ``POST /v1/export/{tenant}/auto-exports``."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    project_id: str = Field(alias="projectId", description="The project whose publishes trigger the export.")
    preset: str = Field(description="The export preset (MFX-39.3), by id or name.")
    halt_at: Literal["warn", "critical"] = Field(
        default="critical", alias="haltAt",
        description="Halt auto-delivery when the export's loss reaches this severity: `critical` (default) "
        "for a severe or near-empty conversion, a types-only result or any critical construct; `warn` for "
        "any loss at all.")
    approve_loss: bool = Field(
        default=False, alias="approveLoss",
        description="Pre-approve the loss: deliver even when it reaches `haltAt`. Recorded on every run.")
    active: bool = Field(default=True, description="Whether publishes trigger it.")


class AutoExportSubscriptionUpdate(BaseModel):
    """A change to a subscription: ``PATCH /v1/export/{tenant}/auto-exports/{id}``."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    halt_at: Optional[Literal["warn", "critical"]] = Field(default=None, alias="haltAt")
    approve_loss: Optional[bool] = Field(default=None, alias="approveLoss")
    active: Optional[bool] = None


def severity_rank(severity: Optional[str]) -> int:
    """A severity's place in :data:`SEVERITIES` (``-1`` when unknown)."""
    return SEVERITIES.index(severity) if severity in SEVERITIES else -1


def _target_loss(label: str, fidelity: Any, guard: Any) -> Tuple[str, List[str]]:
    """One target's loss severity and the reasons for it."""
    reasons: List[str] = []
    severity = "info"
    tier = getattr(getattr(fidelity, "summary", None), "tier", None)
    tier = getattr(tier, "value", tier)
    verdict = getattr(guard, "verdict", None)
    verdict = getattr(verdict, "value", verdict)
    critical = int(getattr(guard, "critical_constructs", 0) or 0)
    preserved = getattr(guard, "preserved_percent", None)
    if verdict in _CRITICAL_VERDICTS:
        severity = "critical"
        reasons.append(f"{label}: a {verdict} conversion"
                       + (f" ({preserved}% preserved)" if preserved is not None else ""))
    if critical > 0:
        severity = "critical"
        reasons.append(f"{label}: {critical} construct{'s' if critical != 1 else ''} lost at critical severity")
    if tier == "types-only":
        severity = "critical"
        reasons.append(f"{label}: only the types survive (types-only)")
    if severity != "critical" and (tier == "lossy" or verdict == "lossy"):
        severity = "warn"
        reasons.append(f"{label}: lossy" + (f" ({preserved}% preserved)" if preserved is not None else ""))
    return severity, reasons


def measure_loss(result: ExportJobResult) -> Tuple[str, List[str]]:
    """The worst loss across an export's targets, and why.

    Args:
        result: A completed export job's result — one target (``fidelity`` / ``guard``) or several
            (``targets[]``).

    Returns:
        ``(severity, reasons)`` — ``info`` / ``warn`` / ``critical`` and one line per contributing target.
    """
    pairs: List[Tuple[str, Any, Any]] = []
    if result.targets:
        pairs = [(t.target, t.fidelity, t.guard) for t in result.targets]
    elif result.fidelity is not None or result.guard is not None:
        pairs = [(result.target or "export", result.fidelity, result.guard)]
    worst, reasons = "info", []
    for label, fidelity, guard in pairs:
        severity, why = _target_loss(label, fidelity, guard)
        reasons.extend(why)
        if severity_rank(severity) > severity_rank(worst):
            worst = severity
    return worst, reasons


def should_halt(severity: str, halt_at: str, approve_loss: bool) -> bool:
    """Whether auto-delivery stops: the loss reached ``halt_at`` and was not pre-approved."""
    return not approve_loss and severity_rank(severity) >= severity_rank(halt_at)


def build_auto_request(project_id: str, version_record_id: str,
                       preset: Mapping[str, Any]) -> Tuple[ExportJobStartRequest, List[str]]:
    """The export job a publish runs for a subscription, and the profiles to deliver it with.

    Args:
        project_id: The published project.
        version_record_id: The published revision.
        preset: The stored preset row.

    Returns:
        ``(request, delivery_profile_ids)`` — the request has ``confirm`` and no delivery profiles.

    Raises:
        app.export_presets.ExportPresetRequestError: When the preset's targets no longer validate.
    """
    expanded = apply_preset(
        ExportJobStartRequest(artifact=project_id, version=version_record_id, preset=str(preset.get("id")),
                              confirm=True),
        preset,
    )
    profiles = list(expanded.delivery_profiles or [])
    return expanded.model_copy(update={"delivery_profiles": None}), profiles


def halt_notice(run: Mapping[str, Any], *, project_name: Optional[str] = None,
                version_label: Optional[str] = None) -> Dict[str, Any]:
    """The inbox payload for a halted or failed auto-export.

    Args:
        run: The run row (``status``, ``preset_name``, ``loss_severity``, ``loss_reasons``, ``error_*``, ``id``).
        project_name: The project's name, when known.
        version_label: The published version's label, when known.

    Returns:
        ``{summary, link, …}`` — the sentence the inbox shows and the Presets tab it links to.
    """
    preset = run.get("preset_name") or "an export preset"
    what = " ".join(part for part in (project_name, version_label) if part) or "the new version"
    if run.get("status") == "halted":
        reasons: Sequence[str] = run.get("loss_reasons") or []
        summary = (f"Auto-export {preset!r} of {what} was not delivered: the export's loss is "
                   f"{run.get('loss_severity')}" + (f" — {reasons[0]}" if reasons else "")
                   + ". Release it from the Presets tab, or fix the source.")
    else:
        summary = (f"Auto-export {preset!r} of {what} failed: "
                   f"{run.get('error_message') or run.get('error_code') or 'see the run'}")
    return {
        "summary": summary[:500],
        "link": "/ade/dashboard/export/studio?tab=presets",
        "run_id": str(run.get("id") or ""),
        "status": run.get("status"),
        "preset_name": run.get("preset_name"),
        "loss_severity": run.get("loss_severity"),
        "project_name": project_name,
        "version_label": version_label,
    }
