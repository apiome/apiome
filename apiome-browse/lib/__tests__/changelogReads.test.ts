/**
 * The bounded changelog reads (DBP-1.27, #7210): what the statements select and how their rows are
 * mapped. The pool is a recorder; the statements' plans are checked on the scale database by
 * `apiome-db plan-check`.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';

const { query } = vi.hoisted(() => ({ query: vi.fn() }));

vi.mock('../db/db', () => ({ default: { query } }));

import {
  CHANGELOG_PAGE_SIZE,
  CHANGELOG_PAGE_SQL,
  CHANGELOG_VERSION_WINDOW,
  FEED_ENTRY_LIMIT,
  FEED_VERSION_LIMIT,
  getChangelogPage,
  getChangelogPair,
  getFeedRows,
  getFeedValidator,
  getPublicVersionChangelog,
} from '../db/changelogs';
import { mapChangelogRow } from '../db/changelogRows';
import { DESCRIPTION_ENTRY_CAP } from '../feed/changelog-feed';

/** A changelog row as the page statement's JSON carries it. */
function queryRow(label: string, entries: unknown[] = []) {
  return {
    published_revision_id: `id-${label}`,
    version_label: label,
    published_at: '2026-11-02T12:00:00+00:00',
    baseline_version_label: null,
    max_severity: 'breaking',
    status: 'ready',
    changelog_json: { schemaVersion: 'ctg.changelog.v1', counts: { total: 7 }, entries },
  };
}

/** The text and values of the only recorded call. */
function onlyCall(): { text: string; values: unknown[] } {
  expect(query).toHaveBeenCalledTimes(1);
  return { text: query.mock.calls[0][0] as string, values: query.mock.calls[0][1] as unknown[] };
}

beforeEach(() => {
  query.mockReset();
  query.mockResolvedValue({ rows: [] });
});

describe('the changelog page statement', () => {
  it('pages by position among the project\'s public versions, newest first', () => {
    expect(CHANGELOG_PAGE_SQL).toContain('WHERE v.project_id = $1');
    expect(CHANGELOG_PAGE_SQL).toContain("AND v.visibility = 'public'");
    expect(CHANGELOG_PAGE_SQL).toContain('v.published = true');
    expect(CHANGELOG_PAGE_SQL).toContain('AND v.deleted_at IS NULL');
    expect(CHANGELOG_PAGE_SQL).toContain(
      'ROW_NUMBER() OVER (ORDER BY v.published_at DESC NULLS LAST, v.created_at DESC, v.id DESC) AS ord'
    );
    expect(CHANGELOG_PAGE_SQL).toContain(`LIMIT ${CHANGELOG_VERSION_WINDOW}`);
    // `since` keeps the newer versions, `before` the older ones; the page is cut after both.
    expect(CHANGELOG_PAGE_SQL).toContain('bounds.since_ord IS NULL OR pv.ord < bounds.since_ord');
    expect(CHANGELOG_PAGE_SQL).toContain('bounds.before_ord IS NULL OR r.ord > bounds.before_ord');
    expect(CHANGELOG_PAGE_SQL).toMatch(/ORDER BY r\.ord\s+LIMIT \$6/);
  });

  it('filters entries by severity and path group in SQL, and drops the snapshots no page prints', () => {
    expect(CHANGELOG_PAGE_SQL).toContain("($4::text IS NULL OR e.entry ->> 'severity' = $4::text)");
    expect(CHANGELOG_PAGE_SQL).toContain("($5::text IS NULL OR e.entry ->> 'pathGroup' = $5::text)");
    expect(CHANGELOG_PAGE_SQL).toContain("jsonb_agg(e.entry - 'before' - 'after' ORDER BY e.ord)");
  });

  it('lists the path groups of every classified version in range, not only of the page', () => {
    const groups = CHANGELOG_PAGE_SQL.slice(CHANGELOG_PAGE_SQL.indexOf('SELECT DISTINCT e.entry ->>'));
    expect(groups).toContain('FROM in_range r');
    expect(groups).toContain("vc.status = 'ready'");
    expect(groups).not.toContain('FROM page');
  });

  it('never selects the private error column', () => {
    expect(CHANGELOG_PAGE_SQL).not.toMatch(/\berror\b/);
  });
});

