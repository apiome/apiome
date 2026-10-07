import { test, expect, type Page } from '@playwright/test';

/**
 * Motion in a real layout engine — HIVE-10.3 (#5339), `docs/mockups/DESIGN.md` §3.4.
 *
 * `tests/motion-pass.test.ts` holds the stylesheets to the §3.4 durations; this suite checks
 * what the browser actually runs when an overlay opens:
 *
 * - no one-shot animation is longer than 260 ms, and the dialog rises (`hive-dialog-rise`);
 * - with the Reduce motion preference *or* the OS setting, every running animation has a zero
 *   duration and the dialog is already where it comes to rest — no jump after the fact;
 * - a closing scrim does not swallow a click aimed at the page behind it.
 */

test.use({ viewport: { width: 1280, height: 900 } });

/** The gallery's first dialog trigger. */
const trigger = (page: Page) => page.locator('#dialogs').getByRole('button', { name: 'Destructive confirm' });

/** Durations of the finite animations running in the document, as `name: ms`. */
async function finiteAnimations(page: Page): Promise<Array<{ name: string; ms: number }>> {
  return page.evaluate(() =>
    document
      .getAnimations()
      .map((animation) => {
        const timing = animation.effect?.getComputedTiming();
        return {
          name: (animation as CSSAnimation).animationName ?? (animation as CSSTransition).transitionProperty ?? '?',
          ms: Number(timing?.duration ?? 0),
          iterations: Number(timing?.iterations ?? 1),
        };
      })
      .filter((animation) => Number.isFinite(animation.iterations))
      .map(({ name, ms }) => ({ name, ms })),
  );
}

async function openGallery(page: Page): Promise<void> {
  await page.goto('/design-system/hive');
  await page.waitForLoadState('networkidle');
  await trigger(page).scrollIntoViewIfNeeded();
}

test('opening a dialog runs nothing longer than 260 ms, and the dialog rises', async ({ page }) => {
  await openGallery(page);
  await trigger(page).click();
  const running = await finiteAnimations(page);
  expect(running.map((animation) => animation.name)).toContain('hive-dialog-rise');
  expect(running.filter((animation) => animation.ms > 260)).toEqual([]);
});

for (const [label, setUp] of [
  [
    'the Reduce motion preference',
    async (page: Page) => {
      await page.evaluate(() => document.documentElement.setAttribute('data-motion', 'reduce'));
    },
  ],
  [
    'the operating-system setting',
    async (page: Page) => {
      await page.emulateMedia({ reducedMotion: 'reduce' });
    },
  ],
] as const) {
  test(`${label} makes opening a dialog instant, with no jump`, async ({ page }) => {
    await openGallery(page);
    await setUp(page);
    await trigger(page).click();
    const dialog = page.getByRole('alertdialog');
    await expect(dialog).toBeVisible();

    expect((await finiteAnimations(page)).filter((animation) => animation.ms > 0)).toEqual([]);
    // Where it is the moment it opens is where it stays.
    const first = await dialog.boundingBox();
    await page.waitForTimeout(300);
    expect(await dialog.boundingBox()).toEqual(first);
    expect(await dialog.evaluate((node) => getComputedStyle(node).opacity)).toBe('1');
  });
}

test('a closing scrim lets a click through to the page', async ({ page }) => {
  await openGallery(page);
  await trigger(page).click();
  await expect(page.getByRole('alertdialog')).toBeVisible();
  await page.keyboard.press('Escape');

  // Straight after Escape the scrim may still be fading out; whatever is under the trigger's
  // centre must not be it.
  const box = await trigger(page).boundingBox();
  const hit = await page.evaluate(
    ([x, y]) => {
      const element = document.elementFromPoint(x, y) as HTMLElement | null;
      return element?.className.toString() ?? '';
    },
    [box!.x + box!.width / 2, box!.y + box!.height / 2],
  );
  expect(hit).not.toContain('hive-overlay');
});
