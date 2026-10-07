/**
 * `<Screenshot/>` in the browser — DOCS-1.3 (#5620): it swaps with the theme toggle, links to the
 * full-size image for the current theme, and passes axe at WCAG 2.2 AA.
 */
import AxeBuilder from '@axe-core/playwright';
import {expect, test} from '@playwright/test';

/** The page that shows an example screenshot. */
const PAGE = 'admin/contribute-to-the-docs';

/** The example's figure. */
const FIGURE = 'figure[data-screenshot-id="catalog"]';

test('shows the light capture, and the dark one after the theme toggle', async ({page}) => {
  await page.emulateMedia({colorScheme: 'light'});
  await page.goto(PAGE);
  const figure = page.locator(FIGURE);
  const visible = figure.locator('img:visible');

  await expect(visible).toHaveCount(1);
  await expect(visible).toHaveAttribute('src', /catalog\.light\.png$/);
  await expect(visible).toHaveAttribute('loading', 'lazy');
  await expect(figure.locator('a')).toHaveAttribute('href', /catalog\.light\.png$/);
  await expect(figure.locator('figcaption')).toContainText('/ade/dashboard/catalog');

  await page.getByRole('button', {name: /dark mode|light mode|system mode/i}).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await expect(visible).toHaveAttribute('src', /catalog\.dark\.png$/);
  await expect(figure.locator('a')).toHaveAttribute('href', /catalog\.dark\.png$/);
});

test('has alt text and no serious accessibility violations, in both themes', async ({page}) => {
  for (const colorScheme of ['light', 'dark'] as const) {
    await page.emulateMedia({colorScheme});
    await page.goto(PAGE);
    await expect(page.locator(`${FIGURE} img:visible`)).toHaveAttribute('alt', /Catalog page/);
    const results = await new AxeBuilder({page})
      .include(FIGURE)
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
      .analyze();
    const blocking = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical');
    expect(blocking.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
  }
});
