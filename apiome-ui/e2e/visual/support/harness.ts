/**
 * Playwright glue for the visual-parity harness (HIVE-10.1, #5337).
 *
 * Everything Playwright-shaped lives here: where the two sides are loaded from, how the app
 * is given the mockup's page width so the two geometries are comparable at all, and how a
 * measurement becomes a {@link ParityReport}. The judgement itself is in `score.ts`, which
 * knows nothing about browsers.
 *
 * **The mockups are read-only.** Nothing in this file writes to `docs/mockups/`; they are
 * loaded over `file://`, exactly as `docs/mockups/README.md` describes its own QA sweep, and
 * the only mutation the harness ever performs is the deliberate padding regression it injects
 * into the *app* side to prove the gate can fail.
 */

import * as fs from 'fs';
import * as path from 'path';
import type { Page } from '@playwright/test';
import { collectRaw, type RawSignature } from '../collect';
import { landmarkSelectors, scopeSelector, type Side } from '../landmarks';
import { buildSignature, type ParitySignature } from '../signature';
import { judgeFirstRow, scoreParity, type FirstRowVerdict, type ParityReport } from '../score';
import { ALL_TOKENS, COLOUR_TOKENS } from '../tokens';
import type { FirstRowBudget, ParityRoute, ParitySubject } from '../routes';

/** `docs/mockups/`, the read-only source of truth. */
export const MOCKUP_ROOT = path.resolve(__dirname, '..', '..', '..', '..', 'docs', 'mockups');

/** `apiome-ui/e2e/fixtures/`, where the page epics dump what their components rendered. */
export const FIXTURE_ROOT = path.resolve(__dirname, '..', '..', 'fixtures');

/**
 * The viewport the comparison is made at.
 *
 * 1440 px is the width `docs/mockups/README.md` says the mockups were drawn at, and wide
 * enough that neither side is in a responsive fallback while being compared.
 */
export const PARITY_VIEWPORT = { width: 1440, height: 1000 };

/** How one page should be set up before it is measured. */
export interface OpenOptions {
  /** The `data-theme` to pin, or `null` for the `:root` light default. */
  theme?: string | null;
  /** The width the app's page region should be given, from the mockup measurement. */
  scopeWidth?: number;
}

/**
 * Read one committed fixture dump.
 *
 * @param dir The fixture directory, e.g. `hive-published`.
 * @param file The file inside it, e.g. `table.html`.
 * @returns The fixture's HTML.
 */
export function readFixture(dir: string, file: string): string {
  return fs.readFileSync(path.join(FIXTURE_ROOT, dir, file), 'utf8');
}

/** CSS that stops every transition, so a box read straight after a load is the final one. */
const FREEZE_MOTION =
  '*,*::before,*::after{transition:none!important;animation:none!important}';

/**
 * Pin the appearance preferences both design systems read off `<html>`.
 *
 * Both sides resolve themes the same way — `html[data-theme]` — so one helper serves both.
 * Density and font scale are pinned to their defaults as well: a mockup left on "compact" by
 * a previous visitor's `localStorage` would otherwise be measured against a comfortable app.
 *
 * @param page The page to pin.
 * @param theme The theme to set, or `null` for the light default.
 */
export async function pinAppearance(
  page: Page,
  theme: string | null | undefined
): Promise<void> {
  await page.evaluate(
    ({ theme: chosen, freeze }) => {
      const root = document.documentElement;
      if (chosen) {
        root.setAttribute('data-theme', chosen);
        root.setAttribute('data-theme-choice', chosen);
      } else {
        root.removeAttribute('data-theme');
        root.removeAttribute('data-theme-choice');
      }
      root.setAttribute('data-font-scale', 'md');
      root.setAttribute('data-density', 'comfortable');

      const style = document.createElement('style');
      style.id = 'visual-parity-frozen';
      style.textContent = freeze;
      document.head.appendChild(style);
    },
    { theme: theme ?? null, freeze: FREEZE_MOTION }
  );
  // One frame, so the pinned attributes have been through layout before anything is read.
  await page.evaluate(
    () => new Promise((resolve) => requestAnimationFrame(() => resolve(null)))
  );
}

