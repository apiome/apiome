"""In-memory stand-in for the GNC-2.2 (#4738) provider check-run accessors.

Extends :class:`tests.fake_binding_db.FakeBindingDb`, which already simulates projects, versions,
bindings, sync candidates, repository registrations and the RBAC guard — a check hangs off a
binding, so the two share one storage double.

The fake keeps the semantics apiome-db V265 and the SQL accessors promise:

* a check is identified by ``(binding_id, commit_sha, name)``, so recording the same verdict again
  moves one row rather than fanning out a second — the re-run idempotency;
* ``completed_at`` is derived from the state, never passed in, so the two can never disagree;
* a released binding, or one whose repository registration has been removed, records nothing;
* ``attempt`` advances only on an explicit re-run, and never decreases;
* a publish attempt with a fingerprint already on a check's ledger is refused, which is the
  publish-once guarantee;
* a dispatched attempt writes the provider's id back onto the check run;
* every write appends its ``check.*`` rows to :attr:`FakeBindingDb.workflow_audits` only when it
  succeeds, as the real accessors do inside their transaction.

The SQL text itself is exercised separately; this fake is for rules.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from app.provider_checks import (
    AUDIT_CHECK_PUBLISHED,
    AUDIT_CHECK_RECORDED,
    ORIGIN_API,
    STATE_PENDING,
)
from tests.fake_binding_db import FakeBindingDb


class FakeCheckDb(FakeBindingDb):
    """A storage double for provider check runs, on top of the binding double.

    Attributes:
        check_runs: Check rows by id.
        check_deliveries: Publish-attempt rows by id.
    """

    def __init__(self) -> None:
        """Create an empty store."""
        super().__init__()
        self.check_runs: Dict[str, Dict[str, Any]] = {}
        self.check_deliveries: Dict[str, Dict[str, Any]] = {}

    # -----------------------------------------------------------------------------------------
    # Row views
    # -----------------------------------------------------------------------------------------

    def _check_view(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """A check row as the SQL read returns it, with the joined columns."""
        view = dict(row)
        binding = self.bindings.get(row["binding_id"], {})
        version = self.versions.get(row["version_id"], {})
        view["version_label"] = version.get("version_id")
        view["ref"] = binding.get("ref")
        view["created_by_name"] = self.user_names.get(row.get("created_by") or "")
        latest = self._latest_delivery(row["id"])
        view["last_publish_outcome"] = latest["outcome"] if latest else None
        view["last_publish_error"] = latest["error_code"] if latest else None
        return view

    def _latest_delivery(self, check_id: str) -> Optional[Dict[str, Any]]:
        """The most recent publish attempt of a check, if there is one."""
        rows = [row for row in self.check_deliveries.values() if row["check_run_id"] == check_id]
        rows.sort(key=lambda row: row["created_at"], reverse=True)
        return rows[0] if rows else None

    def _find_check(
        self, binding_id: str, commit_sha: str, name: str
    ) -> Optional[Dict[str, Any]]:
        """The check a ``(binding, commit, name)`` triple identifies, if it exists."""
        for row in self.check_runs.values():
            if (
                row["binding_id"] == binding_id
                and row["commit_sha"] == commit_sha
                and row["name"] == name
            ):
                return row
        return None

    # -----------------------------------------------------------------------------------------
    # Reads
    # -----------------------------------------------------------------------------------------

    def get_provider_check_run(
        self, *, tenant_id: str, check_id: str
    ) -> Optional[Dict[str, Any]]:
        """One check run inside a tenant."""
        row = self.check_runs.get(check_id)
        return self._check_view(row) if row and row["tenant_id"] == tenant_id else None

    def list_provider_check_runs(
        self,
        *,
        tenant_id: str,
        project_id: Optional[str] = None,
        binding_id: Optional[str] = None,
        version_id: Optional[str] = None,
        commit_sha: Optional[str] = None,
        state: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """A tenant's check runs, newest first, narrowed by the filters given."""
        rows = [row for row in self.check_runs.values() if row["tenant_id"] == tenant_id]
        if project_id:
            rows = [row for row in rows if row["project_id"] == project_id]
        if binding_id:
            rows = [row for row in rows if row["binding_id"] == binding_id]
        if version_id:
            rows = [row for row in rows if row["version_id"] == version_id]
        if commit_sha:
            rows = [row for row in rows if row["commit_sha"] == commit_sha]
        if state:
            rows = [row for row in rows if row["state"] == state]
        rows.sort(key=lambda row: row["created_at"], reverse=True)
        return [self._check_view(row) for row in rows[offset : offset + limit]]

    def list_provider_check_deliveries(
        self, *, check_run_id: str, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """One check's publish attempts, newest first."""
        rows = [
            dict(row)
            for row in self.check_deliveries.values()
            if row["check_run_id"] == check_run_id
        ]
        rows.sort(key=lambda row: row["created_at"], reverse=True)
        return rows[:limit]

    def find_provider_check_delivery(
        self, *, check_run_id: str, request_fingerprint: str
    ) -> Optional[Dict[str, Any]]:
        """A publish attempt already on a check's ledger, if this verdict has gone out before."""
        for row in self.check_deliveries.values():
            if (
                row["check_run_id"] == check_run_id
                and row["request_fingerprint"] == request_fingerprint
            ):
                return dict(row)
        return None

    def find_authorized_bindings_for_check(
        self, *, repository_id: str, ref: str
    ) -> List[Dict[str, Any]]:
        """Active bindings of a repository's ref whose registration is intact, oldest first."""
        rows = [
            row
            for row in self.bindings.values()
            if row["repository_id"] == repository_id
            and row["ref"] == ref
            and row["released_at"] is None
        ]
        rows.sort(key=lambda row: row["created_at"])
        return [
            {
                "id": row["id"],
                "tenant_id": row["tenant_id"],
                "project_id": row["project_id"],
                "version_id": row["version_id"],
                "repository_id": row["repository_id"],
                "provider": row["provider"],
                "repo_full_name": row["repo_full_name"],
                "repo_url": row["repo_url"],
                "ref": row["ref"],
                "path": row["path"],
                "commit_sha": row["commit_sha"],
            }
            for row in rows
        ]

    # -----------------------------------------------------------------------------------------
    # Writes
    # -----------------------------------------------------------------------------------------

    def upsert_provider_check_run(
        self,
        *,
        tenant_id: str,
        binding_id: str,
        commit_sha: str,
        name: str,
        state: str,
        title: str = "",
        summary: str = "",
        details_url: str = "",
        pr_number: Optional[int] = None,
        origin: str = ORIGIN_API,
        delivery_id: Optional[str] = None,
        created_by: Optional[str] = None,
        rerun: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Record a verdict, creating the check or moving the one that already exists."""
        self._run_interleave()
        binding = self.bindings.get(binding_id)
        if (
            not binding
            or binding["tenant_id"] != tenant_id
            or binding["released_at"] is not None
            or not binding["repository_id"]
        ):
            return None

        now = self._tick()
        finished = state != STATE_PENDING
        existing = self._find_check(binding_id, commit_sha, name)
        if existing:
            existing.update(
                state=state,
                title=title,
                summary=summary,
                details_url=details_url,
                pr_number=(pr_number if pr_number is not None else existing["pr_number"]),
                attempt=existing["attempt"] + (1 if rerun else 0),
                started_at=(now if rerun else existing["started_at"]),
                completed_at=(now if finished else None),
                updated_at=now,
            )
            row, created = existing, False
        else:
            check_id = str(uuid.uuid4())
            row = {
                "id": check_id,
                "tenant_id": tenant_id,
                "binding_id": binding_id,
                "project_id": binding["project_id"],
                "version_id": binding["version_id"],
                "provider": binding["provider"],
                "repo_full_name": binding["repo_full_name"],
                "commit_sha": commit_sha,
                "pr_number": pr_number,
                "name": name,
                "state": state,
                "title": title,
                "summary": summary,
                "details_url": details_url,
                "external_id": None,
                "origin": origin,
                "delivery_id": delivery_id,
                "attempt": 1,
                "started_at": now,
                "completed_at": now if finished else None,
                "created_by": created_by,
                "created_at": now,
                "updated_at": now,
            }
            self.check_runs[check_id] = row
            created = True

        self._audit(
            tenant_id=tenant_id,
            project_id=binding["project_id"],
            version_id=binding["version_id"],
            action=AUDIT_CHECK_RECORDED,
            actor_id=created_by,
            detail={
                "check_id": row["id"],
                "binding_id": binding_id,
                "name": name,
                "commit_sha": commit_sha,
                "state": state,
                "origin": origin,
                "delivery_id": delivery_id,
                "attempt": row["attempt"],
                "created": created,
            },
        )
        return {
            "check_id": row["id"],
            "created": created,
            "state": row["state"],
            "attempt": row["attempt"],
        }

    def record_provider_check_delivery(
        self,
        *,
        tenant_id: str,
        check_run_id: str,
        provider: str,
        state: str,
        request_fingerprint: str,
        outcome: str,
        status_code: Optional[int] = None,
        external_id: Optional[str] = None,
        error_code: Optional[str] = None,
        error_message: str = "",
        actor_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Append one publish attempt, refusing a fingerprint already on this check's ledger."""
        check = self.check_runs.get(check_run_id)
        if not check or check["tenant_id"] != tenant_id:
            return None
        for row in self.check_deliveries.values():
            if (
                row["check_run_id"] == check_run_id
                and row["request_fingerprint"] == request_fingerprint
            ):
                return None

        delivery_id = str(uuid.uuid4())
        self.check_deliveries[delivery_id] = {
            "id": delivery_id,
            "check_run_id": check_run_id,
            "tenant_id": tenant_id,
            "provider": provider,
            "state": state,
            "request_fingerprint": request_fingerprint,
            "outcome": outcome,
            "status_code": status_code,
            "external_id": external_id,
            "error_code": error_code,
            "error_message": error_message or "",
            "created_at": self._tick(),
        }
        if external_id:
            check["external_id"] = external_id
            check["updated_at"] = self._tick()
        self._audit(
            tenant_id=tenant_id,
            project_id=check["project_id"],
            version_id=check["version_id"],
            action=AUDIT_CHECK_PUBLISHED,
            actor_id=actor_id,
            detail={
                "check_id": check_run_id,
                "delivery_id": delivery_id,
                "name": check["name"],
                "provider": provider,
                "state": state,
                "outcome": outcome,
                "status_code": status_code,
                "error_code": error_code,
            },
        )
        return {"delivery_id": delivery_id, "outcome": outcome}
