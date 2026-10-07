/**
 * The per-route copy audit stays complete — HIVE-10.4 (#5340).
 *
 * `docs/HIVE_COPY_AUDIT.md` records, for every `page.tsx` route, what its empty, loading, error
 * and gated states say (or why one cannot occur). This suite fails when a route is added without a
 * row, a row names a route that no longer exists, or a cell is left undecided.
 */

import { readFileSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';

import { SRC_ROOT, UI_ROOT, sourceFiles } from './helpers/copy-scan';

const AUDIT = readFileSync(join(UI_ROOT, 'docs', 'HIVE_COPY_AUDIT.md'), 'utf8');

/** Every route the app router serves, as the audit spells it. */
const ROUTES = sourceFiles()
  .filter((file) => file.endsWith('/page.tsx'))
  .map((file) => {
    const route = relative(join(SRC_ROOT, 'app'), dirname(file)).split('\\').join('/');
    return route === '' ? '/' : `/${route}`;
  })
  .sort();

/** The audit's table rows: route plus the four state cells. */
const ROWS = AUDIT.split('\n')
  .filter((line) => line.startsWith('| `'))
  .map((line) => {
    const cells = line.split('|').slice(1, -1).map((cell) => cell.trim());
    return { route: cells[0].replace(/`/g, ''), states: cells.slice(1, 5), notes: cells[5] ?? '' };
  });

/** A decided cell: what it says, why it cannot occur, or a recorded follow-up. */
const DECIDED = /^(✅ \S|n\/a — \S|⚠️ follow-up — \S)/;

describe('docs/HIVE_COPY_AUDIT.md', () => {
  it('finds the routes it audits', () => {
    expect(ROUTES.length).toBeGreaterThan(50);
  });

  it('has exactly one row per route the app serves', () => {
    expect(ROWS.map((row) => row.route).sort()).toEqual(ROUTES);
  });

  it.each(ROWS.map((row) => [row.route, row] as const))('decides all four states for %s', (_route, row) => {
    expect(row.states).toHaveLength(4);
    for (const cell of row.states) expect(cell).toMatch(DECIDED);
  });

  it('restates the §10 rules it audits against', () => {
    for (const rule of ['Titles are nouns', 'Buttons are verbs', '14 words', 'what happened and what to do']) {
      expect(AUDIT).toContain(rule);
    }
  });
});
