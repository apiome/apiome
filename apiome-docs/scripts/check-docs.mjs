#!/usr/bin/env node
/**
 * `yarn docs:check` — page rules for the docs site (see scripts/lib/pages.mjs).
 *
 * Usage: node scripts/check-docs.mjs [docsDir]   (defaults to apiome-docs/docs)
 * Exits 1 and lists every problem when a rule fails.
 */
import path from 'node:path';
import {fileURLToPath} from 'node:url';

import {checkDocs} from './lib/pages.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const docsDir = path.resolve(process.argv[2] ?? path.join(here, '..', 'docs'));
const problems = checkDocs(docsDir);

if (problems.length > 0) {
  console.error(`docs:check found ${problems.length} problem(s) in ${docsDir}:`);
  for (const problem of problems) console.error(`  - ${problem}`);
  process.exit(1);
}
console.log(`docs:check: page rules pass (${docsDir}).`);
