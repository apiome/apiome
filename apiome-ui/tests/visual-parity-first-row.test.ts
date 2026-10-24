/**
 * The first-row-of-data budget (HIVE-13.3, #5616).
 *
 * `e2e/visual/parity.spec.ts` measures where each page's first row of data lands at
 * 1440 × 900, and `e2e/visual/first-row.spec.ts` proves the budget tells the pre-quiet-pass
 * Catalog from the HIVE-11.6 one. What neither can state is the rules themselves, because
 * every input they have is a real measurement. So the rules live here:
 *
 *   * every pairing either declares a budget drawn from the three PROPOSALS.md budgets, or is
 *     exempt with a reason — a new route cannot slip in unmeasured;
 *   * an allowance is a ratchet: the row may not pass its ceiling, and a page back within
 *     budget fails until its allowance is deleted;
 *   * a selector that matches nothing fails rather than passing vacuously;
 *   * the measurement reaches the report, the CI summary and a failure message.
 */

import { FIRST_DATA_ROW, LANDMARK_IDS } from '../e2e/visual/landmarks';
import { firstRowCell, parityMarkdownSummary, parityReportHtml } from '../e2e/visual/report';
import {
  FIRST_ROW_BUDGET_PX,
  FIRST_ROW_EXEMPT,
  FIRST_ROW_EXEMPT_REASONS,
  PARITY_ROUTES,
  firstRowBudget,
  parityRoute,
  type FirstRowBudget,
} from '../e2e/visual/routes';
import {
  explainReport,
  judgeFirstRow,
  scoreParity,
  type FirstRowVerdict,
  type ParityReport,
} from '../e2e/visual/score';
import type { ParitySignature } from '../e2e/visual/signature';

/** A plain list budget with no allowance. */
const LIST: FirstRowBudget = firstRowBudget('list');

/** A list budget with a known overrun up to 390 px. */
const ALLOWED: FirstRowBudget = firstRowBudget('list', FIRST_DATA_ROW, {
  ceilingPx: 390,
  reason: 'a toolbar row added after the quiet pass',
});

describe('the budgets', () => {
  it('are the three PROPOSALS.md sets: list 360, detail 560, Versions 700', () => {
    expect(FIRST_ROW_BUDGET_PX).toEqual({ list: 360, detail: 560, versions: 700 });
  });

  it('default to the first DataTable body row inside the page body', () => {
    expect(LIST).toEqual({ selector: '.page-body tbody tr[data-row-id]', budgetPx: 360 });
    expect(firstRowBudget('detail', '.x').selector).toBe('.x');
    expect('allowance' in LIST).toBe(false);
  });
});

describe('the route map', () => {
  const budgets = new Set<number>(Object.values(FIRST_ROW_BUDGET_PX));

  it('gives every pairing either a budget or an exemption, never both', () => {
    const neither = PARITY_ROUTES.filter((r) => !r.firstRow && !FIRST_ROW_EXEMPT[r.id]).map(
      (r) => r.id
    );
    const both = PARITY_ROUTES.filter((r) => r.firstRow && FIRST_ROW_EXEMPT[r.id]).map(
      (r) => r.id
    );
    expect(neither).toEqual([]);
    expect(both).toEqual([]);
  });

  it('exempts only routes it has, for a reason it can explain', () => {
    for (const [id, reason] of Object.entries(FIRST_ROW_EXEMPT)) {
      expect(() => parityRoute(id)).not.toThrow();
      expect(FIRST_ROW_EXEMPT_REASONS[reason]).toBeTruthy();
    }
  });

  it('holds every route to one of the three budgets, not a number picked to fit', () => {
    const custom = PARITY_ROUTES.filter((r) => r.firstRow && !budgets.has(r.firstRow.budgetPx)).map(
      (r) => `${r.id}: ${r.firstRow?.budgetPx}`
    );
    expect(custom).toEqual([]);
  });

  it('gives every allowance a ceiling above its budget and a reason', () => {
    const bad = PARITY_ROUTES.filter((r) => {
      const allowance = r.firstRow?.allowance;
      if (!allowance || !r.firstRow) return false;
      return allowance.ceilingPx <= r.firstRow.budgetPx || allowance.reason.trim() === '';
    }).map((r) => r.id);
    expect(bad).toEqual([]);
  });

  it('holds Published, the review baseline, to the list budget with no allowance', () => {
    expect(parityRoute('published').firstRow).toEqual(LIST);
  });

  it('exempts the Analytics page, which PROPOSALS.md says keeps its full strip', () => {
    expect(FIRST_ROW_EXEMPT['mcp-analytics']).toBe('analytics');
  });
});

