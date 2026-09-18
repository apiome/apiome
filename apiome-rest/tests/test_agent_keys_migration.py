"""Guardrails for the agent key migration — AGX-3.1 (#4537).

V269 extends ``api_keys`` with ``kind`` / ``toolset_id`` / ``tool_allowlist`` rather than adding a
table. Each fragment below pins a structural promise so a later edit that relaxes it fails here
rather than in production:

* The two kinds are exclusive: an agent key has a toolset and an allowlist, a workspace key has
  neither.
* An agent key carries exactly the ``agent:invoke`` scope (no REST route allowlists it), and a
  workspace key may never hold it.
* The allowlist is a JSON array of at most 1024 AGX-1.1 tool names, checked in ``strict`` mode.
* Agent keys are indexed by prefix *including* revoked rows, so the MCP middleware can say "revoked".

Two **negative** assertions as well: the migration seeds no RBAC resource (the API reuses
``api_keys``), and ``toolset_id`` has no foreign key yet (``agent_toolsets`` is AGX-1.2, #4530).
The fragments are kept in lock-step with :mod:`app.agent_keys` by the constant checks at the end.
"""

import re
from pathlib import Path

from app.agent_keys import AGENT_KEY_KIND, AGENT_KEY_SCOPE, TOOL_ALLOWLIST_MAX_ENTRIES
from app.tool_projection import TOOL_NAME_PATTERN

_MIGRATION = "apiome-db/scripts/V269__agent_keys_agx_3_1.sql"

_REQUIRED_FRAGMENTS = (
    "ALTER TABLE api_keys",
    "ADD COLUMN IF NOT EXISTS kind VARCHAR(16) NOT NULL DEFAULT 'workspace'",
    "ADD COLUMN IF NOT EXISTS toolset_id UUID,",
    "ADD COLUMN IF NOT EXISTS tool_allowlist JSONB;",
    # Rule 1: exclusive kinds.
    "CHECK (kind IN ('workspace', 'agent'))",
    "(kind = 'agent' AND toolset_id IS NOT NULL AND tool_allowlist IS NOT NULL)",
    "OR (kind = 'workspace' AND toolset_id IS NULL AND tool_allowlist IS NULL)",
    # Rule 2: not a REST credential.
    "scopes <@ ARRAY['*', 'diff:read', 'lint:read', 'agent:invoke']::text[]",
    "(kind = 'agent' AND scopes = ARRAY['agent:invoke']::text[])",
    "OR (kind = 'workspace' AND NOT ('agent:invoke' = ANY (scopes)))",
    # Rule 3: an explicit allowlist of tool names.
    "jsonb_typeof(tool_allowlist) = 'array'",
    "AND jsonb_array_length(tool_allowlist) <= 1024",
    """'strict $[*] ? (@.type() != "string" || !(@ like_regex "^[A-Za-z0-9_-]{1,64}$"))'""",
    # Rule 5: prefix lookups see revoked agent keys too.
    "CREATE INDEX IF NOT EXISTS idx_api_keys_agent_prefix",
    "ON api_keys (key_prefix)\n  WHERE kind = 'agent';",
    "CREATE INDEX IF NOT EXISTS idx_api_keys_agent_toolset",
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


def test_it_extends_api_keys_and_reuses_the_existing_expiry(repo_root: Path) -> None:
    ddl = _ddl(repo_root)
    assert "CREATE TABLE" not in ddl
    assert "ADD COLUMN IF NOT EXISTS expires_at" not in ddl
    assert "revoked_at" not in ddl


def test_toolset_id_has_no_foreign_key_yet(repo_root: Path) -> None:
    assert "REFERENCES agent_toolsets" not in _ddl(repo_root)


def test_no_new_rbac_resource(repo_root: Path) -> None:
    lowered = _ddl(repo_root).lower()
    assert "seed_builtin_roles" not in lowered
    assert "role_permissions" not in lowered


def test_the_schema_matches_the_application_constants(repo_root: Path) -> None:
    sql = _sql(repo_root)
    assert f"'{AGENT_KEY_KIND}'" in sql
    assert f"ARRAY['{AGENT_KEY_SCOPE}']::text[]" in sql
    assert f"jsonb_array_length(tool_allowlist) <= {TOOL_ALLOWLIST_MAX_ENTRIES}" in sql
    assert f'like_regex "{TOOL_NAME_PATTERN.pattern}"' in sql
