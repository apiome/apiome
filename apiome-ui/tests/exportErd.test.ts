/**
 * exportErd — the ERD model of a database export (MFX-45.3, #4376).
 *
 * Pinned on a real projection captured from apiome-rest (`fixtures/exportErdShop.json`: an order with a
 * nested address, a list of lines and a list of tags, exported to PostgreSQL with `nested=tables`):
 *
 *  1. Layout: a table that references nothing sits left; every other table one column right of the
 *     furthest table it references; deterministic, cycle-safe.
 *  2. Edges: one per foreign key, referencing → referenced, made-up ones marked.
 *  3. Selection: a construct highlights the table it became and every column it became.
 *  4. Labels: what each row shows, in words.
 */

import * as fs from 'fs';
import * as path from 'path';
import {
  columnAriaLabel,
  columnKeyMarkers,
  erdCounts,
  erdEdges,
  erdFocusTable,
  erdLayout,
  erdLevels,
  erdSelection,
  erdTextLabel,
  ERD_GEOMETRY,
  tableAriaLabel,
  tableHeight,
  tableKindLabel,
  type RelationalSchema,
  type RelationalTable,
} from '../src/app/components/ade/dashboard/export/exportErd';

const SHOP = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'exportErdShop.json'), 'utf-8')) as {
  manifest: { relational: RelationalSchema };
};
const SCHEMA = SHOP.manifest.relational;
const table = (name: string) => SCHEMA.tables.find((t) => t.name === name)!;

function bare(name: string, fks: string[] = []): RelationalTable {
  return {
    name,
    kind: 'table',
    entity_key: name,
    synthesized: false,
    columns: [],
    primary_key: [],
    unique: [],
    foreign_keys: fks.map((target) => ({ columns: [`${target}_id`], table: target, ref_columns: ['id'], synthesized: false })),
  };
}

const schemaOf = (tables: RelationalTable[]): RelationalSchema => ({ dialect: 'postgres', output: 'ddl', schema_name: null, tables });

// ---------------------------------------------------------------------------
// The fixture is what the emitter really writes
// ---------------------------------------------------------------------------

describe('the captured projection', () => {
  it('holds the record tables and the made-up junction and child tables', () => {
    expect(SCHEMA.tables.map((t) => [t.name, t.kind, t.synthesized])).toEqual([
      ['order_lines', 'junction', true],
      ['order_tags', 'child', true],
      ['order', 'table', false],
      ['order_line', 'table', false],
      ['address', 'table', false],
    ]);
  });
});

// ---------------------------------------------------------------------------
// 1. Layout
// ---------------------------------------------------------------------------

describe('erdLevels / erdLayout', () => {
  it('puts tables that reference nothing left and each other table right of what it references', () => {
    const levels = erdLevels(SCHEMA);
    expect(levels.get('address')).toBe(0);
    expect(levels.get('order_line')).toBe(0);
    expect(levels.get('order')).toBe(1); // → address
    expect(levels.get('order_lines')).toBe(2); // → order, order_line
    expect(levels.get('order_tags')).toBe(2); // → order
  });

  it('survives self-references, cycles and references to tables it does not hold', () => {
    const levels = erdLevels(schemaOf([bare('a', ['b']), bare('b', ['a']), bare('c', ['c', 'missing'])]));
    expect([...levels.keys()].sort()).toEqual(['a', 'b', 'c']);
    expect(levels.get('c')).toBe(0);
    // The cycle is cut where the walk re-enters it: finite levels, never beyond the table count.
    expect(levels.get('a')).not.toBe(levels.get('b'));
    expect(Math.max(levels.get('a')!, levels.get('b')!)).toBeLessThanOrEqual(2);
  });

  it('stacks tables in a column in written order, without overlap, deterministically', () => {
    const placed = erdLayout(SCHEMA);
    expect(placed.map((p) => p.table.name)).toEqual(SCHEMA.tables.map((t) => t.name));
    const byLevel = new Map<number, typeof placed>();
    for (const p of placed) byLevel.set(p.level, [...(byLevel.get(p.level) ?? []), p]);
    for (const column of byLevel.values()) {
      for (let i = 1; i < column.length; i += 1) {
        expect(column[i].y).toBeGreaterThanOrEqual(column[i - 1].y + column[i - 1].height);
      }
    }
    for (const p of placed) expect(p.x).toBe(p.level * (ERD_GEOMETRY.tableWidth + ERD_GEOMETRY.columnGap));
    expect(erdLayout(SCHEMA)).toEqual(placed);
  });

  it('sizes a table by its columns', () => {
    expect(tableHeight(table('order'))).toBe(
      ERD_GEOMETRY.headerHeight + table('order').columns.length * ERD_GEOMETRY.rowHeight + 8,
    );
    expect(tableHeight(bare('empty'))).toBe(ERD_GEOMETRY.headerHeight + ERD_GEOMETRY.rowHeight + 8);
  });
});

