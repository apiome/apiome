"""Export presets: the rules — MFX-39.3 (#4335).

An export is a target list, each target's emit options (MFX-1.4) and, since MFX-38.4, where the result
goes. A **preset** saves that combination once per workspace, by name, so a nightly sync or a release
export is applied rather than re-entered — from Export studio, the CLI (``apiome export --preset
nightly-sync``) or the job submit (``"preset": "nightly-sync"``). This module is the pure half:

* **The request** (:class:`ExportPresetCreate`, :class:`ExportPresetUpdate`, :func:`normalize_create`,
  :func:`normalize_update`) — a name, a description, 1–16 targets and an optional delivery profile.
* **The targets** (:func:`validate_targets`) — every target resolves, its options validate against its
  emitter's schema (:func:`app.export_service.resolve_emit_options`), and no two land in the same bundle
  directory — the rules a multi-target job applies, checked when the preset is stored *and* when applied.
* **Applying** (:func:`apply_preset`) — a job request naming a preset becomes the request it stands for:
  ``target`` + ``options`` for one target, ``targets`` for several, the preset's delivery profile first
  among ``delivery_profiles``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field

from .export_delivery_profiles import name_problems, normalize_description
from .export_job_engine import (
    MAX_EXPORT_DELIVERY_PROFILES,
    MAX_EXPORT_TARGETS,
    ExportJobStartRequest,
    target_directory,
)
from .export_service import ExportError, resolve_emit_format, resolve_emit_options

__all__ = [
    "ExportPresetCreate",
    "ExportPresetRequestError",
    "ExportPresetUpdate",
    "NormalizedPreset",
    "PresetTarget",
    "apply_preset",
    "normalize_create",
    "normalize_update",
    "validate_targets",
]


class ExportPresetRequestError(ValueError):
    """A preset that cannot be stored or applied.

    Attributes:
        errors: One message per problem, so a form can mark every bad field at once.
    """

    def __init__(self, *errors: str) -> None:
        self.errors: List[str] = [str(error) for error in errors if error]
        super().__init__("; ".join(self.errors) or "invalid export preset")


class PresetTarget(BaseModel):
    """One target of a preset, with its emit options."""

    model_config = ConfigDict(extra="forbid")

    target: str = Field(description="Target emitter key (`openapi`) or format key (`openapi-3.1`).")
    options: Optional[Dict[str, Any]] = Field(
        default=None, description="Emit options for this target (MFX-1.4), validated against its schema; "
        "null or empty applies its defaults.")


class ExportPresetCreate(BaseModel):
    """A new preset: ``POST /v1/export/{tenant}/presets``."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    name: str = Field(description="A name unique in the workspace (`nightly-sync`), up to 120 characters.")
    description: Optional[str] = Field(default=None, description="What the preset is for.")
    targets: List[PresetTarget] = Field(
        min_length=1, max_length=MAX_EXPORT_TARGETS,
        description=f"The targets, in order: one is a single-target export, 2–{MAX_EXPORT_TARGETS} a "
        "multi-target export with one directory per target.")
    delivery_profile_id: Optional[str] = Field(
        default=None, alias="deliveryProfileId",
        description="A delivery profile (MFX-38.4) the export is delivered with as soon as it completes.")


