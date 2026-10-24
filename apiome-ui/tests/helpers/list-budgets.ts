/**
 * The time budgets RC6-H6 (#6213) holds the Catalog and the versions table to at size —
 * 1,000 catalog items, 300 revisions — measured in jsdom on the CI runner.
 *
 * jsdom does the same React work a browser does without painting, and more slowly, so a step inside
 * these numbers here is inside them in Chromium. The rules are printed on the *Visual parity*
 * reference page (`apiome-docs/docs/reference/visual-parity.md`).
 */

import fs from 'node:fs';
import path from 'node:path';

/**
 * Time ceilings, in milliseconds, in jsdom on the CI runner, with jest running suites in parallel.
 *
 * jsdom timings swing with whatever else the worker is doing, so these are backstops against a
 * gross regression; the exact guard is that a screen at size mounts one page of rows (each suite
 * asserts the count). Measured idle on a developer machine (2026-10-24), at size: first row
 * 150–330 ms, filter 100–160 ms, sort ≈ 120 ms — and before paging, a 2.4–2.6 s first row.
 */
export const LIST_BUDGET_MS = {
  /** From mount to the first row of data on screen (the read itself is mocked). */
  firstRow: 3000,
  /** From a filter keystroke (or chip) to the narrowed list on screen. */
  filter: 1000,
  /** From a header click to the re-ordered list on screen. */
  sort: 1000,
} as const;

/**
 * Time an async step.
 *
 * @param step The work to time.
 * @returns Its duration in milliseconds.
 */
export async function timed(step: () => Promise<void>): Promise<number> {
  const start = performance.now();
  await step();
  return performance.now() - start;
}

/** Where the at-size fixtures go: `e2e/fixtures/hive-at-size/`, mounted by `e2e/visual/at-size.spec.ts`. */
const AT_SIZE_FIXTURE_DIR = path.join(__dirname, '..', '..', 'e2e', 'fixtures', 'hive-at-size');

/**
 * Write one at-size fixture — the screen's `.page`, as rendered — when `AT_SIZE_FIXTURE_DUMP=1`;
 * otherwise only check there is something to write, so a screen that stops rendering fails here.
 *
 *     AT_SIZE_FIXTURE_DUMP=1 npx jest tests/rc6-list-budgets -t fixture
 *
 * @param name The file name, without `.html`.
 */
export function writeAtSizeFixture(name: string): void {
  const html = (document.querySelector('.page') as HTMLElement | null)?.outerHTML ?? '';
  expect(html.length).toBeGreaterThan(0);
  if (process.env.AT_SIZE_FIXTURE_DUMP !== '1') return;
  fs.mkdirSync(AT_SIZE_FIXTURE_DIR, { recursive: true });
  fs.writeFileSync(path.join(AT_SIZE_FIXTURE_DIR, `${name}.html`), `${html}\n`);
}
