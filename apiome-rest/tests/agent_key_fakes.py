"""An in-memory stand-in for the agent-key accessors on ``app.database.db`` — AGX-3.1 (#4537).

The apiome-rest suite runs without a database in CI, so the agent-key tests swap the five
``db.*agent_key*`` accessors for this store. It mirrors the SQL accessors' contract closely enough
that a lifecycle bug shows up here too:

* rows come back as metadata only — ``key_hash`` is stored but never returned, like
  ``_AGENT_KEY_COLUMNS``;
* every read and write is scoped by tenant (and ``kind = 'agent'``: workspace keys seeded with
  :meth:`FakeAgentKeyStore.seed_workspace_key` are never visible);
* names are unique per tenant across both kinds, revoked keys included
  (``api_keys_tenant_name_unique``), so a create on a taken name returns ``None``;
* allowlist edits and revocation only match an unrevoked key, as their ``WHERE deleted_at IS
  NULL`` does, and a second revoke keeps the first revocation time;
* every call is logged in :attr:`FakeAgentKeyStore.calls`.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

#: The accessors the agent-key module calls; :meth:`FakeAgentKeyStore.install` patches these.
ACCESSORS = (
    "list_agent_keys",
    "get_agent_key",
    "insert_agent_key",
    "update_agent_key_allowlist",
    "revoke_agent_key",
)

#: Metadata columns every accessor returns (``Database._AGENT_KEY_COLUMNS``).
_METADATA = (
    "id",
    "tenant_id",
    "name",
    "description",
    "key_prefix",
    "toolset_id",
    "tool_allowlist",
    "expires_at",
    "enabled",
    "revoked_at",
    "last_used_at",
    "created_at",
    "updated_at",
    "created_by",
)


class FakeAgentKeyStore:
    """The ``api_keys`` table, in memory, as the agent-key accessors see it.

    Attributes:
        rows: Stored keys by id, including ``key_hash``, ``kind`` and ``scopes``.
        calls: The name of every accessor called, in order.
    """

    def __init__(self) -> None:
        self.rows: Dict[str, Dict[str, Any]] = {}
        self.calls: List[str] = []

    def install(self, monkeypatch: Any, db: Any) -> "FakeAgentKeyStore":
        """Patch the agent-key accessors on ``db`` with this store's methods.

        Args:
            monkeypatch: The pytest ``monkeypatch`` fixture.
            db: The ``app.database.db`` singleton.

        Returns:
            ``self``, for chaining.
        """
        for name in ACCESSORS:
            monkeypatch.setattr(db, name, getattr(self, name))
        return self

    def seed_workspace_key(self, tenant_id: str, name: str) -> str:
        """Store a workspace key (to prove the agent accessors never see one).

        Args:
            tenant_id: Owning tenant.
            name: Its name, which then counts against the tenant's unique names.

        Returns:
            The new row's id.
        """
        key_id = str(uuid.uuid4())
        self.rows[key_id] = {
            "id": key_id,
            "tenant_id": str(tenant_id),
            "name": name,
            "kind": "workspace",
            "scopes": ["*"],
            "key_hash": "workspace-hash",
            "key_prefix": "sk_000000000...",
            "revoked_at": None,
        }
        return key_id

    # -- helpers ---------------------------------------------------------------------------

    @staticmethod
    def _metadata(row: Dict[str, Any]) -> Dict[str, Any]:
        out = {column: row.get(column) for column in _METADATA}
        out["tool_allowlist"] = list(row.get("tool_allowlist") or [])
        return out

    def _find(self, tenant_id: str, key_id: str) -> Optional[Dict[str, Any]]:
        row = self.rows.get(str(key_id))
        if row and row["tenant_id"] == str(tenant_id) and row["kind"] == "agent":
            return row
        return None

    # -- accessors ---------------------------------------------------------------------------

    def list_agent_keys(
        self,
        tenant_id: str,
        *,
        toolset_id: Optional[str] = None,
        include_revoked: bool = False,
    ) -> List[Dict[str, Any]]:
        self.calls.append("list_agent_keys")
        rows = [
            row
            for row in self.rows.values()
            if row["tenant_id"] == str(tenant_id)
            and row["kind"] == "agent"
            and (toolset_id is None or row["toolset_id"] == str(toolset_id))
            and (include_revoked or row["revoked_at"] is None)
        ]
        rows.sort(key=lambda row: row["created_at"], reverse=True)
        return [self._metadata(row) for row in rows]

    def get_agent_key(self, tenant_id: str, key_id: str) -> Optional[Dict[str, Any]]:
        self.calls.append("get_agent_key")
        row = self._find(tenant_id, key_id)
        return self._metadata(row) if row else None

    def insert_agent_key(self, **fields: Any) -> Optional[Dict[str, Any]]:
        self.calls.append("insert_agent_key")
        taken = any(
            row["tenant_id"] == str(fields["tenant_id"]) and row["name"] == fields["name"]
            for row in self.rows.values()
        )
        if taken:
            return None
        now = datetime.now(timezone.utc)
        row = {
            "id": str(uuid.uuid4()),
            "tenant_id": str(fields["tenant_id"]),
            "name": fields["name"],
            "description": fields["description"],
            "key_hash": fields["key_hash"],
            "key_prefix": fields["key_prefix"],
            "kind": "agent",
            "scopes": ["agent:invoke"],
            "toolset_id": str(fields["toolset_id"]),
            "tool_allowlist": list(fields["tool_allowlist"]),
            "expires_at": fields["expires_at"],
            "enabled": True,
            "revoked_at": None,
            "last_used_at": None,
            "created_at": now,
            "updated_at": now,
            "created_by": fields.get("actor_id"),
        }
        self.rows[row["id"]] = row
        return self._metadata(row)

    def update_agent_key_allowlist(
        self, tenant_id: str, key_id: str, tool_allowlist: List[str]
    ) -> Optional[Dict[str, Any]]:
        self.calls.append("update_agent_key_allowlist")
        row = self._find(tenant_id, key_id)
        if row is None or row["revoked_at"] is not None:
            return None
        row["tool_allowlist"] = list(tool_allowlist)
        row["updated_at"] = datetime.now(timezone.utc)
        return self._metadata(row)

    def revoke_agent_key(self, tenant_id: str, key_id: str) -> Optional[Dict[str, Any]]:
        self.calls.append("revoke_agent_key")
        row = self._find(tenant_id, key_id)
        if row is None or row["revoked_at"] is not None:
            return None
        now = datetime.now(timezone.utc)
        row["revoked_at"] = now
        row["enabled"] = False
        row["updated_at"] = now
        return self._metadata(row)