class ExportPresetUpdate(BaseModel):
    """A change to a preset: ``PATCH /v1/export/{tenant}/presets/{id}``. Omitted fields keep their value."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    name: Optional[str] = Field(default=None, description="A new name.")
    description: Optional[str] = Field(default=None, description="A new description; `\"\"` clears it.")
    targets: Optional[List[PresetTarget]] = Field(
        default=None, min_length=1, max_length=MAX_EXPORT_TARGETS, description="A new target list (replaces it).")
    delivery_profile_id: Optional[str] = Field(
        default=None, alias="deliveryProfileId",
        description="A new delivery profile; `null` removes delivery from the preset.")


@dataclass(frozen=True)
class NormalizedPreset:
    """A validated preset.

    Attributes:
        name: The trimmed name.
        description: The trimmed description, or ``None``.
        targets: ``[{target, options}]`` — each target trimmed, options as given (``{}`` when none).
        delivery_profile_id: The delivery profile, or ``None``.
    """

    name: str
    description: Optional[str]
    targets: List[Dict[str, Any]]
    delivery_profile_id: Optional[str]


def validate_targets(targets: List[Mapping[str, Any]]) -> List[str]:
    """Check a preset's targets as a multi-target job would.

    Every target must resolve, its options must validate against its emitter's schema (MFX-1.4), and
    no two may resolve to the same format (each gets its own bundle directory).

    Args:
        targets: ``[{target, options}]``.

    Returns:
        One message per problem, each naming its position (``targets[1] (protobuf): …``); empty when
        every target is valid.
    """
    problems: List[str] = []
    seen: Dict[str, str] = {}
    for index, entry in enumerate(targets):
        target = str(entry.get("target") or "").strip()
        where = f"targets[{index}]" + (f" ({target})" if target else "")
        if not target:
            problems.append(f"{where}: target is required")
            continue
        try:
            resolve_emit_options(target, entry.get("options") or None)
            directory = target_directory(resolve_emit_format(target))
        except ExportError as exc:
            problems.append(f"{where}: {exc}")
            continue
        if directory in seen:
            problems.append(f"{where}: resolves to the same format as {seen[directory]!r}; each target must "
                            "be a distinct format")
        else:
            seen[directory] = target
    return problems


def _targets(entries: List[PresetTarget]) -> List[Dict[str, Any]]:
    return [{"target": entry.target.strip(), "options": dict(entry.options or {})} for entry in entries]


def normalize_create(request: ExportPresetCreate) -> NormalizedPreset:
    """Validate a new preset.

    Raises:
        ExportPresetRequestError: For a bad name or description, or a target the export would refuse.
    """
    problems: List[str] = []
    name = (request.name or "").strip()
    problems.extend(name_problems(name))
    description = normalize_description(request.description, problems)
    targets = _targets(request.targets)
    problems.extend(validate_targets(targets))
    if problems:
        raise ExportPresetRequestError(*problems)
    profile = (request.delivery_profile_id or "").strip() or None
    return NormalizedPreset(name=name, description=description, targets=targets, delivery_profile_id=profile)


def normalize_update(request: ExportPresetUpdate, existing: Mapping[str, Any]) -> NormalizedPreset:
    """Validate a change to a stored preset, filling what it leaves out from the preset.

    ``deliveryProfileId`` sent as ``null`` removes delivery; left out, it is kept.

    Raises:
        ExportPresetRequestError: For a bad name or description, or a target the export would refuse.
    """
    problems: List[str] = []
    name = (request.name if request.name is not None else str(existing.get("name") or "")).strip()
    problems.extend(name_problems(name))
    description = (normalize_description(request.description, problems) if request.description is not None
                   else existing.get("description"))
    if request.targets is not None:
        targets = _targets(request.targets)
        problems.extend(validate_targets(targets))
    else:
        targets = [dict(entry) for entry in existing.get("targets") or []]
    if "delivery_profile_id" in request.model_fields_set:
        profile = (request.delivery_profile_id or "").strip() or None
    else:
        profile = existing.get("delivery_profile_id")
    if problems:
        raise ExportPresetRequestError(*problems)
    return NormalizedPreset(name=name, description=description, targets=targets, delivery_profile_id=profile)


def apply_preset(request: ExportJobStartRequest, preset: Mapping[str, Any]) -> ExportJobStartRequest:
    """The job request a preset stands for.

    The preset's targets replace the request's (which may not name any): one target becomes ``target``
    with its ``options``, several become ``targets``. The preset's delivery profile goes first among
    ``delivery_profiles``, ahead of any the request names. Everything else — the source, ``version``,
    ``items``, ``overlays``, ``confirm``, ``dry_run`` — is the request's own. The preset's targets are
    validated again, so a preset an emitter's schema has since outgrown is refused rather than guessed at.

    Args:
        request: The submitted request, naming ``preset``.
        preset: The stored preset row (``targets``, ``delivery_profile_id``).

    Returns:
        The expanded request, without ``preset``.

    Raises:
        ExportPresetRequestError: When the preset's targets no longer validate, or the delivery profiles
            would exceed the job's limit.
    """
    targets = [dict(entry) for entry in preset.get("targets") or []]
    problems = validate_targets(targets) if targets else ["the preset has no targets"]
    if problems:
        raise ExportPresetRequestError(*(f"preset {preset.get('name')!r}: {problem}" for problem in problems))
    body = request.model_dump(exclude={"preset"}, exclude_none=True)
    for key in ("target", "targets", "options"):
        body.pop(key, None)
    if len(targets) == 1:
        body["target"] = targets[0]["target"]
        if targets[0].get("options"):
            body["options"] = targets[0]["options"]
    else:
        body["targets"] = [{"target": t["target"], **({"options": t["options"]} if t.get("options") else {})}
                           for t in targets]
    profiles: List[str] = []
    for profile in [preset.get("delivery_profile_id"), *(request.delivery_profiles or [])]:
        if profile and str(profile) not in profiles:
            profiles.append(str(profile))
    if profiles and not request.dry_run:
        if len(profiles) > MAX_EXPORT_DELIVERY_PROFILES:
            raise ExportPresetRequestError(
                f"the preset's delivery profile and 'delivery_profiles' together name more than "
                f"{MAX_EXPORT_DELIVERY_PROFILES} profiles")
        body["delivery_profiles"] = profiles
    else:
        body.pop("delivery_profiles", None)
    return ExportJobStartRequest.model_validate(body)
