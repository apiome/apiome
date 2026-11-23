"""In-memory stand-in for the COL-1.1 (#4513) comment accessors on ``app.database.Database``.

Route and store tests swap this in for the module-level ``db`` of :mod:`app.comment_store` and
:mod:`app.comment_routes`, so a request runs through the real permission guard, the real store
rules, and the real mention resolver, and only the storage is simulated. The fake keeps the
semantics V259 and the SQL accessors promise:

* every thread read is scoped by tenant *and* project;
* a list is ordered by ``last_activity_at`` descending, then id, and carries the opening comment as
  ``root_*`` columns;
* a reply and a status change move ``last_activity_at``; an edit does not;
* resolving stamps ``resolved_by``/``resolved_at``, reopening clears both, and asking for the
  current status changes nothing;
* deleting a thread's last comment deletes the thread;
* only listed members are mentionable;
* deleting an element (:meth:`FakeCommentDb.delete_element`, standing in for V260's triggers)
  orphans its live threads with a label, an orphaned thread ignores resolve/reopen, and a relink
  moves the anchor only while the thread is orphaned and the target exists in its version (COL-1.4).

The SQL text itself is exercised separately against a scratch database; this fake is for rules.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from tests.fake_notification_db import NotificationDbMixin


class FakeCommentDb(NotificationDbMixin):
    """A storage double for comment threads, projects, versions, members, and the RBAC guard.

    Attributes:
        grants: ``None`` grants every ``(resource, action)``; a set grants only its members.
        admins: ``(tenant_id, user_id)`` pairs that administer their tenant.
        member_reads: How many times mentionable members were read, narrowly or in full.
        full_member_reads: How many times the whole member list was read.
        mention_lookups: The handles of each narrow member lookup (#7196).
    """

    def __init__(self) -> None:
        """Create an empty store with a deterministic clock."""
        self.projects: Dict[str, Dict[str, Any]] = {}
        self.versions: Dict[str, Dict[str, Any]] = {}
        self.anchors: Set[Tuple[str, str, str]] = set()
        self.members: List[Dict[str, Any]] = []
        self.user_names: Dict[str, str] = {}
        self.admins: Set[Tuple[str, str]] = set()
        self.grants: Optional[Set[Tuple[str, str]]] = None
        self.audits: List[Dict[str, Any]] = []
        self.threads: Dict[str, Dict[str, Any]] = {}
        self.comments: Dict[str, Dict[str, Any]] = {}
        self.member_reads = 0
        self.full_member_reads = 0
        self.mention_lookups: List[List[str]] = []
        self._now =datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
        NotificationDbMixin.__init__(self)

    # -----------------------------------------------------------------------------------------
    # Seeding
    # -----------------------------------------------------------------------------------------

    def _tick(self) -> datetime:
        """Advance the clock by a second, so writes order deterministically."""
        self._now += timedelta(seconds=1)
        return self._now

    def add_project(self, tenant_id: str, project_id: str, slug: str) -> None:
        """Register a project."""
        self.projects[project_id] = {"id": project_id, "tenant_id": tenant_id, "slug": slug}

    def add_version(self, project_id: str, version_id: str, label: str) -> None:
        """Register a version of a project."""
        self.versions[version_id] = {"id": version_id, "project_id": project_id, "version_id": label}

    def add_anchor(self, version_id: str, anchor_type: str, anchor_id: str) -> None:
        """Register an element that exists inside a version."""
        self.anchors.add((version_id, anchor_type, anchor_id))

    def delete_element(self, anchor_type: str, anchor_id: str, label: str) -> int:
        """Delete an element and orphan its live threads, as apiome-db V260's triggers do.

        Args:
            anchor_type: The element kind.
            anchor_id: The element id.
            label: The element's label at the moment of deletion.

        Returns:
            How many threads were orphaned.
        """
        self.anchors = {anchor for anchor in self.anchors if anchor[1:] != (anchor_type, anchor_id)}
        orphaned = 0
        for row in self.threads.values():
            if row["anchor_type"] == anchor_type and row["anchor_id"] == anchor_id and row["status"] != "orphaned":
                now = self._tick()
                row.update(
                    status="orphaned", anchor_label=label, orphaned_at=now, updated_at=now, last_activity_at=now
                )
                orphaned += 1
        return orphaned

    def add_member(self, user_id: str, name: Optional[str], email: Optional[str]) -> None:
        """Register a mentionable tenant member."""
        self.members.append({"user_id": user_id, "name": name, "email": email})
        if name:
            self.user_names[user_id] = name

    # -----------------------------------------------------------------------------------------
    # Permission guard surface
    # -----------------------------------------------------------------------------------------

    def user_has_permission(self, tenant_id: str, user_id: str, resource: str, action: str) -> bool:
        """Administrators pass everything; otherwise consult :attr:`grants`."""
        if (tenant_id, user_id) in self.admins:
            return True
        return self.grants is None or (resource, action) in self.grants

    def is_user_tenant_admin(self, tenant_id: str, user_id: str) -> bool:
        """Whether the user administers the tenant."""
        return (tenant_id, user_id) in self.admins

    def get_fallback_creator_user_id_for_tenant(self, tenant_id: str) -> None:
        """Legacy keyless API keys resolve to no user."""
        return None

    def write_access_audit(self, **entry: Any) -> None:
        """Record a denial."""
        self.audits.append(entry)

    # -----------------------------------------------------------------------------------------
    # Projects and versions
    # -----------------------------------------------------------------------------------------

    def get_project_by_id(
        self, project_id: str, tenant_id: str, *, include_deleted: bool = False
    ) -> Optional[Dict[str, Any]]:
        """A project of the tenant, by id."""
        row = self.projects.get(project_id)
        return dict(row) if row and row["tenant_id"] == tenant_id else None
    get_project_core = get_project_by_id

    def get_project_by_slug(self, slug: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        """A project of the tenant, by slug."""
        for row in self.projects.values():
            if row["slug"] == slug and row["tenant_id"] == tenant_id:
                return dict(row)
        return None

    def _version_in_tenant(self, row: Optional[Dict[str, Any]], tenant_id: str) -> bool:
        """Whether a version row belongs to a project of the tenant."""
        project = self.projects.get(row["project_id"]) if row else None
        return bool(project and project["tenant_id"] == tenant_id)

    def get_version_by_id(self, version_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        """A version of the tenant, by revision id."""
        row = self.versions.get(version_id)
        return dict(row) if row and self._version_in_tenant(row, tenant_id) else None
    get_version_core = get_version_by_id

    def get_version_by_version_id(
        self, project_id: str, version_id_str: str, tenant_id: str
    ) -> Optional[Dict[str, Any]]:
        """A version of the project, by label."""
        for row in self.versions.values():
            if (
                row["project_id"] == project_id
                and row["version_id"] == version_id_str
                and self._version_in_tenant(row, tenant_id)
            ):
                return dict(row)
        return None

    # -----------------------------------------------------------------------------------------
    # Comment accessors
    # -----------------------------------------------------------------------------------------

    # -- COL-4.4 (#4528): what a Browse reader can give feedback on ---------------------------

    def publish_version(self, version_id: str, *, public: bool = True) -> None:
        """Mark a version published (and public unless told otherwise)."""
        self.versions[version_id]["published"] = True
        self.versions[version_id]["visibility"] = "public" if public else "private"

    def add_operation(self, version_id: str, operation_id: str, method: str, path: str) -> None:
        """Register an operation of a version, by method and path, as a valid anchor."""
        self.operations = getattr(self, "operations", {})
        self.operations[operation_id] = {"version_id": version_id, "method": method.upper(), "path": path}
        self.add_anchor(version_id, "operation", operation_id)

    def get_published_public_version(
        self, *, tenant_id: str, project_slug: str, version_label: str
    ) -> Optional[Dict[str, Any]]:
        """The published, public version a reader may see."""
        for version in self.versions.values():
            project = self.projects.get(version["project_id"], {})
            if (
                project.get("tenant_id") == tenant_id
                and project.get("slug") == project_slug
                and version["version_id"] == version_label
                and version.get("published")
                and version.get("visibility") == "public"
            ):
                return {**version, "project_slug": project_slug}
        return None

    def find_version_operation(self, *, version_id: str, method: str, path: str) -> Optional[str]:
        """An operation of a version by method (any case) and exact path."""
        for operation_id, op in getattr(self, "operations", {}).items():
            if op["version_id"] == version_id and op["method"] == method.upper() and op["path"] == path:
                return operation_id
        return None

    def get_operation_coordinates(self, operation_ids: List[str]) -> Dict[str, Dict[str, str]]:
        """Method and path of each existing operation."""
        ops = getattr(self, "operations", {})
        return {i: {"method": ops[i]["method"], "path": ops[i]["path"]} for i in operation_ids if i in ops}

    def comment_anchor_exists(self, *, version_id: str, anchor_type: str, anchor_id: str) -> bool:
        """Whether the element exists in the version."""
        if anchor_type == "version":
            return anchor_id == version_id and version_id in self.versions
        return (version_id, anchor_type, anchor_id) in self.anchors

    def _thread_view(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """A thread row as the SQL read returns it."""
        view = dict(row)
        view["created_by_name"] = self.user_names.get(row.get("created_by") or "")
        view["comment_count"] = sum(1 for c in self.comments.values() if c["thread_id"] == row["id"])
        return view

    def _comment_view(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """A comment row as the SQL read returns it."""
        view = dict(row)
        view["author_name"] = self.user_names.get(row.get("author_id") or "")
        view["mentions"] = list(row["mentions"])
        return view

    def _scoped_thread(self, tenant_id: str, project_id: str, thread_id: str) -> Optional[Dict[str, Any]]:
        """The raw thread row when it belongs to the tenant's project."""
        row = self.threads.get(thread_id)
        if row and row["tenant_id"] == tenant_id and row["project_id"] == project_id:
            return row
        return None

    def _thread_comments(self, thread_id: str) -> List[Dict[str, Any]]:
        """A thread's raw comment rows, oldest first."""
        rows = [c for c in self.comments.values() if c["thread_id"] == thread_id]
        return sorted(rows, key=lambda c: (c["created_at"], c["id"]))

    def insert_comment_thread(
        self,
        *,
        tenant_id: str,
        project_id: str,
        version_id: str,
        anchor_type: str,
        anchor_id: str,
        created_by: str,
        body: str,
        mentions: List[str],
        notify: Optional[Any] = None,
        origin: str = "internal",
    ) -> Optional[Dict[str, Any]]:
        """Open a thread with its first comment, and fan its mentions out with it."""
        now = self._tick()
        thread_id = str(uuid.uuid4())
        comment_id = str(uuid.uuid4())
        self.threads[thread_id] = {
            "id": thread_id,
            "tenant_id": tenant_id,
            "project_id": project_id,
            "version_id": version_id,
            "anchor_type": anchor_type,
            "anchor_id": anchor_id,
            "status": "open",
            "anchor_label": None,
            "orphaned_at": None,
            "origin": origin,
            "created_by": created_by,
            "resolved_by": None,
            "resolved_at": None,
            "created_at": now,
            "updated_at": now,
            "last_activity_at": now,
        }
        self.comments[comment_id] = {
            "id": comment_id,
            "thread_id": thread_id,
            "author_id": created_by,
            "body": body,
            "mentions": list(mentions),
            "edited_at": None,
            "created_at": now,
        }
        produced = {"thread_id": thread_id, "comment_id": comment_id}
        self._fan_out(tenant_id, notify, produced)
        return produced

    def get_comment_thread(
        self, *, tenant_id: str, project_id: str, thread_id: str
    ) -> Optional[Dict[str, Any]]:
        """One thread of the tenant's project."""
        row = self._scoped_thread(tenant_id, project_id, thread_id)
        return self._thread_view(row) if row else None

    def _filtered_threads(
        self,
        *,
        tenant_id: str,
        project_id: str,
        version_id: Optional[str] = None,
        status: Optional[str] = None,
        anchor_type: Optional[str] = None,
        anchor_id: Optional[str] = None,
        mentioned_user_id: Optional[str] = None,
        origin: Optional[str] = None,
        created_by: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Threads matching the list filters, in list order."""
        rows = []
        for row in self.threads.values():
            if row["tenant_id"] != tenant_id or row["project_id"] != project_id:
                continue
            if version_id and row["version_id"] != version_id:
                continue
            if status and row["status"] != status:
                continue
            if anchor_type and row["anchor_type"] != anchor_type:
                continue
            if anchor_id and row["anchor_id"] != anchor_id:
                continue
            if origin and row.get("origin", "internal") != origin:
                continue
            if created_by and row["created_by"] != created_by:
                continue
            if mentioned_user_id and not any(
                mentioned_user_id in c["mentions"] for c in self._thread_comments(row["id"])
            ):
                continue
            rows.append(row)
        rows.sort(key=lambda r: (r["last_activity_at"], r["id"]), reverse=True)
        return rows

    def list_comment_threads(
        self, *, limit: int = 50, offset: int = 0, cursor: Any = None, **filters: Any
    ) -> List[Dict[str, Any]]:
        """A page of threads with their opening comment as ``root_*`` columns."""
        page = []
        matching = self._filtered_threads(**filters)
        if cursor is not None:
            # Keyset: only rows strictly older than the cursor row (#7196).
            matching = [row for row in matching if (row["last_activity_at"], row["id"]) < tuple(cursor)]
            offset = 0
        for row in matching[offset : offset + limit]:
            view = self._thread_view(row)
            comments = self._thread_comments(row["id"])
            root = self._comment_view(comments[0]) if comments else {}
            for name in ("id", "author_id", "author_name", "body", "mentions", "edited_at", "created_at"):
                view[f"root_{name}"] = root.get(name)
            page.append(view)
        return page

    def count_comment_threads(self, **filters: Any) -> int:
        """How many threads match the filters."""
        return len(self._filtered_threads(**filters))

    def list_comments(self, *, thread_id: str) -> List[Dict[str, Any]]:
        """A thread's comments, oldest first."""
        return [self._comment_view(c) for c in self._thread_comments(thread_id)]

    def list_comments_for_threads(self, thread_ids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """Several threads' comments, oldest first, keyed by thread (DBP-1.6, #7189)."""
        return {str(tid): self.list_comments(thread_id=str(tid)) for tid in thread_ids}

    def get_comment(self, *, thread_id: str, comment_id: str) -> Optional[Dict[str, Any]]:
        """One comment of a thread."""
        row = self.comments.get(comment_id)
        return self._comment_view(row) if row and row["thread_id"] == thread_id else None

    def insert_comment(
        self,
        *,
        tenant_id: str,
        project_id: str,
        thread_id: str,
        author_id: str,
        body: str,
        mentions: List[str],
        notify: Optional[Any] = None,
    ) -> Optional[str]:
        """Reply to a thread, mark it active, and fan the reply's mentions out with it."""
        thread = self._scoped_thread(tenant_id, project_id, thread_id)
        if not thread:
            return None
        now = self._tick()
        comment_id = str(uuid.uuid4())
        self.comments[comment_id] = {
            "id": comment_id,
            "thread_id": thread_id,
            "author_id": author_id,
            "body": body,
            "mentions": list(mentions),
            "edited_at": None,
            "created_at": now,
        }
        thread["last_activity_at"] = now
        self._fan_out(tenant_id, notify, {"thread_id": thread_id, "comment_id": comment_id})
        return comment_id

    def update_comment(
        self,
        *,
        tenant_id: str,
        project_id: str,
        thread_id: str,
        comment_id: str,
        body: str,
        mentions: List[str],
        notify: Optional[Any] = None,
    ) -> bool:
        """Replace a comment's body and mentions, stamping the edit."""
        row = self.comments.get(comment_id)
        if not self._scoped_thread(tenant_id, project_id, thread_id) or not row or row["thread_id"] != thread_id:
            return False
        row.update(body=body, mentions=list(mentions), edited_at=self._tick())
        self._fan_out(tenant_id, notify, {"thread_id": thread_id, "comment_id": comment_id})
        return True

    def delete_comment(
        self, *, tenant_id: str, project_id: str, thread_id: str, comment_id: str
    ) -> Dict[str, bool]:
        """Delete a comment, and its thread when it was the last one."""
        outcome = {"deleted": False, "thread_deleted": False}
        row = self.comments.get(comment_id)
        if not self._scoped_thread(tenant_id, project_id, thread_id) or not row or row["thread_id"] != thread_id:
            return outcome
        del self.comments[comment_id]
        outcome["deleted"] = True
        if not self._thread_comments(thread_id):
            del self.threads[thread_id]
            outcome["thread_deleted"] = True
        return outcome

    def set_comment_thread_status(
        self,
        *,
        tenant_id: str,
        project_id: str,
        thread_id: str,
        status: str,
        actor_id: str,
        notify: Optional[Any] = None,
    ) -> bool:
        """Resolve or reopen a thread; the current status, or an orphaned thread, is a no-op."""
        row = self._scoped_thread(tenant_id, project_id, thread_id)
        if not row or row["status"] in (status, "orphaned"):
            return False
        now = self._tick()
        resolved = status == "resolved"
        row.update(
            status=status,
            resolved_by=actor_id if resolved else None,
            resolved_at=now if resolved else None,
            updated_at=now,
            last_activity_at=now,
        )
        self._fan_out(tenant_id, notify, {"thread_id": thread_id})
        return True

    def relink_comment_thread(
        self,
        *,
        tenant_id: str,
        project_id: str,
        thread_id: str,
        version_id: str,
        anchor_type: str,
        anchor_id: str,
    ) -> bool:
        """Move an orphaned thread's anchor when the target exists in its version."""
        row = self._scoped_thread(tenant_id, project_id, thread_id)
        if not row or row["status"] != "orphaned" or row["version_id"] != version_id:
            return False
        if not self.comment_anchor_exists(version_id=version_id, anchor_type=anchor_type, anchor_id=anchor_id):
            return False
        now = self._tick()
        row.update(
            anchor_type=anchor_type,
            anchor_id=anchor_id,
            status="resolved" if row["resolved_at"] else "open",
            anchor_label=None,
            orphaned_at=None,
            updated_at=now,
            last_activity_at=now,
        )
        return True

    def delete_comment_thread(self, *, tenant_id: str, project_id: str, thread_id: str) -> bool:
        """Delete a thread and its comments."""
        if not self._scoped_thread(tenant_id, project_id, thread_id):
            return False
        del self.threads[thread_id]
        for comment_id in [c["id"] for c in self.comments.values() if c["thread_id"] == thread_id]:
            del self.comments[comment_id]
        return True

    def list_comment_mention_candidates(self, tenant_id: str) -> List[Dict[str, Any]]:
        """The mentionable members."""
        self.member_reads += 1
        self.full_member_reads += 1
        return [dict(member) for member in self.members]

    def find_comment_mention_candidates(
        self, tenant_id: str, handles: Any
    ) -> List[Dict[str, Any]]:
        """The members a handle could name — the same superset the SQL predicate keeps."""
        self.member_reads += 1
        self.mention_lookups.append(list(handles))

        def in_order(handle: str, name: str) -> bool:
            position = 0
            for char in handle:
                position = name.find(char, position) + 1
                if position == 0:
                    return False
            return True

        matched = []
        for member in self.members:
            email = str(member.get("email") or "").lower()
            name = str(member.get("name") or "").lower()
            if any(
                handle in (email, email.split("@", 1)[0])
                or ("@" not in handle and in_order(handle, name))
                for handle in handles
            ):
                matched.append(dict(member))
        return matched

    def filter_mentionable_member_ids(self, tenant_id: str, user_ids: Any) -> List[str]:
        """Which of the given ids are mentionable members."""
        wanted = {str(user_id) for user_id in user_ids}
        return [str(m["user_id"]) for m in self.members if str(m["user_id"]) in wanted]
