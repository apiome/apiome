"""Liquibase / Flyway changelog mode of the SQL DDL export — MFX-35.3 (#4313).

A one-shot ``CREATE TABLE`` dump is not how teams apply schema changes: they run migrations. With
``output=liquibase`` or ``output=flyway`` the SQL DDL export (:mod:`app.sql_ddl_emitter`) writes its
relational projection as migration changesets instead:

* **Liquibase** — a *formatted SQL* changelog, ``NNNN-<name>.changelog.sql``: ``--liquibase formatted
  sql`` and one ``--changeset <author>:<id>`` per statement (ids keep counting across exports), each
  with a ``--comment``. A PostgreSQL ``ALTER TYPE … ADD VALUE`` is marked ``runInTransaction:false``.
* **Flyway** — one versioned migration, ``V<n>__<description>.sql``, holding the same statements.

**First export, then deltas.** Without a baseline (the first export of an artifact in that dialect and
mode, or ``from_scratch``), every table, enum and foreign key is created. With one — the
:func:`next_baseline` an earlier export persisted (:mod:`app.export_service`, table
``apiome.export_schema_baselines``) — only the delta is written:

1. the **canonical diff** (MFI-3.2, :func:`app.import_source.canonical_diff`) between the baseline's
   model and this one names the record types that were added, removed or changed (a field change
   counts for its record; a junction or child table belongs to the record of the field it comes from);
2. for those tables only, the baseline's projection is compared with this one and turned into
   statements, in an order that never breaks a reference: dropped foreign keys, dropped tables, new
   enum types and values, new tables, added / dropped / altered columns, then new foreign keys.

A change SQL cannot apply in place — a column's ``CHECK`` or identity, a table's primary or unique key,
a removed PostgreSQL enum value — is not written and is reported, so a reader knows to migrate it by
hand. Tables the canonical diff does not touch are left alone, and the new baseline keeps what the
database holds for them.

Everything here is pure: the baseline comes in through the emit options and goes out on the
:class:`~app.emitter.EmitResult`; persisting it is the export service's job.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple

from .canonical_model import CanonicalApi, TypeKind
from .emitter import LossKind

__all__ = [
    "BASELINE_VERSION",
    "CHANGELOG_MODES",
    "LOSS_CHANGELOG_BASELINE",
    "LOSS_CHANGELOG_NOT_ALTERED",
    "ChangelogOutput",
    "baseline_variant",
    "changelog_statements",
    "render_changelog",
]

#: The two changelog outputs.
CHANGELOG_MODES = ("liquibase", "flyway")
#: Version of the persisted baseline document; a baseline of another version is ignored.
BASELINE_VERSION = 1
#: Loss subjects.
LOSS_CHANGELOG_BASELINE = "sql-changelog-baseline"
LOSS_CHANGELOG_NOT_ALTERED = "sql-changelog-not-altered"

_MAX_IDENTIFIER: Dict[str, int] = {"postgres": 63, "mysql": 64, "ansi": 128}


def baseline_variant(dialect: str, mode: str) -> str:
    """The store key of one dialect and changelog mode (``postgres:liquibase``)."""
    return f"{dialect}:{mode}"


@dataclass
class _Change:
    """One statement of the changelog."""

    description: str
    sql: str
    in_transaction: bool = True


@dataclass
class ChangelogOutput:
    """What a changelog render produces.

    Attributes:
        path: The file name.
        text: The changelog or migration text.
        baseline: The baseline the next export diffs against.
        notes: ``(kind, subject, detail, pointer)`` per loss to record.
        statements: How many statements (changesets) were written.
        incremental: Whether this is a delta against a baseline.
    """

    path: str
    text: str
    baseline: Dict[str, Any]
    notes: List[Tuple[LossKind, str, str, str]] = field(default_factory=list)
    statements: int = 0
    incremental: bool = False


# ===========================================================================
# The projection snapshot
# ===========================================================================


def _column_snapshot(column: Any) -> Dict[str, Any]:
    """The comparable facts of one column."""
    return {"name": column.name, "sql_type": column.sql_type, "not_null": column.not_null,
            "default": column.default, "checks": list(column.checks), "primary": column.primary,
            "identity": column.identity}


def _fk_name(table_name: str, index: int, dialect: str) -> str:
    """The name the full DDL gives a table's ``index``-th foreign key."""
    return f"fk_{table_name}_{index}"[: _MAX_IDENTIFIER[dialect]]


