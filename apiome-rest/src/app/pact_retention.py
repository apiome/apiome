"""Selector-based retention of pacticipant versions — what to keep, what to delete, PFX-1.11 (#6924).

A retention run says which versions to **keep**; every other live version of the pacticipants it
covers is deleted (a soft delete — :mod:`app.pact_cleanup_store` — so a mistake can be restored
until the purge). The keep selectors, any of which keeps a version:

* ``latest_per_branch`` — the newest *N* versions recorded on each branch;
* ``latest_per_main_branch`` — the newest *N* versions of each pacticipant's main branch (PFX-8.14);
* ``latest_per_other_branch`` — the newest *N* versions of every other branch, and with
  ``other_branch_days`` only while they were recorded in the last *D* days (PFX-8.14);
* ``tags`` — every version carrying one of the tags (PFX-8.14);
* ``deployed_or_released`` — every version currently deployed to, or released in, an environment
  (on by default, so a run never removes what can-i-deploy is answering for);
* ``created_within_days`` — every version recorded in the last *D* days.

Two rules hold whatever the selectors say: each pacticipant's **latest version is always kept**, and
a run deletes at most :data:`MAX_DELETIONS_PER_RUN` versions (the oldest first) — the rest are
reported as ``remaining``, never dropped silently.

The run is **dry-run first**: a request without ``dry_run: false`` only answers the plan and its
``plan_digest``. Applying needs that digest back, and the store re-plans inside the transaction and
refuses when the plan changed in between (a version was published or deployed meanwhile), so
nothing is deleted that the caller did not see.

This module is pure — no database. :mod:`app.pact_retention_store` reads the facts and applies.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = [
    "CODE_NO_SELECTOR",
    "CODE_PLAN_CHANGED",
    "CODE_PLAN_DIGEST_REQUIRED",
    "CODE_TOO_MANY_PACTICIPANTS",
    "CODE_TOO_MANY_VERSIONS",
    "MAX_DELETIONS_PER_RUN",
    "MAX_LISTED_PER_PACTICIPANT",
    "MAX_PACTICIPANTS_PER_RUN",
    "MAX_VERSIONS_EVALUATED",
    "KEEP_REASONS",
    "MAX_KEEP_TAGS",
    "PacticipantPlan",
    "PlannedDeletion",
    "RetentionError",
    "RetentionKeep",
    "RetentionPlan",
    "RetentionRequest",
    "VersionFacts",
    "clean_tag",
    "digest_of",
    "plan_retention",
]

CODE_NO_SELECTOR = "pact-retention-no-selector"
CODE_PLAN_DIGEST_REQUIRED = "pact-retention-plan-digest-required"
CODE_PLAN_CHANGED = "pact-retention-plan-changed"
CODE_TOO_MANY_PACTICIPANTS = "pact-retention-too-many-pacticipants"
CODE_TOO_MANY_VERSIONS = "pact-retention-too-many-versions"

#: The most versions one applied run deletes; a larger plan deletes the oldest and reports the rest.
MAX_DELETIONS_PER_RUN = 5000
#: The most versions one run reads; a larger registry is cleaned one group of pacticipants at a time.
MAX_VERSIONS_EVALUATED = 100_000
#: The most pacticipants a request may name.
MAX_PACTICIPANTS_PER_RUN = 200
#: The most to-be-deleted versions each pacticipant lists in the answer (the counts are complete).
MAX_LISTED_PER_PACTICIPANT = 100

#: The most tags one run (or one stored policy) keeps by.
MAX_KEEP_TAGS = 50

#: Why a version is kept, in the order they are checked.
KEEP_REASONS = (
    "latest",
    "latest_per_branch",
    "latest_per_main_branch",
    "latest_per_other_branch",
    "deployed_or_released",
    "tagged",
    "created_within_days",
)


class RetentionError(ValueError):
    """A retention refusal carrying a stable machine code.

    Attributes:
        code: One of the module's ``CODE_*`` constants.
    """

    def __init__(self, code: str, message: str) -> None:
        """Build the refusal.

        Args:
            code: The stable code a client branches on.
            message: The human-readable explanation.
        """
        super().__init__(message)
        self.code = code


def clean_tag(value: object) -> str:
    """One keep tag, as ``pacticipant_version_tag.name`` stores it, or a refusal saying why."""
    if not isinstance(value, str):
        raise ValueError("a tag is text")
    if value != value.strip() or not value:
        raise ValueError(f"tag {value!r} is empty or has spaces around it")
    if len(value) > 255:
        raise ValueError("a tag is at most 255 characters")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ValueError(f"tag {value!r} has a control character")
    return value


class RetentionKeep(BaseModel):
    """The keep selectors of a run; a version any of them matches is kept.

    Attributes:
        latest_per_branch: Keep the newest N versions of each branch.
        latest_per_main_branch: Keep the newest N versions of each pacticipant's main branch.
        latest_per_other_branch: Keep the newest N versions of every branch that is not the main one.
        other_branch_days: With ``latest_per_other_branch``: only while recorded in the last D days.
        deployed_or_released: Keep every version currently deployed or released.
        tags: Keep every version carrying one of these tags.
        created_within_days: Keep every version recorded in the last D days.
    """

    model_config = ConfigDict(extra="forbid")

    latest_per_branch: Optional[int] = Field(
        default=None, ge=1, le=1000, description="Keep the newest N versions recorded on each branch."
    )
    latest_per_main_branch: Optional[int] = Field(
        default=None, ge=1, le=1000, description="Keep the newest N versions of each pacticipant's main branch."
    )
    latest_per_other_branch: Optional[int] = Field(
        default=None,
        ge=1,
        le=1000,
        description="Keep the newest N versions of every branch that is not its pacticipant's main branch.",
    )
    other_branch_days: Optional[int] = Field(
        default=None,
        ge=1,
        le=3650,
        description="With `latest_per_other_branch`: only while they were recorded in the last D days.",
    )
    deployed_or_released: bool = Field(
        default=True, description="Keep every version currently deployed to or released in an environment."
    )
    tags: List[str] = Field(
        default_factory=list,
        max_length=MAX_KEEP_TAGS,
        description=f"Keep every version carrying one of these tags (at most {MAX_KEEP_TAGS}).",
    )
    created_within_days: Optional[int] = Field(
        default=None, ge=1, le=3650, description="Keep every version recorded in the last D days."
    )

    @field_validator("tags")
    @classmethod
    def _valid_tags(cls, tags: List[str]) -> List[str]:
        """Refuse a blank, padded, over-long or repeated tag — none is dropped silently."""
        cleaned = [clean_tag(tag) for tag in tags]
        repeated = sorted({tag for tag in cleaned if cleaned.count(tag) > 1})
        if repeated:
            raise ValueError(f"tag listed more than once: {', '.join(repeated)}")
        return cleaned

    @model_validator(mode="after")
    def _days_need_a_count(self) -> "RetentionKeep":
        """``other_branch_days`` qualifies ``latest_per_other_branch``; alone it would keep nothing."""
        if self.other_branch_days is not None and self.latest_per_other_branch is None:
            raise ValueError("other_branch_days needs latest_per_other_branch")
        return self

    def selects_anything(self) -> bool:
        """Whether any selector keeps a version beyond each pacticipant's latest one."""
        return bool(
            self.latest_per_branch
            or self.latest_per_main_branch
            or self.latest_per_other_branch
            or self.deployed_or_released
            or self.tags
            or self.created_within_days
        )


