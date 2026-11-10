import { expect, test, type Locator, type Page } from '@playwright/test';

/**
 * The stacking scale, measured in a browser (SUX-1.1, apiome#6748).
 *
 * `tests/z-index-scale.test.tsx` pins which step each primitive names; only a browser can
 * say what is actually on top. Two questions, both answered with `elementFromPoint` — the
 * element a click at that spot would reach:
 *
 *   • **overlay above header** — with a dialog open, the centre of a header on the `chrome`
 *     step is covered by the dialog's scrim, so the header is dimmed and unclickable;
 *   • **popover above modal** — a select opened inside a dialog inside a drawer is the
 *     topmost element across its whole box, and choosing an option works.
 *
 * The header is a fixed bar injected at `var(--z-chrome)`, the step every global header
 * (the rail, Designer's top header) now uses: the gallery route needs no session and has no
 * shell of its own, which is what keeps this suite deterministic. Requires the app to be
 * running (`PLAYWRIGHT_BASE_URL`, default `http://localhost:3000`).
 */

/** Test id of the injected stand-in for a global header. */
const HEADER_ID = 'z-scale-header';

/**
 * Load the gallery with motion frozen and a `chrome`-layer header across the top.
 *
 * @param page The page under test.
 */
async function openGalleryWithHeader(page: Page): Promise<void> {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto('/design-system#overlays');
  await page.waitForLoadState('networkidle');
  await page.addStyleTag({
    content: '*, *::before, *::after { transition: none !important; animation: none !important; }',
  });
  await page.evaluate((id) => {
    const header = document.createElement('div');
    header.dataset.testid = id;
    header.style.cssText =
      'position: fixed; top: 0; left: 0; right: 0; height: 48px; z-index: var(--z-chrome); background: #fff;';
    document.body.appendChild(header);
  }, HEADER_ID);
}

/**
 * The element a pointer would hit at a point.
 *
 * @param page The page under test.
 * @param x Viewport x, in CSS pixels.
 * @param y Viewport y, in CSS pixels.
 * @returns A short description of the hit element: its test id, role and classes.
 */
async function hitAt(page: Page, x: number, y: number): Promise<{ testId: string | null; className: string }> {
  return page.evaluate(
    ([px, py]) => {
      const hit = document.elementFromPoint(px, py);
      return {
        testId: hit?.closest('[data-testid]')?.getAttribute('data-testid') ?? null,
        className: typeof hit?.className === 'string' ? hit.className : '',
      };
    },
    [x, y] as const
  );
}

/**
 * Whether the element at each probe point inside a box belongs to `locator`.
 *
 * @param page The page under test.
 * @param locator The element expected to be on top.
 * @returns One boolean per probe — the centre and a point just inside each corner.
 */
async function isTopmostAcross(page: Page, locator: Locator): Promise<boolean[]> {
  const box = await locator.boundingBox();
  if (!box) throw new Error('The element under test has no box');
  // Far enough in that a rounded corner (`--r-xl` is 20 px) cannot put a probe outside the box.
  const inset = 16;
  const probes: Array<[number, number]> = [
    [box.x + box.width / 2, box.y + box.height / 2],
    [box.x + inset, box.y + inset],
    [box.x + box.width - inset, box.y + inset],
    [box.x + inset, box.y + box.height - inset],
    [box.x + box.width - inset, box.y + box.height - inset],
  ];
  const handle = await locator.elementHandle();
  return Promise.all(
    probes.map(([x, y]) =>
      page.evaluate(
        ([element, px, py]) => {
          const hit = document.elementFromPoint(px, py);
          return !!hit && (element as Element).contains(hit);
        },
        [handle, x, y] as const
      )
    )
  );
}

test.describe('Stacking scale', () => {
  test.beforeEach(async ({ page }) => {
    await openGalleryWithHeader(page);
  });

  test('without a modal, the header is on top of the page', async ({ page }) => {
    expect((await hitAt(page, 640, 24)).testId).toBe(HEADER_ID);
  });

  test('a dialog’s scrim covers the global header', async ({ page }) => {
    await page.locator('#overlays').getByRole('button', { name: 'Open dialog', exact: true }).click();
    await expect(page.getByRole('dialog', { name: 'Publish version 2.4.0' })).toBeVisible();

    const hit = await hitAt(page, 640, 24);
    expect(hit.testId).not.toBe(HEADER_ID);
    expect(hit.className).toContain('hive-overlay');
  });

  test('a drawer’s scrim covers the global header', async ({ page }) => {
    await page.locator('#overlays').getByRole('button', { name: 'Open drawer', exact: true }).click();
    await expect(page.getByRole('dialog', { name: 'Audit event' })).toBeVisible();

    // Left of the 520 px sheet, so the probe lands on the scrim rather than on the drawer.
    const hit = await hitAt(page, 200, 24);
    expect(hit.testId).not.toBe(HEADER_ID);
    expect(hit.className).toContain('hive-overlay');
  });

  test('a select inside a dialog inside a drawer is fully visible and clickable', async ({ page }) => {
    await page.getByRole('button', { name: 'Open layered drawer' }).click();
    await page.getByRole('button', { name: 'Open dialog in drawer' }).click();
    const dialog = page.getByRole('dialog', { name: 'Move to domain' });
    await expect(dialog).toBeVisible();

    // The dialog clears the drawer it was opened from.
    expect(await isTopmostAcross(page, dialog)).toEqual([true, true, true, true, true]);

    await dialog.getByRole('combobox', { name: 'Domain' }).click();
    const listbox = page.getByRole('listbox');
    await expect(listbox).toBeVisible();

    // Popover above modal: nothing — dialog, drawer or either scrim — covers any part of it.
    expect(await isTopmostAcross(page, listbox)).toEqual([true, true, true, true, true]);

    await listbox.getByRole('option', { name: 'Logistics' }).click();
    await expect(dialog.getByRole('combobox', { name: 'Domain' })).toHaveText('Logistics');
  });
});
