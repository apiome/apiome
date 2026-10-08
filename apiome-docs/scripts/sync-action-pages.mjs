#!/usr/bin/env node
/**
 * Write the Reference → CI pages for the GitHub Actions from their READMEs (DOCS-1.11, #5628).
 *
 * Usage: node scripts/sync-action-pages.mjs [--check]
 *
 * Without `--check`, writes every page in `ACTION_PAGES` (scripts/lib/action-pages.mjs). With it,
 * writes nothing and exits 1 naming each page that differs from its README.
 */
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

import {ACTION_PAGES, ACTION_PAGES_DIR, renderActionPage} from './lib/action-pages.mjs';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const check = process.argv.includes('--check');
const stale = [];

for (const spec of ACTION_PAGES) {
  const expected = renderActionPage(spec, fs.readFileSync(path.join(repoRoot, spec.readme), 'utf8'));
  const file = path.join(repoRoot, ACTION_PAGES_DIR, spec.page);
  const current = fs.existsSync(file) ? fs.readFileSync(file, 'utf8') : null;
  if (current === expected) continue;
  if (check) stale.push(`${ACTION_PAGES_DIR}/${spec.page} is out of date with ${spec.readme}`);
  else fs.writeFileSync(file, expected);
}

if (stale.length > 0) {
  for (const line of stale) console.error(line);
  console.error('Run `yarn workspace apiome-docs sync:action-pages` to refresh them.');
  process.exit(1);
}
console.log(check ? 'Action pages are up to date.' : 'Action pages written.');