describe('judging a measurement', () => {
  it('passes a row at or above the budget', () => {
    expect(judgeFirstRow(LIST, 216)).toMatchObject({ status: 'within-budget', passed: true });
    expect(judgeFirstRow(LIST, 360)).toMatchObject({ status: 'within-budget', passed: true });
  });

  it('fails a row one pixel past the budget, and says by how much', () => {
    const verdict = judgeFirstRow(LIST, 361);
    expect(verdict).toMatchObject({ status: 'over-budget', passed: false, topPx: 361 });
    expect(verdict.detail).toContain('1 px over the 360 px budget');
  });

  it('fails the pre-quiet-pass Catalog and passes the HIVE-11.6 one', () => {
    // The two measurements first-row.spec.ts takes in a browser (≈ 609 px and ≈ 344 px).
    expect(judgeFirstRow(LIST, 609).passed).toBe(false);
    expect(judgeFirstRow(LIST, 344).passed).toBe(true);
  });

  it('lets an allowance hold a page at its ceiling, and no further', () => {
    expect(judgeFirstRow(ALLOWED, 382)).toMatchObject({
      status: 'allowed-overrun',
      passed: true,
      ceilingPx: 390,
    });
    expect(judgeFirstRow(ALLOWED, 382).detail).toContain('a toolbar row added');
    expect(judgeFirstRow(ALLOWED, 390).passed).toBe(true);
    expect(judgeFirstRow(ALLOWED, 391)).toMatchObject({ status: 'over-budget', passed: false });
    expect(judgeFirstRow(ALLOWED, 391).detail).toContain('390 px allowance');
  });

  it('fails a page back within budget until its allowance is deleted', () => {
    const verdict = judgeFirstRow(ALLOWED, 344);
    expect(verdict).toMatchObject({ status: 'stale-allowance', passed: false });
    expect(verdict.detail).toContain('delete the allowance');
  });

  it('fails a selector that matches nothing rather than passing it vacuously', () => {
    const verdict = judgeFirstRow(LIST, null);
    expect(verdict).toMatchObject({ status: 'missing', passed: false, topPx: null });
    expect(verdict.detail).toContain(FIRST_DATA_ROW);
  });
});

/** A signature both sides share, so the parity score is a clean 100 %. */
function signature(): ParitySignature {
  const landmark = { present: true, x: 32, width: 1136, typeToken: 'fs-md', fontWeight: 400 };
  return {
    side: 'app',
    tokens: { fg: 'rgb(0, 0, 0)' },
    landmarks: Object.fromEntries(LANDMARK_IDS.map((id) => [id, landmark])),
    type: {},
    ink: {},
    gaps: [],
    paddings: [],
    controls: {},
    radii: {},
    tables: [],
    scope: { width: 1200, height: 900 },
  } as ParitySignature;
}

/**
 * Score a perfect parity pair with a given first-row verdict.
 *
 * @param firstRow The verdict to attach, or `null` for an exempt route.
 * @returns The report.
 */
function scored(firstRow: FirstRowVerdict | null): ParityReport {
  return scoreParity({
    id: 'catalog',
    mockup: 'proposals/catalog-quiet.html',
    subject: 'hive-catalog/table.html',
    app: signature(),
    mockupSignature: signature(),
    firstRow,
  });
}

describe('the verdict', () => {
  it('fails a page that clears parity but not its first-row budget', () => {
    const report = scored(judgeFirstRow(LIST, 609));
    expect(report.score).toBeGreaterThanOrEqual(report.gate);
    expect(report.passed).toBe(false);
    expect(report.firstRow?.status).toBe('over-budget');
  });

  it('passes an exempt page on parity alone', () => {
    const report = scored(null);
    expect(report.passed).toBe(true);
    expect(report.firstRow).toBeNull();
  });

  it('puts the measurement in the failure message', () => {
    expect(explainReport(scored(judgeFirstRow(LIST, 609)))).toMatch(
      /First row\s+609 px, 249 px over the 360 px budget/
    );
    expect(explainReport(scored(null))).not.toContain('First row');
  });
});

describe('the report', () => {
  it('shows the measurement next to the parity score', () => {
    expect(firstRowCell(judgeFirstRow(LIST, 344))).toBe('344 / 360 px');
    expect(firstRowCell(judgeFirstRow(ALLOWED, 382))).toBe('382 / 360 px (allowed 390)');
    expect(firstRowCell(judgeFirstRow(LIST, null))).toBe('no match / 360 px');
    expect(firstRowCell(null)).toBe('—');
    expect(firstRowCell(undefined)).toBe('—');
  });

  it('puts the first-row column and the detail line on the published page', () => {
    const report = scored(judgeFirstRow(LIST, 609));
    const html = parityReportHtml([{ report, images: null }]);
    expect(html).toContain('<th class="num">First row</th>');
    expect(html).toContain('609 / 360 px');
    expect(html).toContain('First row of data: 609 px, 249 px over the 360 px budget');
    expect(html).toContain('<code>.page-body tbody tr[data-row-id]</code>');
  });

  it('puts the measurement in the CI summary', () => {
    const markdown = parityMarkdownSummary([scored(judgeFirstRow(LIST, 344))]);
    expect(markdown).toContain('| Route | Score | First row | Verdict |');
    expect(markdown).toContain('| `catalog` | 100.0 % | 344 / 360 px | pass |');
  });

  it('reads an artefact written before the budget existed', () => {
    const legacy = { ...scored(null) } as ParityReport;
    delete legacy.firstRow;
    const html = parityReportHtml([{ report: legacy, images: null }]);
    expect(html).not.toContain('First row of data');
    expect(parityMarkdownSummary([legacy])).toContain('| — |');
  });
});
