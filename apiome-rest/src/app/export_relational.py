"""The relational projection of a database export, as data — MFX-45.3 (#4376).

A database target (SQL DDL and its DBML, Prisma, Liquibase and Flyway outputs, MFX-EPIC-35) lays the
canonical model out as tables. The emitter used to keep that layout to itself and return only the text.
This module is its wire shape: the emitter returns it on :attr:`app.emitter.EmitResult.relational`, and
the export preview manifest (IXH-4.1) hands it to the Review step, which draws it as an entity-relationship
diagram.

Every table, column and foreign key says whether the projection **made it up** (``synthesized``): a
generated key, the foreign key a nested record became, a junction table for a list of records, a child
table for a list of values. Those are the decisions the fidelity report files as ``SYNTH``; the diagram
marks them.

Each table and column also names the canonical construct it came from (``entity_key``), so a selection in
the diagram is the same selection as in the manifest tree and the code viewer.
"""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "RelationalColumn",
    "RelationalForeignKey",
    "RelationalReference",
    "RelationalSchema",
    "RelationalTable",
]


class RelationalReference(BaseModel):
    """The column a foreign-key column points at."""

    model_config = ConfigDict(extra="forbid")

    table: str = Field(description="The referenced table's name.")
    column: str = Field(description="The referenced column's name.")


class RelationalColumn(BaseModel):
    """One column of a table."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="The column name, as written.")
    type: str = Field(description="The column's SQL type in the export's dialect (e.g. `VARCHAR(64)`, `BIGINT`).")
    not_null: bool = Field(default=False, description="True when the column is NOT NULL.")
    primary_key: bool = Field(default=False, description="True when the column is part of the primary key.")
    unique: bool = Field(default=False, description="True when the column is part of a unique key.")
    identity: bool = Field(default=False, description="True when the database generates the value.")
    synthesized: bool = Field(
        default=False,
        description="True when the projection made the column up (a generated key, a foreign key a nested "
        "record became, a junction or child table's column).",
    )
    entity_key: Optional[str] = Field(
        default=None, description="The canonical construct the column came from (a field or the record's key)."
    )
    references: Optional[RelationalReference] = Field(
        default=None, description="The column this one points at, when it is a single-column foreign key."
    )


class RelationalForeignKey(BaseModel):
    """One foreign key (an edge of the diagram)."""

    model_config = ConfigDict(extra="forbid")

    columns: List[str] = Field(description="The referencing columns, in this table.")
    table: str = Field(description="The referenced table's name.")
    ref_columns: List[str] = Field(description="The referenced columns.")
    synthesized: bool = Field(
        default=False, description="True when the projection made the foreign key up (not declared in the source)."
    )


class RelationalTable(BaseModel):
    """One table."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="The table name, as written.")
    kind: Literal["table", "junction", "child"] = Field(
        description="`table` for a record; `junction` for a list of records; `child` for a list of values."
    )
    entity_key: str = Field(
        description="The canonical construct the table came from: the record, or the list field a junction or "
        "child table holds."
    )
    synthesized: bool = Field(
        default=False, description="True for a junction or child table — a table the projection made up."
    )
    columns: List[RelationalColumn] = Field(default_factory=list, description="The columns, in written order.")
    primary_key: List[str] = Field(default_factory=list, description="The primary key's columns.")
    unique: List[List[str]] = Field(default_factory=list, description="Each unique key's columns.")
    foreign_keys: List[RelationalForeignKey] = Field(default_factory=list, description="The foreign keys.")


class RelationalSchema(BaseModel):
    """The relational projection of one database export."""

    model_config = ConfigDict(extra="forbid")

    dialect: str = Field(description="`postgres`, `mysql` or `ansi`.")
    output: str = Field(description="The written output: `ddl`, `dbml`, `prisma`, `liquibase` or `flyway`.")
    schema_name: Optional[str] = Field(default=None, description="The schema the tables are created in, if any.")
    tables: List[RelationalTable] = Field(default_factory=list, description="Every table, in written order.")
