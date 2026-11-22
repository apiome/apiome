/**
 * The UI does not generate revision documents (COA-5.13, #7089).
 *
 * apiome-rest is the single OpenAPI generator. The Next.js server used to have its own
 * (`buildOpenApiSpecForVersion` in `lib/db/helper.ts`, which queried Postgres for classes and
 * properties and rendered a Handlebars template), and the two disagreed about the same revision.
 * It was removed after a parity audit; every screen now reads the document REST keeps in the
 * document store (`src/app/utils/revision-document.ts`, `lib/revision-document-server.ts`).
 *
 * This guard keeps the generator from coming back: none of its names may appear anywhere under
 * `src/` or `lib/` — not as code, and not in a comment that would send a reader looking for it.
 */

import { describe, expect, test } from '@jest/globals';
import fs from 'fs';
import path from 'path';

const ROOT = path.resolve(__dirname, '..');
const SOURCE_ROOTS = ['src', 'lib'];
const SOURCE_FILE = /\.(ts|tsx|js|jsx|mjs|cjs|hbs)$/;

/** Names of the removed generator. Each must stay out of `src/` and `lib/`. */
const REMOVED = [
  'buildOpenApiSpecForVersion',
  'buildOpenApiSpecJsonForVersion',
  'generateOpenApiSpec',
  'generateClassOpenApiSpec',
];

/** Files that had no other purpose and were deleted with it. */
const DELETED_PATHS = ['src/app/utils/openapi-versions.ts', 'src/app/utils/templates/openapi'];

function* sourceFiles(directory: string): Generator<string> {
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    if (entry.name === 'node_modules' || entry.name.startsWith('.')) continue;
    const full = path.join(directory, entry.name);
    if (entry.isDirectory()) yield* sourceFiles(full);
    else if (SOURCE_FILE.test(entry.name)) yield full;
  }
}

describe('the UI has no OpenAPI generator of its own', () => {
  const files = SOURCE_ROOTS.flatMap((root) => [...sourceFiles(path.join(ROOT, root))]);

  test('the scan sees the source tree', () => {
    expect(files.length).toBeGreaterThan(500);
    expect(files).toContain(path.join(ROOT, 'lib', 'db', 'helper.ts'));
  });

  test.each(REMOVED)('%s appears nowhere under src/ or lib/', (name) => {
    const hits = files
      .filter((file) => fs.readFileSync(file, 'utf8').includes(name))
      .map((file) => path.relative(ROOT, file));
    expect(hits).toEqual([]);
  });

  test.each(DELETED_PATHS)('%s stays deleted', (relative) => {
    expect(fs.existsSync(path.join(ROOT, relative))).toBe(false);
  });

  test('the call sites read the document from apiome-rest', () => {
    const read = (relative: string) => fs.readFileSync(path.join(ROOT, relative), 'utf8');
    expect(read('src/app/ade/dashboard/versions/page.tsx')).toContain('loadRevisionDocument(');
    expect(read('src/app/utils/catalog-revision-diff.ts')).toContain('loadRevisionDocument(');
    expect(read('src/app/api/merge-requests/[mergeRequestId]/spec/route.ts')).toContain(
      'fetchRevisionDocument(',
    );
    expect(read('src/app/api/reviews/[reviewId]/spec/route.ts')).toContain(
      'fetchRevisionDocument(',
    );
  });

  test('the spec routes no longer import the database helper', () => {
    for (const route of [
      'src/app/api/merge-requests/[mergeRequestId]/spec/route.ts',
      'src/app/api/reviews/[reviewId]/spec/route.ts',
      'src/app/api/versions/[versionId]/document/route.ts',
    ]) {
      expect(fs.readFileSync(path.join(ROOT, route), 'utf8')).not.toContain('@lib/db/helper');
    }
  });
});