/**
 * Load a mockup.
 *
 * @param page The page to load it into.
 * @param mockup The mockup path, relative to `docs/mockups/`.
 * @param options Appearance pins.
 */
export async function openMockup(
  page: Page,
  mockup: string,
  options: OpenOptions = {}
): Promise<void> {
  await page.setViewportSize(PARITY_VIEWPORT);
  await page.goto(`file://${path.join(MOCKUP_ROOT, mockup)}`);
  // `hive.js` renders the shell, so the page is only settled once it has run.
  await page.waitForFunction(() => document.querySelector('main.page') !== null);
  await pinAppearance(page, options.theme);
}

/**
 * Load the app side of a comparison.
 *
 * A fixture is mounted into `/login`, which is the one route that compiles the real
 * `globals.css` without needing a session — the pattern every Hive browser suite since
 * HIVE-7.1 uses. It is mounted inside a container of exactly the mockup's page width, which
 * is what makes the two geometries comparable: the mockup's page sits beside a rail this
 * fixture does not have, and comparing a 1200 px page against a 1440 px one would report a
 * layout difference that is really a measurement mistake.
 *
 * @param page The page to load it into.
 * @param subject Where the app side comes from.
 * @param options Appearance pins; `scopeWidth` is required for a fixture.
 */
export async function openApp(
  page: Page,
  subject: ParitySubject,
  options: OpenOptions
): Promise<void> {
  await page.setViewportSize(PARITY_VIEWPORT);

  if (subject.kind === 'route') {
    await page.goto(subject.path);
    await page.waitForLoadState('networkidle');
    await pinAppearance(page, options.theme);
    return;
  }

  const html = readFixture(subject.dir, subject.file);
  await page.goto('/login');
  await page.waitForLoadState('networkidle');
  await mountFixtureMarkup(page, html, options.scopeWidth ?? PARITY_VIEWPORT.width);
  await pinAppearance(page, options.theme);
}

/**
 * Replace whatever is on the page with one fixture, in a container of a given width.
 *
 * Split out of {@link openApp} because the theme-swap test mounts eighteen fixtures into a
 * single already-loaded page: the stylesheet is what the navigation is for, and re-fetching
 * it once per fixture would make that test a dev-server benchmark.
 *
 * @param page A page that has already loaded a route which compiles `globals.css`.
 * @param markup The fixture's HTML.
 * @param width The width to give the page region, in CSS pixels.
 */
export async function mountFixtureMarkup(
  page: Page,
  markup: string,
  width: number
): Promise<void> {
  await page.evaluate(
    ({ html, containerWidth }) => {
      document.body.style.margin = '0';
      document.body.style.background = 'var(--bg-canvas)';
      document.body.innerHTML =
        `<div id="visual-parity-mount" style="width:${containerWidth}px">${html}</div>`;
    },
    { html: markup, containerWidth: width }
  );
}

/**
 * Measure whichever page is loaded.
 *
 * @param page The loaded page.
 * @param side Which side of the comparison it is.
 * @param paddingDeltaPx Extra padding to inject first; the self-test hook.
 * @returns The raw measurement.
 */
export async function collectRawSignature(
  page: Page,
  side: Side,
  paddingDeltaPx = 0
): Promise<RawSignature> {
  return page.evaluate(collectRaw, {
    scopeSelector: scopeSelector(side),
    landmarks: landmarkSelectors(side) as unknown as Record<string, string>,
    tokens: [...ALL_TOKENS],
    colourTokens: [...COLOUR_TOKENS],
    paddingDeltaPx,
  });
}

/**
 * Measure whichever page is loaded and translate it into token space.
 *
 * @param page The loaded page.
 * @param side Which side of the comparison it is.
 * @param paddingDeltaPx Extra padding to inject first; the self-test hook.
 * @returns The signature.
 */
