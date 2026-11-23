'use client';

/**
 * Holding a keyset-paged list on a screen (DBP-1.13, #7196).
 *
 * Two shapes, for the two ways a screen pages:
 *
 * - {@link useCursorPages} — "Load more": the rows read so far, with the next page appended.
 * - {@link useCursorTrail} — Previous / Next: one page at a time, remembering the cursor each page
 *   started at so the reader can step back.
 *
 * Both reset when their `key` (the filters, as one comparable string) changes, and neither lets a
 * slow answer for old filters overwrite the answer for new ones.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { hasMoreAfter, type PageInfo } from '@lib/cursor-pages';

/** What a page read is told. */
export interface CursorPageRequest {
  /** The previous page's cursor; null for the first page. */
  cursor: string | null;
  /** Rows already read — the `offset` fallback for an endpoint that issues no cursor. */
  offset: number;
  /** True for the first page: the one request that may ask for the count. */
  first: boolean;
  /** Aborted when the filters change or the screen unmounts. */
  signal: AbortSignal;
}

/** What a page read answers with. */
export interface CursorPageResult<Row> {
  /** The page's rows. */
  rows: Row[];
  /** Its paging fields — `readPage(body)`. */
  page: PageInfo;
}

/** What {@link useCursorPages} is told. */
export interface UseCursorPagesOptions<Row> {
  /** The filters as one comparable string; a change starts again from the first page. */
  key: string;
  /** Skip every read. Defaults to true. */
  enabled?: boolean;
  /** Read one page. May close over the screen's filters. */
  load: (request: CursorPageRequest) => Promise<CursorPageResult<Row>>;
  /** A row's identity, so a row that moved between pages is not drawn twice. */
  getRowId?: (row: Row) => string;
  /** The message when a read throws something that is not an `Error`. */
  errorMessage?: string;
}

/** What {@link useCursorPages} gives back. */
export interface UseCursorPagesResult<Row> {
  /** Every row read so far for the current key. */
  rows: Row[];
  /** The matches, or null when the server did not count them. */
  total: number | null;
  /** True when another page can be read. */
  hasMore: boolean;
  /** True until the first page for the current key has answered. */
  loading: boolean;
  /** True while a further page is being read. */
  loadingMore: boolean;
  /** What went wrong with the first page, or null. */
  error: string | null;
  /** What went wrong with the last `loadMore`, or null. The rows already read stay. */
  moreError: string | null;
  /** Read the next page and append it. */
  loadMore: () => void;
  /** Read the first page again, replacing what is loaded once it answers. */
  reload: () => void;
  /** Change the rows in place — after a write the screen made itself. */
  setRows: (update: (rows: Row[]) => Row[]) => void;
}

/** The rows read for one key. */
interface Loaded<Row> {
  key: string;
  rows: Row[];
  page: PageInfo;
  /** The first page's count: later pages are not asked for one. */
  total: number | null;
}

/**
 * Hold a "Load more" list.
 *
 * @param options - See {@link UseCursorPagesOptions}.
 * @returns See {@link UseCursorPagesResult}.
 */
