/**
 * The screenshot manifest (`apiome-docs/screens.json`) — DOCS-1.3 (#5620).
 *
 * Every product screenshot on the site is an entry in the manifest, captured by
 * `scripts/screenshots.ts` into `static/img/screens/<id>.<theme>.png` and placed on a page with
 * `<Screenshot id="…" alt="…"/>`. This module is the part of that pipeline that needs no browser:
 * reading and validating the manifest, filling in its defaults, naming the image files, and the
 * checks `yarn docs:check` runs (every referenced id exists and has both theme images, every
 * entry has its images).
 */
import fs from 'node:fs';
import path from 'node:path';

/** The themes a screenshot is captured in, and the only values `theme` may hold. */
export const SCREEN_THEMES = Object.freeze(['light', 'dark']);

/** Values filled in for an entry that does not set them. */
export const SCREEN_DEFAULTS = Object.freeze({
  theme: SCREEN_THEMES,
  viewport: Object.freeze({width: 1440, height: 900}),
  density: 'comfortable',
  fontScale: 'md',
});

/**
 * The product's palettes (`apiome-ui/src/app/config/themes.ts`), the values `appTheme` may hold.
 * `system` is not one: it is a choice that resolves to `light` or `dark`, which is what an entry
 * without `appTheme` already shows.
 */
export const APP_THEMES = Object.freeze(['light', 'dark', 'high-contrast', 'blueprint', 'whiteboard', 'solarized', 'nord', 'darcula']);

/** Densities the app supports (`data-density`). */
const DENSITIES = new Set(['comfortable', 'compact']);

/** Font scales the app supports (`data-font-scale`). */
const FONT_SCALES = new Set(['xs', 'sm', 'md', 'lg', 'xl']);

/** A manifest id: lower-case words joined by hyphens, so it is safe as a file name. */
const ID_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

/** `fixture:<dir>/<file>` — a committed dump under `apiome-ui/e2e/fixtures/`. */
const FIXTURE_PATTERN = /^fixture:([A-Za-z0-9._-]+)\/([A-Za-z0-9._-]+\.html)$/;

/** The site-relative directory the images are written to and served from. */
export const SCREENS_DIR = 'img/screens';

/**
 * @typedef {object} ScreenData
 * @property {'golden-path'|'signed-out'|'fixture'} kind - Where the page's content comes from.
 * @property {string} [dir] - Fixture directory under `apiome-ui/e2e/fixtures/` (fixture only).
 * @property {string} [file] - Fixture file inside `dir` (fixture only).
 */

/**
 * @typedef {object} Screen
 * @property {string} id - Stable id; also the image file stem.
 * @property {string} route - The product route the screen shows, e.g. `/ade/dashboard/catalog`.
 * @property {string} waitFor - CSS selector that must be visible before the capture.
 * @property {{x: number, y: number, width: number, height: number}} [clip] - Region to capture.
 * @property {string[]} mask - CSS selectors whose elements are painted over (dates, ids, counts).
 * @property {string[]} theme - Themes to capture, a subset of {@link SCREEN_THEMES}.
 * @property {{width: number, height: number}} viewport - Browser viewport.
 * @property {'comfortable'|'compact'} density - `data-density` pinned on `<html>`.
 * @property {string} fontScale - `data-font-scale` pinned on `<html>`.
 * @property {string} [appTheme] - A product theme (one of {@link APP_THEMES}) pinned in every
 *   capture, whatever the site theme: both images then show that palette. For theme galleries.
 * @property {ScreenData} data - Parsed `data` field.
 * @property {ScreenData} [fallback] - Fixture to use when the golden-path stack is not available.
 */

/**
 * Parse a `data` / `fallback` value.
 *
 * @param {unknown} value - `"golden-path"`, `"signed-out"` or `"fixture:<dir>/<file>"`.
 * @returns {ScreenData | null} The parsed source, or `null` when the value is not one of those.
 */
export function parseData(value) {
  if (value === 'golden-path') return {kind: 'golden-path'};
  if (value === 'signed-out') return {kind: 'signed-out'};
  const match = typeof value === 'string' ? FIXTURE_PATTERN.exec(value) : null;
  return match ? {kind: 'fixture', dir: match[1], file: match[2]} : null;
}

