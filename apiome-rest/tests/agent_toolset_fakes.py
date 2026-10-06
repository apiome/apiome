"""An in-memory stand-in for the agent-toolset accessors on ``app.database.db`` — AGX-1.2 (#4530).

The apiome-rest suite runs without a database in CI, so the toolset tests swap the
``db.*agent_toolset*`` accessors for this store. It follows the SQL accessors' contract closely
enough that a curation bug shows up here too:

* every read and write is scoped by tenant, so another tenant's toolset or version is invisible;
* a version has at most one toolset (``agent_toolsets_version_uq``), so a second insert returns
  ``None`` and writes nothing;
* :meth:`FakeToolsetStore.set_agent_toolset_tool_enabled` refuses (returns ``None``) to enable an
  unconfirmed write op, as its ``WHERE`` does. It stamps the confirmation when enabling a write op
  and clears it when disabling, and :meth:`FakeToolsetStore._check` enforces V270's
  ``agent_toolset_tools_write_confirmed_ck`` on every stored row;
* toolset rows carry the version coordinates and tool counts ``_AGENT_TOOLSET_COLUMNS`` returns;
* every call is logged in :attr:`FakeToolsetStore.calls`.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence

#: The accessors the toolset module and routes call; :meth:`FakeToolsetStore.install` patches these.
ACCESSORS = (
    "get_agent_toolset_version",
    "agent_toolset_exists",
    "list_agent_toolsets",
    "get_agent_toolset",
    "insert_agent_toolset",
    "update_agent_toolset",
    "delete_agent_toolset",
    "list_agent_toolset_tools",
    "get_agent_toolset_tool",
    "set_agent_toolset_tool_enabled",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class FakeToolsetStore:
    """``versions`` plus ``agent_toolsets`` / ``agent_toolset_tools``, in memory.

    Attributes:
        versions: Seeded versions by id (``tenant_id``, ``project_id``, ``version_label``,
            ``published``, ``deleted``).
        toolsets: Stored toolsets by id.
        tools: Stored tool rows by id.
        calls: The name of every accessor called, in order.
    """

    def __init__(self) -> None:
        self.versions: Dict[str, Dict[str, Any]] = {}
        self.toolsets: Dict[str, Dict[str, Any]] = {}
        self.tools: Dict[str, Dict[str, Any]] = {}
        self.calls: List[str] = []

    def install(self, monkeypatch: Any, db: Any) -> "FakeToolsetStore":
        """Patch the toolset accessors on ``db`` with this store's methods.

        Args:
            monkeypatch: The pytest ``monkeypatch`` fixture.
            db: The ``app.database.db`` singleton.

        Returns:
            ``self``, for chaining.
        """
        for name in ACCESSORS:
            monkeypatch.setattr(db, name, getattr(self, name))
        return self

    # -- seeding ---------------------------------------------------------------------------

    def seed_version(
        self,
        tenant_id: str,
        *,
        published: bool = True,
        deleted: bool = False,
        label: str = "1.0.0",
    ) -> str:
        """Store a version of a fresh project in ``tenant_id`` and return its id."""
        version_id = str(uuid.uuid4())
        self.versions[version_id] = {
            "id": version_id,
            "tenant_id": tenant_id,
            "project_id": str(uuid.uuid4()),
            "version_label": label,
            "published": published,
            "deleted": deleted,
        }
        return version_id

    # -- helpers ---------------------------------------------------------------------------

    @staticmethod
    def _check(tool: Mapping[str, Any]) -> None:
        """V270's ``agent_toolset_tools_write_confirmed_ck``."""
        live_write = tool["write_op"] and tool["enabled"]
        assert live_write == (tool["write_confirmed_at"] is not None), (
            "agent_toolset_tools_write_confirmed_ck violated",
            tool,
        )

    def _owned(self, tenant_id: str, toolset_id: str) -> Optional[Dict[str, Any]]:
        toolset = self.toolsets.get(str(toolset_id))
        if toolset is None or toolset["tenant_id"] != tenant_id:
            return None
        return toolset

    def _project(self, toolset: Mapping[str, Any]) -> Dict[str, Any]:
        version = self.versions[toolset["version_id"]]
        rows = [tool for tool in self.tools.values() if tool["toolset_id"] == toolset["id"]]
        return {
            **dict(toolset),
            "project_id": version["project_id"],
            "version_label": version["version_label"],
            "tool_count": len(rows),
            "enabled_tool_count": sum(1 for tool in rows if tool["enabled"]),
            "enabled_write_op_count": sum(
                1 for tool in rows if tool["enabled"] and tool["write_op"]
            ),
        }

    # -- accessors -------------------------------------------------------------------------

    def get_agent_toolset_version(self, tenant_id: str, version_id: str) -> Optional[Dict[str, Any]]:
        self.calls.append("get_agent_toolset_version")
        version = self.versions.get(str(version_id))
        if version is None or version["tenant_id"] != tenant_id:
            return None
        return {key: value for key, value in version.items() if key != "tenant_id"}

    def agent_toolset_exists(self, tenant_id: str, toolset_id: str) -> bool:
        self.calls.append("agent_toolset_exists")
        return self._owned(tenant_id, toolset_id) is not None

    def list_agent_toolsets(
        self, tenant_id: str, *, version_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        self.calls.append("list_agent_toolsets")
        rows = [
            self._project(toolset)
            for toolset in self.toolsets.values()
            if toolset["tenant_id"] == tenant_id
            and (version_id is None or toolset["version_id"] == version_id)
        ]
        return sorted(rows, key=lambda row: row["created_at"], reverse=True)

    def get_agent_toolset(self, tenant_id: str, toolset_id: str) -> Optional[Dict[str, Any]]:
        self.calls.append("get_agent_toolset")
        toolset = self._owned(tenant_id, toolset_id)
        return self._project(toolset) if toolset else None

    def insert_agent_toolset(
        self,
        *,
        tenant_id: str,
        version_id: str,
        enabled: bool,
        target: str,
        tools: Sequence[Mapping[str, Any]],
        actor_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        self.calls.append("insert_agent_toolset")
        if any(toolset["version_id"] == version_id for toolset in self.toolsets.values()):
            return None
        assert target in ("prod", "mock")
        now = _now()
        toolset_id = str(uuid.uuid4())
        self.toolsets[toolset_id] = {
            "id": toolset_id,
            "tenant_id": tenant_id,
            "version_id": version_id,
            "enabled": enabled,
            "target": target,
            "created_at": now,
            "updated_at": now,
            "created_by": actor_id,
            "updated_by": actor_id,
        }
        for seed in tools:
            tool = {
                "id": str(uuid.uuid4()),
                "toolset_id": toolset_id,
                "operation_key": seed["operation_key"],
                "tool_name": seed["tool_name"],
                "write_op": bool(seed["write_op"]),
                "enabled": bool(seed["enabled"]),
                "write_confirmed_by": None,
                "write_confirmed_at": None,
                "updated_by": actor_id,
                "created_at": now,
                "updated_at": now,
            }
            self._check(tool)
            self.tools[tool["id"]] = tool
        return self._project(self.toolsets[toolset_id])

    def update_agent_toolset(
        self,
        tenant_id: str,
        toolset_id: str,
        *,
        enabled: Optional[bool] = None,
        target: Optional[str] = None,
        actor_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        self.calls.append("update_agent_toolset")
        toolset = self._owned(tenant_id, toolset_id)
        if toolset is None:
            return None
        if enabled is not None:
            toolset["enabled"] = enabled
        if target is not None:
            toolset["target"] = target
        toolset["updated_by"] = actor_id
        toolset["updated_at"] = _now()
        return self._project(toolset)

    def delete_agent_toolset(self, tenant_id: str, toolset_id: str) -> Optional[Dict[str, Any]]:
        self.calls.append("delete_agent_toolset")
        toolset = self._owned(tenant_id, toolset_id)
        if toolset is None:
            return None
        projected = self._project(toolset)
        del self.toolsets[toolset["id"]]
        for tool_id in [key for key, tool in self.tools.items() if tool["toolset_id"] == toolset["id"]]:
            del self.tools[tool_id]
        return projected

    def list_agent_toolset_tools(self, tenant_id: str, toolset_id: str) -> List[Dict[str, Any]]:
        self.calls.append("list_agent_toolset_tools")
        if self._owned(tenant_id, toolset_id) is None:
            return []
        rows = [dict(tool) for tool in self.tools.values() if tool["toolset_id"] == toolset_id]
        return sorted(rows, key=lambda row: row["operation_key"])

    def get_agent_toolset_tool(
        self, tenant_id: str, toolset_id: str, tool_id: str
    ) -> Optional[Dict[str, Any]]:
        self.calls.append("get_agent_toolset_tool")
        tool = self.tools.get(str(tool_id))
        if tool is None or tool["toolset_id"] != toolset_id:
            return None
        if self._owned(tenant_id, toolset_id) is None:
            return None
        return dict(tool)

    def set_agent_toolset_tool_enabled(
        self,
        tenant_id: str,
        toolset_id: str,
        tool_id: str,
        *,
        enabled: bool,
        confirm_write_op: bool,
        actor_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        self.calls.append("set_agent_toolset_tool_enabled")
        if self.get_agent_toolset_tool(tenant_id, toolset_id, tool_id) is None:
            return None
        tool = self.tools[str(tool_id)]
        if enabled and tool["write_op"] and not confirm_write_op:
            return None
        confirmed = enabled and tool["write_op"]
        tool.update(
            enabled=enabled,
            write_confirmed_by=actor_id if confirmed else None,
            write_confirmed_at=_now() if confirmed else None,
            updated_by=actor_id,
            updated_at=_now(),
        )
        self._check(tool)
        return dict(tool)