class RetentionRequest(BaseModel):
    """One retention run.

    Attributes:
        keep: The keep selectors.
        pacticipants: The pacticipants to clean (handles, ids or names); all of them when omitted.
        dry_run: Only plan (the default). ``false`` applies the plan.
        plan_digest: The ``plan_digest`` of the dry run being applied; required with ``dry_run: false``.
        reason: Why, stored on every deleted version and in the audit trail.
    """

    model_config = ConfigDict(extra="forbid")

    keep: RetentionKeep
    pacticipants: Optional[List[str]] = Field(
        default=None,
        description=(
            f"Handles, ids or names to clean (at most {MAX_PACTICIPANTS_PER_RUN}); every pacticipant when omitted."
        ),
    )
    dry_run: bool = Field(default=True, description="Only answer the plan. `false` applies it.")
    plan_digest: Optional[str] = Field(
        default=None,
        description="The `plan_digest` of the dry run being applied. Required when `dry_run` is false.",
    )
    reason: Optional[str] = Field(default=None, description="Why; stored on each deleted version (≤ 500 characters).")


@dataclass(frozen=True)
class VersionFacts:
    """What retention needs to know about one live version.

    Attributes:
        id: The version id.
        pacticipant_id: Its pacticipant.
        number: The version number.
        seq: Order of recording.
        created_at: When it was recorded (timezone-aware).
        branches: The branches it was recorded on.
        in_use: Whether it is currently deployed or released.
        tags: Its tags.
    """

    id: str
    pacticipant_id: str
    number: str
    seq: int
    created_at: datetime
    branches: Tuple[str, ...] = ()
    in_use: bool = False
    tags: Tuple[str, ...] = ()


