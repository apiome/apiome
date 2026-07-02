export type Column = { key: string; label: string };

export type OutputMode = { json: boolean };

function cell(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (value instanceof Date) return value.toISOString();
  return String(value);
}

function renderTable(rows: Record<string, unknown>[], columns: Column[]): string {
  if (rows.length === 0) return "(no rows)";
  const widths = columns.map((c) =>
    Math.max(c.label.length, ...rows.map((r) => cell(r[c.key]).length)),
  );
  const line = (cells: string[]): string =>
    cells.map((value, i) => value.padEnd(widths[i] ?? 0)).join("  ");
  const header = line(columns.map((c) => c.label));
  const sep = widths.map((w) => "-".repeat(w)).join("  ");
  const body = rows.map((r) => line(columns.map((c) => cell(r[c.key])))).join("\n");
  return [header, sep, body].join("\n");
}

/** Print a list of records as a table, or as JSON when `--json` is set. */
export function printRows(
  mode: OutputMode,
  rows: Record<string, unknown>[],
  columns: Column[],
): void {
  if (mode.json) {
    process.stdout.write(`${JSON.stringify(rows, null, 2)}\n`);
    return;
  }
  process.stdout.write(`${renderTable(rows, columns)}\n`);
}

/** Print a single record as key/value lines, or as JSON when `--json` is set. */
export function printRecord(mode: OutputMode, record: Record<string, unknown>): void {
  if (mode.json) {
    process.stdout.write(`${JSON.stringify(record, null, 2)}\n`);
    return;
  }
  const width = Math.max(0, ...Object.keys(record).map((k) => k.length));
  for (const [k, v] of Object.entries(record)) {
    process.stdout.write(`${k.padEnd(width)}  ${cell(v)}\n`);
  }
}

/** Status / advisory line — goes to stderr so it never pollutes `--json` stdout. */
export function note(message: string): void {
  process.stderr.write(`${message}\n`);
}
