/**
 * Stale screenshots — a `yarn docs:check` rule (DOCS-1.13, #5630).
 *
 * A screenshot is stale when it was captured before the last {@link STALE_AFTER_RELEASES} releases
 * **and** the code behind its route changed after it was captured: the screen has had time to move
 * on, and it did. Both dates come from `git log` — the image's last commit and the last commit
 * touching the entry's source paths — and the releases from `release-notes/releases.json`
 * (DOCS-1.12). An image that only got old, with no change to its route, is not stale.
 */
import {execFileSync} from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

import {imagePath} from './screens.mjs';

/** A screenshot older than this many closed releases is checked against its route's history. */
export const STALE_AFTER_RELEASES = 2;

/** Where the app's routes live, relative to the repository root (the Next.js app router). */
export const APP_ROUTES_DIR = 'apiome-ui/src/app';

/**
 * @callback LastChange
 * @param {string[]} paths - Repository-relative paths.
 * @returns {Date | null} When any of them last changed in a commit; `null` when none has history.
 */

/**
 * The repository-relative paths whose changes make a screenshot stale.
 *
 * The entry's `sources` when it lists them; otherwise the route's folder under
 * {@link APP_ROUTES_DIR} (`/ade/dashboard/catalog` → `apiome-ui/src/app/ade/dashboard/catalog`),
 * when that folder exists.
 *
 * @param {{route: string, sources?: string[]}} screen - A manifest entry.
 * @param {string} repoRoot - Absolute path of the repository root.
 * @returns {string[]} The paths; empty when the route has no folder and the entry names none.
 */
export function screenSources(screen, repoRoot) {
  if (screen.sources) return screen.sources;
  const route = screen.route.split(/[?#]/)[0].replace(/\/$/, '');
  const folder = path.posix.join(APP_ROUTES_DIR, route);
  return fs.existsSync(path.join(repoRoot, folder)) ? [folder] : [];
}

/**
 * Build a {@link LastChange} that asks git.
 *
 * Returns `null` for every path when git is not available or the directory is not a checkout (the
 * Docker image build copies no `.git`), so the rule then has nothing to say rather than failing.
 *
 * @param {string} repoRoot - Absolute path of the repository root.
 * @returns {LastChange} The lookup.
 */
export function gitLastChange(repoRoot) {
  return (paths) => {
    if (paths.length === 0) return null;
    try {
      const out = execFileSync('git', ['log', '-1', '--format=%cI', '--', ...paths], {
        cwd: repoRoot,
        encoding: 'utf8',
        stdio: ['ignore', 'pipe', 'ignore'],
      }).trim();
      return out ? new Date(out) : null;
    } catch {
      return null;
    }
  };
}

/**
 * Read the closed releases from `release-notes/releases.json`.
 *
 * @param {string} file - Absolute path of the manifest.
 * @returns {Array<{name: string, closed: string}>} The releases; empty when the file is missing.
 */
export function loadReleases(file) {
  if (!fs.existsSync(file)) return [];
  return JSON.parse(fs.readFileSync(file, 'utf8')).releases ?? [];
}

/**
 * The release a screenshot must be newer than to skip the history check: the
 * `staleAfter`-th most recent closed release.
 *
 * @param {Array<{name: string, closed: string}>} releases - Closed releases, in any order.
 * @param {number} staleAfter - How many releases an image may span.
 * @returns {{name: string, closed: Date} | null} The cutoff, or `null` while fewer releases exist.
 */
export function staleCutoff(releases, staleAfter) {
  const sorted = [...releases].sort((a, b) => b.closed.localeCompare(a.closed));
  const release = sorted[staleAfter - 1];
  return release ? {name: release.name, closed: new Date(`${release.closed}T23:59:59Z`)} : null;
}

/**
 * Check every manifest entry for staleness.
 *
 * @param {object} options - Inputs.
 * @param {Array<{id: string, route: string, theme: string[], sources?: string[]}>} options.screens - Manifest entries.
 * @param {Array<{name: string, closed: string}>} options.releases - Closed releases.
 * @param {LastChange} options.lastChange - Commit-date lookup (git, or a fake in tests).
 * @param {string} options.repoRoot - Absolute path of the repository root.
 * @param {string} [options.screensPrefix] - Repository-relative path of the site's `static/`.
 * @param {number} [options.staleAfter] - Defaults to {@link STALE_AFTER_RELEASES}.
 * @returns {string[]} One problem per stale entry, naming the dates and the recapture command.
 */
export function checkStaleScreenshots({
  screens,
  releases,
  lastChange,
  repoRoot,
  screensPrefix = 'apiome-docs/static',
  staleAfter = STALE_AFTER_RELEASES,
}) {
  const cutoff = staleCutoff(releases, staleAfter);
  if (!cutoff) return [];

  const day = (date) => date.toISOString().slice(0, 10);
  const problems = [];
  for (const screen of screens) {
    // The older of the two themes decides: a half-refreshed entry is still stale.
    const captured = screen.theme
      .map((theme) => lastChange([path.posix.join(screensPrefix, imagePath(screen.id, theme))]))
      .filter((date) => date !== null)
      .sort((a, b) => a - b)[0];
    if (!captured || captured >= cutoff.closed) continue;

    const sources = screenSources(screen, repoRoot);
    const changed = lastChange(sources);
    if (!changed || changed <= captured) continue;

    problems.push(
      `screens.json: \`${screen.id}\` was captured ${day(captured)}, before ${cutoff.name}, and ` +
        `${sources.join(', ')} changed ${day(changed)}; run \`yarn docs:screenshots -- --id ${screen.id}\``,
    );
  }
  return problems;
}
