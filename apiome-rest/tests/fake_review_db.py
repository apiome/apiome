"""In-memory stand-in for the COL-2.1 (#4517) review accessors on ``app.database.Database``.

Extends :class:`tests.fake_comment_db.FakeCommentDb`, which already simulates projects, versions,
tenant members, administrators, and the RBAC guard — the review store resolves projects and
versions through the comment store, so both share one storage double.

The fake keeps the semantics apiome-db V261 and the SQL accessors promise:

* every review read is scoped by tenant *and* project, and a version has at most one open review;
* a list is ordered by ``updated_at`` descending, then id, and carries the current round's tally;
* reviewer rows are listed by round, then reviewer name;
* a write re-checks its guard (open, expected round, state) and changes nothing when it fails;
* a recorded decision is immutable — only a ``pending`` row of the current round takes a decision;
* each write appends its ``review.*`` rows to :attr:`FakeReviewDb.workflow_audits` only when it
  succeeds, as the real accessors do inside their transaction.

Two test hooks simulate what the real system does around the store:

* :meth:`change_spec` changes a version's content fingerprint (served by :meth:`spec_fingerprint`,
  which tests install in place of :func:`app.review_store.spec_fingerprint`);
* :attr:`interleave` runs once at the start of the next write, standing in for a concurrent
  writer that commits between the store's read and its write.
"""

from __future__ import annotations

import uuid
from typing import Any, Callable, Dict, List, Optional, Sequence

from app.review_lifecycle import (
    AUDIT_DECISION,
    AUDIT_RE_REQUESTED,
    AUDIT_REQUESTED,
    AUDIT_STATE_CHANGED,
    AUDIT_WITHDRAWN,
    DECISION_APPROVE,
    DECISION_PENDING,
    DECISION_REQUEST_CHANGES,
    STATE_DRAFT,
    STATE_IN_REVIEW,
    can_re_request,
    can_record_decision,
    state_after_decisions,
)
from tests.fake_comment_db import FakeCommentDb

#: The fingerprint a version has until :meth:`FakeReviewDb.change_spec` is called on it.
ORIGINAL_FINGERPRINT = "sha256:original"


