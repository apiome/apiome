"""Guardrails for the contract-protocol migration — XPC-1.2 (#5730).

V371 adds ``protocol`` to ``verification_target`` and ``verification_run``. What is pinned here:

* both columns default to ``http`` — every target and run that existed before the GraphQL adapter
  *was* HTTP, and the default records that rather than leaving the column to be guessed;
* both are CHECKed against exactly the adapter list in :mod:`app.contract_protocols`, so the
  database and the API refuse the same values;
* the migration is additive — no row is updated, which V212's immutability triggers on
  ``verification_run`` would refuse anyway.
"""

import re
from pathlib import Path

from app.contract_protocols import CONTRACT_PROTOCOLS

_MIGRATION = "apiome-db/scripts/V371__contract_protocol_xpc_1_2.sql"

_REQUIRED_FRAGMENTS = (
    "ALTER TABLE apiome.verification_target\n    ADD COLUMN IF NOT EXISTS protocol TEXT NOT NULL "
    "DEFAULT 'http';",
    "ALTER TABLE apiome.verification_run\n    ADD COLUMN IF NOT EXISTS protocol TEXT NOT NULL "
    "DEFAULT 'http';",
    "verification_target_protocol_check",
    "verification_run_protocol_check",
)

_FORBIDDEN_FRAGMENTS = (
    "UPDATE apiome.verification_run",
    "UPDATE apiome.verification_target",
    "seed_builtin_roles",
)


def test_migration_adds_both_protocol_columns(repo_root: Path) -> None:
    text = (repo_root / _MIGRATION).read_text()
    missing = [fragment for fragment in _REQUIRED_FRAGMENTS if fragment not in text]
    assert not missing, f"Migration missing expected fragments: {missing}"


def test_the_check_constraints_match_the_adapter_list(repo_root: Path) -> None:
    text = (repo_root / _MIGRATION).read_text()
    checks = re.findall(r"CHECK \(protocol IN \(([^)]*)\)\)", text)
    assert len(checks) == 2
    for check in checks:
        values = tuple(value.strip().strip("'") for value in check.split(","))
        assert values == CONTRACT_PROTOCOLS


def test_migration_is_additive(repo_root: Path) -> None:
    text = (repo_root / _MIGRATION).read_text()
    present = [fragment for fragment in _FORBIDDEN_FRAGMENTS if fragment in text]
    assert not present, f"Migration unexpectedly touches: {present}"


def test_migration_version_number_is_unique(repo_root: Path) -> None:
    scripts = repo_root / "apiome-db" / "scripts"
    claimed = [path.name for path in scripts.glob("V371__*.sql")]
    assert claimed == ["V371__contract_protocol_xpc_1_2.sql"]
