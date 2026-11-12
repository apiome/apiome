"""Advanced component governance and lifecycle — DCW-3.4 (private-suite#2364).

A pure module (no storage, no HTTP) behind the governance surface of the DCW-3.1 operational
component library (:mod:`app.component_library`):

* **Approval policy.** Ordered approval *stages*, configured on the governing style guide next to
  the COL-2.3 version approval policy (:mod:`app.approval_policy`) and resolved through the same
  GOV-1.4 guide chain. Each stage reuses the COL-2.3 semantics — a number of approvals and an
  optional role slug at least one of them must come from — and decisions use the COL-2.1
  vocabulary (:mod:`app.review_lifecycle`). Stages are sequential: a stage collects decisions only
  once every earlier stage is satisfied. No stages means no gate, which is how every tenant
  behaved before DCW-3.4.
* **Stale approvals.** A decision judges one payload digest. Editing a draft revision changes its
  digest, so decisions given to the earlier payload stop counting (COL-2.1's ``spec_changed``).
* **Scheduled deprecation.** A sunset date (no earlier than the policy's notice window), an
  optional replacement revision, and migration guidance. Deprecation is metadata: the published
  revision itself is never modified.
* **Bulk upgrade planning.** Which live pins a target revision can replace. Published project
  versions are immutable, so their pins are reported and skipped, never rewritten. The plan's
  confirmation token binds an execute call to the exact plan that was previewed.
* **Audit export.** One flat row per ledger entry — actor, policy, old/new revision, affected
  projects, decision, and timestamp — as JSON or CSV.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .approval_policy import (
    MAX_REQUIRED_APPROVALS,
    normalize_required_approvals,
    normalize_required_reviewer_role,
)
from .review_lifecycle import DECISION_APPROVE, DECISION_REQUEST_CHANGES, RECORDABLE_DECISIONS

__all__ = [
    "AUDIT_EXPORT_COLUMNS",
    "ComponentApprovalAssessment",
    "ComponentApprovalStage",
    "ComponentGovernancePolicy",
    "DEPRECATION_SCHEDULED",
    "DEPRECATION_SUNSET",
    "MAX_APPROVAL_STAGES",
    "MAX_DEPRECATION_NOTICE_DAYS",
    "MAX_MIGRATION_GUIDE_LENGTH",
    "MAX_NOTE_LENGTH",
    "MAX_STAGE_NAME_LENGTH",
    "RECORDABLE_DECISIONS",
    "STAGE_CHANGES_REQUESTED",
    "STAGE_CURRENT",
    "STAGE_SATISFIED",
    "STAGE_WAITING",
    "STATUS_BLOCKED",
    "STATUS_DISABLED",
    "STATUS_SATISFIED",
    "SKIP_ALREADY_ON_TARGET",
    "SKIP_PUBLISHED_VERSION",
    "SKIP_TARGET_ALREADY_PINNED",
    "UPGRADE_ELIGIBLE",
    "assess_component_approval",
    "audit_export_row",
    "deprecation_status",
    "migration_guidance",
    "normalize_deprecation_notice_days",
    "normalize_approval_stages",
    "plan_bulk_upgrade",
    "render_audit_csv",
    "upgrade_confirmation_token",
    "validate_approval_stages",
    "validate_sunset",
]

#: At most this many stages (mirrors ``style_guides_component_approval_stages_ck``).
MAX_APPROVAL_STAGES = 5
#: Longest stage name.
MAX_STAGE_NAME_LENGTH = 64
#: Longest notice window (mirrors ``style_guides_component_deprecation_notice_days_ck``).
MAX_DEPRECATION_NOTICE_DAYS = 365
#: Longest migration guide (mirrors ``component_revision_deprecation_guide``).
MAX_MIGRATION_GUIDE_LENGTH = 10000
#: Longest decision note (mirrors ``component_revision_approval_note`` and COL-2.1).
MAX_NOTE_LENGTH = 5000

#: No stages are configured — component publishes need no approval.
STATUS_DISABLED = "disabled"
#: Every stage is satisfied — the revision may be published.
STATUS_SATISFIED = "satisfied"
#: At least one stage is unsatisfied — publishing answers 409 ``APPROVAL_REQUIRED``.
STATUS_BLOCKED = "blocked"

#: The stage has the approvals (and role) it requires.
STAGE_SATISFIED = "satisfied"
#: The first unsatisfied stage: the only one that accepts decisions.
STAGE_CURRENT = "current"
#: A reviewer of this stage requested changes on the current payload.
STAGE_CHANGES_REQUESTED = "changes_requested"
#: A later stage, waiting for the earlier ones.
STAGE_WAITING = "waiting"

#: The deprecation is announced and the sunset date has not passed.
DEPRECATION_SCHEDULED = "scheduled"
#: The sunset date has passed: new pins to the revision are refused.
DEPRECATION_SUNSET = "sunset"

#: The pin can be moved to the target revision.
UPGRADE_ELIGIBLE = "eligible"
#: The pin belongs to a published project version, which is immutable.
SKIP_PUBLISHED_VERSION = "published-version"
#: The pin already uses the target revision.
SKIP_ALREADY_ON_TARGET = "already-on-target"
#: The version already pins the target revision through another pin.
SKIP_TARGET_ALREADY_PINNED = "target-already-pinned"

#: Columns of the audit export, in order. CSV uses them as the header row.
AUDIT_EXPORT_COLUMNS = (
    "timestamp",
    "action",
    "decision",
    "actorId",
    "actorEmail",
    "componentId",
    "componentName",
    "policy",
    "oldRevision",
    "newRevision",
    "affectedProjects",
    "outcome",
)


# ===========================================================================
# Policy
# ===========================================================================


@dataclass(frozen=True)
class ComponentApprovalStage:
    """One approval stage.

    Attributes:
        name: Display name ("Platform review", "Security").
        required_approvals: Approvals the stage needs, ``1..20``.
        required_reviewer_role: Role slug at least one approval must come from, or ``None``.
    """

    name: str
    required_approvals: int = 1
    required_reviewer_role: Optional[str] = None

    def as_payload(self) -> Dict[str, Any]:
        """Serialize to the camelCase shape stored on the guide and returned by the API."""
        return {
            "name": self.name,
            "requiredApprovals": self.required_approvals,
            "requiredReviewerRole": self.required_reviewer_role,
        }


@dataclass(frozen=True)
class ComponentGovernancePolicy:
    """The resolved component-library policy of the tenant's governing style guide.

    Attributes:
        stages: Ordered approval stages; empty means no approval gate.
        deprecation_notice_days: Minimum days between scheduling a deprecation and its sunset.
        guide_id: The guide the policy came from, or ``None`` when no guide resolved.
        guide_name: That guide's name, for audit rows and messages.
    """

    stages: Tuple[ComponentApprovalStage, ...] = ()
    deprecation_notice_days: int = 0
    guide_id: Optional[str] = None
    guide_name: Optional[str] = None

    @property
    def approval_active(self) -> bool:
        """Whether publishing a component revision needs approvals."""
        return bool(self.stages)

    @classmethod
    def from_guide(cls, guide: Optional[Mapping[str, Any]]) -> "ComponentGovernancePolicy":
        """Build the policy from a style-guide row, leniently.

        Args:
            guide: A row carrying ``component_approval_stages`` and
                ``component_deprecation_notice_days`` (plus ``id``/``name``), or ``None``.

        Returns:
            The policy; a missing guide or unusable values yield the inactive default.
        """
        if not isinstance(guide, Mapping):
            return cls()
        return cls(
            stages=tuple(normalize_approval_stages(guide.get("component_approval_stages"))),
            deprecation_notice_days=normalize_deprecation_notice_days(
                guide.get("component_deprecation_notice_days")
            ),
            guide_id=str(guide["id"]) if guide.get("id") else None,
            guide_name=str(guide["name"]) if guide.get("name") else None,
        )

    def as_payload(self) -> Dict[str, Any]:
        """Serialize to the camelCase shape the API and audit rows share."""
        return {
            "guideId": self.guide_id,
            "guideName": self.guide_name,
            "approvalStages": [stage.as_payload() for stage in self.stages],
            "deprecationNoticeDays": self.deprecation_notice_days,
        }


def _stage_name(raw: Any, index: int) -> str:
    text = raw.strip() if isinstance(raw, str) else ""
    return text[:MAX_STAGE_NAME_LENGTH] if text else f"Stage {index + 1}"


def normalize_approval_stages(raw: Any) -> List[ComponentApprovalStage]:
    """Coerce a stored stage list into stages, dropping anything unusable.

    Used on read, where a bad stored value must degrade rather than fail. Stages that would
    require no approvals are dropped: a stage nobody needs to approve gates nothing.

    Args:
        raw: The ``component_approval_stages`` value (a list, a JSON string, or junk).

    Returns:
        At most :data:`MAX_APPROVAL_STAGES` stages, in stored order.
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            return []
    if not isinstance(raw, list):
        return []
    stages: List[ComponentApprovalStage] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        required = normalize_required_approvals(item.get("requiredApprovals"))
        if required < 1:
            continue
        stages.append(
            ComponentApprovalStage(
                name=_stage_name(item.get("name"), len(stages)),
                required_approvals=required,
                required_reviewer_role=normalize_required_reviewer_role(
                    item.get("requiredReviewerRole")
                ),
            )
        )
        if len(stages) == MAX_APPROVAL_STAGES:
            break
    return stages


