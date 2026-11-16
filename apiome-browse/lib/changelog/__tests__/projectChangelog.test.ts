/**
 * Tests for the public per-API changelog page model — PCX-2.1 (#5896).
 *
 * Pins: one section per version newest first, CTG order inside each, totals matching the stored
 * `counts`, explicit initial / failed / pending states, the three server filters (and their
 * shareable query string), stable unique entry anchors, and compare deep-links.
 */

import { describe, expect, it } from 'vitest';
import {
  buildProjectChangelog,
  changelogFilterQuery,
  compareFocusHref,
  entryAnchor,
  parseChangelogFilters,
  sectionNote,
  versionAnchor,
} from '../projectChangelog';
import type { ChangelogEntry, PublicVersionChangelogRow, Severity } from '../types';

function entry(severity: Severity, pathGroup: string, pointer: string, ruleId = 'rule.test'): ChangelogEntry {
  return { severity, pathGroup, pointer, ruleId, changeKind: 'modified', summary: `change at ${pointer}` };
}

/** A `ready` row whose stored counts are derived from its entries. */
function readyRow(version: string, baseline: string, entries: ChangelogEntry[]): PublicVersionChangelogRow {
  const counts = { breaking: 0, 'non-breaking': 0, 'docs-only': 0, unclassified: 0, total: entries.length };
  for (const e of entries) counts[e.severity] += 1;
  return {
    publishedRevisionId: `rev-${version}`,
    versionLabel: version,
    publishedAt: '2026-11-01T00:00:00.000Z',
    baselineVersionLabel: baseline,
    maxSeverity: entries[0]?.severity ?? null,
    status: 'ready',
    changelog: {
      schemaVersion: 'ctg.changelog.v1',
      fromVersion: baseline,
      toVersion: version,
      counts,
      maxSeverity: entries[0]?.severity ?? null,
      entries,
    },
  };
}

function stateRow(version: string, status: 'initial' | 'failed' | null): PublicVersionChangelogRow {
  return {
    publishedRevisionId: `rev-${version}`,
    versionLabel: version,
    publishedAt: null,
    baselineVersionLabel: null,
    maxSeverity: null,
    status,
    changelog: null,
  };
}

/** Petstore with three publishes: 1.0.0 initial, 1.1.0 additive, 1.2.0 breaking + docs. */
const PETSTORE: PublicVersionChangelogRow[] = [
  readyRow('1.2.0', '1.1.0', [
    entry('breaking', '/paths/~1pets', '/paths/~1pets/get/parameters/0'),
    entry('breaking', '/paths/~1pets~1{id}', '/paths/~1pets~1{id}/delete'),
    entry('docs-only', '/info', '/info/description'),
  ]),
  readyRow('1.1.0', '1.0.0', [entry('non-breaking', '/paths/~1pets', '/paths/~1pets/post')]),
  { ...stateRow('1.0.0', 'initial') },
];

