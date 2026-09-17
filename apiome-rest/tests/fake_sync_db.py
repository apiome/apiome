"""In-memory stand-in for the GNC-2.3 (#4739) three-way synchronization accessors.

Extends :class:`tests.fake_check_db.FakeCheckDb`, which already simulates projects, versions,
bindings, sync candidates, repository registrations, provider checks and the RBAC guard — a merge
result hangs off a binding, so they all share one storage double.

The fake keeps the semantics apiome-db V266 and the SQL accessors promise:

* a plan is identified by ``(binding_id, plan_fingerprint)``, so merging the same three documents
  again finds the stored row rather than writing a second answer — the rerun idempotency;
* a plan and its conflicts appear together or not at all, because a merge result whose conflicts
  are missing would read as clean;
* a conflict is settled exactly once, and the plan's ``unresolved_count`` is recomputed from the
  rows rather than decremented, so the status is always derived and never accumulated;
* ``conflict_count`` is what the merge found and never moves afterwards;
* every write appends its ``sync.*`` rows to :attr:`FakeBindingDb.workflow_audits` only when it
  succeeds, as the real accessors do inside their transaction;
* **nothing here touches a version.** The double has no path from a merge to a draft, because
  neither does the schema.

It also supplies the two review accessors the guard consults
(:func:`app.spec_sync_store._guard_for`), which the comment double does not need.

The SQL text itself is exercised separately; this fake is for rules.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from app.spec_sync import (
    AUDIT_CONFLICT_RESOLVED,
    AUDIT_PLANNED,
    STATUS_CONFLICTED,
    STATUS_RESOLVED,
)
from tests.fake_check_db import FakeCheckDb


class FakeSyncDb(FakeCheckDb):
    """A storage double for three-way merge results, on top of the check double.

    Attributes:
        sync_plans: Plan rows by id.
        sync_conflicts: Conflict rows by id.
        open_reviews: Open review rows by version id, for the guard.
        review_reviewers: Reviewer decision rows by review id, for the guard.
    """

    def __init__(self) -> None:
        """Create an empty store."""
        super().__init__()
        self.sync_plans: Dict[str, Dict[str, Any]] = {}
        self.sync_conflicts: Dict[str, Dict[str, Any]] = {}
        self.open_reviews: Dict[str, Dict[str, Any]] = {}
        self.review_reviewers: Dict[str, List[Dict[str, Any]]] = {}

    # -----------------------------------------------------------------------------------------
    # Test hooks
    # -----------------------------------------------------------------------------------------

    def open_review(
        self,
        version_id: str,
        review_id: str,
        *,
        round_number: int = 1,
        decisions: Optional[List[str]] = None,
    ) -> None:
        """Put an open review on a version, with the decisions of its current round.

        Args:
            version_id: The version under review.
            review_id: The review id.
            round_number: The current round.
            decisions: One ``decision`` per reviewer of that round.
        """
        self.open_reviews[version_id] = {"id": review_id, "round": round_number}
        self.review_reviewers[review_id] = [
            {"round": round_number, "decision": decision} for decision in (decisions or [])
        ]

    # -----------------------------------------------------------------------------------------
    # Review surface the synchronization guard consults
    # -----------------------------------------------------------------------------------------

    def get_open_review_for_version(
        self, *, tenant_id: str, project_id: str, version_id: str
    ) -> Optional[Dict[str, Any]]:
        """The version's open review, if it has one."""
        row = self.open_reviews.get(version_id)
        return dict(row) if row else None

    def list_review_reviewers(self, *, review_id: str) -> List[Dict[str, Any]]:
        """Every reviewer row of a review."""
        return [dict(row) for row in self.review_reviewers.get(review_id, [])]

    # -----------------------------------------------------------------------------------------
    # Row views
    # -----------------------------------------------------------------------------------------

    def _plan_view(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """A plan row as the SQL read returns it, with the joined columns."""
        view = dict(row)
        view["computed_by_name"] = self.user_names.get(row.get("computed_by") or "")
        return view

    def _conflict_view(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """A conflict row as the SQL read returns it, with the joined columns."""
        view = dict(row)
        view["resolved_by_name"] = self.user_names.get(row.get("resolved_by") or "")
        return view

    # -----------------------------------------------------------------------------------------
    # Reads
    # -----------------------------------------------------------------------------------------

    def find_draft_sync_plan(
        self, *, tenant_id: str, binding_id: str, plan_fingerprint: str
    ) -> Optional[Dict[str, Any]]:
        """The stored merge of one binding's three documents, by its rerun key."""
        for row in self.sync_plans.values():
            if (
                row["tenant_id"] == tenant_id
                and row["binding_id"] == binding_id
                and row["plan_fingerprint"] == plan_fingerprint
            ):
                return self._plan_view(row)
        return None

    def get_draft_sync_plan(
        self, *, tenant_id: str, project_id: str, plan_id: str
    ) -> Optional[Dict[str, Any]]:
        """One merge result inside a tenant's project."""
        row = self.sync_plans.get(plan_id)
        if row and row["tenant_id"] == tenant_id and row["project_id"] == project_id:
            return self._plan_view(row)
        return None

    def list_draft_sync_plans(
        self, *, tenant_id: str, version_id: str, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """A version's merge results, newest first."""
        rows = [
            row
            for row in self.sync_plans.values()
            if row["tenant_id"] == tenant_id and row["version_id"] == version_id
        ]
        rows.sort(key=lambda row: row["created_at"], reverse=True)
        return [self._plan_view(row) for row in rows[: max(1, int(limit))]]

    def list_draft_sync_conflicts(self, *, tenant_id: str, plan_id: str) -> List[Dict[str, Any]]:
        """One plan's conflicts, outstanding ones first and then in pointer order."""
        rows = [
            row
            for row in self.sync_conflicts.values()
            if row["tenant_id"] == tenant_id and row["plan_id"] == plan_id
        ]
        rows.sort(key=lambda row: (row["resolution"] is not None, row["pointer"]))
        return [self._conflict_view(row) for row in rows]

    def get_draft_sync_conflict(
        self, *, tenant_id: str, plan_id: str, conflict_id: str
    ) -> Optional[Dict[str, Any]]:
        """One conflict of one plan."""
        row = self.sync_conflicts.get(conflict_id)
        if row and row["tenant_id"] == tenant_id and row["plan_id"] == plan_id:
            return self._conflict_view(row)
        return None

    # -----------------------------------------------------------------------------------------
    # Writes
    # -----------------------------------------------------------------------------------------

    def record_draft_sync_plan(
        self,
        *,
        tenant_id: str,
        project_id: str,
        version_id: str,
        binding_id: str,
        candidate_id: Optional[str],
        base_commit_sha: str,
        base_digest: str,
        git_commit_sha: str,
        git_digest: str,
        draft_digest: str,
        plan_fingerprint: str,
        status: str,
        auto_applied_count: int,
        local_count: int,
        agreed_count: int,
        changes: List[Dict[str, Any]],
        conflicts: List[Dict[str, Any]],
        conflicts_truncated: bool,
        source_file: str,
        source_member_count: int,
        guard: str,
        actor_id: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        """Store one merge result and its conflicts, or return the one already stored."""
        self._run_interleave()
        existing = self.find_draft_sync_plan(
            tenant_id=tenant_id, binding_id=binding_id, plan_fingerprint=plan_fingerprint
        )
        if existing:
            return {"plan_id": str(existing["id"]), "created": False}

        now = self._tick()
        plan_id = str(uuid.uuid4())
        self.sync_plans[plan_id] = {
            "id": plan_id,
            "tenant_id": tenant_id,
            "binding_id": binding_id,
            "project_id": project_id,
            "version_id": version_id,
            "candidate_id": candidate_id,
            "base_commit_sha": base_commit_sha,
            "base_digest": base_digest,
            "git_commit_sha": git_commit_sha,
            "git_digest": git_digest,
            "draft_digest": draft_digest,
            "plan_fingerprint": plan_fingerprint,
            "status": status,
            "auto_applied_count": auto_applied_count,
            "local_count": local_count,
            "agreed_count": agreed_count,
            "conflict_count": len(conflicts),
            "unresolved_count": len(conflicts),
            "conflicts_truncated": bool(conflicts_truncated),
            "changes": list(changes),
            "source_file": source_file,
            "source_member_count": source_member_count,
            "guard": guard,
            "computed_by": actor_id,
            "created_at": now,
            "updated_at": now,
        }
        for conflict in conflicts:
            conflict_id = str(uuid.uuid4())
            self.sync_conflicts[conflict_id] = {
                "id": conflict_id,
                "plan_id": plan_id,
                "tenant_id": tenant_id,
                "pointer": conflict.get("pointer", ""),
                "scope": conflict.get("scope", "document"),
                "group_key": conflict.get("group_key", ""),
                "label": conflict.get("label", ""),
                "git_kind": conflict.get("git_kind", "update"),
                "draft_kind": conflict.get("draft_kind", "update"),
                "base_value": conflict.get("base_value"),
                "git_value": conflict.get("git_value"),
                "draft_value": conflict.get("draft_value"),
                "source_file": conflict.get("source_file", ""),
                "source_line": conflict.get("source_line"),
                "source_url": conflict.get("source_url", ""),
                "resolution": None,
                "resolved_at": None,
                "resolved_by": None,
                "resolution_note": None,
                "created_at": self._tick(),
            }
        self._audit(
            tenant_id=tenant_id,
            project_id=project_id,
            version_id=version_id,
            action=AUDIT_PLANNED,
            actor_id=actor_id,
            detail={
                "plan_id": plan_id,
                "binding_id": binding_id,
                "candidate_id": candidate_id,
                "base_commit_sha": base_commit_sha,
                "git_commit_sha": git_commit_sha,
                "draft_digest": draft_digest,
                "status": status,
                "auto_applied_count": auto_applied_count,
                "conflict_count": len(conflicts),
                "conflicts_truncated": bool(conflicts_truncated),
                "guard": guard,
            },
        )
        return {"plan_id": plan_id, "created": True}

    def resolve_draft_sync_conflict(
        self,
        *,
        tenant_id: str,
        project_id: str,
        plan_id: str,
        conflict_id: str,
        resolution: str,
        actor_id: str,
        note: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Settle one conflict, and move the plan on when it was the last."""
        self._run_interleave()
        plan = self.sync_plans.get(plan_id)
        if not plan or plan["tenant_id"] != tenant_id or plan["project_id"] != project_id:
            return None
        row = self.sync_conflicts.get(conflict_id)
        if not row or row["plan_id"] != plan_id or row["tenant_id"] != tenant_id:
            return None
        if row["resolution"] is not None:
            return None
        row.update(
            resolution=resolution,
            resolved_at=self._tick(),
            resolved_by=actor_id,
            resolution_note=note,
        )
        outstanding = sum(
            1
            for other in self.sync_conflicts.values()
            if other["plan_id"] == plan_id and other["resolution"] is None
        )
        status = STATUS_CONFLICTED if outstanding else STATUS_RESOLVED
        plan.update(unresolved_count=outstanding, status=status, updated_at=self._tick())
        self._audit(
            tenant_id=tenant_id,
            project_id=project_id,
            version_id=plan["version_id"],
            action=AUDIT_CONFLICT_RESOLVED,
            actor_id=actor_id,
            detail={
                "plan_id": plan_id,
                "binding_id": plan["binding_id"],
                "conflict_id": conflict_id,
                "pointer": row["pointer"],
                "resolution": resolution,
                "status": status,
                "unresolved_count": outstanding,
            },
        )
        return {
            "conflict_id": conflict_id,
            "resolution": resolution,
            "status": status,
            "unresolved_count": outstanding,
        }
