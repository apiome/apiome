"""In-memory stand-in for the GNC-2.1 (#4737) branch-to-draft binding accessors.

Extends :class:`tests.fake_comment_db.FakeCommentDb`, which already simulates projects, versions,
tenant members, administrators, and the RBAC guard — the binding store resolves projects and
versions through the comment store, so both share one storage double.

The fake keeps the semantics apiome-db V264 and the SQL accessors promise:

* every binding read is scoped by tenant *and* project, and a version has at most one **active**
  binding (``released_at IS NULL``);
* releasing keeps the row and supersedes its outstanding candidates, exactly as the accessor does;
* what a binding *names* never changes — a re-bind releases and inserts, it never rewrites;
* raising a candidate is idempotent twice over (one pending row per target commit, one row per
  provider delivery), refuses a released binding, refuses a commit the binding is already at, and
  supersedes any older pending candidate so at most one is decidable;
* settling moves a ``pending`` row exactly once, and ``applied`` advances the binding's
  synchronized pair;
* each write appends its ``binding.*`` rows to :attr:`FakeBindingDb.workflow_audits` only when it
  succeeds, as the real accessors do inside their transaction.

:attr:`interleave` runs once at the start of the next write, standing in for a concurrent writer
that commits between the store's read and its write. The SQL text itself is exercised separately
(``tests/test_draft_binding_database_accessors.py`` pins the transaction semantics against a
scripted connection); this fake is for rules.
"""

from __future__ import annotations

import uuid
from typing import Any, Callable, Dict, List, Optional

from app.draft_bindings import (
    AUDIT_BOUND,
    AUDIT_CANDIDATE_RAISED,
    AUDIT_CANDIDATE_RESOLVED,
    AUDIT_REBOUND,
    AUDIT_RELEASED,
    RELEASE_REASON_REPLACED,
    RELEASE_REASON_REPOSITORY_REMOVED,
    STATUS_APPLIED,
    STATUS_PENDING,
    STATUS_SUPERSEDED,
)
from tests.fake_comment_db import FakeCommentDb


