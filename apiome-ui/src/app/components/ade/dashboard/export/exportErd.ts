/**
 * Export ERD model — the relational projection of a database export as a diagram (MFX-45.3, #4376).
 *
 * A database target (SQL DDL and its DBML / Prisma / Liquibase / Flyway outputs) lays the model out as
 * tables. The export preview manifest returns that layout (`relational`, from the emitter); this module
 * turns it into the nodes and edges the ERD draws (`./ExportErdView.tsx`):
 *
 *  - one node per table, laid out deterministically: a table that references nothing sits in the left
 *    column, and every other table one column right of the furthest table it references
 *    ({@link erdLayout}), so foreign keys read right-to-left and nothing depends on a layout engine;
 *  - one edge per foreign key, from the referencing table to the referenced one;
 *  - what the export **made up** — a generated key, a nested record's foreign key, a junction or child
 *    table — stays marked (`synthesized`), the decisions the fidelity report files as SYNTH;
 *  - selection is the Review step's entity selection: every table and column names the canonical
 *    construct it came from (`entity_key`), so the diagram, the manifest tree and the code viewer select
 *    the same thing ({@link erdSelection}).
 *
 * Everything here is pure (no React, no fetch) so it unit-tests directly.
 */

/** The column a foreign-key column points at (mirror of REST `RelationalReference`). */
export interface RelationalReference {
  table: string;
  column: string;
}

/** One column (mirror of REST `RelationalColumn`). */
export interface RelationalColumn {
  name: string;
  /** The SQL type in the export's dialect. */
  type: string;
  not_null: boolean;
  primary_key: boolean;
  unique: boolean;
  identity: boolean;
  /** True when the export made the column up. */
  synthesized: boolean;
  /** The canonical construct the column came from. */
  entity_key: string | null;
  references: RelationalReference | null;
}

/** One foreign key (mirror of REST `RelationalForeignKey`). */
export interface RelationalForeignKey {
  columns: string[];
  table: string;
  ref_columns: string[];
  synthesized: boolean;
}

/** One table (mirror of REST `RelationalTable`). */
export interface RelationalTable {
  name: string;
  kind: 'table' | 'junction' | 'child';
  /** The record, or the list field a junction / child table holds. */
  entity_key: string;
  synthesized: boolean;
  columns: RelationalColumn[];
  primary_key: string[];
  unique: string[][];
  foreign_keys: RelationalForeignKey[];
}

/** The relational projection of one database export (mirror of REST `RelationalSchema`). */
export interface RelationalSchema {
  dialect: string;
  /** `ddl`, `dbml`, `prisma`, `liquibase` or `flyway`. */
  output: string;
  schema_name: string | null;
  tables: RelationalTable[];
}

// ---------------------------------------------------------------------------
// Labels
// ---------------------------------------------------------------------------

/**
 * The name of the text view the ERD toggles with: what the export wrote.
 *
 * @param output The schema's `output`.
 * @returns e.g. `DDL`, `DBML`, `Prisma schema`, `Changelog`.
 */
export function erdTextLabel(output: string): string {
  switch (output) {
    case 'dbml':
      return 'DBML';
    case 'prisma':
      return 'Prisma schema';
    case 'liquibase':
    case 'flyway':
      return 'Changelog';
    default:
      return 'DDL';
  }
}

/** The badge a made-up table carries beside its name. */
export function tableKindLabel(kind: RelationalTable['kind']): string | null {
  if (kind === 'junction') return 'junction';
  if (kind === 'child') return 'child table';
  return null;
}

/** The short key markers of a column, in reading order: `PK`, `FK`, `UQ`. */
export function columnKeyMarkers(column: RelationalColumn): string[] {
  const markers: string[] = [];
  if (column.primary_key) markers.push('PK');
  if (column.references) markers.push('FK');
  if (column.unique && !column.primary_key) markers.push('UQ');
  return markers;
}

