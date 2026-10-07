/**
 * `yarn docs:screenshots` — capture every product screenshot the docs site uses (DOCS-1.3, #5620).
 *
 * Reads `screens.json`, opens each entry's route in Chromium at its viewport (1440 × 900 by
 * default), pins the appearance the same way the accessibility gate does
 * (`apiome-ui/e2e/support/a11y.ts`: theme, density, font scale, frozen motion), fixes the clock,
 * paints over the `mask` selectors, and writes `static/img/screens/<id>.<theme>.png`.
 *
 * Where a screen's content comes from (`data` in the manifest):
 *
 * - `golden-path` — the real route, signed in as the seeded user, against the golden-path stack
 *   (`scripts/golden_path/run.sh`: Postgres, REST, MCP, mock, seeded tenant `acme-corp`).
 * - `fixture:<dir>/<file>` — a committed dump from `apiome-ui/e2e/fixtures/`, mounted into
 *   `/login` (which compiles the real `globals.css` and needs no session). A `golden-path` entry
 *   with a `fallback` fixture uses it when the stack is not running.
 *
 * Usage (from the repository root):
 *
 *   yarn docs:screenshots                         # every entry, against a running apiome-ui
 *   yarn docs:screenshots -- --id catalog         # one entry (repeat or comma-separate --id)
 *   yarn docs:screenshots -- --route /ade/dashboard/catalog
 *   yarn docs:screenshots -- --start-ui           # start an apiome-ui dev server for the run
 *   yarn docs:screenshots -- --start-ui --boot    # …and bring the golden-path stack up first
 *   yarn docs:screenshots -- --fixtures-only      # ignore the stack even when it is up
 *
 * Environment:
 *
 *   DOCS_UI_URL           apiome-ui to capture from (default http://localhost:3300; --ui-url wins)
 *   APIOME_REST_URL       REST API probed for the stack (default http://localhost:8000)
 *   DOCS_USER_EMAIL       seeded user (default ada@example.com)
 *   DOCS_USER_PASSWORD    seeded password (default apiome-dev)
 *   DOCS_CHROMIUM_PATH    Chromium executable, when Playwright's own browser is not installed
 *
 * Exits 1 when any selected entry could not be captured.
 */
import {spawn, spawnSync, type ChildProcess} from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

import {chromium, type Browser, type BrowserContext, type Page} from '@playwright/test';

import {mountMarkup, pinAppearance, readFixture} from '../../apiome-ui/e2e/support/a11y';
import {loadManifest, parseScreenshotArgs, planCapture, selectScreens} from './lib/screens.mjs';

/** The docs workspace (`apiome-docs/`). */
const SITE_DIR = path.resolve(__dirname, '..');

/** The repository root. */
const REPO_ROOT = path.resolve(SITE_DIR, '..');

/** The app's workspace, started by `--start-ui`. */
const UI_DIR = path.join(REPO_ROOT, 'apiome-ui');

/** Port of the dev server `--start-ui` starts (the visual-parity harness uses the same). */
const UI_PORT = 3300;

/**
 * The instant every captured page believes it is. Dates and relative times ("3 days ago") then
 * read the same on every run; anything that still moves goes in an entry's `mask`.
 */
const FIXED_TIME = new Date('2026-06-15T09:30:00Z');

/** Paint for masked regions — a neutral grey that reads in both themes. */
const MASK_COLOR = '#9aa3ad';

/** How long a page may take to show its `waitFor` selector. */
const READY_TIMEOUT_MS = 60_000;

/** One capture: an entry, a theme, and where the content comes from. */
interface CaptureJob {
  screen: {
    id: string;
    route: string;
    waitFor: string;
    clip?: {x: number; y: number; width: number; height: number};
    mask: string[];
    viewport: {width: number; height: number};
    density: 'comfortable' | 'compact';
    fontScale: string;
  };
  theme: 'light' | 'dark';
  source: {kind: 'golden-path'} | {kind: 'fixture'; dir: string; file: string};
  output: string;
}

/**
 * Wait until a URL answers with a non-error status.
 *
 * @param url The URL to probe.
 * @param timeoutMs How long to keep trying.
 * @returns `true` once it answers, `false` when time runs out.
 */
async function waitForUrl(url: string, timeoutMs: number): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  do {
    try {
      const response = await fetch(url, {signal: AbortSignal.timeout(4_000)});
      if (response.ok) return true;
    } catch {
      // Not up yet.
    }
    if (timeoutMs > 0) await new Promise((resolve) => setTimeout(resolve, 2_000));
  } while (Date.now() < deadline);
  return false;
}

