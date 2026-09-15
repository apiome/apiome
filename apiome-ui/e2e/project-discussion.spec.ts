import * as fs from 'fs';
import * as path from 'path';
import { expect, test, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

/**
 * The Project Discussion panel, measured in a browser (COL-1.3, #4515).
 *
 * `tests/project-discussion-panel.test.tsx` pins what the panel renders and how its filters and
 * links behave; `tests/discussion-css.test.ts` pins its declarations. Neither can answer the
 * questions about *computed layout*, because jsdom compiles no CSS:
 *
 *   • **No horizontal document scroll**, from 1440 px down to a phone, in every theme — on a
 *     fixture whose longest pathname and comment are single unbroken tokens.
 *   • **The rows wrap**: the chips, the row head and the meta line fold rather than overflow.
 *   • **Every row's element name is a link into the Studio** carrying the COL-1.2 deep link.
 *   • **"axe: zero serious/critical violations"**, in every theme.
 *
 * ### Why it mounts a fixture instead of signing in
 *
 * The states worth measuring — an orphaned thread, a capped count, a 100-character pathname — are
 * the ones a seeded database will not produce on demand. The fixture is not hand-written: the
 * jsdom suite renders the real panel and, with `DISCUSSION_FIXTURE_DUMP=1`, writes it to
 * `e2e/fixtures/project-discussion/panel.html`.
 *
 * This loads `/login`, which compiles the real `globals.css` and needs no session, and injects the
 * fixture into it. Requires the app to be running (`PLAYWRIGHT_BASE_URL`, default
 * `http://localhost:3000`).
 */

/** WCAG 2.1 Level A/AA. */
const WCAG_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'];

/** Every theme with a block of its own; `null` is the `:root` light default. */
const THEMES = [null, 'dark', 'high-contrast', 'blueprint', 'whiteboard', 'solarized', 'nord', 'darcula'];

/** Widths from a wide desktop down to a phone. */
const WIDTHS = [1440, 1280, 1024, 768, 420];

/** The fixture the jsdom suite writes. */
const FIXTURE = path.join(__dirname, 'fixtures', 'project-discussion', 'panel.html');

/**
 * Put the panel on a page that has the real stylesheet compiled.
 *
 * @param page - The Playwright page.
 */
async function mount(page: Page): Promise<void> {
  const html = fs.readFileSync(FIXTURE, 'utf8');
  await page.goto('/login');
  await page.waitForLoadState('networkidle');
  await page.evaluate((markup) => {
    document.body.innerHTML = `<main style="display:flex;flex-direction:column;min-height:100vh;padding:1rem">${markup}</main>`;
    document.body.style.margin = '0';
  }, html);
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => resolve(null))));
}

/**
 * Apply a theme.
 *
 * @param page - The Playwright page.
 * @param theme - The theme, or null for the default.
 */
async function applyTheme(page: Page, theme: string | null): Promise<void> {
  await page.evaluate((value) => {
    const root = document.documentElement;
    if (value) root.setAttribute('data-theme', value);
    else root.removeAttribute('data-theme');
  }, theme);
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => resolve(null))));
}

/**
 * Whether the document scrolls sideways.
 *
 * @param page - The Playwright page.
 * @returns True when the document is wider than the viewport.
 */
function documentOverflows(page: Page): Promise<boolean> {
  return page.evaluate(() => {
    const doc = document.documentElement;
    return doc.scrollWidth - doc.clientWidth > 1;
  });
}

test.describe('Project Discussion panel', () => {
  test('the fixture exists (regenerate it with DISCUSSION_FIXTURE_DUMP=1)', () => {
    expect(fs.existsSync(FIXTURE)).toBe(true);
  });

  test('never scrolls the document sideways, at any width', async ({ page }) => {
    await mount(page);
    for (const width of WIDTHS) {
      await page.setViewportSize({ width, height: 900 });
      await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => resolve(null))));
      expect({ width, overflows: await documentOverflows(page) }).toEqual({ width, overflows: false });
    }
  });

  test('wraps the longest element name inside its row', async ({ page }) => {
    await page.setViewportSize({ width: 420, height: 900 });
    await mount(page);
    const row = page.getByTestId('discussion-thread-thread-long');
    const name = row.locator('.disc-thread__element');
    const [rowBox, nameBox] = await Promise.all([row.boundingBox(), name.boundingBox()]);
    expect(rowBox).not.toBeNull();
    expect(nameBox).not.toBeNull();
    expect(nameBox!.x + nameBox!.width).toBeLessThanOrEqual(rowBox!.x + rowBox!.width + 1);
  });

  test('links every row into the Studio workspace', async ({ page }) => {
    await mount(page);
    const links = page.getByTestId('discussion-thread-link');
    expect(await links.count()).toBeGreaterThan(0);
    for (const href of await links.evaluateAll((nodes) => nodes.map((node) => node.getAttribute('href') ?? ''))) {
      const url = new URL(href);
      expect(url.pathname).toBe('/workspace');
      expect(url.searchParams.get('projectId')).toBeTruthy();
      expect(url.searchParams.get('versionId')).toBeTruthy();
    }
    const live = new URL((await page.getByTestId('discussion-thread-thread-class').getByTestId('discussion-thread-link').getAttribute('href'))!);
    expect(live.searchParams.get('comment')).toBe('class:class-customer');
    expect(live.searchParams.get('thread')).toBe('thread-class');
  });

  for (const theme of THEMES) {
    test(`axe: no serious or critical violations (${theme ?? 'light'})`, async ({ page }) => {
      await mount(page);
      await applyTheme(page, theme);
      const results = await new AxeBuilder({ page })
        .withTags(WCAG_TAGS)
        .include('[data-testid="project-discussion-panel"]')
        .analyze();
      const serious = results.violations.filter((violation) =>
        ['serious', 'critical'].includes(violation.impact ?? '')
      );
      expect(serious.map((violation) => `${violation.id}: ${violation.nodes.length}`)).toEqual([]);
    });
  }
});