export async function collectSide(
  page: Page,
  side: Side,
  paddingDeltaPx = 0
): Promise<ParitySignature> {
  return buildSignature(await collectRawSignature(page, side, paddingDeltaPx), side);
}

/** The three screenshots of one comparison. */
export interface ParityImages {
  /** The mockup's page region. */
  mockup: Buffer;
  /** The app's page region, at the same size. */
  app: Buffer;
  /** The two, blended so that black means agreement. */
  diff: Buffer;
}

/** Both signatures, the verdict drawn from them, and the images for the eye. */
export interface ParityMeasurement {
  /** What the mockup measured. */
  mockup: ParitySignature;
  /** What the app measured. */
  app: ParitySignature;
  /** The verdict. */
  report: ParityReport;
  /** The screenshots, when `capture` was asked for. */
  images: ParityImages | null;
}

/**
 * Run one full comparison: load the mockup, load the app at the mockup's width, score.
 *
 * @param page The page to drive. It is navigated twice.
 * @param route The route map entry to measure.
 * @param options.theme The theme to pin on both sides.
 * @param options.paddingDeltaPx Padding to inject into the app; the self-test hook.
 * @param options.capture Whether to screenshot both sides and blend them.
 * @returns Both signatures, the report (with the first-row verdict when the route declares a
 *   budget) and — when asked for — the images.
 */
export async function measureParity(
  page: Page,
  route: ParityRoute,
  options: {
    theme?: string | null;
    paddingDeltaPx?: number;
    capture?: boolean;
  } = {}
): Promise<ParityMeasurement> {
  await openMockup(page, route.mockup, { theme: options.theme });
  const mockup = await collectSide(page, 'mockup');
  const mockupShot = options.capture ? await captureScope(page, 'mockup') : null;

  await openApp(page, route.subject, {
    theme: options.theme,
    scopeWidth: mockup.scope.width,
  });
  const app = await collectSide(page, 'app', options.paddingDeltaPx ?? 0);
  const appShot = options.capture ? await captureScope(page, 'app') : null;
  // Read last: it resizes the viewport to 1440 × 900, which the screenshot must not see.
  const firstRow = route.firstRow
    ? judgeFirstRow(route.firstRow, await measureFirstRow(page, route.firstRow.selector))
    : null;

  let images: ParityImages | null = null;
  if (mockupShot && appShot) {
    // Both are clipped to the same viewport height; the width is the mockup's page width,
    // which the app was mounted at, so the two only differ where the designs do.
    const size = {
      width: Math.min(mockupShot.width, appShot.width),
      height: Math.min(mockupShot.height, appShot.height),
    };
    images = {
      mockup: mockupShot.png,
      app: appShot.png,
      diff: await renderDifference(page, mockupShot.png, appShot.png, size),
    };
  }

  const subject =
    route.subject.kind === 'route'
      ? route.subject.path
      : `${route.subject.dir}/${route.subject.file}`;

  return {
    mockup,
    app,
    images,
    report: scoreParity({
      id: route.id,
      mockup: route.mockup,
      subject,
      app,
      mockupSignature: mockup,
      firstRow,
    }),
  };
}

/**
 * Screenshot the page region, clipped to the viewport.
 *
 * Both sides are clipped to the same width and height so the two images can be laid over
 * each other; a full-page shot of each would produce two images of different heights whose
 * difference would be meaningless.
 *
 * @param page The loaded page.
 * @param side Which side of the comparison it is.
 * @returns The PNG bytes and the size they were taken at.
 */
export async function captureScope(
  page: Page,
  side: Side
): Promise<{ png: Buffer; width: number; height: number }> {
  const selector = scopeSelector(side);
  const box = await page.evaluate((sel) => {
    const element = document.querySelector(sel);
    if (!element) return null;
    const rect = element.getBoundingClientRect();
    return { x: rect.left + window.scrollX, width: rect.width };
  }, selector);
  if (!box) throw new Error(`visual-parity: cannot screenshot, no element matched "${selector}"`);

  const width = Math.round(box.width);
  const height = PARITY_VIEWPORT.height;
  const png = await page.screenshot({
    clip: { x: Math.round(box.x), y: 0, width, height },
  });
  return { png, width, height };
}