/**
 * Is the golden-path stack up? Probes the REST API's readiness endpoint.
 *
 * @returns `true` when `GET <APIOME_REST_URL>/readyz` answers.
 */
async function stackIsUp(): Promise<boolean> {
  const rest = (process.env.APIOME_REST_URL ?? 'http://localhost:8000').replace(/\/+$/, '');
  return waitForUrl(`${rest}/readyz`, 0);
}

/**
 * Bring the golden-path stack up and leave it running (`scripts/golden_path/run.sh --keep`).
 *
 * @throws Error when the script fails.
 */
function bootStack(): void {
  console.log('==> Booting the golden-path stack (scripts/golden_path/run.sh --keep)');
  const result = spawnSync(path.join(REPO_ROOT, 'scripts', 'golden_path', 'run.sh'), ['--keep'], {
    cwd: REPO_ROOT,
    stdio: 'inherit',
  });
  if (result.status !== 0) throw new Error('scripts/golden_path/run.sh failed');
}

/**
 * Start an apiome-ui dev server for the run.
 *
 * With the stack up, the app reads `apiome-ui/.env` (database, REST URL, auth secret) as
 * `yarn dev` always does. Without it, only `/login` is ever rendered, so the same pins as the
 * visual-parity harness apply and no database is needed.
 *
 * @param withStack Whether the golden-path stack is running.
 * @returns The child process and the URL it serves.
 */
async function startUi(withStack: boolean): Promise<{child: ChildProcess; url: string}> {
  const url = `http://localhost:${UI_PORT}`;
  const env: NodeJS.ProcessEnv = {
    ...process.env,
    BETTER_AUTH_URL: url,
    // The beta background is decorative and animated; off, so nothing moves under a capture.
    NEXT_PUBLIC_BETA_MODE: '',
  };
  if (!withStack) {
    env.APIOME_LOAD_DOTENV = '0';
    env.BETTER_AUTH_SECRET = process.env.BETTER_AUTH_SECRET ?? 'docs-screenshots-secret';
  }
  console.log(`==> Starting apiome-ui on ${url}`);
  const child = spawn('yarn', ['dev', '--port', String(UI_PORT)], {cwd: UI_DIR, env, stdio: 'ignore', detached: true});
  if (!(await waitForUrl(`${url}/login`, 240_000))) {
    stopUi(child);
    throw new Error(`apiome-ui did not answer on ${url}/login`);
  }
  return {child, url};
}

/**
 * Stop a dev server started by {@link startUi}, with everything it spawned.
 *
 * @param child The `yarn dev` process (a process-group leader).
 */
function stopUi(child: ChildProcess): void {
  if (child.pid === undefined) return;
  try {
    process.kill(-child.pid, 'SIGTERM');
  } catch {
    // Already gone.
  }
}

/**
 * Sign in as the seeded user through the login page's email form, and keep the session.
 *
 * @param browser The browser.
 * @param baseURL The apiome-ui origin.
 * @returns The signed-in storage state, reused by every golden-path capture.
 */
async function signIn(browser: Browser, baseURL: string): Promise<Awaited<ReturnType<BrowserContext['storageState']>>> {
  const context = await browser.newContext({baseURL});
  const page = await context.newPage();
  await page.goto('/login');
  await page.getByRole('button', {name: 'or use your email'}).click();
  await page.locator('#email').fill(process.env.DOCS_USER_EMAIL ?? 'ada@example.com');
  await page.locator('#password').fill(process.env.DOCS_USER_PASSWORD ?? 'apiome-dev');
  await page.locator('#credentials-form').getByRole('button', {name: /Sign In/}).click();
  await page.waitForURL((url) => !url.pathname.startsWith('/login'), {timeout: READY_TIMEOUT_MS});
  const state = await context.storageState();
  await context.close();
  return state;
}

/**
 * Load a job's content into the page: the real route, or a fixture mounted into `/login`.
 *
 * @param page The page.
 * @param job The capture.
 */
async function loadContent(page: Page, job: CaptureJob): Promise<void> {
  if (job.source.kind === 'fixture') {
    await mountMarkup(page, readFixture(job.source.dir, job.source.file));
  } else {
    await page.goto(job.screen.route);
    await page.waitForLoadState('networkidle');
  }
}

/**
 * Capture one job to its PNG.
 *
 * @param browser The browser.
 * @param baseURL The apiome-ui origin.
 * @param job The capture.
 * @param session Signed-in storage state, for golden-path content.
 */
