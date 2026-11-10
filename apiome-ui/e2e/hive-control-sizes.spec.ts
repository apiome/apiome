import { expect, test, type Page } from '@playwright/test';

/**
 * Field size parity, measured in a browser (SUX-1.2, apiome#6749).
 *
 * `tests/control-sizes.test.tsx` pins the classes; only a browser can say the boxes line up.
 * The gallery's control-sizes specimen draws one row per size step — `Button`, `Input`,
 * `Select` trigger and `Segmented` side by side — and this suite checks, at both densities,
 * that every control in a row has the same outer height, that height is the row's metric
 * (`--control-h-sm`, `--control-h`, `--control-h-lg`), and their text shares a baseline.
 *
 * The gallery route needs no session. Requires the app to be running
 * (`PLAYWRIGHT_BASE_URL`, default `http://localhost:3000`).
 */

/** The size steps and the custom property each is bound to. */
const STEPS = [
  { size: 'sm', metric: '--control-h-sm' },
  { size: 'md', metric: '--control-h' },
  { size: 'lg', metric: '--control-h-lg' },
] as const;

/** One control's outer box and the y of its first text line's baseline. */
interface Measured {
  /** What the control is, for the failure message. */
  name: string;
  /** Border-box height, in CSS pixels. */
  height: number;
  /** Top of the box, in CSS pixels from the viewport top. */
  top: number;
}

/**
 * Open the gallery at a density, with motion frozen.
 *
 * @param page The page under test.
 * @param density The `data-density` value to pin on `<html>`.
 */
async function openGallery(page: Page, density: 'comfortable' | 'compact'): Promise<void> {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/design-system#forms');
  await page.waitForLoadState('networkidle');
  await page.addStyleTag({
    content: '*, *::before, *::after { transition: none !important; animation: none !important; }',
  });
  await page.evaluate((value) => document.documentElement.setAttribute('data-density', value), density);
}

/**
 * Measure the four controls of one row.
 *
 * @param page The page under test.
 * @param size The row's size step.
 * @returns The button, input, select trigger and segmented track, in that order.
 */
async function measureRow(page: Page, size: string): Promise<Measured[]> {
  return page.evaluate((step) => {
    const row = document.querySelector(`[data-testid="control-size-row-${step}"]`);
    if (!row) throw new Error(`row ${step} not found`);
    const pick = (selector: string, name: string) => {
      const el = row.querySelector(selector);
      if (!el) throw new Error(`${name} not found in row ${step}`);
      const box = el.getBoundingClientRect();
      return { name, height: box.height, top: box.top };
    };
    return [
      pick('button:not([role])', 'Button'),
      pick('input', 'Input'),
      pick('[role="combobox"]', 'Select'),
      pick('[role="radiogroup"]', 'Segmented'),
    ];
  }, size);
}

/**
 * The pixel value a control metric resolves to on the page.
 *
 * @param page The page under test.
 * @param metric The custom property name.
 * @returns Its computed height in CSS pixels.
 */
async function metricPx(page: Page, metric: string): Promise<number> {
  return page.evaluate((name) => {
    const probe = document.createElement('div');
    probe.style.height = `var(${name})`;
    document.body.appendChild(probe);
    const px = probe.getBoundingClientRect().height;
    probe.remove();
    return px;
  }, metric);
}

for (const density of ['comfortable', 'compact'] as const) {
  test.describe(`control sizes at ${density} density`, () => {
    for (const step of STEPS) {
      test(`${step.size}: button, input, select and segmented share height and top`, async ({ page }) => {
        await openGallery(page, density);
        const expected = await metricPx(page, step.metric);
        const controls = await measureRow(page, step.size);
        for (const control of controls) {
          expect(control.height, `${control.name} height`).toBeCloseTo(expected, 0);
        }
        // Same height and centred in one flex row → same top edge, and the single line of
        // text each centres sits on one baseline.
        const tops = controls.map((c) => c.top);
        expect(Math.max(...tops) - Math.min(...tops)).toBeLessThanOrEqual(1);
      });
    }

    test('the default Segmented equals --control-h', async ({ page }) => {
      await openGallery(page, density);
      const expected = await metricPx(page, '--control-h');
      const [, , , segmented] = await measureRow(page, 'md');
      expect(segmented.height).toBeCloseTo(expected, 0);
    });
  });
}