def validate_approval_stages(raw: Any) -> Tuple[List[ComponentApprovalStage], List[str]]:
    """Validate a submitted stage list strictly.

    Used on write, where an administrator should hear what is wrong instead of having a stage
    silently dropped.

    Args:
        raw: The submitted list of ``{name, requiredApprovals, requiredReviewerRole}`` objects.

    Returns:
        ``(stages, errors)``. ``errors`` is empty when every stage is valid.
    """
    if not isinstance(raw, list):
        return [], ["componentApprovalStages must be a list."]
    errors: List[str] = []
    if len(raw) > MAX_APPROVAL_STAGES:
        errors.append(f"At most {MAX_APPROVAL_STAGES} approval stages are supported.")
    stages: List[ComponentApprovalStage] = []
    names: set = set()
    for index, item in enumerate(raw[:MAX_APPROVAL_STAGES]):
        label = f"Stage {index + 1}"
        if not isinstance(item, Mapping):
            errors.append(f"{label} must be an object.")
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            errors.append(f"{label} needs a name.")
            continue
        if len(name.strip()) > MAX_STAGE_NAME_LENGTH:
            errors.append(f"{label} name is longer than {MAX_STAGE_NAME_LENGTH} characters.")
            continue
        if name.strip().lower() in names:
            errors.append(f"{label} repeats the name '{name.strip()}'.")
            continue
        required = item.get("requiredApprovals")
        if (
            isinstance(required, bool)
            or not isinstance(required, int)
            or not 1 <= required <= MAX_REQUIRED_APPROVALS
        ):
            errors.append(
                f"{label} requiredApprovals must be a whole number from 1 to "
                f"{MAX_REQUIRED_APPROVALS}."
            )
            continue
        role_raw = item.get("requiredReviewerRole")
        role = normalize_required_reviewer_role(role_raw)
        if role_raw not in (None, "") and role is None:
            errors.append(f"{label} requiredReviewerRole is not a valid role slug.")
            continue
        names.add(name.strip().lower())
        stages.append(
            ComponentApprovalStage(
                name=name.strip(), required_approvals=required, required_reviewer_role=role
            )
        )
    return stages, errors


