import { expect, test } from '@playwright/test';

import { FIRST_DATA_ROW } from './landmarks';
import { firstRowBudget, parityRoute } from './routes';
import { collectSide, judgeFixtureFirstRow, openMockup } from './support/harness';

/**
 * The first-row budget's self-test (HIVE-13.3, #5616).
 *
 * A budget that never fails is a number nobody checks, so #5616 asks for proof that it tells a
 * cluttered page from a quiet one: **"harness fails on the pre-quiet-pass Catalog fixture and
 * passes on the post-11.6 one"**. Both are frozen copies in `e2e/fixtures/hive-first-row/`
 * (see its README), mounted at the Catalog mockup's page width and held to the plain list
 * budget — no allowance, because an allowance is exactly what this test must not lean on.
 *
 * Runs in the `light` project only: where a row lands does not depend on the palette.
 */

/** The fixture folder holding the frozen Catalog dumps. */
const DIR = 'hive-first-row';

/** The Catalog budget without its allowance: the bar the quiet pass was built to clear. */
const CATALOG_BUDGET = firstRowBudget('list', FIRST_DATA_ROW);

test('the first-row budget fails the pre-quiet-pass Catalog and passes the HIVE-11.6 one', async ({
  page,
}) => {
  await openMockup(page, parityRoute('catalog').mockup, { theme: null });
  const width = (await collectSide(page, 'mockup')).scope.width;

  const before = await judgeFixtureFirstRow(
    page,
    { kind: 'fixture', dir: DIR, file: 'catalog-pre-quiet-pass.html' },
    CATALOG_BUDGET,
    width
  );
  expect(before.status, `pre-quiet-pass Catalog: ${before.detail}`).toBe('over-budget');
  expect(before.passed).toBe(false);

  const after = await judgeFixtureFirstRow(
    page,
    { kind: 'fixture', dir: DIR, file: 'catalog-quiet-pass.html' },
    CATALOG_BUDGET,
    width
  );
  expect(after.status, `HIVE-11.6 Catalog: ${after.detail}`).toBe('within-budget');
  expect(after.passed).toBe(true);
});