export function useCursorPages<Row>(
  options: UseCursorPagesOptions<Row>,
): UseCursorPagesResult<Row> {
  const { key, enabled = true, getRowId, errorMessage = 'The list could not be loaded.' } = options;

  const [loaded, setLoaded] = useState<Loaded<Row> | null>(null);
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null);
  const [moreFailure, setMoreFailure] = useState<{ key: string; message: string } | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [nonce, setNonce] = useState(0);

  const loadRef = useRef(options.load);
  const idRef = useRef(getRowId);
  useEffect(() => {
    loadRef.current = options.load;
    idRef.current = getRowId;
  });
  const keyRef = useRef(key);
  keyRef.current = key;
  /** Bumped by every first-page read, so a `loadMore` that straddles one is dropped. */
  const generationRef = useRef(0);
  const moreAbortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!enabled) return undefined;
    const controller = new AbortController();
    const generation = (generationRef.current += 1);
    moreAbortRef.current?.abort();
    void (async () => {
      try {
        const result = await loadRef.current({
          cursor: null,
          offset: 0,
          first: true,
          signal: controller.signal,
        });
        if (controller.signal.aborted || generation !== generationRef.current) return;
        setLoaded({ key, rows: result.rows, page: result.page, total: result.page.total });
        setFailure(null);
        setMoreFailure(null);
      } catch (error) {
        if (controller.signal.aborted || generation !== generationRef.current) return;
        setFailure({ key, message: error instanceof Error ? error.message : errorMessage });
      }
    })();
    return () => controller.abort();
  }, [enabled, key, nonce, errorMessage]);

  useEffect(() => () => moreAbortRef.current?.abort(), []);

  const current = enabled && loaded?.key === key ? loaded : null;
  const error = enabled && failure?.key === key ? failure.message : null;

  const loadMore = useCallback(() => {
    if (!current || !hasMoreAfter(current.page, current.rows.length)) return;
    const controller = new AbortController();
    moreAbortRef.current?.abort();
    moreAbortRef.current = controller;
    const generation = generationRef.current;
    setLoadingMore(true);
    setMoreFailure(null);
    void (async () => {
      try {
        const result = await loadRef.current({
          cursor: current.page.nextCursor,
          offset: current.rows.length,
          first: false,
          signal: controller.signal,
        });
        if (controller.signal.aborted || generation !== generationRef.current) return;
        setLoaded((previous) => {
          if (!previous || previous.key !== current.key) return previous;
          const id = idRef.current;
          let added = result.rows;
          if (id) {
            const seen = new Set(previous.rows.map(id));
            added = result.rows.filter((row) => !seen.has(id(row)));
          }
          return {
            key: previous.key,
            rows: [...previous.rows, ...added],
            page: result.page,
            total: result.page.total ?? previous.total,
          };
        });
      } catch (failed) {
        if (controller.signal.aborted || generation !== generationRef.current) return;
        setMoreFailure({
          key: current.key,
          message: failed instanceof Error ? failed.message : errorMessage,
        });
      } finally {
        if (moreAbortRef.current === controller) {
          moreAbortRef.current = null;
          setLoadingMore(false);
        }
      }
    })();
  }, [current, errorMessage]);

  const reload = useCallback(() => setNonce((value) => value + 1), []);

  const setRows = useCallback((update: (rows: Row[]) => Row[]) => {
    setLoaded((previous) =>
      previous && previous.key === keyRef.current
        ? { ...previous, rows: update(previous.rows) }
        : previous,
    );
  }, []);

  return {
    rows: current?.rows ?? EMPTY_ROWS,
    total: current?.total ?? null,
    hasMore: current ? hasMoreAfter(current.page, current.rows.length) : false,
    loading: enabled && current === null && error === null,
    loadingMore,
    error,
    moreError: moreFailure?.key === key ? moreFailure.message : null,
    loadMore,
    reload,
    setRows,
  };
}

/** One stable empty list, so "nothing loaded" does not re-render its readers. */
const EMPTY_ROWS: never[] = [];

/** What {@link useCursorTrail} gives back. */
export interface CursorTrail {
  /** The zero-based page the reader is on. */
  page: number;
  /** The cursor that page starts at; null for the first page (and for an offset-paged endpoint). */
  cursor: string | null;
  /** Rows before this page — the `offset` fallback, and the range sentence's start. */
  offset: number;
  /** Whether the server counted on this request: only the first page asks. */
  first: boolean;
  /** Step to the next page, which starts at `nextCursor`. */
  next: (nextCursor: string | null) => void;
  /** Step back one page. */
  previous: () => void;
  /** Back to the first page. */
  reset: () => void;
}

/**
 * Remember where each page of a Previous / Next list started.
 *
 * A keyset list cannot jump to "page 7": it can only continue from a cursor. Stepping back is
 * therefore a matter of remembering the cursors already used, which is all this holds.
 *
 * @param key - The filters as one comparable string; a change returns to the first page.
 * @param pageSize - Rows per page, for {@link CursorTrail.offset}.
 * @returns The current position and the moves.
 */
export function useCursorTrail(key: string, pageSize: number): CursorTrail {
  const [state, setState] = useState<{ key: string; cursors: Array<string | null> }>({
    key,
    cursors: FIRST_PAGE,
  });
  const cursors = state.key === key ? state.cursors : FIRST_PAGE;

  const next = useCallback(
    (nextCursor: string | null) =>
      setState((previous) => ({
        key,
        cursors: [...(previous.key === key ? previous.cursors : FIRST_PAGE), nextCursor],
      })),
    [key],
  );
  const previous = useCallback(
    () =>
      setState((before) => {
        const trail = before.key === key ? before.cursors : FIRST_PAGE;
        return { key, cursors: trail.length > 1 ? trail.slice(0, -1) : trail };
      }),
    [key],
  );
  const reset = useCallback(() => setState({ key, cursors: FIRST_PAGE }), [key]);

  return useMemo(() => {
    const page = cursors.length - 1;
    return {
      page,
      cursor: cursors[page] ?? null,
      offset: page * pageSize,
      first: page === 0,
      next,
      previous,
      reset,
    };
  }, [cursors, pageSize, next, previous, reset]);
}

/** The trail of a list nobody has paged yet. */
const FIRST_PAGE: Array<string | null> = [null];