def _snapshot(writer: Any) -> Dict[str, Any]:
    """The projection as JSON: every table (its columns, keys, checks, named foreign keys) and enum type."""
    tables: Dict[str, Any] = {}
    for table in writer.tables:
        tables[table.key] = {
            "name": table.name,
            "columns": [_column_snapshot(c) for c in table.columns],
            "primary_key": list(table.primary_key),
            "unique": [list(u) for u in table.unique],
            "checks": list(table.checks),
            "foreign_keys": [
                {"name": _fk_name(table.name, i, writer.dialect), "columns": list(cols), "target": target,
                 "target_columns": list(target_cols)}
                for i, (cols, target, target_cols) in enumerate(table.foreign_keys, start=1)
            ],
        }
    enums = {key: {"name": name, "values": writer.enum_labels(key)} for key, name in writer.enum_type_names().items()}
    return {"tables": tables, "enums": enums}


# ===========================================================================
# Planning
# ===========================================================================


def _owner_keys(api: CanonicalApi) -> Dict[str, str]:
    """Field key → the key of the record it belongs to."""
    return {member.key: type_.key for type_ in api.types if type_.kind is TypeKind.RECORD for member in type_.fields}


def _changed_records(previous: CanonicalApi, current: CanonicalApi) -> Set[str]:
    """The record (and enum) type keys the canonical diff adds, removes or changes."""
    from .import_source import canonical_diff  # noqa: PLC0415 - import_source pulls the adapter registry

    owners = {**_owner_keys(previous), **_owner_keys(current)}
    changed: Set[str] = set()
    for entry in canonical_diff(previous, current).entries:
        entity = getattr(entry.entity, "value", entry.entity)
        if entity == "type":
            changed.add(entry.key)
        elif entity == "field" and entry.key in owners:
            changed.add(owners[entry.key])
    return changed


def _table_owner(table_key: str, owners: Mapping[str, str]) -> str:
    """The record a table belongs to: itself, or (a junction / child table) the record of its field."""
    if table_key.endswith("#table"):
        return owners.get(table_key[: -len("#table")], table_key)
    return table_key


def _fk_signature(fk: Mapping[str, Any]) -> Tuple[Tuple[str, ...], str, Tuple[str, ...]]:
    return tuple(fk["columns"]), fk["target"], tuple(fk["target_columns"])