describe('getChangelogPage', () => {
  it('binds the project, the filters and one row more than the page', async () => {
    await getChangelogPage('project-1', { severity: 'breaking', pathGroup: '/pets', since: '1.0.0', before: '3.0.0' });
    expect(onlyCall().values).toEqual(['project-1', '1.0.0', '3.0.0', 'breaking', '/pets', CHANGELOG_PAGE_SIZE + 1]);
  });

  it('binds nulls for an unfiltered first page', async () => {
    await getChangelogPage('project-1');
    expect(onlyCall().values).toEqual(['project-1', null, null, null, null, CHANGELOG_PAGE_SIZE + 1]);
  });

  it('names the next page by the last version shown when there is an older page', async () => {
    const labels = Array.from({ length: 3 }, (_, n) => `3.${2 - n}.0`);
    query.mockResolvedValue({
      rows: [{ rows: labels.map((l) => queryRow(l)), version_labels: labels, versions_in_range: 9, path_groups: ['/pets'], since_not_found: false }],
    });
    const page = await getChangelogPage('project-1', {}, 2);
    expect(page.rows.map((r) => r.versionLabel)).toEqual(['3.2.0', '3.1.0']);
    expect(page.nextBefore).toBe('3.1.0');
    expect(page.versionsInRange).toBe(9);
    expect(page.pathGroups).toEqual(['/pets']);
    expect(page.versionLabels).toEqual(labels);
    // A timestamp that came through JSON is a Date again.
    expect(page.rows[0].publishedAt).toEqual(new Date('2026-11-02T12:00:00Z'));
  });

  it('has no next page when the rows fit', async () => {
    query.mockResolvedValue({
      rows: [{ rows: [queryRow('1.0.0')], version_labels: ['1.0.0'], versions_in_range: 1, path_groups: [], since_not_found: true }],
    });
    const page = await getChangelogPage('project-1', { since: 'nope' }, 2);
    expect(page.nextBefore).toBeNull();
    expect(page.sinceNotFound).toBe(true);
  });

  it('is an empty page, not an error, when the statement returns nothing', async () => {
    expect(await getChangelogPage('project-1')).toEqual({
      rows: [],
      nextBefore: null,
      versionLabels: [],
      versionsInRange: 0,
      pathGroups: [],
      sinceNotFound: false,
    });
  });
});

describe('the other changelog reads', () => {
  it('reads one pair for compare, without its entries, by baseline and head label', async () => {
    query.mockResolvedValue({ rows: [{ ...queryRow('2.0.0'), changelog_json: { counts: { total: 7, breaking: 2 } } }] });
    const row = await getChangelogPair('project-1', '1.0.0', '2.0.0');
    const { text, values } = onlyCall();
    expect(values).toEqual(['project-1', '1.0.0', '2.0.0']);
    expect(text).toContain("vc.changelog_json - 'entries' AS changelog_json");
    expect(text).toContain('AND v.version_id = $3');
    expect(text).toContain('AND bl.version_id = $2');
    expect(row).toMatchObject({ versionLabel: '2.0.0', entriesOmitted: true });
    expect(row?.changelog).toEqual({ counts: { total: 7, breaking: 2 }, entries: [] });
  });

  it('answers null for a pair without a stored changelog', async () => {
    expect(await getChangelogPair('project-1', '1.0.0', '2.0.0')).toBeNull();
  });

  it('reads one version in full for the Changes tab', async () => {
    query.mockResolvedValue({ rows: [queryRow('2.0.0', [{ severity: 'breaking', pathGroup: '/pets' }])] });
    const row = await getPublicVersionChangelog('acme', 'payments', '2.0.0');
    expect(onlyCall().values).toEqual(['acme', 'payments', '2.0.0']);
    expect(row?.entriesOmitted).toBeUndefined();
    expect(row?.changelog?.entries).toHaveLength(1);
  });

  it('derives a feed\'s validator from counts and timestamps alone', async () => {
    query.mockResolvedValue({
      rows: [{ project_id: 'p1', project_name: 'Payments', version_count: 12, changed_at: '2026-11-20T10:00:00.000000Z' }],
    });
    expect(await getFeedValidator('acme', 'payments')).toEqual({
      projectId: 'p1',
      projectName: 'Payments',
      versionCount: 12,
      changedAt: '2026-11-20T10:00:00.000000Z',
    });
    const { text } = onlyCall();
    expect(text).not.toContain('changelog_json');
    expect(text).toContain('MAX(GREATEST(v.updated_at, vc.updated_at, v.published_at))');
    expect(text).toContain('JOIN apiome.browse_public_projects b ON b.project_id = p.id');
  });

  it('reads for a feed only the versions and entries it prints', async () => {
    await getFeedRows('p1');
    const { text, values } = onlyCall();
    expect(values).toEqual(['p1']);
    expect(text).toContain(`LIMIT ${FEED_VERSION_LIMIT}`);
    expect(text).toContain(`'$[0 to ${FEED_ENTRY_LIMIT - 1}]'`);
    expect(FEED_ENTRY_LIMIT).toBe(DESCRIPTION_ENTRY_CAP);
  });
});

describe('mapChangelogRow', () => {
  it('marks a summary read, with an empty entry list that means "not loaded"', () => {
    const row = mapChangelogRow({ ...queryRow('1.0.0'), changelog_json: { counts: { total: 3 } } }, true);
    expect(row.entriesOmitted).toBe(true);
    expect(row.changelog).toEqual({ counts: { total: 3 }, entries: [] });
  });

  it('does not mark a version that has no payload: there is nothing to load', () => {
    const row = mapChangelogRow({ ...queryRow('1.0.0'), status: null, changelog_json: null }, true);
    expect(row.entriesOmitted).toBeUndefined();
    expect(row.changelog).toBeNull();
  });

  it('keeps a Date, parses a string and drops a date that is not one', () => {
    const date = new Date('2026-11-02T12:00:00Z');
    expect(mapChangelogRow({ ...queryRow('1'), published_at: date }).publishedAt).toBe(date);
    expect(mapChangelogRow({ ...queryRow('1'), published_at: 'not a date' }).publishedAt).toBeNull();
    expect(mapChangelogRow({ ...queryRow('1'), published_at: null }).publishedAt).toBeNull();
  });
});
