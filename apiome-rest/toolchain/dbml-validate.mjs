#!/usr/bin/env node
/**
 * DBML validation wrapper (MFX-35.2, #4312).
 *
 * Reads one DBML document from STDIN, parses it with `@dbml/core` — the `dbmlv2` parser, the one
 * dbdiagram.io and dbdocs use, which also reads `check` constraints — and writes one JSON object to
 * STDOUT:
 *
 *   {
 *     "ok":          boolean,                                   // parsed with no error
 *     "tables":      number,                                    // tables across every schema
 *     "diagnostics": [ { "message", "line", "column" } ]       // empty when ok
 *   }
 *
 * The process exits 0 on a handled outcome (valid OR invalid document): the verdict travels in the
 * JSON body, so the Python toolchain runner always gets parseable JSON. A non-zero exit means the
 * wrapper itself failed, with the reason on STDERR.
 *
 * Invoked by `app.db_schema_validation` through `app.toolchain_runner` under the `dbml-validator`
 * tool key; the sandbox gives it no network, and it needs none.
 */

import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { Parser } from '@dbml/core';

/** The installed `@dbml/core` version (its package.json is not in the package's `exports`). */
function dbmlVersion() {
  try {
    const here = dirname(fileURLToPath(import.meta.url));
    const manifest = join(here, 'node_modules', '@dbml', 'core', 'package.json');
    return JSON.parse(readFileSync(manifest, 'utf8')).version ?? 'unknown';
  } catch {
    return 'unknown';
  }
}

/** Read all of STDIN into one UTF-8 string. */
function readStdin() {
  return new Promise((resolve, reject) => {
    let data = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', (chunk) => {
      data += chunk;
    });
    process.stdin.on('end', () => resolve(data));
    process.stdin.on('error', reject);
  });
}

/** One parser diagnostic → `{ message, line, column }` (line and column are 1-based, or null). */
function mapDiagnostic(diagnostic) {
  const start = diagnostic?.location?.start ?? {};
  return {
    message: String(diagnostic?.message ?? diagnostic),
    line: Number.isInteger(start.line) ? start.line : null,
    column: Number.isInteger(start.column) ? start.column : null,
  };
}

async function main() {
  if (process.argv.slice(2).includes('--version')) {
    process.stdout.write(`dbml-validate (apiome) @dbml/core ${dbmlVersion()}\n`);
    return;
  }
  const source = await readStdin();
  let result;
  try {
    const database = Parser.parse(source, 'dbmlv2');
    const tables = (database.schemas ?? []).reduce((total, schema) => total + (schema.tables ?? []).length, 0);
    result = { ok: true, tables, diagnostics: [] };
  } catch (error) {
    const diagnostics = Array.isArray(error?.diags) ? error.diags.map(mapDiagnostic) : [mapDiagnostic(error)];
    result = { ok: false, tables: 0, diagnostics };
  }
  process.stdout.write(JSON.stringify(result));
}

main().catch((err) => {
  process.stderr.write(`dbml-validate wrapper failed: ${err && err.stack ? err.stack : err}\n`);
  process.exit(1);
});