class _Planner:
    """Turns (baseline, current projection) into ordered statements and the next snapshot."""

    def __init__(self, writer: Any, api: CanonicalApi) -> None:
        self.writer = writer
        self.api = api
        self.dialect = writer.dialect
        self.changes: List[_Change] = []
        self.notes: List[Tuple[LossKind, str, str, str]] = []

    # --- full ----------------------------------------------------------------

    def full(self) -> Dict[str, Any]:
        """Every statement of the projection; returns the snapshot it creates."""
        w = self.writer
        if w.options.schema_name:
            self.changes.append(_Change(f"create schema {w.options.schema_name}", w.schema_statement()))
        for key, name in w.enum_type_names().items():
            self.changes.append(_Change(f"create enum type {name}", w.enum_statement(key)))
        for table in w.tables:
            self.changes.append(_Change(f"create table {table.name}", w.create_table_sql(table)))
        snapshot = _snapshot(w)
        for table in w.tables:
            for fk in snapshot["tables"][table.key]["foreign_keys"]:
                self.changes.append(_Change(f"add foreign key {fk['name']}", self._add_fk(table.name, fk)))
        return snapshot

    # --- delta ---------------------------------------------------------------

    def delta(self, previous_api: CanonicalApi, previous: Mapping[str, Any]) -> Dict[str, Any]:
        """Only what changed since ``previous``; returns the snapshot the database then holds."""
        current = _snapshot(self.writer)
        changed = _changed_records(previous_api, self.api)
        owners = {**_owner_keys(previous_api), **_owner_keys(self.api)}
        old_tables: Dict[str, Any] = dict(previous.get("tables") or {})
        new_tables: Dict[str, Any] = current["tables"]

        def affected(key: str) -> bool:
            return _table_owner(key, owners) in changed or (key in old_tables) != (key in new_tables)

        touched = sorted({k for k in (*old_tables, *new_tables) if affected(k)})
        result_tables = {k: v for k, v in old_tables.items() if k not in touched}

        # 1. Foreign keys that go away (their table is dropped or the reference changed).
        kept_fk_names: Dict[str, Dict[Tuple, str]] = {}
        for key in touched:
            old = old_tables.get(key)
            if old is None:
                continue
            new = new_tables.get(key)
            new_sigs = {_fk_signature(fk) for fk in (new or {}).get("foreign_keys", [])}
            kept_fk_names[key] = {}
            for fk in old.get("foreign_keys", []):
                if new is not None and _fk_signature(fk) in new_sigs:
                    kept_fk_names[key][_fk_signature(fk)] = fk["name"]
                else:
                    self.changes.append(_Change(f"drop foreign key {fk['name']}",
                                                self._drop_fk(old["name"], fk["name"])))
        # 2. Tables that go away.
        for key in touched:
            if key in old_tables and key not in new_tables:
                name = old_tables[key]["name"]
                self.changes.append(_Change(f"drop table {name}", f"DROP TABLE {self.writer.qualified(name)};"))
        # 3. Enum types (PostgreSQL).
        result_enums = self._enums(previous.get("enums") or {}, current["enums"], changed)
        # 4. New tables.
        by_key = {table.key: table for table in self.writer.tables}
        for key in touched:
            if key not in old_tables and key in new_tables:
                self.changes.append(_Change(f"create table {new_tables[key]['name']}",
                                            self.writer.create_table_sql(by_key[key])))
        # 5. Columns of the tables both sides have.
        for key in touched:
            if key in old_tables and key in new_tables:
                self._columns(key, old_tables[key], new_tables[key], by_key[key])
        # 6. New foreign keys, named after the ones the table keeps.
        for key in touched:
            if key not in new_tables:
                continue
            table = dict(new_tables[key])
            kept = kept_fk_names.get(key, {})
            taken = set(kept.values())
            fks = []
            for fk in table["foreign_keys"]:
                name = kept.get(_fk_signature(fk))
                if name is None:
                    index = 1
                    while _fk_name(table["name"], index, self.dialect) in taken:
                        index += 1
                    name = _fk_name(table["name"], index, self.dialect)
                    taken.add(name)
                    fk = {**fk, "name": name}
                    self.changes.append(_Change(f"add foreign key {name}", self._add_fk(table["name"], fk)))
                fks.append({**fk, "name": name})
            table["foreign_keys"] = fks
            result_tables[key] = table
        return {"tables": result_tables, "enums": result_enums}

    def _enums(self, old: Mapping[str, Any], new: Mapping[str, Any], changed: Set[str]) -> Dict[str, Any]:
        """New enum types and values; a removed value is reported (PostgreSQL cannot drop one)."""
        result = {k: v for k, v in old.items() if k not in changed or k in new}
        for key, enum in new.items():
            if key not in old:
                self.changes.append(_Change(f"create enum type {enum['name']}", self.writer.enum_statement(key)))
                result[key] = enum
                continue
            if key not in changed:
                continue
            before = list(old[key]["values"])
            for value in enum["values"]:
                if value not in before:
                    literal = "'" + str(value).replace("'", "''") + "'"
                    self.changes.append(_Change(
                        f"add value {value} to enum type {enum['name']}",
                        f"ALTER TYPE {self.writer.qualified(enum['name'])} ADD VALUE {literal};",
                        in_transaction=False,
                    ))
            removed = [v for v in before if v not in enum["values"]]
            if removed:
                self._note(f"enum type {enum['name']!r} no longer has {', '.join(map(str, removed))}; PostgreSQL "
                           "cannot drop an enum value, so the type keeps it", key)
            result[key] = {**enum, "values": before + [v for v in enum["values"] if v not in before]}
        return result

    def _columns(self, key: str, old: Mapping[str, Any], new: Mapping[str, Any], table: Any) -> None:
        """Added, dropped and altered columns of one table; what cannot be altered in place is reported."""
        name = new["name"]
        q = self.writer.qualified(name)
        old_cols = {c["name"]: c for c in old["columns"]}
        new_cols = {c["name"]: c for c in new["columns"]}
        objects = {c.name: c for c in table.columns}
        for column in old["columns"]:
            if column["name"] not in new_cols:
                self.changes.append(_Change(f"drop column {name}.{column['name']}",
                                            f"ALTER TABLE {q} DROP COLUMN {self.writer.quote(column['name'])};"))
        for column in new["columns"]:
            if column["name"] not in old_cols:
                self.changes.append(_Change(f"add column {name}.{column['name']}",
                                            f"ALTER TABLE {q} ADD COLUMN "
                                            f"{self.writer.column_definition(objects[column['name']])};"))
        for column in new["columns"]:
            before = old_cols.get(column["name"])
            if before is not None:
                self._alter(name, before, column, objects[column["name"]])
        for facet, label in (("primary_key", "primary key"), ("unique", "unique keys"), ("checks", "table checks")):
            if old[facet] != new[facet]:
                self._note(f"the {label} of table {name!r} changed; a changelog does not rewrite keys or checks "
                           "in place, so migrate it by hand", key)

    def _alter(self, table: str, old: Mapping[str, Any], new: Mapping[str, Any], column: Any) -> None:
        """The statements that turn column ``old`` into ``new``."""
        q = self.writer.qualified(table)
        c = self.writer.quote(new["name"])
        retype = old["sql_type"] != new["sql_type"]
        renull = old["not_null"] != new["not_null"]
        redefault = old["default"] != new["default"]
        if self.dialect == "mysql" and (retype or renull or redefault):
            self.changes.append(_Change(f"modify column {table}.{new['name']}",
                                        f"ALTER TABLE {q} MODIFY COLUMN {self.writer.column_definition(column)};"))
        else:
            if retype:
                clause = "TYPE" if self.dialect == "postgres" else "SET DATA TYPE"
                self.changes.append(_Change(f"change type of {table}.{new['name']}",
                                            f"ALTER TABLE {q} ALTER COLUMN {c} {clause} {new['sql_type']};"))
            if renull:
                verb = "SET NOT NULL" if new["not_null"] else "DROP NOT NULL"
                self.changes.append(_Change(f"{verb.lower()} on {table}.{new['name']}",
                                            f"ALTER TABLE {q} ALTER COLUMN {c} {verb};"))
            if redefault:
                clause = f"SET DEFAULT {new['default']}" if new["default"] is not None else "DROP DEFAULT"
                self.changes.append(_Change(f"change default of {table}.{new['name']}",
                                            f"ALTER TABLE {q} ALTER COLUMN {c} {clause};"))
        for facet in ("checks", "primary", "identity"):
            if old[facet] != new[facet]:
                self._note(f"the {facet} of column {table}.{new['name']} changed; a changelog does not rewrite it in "
                           "place, so migrate it by hand", f"{table}.{new['name']}")

    def _add_fk(self, table: str, fk: Mapping[str, Any]) -> str:
        w = self.writer
        return (f"ALTER TABLE {w.qualified(table)} ADD CONSTRAINT {w.quote(fk['name'])} FOREIGN KEY "
                f"({', '.join(w.quote(c) for c in fk['columns'])}) REFERENCES {w.qualified(fk['target'])} "
                f"({', '.join(w.quote(c) for c in fk['target_columns'])});")

    def _drop_fk(self, table: str, name: str) -> str:
        verb = "DROP FOREIGN KEY" if self.dialect == "mysql" else "DROP CONSTRAINT"
        return f"ALTER TABLE {self.writer.qualified(table)} {verb} {self.writer.quote(name)};"

    def _note(self, detail: str, pointer: str) -> None:
        self.notes.append((LossKind.NA, LOSS_CHANGELOG_NOT_ALTERED, detail, pointer))


