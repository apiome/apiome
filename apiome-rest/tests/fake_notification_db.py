"""In-memory stand-in for the COL-3.1 (#4521) notification accessors on ``app.database.Database``.

Two pieces:

* :class:`NotificationDbMixin` — the inbox storage and the fan-out hook. Mixed into
  :class:`tests.fake_comment_db.FakeCommentDb` (and so into ``FakeReviewDb``), so a store test that
  writes a comment, a decision, or a resolution can assert the inbox rows the same write produced.
* :class:`FakeNotificationDb` — the mixin on its own plus the permission surface, for the tests of
  the inbox routes themselves.

The fake keeps the semantics V263 and the SQL accessors promise:

* fan-out runs **inside** the write, and only when the write's guard held — a no-op resolve or a
  refused reply notifies nobody, exactly as a rolled-back transaction would;
* an inbox read is scoped to one user in one tenant, newest first;
* the retention cap keeps the newest :data:`app.notifications.RETENTION_PER_USER` rows per user;
* marking read is idempotent, touches only the caller's own rows, and never marks an id that is
  not theirs;
* a recipient whose account is gone is skipped rather than raising.

The SQL text itself is exercised separately against a scratch database; this fake is for rules.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from app.notifications import RETENTION_PER_USER


class NotificationDbMixin:
    """Inbox storage and the in-transaction fan-out hook.

    Attributes:
        notifications: Every stored row, newest last.
        deleted_users: User ids whose account is gone; fan-out skips them.
        collaborators: ``(tenant_id, project_id, version_id) -> [user_id]`` for the publish read.
    """

    def __init__(self) -> None:
        """Create an empty inbox with a deterministic clock."""
        self.notifications: List[Dict[str, Any]] = []
        self.deleted_users: Set[str] = set()
        self.collaborators: Dict[Tuple[str, str, str], List[str]] = {}
        self.user_names: Dict[str, str] = getattr(self, "user_names", {})
        self._notification_now = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)

    # -----------------------------------------------------------------------------------------
    # Fan-out, as the write accessors run it
    # -----------------------------------------------------------------------------------------

    def _fan_out(self, tenant_id: str, notify: Optional[Any], produced: Dict[str, Any]) -> int:
        """Write an event's inbox rows, as ``Database._insert_notifications`` does.

        Args:
            tenant_id: The tenant every row belongs to.
            notify: The notifier the write was given, or ``None``.
            produced: What the write generated, passed to the notifier.

        Returns:
            How many rows were written.
        """
        if notify is None:
            return 0
        written = 0
        touched: Set[str] = set()
        for draft in notify(dict(produced)) or []:
            if not draft.user_id or draft.user_id in self.deleted_users:
                continue
            self._notification_now += timedelta(seconds=1)
            self.notifications.append(
                {
                    "id": str(uuid.uuid4()),
                    "tenant_id": tenant_id,
                    "user_id": draft.user_id,
                    "type": draft.type,
                    "payload": dict(draft.payload or {}),
                    "actor_id": draft.actor_id,
                    "project_id": draft.project_id,
                    "version_id": draft.version_id,
                    "read_at": None,
                    "created_at": self._notification_now,
                }
            )
            touched.add(draft.user_id)
            written += 1
        for user_id in touched:
            self._enforce_retention(user_id)
        return written

    def _enforce_retention(self, user_id: str) -> None:
        """Drop everything past the newest :data:`RETENTION_PER_USER` rows of one user."""
        owned = [row for row in self.notifications if row["user_id"] == user_id]
        if len(owned) <= RETENTION_PER_USER:
            return
        owned.sort(key=lambda row: (row["created_at"], row["id"]), reverse=True)
        doomed = {row["id"] for row in owned[RETENTION_PER_USER:]}
        self.notifications = [row for row in self.notifications if row["id"] not in doomed]

    # -----------------------------------------------------------------------------------------
    # Seeding
    # -----------------------------------------------------------------------------------------

    def add_notification(
        self,
        *,
        tenant_id: str,
        user_id: str,
        type: str = "mention",
        payload: Optional[Dict[str, Any]] = None,
        actor_id: Optional[str] = None,
        project_id: Optional[str] = None,
        version_id: Optional[str] = None,
        read: bool = False,
    ) -> str:
        """Put one notification straight into an inbox, and return its id."""
        self._notification_now += timedelta(seconds=1)
        row = {
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "user_id": user_id,
            "type": type,
            "payload": dict(payload or {}),
            "actor_id": actor_id,
            "project_id": project_id,
            "version_id": version_id,
            "read_at": self._notification_now if read else None,
            "created_at": self._notification_now,
        }
        self.notifications.append(row)
        return str(row["id"])

    def add_collaborators(
        self, tenant_id: str, project_id: str, version_id: str, user_ids: Sequence[str]
    ) -> None:
        """Register who worked on a version, for the publish fan-out."""
        self.collaborators[(tenant_id, project_id, version_id)] = list(user_ids)

    def inbox(self, user_id: str) -> List[Dict[str, Any]]:
        """Every row of one user's inbox, oldest first."""
        return [row for row in self.notifications if row["user_id"] == user_id]

    # -----------------------------------------------------------------------------------------
    # Notification accessors
    # -----------------------------------------------------------------------------------------

    def _matching(
        self,
        *,
        tenant_id: str,
        user_id: str,
        unread_only: bool = False,
        type_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """The caller's rows matching the filters, newest first."""
        rows = [
            row
            for row in self.notifications
            if row["tenant_id"] == tenant_id
            and row["user_id"] == user_id
            and (not unread_only or row["read_at"] is None)
            and (not type_filter or row["type"] == type_filter)
        ]
        rows.sort(key=lambda row: (row["created_at"], row["id"]), reverse=True)
        return rows

    def list_notifications(
        self, *, limit: int = 50, offset: int = 0, **filters: Any
    ) -> List[Dict[str, Any]]:
        """A page of one user's inbox, with the actor's display name read fresh."""
        page = []
        for row in self._matching(**filters)[offset : offset + limit]:
            view = dict(row)
            view["actor_name"] = self.user_names.get(row.get("actor_id") or "")
            page.append(view)
        return page

    def count_notifications(self, **filters: Any) -> int:
        """How many notifications match the filters."""
        return len(self._matching(**filters))

    def count_unread_notifications_by_type(self, *, tenant_id: str, user_id: str) -> Dict[str, int]:
        """One user's unread count, split by type."""
        counts: Dict[str, int] = {}
        for row in self._matching(tenant_id=tenant_id, user_id=user_id, unread_only=True):
            counts[row["type"]] = counts.get(row["type"], 0) + 1
        return counts

    def mark_notifications_read(
        self,
        *,
        tenant_id: str,
        user_id: str,
        notification_ids: Optional[Sequence[str]] = None,
        all_unread: bool = False,
    ) -> int:
        """Stamp ``read_at`` on the caller's unread rows; only ever their own."""
        if not all_unread and not notification_ids:
            return 0
        wanted = {str(value) for value in (notification_ids or [])}
        updated = 0
        for row in self.notifications:
            if row["tenant_id"] != tenant_id or row["user_id"] != user_id:
                continue
            if row["read_at"] is not None:
                continue
            if not all_unread and row["id"] not in wanted:
                continue
            self._notification_now += timedelta(seconds=1)
            row["read_at"] = self._notification_now
            updated += 1
        return updated

    def list_version_collaborators(
        self, *, tenant_id: str, project_id: str, version_id: str
    ) -> List[str]:
        """Who worked on a version — whatever :meth:`add_collaborators` registered."""
        return list(self.collaborators.get((tenant_id, project_id, version_id), []))


class FakeNotificationDb(NotificationDbMixin):
    """The inbox on its own, plus the authentication surface the routes touch.

    Attributes:
        admins: ``(tenant_id, user_id)`` pairs that administer their tenant — irrelevant to an
            inbox, and asserted to stay that way.
    """

    def __init__(self) -> None:
        """Create an empty store."""
        self.user_names: Dict[str, str] = {}
        super().__init__()
        self.admins: Set[Tuple[str, str]] = set()
        self.audits: List[Dict[str, Any]] = []

    def add_user(self, user_id: str, name: str) -> None:
        """Register a display name for an actor."""
        self.user_names[user_id] = name

    def user_has_permission(self, tenant_id: str, user_id: str, resource: str, action: str) -> bool:
        """No inbox route asks for a permission; answering ``False`` proves it."""
        return False

    def is_user_tenant_admin(self, tenant_id: str, user_id: str) -> bool:
        """Whether the user administers the tenant."""
        return (tenant_id, user_id) in self.admins

    def get_fallback_creator_user_id_for_tenant(self, tenant_id: str) -> None:
        """Legacy keyless API keys resolve to no user, and so have no inbox."""
        return None

    def write_access_audit(self, **entry: Any) -> None:
        """Record a denial."""
        self.audits.append(entry)
