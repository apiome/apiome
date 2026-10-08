#!/usr/bin/env node
/**
 * `yarn docs:check` — page rules for the docs site (see scripts/lib/pages.mjs) and the
 * screenshot rules (see scripts/lib/screens.mjs).
 *
 * Usage: node scripts/check-docs.mjs [docsDir]   (defaults to apiome-docs/docs)
 *
 * The screenshot manifest (`screens.json`), the images (`static/img/screens/`) and the release
 * notes are read from the directory above `docsDir`; the generated REST reference is checked
 * against `apiome-rest/openapi.yaml` (see scripts/lib/rest-reference.mjs).
 * Exits 1 and lists every problem when a rule fails.
 */
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

import {checkDocs, listPages} from './lib/pages.mjs';
import {checkRestReference} from './lib/rest-reference.mjs';
import {checkScreenshots, loadManifest} from './lib/screens.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const docsDir = path.resolve(process.argv[2] ?? path.join(here, '..', 'docs'));
const siteDir = path.dirname(docsDir);

const problems = checkDocs(docsDir);

const manifest = loadManifest(path.join(siteDir, 'screens.json'));
problems.push(...manifest.problems.map((problem) => `screens.json: ${problem}`));

const pageDirs = [docsDir, path.join(siteDir, 'release-notes')].filter((dir) => fs.existsSync(dir));
const pages = pageDirs.flatMap((dir) =>
  listPages(dir).map((page) => ({
    page: path.relative(siteDir, page),
    source: fs.readFileSync(page, 'utf8'),
  })),
);
problems.push(
  ...checkScreenshots({screens: manifest.screens, pages, staticDir: path.join(siteDir, 'static')}),
);

problems.push(
  ...checkRestReference({docsDir, openapiFile: path.join(siteDir, '..', 'apiome-rest', 'openapi.yaml')}),
);

if (problems.length > 0) {
  console.error(`docs:check found ${problems.length} problem(s) in ${siteDir}:`);
  for (const problem of problems) console.error(`  - ${problem}`);
  process.exit(1);
}
console.log(`docs:check: page and screenshot rules pass (${siteDir}).`);
