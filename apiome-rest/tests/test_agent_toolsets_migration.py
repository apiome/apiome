"""Guardrails for the agent toolset migration — AGX-1.2 (#4530).

V270 adds ``agent_toolsets`` / ``agent_toolset_tools`` and closes the AGX-2.2 / AGX-3.1 handoffs.
Each fragment below pins a structural promise so a later edit that relaxes it fails here rather than
in production:

* one toolset per version, targeting ``prod`` or ``mock``;
* tool rows reference operations by canonical key and record the AGX-1.1 tool name;
* an enabled write op must carry a confirmation (``agent_toolset_tools_write_confirmed_ck``);
* orphaned upstream credentials and agent keys are deleted *before* the composite
  ``(tenant_id, toolset_id)`` foreign keys are added, so the migration cannot fail on old rows.

The fragments are kept in lock-step with :mod:`app.agent_toolsets` by the constant checks at the end.
"""

import re
from pathlib import Path

from app.agent_toolsets import DEFAULT_TARGET, ToolsetTarget
from app.tool_projection import TOOL_NAME_PATTERN

_MIGRATION = "apiome-db/scripts/V270__agent_toolsets_agx_1_2.sql"

_REQUIRED_FRAGMENTS = (
    "CREATE TABLE IF NOT EXISTS agent_toolsets (",
    "version_id UUID NOT NULL REFERENCES versions(id) ON DELETE CASCADE",
    "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE",
    "CONSTRAINT agent_toolsets_version_uq UNIQUE (version_id)",
    "CONSTRAINT agent_toolsets_tenant_id_uq UNIQUE (tenant_id, id)",
    "CHECK (target IN ('prod', 'mock'))",
    "CREATE TABLE IF NOT EXISTS agent_toolset_tools (",
    "toolset_id UUID NOT NULL REFERENCES agent_toolsets(id) ON DELETE CASCADE",
    "operation_key TEXT NOT NULL",
    "write_op BOOLEAN NOT NULL",
    "(write_op AND enabled AND write_confirmed_at IS NOT NULL)",
    "OR (NOT (write_op AND enabled) AND write_confirmed_at IS NULL)",
    "CONSTRAINT agent_toolset_tools_operation_uq UNIQUE (toolset_id, operation_key)",
    "CONSTRAINT agent_toolset_tools_name_uq UNIQUE (toolset_id, tool_name)",
    "CREATE INDEX IF NOT EXISTS idx_agent_toolset_tools_enabled",
    "ADD CONSTRAINT upstream_credentials_toolset_fk",
    "ADD CONSTRAINT api_keys_agent_toolset_fk",
)


def _sql(repo_root: Path) -> str:
    return (repo_root / _MIGRATION).read_text(encoding="utf-8")


def _ddl(repo_root: Path) -> str:
    """The migration's statements only: ``--`` comments and ``COMMENT ON`` prose removed."""
    sql = re.sub(r"--[^\n]*", "", _sql(repo_root))
    return re.sub(r"COMMENT ON .*?;", "", sql, flags=re.DOTALL)


def test_migration_carries_every_structural_promise(repo_root: Path) -> None:
    sql = _sql(repo_root)
    missing = [fragment for fragment in _REQUIRED_FRAGMENTS if fragment not in sql]
    assert missing == []


def test_orphans_are_removed_before_the_foreign_keys_are_added(repo_root: Path) -> None:
    ddl = _ddl(repo_root)
    credentials = ddl.index("DELETE FROM upstream_credentials")
    keys = ddl.index("DELETE FROM api_keys")
    assert "k.kind = 'agent'" in ddl[keys : ddl.index(";", keys)]  # workspace keys untouched
    assert max(credentials, keys) < ddl.index("ADD CONSTRAINT upstream_credentials_toolset_fk")
    assert max(credentials, keys) < ddl.index("ADD CONSTRAINT api_keys_agent_toolset_fk")


def test_handoff_foreign_keys_are_tenant_scoped_and_cascade(repo_root: Path) -> None:
    ddl = re.sub(r"\s+", " ", _ddl(repo_root))
    expected = (
        "FOREIGN KEY (tenant_id, toolset_id) REFERENCES agent_toolsets (tenant_id, id) "
        "ON DELETE CASCADE"
    )
    assert ddl.count(expected) == 2


def test_no_new_rbac_resource(repo_root: Path) -> None:
    lowered = _ddl(repo_root).lower()
    assert "seed_builtin_roles" not in lowered
    assert "role_permissions" not in lowered


def test_the_schema_matches_the_application_constants(repo_root: Path) -> None:
    sql = _sql(repo_root)
    assert set(ToolsetTarget.__args__) == {"prod", "mock"}
    assert f"DEFAULT '{DEFAULT_TARGET}'" in sql
    assert f"tool_name ~ '{TOOL_NAME_PATTERN.pattern}'" in sql
