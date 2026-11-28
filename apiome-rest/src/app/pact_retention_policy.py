"""A workspace's stored clean-up rules — PFX-8.14 (#7311).

PFX-1.11 (:mod:`app.pact_retention`) let a caller run a retention plan by hand. The Contracts
**Settings → Clean-up** tab, and ``apiome pact retention show|set|preview``, store the rules instead
(apiome-db V456, ``pact_retention_policy``), and apiome-rest applies them every night:

* **What to keep.** Every version deployed or released anywhere — always: a rule set that turns it
  off is refused (``pact-retention-keeps-in-use``), never saved. Then, any of: the latest *N* versions
  of each pacticipant's main branch; the latest *N* of every other branch, optionally only while
  recorded in the last *D* days; every version carrying one of the listed tags. A pacticipant's
  latest version is kept whatever the rules say.
* **Run clean-up nightly.** Off by default: nothing is removed while it is off. On, the rules run
  once a day after :data:`NIGHTLY_HOUR_UTC`:00 UTC.
* **Keep deleted items restorable for** *D* days (1 … 365): the purge window of
  :mod:`app.pact_cleanup_store` for this workspace.

This module is pure: the models, the rules → keep-selector mapping and the schedule.
:mod:`app.pact_retention_policy_store` reads, saves, previews and runs them.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .pact_retention import MAX_KEEP_TAGS, RetentionError, RetentionKeep, RetentionPlan, clean_tag

__all__ = [
    "CODE_KEEPS_IN_USE",
    "DeletedItem",
    "DeletedPage",
    "NIGHTLY_HOUR_UTC",
    "RetentionLastRun",
    "RetentionPolicy",
    "RetentionPreview",
    "RetentionPreviewRequest",
    "RetentionRules",
    "is_due",
    "keep_of",
    "next_run_at",
    "rules_from_row",
]

CODE_KEEPS_IN_USE = "pact-retention-keeps-in-use"

#: The hour (UTC) after which a workspace's nightly clean-up runs, once a day.
NIGHTLY_HOUR_UTC = 2

#: The sentence a refused rule set carries, as the Clean-up tab shows it.
KEEPS_IN_USE_MESSAGE = "Deployed and released versions are always kept."


class RetentionRules(BaseModel):
    """The clean-up rules a workspace saves (``PUT …/pact-retention/policy``).

    A field left out takes its default: a ``PUT`` replaces every rule. ``apiome pact retention set``
    reads the rules first and changes only the flags it is given.

    Attributes:
        keep_deployed_or_released: Always ``true``; ``false`` is refused.
        keep_main_branch_latest: Keep the newest N versions of each pacticipant's main branch.
        keep_other_branch_latest: Keep the newest N versions of every other branch.
        keep_other_branch_days: With ``keep_other_branch_latest``: only while recorded in the last D days.
        keep_tags: Keep every version carrying one of these tags.
        nightly_enabled: Apply the rules every night.
        restore_window_days: Days a deleted pacticipant or version stays restorable.
    """

    model_config = ConfigDict(extra="forbid")

    keep_deployed_or_released: bool = Field(
        default=True,
        description="Every version deployed or released anywhere is kept. Always `true`: `false` is refused.",
    )
    keep_main_branch_latest: Optional[int] = Field(
        default=None, ge=1, le=1000, description="Keep the newest N versions of each pacticipant's main branch."
    )
    keep_other_branch_latest: Optional[int] = Field(
        default=None, ge=1, le=1000, description="Keep the newest N versions of every other branch."
    )
    keep_other_branch_days: Optional[int] = Field(
        default=None,
        ge=1,
        le=3650,
        description="With `keep_other_branch_latest`: only while they were recorded in the last D days.",
    )
    keep_tags: List[str] = Field(
        default_factory=list,
        max_length=MAX_KEEP_TAGS,
        description=f"Keep every version carrying one of these tags (at most {MAX_KEEP_TAGS}).",
    )
    nightly_enabled: bool = Field(
        default=False, description="Apply the rules every night. Off: clean-up removes nothing."
    )
    restore_window_days: int = Field(
        default=30,
        ge=1,
        le=365,
        description="Days a deleted pacticipant or version can be restored before it is purged.",
    )

    @field_validator("keep_tags")
    @classmethod
    def _valid_tags(cls, tags: List[str]) -> List[str]:
        """Refuse a blank, padded, over-long or repeated tag — none is dropped silently."""
        cleaned = [clean_tag(tag) for tag in tags]
        repeated = sorted({tag for tag in cleaned if cleaned.count(tag) > 1})
        if repeated:
            raise ValueError(f"tag listed more than once: {', '.join(repeated)}")
        return cleaned

    @model_validator(mode="after")
    def _days_need_a_count(self) -> "RetentionRules":
        """``keep_other_branch_days`` qualifies ``keep_other_branch_latest``; alone it keeps nothing."""
        if self.keep_other_branch_days is not None and self.keep_other_branch_latest is None:
            raise ValueError("keep_other_branch_days needs keep_other_branch_latest")
        return self


def keep_of(rules: RetentionRules) -> RetentionKeep:
    """The keep selectors a stored rule set runs with.

    Args:
        rules: The rules.

    Returns:
        The selectors: deployed-or-released always on, and the rules' branch and tag selectors.

    Raises:
        RetentionError: ``pact-retention-keeps-in-use`` when the rules turn deployed / released off.
    """
    if not rules.keep_deployed_or_released:
        raise RetentionError(
            CODE_KEEPS_IN_USE,
            f"{KEEPS_IN_USE_MESSAGE} A rule set that would remove a deployed or released version cannot be saved.",
        )
    return RetentionKeep(
        deployed_or_released=True,
        latest_per_main_branch=rules.keep_main_branch_latest,
        latest_per_other_branch=rules.keep_other_branch_latest,
        other_branch_days=rules.keep_other_branch_days,
        tags=list(rules.keep_tags),
    )


def _run_time(now: datetime) -> datetime:
    """Today's nightly run time (UTC) for ``now``."""
    moment = now.astimezone(timezone.utc)
    return moment.replace(hour=NIGHTLY_HOUR_UTC, minute=0, second=0, microsecond=0)


