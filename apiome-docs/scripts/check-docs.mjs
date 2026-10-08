#!/usr/bin/env node
/**
 * `yarn docs:check` — every rule in scripts/lib/gate.mjs: front matter and groups (pages.mjs),
 * orphan pages and internal links (links.mjs), the screenshot manifest and images (screens.mjs),
 * stale screenshots (staleness.mjs) and the generated REST reference (rest-reference.mjs).
 *
 * Usage: node scripts/check-docs.mjs [docsDir]   (defaults to apiome-docs/docs)
 *
 * The site's other inputs (`screens.json`, `static/`, `sidebars.ts`, `release-notes/`) are read
 * from the directory above `docsDir`, and the repository root is the one above that.
 * Exits 1 and lists every problem when a rule fails.
 */
import path from 'node:path';
import {fileURLToPath} from 'node:url';

import {runGate} from './lib/gate.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const docsDir = path.resolve(process.argv[2] ?? path.join(here, '..', 'docs'));
const siteDir = path.dirname(docsDir);

const problems = runGate({siteDir, docsDir});

if (problems.length > 0) {
  console.error(`docs:check found ${problems.length} problem(s) in ${siteDir}:`);
  for (const problem of problems) console.error(`  - ${problem}`);
  process.exit(1);
}
console.log(`docs:check: page, link and screenshot rules pass (${siteDir}).`);