/**
 * The accessible name of a column: everything its row shows, in words.
 *
 * @param table The table name.
 * @param column The column.
 * @returns e.g. `order.ship_to_id: BIGINT, foreign key to address.id, made up by the export`.
 */
export function columnAriaLabel(table: string, column: RelationalColumn): string {
  const parts = [`${table}.${column.name}: ${column.type}`];
  if (column.primary_key) parts.push('primary key');
  if (column.references) parts.push(`foreign key to ${column.references.table}.${column.references.column}`);
  if (column.unique && !column.primary_key) parts.push('unique');
  if (column.not_null) parts.push('not null');
  if (column.identity) parts.push('generated');
  if (column.synthesized) parts.push('made up by the export');
  return parts.join(', ');
}

/**
 * The accessible name of a table.
 *
 * @param table The table.
 * @returns e.g. `Table order_lines, a junction table made up by the export, 3 columns`.
 */
export function tableAriaLabel(table: RelationalTable): string {
  const kind = tableKindLabel(table.kind);
  const what = kind ? `a ${kind === 'junction' ? 'junction table' : kind} made up by the export` : null;
  const count = `${table.columns.length} column${table.columns.length === 1 ? '' : 's'}`;
  return [`Table ${table.name}`, what, count].filter(Boolean).join(', ');
}

// ---------------------------------------------------------------------------
// Counts
// ---------------------------------------------------------------------------

/** What the diagram holds, for its summary line. */
export interface ErdCounts {
  tables: number;
  foreignKeys: number;
  /** Tables the export made up (junction + child). */
  madeUpTables: number;
  /** Columns the export made up (keys, references, link columns). */
  madeUpColumns: number;
}

/**
 * Count what the diagram holds.
 *
 * @param schema The relational projection.
 * @returns The counts.
 */
export function erdCounts(schema: RelationalSchema): ErdCounts {
  let foreignKeys = 0;
  let madeUpTables = 0;
  let madeUpColumns = 0;
  for (const table of schema.tables) {
    foreignKeys += table.foreign_keys.length;
    if (table.synthesized) madeUpTables += 1;
    madeUpColumns += table.columns.filter((column) => column.synthesized).length;
  }
  return { tables: schema.tables.length, foreignKeys, madeUpTables, madeUpColumns };
}

// ---------------------------------------------------------------------------
// Selection
// ---------------------------------------------------------------------------

/** What the shared selection highlights in the diagram. */
export interface ErdSelection {
  /** Tables whose own construct is selected. */
  tables: Set<string>;
  /** `table.column` of every column whose construct is selected. */
  columns: Set<string>;
}

/**
 * The tables and columns a selected canonical construct highlights: the table a record became (or the
 * junction / child table a list field became) and every column that came from it.
 *
 * @param schema The relational projection.
 * @param entityKey The selected construct, or null.
 * @returns The highlighted tables and columns (empty sets with nothing selected).
 */
export function erdSelection(schema: RelationalSchema, entityKey: string | null): ErdSelection {
  const tables = new Set<string>();
  const columns = new Set<string>();
  if (!entityKey) return { tables, columns };
  for (const table of schema.tables) {
    if (table.entity_key === entityKey) tables.add(table.name);
    for (const column of table.columns) {
      if (column.entity_key === entityKey) columns.add(`${table.name}.${column.name}`);
    }
  }
  return { tables, columns };
}

/**
 * The first table holding a selected construct — the one the diagram brings into view.
 *
 * @param schema The relational projection.
 * @param entityKey The selected construct, or null.
 * @returns The table name, or null.
 */
export function erdFocusTable(schema: RelationalSchema, entityKey: string | null): string | null {
  if (!entityKey) return null;
  const selection = erdSelection(schema, entityKey);
  const own = schema.tables.find((table) => selection.tables.has(table.name));
  if (own) return own.name;
  const holding = schema.tables.find((table) =>
    table.columns.some((column) => selection.columns.has(`${table.name}.${column.name}`)),
  );
  return holding?.name ?? null;
}