def is_due(now: datetime, last_run_at: Optional[datetime]) -> bool:
    """Whether a workspace's nightly clean-up should run now.

    Args:
        now: The current time (timezone-aware).
        last_run_at: When it last ran, or ``None``.

    Returns:
        ``True`` once today's run time has passed and it has not run since.
    """
    today = _run_time(now)
    return now >= today and (last_run_at is None or last_run_at < today)


def next_run_at(now: datetime, last_run_at: Optional[datetime], enabled: bool) -> Optional[datetime]:
    """When the nightly clean-up runs next.

    Args:
        now: The current time (timezone-aware).
        last_run_at: When it last ran, or ``None``.
        enabled: Whether the nightly clean-up is on.

    Returns:
        ``None`` when it is off; ``now`` when it is due (it runs within minutes); otherwise the next
        :data:`NIGHTLY_HOUR_UTC`:00 UTC.
    """
    if not enabled:
        return None
    today = _run_time(now)
    if now < today:
        return today
    if is_due(now, last_run_at):
        return now
    return today + timedelta(days=1)


class RetentionLastRun(BaseModel):
    """What the last nightly clean-up did."""

    model_config = ConfigDict(extra="forbid")

    at: str = Field(description="When it finished.")
    deleted: Optional[int] = Field(default=None, description="Versions it deleted.")
    remaining: Optional[int] = Field(default=None, description="Versions past its cap, left for the next night.")
    error: Optional[str] = Field(default=None, description="Why it deleted nothing, when it was refused.")


class RetentionPolicy(RetentionRules):
    """A workspace's clean-up rules as ``GET …/pact-retention/policy`` answers them."""

    configured: bool = Field(description="Whether the workspace has saved rules; `false` shows the defaults.")
    updated_at: Optional[str] = None
    updated_by: Optional[str] = Field(default=None, description="Who saved them last.")
    last_run: Optional[RetentionLastRun] = None
    next_run_at: Optional[str] = Field(
        default=None, description="When the nightly clean-up runs next; null while it is off."
    )
    can_edit: bool = Field(
        description="Whether the caller may save the rules and restore (`pacts:delete`); otherwise read-only."
    )


class RetentionPreviewRequest(BaseModel):
    """``POST …/pact-retention/policy/preview``: preview the saved rules, or a draft of them."""

    model_config = ConfigDict(extra="forbid")

    rules: Optional[RetentionRules] = Field(
        default=None, description="Rules not saved yet; the saved rules when omitted."
    )


class RetentionPreview(BaseModel):
    """What the rules would remove if clean-up ran now — what the next nightly run removes."""

    model_config = ConfigDict(extra="forbid")

    draft: bool = Field(description="Whether this previews rules that are not saved.")
    nightly_enabled: bool = Field(description="Off: nothing is removed while clean-up is off.")
    next_run_at: Optional[str] = None
    plan: RetentionPlan


class DeletedItem(BaseModel):
    """One row of the Recently deleted list: a deleted pacticipant, or a version deleted on its own."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["pacticipant", "version"]
    id: str = Field(description="The pacticipant's or the version's id.")
    pacticipant_id: str
    pacticipant_slug: str
    pacticipant_name: str
    number: Optional[str] = Field(default=None, description="The version number (versions only).")
    deleted_at: str
    deleted_by: Optional[str] = Field(default=None, description="Who deleted it; `Clean-up` for the nightly run.")
    cause: str = Field(description="`pacticipant`, `version` (deleted by hand) or `retention` (clean-up).")
    reason: Optional[str] = None
    purge_after: str = Field(description="When it is removed for good unless restored.")
    versions: int = Field(default=0, description="Versions deleted with the pacticipant (pacticipants only).")
    pacts: int = Field(default=0, description="Pacts that come back with a restore.")
    results: int = Field(default=0, description="Verification results that come back with a restore.")


class DeletedPage(BaseModel):
    """A page of the Recently deleted list, newest first."""

    model_config = ConfigDict(extra="forbid")

    items: List[DeletedItem]
    count: int
    has_more: bool
    next_cursor: Optional[str] = None
    restore_window_days: int
    can_restore: bool = Field(description="Whether the caller may restore (`pacts:delete`).")


def rules_from_row(row: Optional[Dict[str, object]]) -> RetentionRules:
    """The rules stored in a ``pact_retention_policy`` row, or the defaults when there is none.

    Args:
        row: The row, or ``None``.

    Returns:
        The rules.
    """
    if not row:
        return RetentionRules()
    return RetentionRules.model_validate(
        {
            "keep_main_branch_latest": row.get("keep_main_branch_latest"),
            "keep_other_branch_latest": row.get("keep_other_branch_latest"),
            "keep_other_branch_days": row.get("keep_other_branch_days"),
            "keep_tags": row.get("keep_tags") or [],
            "nightly_enabled": bool(row.get("nightly_enabled")),
            "restore_window_days": row.get("restore_window_days") or 30,
        }
    )
