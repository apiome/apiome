"""Nothing crosses a tenant in the Pact Broker schema — PFX-6.1 (#6953).

V251 made "a contract cannot be attached to a consumer of another project" a rule the database keeps,
with composite foreign keys. The PFX migrations (V432 onward) follow the same rule for tenants: a
row has exactly one tenant, so every reference that could name a row of *another* tenant carries the
tenant (or the pacticipant that pins it) as a second column.

This suite reads every PFX migration in order, replays its foreign keys (inline ``REFERENCES``,
table ``FOREIGN KEY`` constraints, ``ALTER TABLE … ADD`` and ``DROP CONSTRAINT``), and checks the
schema they leave behind:

* a table that carries ``tenant_id`` references other tenant-owned rows only through a composite key —
  a single-column reference would let the row's two tenants disagree (V447 fixed three of these);
* a table without ``tenant_id`` references its parent with one key, and every other reference shares
  that parent's column (``pacticipant_branch``: ``(head_version_id, pacticipant_id)``);
* the only exceptions are references to ``users`` and ``tenants`` (which are not tenant-owned rows) and
  the documented ``provider_contract_publication.source_version_id`` (``versions`` carries no tenant).

``test_pact_tenant_isolation_db.py`` proves the same against a migrated database's catalog, and that
the database refuses a cross-tenant row.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Set, Tuple

_SCRIPTS = Path(__file__).resolve().parents[2] / "apiome-db" / "scripts"

#: The first PFX migration (the pacticipant registry, #6914).
_FIRST_PFX = 432
#: A PFX migration's name names its subject.
_PFX_NAME = re.compile(r"pact|pacticipant|provider_contract|bidirectional")

#: Referenced tables that are not tenant-owned rows.
_NOT_TENANT_OWNED = {"users", "tenants"}

#: Single-column references kept on purpose, with the reason.
_EXCEPTIONS: Dict[Tuple[str, str], str] = {
    ("provider_contract_publication", "source_version_id"): (
        "versions carries no tenant_id (its tenant is its project's); source_project_id is a composite "
        "(…, tenant_id) reference"
    ),
}


@dataclass(frozen=True)
class ForeignKey:
    """One foreign key the migrations leave in place."""

    table: str
    name: str
    columns: Tuple[str, ...]
    referenced: str


def _pfx_migrations() -> List[Path]:
    """The PFX migrations, in the order the migrator applies them."""
    scripts = []
    for path in _SCRIPTS.glob("V*__*.sql"):
        version = int(re.match(r"V(\d+)__", path.name).group(1))
        if version >= _FIRST_PFX and _PFX_NAME.search(path.name):
            scripts.append((version, path))
    return [path for _, path in sorted(scripts)]


def _statements(sql: str) -> str:
    """SQL with comments removed and whitespace collapsed (``apiome.`` prefixes dropped)."""
    sql = re.sub(r"--[^\n]*", "", sql)
    sql = re.sub(r"\s+", " ", sql)
    return sql.replace("apiome.", "")


_CREATE = re.compile(r"CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\);", re.S)
_INLINE = re.compile(
    r"(?:^|, |ADD COLUMN IF NOT EXISTS )(\w+) UUID(?: NOT NULL)?(?: DEFAULT \S+)? REFERENCES (\w+) ?\("
)
_TABLE_FK = re.compile(r"(?:CONSTRAINT (\w+) )?FOREIGN KEY \(([^)]*)\) REFERENCES (\w+) ?\(")
_ALTER = re.compile(r"ALTER TABLE (?:ONLY )?(\w+) (.*?);", re.S)
_DROP = re.compile(r"DROP CONSTRAINT IF EXISTS (\w+)")


def _keys_in(table: str, body: str) -> List[ForeignKey]:
    """The foreign keys declared in a ``CREATE TABLE`` body or an ``ALTER TABLE`` clause."""
    keys = []
    for column, referenced in _INLINE.findall(body):
        keys.append(ForeignKey(table, f"{table}_{column}_fkey", (column,), referenced))
    for name, columns, referenced in _TABLE_FK.findall(body):
        cols = tuple(c.strip() for c in columns.split(","))
        keys.append(ForeignKey(table, name or f"{table}_{'_'.join(cols)}_fkey", cols, referenced))
    return keys


def _schema() -> Tuple[Dict[str, ForeignKey], Dict[str, Set[str]]]:
    """Replay the PFX migrations: the foreign keys left in place, and each new table's columns."""
    keys: Dict[str, ForeignKey] = {}
    columns: Dict[str, Set[str]] = {}
    for path in _pfx_migrations():
        sql = _statements(path.read_text(encoding="utf-8"))
        for table, body in _CREATE.findall(sql):
            columns[table] = set(
                re.findall(r"(?:^|, )(\w+) (?:UUID|TEXT|VARCHAR|INTEGER|BOOLEAN|CHAR|TIMESTAMP|JSONB|BIGINT)", body)
            )
            for key in _keys_in(table, body):
                keys[key.name] = key
        for table, clause in _ALTER.findall(sql):
            for name in _DROP.findall(clause):
                keys.pop(name, None)
            for key in _keys_in(table, clause):
                keys[key.name] = key
    return keys, columns


