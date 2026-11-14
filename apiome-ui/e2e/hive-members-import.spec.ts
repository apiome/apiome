import { expect, test, type Page } from '@playwright/test';

import { GATE_THEMES, blockingAxeLines, mountMarkup, pinAppearance, readFixture } from './support/a11y';

/**
 * The members CSV import dialog, measured in a browser (EID-2.5, #5671).
 *
 * `tests/members-hive-redesign.test.tsx` pins the behaviour — the dry run sends nothing, the 58
 * invites go through the invite route one by one, every refused row is listed — and, with
 * `A11Y_FIXTURE_DUMP=1`, writes the file step and the report into `e2e/fixtures/hive-a11y/`.
 * This spec mounts those two surfaces into `/login` (which compiles the real `globals.css` and
 * needs no session) and answers what jsdom cannot: the report keeps each address on one line,
 * its table scrolls inside the dialog rather than the document scrolling sideways, and axe
 * finds nothing serious or critical in the gate themes. Requires the app to be running
 * (`PLAYWRIGHT_BASE_URL`, default `http://localhost:3000`).
 */

/** The surfaces the jsdom suite dumps. */
const SURFACES = ['members-import-csv', 'members-import-report'] as const;

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

test('the report keeps every address on one line', async ({ page }) => {
  await page.setViewportSize({ width: DESKTOP_WIDTH, height: 900 });
  await mount(page, 'members-import-report');
  const heights = await page.locator('.mbr-import-email').evaluateAll((cells) =>
    cells.map((cell) => {
      const style = getComputedStyle(cell);
      const lineHeight = parseFloat(style.lineHeight);
      const line = Number.isFinite(lineHeight) ? lineHeight : parseFloat(style.fontSize) * 1.5;
      return cell.getBoundingClientRect().height / line;
    })
  );
  expect(heights.length).toBeGreaterThan(0);
  for (const lines of heights) expect(lines).toBeLessThan(1.5);
});

test('the report labels each outcome with a visible badge', async ({ page }) => {
  await mount(page, 'members-import-report');
  const report = page.getByTestId('members-import-report');
  for (const label of ['Invite', 'Already a member', 'Invalid email', 'Unknown role', 'No account', 'No seat left']) {
    await expect(report.locator('[data-outcome]').getByText(label, { exact: true }).first()).toBeVisible();
  }
  await expect(page.getByTestId('members-import-send')).toHaveText(/Send 1 invite/);
});