# ===========================================================================
# Rendering
# ===========================================================================


def _usable_baseline(baseline: Any, writer: Any, mode: str) -> Tuple[Optional[Mapping[str, Any]], Optional[str]]:
    """The baseline when it can be diffed against, else ``(None, why not)``."""
    if not isinstance(baseline, Mapping):
        return None, None
    options = writer.options
    if baseline.get("version") != BASELINE_VERSION:
        return None, "the stored baseline is from another version of the export, so full changesets are written"
    expected = {"dialect": writer.dialect, "mode": mode, "nested": options.nested, "schema_name": options.schema_name}
    for name, value in expected.items():
        if baseline.get(name) != value:
            return None, (f"the stored baseline was written with {name}={baseline.get(name)!r}, not {value!r}, so "
                          "full changesets are written")
    return baseline, None


def render_changelog(writer: Any, api: CanonicalApi, *, mode: str, base: str) -> ChangelogOutput:
    """Write the projection as a Liquibase changelog or a Flyway migration.

    Args:
        writer: The projected :class:`app.sql_ddl_emitter._SqlDdlWriter` (its options carry the
            baseline, ``from_scratch`` and the changeset author).
        api: The canonical model being exported.
        mode: ``liquibase`` or ``flyway``.
        base: The file-name stem (the item's name).

    Returns:
        The file, its text, the next baseline and the losses to record.
    """
    options = writer.options
    planner = _Planner(writer, api)
    baseline, why_not = (None, None) if options.from_scratch else _usable_baseline(
        options.changelog_baseline, writer, mode)
    notes: List[Tuple[LossKind, str, str, str]] = []
    if why_not:
        notes.append((LossKind.INFERRED, LOSS_CHANGELOG_BASELINE, why_not, ""))
    if baseline is not None:
        previous_api = CanonicalApi.model_validate(baseline["canonical"])
        snapshot = planner.delta(previous_api, baseline["snapshot"])
        incremental = True
        notes.append((LossKind.INFERRED, LOSS_CHANGELOG_BASELINE,
                      f"incremental: {len(planner.changes)} change(s) since the last export (the canonical diff "
                      "against the stored baseline)", ""))
    else:
        snapshot = planner.full()
        incremental = False
    notes += planner.notes
    previous = baseline or {}
    first_id = int(previous.get("changeset_seq") or 0) + 1
    flyway_version = int(previous.get("flyway_version") or 0) + 1
    changes = planner.changes
    if mode == "liquibase":
        path = f"{first_id:04d}-{base}.changelog.sql"
        text = _liquibase_text(writer, changes, first_id, incremental)
    else:
        description = "update_schema" if incremental else "initial_schema"
        path = f"V{flyway_version}__{description}.sql"
        text = _flyway_text(writer, changes, incremental)
    if incremental and not changes:
        notes.append((LossKind.INFERRED, LOSS_CHANGELOG_BASELINE,
                      "nothing changed since the last export; the file holds no statements", ""))
    next_baseline = {
        "version": BASELINE_VERSION,
        "dialect": writer.dialect,
        "mode": mode,
        "nested": options.nested,
        "schema_name": options.schema_name,
        "canonical": api.model_copy(update={"raw": None}).model_dump(mode="json"),
        "snapshot": snapshot,
        "changeset_seq": first_id - 1 + len(changes),
        "flyway_version": flyway_version if mode == "flyway" else int(previous.get("flyway_version") or 0),
    }
    return ChangelogOutput(path=path, text=text, baseline=next_baseline, notes=notes, statements=len(changes),
                           incremental=incremental)