// ---------------------------------------------------------------------------
// 2. Edges and counts
// ---------------------------------------------------------------------------

describe('erdEdges / erdCounts', () => {
  it('draws one edge per foreign key, referencing → referenced, marking the made-up ones', () => {
    const edges = erdEdges(SCHEMA);
    const pairs = edges.map((e) => `${e.source}→${e.target}`).sort();
    expect(pairs).toEqual(['order_lines→order', 'order_lines→order_line', 'order_tags→order', 'order→address']);
    expect(edges.every((e) => e.synthesized)).toBe(true);
    const shipTo = edges.find((e) => e.source === 'order')!;
    expect(shipTo.label).toBe('ship_to_id → address.id');
    expect(new Set(edges.map((e) => e.id)).size).toBe(edges.length);
  });

  it('leaves out a key pointing at a table the projection does not hold', () => {
    expect(erdEdges(schemaOf([bare('a', ['missing'])]))).toEqual([]);
  });

  it('counts tables, keys and what the export made up', () => {
    const counts = erdCounts(SCHEMA);
    expect(counts.tables).toBe(5);
    expect(counts.foreignKeys).toBe(4);
    expect(counts.madeUpTables).toBe(2);
    expect(counts.madeUpColumns).toBe(
      SCHEMA.tables.flatMap((t) => t.columns).filter((c) => c.synthesized).length,
    );
    expect(counts.madeUpColumns).toBeGreaterThan(0);
  });
});

// ---------------------------------------------------------------------------
// 3. Selection
// ---------------------------------------------------------------------------

describe('erdSelection / erdFocusTable', () => {
  it('a record highlights its table and its generated key', () => {
    const selection = erdSelection(SCHEMA, 'Order');
    expect([...selection.tables]).toEqual(['order']);
    expect([...selection.columns]).toEqual(['order.id']);
    expect(erdFocusTable(SCHEMA, 'Order')).toBe('order');
  });

  it('a list field highlights the junction table it became', () => {
    const selection = erdSelection(SCHEMA, 'Order.lines');
    expect([...selection.tables]).toEqual(['order_lines']);
    expect(selection.columns.size).toBe(table('order_lines').columns.length);
    expect(erdFocusTable(SCHEMA, 'Order.lines')).toBe('order_lines');
  });

  it('a field highlights its column, and the diagram focuses the table holding it', () => {
    const selection = erdSelection(SCHEMA, 'Order.shipTo');
    expect(selection.tables.size).toBe(0);
    expect([...selection.columns]).toEqual(['order.ship_to_id']);
    expect(erdFocusTable(SCHEMA, 'Order.shipTo')).toBe('order');
  });

  it('highlights nothing with nothing selected, or a construct the diagram does not hold', () => {
    expect(erdSelection(SCHEMA, null).tables.size).toBe(0);
    expect(erdFocusTable(SCHEMA, null)).toBeNull();
    expect(erdFocusTable(SCHEMA, 'Nope')).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// 4. Labels
// ---------------------------------------------------------------------------

describe('labels', () => {
  it('names the text view after what the export wrote', () => {
    expect(erdTextLabel('ddl')).toBe('DDL');
    expect(erdTextLabel('dbml')).toBe('DBML');
    expect(erdTextLabel('prisma')).toBe('Prisma schema');
    expect(erdTextLabel('liquibase')).toBe('Changelog');
    expect(erdTextLabel('flyway')).toBe('Changelog');
  });

  it('badges made-up tables', () => {
    expect(tableKindLabel('junction')).toBe('junction');
    expect(tableKindLabel('child')).toBe('child table');
    expect(tableKindLabel('table')).toBeNull();
    expect(tableAriaLabel(table('order_lines'))).toBe(
      `Table order_lines, a junction table made up by the export, ${table('order_lines').columns.length} columns`,
    );
    expect(tableAriaLabel(table('order_tags'))).toMatch(/^Table order_tags, a child table made up by the export/);
    expect(tableAriaLabel(table('address'))).toBe(`Table address, ${table('address').columns.length} columns`);
  });

  it('marks keys and spells a column out in words', () => {
    const id = table('order').columns.find((c) => c.name === 'id')!;
    expect(columnKeyMarkers(id)).toEqual(['PK']);
    expect(columnAriaLabel('order', id)).toBe('order.id: BIGINT, primary key, not null, generated, made up by the export');
    const shipTo = table('order').columns.find((c) => c.name === 'ship_to_id')!;
    expect(columnKeyMarkers(shipTo)).toEqual(['FK']);
    expect(columnAriaLabel('order', shipTo)).toBe(
      'order.ship_to_id: BIGINT, foreign key to address.id, made up by the export',
    );
    const unique = { ...shipTo, references: null, synthesized: false, unique: true, not_null: true };
    expect(columnKeyMarkers(unique)).toEqual(['UQ']);
    expect(columnAriaLabel('order', unique)).toBe('order.ship_to_id: BIGINT, unique, not null');
  });
});
