/**
 * Foreign-key index coverage (DBP-1.12, #7195).
 *
 * Every DELETE of a referenced row (and every UPDATE of its key) runs PostgreSQL's referential
 * check against each referencing table:
 *
 *     SELECT 1 FROM ONLY <child> x WHERE <fk col> = $1 [AND ...] FOR KEY SHARE OF x
 *
 * as a cached generic plan. Without an index whose leading key columns are the foreign-key columns
 * that query is a sequential scan of the child table, once per deleted parent row. Measured on the
 * DBP-1.1 scale database, deleting one version spent 27 ms in `classes_version_id_fkey` alone
 * because the only index on `classes.version_id` was partial on `deleted_at IS NULL`.
 *
 * An index serves the check when it is
 *   - a valid b-tree,
 *   - led by exactly the foreign-key columns (in any order; extra trailing columns are fine), and
 *   - either not partial, or partial only on `<fk col> IS NOT NULL` for some of the foreign-key
 *     columns — the planner proves those from `<fk col> = $1`, so such an index (which costs no
 *     write for a row whose column is NULL) is the cheapest correct choice for a sparse column.
 *
 * Any other predicate (`deleted_at IS NULL`, a status filter) makes the index unusable for the
 * check, because the parameterised query says nothing about those columns.
 *
 * `listUncoveredForeignKeys` reads the live catalog; the schema test in
 * `test/foreign-key-index-coverage.test.ts` compares its result with the reviewed allowlist in
 * `foreign-key-index-allowlist.json`.
 */

import type pg from "pg";

/** One foreign key and the indexes on its table that start with its columns. */
export type ForeignKeyRow = {
  /** Referencing table, unqualified (`classes`). */
  table: string;
  /** Constraint name (`classes_version_id_fkey`). */
  constraint: string;
  /** Referencing columns in constraint order. */
  columns: string[];
  /** Referenced table, unqualified (`versions`). */
  referencedTable: string;
  /**
   * Indexes on `table` whose first `columns.length` key columns are exactly `columns` (any
   * order), with their predicate (`null` when not partial) and access method.
   */
  candidateIndexes: { name: string; predicate: string | null; method: string; valid: boolean }[];
};

/** A foreign key no index can serve, as `listUncoveredForeignKeys` returns it. */
export type UncoveredForeignKey = {
  /** `table.constraint` — the allowlist key. */
  key: string;
  table: string;
  constraint: string;
  columns: string[];
  referencedTable: string;
  /**
   * `none` when no index starts with the columns; `partial` when only unusable ones do (partial on
   * another predicate — the usual case — invalid, or not a b-tree).
   */
  status: "none" | "partial";
};

/**
 * Catalog query: every foreign key in `schema` with the indexes on its table led by its columns.
 * `$1` is the schema name.
 */
export const FOREIGN_KEY_INDEX_SQL = `
SELECT t.relname AS table_name,
       c.conname AS constraint_name,
       rt.relname AS referenced_table,
       ARRAY(SELECT a.attname::text
               FROM unnest(c.conkey) WITH ORDINALITY k(attnum, ord)
               JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
              ORDER BY k.ord) AS columns,
       COALESCE((
         SELECT json_agg(json_build_object(
                  'name', ic.relname,
                  'predicate', pg_get_expr(i.indpred, i.indrelid),
                  'method', am.amname,
                  'valid', i.indisvalid)
                ORDER BY ic.relname)
           FROM pg_index i
           JOIN pg_class ic ON ic.oid = i.indexrelid
           JOIN pg_am am ON am.oid = ic.relam
          WHERE i.indrelid = c.conrelid
            AND i.indnkeyatts >= cardinality(c.conkey)
            AND (SELECT array_agg(x ORDER BY x)
                   FROM unnest((i.indkey::int2[])[0:cardinality(c.conkey) - 1]) x)
                = (SELECT array_agg(x ORDER BY x) FROM unnest(c.conkey) x)
       ), '[]'::json) AS candidate_indexes
  FROM pg_constraint c
  JOIN pg_class t ON t.oid = c.conrelid
  JOIN pg_class rt ON rt.oid = c.confrelid
 WHERE c.contype = 'f'
   AND c.connamespace = $1::regnamespace
 ORDER BY t.relname, c.conname
`;