KEYS, COLUMNS = _schema()


def _tenant_owned(table: str) -> List[ForeignKey]:
    """A table's references to tenant-owned rows."""
    return [k for k in KEYS.values() if k.table == table and k.referenced not in _NOT_TENANT_OWNED]


def test_the_replay_reads_the_pfx_tables() -> None:
    """Guard the parser: the registry, publication and webhook tables and their keys are all read."""
    for table in (
        "pacticipant",
        "pacticipant_version",
        "pact_version",
        "pact_publication",
        "pact_webhook",
        "pact_triggered_webhook",
        "deployed_version",
        "pact_commit_status",
        "pact_provider_state",
    ):
        assert table in COLUMNS, f"{table} not read from the PFX migrations"
    assert "tenant_id" in COLUMNS["pacticipant"] and "tenant_id" not in COLUMNS["pacticipant_version"]
    assert KEYS["pacticipant_branch_version_branch_fk"].columns == ("branch_id", "pacticipant_id")
    assert len(KEYS) > 40


def test_a_table_with_a_tenant_references_tenant_owned_rows_only_through_composite_keys() -> None:
    """A single-column reference from a tenant-carrying row could name another tenant's row."""
    tables = {key.table for key in KEYS.values()}
    crossing = []
    for table in sorted(tables):
        carries_tenant = "tenant_id" in COLUMNS.get(table, set()) or any(
            "tenant_id" in key.columns for key in KEYS.values() if key.table == table
        )
        if not carries_tenant and table in COLUMNS:
            continue
        for key in _tenant_owned(table):
            if len(key.columns) == 1 and (table, key.columns[0]) not in _EXCEPTIONS:
                crossing.append(f"{table}.{key.columns[0]} → {key.referenced}")
    assert crossing == [], "single-column references from tenant-carrying tables:\n" + "\n".join(crossing)


def test_a_table_without_a_tenant_shares_one_parent_column_across_its_references() -> None:
    """``pacticipant_version``-style children: one parent, and every other key carries its column."""
    for table, cols in COLUMNS.items():
        if "tenant_id" in cols:
            continue
        keys = _tenant_owned(table)
        singles = [key for key in keys if len(key.columns) == 1]
        assert len(singles) <= 1, f"{table} has several single-column parents: {singles}"
        if singles:
            anchor = singles[0].columns[0]
            for key in keys:
                assert anchor in key.columns, f"{table}.{key.name} does not carry its parent {anchor}"
        else:
            shared = set.intersection(*(set(key.columns) for key in keys)) if keys else {"-"}
            assert shared, f"{table}: its references share no column, so they could name two tenants"


def test_v447_closes_the_three_single_column_references() -> None:
    """The webhook delivery, the firing and the commit status now carry their tenant."""
    assert KEYS["push_webhook_delivery_events_pact_webhook_fk"].columns == ("pact_webhook_id", "tenant_id")
    assert KEYS["pact_triggered_webhook_delivery_fk"].columns == ("delivery_event_id", "tenant_id")
    assert KEYS["pact_commit_status_repository_fk"].columns == ("repository_id", "tenant_id")
    for superseded in (
        "push_webhook_delivery_events_pact_webhook_id_fkey",
        "pact_triggered_webhook_delivery_event_id_fkey",
        "pact_commit_status_repository_id_fkey",
    ):
        assert superseded not in KEYS


def test_v447_keeps_the_delete_behaviour_and_indexes_each_new_key() -> None:
    sql = _statements((_SCRIPTS / "V447__pact_tenant_isolation_6953.sql").read_text(encoding="utf-8"))
    assert sql.strip().startswith("SET search_path TO apiome, public;")
    assert "REFERENCES pact_webhook (id, tenant_id) ON DELETE CASCADE" in sql
    assert "REFERENCES push_webhook_delivery_events (id, tenant_id) ON DELETE CASCADE" in sql
    assert "REFERENCES tenant_repositories (id, tenant_id) ON DELETE SET NULL (repository_id)" in sql
    for index in (
        "ON push_webhook_delivery_events (pact_webhook_id, tenant_id) WHERE pact_webhook_id IS NOT NULL",
        "ON pact_triggered_webhook (delivery_event_id, tenant_id)",
        "ON pact_commit_status (repository_id, tenant_id) WHERE repository_id IS NOT NULL",
    ):
        assert index in sql
    assert "UNIQUE (id, tenant_id)" in sql


def test_every_exception_is_still_a_reference() -> None:
    """A stale exception (the reference made composite or removed) fails rather than lingering."""
    for table, column in _EXCEPTIONS:
        assert any(k.table == table and k.columns == (column,) for k in KEYS.values()), (table, column)
