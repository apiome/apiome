"""Guardrails for the contract-protocol migration — XPC-1.2 (#5730).

V371 adds ``protocol`` to ``verification_target`` and ``verification_run``. What is pinned here:

* both columns default to ``http`` — every target and run that existed before the GraphQL adapter
  *was* HTTP, and the default records that rather than leaving the column to be guessed;
* both are CHECKed against exactly the adapter list in :mod:`app.contract_protocols`, so the
  database and the API refuse the same values — V374 (XPC-3.2, #5742) widens both checks to
  ``grpc`` and ``connect``;
* the migration is additive — no row is updated, which V212's immutability triggers on
  ``verification_run`` would refuse anyway.
"""

import re
from pathlib import Path

from app.contract_protocols import CONTRACT_PROTOCOLS

_MIGRATION = "apiome-db/scripts/V371__contract_protocol_xpc_1_2.sql"
_WIDENING = "apiome-db/scripts/V374__contract_protocol_grpc_xpc_3_2.sql"

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


def _check_values(text: str):
    """The value lists of every ``CHECK (protocol IN (…))`` in a migration's executable SQL."""
    executable = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("--"))
    checks = re.findall(r"CHECK \(protocol IN \(([^)]*)\)\)", executable)
    return [tuple(value.strip().strip("'") for value in check.split(",")) for check in checks]


def test_the_check_constraints_match_the_adapter_list_of_their_time(repo_root: Path) -> None:
    # V371 constrained to the adapters of XPC-1.2; V374 (XPC-3.2) widens to the current list.
    assert _check_values((repo_root / _MIGRATION).read_text()) == [("http", "graphql")] * 2
    assert _check_values((repo_root / _WIDENING).read_text()) == [CONTRACT_PROTOCOLS] * 2


def test_widening_drops_and_re_adds_both_constraints_without_touching_rows(
    repo_root: Path,
) -> None:
    text = (repo_root / _WIDENING).read_text()
    for table in ("verification_target", "verification_run"):
        assert f"DROP CONSTRAINT IF EXISTS {table}_protocol_check;" in text
        assert f"ADD CONSTRAINT {table}_protocol_check" in text
    present = [fragment for fragment in _FORBIDDEN_FRAGMENTS if fragment in text]
    assert not present, f"Migration unexpectedly touches: {present}"


def test_migration_is_additive(repo_root: Path) -> None:
    text = (repo_root / _MIGRATION).read_text()
    present = [fragment for fragment in _FORBIDDEN_FRAGMENTS if fragment in text]
    assert not present, f"Migration unexpectedly touches: {present}"


def test_migration_version_number_is_unique(repo_root: Path) -> None:
    scripts = repo_root / "apiome-db" / "scripts"
    claimed = [path.name for path in scripts.glob("V371__*.sql")]
    assert claimed == ["V371__contract_protocol_xpc_1_2.sql"]
    claimed = [path.name for path in scripts.glob("V374__*.sql")]
    assert claimed == ["V374__contract_protocol_grpc_xpc_3_2.sql"]
