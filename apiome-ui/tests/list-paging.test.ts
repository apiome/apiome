/**
 * Paging a long list in the browser — RC6-H6 (#6213): `dataTablePage` and the two foot sentences
 * that say which slice is drawn.
 */

import { dataTablePage, dataTablePageCount } from '../src/app/components/ui/DataTable';
import { CATALOG_PAGE_SIZE, catalogFootLabel } from '../src/app/components/ade/catalog/catalogModel';
import { VERSIONS_PAGE_SIZE, versionsFootLabel } from '../src/app/components/ade/versions/versionsModel';

const ROWS = Array.from({ length: 120 }, (_, index) => index);

describe('dataTablePage', () => {
  it('returns one page of rows, with the page count', () => {
    expect(dataTablePage(ROWS, 1, 50)).toEqual({ page: 1, pageCount: 3, rows: ROWS.slice(0, 50) });
    expect(dataTablePage(ROWS, 3, 50).rows).toEqual(ROWS.slice(100, 120));
  });

  it('clamps a page the list no longer reaches, and a nonsense one', () => {
    expect(dataTablePage(ROWS, 9, 50).page).toBe(3);
    expect(dataTablePage(ROWS, 0, 50).page).toBe(1);
    expect(dataTablePage(ROWS, Number.NaN, 50).page).toBe(1);
    expect(dataTablePage(ROWS, 2.7, 50).page).toBe(2);
  });

  it('treats an empty list as one empty page', () => {
    expect(dataTablePage([], 4, 50)).toEqual({ page: 1, pageCount: 1, rows: [] });
    expect(dataTablePageCount(0, 50)).toBe(1);
  });
});

describe('the foot sentences', () => {
  const byName = { columnId: 'name', direction: 'asc' } as const;

  it('keep the short form for a list that fits one page', () => {
    expect(catalogFootLabel(7, byName)).toMatch(/^7 items · sorted by /);
    expect(versionsFootLabel(6, { columnId: 'created', direction: 'desc' }, '')).toMatch(/^6 revisions · /);
  });

  it('say which slice is drawn once the list needs pages', () => {
    expect(catalogFootLabel(1000, byName, 2)).toMatch(/^Showing 51–100 of 1000 items · sorted by /);
    expect(versionsFootLabel(300, { columnId: 'created', direction: 'desc' }, '', 6)).toMatch(
      /^Showing 251–300 of 300 revisions · sorted by .* · lifecycle filter: all$/
    );
  });

  it('page fifty at a time', () => {
    expect(CATALOG_PAGE_SIZE).toBe(50);
    expect(VERSIONS_PAGE_SIZE).toBe(50);
  });
});