/**
 * Render the difference between two screenshots as a third image.
 *
 * The blend is done by the browser (`mix-blend-mode: difference`) rather than by a pixel
 * library, so the harness stays dependency-free: black means the two pages agree at that
 * pixel, and anything bright is where they do not.
 *
 * @param page A page to render in. Its content is replaced.
 * @param mockupPng The mockup screenshot.
 * @param appPng The app screenshot.
 * @param size The size both screenshots were taken at.
 * @returns The PNG bytes of the difference.
 */
export async function renderDifference(
  page: Page,
  mockupPng: Buffer,
  appPng: Buffer,
  size: { width: number; height: number }
): Promise<Buffer> {
  await page.setViewportSize({ width: size.width, height: size.height });
  await page.setContent(
    `<!doctype html><html><body style="margin:0;background:#000">
      <div style="position:relative;width:${size.width}px;height:${size.height}px;isolation:isolate">
        <img src="data:image/png;base64,${mockupPng.toString('base64')}"
             style="position:absolute;inset:0;width:100%;height:100%" alt="" />
        <img src="data:image/png;base64,${appPng.toString('base64')}"
             style="position:absolute;inset:0;width:100%;height:100%;mix-blend-mode:difference" alt="" />
      </div>
    </body></html>`
  );
  return page.screenshot({ clip: { x: 0, y: 0, width: size.width, height: size.height } });
}

/**
 * The viewport the first-row budget is measured at (HIVE-13.3, #5616).
 *
 * `docs/mockups/PROPOSALS.md` measured every first-row offset at 1440 × 900, so a budget taken
 * from it only means something at that size. The parity comparison itself runs at
 * {@link PARITY_VIEWPORT}; the budget is read after it, once the viewport has been set to this.
 */
export const FIRST_ROW_VIEWPORT = { width: 1440, height: 900 };

/**
 * Read how far down the page region the first row of data starts.
 *
 * The page region is the top of the viewport on both shells (neither has a top bar), so the
 * offset from the region's top edge is the same y the proposals measured by eye. The page is
 * scrolled to the top first, so a previous measurement cannot leave the row half-way up.
 *
 * @param page A page with the app side loaded and its appearance pinned.
 * @param rowSelector The selector of the first data row; the first match is read.
 * @returns The row's top edge in CSS pixels below the page region's top, rounded to a whole
 *   pixel, or `null` when nothing matched the selector.
 * @throws When the page region itself is missing, which is a harness error, not a budget miss.
 */
export async function measureFirstRow(page: Page, rowSelector: string): Promise<number | null> {
  await page.setViewportSize(FIRST_ROW_VIEWPORT);
  return page.evaluate(
    ({ scope, row }) => {
      window.scrollTo(0, 0);
      const region = document.querySelector(scope);
      if (!region) throw new Error(`visual-parity: no element matched scope selector "${scope}"`);
      const first = region.querySelector(row);
      if (!first) return null;
      return Math.round(first.getBoundingClientRect().top - region.getBoundingClientRect().top);
    },
    { scope: scopeSelector('app'), row: rowSelector }
  );
}

/**
 * Mount one fixture and judge its first row against a budget, without a parity comparison.
 *
 * The first-row self-test uses this to hold frozen fixtures — the Catalog before and after its
 * quiet pass — against the Catalog budget, so the gate is proven to tell the two apart.
 *
 * @param page The page to drive.
 * @param subject The fixture to mount.
 * @param budget The budget to judge it against.
 * @param scopeWidth The width to give the page region, normally the paired mockup's page width.
 * @returns The verdict.
 */
export async function judgeFixtureFirstRow(
  page: Page,
  subject: ParitySubject,
  budget: FirstRowBudget,
  scopeWidth: number
): Promise<FirstRowVerdict> {
  await openApp(page, subject, { theme: null, scopeWidth });
  return judgeFirstRow(budget, await measureFirstRow(page, budget.selector));
}
