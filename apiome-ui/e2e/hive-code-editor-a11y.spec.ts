import { expect, test, type Page } from '@playwright/test';

import { GATE_THEMES, blockingAxeLines, pinAppearance } from './support/a11y';

/**
 * The Hive editor theme under the axe gate — #6274.
 *
 * Monaco paints code in colours of its own, and before #6274 no gated page rendered a
 * Hive-themed editor, so its light keys, strings and line numbers fell under 4.5:1 unseen.
 * This suite opens `/design-system/code-editor` (a YAML and a JSON specimen through the real
 * `useHiveMonacoTheme`), waits until Monaco has painted the lines and the gutter, checks the
 * editor really took the Hive palette (its well is `--bg-inset`, not a stock theme's grey), and
 * runs axe at the shared tags ({@link WCAG_TAGS}) in each gate theme: zero serious or critical
 * violations, colour contrast included.
 */

const ROUTE = '/design-system/code-editor';
const EDITORS = ['hive-editor-yaml', 'hive-editor-json'];

/**
 * Wait until both editors have painted their lines and line numbers.
 *
 * @param page The page.
 */
async function waitForEditors(page: Page): Promise<void> {
  for (const id of EDITORS) {
    const editor = page.getByTestId(id);
    await expect(editor.locator('.monaco-editor .view-line').first()).toBeVisible({ timeout: 30_000 });
    await expect(editor.locator('.monaco-editor .line-numbers').first()).toBeVisible();
  }
}

/**
 * The editor's well colour and `--bg-inset`, both as the browser resolves them.
 *
 * @param page The page.
 * @param id The editor container's test id.
 * @returns `[well, inset]` as `rgb()` strings.
 */
async function wellAndInset(page: Page, id: string): Promise<[string, string]> {
  return page.evaluate((testId) => {
    const well = document.querySelector(`[data-testid="${testId}"] .monaco-editor-background`);
    const probe = document.createElement('div');
    probe.style.backgroundColor = 'var(--bg-inset)';
    document.body.appendChild(probe);
    const inset = getComputedStyle(probe).backgroundColor;
    probe.remove();
    return [well ? getComputedStyle(well).backgroundColor : '', inset];
  }, id);
}

for (const theme of GATE_THEMES) {
  test(`${ROUTE}: the Hive editor has no serious or critical violation in ${theme ?? 'light'}`, async ({ page }) => {
    await page.goto(ROUTE);
    await page.waitForLoadState('networkidle');
    await waitForEditors(page);
    await pinAppearance(page, theme);
    // The hook repaints on the `data-theme` change; give Monaco a frame to restyle its tokens.
    await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => resolve(null))));

    for (const id of EDITORS) {
      const [well, inset] = await wellAndInset(page, id);
      expect({ id, well }).toEqual({ id, well: inset });
    }
    expect(await blockingAxeLines(page, 'main')).toEqual([]);
  });
}
