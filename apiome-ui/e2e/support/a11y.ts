/**
 * Shared accessibility helpers for the Playwright suites — HIVE-10.2 (#5338).
 *
 * `docs/mockups/DESIGN.md` §9 asks for WCAG 2.2 AA everywhere and zero serious/critical axe
 * violations in every theme. Before this module each spec carried its own copy of the tag list,
 * the theme pinning and the serious/critical filter, and the tag list stopped at WCAG 2.1 — so
 * axe's WCAG 2.2 `target-size` rule never ran. New specs import from here.
 */

import fs from 'node:fs';
import path from 'node:path';
import AxeBuilder from '@axe-core/playwright';
import type { Page } from '@playwright/test';

/** One axe run, typed from the AxeBuilder actually in use (its nested axe-core, not the hoisted one). */
type AxeResults = Awaited<ReturnType<AxeBuilder['analyze']>>;
/** One violation in {@link AxeResults}. */
type Result = AxeResults['violations'][number];

/** WCAG 2.0, 2.1 and 2.2 Level A/AA — the conformance target of DESIGN.md §9. */
export const WCAG_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'];

/** The themes the CI gate runs every route in: light (`null`, the `:root` default), dark, high contrast. */
export const GATE_THEMES: ReadonlyArray<string | null> = [null, 'dark', 'high-contrast'];

/** Themes whose base appearance is dark; `ThemeProvider` adds next-themes' `.dark` class for these. */
const DARK_APPEARANCE = new Set(['dark', 'high-contrast', 'blueprint', 'solarized', 'nord', 'darcula']);

/** Committed fixture dumps (`e2e/fixtures/<dir>/<file>`). */
export const FIXTURE_ROOT = path.resolve(__dirname, '..', 'fixtures');

/** CSS that stops every transition, so axe never samples a colour mid theme-swap. */
const FREEZE_MOTION = '*,*::before,*::after{transition:none!important;animation:none!important}';

/** Appearance pins for {@link pinAppearance}. */
export interface AppearanceOptions {
  /** `data-density`; defaults to `comfortable`. */
  density?: 'comfortable' | 'compact';
  /** `data-font-scale`; defaults to `md`. */
  fontScale?: string;
}

/**
 * Pin the appearance `<html>` carries, exactly as `ThemeProvider` and the preferences boot
 * script would: `data-theme` + `data-theme-choice`, the `.dark` class for a dark-based theme,
 * density and font scale. Motion is frozen and one frame is awaited, so what axe reads is final.
 *
 * @param page The page to pin.
 * @param theme A theme id, or `null` for the light default.
 * @param options Density and font scale.
 */
export async function pinAppearance(page: Page, theme: string | null, options: AppearanceOptions = {}): Promise<void> {
  await page.evaluate(
    ({ chosen, dark, density, fontScale, freeze }) => {
      const root = document.documentElement;
      if (chosen) {
        root.setAttribute('data-theme', chosen);
        root.setAttribute('data-theme-choice', chosen);
      } else {
        root.removeAttribute('data-theme');
        root.removeAttribute('data-theme-choice');
      }
      root.classList.toggle('dark', dark);
      root.style.colorScheme = dark ? 'dark' : 'light';
      root.setAttribute('data-density', density);
      root.setAttribute('data-font-scale', fontScale);
      if (!document.getElementById('a11y-frozen')) {
        const style = document.createElement('style');
        style.id = 'a11y-frozen';
        style.textContent = freeze;
        document.head.appendChild(style);
      }
    },
    {
      chosen: theme,
      dark: theme !== null && DARK_APPEARANCE.has(theme),
      density: options.density ?? 'comfortable',
      fontScale: options.fontScale ?? 'md',
      freeze: FREEZE_MOTION,
    },
  );
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => resolve(null))));
}

/**
 * Read one committed fixture dump.
 *
 * @param dir The fixture directory, e.g. `hive-catalog`.
 * @param file The file inside it, e.g. `table.html`.
 * @returns The markup.
 */
export function readFixture(dir: string, file: string): string {
  return fs.readFileSync(path.join(FIXTURE_ROOT, dir, file), 'utf8');
}

/**
 * Mount fixture markup into `/login`, which compiles the real `globals.css` and needs no session.
 *
 * The markup goes inside a `<main>` (as the app's shell would put a page), so landmark rules read
 * it the way they read the real route.
 *
 * @param page The page.
 * @param markup The fixture's HTML.
 */
export async function mountMarkup(page: Page, markup: string): Promise<void> {
  await page.goto('/login');
  await page.waitForLoadState('networkidle');
  await page.evaluate((html) => {
    document.body.innerHTML = `<main id="a11y-mount" style="min-height:100vh;background:var(--bg-canvas)">${html}</main>`;
  }, markup);
}

/**
 * The violations the gate blocks on: serious and critical.
 *
 * @param results An axe run.
 * @returns Only the blocking violations.
 */
export function blockingViolations(results: AxeResults): Result[] {
  return results.violations.filter((violation) => violation.impact === 'serious' || violation.impact === 'critical');
}

/**
 * Violations as readable lines for an assertion message: rule, help, and the first targets.
 *
 * @param violations Axe violations.
 * @returns One line per violation.
 */
export function formatViolations(violations: Result[]): string[] {
  return violations.map(
    (violation) =>
      `${violation.id} (${violation.impact}): ${violation.help} — ${violation.nodes
        .slice(0, 3)
        .map((node) => node.target.join(' '))
        .join(' | ')}`,
  );
}

/**
 * Run axe over a page (or one region of it) at the gate's tags.
 *
 * @param page The page.
 * @param scope A selector to limit the run to, or omit for the whole document.
 * @returns The blocking violations, formatted.
 */
export async function blockingAxeLines(page: Page, scope?: string): Promise<string[]> {
  let builder = new AxeBuilder({ page }).withTags(WCAG_TAGS);
  if (scope) builder = builder.include(scope);
  return formatViolations(blockingViolations(await builder.analyze()));
}
