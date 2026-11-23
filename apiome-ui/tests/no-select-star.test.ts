/**
 * The UI's direct SQL names its columns (DBP-1.13, #7196).
 *
 * `SELECT *`, `alias.*` and `RETURNING *` read whatever the table holds today — and tomorrow.
 * `apiome.users` carries a password hash, `apiome.api_keys` a key hash, and `apiome.versions` a
 * 1536-dimension embedding; each of them once travelled to a caller that never asked for it,
 * because the statement said `*`. Every projection under `lib/db` is now a column list, and this
 * guard keeps it that way by scanning the source text: no behavioural suite can notice a `*`
 * coming back, since the mocked pool returns whatever the test scripted.
 *
 * What is allowed:
 *
 * - `COUNT(*)` — it counts rows, it does not project them.
 * - `SELECT * FROM (` — the outer read of a subquery whose own `SELECT` names the columns.
 * - The few lines in {@link ALLOWED}, each with the reason it is safe.
 */

import { describe, expect, test } from '@jest/globals';
import fs from 'fs';
import path from 'path';

import { sourceFiles } from './helpers/source-files';

const ROOT = path.resolve(__dirname, '..');

/** The direct-SQL layer: everything under `lib/db`, and the one policy read outside it. */
const SQL_FILES = [
  ...sourceFiles(path.join(ROOT, 'lib', 'db'), /\.ts$/),
  path.join(ROOT, 'lib', 'auth', 'signup-policy-resolver.ts'),
];

/** What may not appear, by name. */
const FORBIDDEN: ReadonlyArray<{ name: string; pattern: RegExp }> = [
  // `SELECT *` and `SELECT DISTINCT *`, unless it reads a parenthesised subquery.
  { name: 'SELECT *', pattern: /\bSELECT\s+(?:DISTINCT\s+)?\*(?!\s+FROM\s*\()/i },
  { name: 'RETURNING *', pattern: /\bRETURNING\s+\*/i },
  // `alias.*` — an identifier, a dot, a star, and then not the `/` that would close a comment.
  { name: 'alias.*', pattern: /(?<![\w$'"`/.])[A-Za-z_][A-Za-z0-9_]*\.\*(?![/\w])/ },
];

/**
 * Lines the patterns match that are not a `*` projection of a table.
 *
 * Keyed by the file's path under the package, then the line's trimmed text. Add an entry only
 * for a read whose inner query already names its columns, and say which.
 */
const ALLOWED: Readonly<Record<string, readonly string[]>> = {
  // (none: every CTE read under lib/db names its columns too)
};

/**
 * Whether a line is commentary rather than code or SQL: a JSDoc/block-comment line, a `//`
 * line, or a SQL `--` line.
 *
 * @param line One source line.
 * @returns `true` for a comment line.
 */
function isComment(line: string): boolean {
  const text = line.trim();
  return (
    text.startsWith('*') || text.startsWith('/*') || text.startsWith('//') || text.startsWith('--')
  );
}

/**
 * Every forbidden projection in one file.
 *
 * @param file Absolute path.
 * @returns `path:line  [what]  text` for each hit.
 */
function violations(file: string): string[] {
  const relative = path.relative(ROOT, file).split(path.sep).join('/');
  const allowed = ALLOWED[relative] ?? [];
  const found: string[] = [];
  fs.readFileSync(file, 'utf8')
    .split('\n')
    .forEach((line, index) => {
      if (isComment(line) || allowed.includes(line.trim())) return;
      for (const { name, pattern } of FORBIDDEN) {
        if (pattern.test(line)) found.push(`${relative}:${index + 1}  [${name}]  ${line.trim()}`);
      }
    });
  return found;
}

describe('the direct-SQL layer names its columns', () => {
  test('the scan sees the layer', () => {
    const names = SQL_FILES.map((file) => path.relative(ROOT, file).split(path.sep).join('/'));
    expect(names.length).toBeGreaterThan(40);
    expect(names).toEqual(
      expect.arrayContaining([
        'lib/db/helper.ts',
        'lib/db/admin-helper.ts',
        'lib/db/import-transaction.ts',
        'lib/auth/signup-policy-resolver.ts',
      ]),
    );
  });

  test('no statement selects or returns *', () => {
    expect(SQL_FILES.flatMap(violations)).toEqual([]);
  });

  test('the allowlist holds no entry that no longer matches a line', () => {
    const stale = Object.entries(ALLOWED).flatMap(([relative, lines]) => {
      const source = fs.readFileSync(path.join(ROOT, relative), 'utf8');
      const present = new Set(source.split('\n').map((line) => line.trim()));
      return lines.filter((line) => !present.has(line)).map((line) => `${relative}: ${line}`);
    });
    expect(stale).toEqual([]);
  });

  test.each([
    ['SELECT * FROM apiome.users WHERE id = $1', 'SELECT *'],
    ['`SELECT DISTINCT * FROM apiome.tenants`', 'SELECT *'],
    ['select  *  from apiome.api_keys', 'SELECT *'],
    ['VALUES ($1, $2) RETURNING *`,', 'RETURNING *'],
    ['`SELECT p.*, u.name as creator_name FROM apiome.projects p', 'alias.*'],
    ['SELECT DISTINCT a.*', 'alias.*'],
  ])('the patterns catch %j', (line, name) => {
    const hit = FORBIDDEN.filter(({ pattern }) => pattern.test(line)).map((entry) => entry.name);
    expect(hit).toContain(name);
  });

  test.each([
    'SELECT COUNT(*) FROM apiome.tenants t WHERE t.deleted_at IS NULL',
    '`SELECT count(*)::int AS total FROM (',
    '`SELECT * FROM (',
    'SELECT id, name FROM nested_props',
    "import * as admin from './admin-helper';",
    "const files = glob('lib/**/*.ts');",
    'const total = a.count * b.count;',
  ])('the patterns leave %j alone', (line) => {
    expect(FORBIDDEN.filter(({ pattern }) => pattern.test(line))).toEqual([]);
  });
});