class PlannedDeletion(BaseModel):
    """A version the plan deletes."""

    model_config = ConfigDict(extra="forbid")

    number: str
    pacts: int = Field(default=0, description="Pacts published from this version that go with it.")
    results: int = Field(default=0, description="Verification results recorded for this version that go with it.")
    created_at: Optional[str] = None
    branches: List[str] = Field(default_factory=list)


class PacticipantPlan(BaseModel):
    """The plan for one pacticipant."""

    model_config = ConfigDict(extra="forbid")

    slug: str
    name: str
    evaluated: int = Field(description="Live versions read.")
    kept: int = Field(description="Versions a selector (or the latest-version rule) keeps.")
    deleted: int = Field(description="Versions this run deletes (or, in a dry run, would delete).")
    remaining: int = Field(
        default=0, description="Versions to delete that are past this run's cap; a later run deletes them."
    )
    kept_by: Dict[str, int] = Field(
        default_factory=dict, description="Kept versions by the first rule that keeps them."
    )
    deletions: List[PlannedDeletion] = Field(
        default_factory=list,
        description=f"The versions deleted, oldest first (at most {MAX_LISTED_PER_PACTICIPANT} listed).",
    )


class RetentionPlan(BaseModel):
    """The answer to a retention run: the plan, and whether it was applied."""

    model_config = ConfigDict(extra="forbid")

    dry_run: bool
    applied: bool = Field(description="Whether the deletions were made.")
    plan_digest: str = Field(description="Send this back with `dry_run: false` to apply exactly this plan.")
    keep: RetentionKeep
    evaluated: int
    kept: int
    deleted: int
    remaining: int = Field(default=0, description="Deletions past this run's cap; run again to make them.")
    pacts: int = Field(default=0, description="Pacts published from the deleted versions, which go with them.")
    results: int = Field(default=0, description="Verification results of the deleted versions, which go with them.")
    matched_by: Dict[str, int] = Field(
        default_factory=dict,
        description=(
            "Versions each rule matches on its own (a version two rules match is counted under both), "
            "so a rule can say how much it keeps."
        ),
    )
    max_deletions: int = MAX_DELETIONS_PER_RUN
    grace_days: int = Field(description="Days a deleted version can still be restored before it is purged.")
    pacticipants: List[PacticipantPlan] = Field(default_factory=list)


@dataclass
class _Decision:
    """The planner's working state for one pacticipant."""

    slug: str
    name: str
    versions: List[VersionFacts] = field(default_factory=list)