/**
 * Check that a value is a positive integer.
 *
 * @param {unknown} value - Any value.
 * @returns {boolean} `true` for 1, 2, 3, …
 */
function isPositiveInteger(value) {
  return Number.isInteger(value) && value > 0;
}

/**
 * Validate one raw manifest entry and fill in its defaults.
 *
 * @param {Record<string, unknown>} raw - The entry as written in `screens.json`.
 * @returns {{screen: Screen | null, problems: string[]}} The normalized entry (or `null` when it
 *   is unusable) and every problem found, each prefixed with the entry's id when it has one.
 */
export function normalizeScreen(raw) {
  const problems = [];
  const label = typeof raw?.id === 'string' ? raw.id : '(entry without an id)';
  const fail = (message) => problems.push(`${label}: ${message}`);

  if (raw === null || typeof raw !== 'object' || Array.isArray(raw)) {
    return {screen: null, problems: ['every entry must be an object']};
  }
  if (typeof raw.id !== 'string' || !ID_PATTERN.test(raw.id)) {
    fail('`id` must be lower-case words joined by hyphens, e.g. `catalog-table`');
  }
  if (typeof raw.route !== 'string' || !raw.route.startsWith('/')) {
    fail('`route` must be a product path starting with `/`');
  }
  if (typeof raw.waitFor !== 'string' || raw.waitFor.trim() === '') {
    fail('`waitFor` must be a CSS selector that is visible once the screen is ready');
  }

  const data = parseData(raw.data);
  if (!data) fail('`data` must be "golden-path", "signed-out" or "fixture:<dir>/<file>.html"');

  let fallback;
  if (raw.fallback !== undefined) {
    fallback = parseData(raw.fallback);
    if (!fallback || fallback.kind !== 'fixture') {
      fail('`fallback` must be "fixture:<dir>/<file>.html"');
    } else if (data?.kind !== 'golden-path') {
      fail('`fallback` only applies to a "golden-path" entry');
    }
  }

  const theme = raw.theme ?? SCREEN_DEFAULTS.theme;
  if (
    !Array.isArray(theme) ||
    theme.length === 0 ||
    theme.some((name) => !SCREEN_THEMES.includes(name)) ||
    new Set(theme).size !== theme.length
  ) {
    fail(`\`theme\` must list one or both of ${SCREEN_THEMES.join(', ')}`);
  }

  const viewport = raw.viewport ?? SCREEN_DEFAULTS.viewport;
  if (!isPositiveInteger(viewport?.width) || !isPositiveInteger(viewport?.height)) {
    fail('`viewport` must be {"width": <px>, "height": <px>}');
  }

  const density = raw.density ?? SCREEN_DEFAULTS.density;
  if (!DENSITIES.has(density)) fail('`density` must be "comfortable" or "compact"');

  const fontScale = raw.fontScale ?? SCREEN_DEFAULTS.fontScale;
  if (!FONT_SCALES.has(fontScale)) fail(`\`fontScale\` must be one of ${[...FONT_SCALES].join(', ')}`);

  if (raw.appTheme !== undefined && !APP_THEMES.includes(raw.appTheme)) {
    fail(`\`appTheme\` must be one of ${APP_THEMES.join(', ')}`);
  }

  const mask = raw.mask ?? [];
  if (!Array.isArray(mask) || mask.some((selector) => typeof selector !== 'string' || selector.trim() === '')) {
    fail('`mask` must be a list of CSS selectors');
  }

  if (raw.clip !== undefined) {
    const {x, y, width, height} = raw.clip ?? {};
    if (![x, y].every((n) => Number.isInteger(n) && n >= 0) || !isPositiveInteger(width) || !isPositiveInteger(height)) {
      fail('`clip` must be {"x", "y", "width", "height"} in whole pixels');
    }
  }

  if (problems.length > 0) return {screen: null, problems};
  return {
    screen: {
      id: raw.id,
      route: raw.route,
      waitFor: raw.waitFor,
      ...(raw.clip ? {clip: raw.clip} : {}),
      mask,
      theme: [...theme],
      viewport: {width: viewport.width, height: viewport.height},
      density,
      fontScale,
      ...(raw.appTheme ? {appTheme: raw.appTheme} : {}),
      data,
      ...(fallback ? {fallback} : {}),
    },
    problems,
  };
}

