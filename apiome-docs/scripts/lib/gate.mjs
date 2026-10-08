/**
 * Every `yarn docs:check` rule over one site, in one call (DOCS-1.13, #5630).
 *
 * `scripts/check-docs.mjs` runs it over `apiome-docs/`; the tests run it over the fixture sites in
 * `test/fixtures/gate/`, one per failure the gate must catch. The production build that follows in
 * `docs:check` adds what only a build can see — heading anchors and MDX that does not compile.
 */
import fs from 'node:fs';
import path from 'node:path';

import {checkInternalLinks, checkOrphans} from './links.mjs';
import {checkDocs, listPages} from './pages.mjs';
import {checkRestReference} from './rest-reference.mjs';
import {checkScreenshots, loadManifest} from './screens.mjs';
import {checkStaleScreenshots, gitLastChange, loadReleases} from './staleness.mjs';

/**
 * Run the gate.
 *
 * @param {object} options - Inputs.
 * @param {string} options.siteDir - Absolute path of the site (holds `docs/`, `screens.json`,
 *   `static/`, `sidebars.ts`, `release-notes/`).
 * @param {string} [options.docsDir] - Absolute path of the docs directory; defaults to `<siteDir>/docs`.
 * @param {string} [options.repoRoot] - Absolute path of the repository root; defaults to the
 *   site's parent. Source paths and the REST document are resolved against it.
 * @param {import('./staleness.mjs').LastChange} [options.lastChange] - Commit-date lookup; git by default.
 * @returns {string[]} Every problem found; empty when the site passes.
 */
export function runGate({siteDir, docsDir = path.join(siteDir, 'docs'), repoRoot = path.dirname(siteDir), lastChange}) {
  const problems = [...checkDocs(docsDir)];

  const sidebarsFile = path.join(siteDir, 'sidebars.ts');
  if (fs.existsSync(sidebarsFile)) {
    problems.push(...checkOrphans({docsDir, sidebarsSource: fs.readFileSync(sidebarsFile, 'utf8')}));
  }
  problems.push(...checkInternalLinks({siteDir, docsDir}));

  const manifest = loadManifest(path.join(siteDir, 'screens.json'));
  problems.push(...manifest.problems.map((problem) => `screens.json: ${problem}`));

  const pageDirs = [docsDir, path.join(siteDir, 'release-notes')].filter((dir) => fs.existsSync(dir));
  const pages = pageDirs.flatMap((dir) =>
    listPages(dir).map((page) => ({
      page: path.relative(siteDir, page),
      source: fs.readFileSync(page, 'utf8'),
    })),
  );
  problems.push(...checkScreenshots({screens: manifest.screens, pages, staticDir: path.join(siteDir, 'static')}));

  problems.push(
    ...checkStaleScreenshots({
      screens: manifest.screens,
      releases: loadReleases(path.join(siteDir, 'release-notes', 'releases.json')),
      lastChange: lastChange ?? gitLastChange(repoRoot),
      repoRoot,
      screensPrefix: path.posix.join(path.relative(repoRoot, siteDir).split(path.sep).join('/'), 'static'),
    }),
  );

  problems.push(...checkRestReference({docsDir, openapiFile: path.join(repoRoot, 'apiome-rest', 'openapi.yaml')}));
  return problems;
}
