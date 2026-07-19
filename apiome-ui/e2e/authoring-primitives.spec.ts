import { test, expect } from '@playwright/test';

/**
 * Authoring primitive visual references (UXE-1.3).
 *
 * Screenshots the primitive reference gallery once per theme, which is what
 * makes the acceptance criterion "light, dark, high-contrast and reduced-motion
 * references pass" checkable rather than a matter of opinion.
 *
 * The gallery renders fixed fixtures from `@lib/authoring/reference-fixtures`
 * with no timestamps or randomness, so a diff here is always a styling change
 * and never a data change.
 *
 * Baselines are generated with `yarn test:e2e:update-snapshots` against a
 * running, authenticated app. These tests are skipped automatically when the
 * route redirects to login, so an unauthenticated CI run reports "skipped"
 * rather than a false failure.
 */

const GALLERY_ROUTE = '/ade/authoring/reference';

/** Themes the gallery must render correctly in. */
const THEMES = ['light', 'dark', 'high-contrast'] as const;

/**
 * Apply a theme the way `ThemeProvider` does, then settle.
 *
 * The provider stamps `data-theme` on both `html` and `body` and adds the
 * theme's class, so a test that only sets one of them would not exercise the
 * high-contrast selectors in `globals.css`.
 *
 * @param page - Playwright page.
 * @param theme - Theme id.
 */
async function applyTheme(page: import('@playwright/test').Page, theme: string) {
  await page.evaluate((id) => {
    const dark = ['dark', 'high-contrast'].includes(id);
    [document.documentElement, document.body].forEach((element) => {
      element.setAttribute('data-theme', id);
      element.classList.toggle('dark', dark);
      element.classList.add(`theme-${id}`);
    });
  }, theme);

  await page.waitForTimeout(300);
}

/**
 * Open the gallery, skipping the test when the app is not authenticated.
 *
 * @param page - Playwright page.
 */
async function openGallery(page: import('@playwright/test').Page) {
  await page.goto(GALLERY_ROUTE);
  await page.waitForLoadState('networkidle');

  const gallery = page.getByTestId('authoring-reference-gallery');
  test.skip(
    (await gallery.count()) === 0,
    'Authoring reference gallery needs an authenticated session.'
  );

  await expect(gallery).toBeVisible();
}

test.describe('Authoring primitive references', () => {
  for (const theme of THEMES) {
    test(`primitive gallery in the ${theme} theme`, async ({ page }) => {
      await page.setViewportSize({ width: 1440, height: 900 });
      await openGallery(page);
      await applyTheme(page, theme);

      await expect(page).toHaveScreenshot(`authoring-primitives-${theme}.png`, {
        maxDiffPixels: 100,
        fullPage: true,
      });
    });
  }

  test('primitive gallery with reduced motion', async ({ page }) => {
    // Reduced motion must not change layout or hide any state — it removes
    // movement only (roadmap section 27.3), so this baseline should match the
    // light one modulo any in-flight transition.
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.setViewportSize({ width: 1440, height: 900 });
    await openGallery(page);
    await applyTheme(page, 'light');

    await expect(page).toHaveScreenshot('authoring-primitives-reduced-motion.png', {
      maxDiffPixels: 100,
      fullPage: true,
    });
  });

  test('primitive gallery reflows at 320 CSS pixels', async ({ page }) => {
    // Section 27.4 requires reflow at 320px with no horizontal scrolling.
    await page.setViewportSize({ width: 320, height: 800 });
    await openGallery(page);

    const overflows = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1
    );
    expect(overflows).toBe(false);

    await expect(page).toHaveScreenshot('authoring-primitives-320.png', {
      maxDiffPixels: 100,
      fullPage: true,
    });
  });

  test('status is never conveyed by colour alone', async ({ page }) => {
    await openGallery(page);

    // Every toned element must carry readable text; a bare coloured chip would
    // be invisible to a greyscale or colour-blind reader.
    const untoned = await page
      .locator('[data-tone]')
      .evaluateAll((nodes) => nodes.filter((node) => !(node.textContent ?? '').trim()).length);

    expect(untoned).toBe(0);
  });

  test('the gallery is not reachable from product navigation', async ({ page }) => {
    // It is a development aid, so it must stay out of the shell's secondary
    // navigation even though its route resolves.
    await openGallery(page);

    const navLink = page.locator(`nav a[href*="${GALLERY_ROUTE}"]`);
    expect(await navLink.count()).toBe(0);
  });
});
