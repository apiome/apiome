"""In-memory stand-in for the GNC-3.1 (#4740) API change check suite accessors.

Extends :class:`tests.fake_sync_db.FakeSyncDb`, which already simulates projects, versions,
bindings, sync candidates, repository registrations, provider checks and the RBAC guard — an
evaluation is reported through a binding's check, so they all share one storage double.

The fake keeps the semantics apiome-db V267 and the SQL accessors promise:

* an evaluation is identified by ``(version_id, input_fingerprint)``, so evaluating the same inputs
  again collides and writes nothing — the re-run idempotency;
* evaluations are append-only: the fake has no update path at all;
* a placeholder (``evaluated = False``) may only be ``pending`` or ``skipped``, and a binding always
  names a commit — the V267 CHECKs, raised as ``ValueError``;
* the policy has two scopes and the project override wins, as the one-query read resolves it;
* a new evaluation appends one ``check_suite.evaluated`` row to
  :attr:`FakeBindingDb.workflow_audits`; a collision appends none.

It also supplies the reads the suite makes of neighbouring tickets' storage — the CTG-4.5
deploy-gate policy, the prior published baseline, and ECA-1.3 runs by revision — each as plain data
a test seeds. The SQL text itself is exercised separately; this fake is for rules.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional, Tuple

from app.api_check_suite import AUDIT_SUITE_EVALUATED
from tests.fake_sync_db import FakeSyncDb


class FakeSuiteDb(FakeSyncDb):
    """A storage double for check-suite evaluations and policies, on top of the sync double.

    Attributes:
        suite_policies: Policy rows by ``(tenant_id, project_id or None)``.
        suite_runs: Evaluation rows by id.
        gate_policies: CTG-4.5 deploy-gate policy rows by ``(tenant_id, project_id or None)``.
        baselines: The prior published revision id, by version id.
        verification_runs: ECA-1.3 run rows, newest last.
    """

    def __init__(self) -> None:
        """Create an empty store."""
        super().__init__()
        self.suite_policies: Dict[Tuple[str, Optional[str]], Dict[str, Any]] = {}
        self.suite_runs: Dict[str, Dict[str, Any]] = {}
        self.gate_policies: Dict[Tuple[str, Optional[str]], Dict[str, Any]] = {}
        self.baselines: Dict[str, str] = {}
        self.verification_runs: List[Dict[str, Any]] = []

    # -----------------------------------------------------------------------------------------
    # Neighbouring reads
    # -----------------------------------------------------------------------------------------

    def get_deploy_gate_policy(
        self, tenant_id: str, project_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """The CTG-4.5 policy in force: the project override, else the tenant row."""
        return self.gate_policies.get((tenant_id, project_id)) or self.gate_policies.get(
            (tenant_id, None)
        )

    def upsert_deploy_gate_policy(
        self,
        *,
        tenant_id: str,
        project_id: Optional[str],
        thresholds: Dict[str, Any],
        content_fingerprint: str,
        actor_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Save one scope's CTG-4.5 thresholds in place."""
        row = {
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "project_id": project_id,
            "thresholds": dict(thresholds),
            "content_fingerprint": content_fingerprint,
            "updated_by": actor_id,
            "updated_at": self._tick(),
        }
        self.gate_policies[(tenant_id, project_id)] = row
        return dict(row)

    def get_prior_published_baseline_revision_id(
        self, project_id: str, tenant_id: str, head_revision_id: str
    ) -> Optional[str]:
        """The previous published revision on the line, as a test seeded it."""
        return self.baselines.get(head_revision_id)

    def list_verification_runs_for_revision(
        self, tenant_id: str, revision_id: str, *, limit: int = 1
    ) -> List[Dict[str, Any]]:
        """A revision's contract runs, newest first — matched on ``source.revision_id``."""
        rows = [
            dict(row)
            for row in self.verification_runs
            if row["tenant_id"] == tenant_id
            and (row.get("source") or {}).get("revision_id") == revision_id
        ]
        rows.sort(key=lambda row: row["created_at"], reverse=True)
        return rows[: max(1, int(limit))]

    def add_verification_run(
        self,
        tenant_id: str,
        revision_id: str,
        *,
        outcome: str = "passed",
        suite_digest: str = "sha256:suite",
        reference: str = "project/pets/1.0.0",
    ) -> Dict[str, Any]:
        """Record one contract run of a revision."""
        now = self._tick()
        row = {
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "suite_digest": suite_digest,
            "outcome": outcome,
            "target_slug": "staging",
            "finished_at": now,
            "created_at": now,
            "total_cases": 3,
            "passed_cases": 3 if outcome == "passed" else 1,
            "failed_cases": 0 if outcome == "passed" else 2,
            "errored_cases": 0,
            "skipped_cases": 0,
            "source": {"revision_id": revision_id, "reference": reference},
        }
        self.verification_runs.append(row)
        return row

    # -----------------------------------------------------------------------------------------
    # Policy
    # -----------------------------------------------------------------------------------------

    def get_check_suite_policy(
        self, tenant_id: str, project_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """The suite policy in force: the project override, else the tenant row."""
        row = None
        if project_id is not None:
            row = self.suite_policies.get((tenant_id, project_id))
        row = row or self.suite_policies.get((tenant_id, None))
        return dict(row) if row else None

    def upsert_check_suite_policy(
        self,
        *,
        tenant_id: str,
        project_id: Optional[str],
        policy: Dict[str, Any],
        content_fingerprint: str,
        actor_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Save one scope's policy in place."""
        key = (tenant_id, project_id)
        now = self._tick()
        row = self.suite_policies.get(key) or {
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "project_id": project_id,
            "created_by": actor_id,
            "created_at": now,
        }
        row.update(
            policy=dict(policy),
            content_fingerprint=content_fingerprint,
            updated_by=actor_id,
            updated_at=now,
        )
        self.suite_policies[key] = row
        return dict(row)

    def delete_check_suite_policy(self, tenant_id: str, project_id: Optional[str] = None) -> int:
        """Remove exactly one scope's policy."""
        return 1 if self.suite_policies.pop((tenant_id, project_id), None) else 0

    # -----------------------------------------------------------------------------------------
    # Evaluations
    # -----------------------------------------------------------------------------------------

    def _run_view(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """An evaluation row as the SQL read returns it, with the joined columns."""
        view = dict(row)
        view["version_label"] = self.versions.get(row["version_id"], {}).get("version_id")
        view["created_by_name"] = self.user_names.get(row.get("created_by") or "")
        return view

    def insert_check_suite_run(self, **fields: Any) -> Optional[Dict[str, Any]]:
        """Append an evaluation, or collide with the identical one."""
        self._run_interleave()
        if not fields["evaluated"] and fields["state"] not in ("pending", "skipped"):
            raise ValueError("api_check_suite_runs_placeholder_check")
        if (fields.get("binding_id") is None) != (fields.get("commit_sha") is None):
            raise ValueError("api_check_suite_runs_binding_commit_check")
        for row in self.suite_runs.values():
            if (
                row["version_id"] == fields["version_id"]
                and row["input_fingerprint"] == fields["input_fingerprint"]
            ):
                return None
        run_id = str(uuid.uuid4())
        self.suite_runs[run_id] = {**fields, "id": run_id, "created_at": self._tick()}
        self._audit(
            tenant_id=fields["tenant_id"],
            project_id=fields["project_id"],
            version_id=fields["version_id"],
            action=AUDIT_SUITE_EVALUATED,
            actor_id=fields.get("created_by"),
            detail={"run_id": run_id, "state": fields["state"], "reason": fields["reason"]},
        )
        return {"id": run_id}

    def get_check_suite_run(self, *, tenant_id: str, run_id: str) -> Optional[Dict[str, Any]]:
        """One evaluation inside a tenant."""
        row = self.suite_runs.get(run_id)
        return self._run_view(row) if row and row["tenant_id"] == tenant_id else None

    def find_check_suite_run(
        self, *, tenant_id: str, version_id: str, input_fingerprint: str
    ) -> Optional[Dict[str, Any]]:
        """The evaluation of exactly these inputs."""
        for row in self.suite_runs.values():
            if (
                row["tenant_id"] == tenant_id
                and row["version_id"] == version_id
                and row["input_fingerprint"] == input_fingerprint
            ):
                return self._run_view(row)
        return None

    def list_check_suite_runs(
        self,
        *,
        tenant_id: str,
        version_id: str,
        commit_sha: Optional[str] = None,
        evaluated: Optional[bool] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """A version's evaluations, newest first."""
        rows = [
            row
            for row in self.suite_runs.values()
            if row["tenant_id"] == tenant_id
            and row["version_id"] == version_id
            and (commit_sha is None or row.get("commit_sha") == commit_sha)
            and (evaluated is None or bool(row["evaluated"]) == evaluated)
        ]
        rows.sort(key=lambda row: row["created_at"], reverse=True)
        return [self._run_view(row) for row in rows[offset : offset + max(1, int(limit))]]

    def find_current_check_suite_run(
        self,
        *,
        tenant_id: str,
        version_id: str,
        draft_digest: str,
        policy_fingerprint: str,
        thresholds_fingerprint: str,
    ) -> Optional[Dict[str, Any]]:
        """The newest judged evaluation of exactly this content under exactly these policies."""
        for row in self.list_check_suite_runs(
            tenant_id=tenant_id, version_id=version_id, evaluated=True, limit=10_000
        ):
            if (
                row["draft_digest"] == draft_digest
                and row["policy_fingerprint"] == policy_fingerprint
                and row["thresholds_fingerprint"] == thresholds_fingerprint
            ):
                return row
        return None