def _matching_rules(
    version: VersionFacts,
    keep: RetentionKeep,
    latest_id: str,
    keepers: Dict[str, set],
    cutoff: Optional[datetime],
) -> List[str]:
    """Every rule that keeps a version, in :data:`KEEP_REASONS` order; empty when the run deletes it."""
    tags = set(keep.tags)
    matched = {
        "latest": version.id == latest_id,
        "latest_per_branch": version.id in keepers["latest_per_branch"],
        "latest_per_main_branch": version.id in keepers["latest_per_main_branch"],
        "latest_per_other_branch": version.id in keepers["latest_per_other_branch"],
        "deployed_or_released": keep.deployed_or_released and version.in_use,
        "tagged": bool(tags and tags.intersection(version.tags)),
        "created_within_days": cutoff is not None and version.created_at >= cutoff,
    }
    return [reason for reason in KEEP_REASONS if matched[reason]]


def _branch_keepers(
    versions: Sequence[VersionFacts],
    per_branch: Optional[int],
    *,
    include: Optional[Callable[[str], bool]] = None,
    since: Optional[datetime] = None,
) -> set:
    """The ids of the newest ``per_branch`` versions of each branch.

    Args:
        versions: One pacticipant's live versions.
        per_branch: How many of each branch to keep; nothing when ``None``.
        include: Only the branches this accepts (all of them when ``None``).
        since: Only versions recorded at or after this time count as kept.

    Returns:
        The kept version ids.
    """
    if not per_branch:
        return set()
    by_branch: Dict[str, List[VersionFacts]] = {}
    for version in versions:
        for branch in version.branches:
            if include is None or include(branch):
                by_branch.setdefault(branch, []).append(version)
    keepers = set()
    for members in by_branch.values():
        for version in sorted(members, key=lambda v: v.seq, reverse=True)[:per_branch]:
            if since is None or version.created_at >= since:
                keepers.add(version.id)
    return keepers


