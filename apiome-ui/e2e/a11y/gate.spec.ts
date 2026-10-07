import fs from 'node:fs';
import path from 'node:path';
import { test, expect, type Page } from '@playwright/test';

import { A11Y_ROUTES, type A11yRoute } from './routes';
import { FIXTURE_ROOT, GATE_THEMES, blockingAxeLines, mountMarkup, pinAppearance, readFixture } from '../support/a11y';

/**
 * The axe gate — HIVE-10.2 (#5338), `docs/mockups/DESIGN.md` §9.
 *
 * For every `fixtures` and `route` entry of the ledger (`routes.ts`), in light, dark and high
 * contrast, at comfortable density and the default font scale: zero serious or critical axe
 * violations at WCAG 2.2 A/AA. `spec` entries run as their own files under the same config.
 *
 * Fixture entries gate every dump in their directory (or the listed files), so a state a
 * redesign ticket dumped — empty, error, deleted — is held to the same bar as the happy path.
 *
 * The suite also probes the 44 px pointer targets of `.hit-target` in a real layout engine: the
 * point 21 px out from a small control's centre must still reach that control (or another
 * control that sits there), never the page behind it.
 */

/** The width DESIGN.md §5 forbids horizontal document scroll at, and the gate's viewport. */
const VIEWPORT = { width: 1280, height: 900 };

/** The files a `fixtures` subject gates. */
function fixtureFiles(route: A11yRoute): string[] {
  if (route.subject.kind !== 'fixtures') return [];
  if (route.subject.files) return [...route.subject.files];
  return fs
    .readdirSync(path.join(FIXTURE_ROOT, route.subject.dir))
    .filter((file) => file.endsWith('.html'))
    .sort();
}

/** A readable theme name for test titles. */
const themeName = (theme: string | null) => theme ?? 'light';

/**
 * Open a live route and let it settle.
 *
 * @param page The page.
 * @param route The path to load.
 */
async function openRoute(page: Page, route: string): Promise<void> {
  await page.goto(route);
  await page.waitForLoadState('networkidle');
}

test.use({ viewport: VIEWPORT });

for (const route of A11Y_ROUTES) {
  const subject = route.subject;
  if (subject.kind === 'spec') continue;

  test.describe(`axe gate: ${route.id}`, () => {
    if (subject.kind === 'fixtures') {
      for (const file of fixtureFiles(route)) {
        for (const theme of GATE_THEMES) {
          test(`${subject.dir}/${file} has no serious or critical violation in ${themeName(theme)}`, async ({ page }) => {
            await mountMarkup(page, readFixture(subject.dir, file));
            await pinAppearance(page, theme);
            expect(await blockingAxeLines(page, '#a11y-mount')).toEqual([]);
          });
        }
      }
      return;
    }

    for (const theme of GATE_THEMES) {
      test(`${subject.path} has no serious or critical violation in ${themeName(theme)}`, async ({ page }) => {
        await openRoute(page, subject.path);
        await pinAppearance(page, theme);
        expect(await blockingAxeLines(page)).toEqual([]);
      });
    }
  });
}

test.describe('pointer targets (.hit-target)', () => {
  /**
   * Probe every visible `.hit-target` on the page at the points `reach` px left, right, above and
   * below its centre. The hit area is designed to claim only *empty* space — a neighbour's visible
   * box always wins — so a point is a miss only when it lands on an ancestor's own background
   * (the container the control sits in), which is exactly where the hit area should have been.
   * A wrapping `<label>` counts as a hit: pressing it activates the control.
   *
   * @returns One line per miss.
   */
  async function probeHitTargets(page: Page, reach: number): Promise<string[]> {
    return page.evaluate((distance) => {
      const misses: string[] = [];
      const targets = Array.from(document.querySelectorAll<HTMLElement>('.hit-target'));
      for (const target of targets) {
        const box = target.getBoundingClientRect();
        if (box.width === 0 || box.height === 0) continue;
        const style = getComputedStyle(target);
        if (style.visibility === 'hidden' || style.pointerEvents === 'none') continue;
        if ((target as HTMLButtonElement).disabled || target.getAttribute('aria-disabled') === 'true') continue;
        target.scrollIntoView({ block: 'center', inline: 'center' });
        const rect = target.getBoundingClientRect();
        const cx = rect.left + rect.width / 2;
        const cy = rect.top + rect.height / 2;
        const points: Array<[number, number]> = [
          [cx - Math.max(distance, rect.width / 2 - 1), cy],
          [cx + Math.max(distance, rect.width / 2 - 1), cy],
          [cx, cy - Math.max(distance, rect.height / 2 - 1)],
          [cx, cy + Math.max(distance, rect.height / 2 - 1)],
        ];
        for (const [x, y] of points) {
          if (x < 0 || y < 0 || x >= innerWidth || y >= innerHeight) continue;
          const hit = document.elementFromPoint(x, y) as HTMLElement | null;
          if (!hit) continue;
          if (hit === target || target.contains(hit)) continue;
          // Another element's visible box: the hit area yields to it by design.
          if (!hit.contains(target)) continue;
          // The control's own label activates it.
          if (hit.closest('label')?.contains(target)) continue;
          const name = target.getAttribute('aria-label') || target.textContent?.trim().slice(0, 30) || target.tagName;
          misses.push(`${name} @ (${Math.round(x - cx)}, ${Math.round(y - cy)}) → ${hit.tagName.toLowerCase()}.${hit.className}`.slice(0, 160));
          break;
        }
      }
      return misses;
    }, reach);
  }

  test('every small control on the gallery reaches 44 px in comfortable density', async ({ page }) => {
    await openRoute(page, '/design-system');
    await pinAppearance(page, null, { density: 'comfortable' });
    // 21 px out from the centre: just inside a 44 px square.
    expect(await probeHitTargets(page, 21)).toEqual([]);
  });

  test('targets fall back to the 24 px AA floor in compact density', async ({ page }) => {
    await openRoute(page, '/design-system');
    await pinAppearance(page, null, { density: 'compact' });
    expect(await probeHitTargets(page, 11)).toEqual([]);
    const size = await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--target-min').trim());
    expect(size).toBe('1.5rem');
  });
});
