"""Guardrails for the agent toolset enrichment migration — AGX-1.3 (#4531).

V273 adds ``agent_toolsets.description_enrichment`` and ``agent_toolset_enrichments``. Each fragment
pins a structural promise so a later edit that relaxes it fails here rather than in production:

* only a reviewed proposal can carry text to serve (``agent_toolset_enrichments_review_ck``);
* one proposal per description per toolset, which makes the pass idempotent;
* proposals go with their toolset (``ON DELETE CASCADE``);
* the opt-out defaults to serving accepted text.

The constant checks at the end keep the fragments in lock-step with the application.
"""

import re
from pathlib import Path

from app.agent_tool_enrichment import (
    MAX_PARAM_DESCRIPTION_CHARS,
    MAX_TOOL_DESCRIPTION_CHARS,
    TARGET_PARAMETER,
    TARGET_TOOL,
)

_MIGRATION = "apiome-db/scripts/V273__agent_toolset_enrichment_agx_1_3.sql"

_REQUIRED_FRAGMENTS = (
    "ADD COLUMN IF NOT EXISTS description_enrichment BOOLEAN NOT NULL DEFAULT true",
    "CREATE TABLE IF NOT EXISTS agent_toolset_enrichments (",
    "toolset_id UUID NOT NULL REFERENCES agent_toolsets(id) ON DELETE CASCADE",
    "CHECK (target_kind IN ('tool', 'parameter'))",
    "(target_kind = 'tool') = (parameter_name IS NULL)",
    "CHECK (status IN ('proposed', 'accepted', 'rejected'))",
    "(status = 'proposed' AND accepted_description IS NULL AND reviewed_at IS NULL)",
    "OR (status = 'accepted' AND accepted_description IS NOT NULL AND reviewed_at IS NOT NULL)",
    "OR (status = 'rejected' AND accepted_description IS NULL AND reviewed_at IS NOT NULL)",
    "CONSTRAINT agent_toolset_enrichments_target_uq UNIQUE (toolset_id, target_key)",
    "CREATE INDEX IF NOT EXISTS idx_agent_toolset_enrichments_accepted",
    "WHERE status = 'accepted'",
)


def _migration_sql() -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / _MIGRATION).read_text(encoding="utf-8")


def test_v273_pins_the_review_and_idempotency_rules():
    sql = _migration_sql()
    missing = [fragment for fragment in _REQUIRED_FRAGMENTS if fragment not in sql]
    assert missing == []


def test_v273_is_the_only_migration_with_its_version():
    scripts = Path(__file__).resolve().parents[2] / "apiome-db" / "scripts"
    assert [path.name for path in scripts.glob("V273__*.sql")] == [Path(_MIGRATION).name]


def test_target_kinds_match_the_application():
    sql = _migration_sql()
    assert f"'{TARGET_TOOL}', '{TARGET_PARAMETER}'" in sql


def test_stored_text_bounds_admit_the_applications_caps():
    """The column CHECKs must accept every description the application can produce."""
    sql = _migration_sql()
    bounds = [int(limit) for limit in re.findall(r"BETWEEN 1 AND (\d+)\)", sql)]
    assert bounds and min(bounds) >= max(MAX_TOOL_DESCRIPTION_CHARS, MAX_PARAM_DESCRIPTION_CHARS)