def _header(writer: Any, label: str, incremental: bool) -> str:
    kind = "changes since the last export" if incremental else "full schema"
    return f"-- {writer.title}: {label} ({writer.dialect}, {kind}), generated by Apiome.\n"


def _liquibase_text(writer: Any, changes: List[_Change], first_id: int, incremental: bool) -> str:
    """A Liquibase formatted-SQL changelog: one changeset per statement."""
    author = writer.options.changeset_author
    lines = ["--liquibase formatted sql", "", _header(writer, "Liquibase changelog", incremental).rstrip("\n")]
    for offset, change in enumerate(changes):
        attributes = "" if change.in_transaction else " runInTransaction:false"
        lines += ["", f"--changeset {author}:{first_id + offset}{attributes}",
                  f"--comment: {change.description}", change.sql]
    return "\n".join(lines) + "\n"


def _flyway_text(writer: Any, changes: List[_Change], incremental: bool) -> str:
    """A Flyway versioned migration: every statement, each after a comment naming it."""
    lines = [_header(writer, "Flyway migration", incremental).rstrip("\n")]
    if not changes:
        lines.append("-- No changes since the last export.")
    for change in changes:
        lines += ["", f"-- {change.description}", change.sql]
    return "\n".join(lines) + "\n"


def changelog_statements(text: str) -> List[str]:
    """The SQL statements of a rendered changelog or migration (comments and blank lines dropped)."""
    body = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("--")]
    return [s.strip().rstrip(";").rstrip() for s in "\n".join(body).split(";\n") if s.strip().rstrip(";")]
