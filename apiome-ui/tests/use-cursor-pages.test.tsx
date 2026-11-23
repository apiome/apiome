/**
 * The two hooks that hold a keyset-paged list on a screen (DBP-1.13, #7196).
 *
 *  1. `useCursorPages` — "Load more": the first page, the next page appended from the previous
 *     page's cursor, a reset when the filters change, and a stale answer dropped.
 *  2. `useCursorTrail` — Previous / Next: the cursor each page started at is remembered, so the
 *     reader can step back, and a filter change returns to the first page.
 */

import { act, renderHook, waitFor } from '@testing-library/react';

import { readPage } from '../lib/cursor-pages';
import {
  useCursorPages,
  useCursorTrail,
  type CursorPageRequest,
  type CursorPageResult,
} from '../src/app/hooks/useCursorPages';

interface Row {
  id: string;
}

const rows = (...ids: string[]): Row[] => ids.map((id) => ({ id }));

/** A promise the test resolves by hand, to order two answers. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe('useCursorPages', () => {
  it('reads the first page, then appends the next from its cursor', async () => {
    const requests: Array<Omit<CursorPageRequest, 'signal'>> = [];
    const load = jest.fn(async ({ cursor, offset, first }: CursorPageRequest) => {
      requests.push({ cursor, offset, first });
      return cursor === 'after-b'
        ? { rows: rows('c'), page: readPage({ has_more: false, next_cursor: null, total: null }) }
        : {
            rows: rows('a', 'b'),
            page: readPage({ has_more: true, next_cursor: 'after-b', total: 3 }),
          };
    });
    const { result } = renderHook(() => useCursorPages<Row>({ key: 'k', load }));

    expect(result.current.loading).toBe(true);
    await waitFor(() => expect(result.current.rows).toHaveLength(2));
    expect(result.current).toMatchObject({ loading: false, hasMore: true, total: 3, error: null });

    act(() => result.current.loadMore());
    await waitFor(() => expect(result.current.rows.map((row) => row.id)).toEqual(['a', 'b', 'c']));
    // The later page did not count; the first page's count is kept.
    expect(result.current).toMatchObject({ hasMore: false, total: 3, loadingMore: false });
    expect(requests).toEqual([
      { cursor: null, offset: 0, first: true },
      { cursor: 'after-b', offset: 2, first: false },
    ]);

    // Nothing more: another call reads nothing.
    act(() => result.current.loadMore());
    expect(load).toHaveBeenCalledTimes(2);
  });

  it('offers more on has_more alone, with no total', async () => {
    const load = async (): Promise<CursorPageResult<Row>> => ({
      rows: rows('a'),
      page: readPage({ has_more: true, next_cursor: 'c', total: null }),
    });
    const { result } = renderHook(() => useCursorPages<Row>({ key: 'k', load }));
    await waitFor(() => expect(result.current.rows).toHaveLength(1));
    expect(result.current.hasMore).toBe(true);
    expect(result.current.total).toBeNull();
  });

  it('falls back to the offset for an answer with a total and no has_more', async () => {
    const offsets: number[] = [];
    const load = async ({ cursor, offset }: CursorPageRequest) => {
      offsets.push(offset);
      expect(cursor).toBeNull();
      return { rows: rows(`r${offset}`), page: readPage({ total: 2 }) };
    };
    const { result } = renderHook(() => useCursorPages<Row>({ key: 'k', load }));
    await waitFor(() => expect(result.current.hasMore).toBe(true));
    act(() => result.current.loadMore());
    await waitFor(() => expect(result.current.rows).toHaveLength(2));
    expect(result.current.hasMore).toBe(false);
    expect(offsets).toEqual([0, 1]);
  });

  it('does not draw a row twice when it moved between pages', async () => {
    const load = async ({ cursor }: CursorPageRequest) =>
      cursor
        ? { rows: rows('b', 'c'), page: readPage({ has_more: false }) }
        : { rows: rows('a', 'b'), page: readPage({ has_more: true, next_cursor: 'n' }) };
    const { result } = renderHook(() =>
      useCursorPages<Row>({ key: 'k', load, getRowId: (row) => row.id }),
    );
    await waitFor(() => expect(result.current.rows).toHaveLength(2));
    act(() => result.current.loadMore());
    await waitFor(() => expect(result.current.rows.map((row) => row.id)).toEqual(['a', 'b', 'c']));
  });

  it('starts again when the key changes, and drops the old key`s late answer', async () => {
    const slow = deferred<CursorPageResult<Row>>();
    const signals: AbortSignal[] = [];
    const load = jest.fn(({ signal }: CursorPageRequest) => {
      signals.push(signal);
      return signals.length === 1
        ? slow.promise
        : Promise.resolve({ rows: rows('new'), page: readPage({ has_more: false }) });
    });
    const { result, rerender } = renderHook(({ key }) => useCursorPages<Row>({ key, load }), {
      initialProps: { key: 'old' },
    });

    rerender({ key: 'new' });
    await waitFor(() => expect(result.current.rows.map((row) => row.id)).toEqual(['new']));
    // The request for the old filters was aborted…
    expect(signals[0].aborted).toBe(true);

    // …and its answer, arriving late, changes nothing.
    await act(async () => {
      slow.resolve({ rows: rows('stale'), page: readPage({ has_more: true, next_cursor: 'x' }) });
      await slow.promise;
    });
    expect(result.current.rows.map((row) => row.id)).toEqual(['new']);
    expect(result.current.hasMore).toBe(false);
  });

  it('drops a load-more that straddles a filter change', async () => {
    const more = deferred<CursorPageResult<Row>>();
    const load = jest.fn(({ cursor }: CursorPageRequest) =>
      cursor
        ? more.promise
        : Promise.resolve({
            rows: rows('a'),
            page: readPage({ has_more: true, next_cursor: 'n' }),
          }),
    );
    const { result, rerender } = renderHook(({ key }) => useCursorPages<Row>({ key, load }), {
      initialProps: { key: 'one' },
    });
    await waitFor(() => expect(result.current.rows).toHaveLength(1));
    act(() => result.current.loadMore());
    rerender({ key: 'two' });
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => {
      more.resolve({ rows: rows('late'), page: readPage({ has_more: false }) });
      await more.promise;
    });
    expect(result.current.rows.map((row) => row.id)).toEqual(['a']);
  });

  it('reports a failed first page, and reads again on reload', async () => {
    let fail = true;
    const load = async (): Promise<CursorPageResult<Row>> => {
      if (fail) throw new Error('Store unavailable');
      return { rows: rows('a'), page: readPage({ has_more: false }) };
    };
    const { result } = renderHook(() => useCursorPages<Row>({ key: 'k', load }));
    await waitFor(() => expect(result.current.error).toBe('Store unavailable'));
    expect(result.current.loading).toBe(false);

    fail = false;
    act(() => result.current.reload());
    await waitFor(() => expect(result.current.rows).toHaveLength(1));
    expect(result.current.error).toBeNull();
  });

  it('keeps the rows when the next page fails, and says so', async () => {
    const load = async ({ cursor }: CursorPageRequest): Promise<CursorPageResult<Row>> => {
      if (cursor) throw new Error('Rate limited');
      return { rows: rows('a'), page: readPage({ has_more: true, next_cursor: 'n' }) };
    };
    const { result } = renderHook(() => useCursorPages<Row>({ key: 'k', load }));
    await waitFor(() => expect(result.current.rows).toHaveLength(1));
    act(() => result.current.loadMore());
    await waitFor(() => expect(result.current.moreError).toBe('Rate limited'));
    expect(result.current.rows).toHaveLength(1);
    expect(result.current.hasMore).toBe(true);
    expect(result.current.loadingMore).toBe(false);
  });

  it('reads nothing while disabled', () => {
    const load = jest.fn();
    const { result } = renderHook(() => useCursorPages<Row>({ key: 'k', enabled: false, load }));
    expect(load).not.toHaveBeenCalled();
    expect(result.current).toMatchObject({ rows: [], loading: false, hasMore: false, total: null });
  });

  it('lets the screen change the rows it holds', async () => {
    const load = async () => ({ rows: rows('a', 'b'), page: readPage({ has_more: false }) });
    const { result } = renderHook(() => useCursorPages<Row>({ key: 'k', load }));
    await waitFor(() => expect(result.current.rows).toHaveLength(2));
    act(() => result.current.setRows((current) => current.filter((row) => row.id !== 'a')));
    expect(result.current.rows.map((row) => row.id)).toEqual(['b']);
  });
});

describe('useCursorTrail', () => {
  it('starts on the first page, which is the one that counts', () => {
    const { result } = renderHook(() => useCursorTrail('k', 25));
    expect(result.current).toMatchObject({ page: 0, cursor: null, offset: 0, first: true });
  });

  it('steps forward to a cursor and back to the one before', () => {
    const { result } = renderHook(() => useCursorTrail('k', 25));
    act(() => result.current.next('c1'));
    expect(result.current).toMatchObject({ page: 1, cursor: 'c1', offset: 25, first: false });
    act(() => result.current.next('c2'));
    expect(result.current).toMatchObject({ page: 2, cursor: 'c2', offset: 50 });

    act(() => result.current.previous());
    expect(result.current).toMatchObject({ page: 1, cursor: 'c1', offset: 25 });
    act(() => result.current.previous());
    expect(result.current).toMatchObject({ page: 0, cursor: null, first: true });
    // There is nothing before the first page.
    act(() => result.current.previous());
    expect(result.current.page).toBe(0);
  });

  it('carries only an offset for an endpoint that issues no cursor', () => {
    const { result } = renderHook(() => useCursorTrail('k', 10));
    act(() => result.current.next(null));
    expect(result.current).toMatchObject({ page: 1, cursor: null, offset: 10, first: false });
  });

  it('returns to the first page when the key changes, and on reset', () => {
    const { result, rerender } = renderHook(({ key }) => useCursorTrail(key, 25), {
      initialProps: { key: 'one' },
    });
    act(() => result.current.next('c1'));
    rerender({ key: 'two' });
    expect(result.current).toMatchObject({ page: 0, cursor: null, first: true });

    // A step taken under the new key does not inherit the old trail.
    act(() => result.current.next('d1'));
    expect(result.current).toMatchObject({ page: 1, cursor: 'd1' });
    act(() => result.current.reset());
    expect(result.current.page).toBe(0);
  });
});
