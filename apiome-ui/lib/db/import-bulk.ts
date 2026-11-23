/**
 * Set-based inserts for the import pipeline (DBP-1.9, #7192).
 *
 * An import used to send one `INSERT` per row: a 1,000-operation specification was 10,000–20,000
 * round trips. {@link bulkInsert} sends a table's rows as one JSON array and lets PostgreSQL
 * expand it, so a table costs one statement per {@link BULK_CHUNK_ROWS} rows whatever the
 * specification's size. Callers assign every row's `id` themselves (`crypto.randomUUID()`), so
 * child rows can name their parents without reading anything back.
 */

/** Anything that runs SQL: the pool, or a client checked out of it. */
export type BulkQueryable = {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- pg rows are untyped
  query: (text: string, params?: any[]) => Promise<{ rows: any[]; rowCount?: number | null }>;
};

/** Rows sent per statement. A row is a few hundred bytes to a few kilobytes of JSON. */
export const BULK_CHUNK_ROWS = 5000;

/** A plain SQL identifier: what a table or column name passed to {@link bulkInsert} must be. */
const IDENTIFIER = /^[a-z_][a-z0-9_]*$/;

/** Options for {@link bulkInsert}. */
export interface BulkInsertOptions {
  /** An `ON CONFLICT …` clause, e.g. `ON CONFLICT (version_id, scheme_name) DO NOTHING`. */
  conflict?: string;
  /** A `RETURNING` column list, e.g. `id`; the returned rows of every chunk are concatenated. */
  returning?: string;
  /** Rows per statement; defaults to {@link BULK_CHUNK_ROWS}. */
  chunkRows?: number;
}

/**
 * The statement {@link bulkInsert} runs for a table.
 *
 * `jsonb_populate_recordset(NULL::apiome.<table>, $1)` reads each JSON object as a row of the
 * table's own type, so every value is converted by the column's type (uuid, jsonb, enum, boolean)
 * and no column type is repeated here. Only the named columns are inserted; the others keep
 * their defaults. A key missing from a row, or `null`, is SQL `NULL`.
 *
 * @param table Table name in the `apiome` schema.
 * @param columns Columns to insert, in order.
 * @param options Conflict and returning clauses.
 * @returns The SQL text, taking the JSON array as `$1`.
 * @throws Error when a table or column name is not a plain identifier.
 */
export function bulkInsertSql(
  table: string,
  columns: readonly string[],
  options: Pick<BulkInsertOptions, 'conflict' | 'returning'> = {},
): string {
  for (const name of [table, ...columns]) {
    if (!IDENTIFIER.test(name)) throw new Error(`bulkInsert: "${name}" is not a plain identifier`);
  }
  if (columns.length === 0) throw new Error('bulkInsert: no columns');
  const list = columns.join(', ');
  return (
    `INSERT INTO apiome.${table} (${list}) ` +
    `SELECT ${list} FROM jsonb_populate_recordset(NULL::apiome.${table}, $1::jsonb)` +
    (options.conflict ? ` ${options.conflict}` : '') +
    (options.returning ? ` RETURNING ${options.returning}` : '')
  );
}

/**
 * Insert rows into one table in as few statements as possible.
 *
 * @param client Where to run (inside the caller's transaction, when it has one).
 * @param table Table name in the `apiome` schema.
 * @param columns Columns to insert; each row is an object keyed by these names.
 * @param rows The rows. JSON columns take plain objects (do not pre-stringify them).
 * @param options Conflict and returning clauses, and the chunk size.
 * @returns How many rows were inserted, and the `RETURNING` rows when asked for.
 */
export async function bulkInsert(
  client: BulkQueryable,
  table: string,
  columns: readonly string[],
  rows: readonly Record<string, unknown>[],
  options: BulkInsertOptions = {},
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- pg rows are untyped
): Promise<{ rowCount: number; rows: any[] }> {
  if (rows.length === 0) return { rowCount: 0, rows: [] };
  const sql = bulkInsertSql(table, columns, options);
  const size = Math.max(1, options.chunkRows ?? BULK_CHUNK_ROWS);
  let rowCount = 0;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- pg rows are untyped
  const returned: any[] = [];
  for (let start = 0; start < rows.length; start += size) {
    const chunk = rows.slice(start, start + size);
    const result = await client.query(sql, [JSON.stringify(chunk)]);
    rowCount += result.rowCount ?? chunk.length;
    if (options.returning && result.rows?.length) returned.push(...result.rows);
  }
  return { rowCount, rows: returned };
}