class FakeReviewDb(FakeCommentDb):
    """A storage double for reviews, on top of the comment double.

    Attributes:
        reviews: Review rows by id.
        reviewer_rows: Reviewer rows by id.
        workflow_audits: The ``review.*`` audit rows written, in order.
        fingerprints: Current content fingerprint per version id.
        fingerprint_reads: How many times a version's fingerprint was computed.
        interleave: A callable run once at the start of the next write.
    """

    def __init__(self) -> None:
        """Create an empty store."""
        super().__init__()
        self.reviews: Dict[str, Dict[str, Any]] = {}
        self.reviewer_rows: Dict[str, Dict[str, Any]] = {}
        self.workflow_audits: List[Dict[str, Any]] = []
        self.fingerprints: Dict[str, str] = {}
        self.fingerprint_reads = 0
        self.interleave: Optional[Callable[[], None]] = None

    # -----------------------------------------------------------------------------------------
    # Test hooks
    # -----------------------------------------------------------------------------------------

    def publish(self, version_id: str) -> None:
        """Mark a version published."""
        self.versions[version_id]["published"] = True

    def change_spec(self, version_id: str) -> str:
        """Give a version new content, returning its new fingerprint."""
        self.fingerprints[version_id] = f"sha256:{uuid.uuid4().hex}"
        return self.fingerprints[version_id]

    def spec_fingerprint(self, tenant_id: str, version: Dict[str, Any]) -> str:
        """The version's current fingerprint; installed over ``review_store.spec_fingerprint``."""
        self.fingerprint_reads += 1
        return self.fingerprints.get(str(version["id"]), ORIGINAL_FINGERPRINT)

    def _run_interleave(self) -> None:
        """Run the pending concurrent-writer hook, once."""
        hook, self.interleave = self.interleave, None
        if hook:
            hook()

    # -----------------------------------------------------------------------------------------
    # Reads
    # -----------------------------------------------------------------------------------------

    def _round_rows(self, review_id: str, round_number: int) -> List[Dict[str, Any]]:
        """The raw reviewer rows of one round."""
        return [
            row
            for row in self.reviewer_rows.values()
            if row["review_id"] == review_id and row["round"] == round_number
        ]

    def _review_view(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """A review row as the SQL read returns it, with the current round's tally."""
        view = dict(row)
        view["version_label"] = self.versions.get(row["version_id"], {}).get("version_id")
        view["requested_by_name"] = self.user_names.get(row.get("requested_by") or "")
        decisions = [item["decision"] for item in self._round_rows(row["id"], row["round"])]
        view["reviewer_count"] = len(decisions)
        view["approved_count"] = decisions.count(DECISION_APPROVE)
        view["changes_requested_count"] = decisions.count(DECISION_REQUEST_CHANGES)
        view["pending_count"] = decisions.count(DECISION_PENDING)
        return view

    def _scoped_review(self, tenant_id: str, project_id: str, review_id: str) -> Optional[Dict[str, Any]]:
        """The raw review row when it belongs to the tenant's project."""
        row = self.reviews.get(review_id)
        if row and row["tenant_id"] == tenant_id and row["project_id"] == project_id:
            return row
        return None

    def get_review(self, *, tenant_id: str, project_id: str, review_id: str) -> Optional[Dict[str, Any]]:
        """One review of the tenant's project."""
        row = self._scoped_review(tenant_id, project_id, review_id)
        return self._review_view(row) if row else None

    def get_open_review_for_version(
        self, *, tenant_id: str, project_id: str, version_id: str
    ) -> Optional[Dict[str, Any]]:
        """The version's open review."""
        for row in self.reviews.values():
            if (
                row["tenant_id"] == tenant_id
                and row["project_id"] == project_id
                and row["version_id"] == version_id
                and row["closed_at"] is None
            ):
                return self._review_view(row)
        return None

    def _filtered_reviews(
        self,
        *,
        tenant_id: str,
        project_id: str,
        version_id: Optional[str] = None,
        state: Optional[str] = None,
        open_only: Optional[bool] = None,
    ) -> List[Dict[str, Any]]:
        """Reviews matching the list filters, in list order."""
        rows = []
        for row in self.reviews.values():
            if row["tenant_id"] != tenant_id or row["project_id"] != project_id:
                continue
            if version_id and row["version_id"] != version_id:
                continue
            if state and row["state"] != state:
                continue
            if open_only is True and row["closed_at"] is not None:
                continue
            if open_only is False and row["closed_at"] is None:
                continue
            rows.append(row)
        rows.sort(key=lambda r: r["id"])
        rows.sort(key=lambda r: r["updated_at"], reverse=True)
        return rows

    def list_reviews(self, *, limit: int = 50, offset: int = 0, **filters: Any) -> List[Dict[str, Any]]:
        """A page of reviews."""
        return [self._review_view(row) for row in self._filtered_reviews(**filters)[offset : offset + limit]]

    def count_reviews(self, **filters: Any) -> int:
        """How many reviews match the filters."""
        return len(self._filtered_reviews(**filters))

    def list_review_reviewers(self, *, review_id: str) -> List[Dict[str, Any]]:
        """Every reviewer row of a review, by round then reviewer name."""
        rows = []
        for row in self.reviewer_rows.values():
            if row["review_id"] == review_id:
                view = dict(row)
                view["user_name"] = self.user_names.get(row.get("user_id") or "")
                rows.append(view)
        rows.sort(key=lambda r: r["id"])
        rows.sort(key=lambda r: (r["user_name"] is None, r["user_name"] or ""))
        rows.sort(key=lambda r: r["round"])
        return rows

    # -----------------------------------------------------------------------------------------
    # Writes
    # -----------------------------------------------------------------------------------------

    def _audit(self, review: Dict[str, Any], action: str, actor_id: Optional[str], detail: Dict[str, Any]) -> None:
        """Append a ``review.*`` audit row."""
        self.workflow_audits.append(
            {
                "tenant_id": review["tenant_id"],
                "project_id": review["project_id"],
                "version_id": review["version_id"],
                "action": action,
                "outcome": "success",
                "actor_id": actor_id,
                "detail": detail,
            }
        )

    def _add_round(self, review_id: str, round_number: int, reviewer_ids: Sequence[str], now: Any) -> None:
        """Insert one pending row per reviewer for a round."""
        for user_id in reviewer_ids:
            row_id = str(uuid.uuid4())
            self.reviewer_rows[row_id] = {
                "id": row_id,
                "review_id": review_id,
                "round": round_number,
                "user_id": user_id,
                "decision": DECISION_PENDING,
                "note": None,
                "decided_at": None,
                "created_at": now,
            }

    def insert_review(
        self,
        *,
        tenant_id: str,
        project_id: str,
        version_id: str,
        requested_by: str,
        reviewer_ids: Sequence[str],
        spec_fingerprint: str,
        notify: Optional[Any] = None,
    ) -> Optional[str]:
        """Request a review; ``None`` when the version already has an open review."""
        self._run_interleave()
        if any(row["version_id"] == version_id and row["closed_at"] is None for row in self.reviews.values()):
            return None
        now = self._tick()
        review_id = str(uuid.uuid4())
        review = {
            "id": review_id,
            "tenant_id": tenant_id,
            "project_id": project_id,
            "version_id": version_id,
            "requested_by": requested_by,
            "state": STATE_IN_REVIEW,
            "round": 1,
            "spec_fingerprint": spec_fingerprint,
            "created_at": now,
            "updated_at": now,
            "closed_at": None,
            "closed_by": None,
        }
        self.reviews[review_id] = review
        self._add_round(review_id, 1, reviewer_ids, now)
        self._audit(
            review,
            AUDIT_REQUESTED,
            requested_by,
            {
                "review_id": review_id,
                "round": 1,
                "from_state": STATE_DRAFT,
                "to_state": STATE_IN_REVIEW,
                "reviewers": list(reviewer_ids),
                "spec_fingerprint": spec_fingerprint,
            },
        )
        self._fan_out(tenant_id, notify, {"review_id": review_id, "round": 1})
        return review_id

    def _open_review(self, tenant_id: str, project_id: str, review_id: str) -> Optional[Dict[str, Any]]:
        """The raw review row when it is open in the tenant's project."""
        row = self._scoped_review(tenant_id, project_id, review_id)
        return row if row and row["closed_at"] is None else None

    def re_request_review(
        self,
        *,
        tenant_id: str,
        project_id: str,
        review_id: str,
        expected_round: int,
        reviewer_ids: Sequence[str],
        spec_fingerprint: str,
        actor_id: str,
        notify: Optional[Any] = None,
    ) -> Optional[Dict[str, Any]]:
        """Start the next round; ``None`` when the guard fails."""
        self._run_interleave()
        review = self._open_review(tenant_id, project_id, review_id)
        if not review or review["round"] != expected_round or not can_re_request(review["state"]):
            return None
        now = self._tick()
        from_state = review["state"]
        next_round = review["round"] + 1
        review.update(state=STATE_IN_REVIEW, round=next_round, spec_fingerprint=spec_fingerprint, updated_at=now)
        self._add_round(review_id, next_round, reviewer_ids, now)
        self._audit(
            review,
            AUDIT_RE_REQUESTED,
            actor_id,
            {
                "review_id": review_id,
                "round": next_round,
                "previous_round": expected_round,
                "from_state": from_state,
                "to_state": STATE_IN_REVIEW,
                "reviewers": list(reviewer_ids),
                "spec_fingerprint": spec_fingerprint,
            },
        )
        self._fan_out(tenant_id, notify, {"review_id": review_id, "round": next_round})
        return {"round": next_round, "from_state": from_state}

    def record_review_decision(
        self,
        *,
        tenant_id: str,
        project_id: str,
        review_id: str,
        expected_round: int,
        user_id: str,
        decision: str,
        note: Optional[str],
        notify: Optional[Any] = None,
    ) -> Optional[Dict[str, Any]]:
        """Record a decision and fold the round; ``None`` when the guard fails."""
        self._run_interleave()
        review = self._open_review(tenant_id, project_id, review_id)
        if not review or review["round"] != expected_round or not can_record_decision(review["state"]):
            return None
        rows = self._round_rows(review_id, expected_round)
        mine = next((row for row in rows if row["user_id"] == user_id), None)
        if mine is None or mine["decision"] != DECISION_PENDING:
            return None
        now = self._tick()
        mine.update(decision=decision, note=note, decided_at=now)
        from_state = review["state"]
        to_state = state_after_decisions(row["decision"] for row in rows)
        review.update(state=to_state, updated_at=now)
        self._audit(
            review,
            AUDIT_DECISION,
            user_id,
            {
                "review_id": review_id,
                "round": expected_round,
                "reviewer": user_id,
                "decision": decision,
                "has_note": note is not None,
            },
        )
        if to_state != from_state:
            self._audit(
                review,
                AUDIT_STATE_CHANGED,
                user_id,
                {"review_id": review_id, "round": expected_round, "from_state": from_state, "to_state": to_state},
            )
        self._fan_out(
            tenant_id,
            notify,
            {
                "review_id": review_id,
                "round": expected_round,
                "decision": decision,
                "from_state": from_state,
                "to_state": to_state,
            },
        )
        return {"from_state": from_state, "to_state": to_state}

    def withdraw_review(self, *, tenant_id: str, project_id: str, review_id: str, actor_id: str) -> bool:
        """Close an open review."""
        self._run_interleave()
        review = self._open_review(tenant_id, project_id, review_id)
        if not review:
            return False
        now = self._tick()
        review.update(closed_at=now, closed_by=actor_id, updated_at=now)
        self._audit(
            review,
            AUDIT_WITHDRAWN,
            actor_id,
            {"review_id": review_id, "round": review["round"], "state": review["state"]},
        )
        return True
