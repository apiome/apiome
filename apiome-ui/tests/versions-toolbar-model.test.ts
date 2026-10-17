/**
 * The rules behind the Versions table's one toolbar (HIVE-11.4, #5600).
 *
 * `versions-hive-redesign.test.tsx` drives the toolbar on the rendered page; this pins the
 * pure half — the URL vocabulary, the three quick date ranges, and the two trigger labels.
 */

import {
  activeTableFilterCount,
  parseTableFilters,
  tableFiltersToSearchParams,
} from '../src/app/components/ui/dataTableUrlState';
import {
  isoDay,
  isVersionsDateRangeValid,
  stateFromVersionFacet,
  VERSIONS_PROJECT_SCOPED_FILTERS,
  VERSIONS_TABLE_FILTERS,
  versionFacetFromState,
  versionsAuthorLabel,
  versionsDatePresetFor,
  versionsDatePresetRange,
  versionsDateRangeLabel,
} from '../src/app/components/ade/versions/versionsToolbarModel';

/** A fixed clock: Thursday 16 October 2026, mid-afternoon local time. */
const NOW = new Date(2026, 9, 16, 15, 30);

describe('the URL vocabulary', () => {
  it('names the history params after the REST revisions list', () => {
    expect(Object.keys(VERSIONS_TABLE_FILTERS.fields)).toEqual([
      'q',
      'creatorId',
      'createdAfter',
      'createdBefore',
      'lifecycle',
      'state',
      'tag',
    ]);
  });

  it('round-trips every filter and leaves the unfiltered table at a bare query', () => {
    const filters = {
      q: 'payout',
      creatorId: 'u-ada',
      createdAfter: '2026-07-01',
      createdBefore: '2026-08-31',
      lifecycle: 'beta',
      state: 'drafts',
      tag: 'tag-1',
    };
    const params = tableFiltersToSearchParams(filters, VERSIONS_TABLE_FILTERS);
    expect(parseTableFilters(params, VERSIONS_TABLE_FILTERS)).toEqual(filters);
    expect(activeTableFilterCount(filters, VERSIONS_TABLE_FILTERS)).toBe(7);
    expect(tableFiltersToSearchParams(VERSIONS_TABLE_FILTERS.empty, VERSIONS_TABLE_FILTERS).toString()).toBe('');
  });

  it('drops a lifecycle or state the screen does not have', () => {
    const parsed = parseTableFilters(new URLSearchParams('lifecycle=retired&state=all'), VERSIONS_TABLE_FILTERS);
    expect(parsed.lifecycle).toBe('');
    expect(parsed.state).toBe('');
  });

  it('clears everything but the state chip on a project switch', () => {
    expect([...VERSIONS_PROJECT_SCOPED_FILTERS].sort()).toEqual(
      Object.keys(VERSIONS_TABLE_FILTERS.fields).filter((key) => key !== 'state').sort()
    );
  });

  it('maps the quick chip to the state param and back, All being absent', () => {
    expect(stateFromVersionFacet('all')).toBe('');
    expect(stateFromVersionFacet('drafts')).toBe('drafts');
    expect(versionFacetFromState('')).toBe('all');
    expect(versionFacetFromState('published')).toBe('published');
    expect(versionFacetFromState('bogus')).toBe('all');
  });
});

describe('the quick date ranges', () => {
  it('counts today in Last 7 days and Last 30 days', () => {
    expect(versionsDatePresetRange('last7', NOW)).toEqual({ from: '2026-10-10', to: '2026-10-16' });
    expect(versionsDatePresetRange('last30', NOW)).toEqual({ from: '2026-09-17', to: '2026-10-16' });
  });

  it('starts This quarter on the first day of the calendar quarter', () => {
    expect(versionsDatePresetRange('quarter', NOW)).toEqual({ from: '2026-10-01', to: '2026-10-16' });
    expect(versionsDatePresetRange('quarter', new Date(2026, 2, 31))).toEqual({ from: '2026-01-01', to: '2026-03-31' });
  });

  it('crosses a month and a year boundary', () => {
    expect(versionsDatePresetRange('last7', new Date(2026, 0, 3))).toEqual({ from: '2025-12-28', to: '2026-01-03' });
  });

  it('recognises a pair that is exactly a preset, and nothing else', () => {
    expect(versionsDatePresetFor({ from: '2026-10-10', to: '2026-10-16' }, NOW)).toBe('last7');
    expect(versionsDatePresetFor({ from: '2026-10-11', to: '2026-10-16' }, NOW)).toBeNull();
    expect(versionsDatePresetFor({ from: '', to: '' }, NOW)).toBeNull();
  });

  it('writes local calendar days', () => {
    expect(isoDay(new Date(2026, 1, 5, 23, 59))).toBe('2026-02-05');
  });
});

describe('the trigger labels', () => {
  it('reads Any time, a preset, or the range in words', () => {
    expect(versionsDateRangeLabel({ from: '', to: '' }, NOW)).toBe('Any time');
    expect(versionsDateRangeLabel({ from: '2026-10-01', to: '2026-10-16' }, NOW)).toBe('This quarter');
    expect(versionsDateRangeLabel({ from: '2026-07-01', to: '2026-08-31' }, NOW)).toBe('Jul 1, 2026 – Aug 31, 2026');
    expect(versionsDateRangeLabel({ from: '2026-07-01', to: '' }, NOW)).toBe('Since Jul 1, 2026');
    expect(versionsDateRangeLabel({ from: '', to: '2026-08-31' }, NOW)).toBe('Until Aug 31, 2026');
  });

  it('accepts open ends and an ordered pair, and refuses an inverted one', () => {
    expect(isVersionsDateRangeValid({ from: '', to: '' })).toBe(true);
    expect(isVersionsDateRangeValid({ from: '2026-07-01', to: '' })).toBe(true);
    expect(isVersionsDateRangeValid({ from: '2026-07-01', to: '2026-07-01' })).toBe(true);
    expect(isVersionsDateRangeValid({ from: '2026-08-01', to: '2026-07-01' })).toBe(false);
  });

  it('names the author, All authors, or 1 author for an id the list does not hold yet', () => {
    const options = [{ id: 'u-ada', label: 'Ada Lovelace' }];
    expect(versionsAuthorLabel('', options)).toBe('All authors');
    expect(versionsAuthorLabel('u-ada', options)).toBe('Ada Lovelace');
    expect(versionsAuthorLabel('u-unknown', options)).toBe('1 author');
  });
});
