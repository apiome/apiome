/**
 * The one reader of apiome-rest's keyset-paged list envelopes (DBP-1.13, #7196).
 *
 * What is pinned here is the contract every converted screen leans on: whether another page
 * follows is the server's `has_more`, never a comparison with a count; a `total` that was not
 * asked for is unknown, not zero; and a count at the cap is "at least this many".
 */

import {
  EMPTY_PAGE_INFO,
  MAX_CURSOR_LENGTH,
  TOTAL_CAP,
  cursorRangeLabel,
  formatTotal,
  forwardPageParams,
  hasMoreAfter,
  readPage,
  setPageParams,
} from '../lib/cursor-pages';

describe('readPage', () => {
  it('reads the snake_case envelope', () => {
    expect(readPage({ has_more: true, next_cursor: 'abc', total: null })).toEqual({
      hasMore: true,
      nextCursor: 'abc',
      total: null,
      reported: true,
    });
  });

  it('reads the camelCase envelope', () => {
    expect(readPage({ hasMore: false, nextCursor: null, total: 12 })).toEqual({
      hasMore: false,
      nextCursor: null,
      total: 12,
      reported: true,
    });
  });

  it('reads an offset-paged answer as "the server did not say"', () => {
    expect(readPage({ total: 40, limit: 10, offset: 0 })).toEqual({
      hasMore: false,
      nextCursor: null,
      total: 40,
      reported: false,
    });
  });

  it('treats a missing, null or malformed total as unknown rather than zero', () => {
    expect(readPage({ has_more: false }).total).toBeNull();
    expect(readPage({ total: null }).total).toBeNull();
    expect(readPage({ total: '12' }).total).toBeNull();
    expect(readPage({ total: -1 }).total).toBeNull();
    expect(readPage({ total: Number.NaN }).total).toBeNull();
    expect(readPage({ total: 0 }).total).toBe(0);
  });

  it('reads anything that is not an object as an empty page', () => {
    for (const body of [null, undefined, 'text', 7, []]) {
      expect(readPage(body)).toMatchObject({ hasMore: false, nextCursor: null, total: null });
    }
    expect(readPage(null)).toBe(EMPTY_PAGE_INFO);
  });

  it('ignores an empty cursor', () => {
    expect(readPage({ has_more: true, next_cursor: '' }).nextCursor).toBeNull();
  });
});

describe('hasMoreAfter', () => {
  it('believes has_more, whatever the total says', () => {
    expect(hasMoreAfter(readPage({ has_more: false, total: 500 }), 50)).toBe(false);
    expect(hasMoreAfter(readPage({ has_more: true, next_cursor: 'c', total: null }), 50)).toBe(
      true,
    );
    expect(hasMoreAfter(readPage({ has_more: true, next_cursor: 'c', total: 50 }), 50)).toBe(true);
  });

  it('compares with the total only for an answer that carries no has_more', () => {
    expect(hasMoreAfter(readPage({ total: 120 }), 50)).toBe(true);
    expect(hasMoreAfter(readPage({ total: 50 }), 50)).toBe(false);
    expect(hasMoreAfter(readPage({}), 50)).toBe(false);
  });
});

describe('setPageParams', () => {
  const build = (request: Parameters<typeof setPageParams>[1]) =>
    setPageParams(new URLSearchParams({ limit: '25' }), request).toString();

  it('sends nothing for the first page', () => {
    expect(build({})).toBe('limit=25');
    expect(build({ cursor: null, offset: 0 })).toBe('limit=25');
  });

  it('sends the cursor, and never an offset beside it', () => {
    expect(build({ cursor: 'abc', offset: 50 })).toBe('limit=25&cursor=abc');
  });

  it('falls back to the offset only when there is no cursor', () => {
    expect(build({ offset: 50 })).toBe('limit=25&offset=50');
  });

  it('asks for the count only when told to', () => {
    expect(build({ includeTotal: true })).toBe('limit=25&include_total=true');
    expect(build({ cursor: 'abc', includeTotal: false })).toBe('limit=25&cursor=abc');
  });

  it('replaces paging parameters already on the query', () => {
    const params = new URLSearchParams('offset=100&cursor=old&include_total=true&q=x');
    expect(setPageParams(params, { cursor: 'new' }).toString()).toBe('q=x&cursor=new');
  });
});

describe('forwardPageParams', () => {
  const forward = (query: string) =>
    forwardPageParams(new URLSearchParams(query), new URLSearchParams()).toString();

  it('passes a cursor through untouched and the count request only as the literal true', () => {
    expect(forward('cursor=eyJ0IjoiMjAyNiJ9&include_total=true')).toBe(
      'cursor=eyJ0IjoiMjAyNiJ9&include_total=true',
    );
    expect(forward('include_total=1')).toBe('');
    expect(forward('include_total=false')).toBe('');
  });

  it('drops everything else, and a cursor longer than the server issues', () => {
    expect(forward('tenant=evil&offset=5')).toBe('');
    expect(forward(`cursor=${'x'.repeat(MAX_CURSOR_LENGTH + 1)}`)).toBe('');
    expect(forward(`cursor=${'x'.repeat(MAX_CURSOR_LENGTH)}`)).toContain('cursor=');
  });
});

describe('formatTotal', () => {
  it('groups a count', () => {
    expect(formatTotal(0)).toBe('0');
    expect(formatTotal(1234)).toBe('1,234');
  });

  it('writes the counting cap as "at least"', () => {
    expect(formatTotal(TOTAL_CAP - 1)).toBe('9,999');
    expect(formatTotal(TOTAL_CAP)).toBe('10,000+');
    expect(formatTotal(TOTAL_CAP + 5)).toBe('10,000+');
  });

  it('answers null for a count nobody gave, so nothing is shown', () => {
    expect(formatTotal(null)).toBeNull();
    expect(formatTotal(undefined)).toBeNull();
    expect(formatTotal(Number.NaN)).toBeNull();
  });
});

describe('cursorRangeLabel', () => {
  it('states the window and the count', () => {
    expect(cursorRangeLabel(0, 25, 240, 'run')).toBe('Showing 1–25 of 240 runs');
    expect(cursorRangeLabel(25, 2, 27, 'run')).toBe('Showing 26–27 of 27 runs');
    expect(cursorRangeLabel(0, 1, 1, 'run')).toBe('Showing 1–1 of 1 run');
  });

  it('states only the window when the count is unknown', () => {
    expect(cursorRangeLabel(50, 25, null, 'run')).toBe('Showing 51–75');
  });

  it('writes a capped count as 10,000+', () => {
    expect(cursorRangeLabel(0, 25, 10000, 'run')).toBe('Showing 1–25 of 10,000+ runs');
  });

  it('says so when nothing is shown', () => {
    expect(cursorRangeLabel(0, 0, 0, 'run')).toBe('No runs');
    expect(cursorRangeLabel(0, 0, null)).toBe('No rows');
  });
});