def normalize_deprecation_notice_days(raw: Any) -> int:
    """Coerce a stored or submitted notice window into ``0..365``.

    Args:
        raw: Any candidate value.

    Returns:
        The clamped number of days; anything unparseable or negative is ``0``.
    """
    if isinstance(raw, bool):
        return 0
    try:
        value = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    return max(0, min(value, MAX_DEPRECATION_NOTICE_DAYS))


# ===========================================================================
# Approval assessment
# ===========================================================================


@dataclass(frozen=True)
class ComponentApprovalAssessment:
    """The policy's verdict on one draft revision.

    Attributes:
        policy: The policy the verdict was reached under.
        status: ``disabled`` / ``satisfied`` / ``blocked``.
        payload_digest: The revision digest the decisions were counted against.
        stages: One entry per stage: ``{index, name, requiredApprovals, requiredReviewerRole,
            status, approvals, roleApprovals, changesRequested, approvers}``.
        current_stage: Index of the stage that accepts decisions, or ``None``.
        stale_decisions: Decisions given to an earlier payload, which no longer count.
    """

    policy: ComponentGovernancePolicy = field(default_factory=ComponentGovernancePolicy)
    status: str = STATUS_DISABLED
    payload_digest: Optional[str] = None
    stages: Tuple[Dict[str, Any], ...] = ()
    current_stage: Optional[int] = None
    stale_decisions: int = 0

    @property
    def blocked(self) -> bool:
        """Whether publishing must be refused."""
        return self.status == STATUS_BLOCKED

    def message(self) -> str:
        """Human-readable one-liner for dialogs, errors, and audit rows."""
        if self.status == STATUS_DISABLED:
            return "No component approval policy applies."
        if self.status == STATUS_SATISFIED:
            return "Every approval stage is satisfied."
        stage = self.stages[self.current_stage or 0] if self.stages else {}
        name = stage.get("name", "Approval")
        if stage.get("status") == STAGE_CHANGES_REQUESTED:
            return (
                f"A reviewer in '{name}' requested changes. Update the draft, then ask for "
                "approval again."
            )
        role = stage.get("requiredReviewerRole")
        if (
            role
            and stage.get("approvals", 0) >= stage.get("requiredApprovals", 1)
            and not stage.get("roleApprovals")
        ):
            return f"'{name}' needs an approval from a reviewer with the '{role}' role."
        return (
            f"'{name}' has {stage.get('approvals', 0)} of {stage.get('requiredApprovals', 1)} "
            "required approval(s)."
        )

    def as_payload(self) -> Dict[str, Any]:
        """Serialize to the camelCase shape the API, the 409 body, and audit rows share."""
        return {
            "policy": self.policy.as_payload(),
            "status": self.status,
            "blocked": self.blocked,
            "payloadDigest": self.payload_digest,
            "currentStage": self.current_stage,
            "staleDecisions": self.stale_decisions,
            "stages": [dict(stage) for stage in self.stages],
            "message": self.message(),
        }