describe('buildProjectChangelog', () => {
  it('renders one section per version, newest first, with totals matching counts', () => {
    const model = buildProjectChangelog(PETSTORE, {}, 'acme', 'petstore');
    expect(model.sections.map((s) => s.versionLabel)).toEqual(['1.2.0', '1.1.0', '1.0.0']);
    for (const section of model.sections.filter((s) => s.state === 'ready')) {
      expect(section.shownCounts).toEqual(section.storedCounts);
    }
    expect(model.sections[0].shownCounts).toEqual({ breaking: 2, 'non-breaking': 0, 'docs-only': 1, total: 3 });
    expect(model.filtered).toBe(false);
  });

  it('keeps CTG order: breaking → non-breaking → docs-only, groups in stored order', () => {
    const model = buildProjectChangelog(PETSTORE, {}, 'acme', 'petstore');
    const first = model.sections[0];
    expect(first.severities.map((s) => s.severity)).toEqual(['breaking', 'docs-only']);
    expect(first.severities[0].groups.map((g) => g.pathGroup)).toEqual(['/paths/~1pets', '/paths/~1pets~1{id}']);
  });

  it('renders initial, failed and pending rows as explicit states', () => {
    const rows = [stateRow('1.5.0', 'failed'), stateRow('1.4.0', null), stateRow('1.0.0', 'initial')];
    const model = buildProjectChangelog(rows, {}, 'acme', 'petstore');
    expect(model.sections.map((s) => s.state)).toEqual(['failed', 'pending', 'initial']);
    expect(sectionNote(model.sections[0], false)).toBe('Classification failed for 1.5.0 — plain diff only.');
    expect(sectionNote(model.sections[1], false)).toBe('Changes for 1.4.0 are pending classification.');
    expect(sectionNote(model.sections[2], false)).toBe('Initial publication — no prior baseline to compare against.');
    for (const s of model.sections) {
      expect(s.storedCounts).toBeNull();
      expect(s.severities).toEqual([]);
    }
  });

  it('treats a ready row carrying the initialPublication marker as initial', () => {
    const row = readyRow('1.0.0', '', []);
    row.changelog!.initialPublication = true;
    expect(buildProjectChangelog([row], {}, 'a', 'b').sections[0].state).toBe('initial');
  });

  it('notes a classified version with no changes', () => {
    const model = buildProjectChangelog([readyRow('2.0.0', '1.0.0', [])], {}, 'a', 'b');
    expect(sectionNote(model.sections[0], false)).toBe('No changes detected.');
  });

  it('filters entries by severity, keeping every section and stored totals', () => {
    const model = buildProjectChangelog(PETSTORE, { severity: 'breaking' }, 'acme', 'petstore');
    expect(model.sections).toHaveLength(3);
    expect(model.sections[0].shownCounts.total).toBe(2);
    expect(model.sections[0].storedCounts?.total).toBe(3);
    expect(model.sections[1].shownCounts.total).toBe(0);
    expect(sectionNote(model.sections[1], model.filtered)).toBe('No changes in this version match the filters.');
    expect(model.filtered).toBe(true);
  });

  it('filters entries by path group and lists every path group for the control', () => {
    const model = buildProjectChangelog(PETSTORE, { pathGroup: '/paths/~1pets' }, 'acme', 'petstore');
    expect(model.sections[0].shownCounts.total).toBe(1);
    expect(model.sections[1].shownCounts.total).toBe(1);
    expect(model.pathGroups).toEqual(['/info', '/paths/~1pets', '/paths/~1pets~1{id}']);
  });

  it('keeps only versions newer than ?since (exclusive)', () => {
    const model = buildProjectChangelog(PETSTORE, { since: '1.1.0' }, 'acme', 'petstore');
    expect(model.sections.map((s) => s.versionLabel)).toEqual(['1.2.0']);
    expect(model.sinceNotFound).toBe(false);
  });

  it('shows every version and flags an unknown ?since', () => {
    const model = buildProjectChangelog(PETSTORE, { since: '9.9.9' }, 'acme', 'petstore');
    expect(model.sections).toHaveLength(3);
    expect(model.sinceNotFound).toBe(true);
  });

  it('gives each entry a compare deep-link with the baseline and pointer', () => {
    const model = buildProjectChangelog(PETSTORE, {}, 'acme', 'petstore');
    const first = model.sections[0].severities[0].groups[0].entries[0];
    expect(first.compareHref).toBe(
      '/tenant/acme/petstore/compare?v1=1.1.0&v2=1.2.0&focus=%2Fpaths%2F~1pets%2Fget%2Fparameters%2F0'
    );
  });

  it('gives entries stable anchors that survive filtering and stay unique', () => {
    const dup = entry('breaking', '/paths/~1a', '/paths/~1a/get');
    const rows = [readyRow('3.0.0', '2.0.0', [dup, { ...dup }])];
    const model = buildProjectChangelog(rows, {}, 'a', 'b');
    const anchors = model.sections[0].severities[0].groups[0].entries.map((e) => e.anchor);
    expect(anchors[0]).toBe(entryAnchor('3.0.0', dup));
    expect(anchors[1]).toBe(`${anchors[0]}-2`);

    const all = buildProjectChangelog(PETSTORE, {}, 'acme', 'petstore');
    const filtered = buildProjectChangelog(PETSTORE, { severity: 'docs-only' }, 'acme', 'petstore');
    const docsAll = all.sections[0].severities[1].groups[0].entries[0].anchor;
    expect(filtered.sections[0].severities[0].groups[0].entries[0].anchor).toBe(docsAll);
  });
});

describe('parseChangelogFilters / changelogFilterQuery', () => {
  it('parses known filters and drops unknown severities and blanks', () => {
    expect(parseChangelogFilters({ severity: 'breaking', pathGroup: '/info', since: ' 1.4.0 ' })).toEqual({
      severity: 'breaking',
      pathGroup: '/info',
      since: '1.4.0',
    });
    expect(parseChangelogFilters({ severity: 'scary', pathGroup: '  ' })).toEqual({});
    expect(parseChangelogFilters({ severity: ['docs-only', 'breaking'] })).toEqual({ severity: 'docs-only' });
  });

  it('round-trips filters through the query string', () => {
    const filters = { severity: 'non-breaking' as const, pathGroup: '/paths/~1pets', since: '1.0.0' };
    const qs = changelogFilterQuery(filters);
    expect(qs).toBe('?severity=non-breaking&pathGroup=%2Fpaths%2F%7E1pets&since=1.0.0');
    expect(parseChangelogFilters(Object.fromEntries(new URLSearchParams(qs)))).toEqual(filters);
    expect(changelogFilterQuery({})).toBe('');
  });
});

describe('anchors and compare links', () => {
  it('slugs version anchors', () => {
    expect(versionAnchor('1.5.0-rc.1')).toBe('v-1-5-0-rc-1');
    expect(versionAnchor('***')).toBe('v-x');
  });

  it('returns no compare link without a baseline', () => {
    expect(compareFocusHref('a', 'b', null, '1.0.0', '/info')).toBeNull();
  });
});