/**
 * Validate a whole manifest document.
 *
 * @param {unknown} doc - The parsed `screens.json`.
 * @returns {{screens: Screen[], problems: string[]}} The usable entries and every problem.
 */
export function validateManifest(doc) {
  if (doc === null || typeof doc !== 'object' || !Array.isArray(doc.screens)) {
    return {screens: [], problems: ['screens.json must be {"screens": [ … ]}']};
  }
  const screens = [];
  const problems = [];
  const seen = new Set();
  for (const raw of doc.screens) {
    const result = normalizeScreen(raw);
    problems.push(...result.problems);
    if (!result.screen) continue;
    if (seen.has(result.screen.id)) {
      problems.push(`${result.screen.id}: duplicate id`);
      continue;
    }
    seen.add(result.screen.id);
    screens.push(result.screen);
  }
  return {screens, problems};
}

/**
 * Read and validate a manifest file.
 *
 * @param {string} file - Absolute path of `screens.json`.
 * @returns {{screens: Screen[], problems: string[]}} As {@link validateManifest}; a missing or
 *   unparsable file is reported as a problem.
 */
export function loadManifest(file) {
  let doc;
  try {
    doc = JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch (error) {
    return {screens: [], problems: [`${path.basename(file)}: ${error.message}`]};
  }
  return validateManifest(doc);
}

/**
 * The site-relative path of one screenshot image.
 *
 * @param {string} id - Manifest id.
 * @param {string} theme - `light` or `dark`.
 * @returns {string} e.g. `img/screens/catalog.dark.png`.
 */
export function imagePath(id, theme) {
  return `${SCREENS_DIR}/${id}.${theme}.png`;
}

/**
 * Pick the entries a run captures.
 *
 * @param {Screen[]} screens - The manifest entries.
 * @param {{ids?: string[], routes?: string[]}} filters - `--id` values (exact) and `--route`
 *   values (an entry matches when its route starts with the value). Empty filters select all.
 * @returns {Screen[]} The selected entries, in manifest order.
 */
export function selectScreens(screens, {ids = [], routes = []} = {}) {
  return screens.filter((screen) => {
    if (ids.length > 0 && !ids.includes(screen.id)) return false;
    if (routes.length > 0 && !routes.some((route) => screen.route.startsWith(route))) return false;
    return true;
  });
}

/**
 * Find every `<Screenshot id="…"/>` a page renders.
 *
 * Fenced code blocks and inline code are skipped: a page that *shows* the component as an example
 * does not render it.
 *
 * @param {string} source - Markdown / MDX source.
 * @returns {string[]} The referenced ids, once each, in order of first use.
 */
export function findScreenshotReferences(source) {
  const prose = source.replace(/^(\s*)(```|~~~)[^\n]*\n[\s\S]*?^\1\2[^\n]*$/gm, '').replace(/`[^`\n]*`/g, '');
  const ids = [];
  const pattern = /<Screenshot\b[^>]*?\bid=(?:"([^"]+)"|'([^']+)'|\{\s*["']([^"']+)["']\s*\})/g;
  for (const match of prose.matchAll(pattern)) {
    const id = match[1] ?? match[2] ?? match[3];
    if (!ids.includes(id)) ids.push(id);
  }
  return ids;
}

/**
 * The screenshot checks `yarn docs:check` runs.
 *
 * @param {object} options - Inputs.
 * @param {Screen[]} options.screens - Valid manifest entries.
 * @param {Array<{page: string, source: string}>} options.pages - Every doc page, by relative path.
 * @param {string} options.staticDir - Absolute path of the site's `static/` directory.
 * @returns {string[]} Problems: a page references an unknown id or one without both theme
 *   images, or a manifest entry is missing an image for a theme it declares.
 */
export function checkScreenshots({screens, pages, staticDir}) {
  const problems = [];
  const byId = new Map(screens.map((screen) => [screen.id, screen]));
  const exists = (id, theme) => fs.existsSync(path.join(staticDir, imagePath(id, theme)));

  for (const screen of screens) {
    for (const theme of screen.theme) {
      if (!exists(screen.id, theme)) {
        problems.push(
          `screens.json: \`${screen.id}\` has no ${theme} image (${imagePath(screen.id, theme)}); ` +
            `run \`yarn docs:screenshots -- --id ${screen.id}\``,
        );
      }
    }
  }

  for (const {page, source} of pages) {
    for (const id of findScreenshotReferences(source)) {
      const screen = byId.get(id);
      if (!screen) {
        problems.push(`${page}: <Screenshot id="${id}"/> is not in screens.json`);
      } else if (SCREEN_THEMES.some((theme) => !screen.theme.includes(theme) || !exists(id, theme))) {
        problems.push(`${page}: <Screenshot id="${id}"/> needs both a light and a dark image`);
      }
    }
  }
  return problems;
}

/**
 * @typedef {object} CaptureJob
 * @property {Screen} screen - The manifest entry.
 * @property {string} theme - `light` or `dark`.
 * @property {ScreenData} source - Where the content comes from in this run.
 * @property {string} output - Site-relative image path, see {@link imagePath}.
 */

/**
 * Decide what a run captures, and from where.
 *
 * A `golden-path` entry is captured from the signed-in stack when it is up; otherwise from its
 * `fallback` fixture when it has one; otherwise it is skipped. A `fixture` entry never needs the
 * stack, and a `signed-out` entry opens its route on apiome-ui without a session, which needs no
 * stack either.
 *
 * @param {Screen[]} screens - The selected entries.
 * @param {{stackAvailable: boolean}} options - Whether the golden-path stack answered.
 * @returns {{jobs: CaptureJob[], skipped: Array<{id: string, reason: string}>}} One job per
 *   entry and theme, and the entries that cannot be captured in this run.
 */
export function planCapture(screens, {stackAvailable}) {
  const jobs = [];
  const skipped = [];
  for (const screen of screens) {
    let source = screen.data;
    if (source.kind === 'golden-path' && !stackAvailable) {
      if (!screen.fallback) {
        skipped.push({id: screen.id, reason: 'needs the golden-path stack, which is not running, and has no fallback'});
        continue;
      }
      source = screen.fallback;
    }
    for (const theme of screen.theme) {
      jobs.push({screen, theme, source, output: imagePath(screen.id, theme)});
    }
  }
  return {jobs, skipped};
}

/**
 * @typedef {object} ScreenshotArgs
 * @property {string[]} ids - `--id` values.
 * @property {string[]} routes - `--route` values.
 * @property {string|undefined} uiUrl - `--ui-url`: an apiome-ui that is already running.
 * @property {boolean} startUi - `--start-ui`: start an apiome-ui dev server for the run.
 * @property {boolean} boot - `--boot`: start the golden-path stack when it is not running.
 * @property {boolean} fixturesOnly - `--fixtures-only`: never use the stack, even when it is up.
 * @property {boolean} help - `--help`.
 */

/**
 * Parse the command line of `yarn docs:screenshots`.
 *
 * Accepts `--id a --id b`, `--id a,b` and `--id=a`; a bare `--` (as `yarn x -- --id a` passes
 * it) is ignored.
 *
 * @param {string[]} argv - Arguments after the script name.
 * @returns {ScreenshotArgs} The parsed options.
 * @throws {Error} On an unknown option or an option missing its value.
 */
export function parseScreenshotArgs(argv) {
  const args = {ids: [], routes: [], uiUrl: undefined, startUi: false, boot: false, fixturesOnly: false, help: false};
  const flags = {'--start-ui': 'startUi', '--boot': 'boot', '--fixtures-only': 'fixturesOnly', '--help': 'help', '-h': 'help'};
  for (let i = 0; i < argv.length; i += 1) {
    const [name, inline] = argv[i].split(/=(.*)/s, 2);
    if (name === '--') continue;
    if (name in flags) {
      args[flags[name]] = true;
      continue;
    }
    if (!['--id', '--route', '--ui-url'].includes(name)) throw new Error(`unknown option ${name}`);
    const value = inline ?? argv[(i += 1)];
    if (value === undefined || value.startsWith('--')) throw new Error(`${name} needs a value`);
    if (name === '--ui-url') args.uiUrl = value.replace(/\/+$/, '');
    else (name === '--id' ? args.ids : args.routes).push(...value.split(',').filter(Boolean));
  }
  return args;
}