def assess_component_approval(
    policy: ComponentGovernancePolicy,
    decisions: Iterable[Mapping[str, Any]],
    payload_digest: str,
    role_of: Callable[[str], Optional[str]],
) -> ComponentApprovalAssessment:
    """Judge a draft revision's decisions against the policy.

    Only decisions whose ``payload_digest`` matches the revision's current digest count. Stages
    are evaluated in order; the first stage that is not satisfied is the current one, and every
    later stage waits. A ``request_changes`` decision in a stage blocks it whatever the count.

    Args:
        policy: The resolved policy.
        decisions: Decision rows (``stage_index``, ``user_id``, ``user_email``, ``decision``,
            ``payload_digest``).
        payload_digest: The revision's current digest.
        role_of: Resolves a user id to their effective role slug (only called when a stage
            requires a role).

    Returns:
        The assessment.
    """
    if not policy.approval_active:
        return ComponentApprovalAssessment(policy=policy, payload_digest=payload_digest)
    current: List[Mapping[str, Any]] = []
    stale = 0
    for row in decisions:
        if str(row.get("payload_digest") or "") == payload_digest:
            current.append(row)
        else:
            stale += 1

    stages: List[Dict[str, Any]] = []
    current_stage: Optional[int] = None
    for index, stage in enumerate(policy.stages):
        rows = [row for row in current if int(row.get("stage_index") or 0) == index]
        approvers: List[Dict[str, Optional[str]]] = []
        role_approvals = 0
        changes = 0
        for row in rows:
            decision = str(row.get("decision") or "")
            if decision == DECISION_REQUEST_CHANGES:
                changes += 1
                continue
            if decision != DECISION_APPROVE:
                continue
            user_id = str(row.get("user_id") or "") or None
            role_slug: Optional[str] = None
            if stage.required_reviewer_role and user_id:
                role_slug = normalize_required_reviewer_role(role_of(user_id))
                if role_slug == stage.required_reviewer_role:
                    role_approvals += 1
            approvers.append(
                {"userId": user_id, "userEmail": row.get("user_email"), "roleSlug": role_slug}
            )
        approvals = len(approvers)
        met = approvals >= stage.required_approvals and (
            not stage.required_reviewer_role or role_approvals >= 1
        )
        if current_stage is not None:
            status = STAGE_WAITING
        elif changes:
            status = STAGE_CHANGES_REQUESTED
            current_stage = index
        elif met:
            status = STAGE_SATISFIED
        else:
            status = STAGE_CURRENT
            current_stage = index
        stages.append(
            {
                "index": index,
                **stage.as_payload(),
                "status": status,
                "approvals": approvals,
                "roleApprovals": role_approvals,
                "changesRequested": changes,
                "approvers": approvers,
            }
        )
    return ComponentApprovalAssessment(
        policy=policy,
        status=STATUS_BLOCKED if current_stage is not None else STATUS_SATISFIED,
        payload_digest=payload_digest,
        stages=tuple(stages),
        current_stage=current_stage,
        stale_decisions=stale,
    )