def digest_of(keep: RetentionKeep, pacticipant_ids: Sequence[str], deletion_ids: Sequence[str]) -> str:
    """The digest that identifies one plan: its selectors, its scope and the versions it deletes.

    Args:
        keep: The keep selectors.
        pacticipant_ids: The pacticipants the run covers.
        deletion_ids: The versions the run deletes.

    Returns:
        ``sha256:<hex>``.
    """
    payload = json.dumps(
        {
            "keep": keep.model_dump(),
            "pacticipants": sorted(pacticipant_ids),
            "delete": sorted(deletion_ids),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _iso(value: datetime) -> str:
    """ISO-8601 text of a timestamp."""
    return value.isoformat()


def plan_retention(
    keep: RetentionKeep,
    pacticipants: Sequence[Tuple[str, str, str]],
    versions: Sequence[VersionFacts],
    *,
    now: Optional[datetime] = None,
    dry_run: bool = True,
    grace_days: int = 30,
    max_deletions: int = MAX_DELETIONS_PER_RUN,
    main_branches: Optional[Mapping[str, Optional[str]]] = None,
) -> Tuple[RetentionPlan, Dict[str, List[str]]]:
    """Decide which versions a run keeps and which it deletes.

    Args:
        keep: The keep selectors.
        pacticipants: ``(id, slug, name)`` of every pacticipant the run covers.
        versions: The live versions of those pacticipants.
        now: The current time (tests pin it).
        dry_run: Copied to the answer.
        grace_days: Copied to the answer.
        max_deletions: The cap on deletions (the oldest versions are deleted first).
        main_branches: Each pacticipant id's main branch. A pacticipant without one has no main
            branch: ``latest_per_main_branch`` keeps none of its versions, and every branch it has
            counts as an *other* branch.

    Returns:
        The plan (``applied`` false), and the version ids to delete per pacticipant id.

    Raises:
        RetentionError: ``pact-retention-no-selector`` when no selector would keep anything beyond
            each pacticipant's latest version.
    """
    if not keep.selects_anything():
        raise RetentionError(
            CODE_NO_SELECTOR,
            "a retention run needs at least one keep selector: latest_per_branch, latest_per_main_branch, "
            "latest_per_other_branch, tags, created_within_days, or deployed_or_released",
        )
    moment = now or datetime.now(timezone.utc)
    cutoff = moment - timedelta(days=keep.created_within_days) if keep.created_within_days else None
    other_since = moment - timedelta(days=keep.other_branch_days) if keep.other_branch_days else None
    mains = main_branches or {}

    decisions: Dict[str, _Decision] = {pid: _Decision(slug=slug, name=name) for pid, slug, name in pacticipants}
    for version in versions:
        if version.pacticipant_id in decisions:
            decisions[version.pacticipant_id].versions.append(version)

    candidates: List[Tuple[VersionFacts, str]] = []
    kept_by: Dict[str, Dict[str, int]] = {pid: {} for pid in decisions}
    matched_by: Dict[str, int] = {}
    for pid, decision in decisions.items():
        if not decision.versions:
            continue
        latest_id = max(decision.versions, key=lambda v: v.seq).id
        main = mains.get(pid)
        keepers = {
            "latest_per_branch": _branch_keepers(decision.versions, keep.latest_per_branch),
            "latest_per_main_branch": _branch_keepers(
                decision.versions, keep.latest_per_main_branch if main else None, include=lambda b: b == main
            ),
            "latest_per_other_branch": _branch_keepers(
                decision.versions, keep.latest_per_other_branch, include=lambda b: b != main, since=other_since
            ),
        }
        for version in decision.versions:
            rules = _matching_rules(version, keep, latest_id, keepers, cutoff)
            for rule in rules:
                matched_by[rule] = matched_by.get(rule, 0) + 1
            if not rules:
                candidates.append((version, pid))
            else:
                kept_by[pid][rules[0]] = kept_by[pid].get(rules[0], 0) + 1

    # The oldest first, so a capped run makes the deletions a later run would make anyway.
    candidates.sort(key=lambda item: item[0].seq)
    chosen, over = candidates[:max_deletions], candidates[max_deletions:]
    deletions: Dict[str, List[str]] = {}
    listed: Dict[str, List[PlannedDeletion]] = {pid: [] for pid in decisions}
    for version, pid in chosen:
        deletions.setdefault(pid, []).append(version.id)
        if len(listed[pid]) < MAX_LISTED_PER_PACTICIPANT:
            listed[pid].append(
                PlannedDeletion(
                    number=version.number, created_at=_iso(version.created_at), branches=list(version.branches)
                )
            )
    remaining: Dict[str, int] = {}
    for _version, pid in over:
        remaining[pid] = remaining.get(pid, 0) + 1

    rows = []
    for pid, decision in sorted(decisions.items(), key=lambda item: item[1].slug):
        rows.append(
            PacticipantPlan(
                slug=decision.slug,
                name=decision.name,
                evaluated=len(decision.versions),
                kept=sum(kept_by[pid].values()),
                deleted=len(deletions.get(pid, [])),
                remaining=remaining.get(pid, 0),
                kept_by={reason: kept_by[pid][reason] for reason in KEEP_REASONS if reason in kept_by[pid]},
                deletions=listed[pid],
            )
        )
    deleted_ids = [vid for ids in deletions.values() for vid in ids]
    plan = RetentionPlan(
        dry_run=dry_run,
        applied=False,
        plan_digest=digest_of(keep, list(decisions), deleted_ids),
        keep=keep,
        evaluated=sum(row.evaluated for row in rows),
        kept=sum(row.kept for row in rows),
        deleted=len(deleted_ids),
        remaining=len(over),
        matched_by={reason: matched_by[reason] for reason in KEEP_REASONS if reason in matched_by},
        max_deletions=max_deletions,
        grace_days=grace_days,
        pacticipants=rows,
    )
    return plan, deletions
