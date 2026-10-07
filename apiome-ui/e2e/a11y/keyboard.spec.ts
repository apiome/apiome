import { test, expect, type Locator, type Page } from '@playwright/test';

import { A11Y_ROUTES } from './routes';
import { pinAppearance } from '../support/a11y';

/**
 * Keyboard gate — HIVE-10.2 (#5338), `docs/mockups/DESIGN.md` §9 "all overlays trap focus and
 * restore it" and WCAG 2.1.2 "no keyboard trap".
 *
 * - **No trap on any page:** on every live route of the ledger, repeated Tab keeps moving focus to
 *   a new element and never sticks on one, until it has walked the page or cycled back.
 * - **Overlays trap and restore:** the drawer, a dialog and the command palette open from the
 *   keyboard, keep Tab and Shift+Tab inside, close on Escape and return focus to their trigger.
 *
 * The task-by-task keyboard paths these checks stand behind are documented in
 * `apiome-docs/docs/reference/keyboard.md`.
 */

test.use({ viewport: { width: 1280, height: 900 } });

/** A short, stable description of the focused element. */
async function focusedKey(page: Page): Promise<string> {
  return page.evaluate(() => {
    const el = document.activeElement as HTMLElement | null;
    if (!el || el === document.body) return 'body';
    const path: string[] = [];
    let node: Element | null = el;
    while (node && node !== document.body && path.length < 6) {
      const index = node.parentElement ? Array.from(node.parentElement.children).indexOf(node) : 0;
      path.unshift(`${node.tagName.toLowerCase()}:${index}`);
      node = node.parentElement;
    }
    return path.join('>');
  });
}

/** Whether focus is inside `container`. */
async function focusInside(container: Locator): Promise<boolean> {
  return container.evaluate((node) => node.contains(document.activeElement));
}

const LIVE_ROUTES = A11Y_ROUTES.flatMap((route) => (route.subject.kind === 'route' ? [route.subject.path] : []));

test.describe('no keyboard trap', () => {
  for (const path of LIVE_ROUTES) {
    test(`Tab keeps moving through ${path}`, async ({ page }) => {
      await page.goto(path);
      await page.waitForLoadState('networkidle');
      await pinAppearance(page, null);
      await page.locator('body').click({ position: { x: 1, y: 1 } });

      const seen = new Set<string>();
      let previous = await focusedKey(page);
      for (let press = 0; press < 40; press += 1) {
        await page.keyboard.press('Tab');
        const current = await focusedKey(page);
        // Focus must move on every press; staying put is the definition of a trap.
        expect(current, `Tab ${press + 1} left focus on ${current}`).not.toBe(previous);
        if (seen.has(current) && current !== 'body') break; // walked the page and cycled back
        seen.add(current);
        previous = current;
      }
      expect(seen.size).toBeGreaterThan(1);
    });
  }
});

test.describe('overlays trap focus and restore it', () => {
  /**
   * Open an overlay from its trigger with the keyboard, check the trap, close with Escape and
   * check focus came home.
   */
  async function checkOverlay(page: Page, trigger: Locator, overlay: Locator): Promise<void> {
    await trigger.focus();
    await page.keyboard.press('Enter');
    await expect(overlay).toBeVisible();
    await expect.poll(() => focusInside(overlay)).toBe(true);

    for (let press = 0; press < 15; press += 1) {
      await page.keyboard.press('Tab');
      expect(await focusInside(overlay), `Tab ${press + 1} escaped the overlay`).toBe(true);
    }
    for (let press = 0; press < 5; press += 1) {
      await page.keyboard.press('Shift+Tab');
      expect(await focusInside(overlay), `Shift+Tab ${press + 1} escaped the overlay`).toBe(true);
    }

    await page.keyboard.press('Escape');
    await expect(overlay).toBeHidden();
    await expect(trigger).toBeFocused();
  }

  test.beforeEach(async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
  });

  test('the drawer', async ({ page }) => {
    await page.goto('/design-system');
    await page.waitForLoadState('networkidle');
    await checkOverlay(page, page.getByRole('button', { name: 'Open drawer' }), page.getByRole('dialog'));
  });

  test('a dialog', async ({ page }) => {
    await page.goto('/design-system');
    await page.waitForLoadState('networkidle');
    const trigger = page.locator('#dialogs').getByRole('button').first();
    await trigger.scrollIntoViewIfNeeded();
    await checkOverlay(page, trigger, page.locator('[role="dialog"], [role="alertdialog"]').first());
  });

  test('the command palette', async ({ page }) => {
    await page.goto('/design-system/command-palette');
    await page.waitForLoadState('networkidle');
    await checkOverlay(page, page.getByTestId('open-palette'), page.getByTestId('command-palette'));
  });
});