# ===========================================================================
# Deprecation
# ===========================================================================


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def deprecation_status(sunset_at: datetime, now: datetime) -> str:
    """Whether a deprecation is still announced or has reached its sunset.

    Args:
        sunset_at: The scheduled sunset.
        now: The current time.

    Returns:
        :data:`DEPRECATION_SUNSET` once ``now`` reaches ``sunset_at``, else
        :data:`DEPRECATION_SCHEDULED`.
    """
    return DEPRECATION_SUNSET if _as_utc(now) >= _as_utc(sunset_at) else DEPRECATION_SCHEDULED


def validate_sunset(sunset_at: datetime, now: datetime, notice_days: int) -> Optional[str]:
    """Check a requested sunset date against the policy's notice window.

    Args:
        sunset_at: The requested sunset.
        now: The current time.
        notice_days: The policy's minimum notice.

    Returns:
        ``None`` when acceptable, else a human-readable reason.
    """
    sunset = _as_utc(sunset_at)
    current = _as_utc(now)
    if sunset <= current:
        return "The sunset date must be in the future."
    earliest = current + timedelta(days=notice_days)
    if notice_days and sunset < earliest:
        return (
            f"The deprecation policy requires {notice_days} day(s) of notice; the earliest "
            f"sunset is {earliest.date().isoformat()}."
        )
    return None


