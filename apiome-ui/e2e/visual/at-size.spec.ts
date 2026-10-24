import { expect, test } from '@playwright/test';

import { parityRoute, type FirstRowBudget } from './routes';
import { collectSide, judgeFixtureFirstRow, openMockup } from './support/harness';

/**
 * The first-row budget at size — RC6-H6 (#6213).
 *
 * The parity gate measures the Catalog and the versions table from fixtures with a handful of
 * rows. A realistic tenant has a thousand catalog items and projects with hundreds of revisions,
 * so `tests/rc6-list-budgets-*.test.tsx` renders the real screens at that size and dumps them into
 * `e2e/fixtures/hive-at-size/`:
 *
 *     AT_SIZE_FIXTURE_DUMP=1 npx jest tests/rc6-list-budgets -t fixture
 *
 * This mounts each dump at its route's mockup width and holds it to the same budget the route
 * carries in `routes.ts` (allowance included): what sits above the first row must not grow with
 * the list — no count-driven banner, no unpaged block of cards before the rows.
 */

const DIR = 'hive-at-size';

/** How far the first card may move between three items and a thousand (sub-pixel text metrics). */
const CARDS_TOLERANCE_PX = 4;

const TABLES: Array<{ name: string; route: string; file: string }> = [
  { name: 'the Catalog table with 1,000 items', route: 'catalog', file: 'catalog-table-1000.html' },
  { name: 'the versions table with 300 revisions', route: 'versions', file: 'versions-300.html' },
];

for (const { name, route, file } of TABLES) {
  test(`${name} keeps its first row within the route's budget`, async ({ page }) => {
    const entry = parityRoute(route);
    if (!entry.firstRow) throw new Error(`visual-parity: route "${route}" carries no first-row budget`);
    await openMockup(page, entry.mockup, { theme: null });
    const width = (await collectSide(page, 'mockup')).scope.width;

    const verdict = await judgeFixtureFirstRow(page, { kind: 'fixture', dir: DIR, file }, entry.firstRow, width);
    // A stale allowance means the fixture is *better* than the route's allowance needs, which is
    // the route's business (the parity gate reports it), not a failure at size.
    expect(['within-budget', 'allowed-overrun', 'stale-allowance'], `${name}: ${verdict.detail}`).toContain(
      verdict.status
    );
  });
}

/**
 * The cards view is not a parity route — its first card sits under the select-all line and a
 * paradigm heading by design — so what is held at size is that it does not move: the first card of
 * a thousand lands where the first card of three does, in the same returning-reader state.
 */
test('the Catalog cards with 1,000 items keep their first card where three items put it', async ({ page }) => {
  const entry = parityRoute('catalog');
  if (!entry.firstRow) throw new Error('visual-parity: route "catalog" carries no first-row budget');
  await openMockup(page, entry.mockup, { theme: null });
  const width = (await collectSide(page, 'mockup')).scope.width;
  const budget: FirstRowBudget = { ...entry.firstRow, selector: '.page-body [data-testid="catalog-card"]' };

  const few = await judgeFixtureFirstRow(page, { kind: 'fixture', dir: DIR, file: 'catalog-cards-3.html' }, budget, width);
  const many = await judgeFixtureFirstRow(
    page,
    { kind: 'fixture', dir: DIR, file: 'catalog-cards-1000.html' },
    budget,
    width
  );
  expect(few.topPx, few.detail).not.toBeNull();
  expect(many.topPx, many.detail).not.toBeNull();
  expect(Math.abs((many.topPx as number) - (few.topPx as number))).toBeLessThanOrEqual(CARDS_TOLERANCE_PX);
});