/**
 * Whether a partial-index predicate still lets the planner use the index for the referential
 * check: it must be a conjunction of `<col> IS NOT NULL` terms over the foreign-key columns.
 *
 * @param predicate - `pg_get_expr(indpred, indrelid)` output, e.g. `(release_id IS NOT NULL)` or
 *   `((a IS NOT NULL) AND (b IS NOT NULL))`; `null` for a non-partial index.
 * @param columns - The foreign-key columns.
 * @returns `true` when the index can serve `col = $1` lookups for every row that can reference.
 */
export function predicateServesForeignKey(predicate: string | null, columns: string[]): boolean {
  if (predicate === null) return true;
  const terms = stripParens(predicate).split(/\s+AND\s+/i);
  return terms.every((term) => {
    const match = /^"?([A-Za-z_][A-Za-z0-9_$]*)"? IS NOT NULL$/i.exec(stripParens(term));
    return match !== null && columns.includes(match[1] ?? "");
  });
}

/** Remove balanced outer parentheses and surrounding space from an expression. */
function stripParens(expression: string): string {
  let text = expression.trim();
  while (text.startsWith("(") && text.endsWith(")") && outerParensMatch(text)) {
    text = text.slice(1, -1).trim();
  }
  return text;
}

/** True when the first `(` of `text` closes at its last character. */
function outerParensMatch(text: string): boolean {
  let depth = 0;
  for (let i = 0; i < text.length; i += 1) {
    if (text[i] === "(") depth += 1;
    else if (text[i] === ")") {
      depth -= 1;
      if (depth === 0 && i < text.length - 1) return false;
    }
  }
  return depth === 0;
}

/**
 * Classify catalog rows: the foreign keys no valid b-tree index can serve.
 *
 * @param rows - Output of {@link FOREIGN_KEY_INDEX_SQL}, mapped to {@link ForeignKeyRow}.
 * @returns The uncovered foreign keys, sorted by key.
 */
export function uncoveredForeignKeys(rows: ForeignKeyRow[]): UncoveredForeignKey[] {
  const uncovered: UncoveredForeignKey[] = [];
  for (const row of rows) {
    const btrees = row.candidateIndexes.filter((index) => index.method === "btree" && index.valid);
    if (btrees.some((index) => predicateServesForeignKey(index.predicate, row.columns))) continue;
    uncovered.push({
      key: `${row.table}.${row.constraint}`,
      table: row.table,
      constraint: row.constraint,
      columns: row.columns,
      referencedTable: row.referencedTable,
      status: row.candidateIndexes.length > 0 ? "partial" : "none",
    });
  }
  return uncovered.sort((a, b) => a.key.localeCompare(b.key));
}

/**
 * Read the catalog and return every foreign key in `schema` without a usable index.
 *
 * @param client - A connected client on a migrated database.
 * @param schema - Schema to inspect (default `apiome`).
 * @returns The uncovered foreign keys, sorted by `table.constraint`.
 */
export async function listUncoveredForeignKeys(
  client: pg.Client,
  schema = "apiome",
): Promise<UncoveredForeignKey[]> {
  const result = await client.query<{
    table_name: string;
    constraint_name: string;
    referenced_table: string;
    columns: string[];
    candidate_indexes: ForeignKeyRow["candidateIndexes"];
  }>(FOREIGN_KEY_INDEX_SQL, [schema]);
  return uncoveredForeignKeys(
    result.rows.map((row) => ({
      table: row.table_name,
      constraint: row.constraint_name,
      columns: row.columns,
      referencedTable: row.referenced_table,
      candidateIndexes: row.candidate_indexes,
    })),
  );
}