class FakeBindingDb(FakeCommentDb):
    """A storage double for branch-to-draft bindings, on top of the comment double.

    Attributes:
        bindings: Binding rows by id.
        candidates: Sync-candidate rows by id.
        repositories: Registered repository rows by id.
        workflow_audits: The ``binding.*`` audit rows written, in order.
        interleave: A callable run once at the start of the next write.
    """

    def __init__(self) -> None:
        """Create an empty store."""
        super().__init__()
        self.bindings: Dict[str, Dict[str, Any]] = {}
        self.candidates: Dict[str, Dict[str, Any]] = {}
        self.repositories: Dict[str, Dict[str, Any]] = {}
        self.workflow_audits: List[Dict[str, Any]] = []
        self.interleave: Optional[Callable[[], None]] = None

    # -----------------------------------------------------------------------------------------
    # Test hooks
    # -----------------------------------------------------------------------------------------

    def publish(self, version_id: str) -> None:
        """Mark a version published."""
        self.versions[version_id]["published"] = True

    def add_repository(
        self,
        tenant_id: str,
        repository_id: str,
        *,
        clone_url: str = "https://github.com/acme/specs",
        default_branch: str = "main",
        linked_account_id: Optional[str] = None,
        created_by: Optional[str] = None,
    ) -> None:
        """Register a tenant repository."""
        self.repositories[repository_id] = {
            "id": repository_id,
            "tenant_id": tenant_id,
            "clone_url": clone_url,
            "default_branch": default_branch,
            "linked_account_id": linked_account_id,
            "created_by": created_by,
        }

    def _run_interleave(self) -> None:
        """Run the one-shot concurrent-writer hook, if one is armed."""
        hook, self.interleave = self.interleave, None
        if hook:
            hook()

    def _audit(
        self,
        *,
        tenant_id: str,
        project_id: str,
        version_id: str,
        action: str,
        actor_id: Optional[str],
        detail: Dict[str, Any],
    ) -> None:
        """Append one ``binding.*`` audit row, as the accessors do inside their transaction."""
        self.workflow_audits.append(
            {
                "tenant_id": tenant_id,
                "project_id": project_id,
                "version_id": version_id,
                "action": action,
                "actor_id": actor_id,
                "detail": detail,
            }
        )

    # -----------------------------------------------------------------------------------------
    # Repository registration
    # -----------------------------------------------------------------------------------------

    def get_tenant_repository(self, tenant_id: str, repository_id: str) -> Optional[Dict[str, Any]]:
        """A registered repository of the tenant, by id."""
        row = self.repositories.get(repository_id)
        return dict(row) if row and row["tenant_id"] == tenant_id else None

    def delete_tenant_repository(self, tenant_id: str, repository_id: str) -> bool:
        """De-register a repository, releasing every binding it authorized."""
        row = self.repositories.pop(repository_id, None)
        if not row or row["tenant_id"] != tenant_id:
            return False
        for binding in list(self.bindings.values()):
            if binding["repository_id"] == repository_id and binding["released_at"] is None:
                self._release(binding, actor_id=None, reason=RELEASE_REASON_REPOSITORY_REMOVED)
        return True

    # -----------------------------------------------------------------------------------------
    # Row views
    # -----------------------------------------------------------------------------------------

    def _binding_view(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """A binding row as the SQL read returns it."""
        view = dict(row)
        version = self.versions.get(row["version_id"], {})
        view["version_label"] = version.get("version_id")
        view["created_by_name"] = self.user_names.get(row.get("created_by") or "")
        view["active"] = row["released_at"] is None
        view["pending_candidate_count"] = sum(
            1
            for c in self.candidates.values()
            if c["binding_id"] == row["id"] and c["status"] == STATUS_PENDING
        )
        return view

    def _candidate_view(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """A candidate row as the SQL read returns it."""
        view = dict(row)
        view["detected_by_name"] = self.user_names.get(row.get("detected_by") or "")
        view["resolved_by_name"] = self.user_names.get(row.get("resolved_by") or "")
        return view

    def _active_binding(self, tenant_id: str, version_id: str) -> Optional[Dict[str, Any]]:
        """The raw active binding row of a version, if any."""
        for row in self.bindings.values():
            if (
                row["version_id"] == version_id
                and row["tenant_id"] == tenant_id
                and row["released_at"] is None
            ):
                return row
        return None

    # -----------------------------------------------------------------------------------------
    # Binding reads
    # -----------------------------------------------------------------------------------------

    def get_draft_binding(
        self, *, tenant_id: str, project_id: str, binding_id: str
    ) -> Optional[Dict[str, Any]]:
        """One binding inside a tenant's project."""
        row = self.bindings.get(binding_id)
        if row and row["tenant_id"] == tenant_id and row["project_id"] == project_id:
            return self._binding_view(row)
        return None

    def get_active_draft_binding(
        self, *, tenant_id: str, project_id: str, version_id: str
    ) -> Optional[Dict[str, Any]]:
        """A version's active binding, if it has one."""
        row = self._active_binding(tenant_id, version_id)
        return self._binding_view(row) if row and row["project_id"] == project_id else None

    def _filtered_bindings(
        self,
        tenant_id: str,
        project_id: str,
        version_id: Optional[str],
        active: Optional[bool],
    ) -> List[Dict[str, Any]]:
        """The bindings a list/count read matches, newest first."""
        rows = [
            row
            for row in self.bindings.values()
            if row["tenant_id"] == tenant_id
            and row["project_id"] == project_id
            and (version_id is None or row["version_id"] == version_id)
            and (active is None or (row["released_at"] is None) is active)
        ]
        rows.sort(key=lambda row: (row["created_at"], row["id"]), reverse=True)
        return rows

    def list_draft_bindings(
        self,
        *,
        tenant_id: str,
        project_id: str,
        version_id: Optional[str] = None,
        active: Optional[bool] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """A page of a project's bindings, newest first."""
        rows = self._filtered_bindings(tenant_id, project_id, version_id, active)
        return [self._binding_view(row) for row in rows[offset : offset + limit]]

    def count_draft_bindings(
        self,
        *,
        tenant_id: str,
        project_id: str,
        version_id: Optional[str] = None,
        active: Optional[bool] = None,
    ) -> int:
        """How many bindings the same filters match."""
        return len(self._filtered_bindings(tenant_id, project_id, version_id, active))

    def find_active_bindings_for_repository_ref(
        self, *, repository_id: str, ref: str
    ) -> List[Dict[str, Any]]:
        """Active bindings of a repository's ref, oldest first."""
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
                "commit_sha": row["commit_sha"],
                "source_digest": row["source_digest"],
                "path": row["path"],
                "ref": row["ref"],
            }
            for row in rows
        ]

    # -----------------------------------------------------------------------------------------
    # Candidate reads
    # -----------------------------------------------------------------------------------------

    def list_binding_sync_candidates(
        self,
        *,
        tenant_id: str,
        binding_id: str,
        pending_only: Optional[bool] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """A page of one binding's candidates, newest first."""
        rows = [
            row
            for row in self.candidates.values()
            if row["tenant_id"] == tenant_id
            and row["binding_id"] == binding_id
            and (
                pending_only is None
                or (row["status"] == STATUS_PENDING) is pending_only
            )
        ]
        rows.sort(key=lambda row: (row["detected_at"], row["id"]), reverse=True)
        return [self._candidate_view(row) for row in rows[offset : offset + limit]]

    def get_binding_sync_candidate(
        self, *, tenant_id: str, binding_id: str, candidate_id: str
    ) -> Optional[Dict[str, Any]]:
        """One candidate of one binding."""
        row = self.candidates.get(candidate_id)
        if row and row["tenant_id"] == tenant_id and row["binding_id"] == binding_id:
            return self._candidate_view(row)
        return None

    # -----------------------------------------------------------------------------------------
    # Writes
    # -----------------------------------------------------------------------------------------

    def _release(
        self, row: Dict[str, Any], *, actor_id: Optional[str], reason: str
    ) -> int:
        """Stamp a binding released and supersede its outstanding candidates."""
        now = self._tick()
        row.update(released_at=now, released_by=actor_id, release_reason=reason, updated_at=now)
        superseded = 0
        for candidate in self.candidates.values():
            if candidate["binding_id"] == row["id"] and candidate["status"] == STATUS_PENDING:
                candidate.update(
                    status=STATUS_SUPERSEDED, resolved_at=self._tick(), resolved_by=actor_id
                )
                superseded += 1
        self._audit(
            tenant_id=row["tenant_id"],
            project_id=row["project_id"],
            version_id=row["version_id"],
            action=AUDIT_RELEASED,
            actor_id=actor_id,
            detail={
                "binding_id": row["id"],
                "reason": reason,
                "ref": row["ref"],
                "commit_sha": row["commit_sha"],
                "candidates_superseded": superseded,
            },
        )
        return superseded

    def insert_draft_binding(
        self,
        *,
        tenant_id: str,
        project_id: str,
        version_id: str,
        repository_id: Optional[str],
        provider: str,
        repo_full_name: str,
        repo_url: str,
        ref: str,
        path: str,
        commit_sha: str,
        source_digest: str,
        created_by: str,
        replace: bool,
    ) -> Optional[Dict[str, Any]]:
        """Bind a draft version, releasing the current binding when asked."""
        self._run_interleave()
        existing = self._active_binding(tenant_id, version_id)
        released_id: Optional[str] = None
        if existing:
            if not replace:
                return None
            released_id = existing["id"]
            now = self._tick()
            existing.update(
                released_at=now,
                released_by=created_by,
                release_reason=RELEASE_REASON_REPLACED,
                updated_at=now,
            )
        now = self._tick()
        binding_id = str(uuid.uuid4())
        self.bindings[binding_id] = {
            "id": binding_id,
            "tenant_id": tenant_id,
            "project_id": project_id,
            "version_id": version_id,
            "repository_id": repository_id,
            "provider": provider,
            "repo_full_name": repo_full_name,
            "repo_url": repo_url,
            "ref": ref,
            "path": path,
            "commit_sha": commit_sha,
            "source_digest": source_digest,
            "synchronized_at": now,
            "created_by": created_by,
            "created_at": now,
            "updated_at": now,
            "released_at": None,
            "released_by": None,
            "release_reason": None,
        }
        self._audit(
            tenant_id=tenant_id,
            project_id=project_id,
            version_id=version_id,
            action=(AUDIT_REBOUND if released_id else AUDIT_BOUND),
            actor_id=created_by,
            detail={
                "binding_id": binding_id,
                "released_binding_id": released_id,
                "repository_id": repository_id,
                "provider": provider,
                "repository_full_name": repo_full_name,
                "ref": ref,
                "path": path,
                "commit_sha": commit_sha,
                "source_digest": source_digest,
            },
        )
        return {"binding_id": binding_id, "released_binding_id": released_id}

    def release_draft_binding(
        self,
        *,
        tenant_id: str,
        project_id: str,
        binding_id: str,
        actor_id: Optional[str],
        reason: str,
    ) -> bool:
        """Release an active binding, keeping the row as history."""
        self._run_interleave()
        row = self.bindings.get(binding_id)
        if (
            not row
            or row["tenant_id"] != tenant_id
            or row["project_id"] != project_id
            or row["released_at"] is not None
        ):
            return False
        self._release(row, actor_id=actor_id, reason=reason)
        return True

    def raise_binding_sync_candidate(
        self,
        *,
        tenant_id: str,
        binding_id: str,
        to_commit_sha: str,
        origin: str,
        delivery_id: Optional[str] = None,
        detected_by: Optional[str] = None,
        to_digest: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Record that a bound ref moved, as a pending candidate."""
        self._run_interleave()
        binding = self.bindings.get(binding_id)
        if not binding or binding["tenant_id"] != tenant_id or binding["released_at"] is not None:
            return None
        if binding["commit_sha"] == to_commit_sha:
            return None
        for row in self.candidates.values():
            if row["binding_id"] != binding_id:
                continue
            # The two partial unique indexes of V264, in the order they are declared.
            if row["status"] == STATUS_PENDING and row["to_commit_sha"] == to_commit_sha:
                return None
            if delivery_id is not None and row["delivery_id"] == delivery_id:
                return None
        candidate_id = str(uuid.uuid4())
        self.candidates[candidate_id] = {
            "id": candidate_id,
            "binding_id": binding_id,
            "tenant_id": tenant_id,
            "ref": binding["ref"],
            "from_commit_sha": binding["commit_sha"],
            "from_digest": binding["source_digest"],
            "to_commit_sha": to_commit_sha,
            "to_digest": to_digest,
            "origin": origin,
            "delivery_id": delivery_id,
            "status": STATUS_PENDING,
            "detected_at": self._tick(),
            "detected_by": detected_by,
            "resolved_at": None,
            "resolved_by": None,
            "resolution_note": None,
        }
        superseded = 0
        for row in self.candidates.values():
            if (
                row["binding_id"] == binding_id
                and row["id"] != candidate_id
                and row["status"] == STATUS_PENDING
            ):
                row.update(status=STATUS_SUPERSEDED, resolved_at=self._tick())
                superseded += 1
        self._audit(
            tenant_id=tenant_id,
            project_id=binding["project_id"],
            version_id=binding["version_id"],
            action=AUDIT_CANDIDATE_RAISED,
            actor_id=detected_by,
            detail={
                "binding_id": binding_id,
                "candidate_id": candidate_id,
                "ref": binding["ref"],
                "from_commit_sha": binding["commit_sha"],
                "to_commit_sha": to_commit_sha,
                "origin": origin,
                "delivery_id": delivery_id,
                "superseded": superseded,
            },
        )
        return {"candidate_id": candidate_id, "superseded": superseded}

    def resolve_binding_sync_candidate(
        self,
        *,
        tenant_id: str,
        project_id: str,
        binding_id: str,
        candidate_id: str,
        status: str,
        actor_id: str,
        note: Optional[str] = None,
        to_digest: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Settle an outstanding candidate, advancing the binding when it is applied."""
        self._run_interleave()
        binding = self.bindings.get(binding_id)
        if (
            not binding
            or binding["tenant_id"] != tenant_id
            or binding["project_id"] != project_id
            or binding["released_at"] is not None
        ):
            return None
        if status == STATUS_APPLIED and not (to_digest or "").strip():
            return None
        candidate = self.candidates.get(candidate_id)
        if (
            not candidate
            or candidate["binding_id"] != binding_id
            or candidate["tenant_id"] != tenant_id
            or candidate["status"] != STATUS_PENDING
        ):
            return None
        candidate.update(
            status=status,
            to_digest=(to_digest if to_digest is not None else candidate["to_digest"]),
            resolved_at=self._tick(),
            resolved_by=actor_id,
            resolution_note=note,
        )
        commit_sha = binding["commit_sha"]
        source_digest = binding["source_digest"]
        if status == STATUS_APPLIED:
            commit_sha = candidate["to_commit_sha"]
            source_digest = str(to_digest)
            now = self._tick()
            binding.update(
                commit_sha=commit_sha,
                source_digest=source_digest,
                synchronized_at=now,
                updated_at=now,
            )
        self._audit(
            tenant_id=tenant_id,
            project_id=project_id,
            version_id=binding["version_id"],
            action=AUDIT_CANDIDATE_RESOLVED,
            actor_id=actor_id,
            detail={
                "binding_id": binding_id,
                "candidate_id": candidate_id,
                "status": status,
                "from_commit_sha": candidate["from_commit_sha"],
                "to_commit_sha": candidate["to_commit_sha"],
                "commit_sha": commit_sha,
                "source_digest": source_digest,
            },
        )
        return {
            "candidate_id": candidate_id,
            "commit_sha": commit_sha,
            "source_digest": source_digest,
        }