async function capture(
  browser: Browser,
  baseURL: string,
  job: CaptureJob,
  session: Awaited<ReturnType<BrowserContext['storageState']>> | undefined,
): Promise<void> {
  const context = await browser.newContext({
    baseURL,
    viewport: job.screen.viewport,
    deviceScaleFactor: 1,
    colorScheme: job.theme,
    reducedMotion: 'reduce',
    locale: 'en-US',
    timezoneId: 'UTC',
    ...(job.source.kind === 'golden-path' && session ? {storageState: session} : {}),
  });
  try {
    const page = await context.newPage();
    await page.clock.setFixedTime(FIXED_TIME);
    await loadContent(page, job);
    await pinAppearance(page, job.theme === 'dark' ? 'dark' : null, {
      density: job.screen.density,
      fontScale: job.screen.fontScale,
    });
    await page.locator(job.screen.waitFor).first().waitFor({state: 'visible', timeout: READY_TIMEOUT_MS});
    await page.evaluate(() => document.fonts.ready.then(() => undefined));

    const file = path.join(SITE_DIR, 'static', job.output);
    fs.mkdirSync(path.dirname(file), {recursive: true});
    await page.screenshot({
      path: file,
      ...(job.screen.clip ? {clip: job.screen.clip} : {}),
      mask: job.screen.mask.map((selector) => page.locator(selector)),
      maskColor: MASK_COLOR,
      animations: 'disabled',
      caret: 'hide',
      scale: 'css',
    });
    console.log(`  ✓ ${job.output} (${job.source.kind})`);
  } finally {
    await context.close();
  }
}

/**
 * Run the pipeline.
 *
 * @returns The process exit code.
 */
async function main(): Promise<number> {
  const args = parseScreenshotArgs(process.argv.slice(2));
  if (args.help) {
    console.log(fs.readFileSync(__filename, 'utf8').split('*/')[0]);
    return 0;
  }

  const manifest = loadManifest(path.join(SITE_DIR, 'screens.json'));
  if (manifest.problems.length > 0) {
    for (const problem of manifest.problems) console.error(`screens.json: ${problem}`);
    return 1;
  }
  const screens = selectScreens(manifest.screens, {ids: args.ids, routes: args.routes});
  if (screens.length === 0) {
    console.error('No manifest entry matches the --id / --route filters.');
    return 1;
  }

  let stackAvailable = !args.fixturesOnly && (await stackIsUp());
  if (!stackAvailable && args.boot && !args.fixturesOnly) {
    bootStack();
    stackAvailable = await stackIsUp();
  }
  console.log(`==> Golden-path stack: ${stackAvailable ? 'up' : 'not running (fixtures and fallbacks only)'}`);

  const {jobs, skipped} = planCapture(screens, {stackAvailable}) as {
    jobs: CaptureJob[];
    skipped: Array<{id: string; reason: string}>;
  };

  let ui: {child: ChildProcess; url: string} | undefined;
  let browser: Browser | undefined;
  const failed: string[] = [];
  try {
    if (args.startUi) ui = await startUi(stackAvailable);
    const baseURL = ui?.url ?? args.uiUrl ?? (process.env.DOCS_UI_URL ?? `http://localhost:${UI_PORT}`).replace(/\/+$/, '');
    if (!(await waitForUrl(`${baseURL}/login`, 0))) {
      console.error(`apiome-ui is not answering on ${baseURL}/login — start it, or pass --start-ui.`);
      return 1;
    }

    browser = await chromium.launch({executablePath: process.env.DOCS_CHROMIUM_PATH || undefined});
    const session = jobs.some((job) => job.source.kind === 'golden-path') ? await signIn(browser, baseURL) : undefined;

    console.log(`==> Capturing ${jobs.length} image(s) from ${baseURL}`);
    for (const job of jobs) {
      try {
        await capture(browser, baseURL, job, session);
      } catch (error) {
        failed.push(`${job.output}: ${(error as Error).message.split('\n')[0]}`);
        console.error(`  ✗ ${job.output}`);
      }
    }
  } finally {
    await browser?.close();
    if (ui) stopUi(ui.child);
  }

  for (const {id, reason} of skipped) console.error(`  - skipped ${id}: ${reason}`);
  for (const line of failed) console.error(`  - failed ${line}`);
  return skipped.length > 0 || failed.length > 0 ? 1 : 0;
}

main().then(
  (code) => process.exit(code),
  (error) => {
    console.error(error instanceof Error ? error.message : error);
    process.exit(1);
  },
);