// ---------------------------------------------------------------------------
// Layout
// ---------------------------------------------------------------------------

/** Geometry of the diagram. */
export const ERD_GEOMETRY = {
  /** Width of one table node. */
  tableWidth: 320,
  /** Horizontal gap between columns of tables (the edge corridor). */
  columnGap: 180,
  /** Height of a table's header row. */
  headerHeight: 34,
  /** Height of one column row. */
  rowHeight: 24,
  /** Vertical gap between stacked tables. */
  tableGap: 28,
} as const;

/** One placed table. */
export interface PlacedTable {
  table: RelationalTable;
  /** Column index (0 = references nothing). */
  level: number;
  x: number;
  y: number;
  height: number;
}

/**
 * The table's column index: 0 when it references no other table, else one more than the furthest table
 * it references. Self-references and cycles are cut (a table on the current path counts as level 0).
 *
 * @param schema The relational projection.
 * @returns Table name → level.
 */
export function erdLevels(schema: RelationalSchema): Map<string, number> {
  const byName = new Map(schema.tables.map((table) => [table.name, table] as const));
  const levels = new Map<string, number>();
  const visiting = new Set<string>();
  const levelOf = (name: string): number => {
    const known = levels.get(name);
    if (known !== undefined) return known;
    const table = byName.get(name);
    if (!table || visiting.has(name)) return 0;
    visiting.add(name);
    let level = 0;
    for (const fk of table.foreign_keys) {
      if (fk.table === name || !byName.has(fk.table)) continue;
      level = Math.max(level, levelOf(fk.table) + 1);
    }
    visiting.delete(name);
    levels.set(name, level);
    return level;
  };
  for (const table of schema.tables) levelOf(table.name);
  return levels;
}

/** The height of one table node. */
export function tableHeight(table: RelationalTable): number {
  return ERD_GEOMETRY.headerHeight + Math.max(1, table.columns.length) * ERD_GEOMETRY.rowHeight + 8;
}

/**
 * Lay the tables out: columns by {@link erdLevels}, tables stacked within a column in written order.
 * Deterministic — the same schema always yields the same picture.
 *
 * @param schema The relational projection.
 * @returns The placed tables, in written order.
 */
export function erdLayout(schema: RelationalSchema): PlacedTable[] {
  const levels = erdLevels(schema);
  const nextY = new Map<number, number>();
  return schema.tables.map((table) => {
    const level = levels.get(table.name) ?? 0;
    const y = nextY.get(level) ?? 0;
    const height = tableHeight(table);
    nextY.set(level, y + height + ERD_GEOMETRY.tableGap);
    return {
      table,
      level,
      x: level * (ERD_GEOMETRY.tableWidth + ERD_GEOMETRY.columnGap),
      y,
      height,
    };
  });
}

/** One edge of the diagram: a foreign key. */
export interface ErdEdge {
  /** Stable id: `fk:<table>:<columns>`. */
  id: string;
  /** The referencing table. */
  source: string;
  /** The referenced table. */
  target: string;
  /** `columns → table.ref_columns`, the edge's label. */
  label: string;
  synthesized: boolean;
}

/**
 * The foreign keys as edges. A key pointing at a table the projection does not hold is left out (it has
 * nothing to point at in the drawing).
 *
 * @param schema The relational projection.
 * @returns One edge per drawable foreign key.
 */
export function erdEdges(schema: RelationalSchema): ErdEdge[] {
  const names = new Set(schema.tables.map((table) => table.name));
  const edges: ErdEdge[] = [];
  for (const table of schema.tables) {
    for (const fk of table.foreign_keys) {
      if (!names.has(fk.table)) continue;
      edges.push({
        id: `fk:${table.name}:${fk.columns.join(',')}`,
        source: table.name,
        target: fk.table,
        label: `${fk.columns.join(', ')} → ${fk.table}.${fk.ref_columns.join(', ')}`,
        synthesized: fk.synthesized,
      });
    }
  }
  return edges;
}
