import * as fs from 'fs';
import * as path from 'path';
import { expect, test, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

/**
 * The dependency graph UI, measured in a browser (CDG-3.4, #5969).
 *
 * `tests/dependency-graph-ui.test.tsx` renders the real Dependencies panel, the graph page and
 * the Blast radius drawer against the CDG-3.3 golden fixture — a change to `GET /pets/{id}`
 * reaching 3 direct consumers, 1 transitive one, 2 verification runs and 1 agent-toolset tool —
 * and, with `A11Y_FIXTURE_DUMP=1`, writes what it rendered into `e2e/fixtures/hive-a11y/`. This
 * suite mounts those fixtures on `/login` (the real `globals.css`, no session) and asks what
 * jsdom cannot: axe in every theme, no sideways document scroll, the drawing keeping its own
 * scroller, the truncation notice, and that the golden answer reads the same in a browser.
 *
 * Requires the app to be running (`PLAYWRIGHT_BASE_URL`, default `http://localhost:3000`).
 */

const WCAG_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'];
const THEMES = [null, 'dark', 'high-contrast', 'blueprint', 'whiteboard', 'solarized', 'nord', 'darcula'];
const FIXTURES = path.join(__dirname, 'fixtures', 'hive-a11y');

type Fixture = 'dependency-graph' | 'dependency-graph-truncated' | 'dependencies-tab' | 'blast-radius';
const ALL: Fixture[] = ['dependency-graph', 'dependency-graph-truncated', 'dependencies-tab', 'blast-radius'];

function fixture(name: Fixture): string {
  return fs.readFileSync(path.join(FIXTURES, `${name}.html`), 'utf8');
}

async function mount(page: Page, name: Fixture, theme: string | null = null): Promise<void> {
  await page.goto('/login');
  await page.waitForLoadState('networkidle');
  await page.evaluate(
    ({ html, theme: next }) => {
      document.body.innerHTML = `<main style="min-height:100vh;background:var(--bg-canvas);padding:1rem">${html}</main>`;
      document.body.style.margin = '0';
      const frozen = document.createElement('style');
      frozen.textContent = '*,*::before,*::after{transition:none!important;animation:none!important}';
      document.head.appendChild(frozen);
      if (next) document.documentElement.setAttribute('data-theme', next);
      else document.documentElement.removeAttribute('data-theme');
    },
    { html: fixture(name), theme }
  );
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => resolve(null))));
}

function documentOverflows(page: Page): Promise<boolean> {
  return page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth > 1);
}

test.describe('the CDG-3.3 golden answer', () => {
  test('reads 3 direct, 1 transitive, 2 verification runs and 1 agent tool', async ({ page }) => {
    await mount(page, 'blast-radius');
    await expect(page.getByTestId('blast-radius-direct').getByRole('listitem')).toHaveCount(3);
    await expect(page.getByTestId('blast-radius-transitive').getByRole('listitem')).toHaveCount(1);
    await expect(page.getByTestId('blast-evidence-verification_runs').getByRole('listitem')).toHaveCount(2);
    await expect(page.getByTestId('blast-evidence-agent_toolset_tools').getByRole('listitem')).toHaveCount(1);
  });
});

test.describe('the truncation notice', () => {
  test('says "Showing … of N" when the search is cut short', async ({ page }) => {
    await mount(page, 'dependency-graph-truncated');
    await expect(page.getByTestId('graph-truncated')).toContainText('of 2,431');
  });
});

test.describe('layout', () => {
  for (const width of [1440, 1280, 900, 640]) {
    test(`no sideways document scroll at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      for (const name of ALL) {
        await mount(page, name);
        expect(await documentOverflows(page), `${name} at ${width}px`).toBe(false);
      }
    });
  }

  test('the drawing scrolls inside its own frame on a narrow screen', async ({ page }) => {
    await page.setViewportSize({ width: 640, height: 900 });
    await mount(page, 'dependencies-tab');
    const plot = page.getByTestId('dependency-graph-plot');
    const scrolls = await plot.evaluate((el) => el.scrollWidth > el.clientWidth);
    expect(scrolls).toBe(true);
  });
});

test.describe('accessibility', () => {
  for (const theme of THEMES) {
    test(`axe passes on every surface (${theme ?? 'light'})`, async ({ page }) => {
      for (const name of ALL) {
        await mount(page, name, theme);
        const results = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze();
        const serious = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical');
        expect(serious, `${name} (${theme ?? 'light'})`).toEqual([]);
      }
    });
  }

  test('a graph node takes focus and shows its ring', async ({ page }) => {
    await mount(page, 'dependencies-tab');
    const node = page.locator('.dg-node__link').first();
    await node.focus();
    const ring = node.locator('.dg-node__ring');
    await expect(ring).toHaveCSS('opacity', '1');
  });
});