def migration_guidance(
    *,
    component_name: str,
    revision: str,
    sunset_at: datetime,
    replacement_revision: Optional[str],
    guide: Optional[str],
    affected: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Build the migration guidance consumers see for a deprecation.

    Args:
        component_name: The library component's name.
        revision: The deprecated semver revision.
        sunset_at: The sunset.
        replacement_revision: The replacement semver, when one was named.
        guide: The author's free-text guidance, if any.
        affected: Affected pins (``published`` flag per entry).

    Returns:
        ``{summary, guide, replacementRevision, steps, draftVersions, publishedVersions}``.
        ``steps`` are ordered and say what to do for draft and for published versions.
    """
    drafts = sum(1 for row in affected if not row.get("published"))
    published = len(affected) - drafts
    when = _as_utc(sunset_at).date().isoformat()
    target = f"{component_name}@{replacement_revision}" if replacement_revision else None
    summary = f"{component_name}@{revision} is deprecated and reaches its sunset on {when}."
    if target:
        summary += f" Move to {target}."
    steps: List[str] = []
    if drafts:
        steps.append(
            f"Upgrade the {drafts} draft version(s) that pin {component_name}@{revision}"
            + (f" to {target} with a bulk upgrade" if target else " to a newer revision")
            + " before the sunset."
        )
    if published:
        steps.append(
            f"{published} published version(s) keep their pin — published versions never "
            "change. Create a new draft from each one to migrate it."
        )
    steps.append(
        f"After {when}, new pins to {component_name}@{revision} are refused; existing pins "
        "keep working."
    )
    return {
        "summary": summary,
        "guide": guide or None,
        "replacementRevision": replacement_revision,
        "steps": steps,
        "draftVersions": drafts,
        "publishedVersions": published,
    }


# ===========================================================================
# Bulk upgrade
# ===========================================================================


def plan_bulk_upgrade(
    pins: Sequence[Mapping[str, Any]], target_revision_id: str
) -> List[Dict[str, Any]]:
    """Decide, pin by pin, whether a target revision can replace it.

    Args:
        pins: Live pins of the component (``pin_id``, ``version_id``, ``project_id``,
            ``revision_id``, ``published`` …), in a stable order.
        target_revision_id: The published revision to move to.

    Returns:
        One entry per pin, the input row plus ``status`` — :data:`UPGRADE_ELIGIBLE` or a
        ``SKIP_*`` reason. A version that already pins the target keeps that pin; its other pins
        of the component are skipped rather than collapsed, so nothing is removed implicitly.
    """
    target = str(target_revision_id)
    versions_on_target = {
        str(pin.get("version_id")) for pin in pins if str(pin.get("revision_id")) == target
    }
    plan: List[Dict[str, Any]] = []
    for pin in pins:
        entry = dict(pin)
        if str(pin.get("revision_id")) == target:
            entry["status"] = SKIP_ALREADY_ON_TARGET
        elif pin.get("published"):
            entry["status"] = SKIP_PUBLISHED_VERSION
        elif str(pin.get("version_id")) in versions_on_target:
            entry["status"] = SKIP_TARGET_ALREADY_PINNED
        else:
            entry["status"] = UPGRADE_ELIGIBLE
        plan.append(entry)
    return plan


def upgrade_confirmation_token(
    component_id: str, target_revision_id: str, plan: Sequence[Mapping[str, Any]]
) -> str:
    """A digest of the eligible part of a plan.

    The execute call must send back the token of the plan it was shown. Any change in between —
    a pin added or removed, a version published, a pin moved — changes the token, so the server
    refuses to run a plan nobody previewed.

    Args:
        component_id: The component.
        target_revision_id: The target revision.
        plan: The output of :func:`plan_bulk_upgrade`.

    Returns:
        ``sha256:<hex>``.
    """
    eligible = sorted(
        (str(entry.get("pin_id")), str(entry.get("revision_id")))
        for entry in plan
        if entry.get("status") == UPGRADE_ELIGIBLE
    )
    canonical = json.dumps(
        {"component": str(component_id), "target": str(target_revision_id), "pins": eligible},
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ===========================================================================
# Audit export
# ===========================================================================


def _decision_for(action: str, detail: Mapping[str, Any]) -> str:
    explicit = detail.get("decision")
    if isinstance(explicit, str) and explicit:
        return explicit
    return {
        "component.create": "created",
        "component.delete": "deleted",
        "revision.draft": "drafted",
        "revision.update": "updated",
        "revision.publish": "published",
        "revision.delete": "deleted",
        "pin.create": "pinned",
        "pin.remove": "unpinned",
        "deprecation.schedule": "scheduled",
        "deprecation.cancel": "cancelled",
        "pin.upgrade": "upgraded",
        "upgrade.bulk": "upgraded",
    }.get(action, action)


def _projects_of(detail: Mapping[str, Any]) -> List[Dict[str, Any]]:
    raw = detail.get("affectedProjects")
    if not isinstance(raw, list):
        return []
    return [dict(item) for item in raw if isinstance(item, Mapping)]


def audit_export_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    """Flatten one ledger row into the export shape.

    DCW-3.1 rows predate the governance fields, so the old/new revisions fall back to the
    ``previousHead`` / ``revision`` keys those rows carry.

    Args:
        row: A ``component_library_audit`` row joined to the actor's email and component name.

    Returns:
        A dict keyed by :data:`AUDIT_EXPORT_COLUMNS`.
    """
    detail = row.get("detail") if isinstance(row.get("detail"), Mapping) else {}
    action = str(row.get("action") or "")
    created = row.get("created_at")
    timestamp = created.isoformat() if isinstance(created, datetime) else (str(created or "") or None)
    return {
        "timestamp": timestamp,
        "action": action,
        "decision": _decision_for(action, detail),
        "actorId": str(row["actor_id"]) if row.get("actor_id") else None,
        "actorEmail": row.get("actor_email"),
        "componentId": str(row["component_id"]) if row.get("component_id") else None,
        "componentName": row.get("component_name") or detail.get("componentName"),
        "policy": detail.get("policy"),
        "oldRevision": detail.get("oldRevision", detail.get("previousHead")),
        "newRevision": detail.get("newRevision", detail.get("revision")),
        "affectedProjects": _projects_of(detail),
        "outcome": row.get("outcome") or "success",
    }


def _csv_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    text = str(value)
    # Keep spreadsheet applications from evaluating a cell as a formula.
    if text[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


def render_audit_csv(rows: Sequence[Mapping[str, Any]]) -> str:
    """Render export rows as CSV with a header row.

    ``policy`` and ``affectedProjects`` are written as compact JSON. Cells that a spreadsheet
    would evaluate as a formula are prefixed with ``'``.

    Args:
        rows: Rows from :func:`audit_export_row`.

    Returns:
        The CSV text.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(AUDIT_EXPORT_COLUMNS)
    for row in rows:
        writer.writerow([_csv_cell(row.get(column)) for column in AUDIT_EXPORT_COLUMNS])
    return buffer.getvalue()
