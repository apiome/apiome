'use client';

/**
 * Paging for the admin console's lists (DBP-1.13, #7196).
 *
 * The admin server actions used to return every user, tenant and template in one response. They
 * now return a page — `{ success, <rows>, hasMore, nextCursor }` — and apply the reader's search
 * in SQL. {@link useAdminPagedList} holds what has been loaded so far and reads the next page;
 * {@link AdminLoadMore} is the control under a list that asks for it.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { Button } from '@/app/components/ui/Button';

/** How long typing in a search box settles before the list is read again. */
export const ADMIN_SEARCH_DEBOUNCE_MS = 250;

/** What a paged admin action is asked for. */
export interface AdminPageRequest {
  /** The previous page's cursor; `null` for the first page. */
  cursor: string | null;
}

/** One paged admin list, as a screen holds it. */
export interface AdminPagedList<Row, Extra = Record<string, unknown>> {
  /** The rows loaded so far, in list order. */
  items: Row[];
  /** Whether the server has rows after the last one loaded. */
  hasMore: boolean;
  /** True while a further page is being read. */
  loadingMore: boolean;
  /** The rest of the first page's response (totals, for instance). */
  extra: Extra | null;
  /**
   * Read the first page again, replacing what is loaded.
   *
   * @returns Whether the read succeeded.
   */
  reload: () => Promise<boolean>;
  /** Read the next page and append it. */
  loadMore: () => Promise<void>;
  /** Forget what is loaded. */
  clear: () => void;
}

/**
 * Hold one paged admin list.
 *
 * A response that arrives after a newer read was started is dropped, so a slow first page can
 * never overwrite the result of the search typed after it.
 *
 * @param read Calls the server action for one page; it may close over the screen's filters.
 * @param key The response field holding the rows (`users`, `tenants`, `templates`).
 * @param transform Maps each row as it arrives (number coercion, for instance).
 * @returns The list state and its actions.
 */
export function useAdminPagedList<Row, Extra = Record<string, unknown>>(
  read: (request: AdminPageRequest) => Promise<string>,
  key: string,
  transform?: (row: Row) => Row,
): AdminPagedList<Row, Extra> {
  const [items, setItems] = useState<Row[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [extra, setExtra] = useState<Extra | null>(null);

  const readRef = useRef(read);
  const transformRef = useRef(transform);
  useEffect(() => {
    readRef.current = read;
    transformRef.current = transform;
  });
  const cursorRef = useRef<string | null>(null);
  const sequenceRef = useRef(0);

  const fetchPage = useCallback(
    async (cursor: string | null) => {
      const data = JSON.parse(await readRef.current({ cursor })) as Record<string, unknown>;
      if (!data?.success) return null;
      const rows = Array.isArray(data[key]) ? (data[key] as Row[]) : [];
      const map = transformRef.current;
      return {
        rows: map ? rows.map(map) : rows,
        hasMore: data.hasMore === true && typeof data.nextCursor === 'string',
        nextCursor: typeof data.nextCursor === 'string' ? data.nextCursor : null,
        data,
      };
    },
    [key],
  );

  const reload = useCallback(async () => {
    const sequence = (sequenceRef.current += 1);
    const page = await fetchPage(null);
    if (sequence !== sequenceRef.current) return page !== null;
    if (!page) return false;
    cursorRef.current = page.nextCursor;
    setItems(page.rows);
    setHasMore(page.hasMore);
    setExtra(page.data as Extra);
    return true;
  }, [fetchPage]);

  const loadMore = useCallback(async () => {
    const cursor = cursorRef.current;
    if (!cursor) return;
    const sequence = sequenceRef.current;
    setLoadingMore(true);
    try {
      const page = await fetchPage(cursor);
      if (sequence !== sequenceRef.current || !page) return;
      cursorRef.current = page.nextCursor;
      setItems((current) => [...current, ...page.rows]);
      setHasMore(page.hasMore);
    } catch (error) {
      console.error('Error loading more rows:', error);
    } finally {
      setLoadingMore(false);
    }
  }, [fetchPage]);

  const clear = useCallback(() => {
    sequenceRef.current += 1;
    cursorRef.current = null;
    setItems([]);
    setHasMore(false);
    setExtra(null);
  }, []);

  return { items, hasMore, loadingMore, extra, reload, loadMore, clear };
}

/**
 * Run `effect` a short while after `value` last changed — not on the first render.
 *
 * @param value The search text (or any filter) being watched.
 * @param effect What to do once it settles.
 */
export function useSettledChange(value: unknown, effect: () => void): void {
  const effectRef = useRef(effect);
  useEffect(() => {
    effectRef.current = effect;
  });
  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return undefined;
    }
    const timer = setTimeout(() => effectRef.current(), ADMIN_SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [value]);
}

/** Props of {@link AdminLoadMore}. */
export interface AdminLoadMoreProps {
  /** The list being paged. */
  list: Pick<AdminPagedList<unknown>, 'items' | 'hasMore' | 'loadingMore' | 'loadMore'>;
  /** What the rows are, plural (`users`). */
  noun: string;
  /** `data-testid` of the row; the button's is `<testId>-button`. */
  testId: string;
}

/**
 * The row under a paged list: how many rows are loaded, and the button that reads the next
 * page. Draws nothing once everything is loaded, so a short list looks as it always has.
 *
 * @param props See {@link AdminLoadMoreProps}.
 * @returns The row, or `null` when there is no further page.
 */
export function AdminLoadMore({ list, noun, testId }: AdminLoadMoreProps) {
  if (!list.hasMore) return null;
  return (
    <div className="flex items-center justify-between gap-3 p-4" data-testid={testId}>
      <span className="text-xs text-gray-500 dark:text-gray-400" aria-live="polite">
        Showing the first {list.items.length} {noun}
      </span>
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={list.loadingMore}
        title={list.loadingMore ? `Loading the next page of ${noun}` : undefined}
        onClick={() => void list.loadMore()}
        data-testid={`${testId}-button`}
      >
        {list.loadingMore ? 'Loading…' : 'Load more'}
      </Button>
    </div>
  );
}
