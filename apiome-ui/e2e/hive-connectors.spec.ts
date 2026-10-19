import { expect, test, type Page } from '@playwright/test';

import { GATE_THEMES, blockingAxeLines, mountMarkup, pinAppearance, readFixture } from './support/a11y';

/**
 * The Connectors pages, measured in a browser (CDG-1.7, #5958).
 *
 * `tests/connectors-pages.test.tsx` pins the behaviour — a failing dry run blocks the save, saving
 * opens the connector without a reload, an item links to its catalog page — and, with
 * `A11Y_FIXTURE_DUMP=1`, writes what it rendered into `e2e/fixtures/hive-a11y/`. This spec mounts
 * those four surfaces into `/login` (which compiles the real `globals.css` and needs no session)
 * and answers what jsdom cannot: the document never scrolls sideways at the desktop width, the
 * runs ledger's source badges are visible, and axe finds nothing serious or critical in the three
 * gate themes. Requires the app to be running (`PLAYWRIGHT_BASE_URL`, default
 * `http://localhost:3000`).
 */

/** The surfaces the jsdom suite dumps. */
const SURFACES = [
  'connectors',
  'connector-add',
  'connector-add-mcp-registry',
  'connector-detail',
  'connector-runs',
] as const;

/** The viewport width DESIGN.md §5 forbids horizontal document scroll at. */
const DESKTOP_WIDTH = 1280;

async function mount(page: Page, surface: (typeof SURFACES)[number], theme: string | null = null): Promise<void> {
  await mountMarkup(page, readFixture('hive-a11y', `${surface}.html`));
  await pinAppearance(page, theme);
}

for (const surface of SURFACES) {
  test(`${surface} does not scroll sideways at ${DESKTOP_WIDTH}px`, async ({ page }) => {
    await page.setViewportSize({ width: DESKTOP_WIDTH, height: 900 });
    await mount(page, surface);
    const overflows = await page.evaluate(() => {
      const doc = document.documentElement;
      return doc.scrollWidth - doc.clientWidth > 1;
    });
    expect(overflows).toBe(false);
  });

  for (const theme of GATE_THEMES) {
    test(`${surface} has no serious axe findings (${theme ?? 'light'})`, async ({ page }) => {
      await mount(page, surface, theme);
      expect(await blockingAxeLines(page)).toEqual([]);
    });
  }
}

test('the runs ledger shows each run behind a visible source badge', async ({ page }) => {
  await mount(page, 'connector-runs');
  const badges = page.getByTestId('refresh-run-source');
  await expect(badges.first()).toBeVisible();
  await expect(page.getByTestId('refresh-runs-ledger')).toContainText('Connector');
});

test('the wizard shows the dry run inventory before the save', async ({ page }) => {
  await mount(page, 'connector-add');
  await expect(page.getByTestId('connector-dry-run-result')).toBeVisible();
  await expect(page.getByTestId('connector-next')).toBeEnabled();
});
