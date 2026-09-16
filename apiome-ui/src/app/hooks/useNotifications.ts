'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import {
  filterMutedNotifications,
  visibleUnreadTotal,
} from '@lib/notification-preferences';
import {
  EMPTY_UNREAD_COUNTS,
  NOTIFICATION_PAGE_SIZE,
  parseUnreadCounts,
  type NotificationPage,
  type NotificationRow,
  type NotificationType,
  type NotificationUnreadCounts,
} from '@lib/notifications';

import { useNotificationPreferences } from './useNotificationPreferences';

/**
 * The notification centre's one read — COL-3.2 (#4522).
 *
 * Both surfaces share it: the rail bell (a short page, the badge) and
 * `/ade/dashboard/notifications` (a long one, with filters and paging). Written once so
 * the two can never disagree about what is unread.
 *
 * ### Why it refetches
 *
 * A notification is written by somebody *else*, on another screen, at a moment this tab
 * knows nothing about. Four things therefore reload:
 *
 * 1. the inputs changing (a different filter, a tenant switch);
 * 2. a {@link POLL_INTERVAL_MS} timer, while the tab is visible;
 * 3. the tab becoming visible again — a reader coming back from a review page should not
 *    wait out the timer;
 * 4. a caller asking, via {@link UseNotificationsResult.refresh}.
 *
 * The timer is suspended while the tab is hidden, because a background tab polling an
 * inbox once a minute forever is a cost nobody asked for; the `visibilitychange` read on
 * the way back is what makes that safe.
 *
 * ### Why muted types are filtered here
 *
 * apiome-rest's `type` filter takes a single value, and the badge needs the whole `by_type`
 * map regardless, so one unfiltered read answers both questions and the reader's switches
 * are applied to the result. The cost is that a page can come back mostly muted — which is
 * why `total` below counts rows *shown*, and the surfaces say "load more" rather than
 * claiming a number they have not drawn.
 *
 * ### Why a failure is quiet in the rail and loud on the page
 *
 * The hook reports `error` and lets the surface decide. The bell draws no badge and says
 * nothing — it is an aid, and a broken aid must not become the loudest thing in the shell —
 * while the page, whose whole job is this list, shows the message.
 */

/** How often a visible tab re-reads the inbox. */
export const POLL_INTERVAL_MS = 60_000;

/** What {@link useNotifications} is told. */
export interface UseNotificationsOptions {
  /** Skip every read — no tenant selected, or a surface with nothing to draw. */
  enabled: boolean;
  /** How many rows a page asks for. Defaults to {@link NOTIFICATION_PAGE_SIZE}. */
  limit?: number;
  /** Only rows that have not been read. */
  unreadOnly?: boolean;
  /** Only one type — the page's filter chips. Muting still applies on top. */
  type?: NotificationType | null;
  /** Poll while the tab is visible. Defaults to true. */
  poll?: boolean;
  /**
   * Read only the unread tallies, not the rows.
   *
   * What the rail bell passes while its menu is shut: the badge needs a number every
   * minute, and the twenty rows behind it are worth reading once, when the reader opens
   * the menu and can actually see them.
   */
  countsOnly?: boolean;
}

/** What {@link useNotifications} gives back. */
export interface UseNotificationsResult {
  /** The rows to draw: read, filtered by the reader's switches, newest first. */
  rows: readonly NotificationRow[];
  /** The unread tallies exactly as apiome-rest reports them. */
  counts: NotificationUnreadCounts;
  /** Unread rows of the types the reader has left on — the badge. */
  unreadTotal: number;
  /** How many rows match upstream, before muting. */
  total: number;
  /** True when more rows remain upstream than have been read. */
  hasMore: boolean;
  /** True until the first read for the current inputs has resolved. */
  loading: boolean;
  /** True while a `loadMore` is in flight. */
  loadingMore: boolean;
  /** What went wrong with the last read, or null. */
  error: string | null;
  /** Read the next page and append it. */
  loadMore: () => void;
  /** Read again now — after a write the surface made itself. */
  refresh: () => void;
  /** Mark these rows read; folds the answer's count straight into the badge. */
  markRead: (ids: readonly string[]) => Promise<void>;
  /** Mark the whole inbox read, muted types included. */
  markAllRead: () => Promise<void>;
}

/** A resolved read, remembered with the inputs that produced it. */
interface LoadedInbox {
  /** The query string it answers; a reply for older inputs is discarded. */
  key: string;
  /** Every row read so far for those inputs. */
  rows: NotificationRow[];
  /** How many match upstream. */
  total: number;
}

/** The envelope every notification BFF route answers with. */
type Envelope<T> = Partial<T> & { success?: boolean; error?: string };

/**
 * GET a BFF route and parse its envelope.
 *
 * @param url - The route, with its query.
 * @returns The parsed body.
 * @throws Error carrying the route's own message when it refused.
 */
async function getEnvelope<T>(url: string): Promise<Envelope<T>> {
  const response = await fetch(url, { cache: 'no-store' });
  const body = (await response.json().catch(() => ({}))) as Envelope<T>;
  if (!response.ok || body.success === false) {
    throw new Error(body.error || 'Failed to read notifications');
  }
  return body;
}

/**
 * The query string for one read.
 *
 * @param options - The hook's inputs.
 * @param offset - Where the page starts.
 * @returns The query, without its leading `?`.
 */
function listQuery(options: UseNotificationsOptions, offset: number): string {
  const params = new URLSearchParams();
  if (options.unreadOnly) params.set('unread', 'true');
  if (options.type) params.set('type', options.type);
  params.set('limit', String(options.limit ?? NOTIFICATION_PAGE_SIZE));
  params.set('offset', String(offset));
  return params.toString();
}

/**
 * Read the caller's inbox.
 *
 * @param options - See {@link UseNotificationsOptions}.
 * @returns See {@link UseNotificationsResult}.
 */
export function useNotifications(options: UseNotificationsOptions): UseNotificationsResult {
  const { enabled, unreadOnly = false, type = null, poll = true, countsOnly = false } = options;
  const limit = options.limit ?? NOTIFICATION_PAGE_SIZE;
  const { preferences } = useNotificationPreferences();

  const [loaded, setLoaded] = useState<LoadedInbox | null>(null);
  const [counts, setCounts] = useState<NotificationUnreadCounts>(EMPTY_UNREAD_COUNTS);
  const [error, setError] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [nonce, setNonce] = useState(0);

  /** The inputs, as one comparable string. A reply for anything else is thrown away. */
  const key = useMemo(
    () =>
      enabled
        ? `${countsOnly ? 'counts&' : ''}${listQuery({ enabled, unreadOnly, type, limit }, 0)}`
        : '',
    [enabled, unreadOnly, type, limit, countsOnly]
  );

  /** The newest inputs, for the async resolutions to compare themselves against. */
  const keyRef = useRef(key);
  keyRef.current = key;

  // The first page and the counts, together. `nonce` is what `refresh`, the poll timer and
  // the visibility listener all bump — one dependency rather than three copies of the read.
  useEffect(() => {
    if (!enabled) {
      setLoaded(null);
      setCounts(EMPTY_UNREAD_COUNTS);
      setError(null);
      return;
    }

    let cancelled = false;
    const requested = key;

    void (async () => {
      try {
        const [page, unread] = await Promise.all([
          countsOnly
            ? Promise.resolve(null)
            : getEnvelope<NotificationPage>(
                `/api/notifications?${listQuery({ enabled, unreadOnly, type, limit }, 0)}`
              ),
          getEnvelope<{ unread: NotificationUnreadCounts }>('/api/notifications/unread-count'),
        ]);
        if (cancelled || keyRef.current !== requested) return;
        if (page) {
          setLoaded({
            key: requested,
            rows: page.notifications ?? [],
            total: page.total ?? page.notifications?.length ?? 0,
          });
        }
        setCounts(parseUnreadCounts(unread.unread));
        setError(null);
      } catch (failure) {
        if (cancelled || keyRef.current !== requested) return;
        setError(failure instanceof Error ? failure.message : 'Failed to read notifications');
      }
    })();

    return () => {
      cancelled = true;
    };
    // `key` already encodes the four inputs below; they are listed because the read spells
    // them out again, and an exhaustive list is cheaper to keep true than an explanation.
  }, [enabled, key, nonce, countsOnly, unreadOnly, type, limit]);

  const refresh = useCallback(() => setNonce((value) => value + 1), []);

  // The poll, and the read on the way back to a tab that was hidden. Both only exist while
  // the hook is enabled and polling, so a surface that opts out costs nothing.
  useEffect(() => {
    if (!enabled || !poll || typeof document === 'undefined') return;

    const timer = window.setInterval(() => {
      if (document.visibilityState === 'visible') refresh();
    }, POLL_INTERVAL_MS);

    const onVisibility = () => {
      if (document.visibilityState === 'visible') refresh();
    };
    document.addEventListener('visibilitychange', onVisibility);

    return () => {
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [enabled, poll, refresh]);

  const rowsForKey = loaded?.key === key ? loaded.rows : null;

  const loadMore = useCallback(() => {
    const current = loaded;
    if (!enabled || !current || current.key !== key) return;
    if (current.rows.length >= current.total) return;

    setLoadingMore(true);
    void (async () => {
      try {
        const page = await getEnvelope<NotificationPage>(
          `/api/notifications?${listQuery({ enabled, unreadOnly, type, limit }, current.rows.length)}`
        );
        if (keyRef.current !== current.key) return;
        setLoaded((previous) => {
          // Appending to whatever is there *now*: a refresh may have replaced the page
          // while this read was in flight, and duplicating its rows would be worse than
          // dropping this one.
          if (!previous || previous.key !== current.key) return previous;
          const seen = new Set(previous.rows.map((row) => row.id));
          const added = (page.notifications ?? []).filter((row) => !seen.has(row.id));
          return {
            key: previous.key,
            rows: [...previous.rows, ...added],
            total: page.total ?? previous.total,
          };
        });
        setError(null);
      } catch (failure) {
        if (keyRef.current !== current.key) return;
        setError(failure instanceof Error ? failure.message : 'Failed to read notifications');
      } finally {
        setLoadingMore(false);
      }
    })();
  }, [enabled, key, limit, loaded, type, unreadOnly]);

  /**
   * POST a mark-read request and fold its answer back in.
   *
   * The endpoint answers with the unread count that follows, so the badge is corrected
   * from the reply rather than from a second read — and the rows already on screen are
   * stamped locally so the dot goes out in the same frame the reader clicked.
   *
   * @param body - `{ids}` or `{all: true}`.
   * @param markedIds - The ids to stamp locally; null stamps every row.
   */
  const postRead = useCallback(
    async (body: { ids: string[] } | { all: true }, markedIds: readonly string[] | null) => {
      const at = new Date().toISOString();
      try {
        const response = await fetch('/api/notifications/read', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
          cache: 'no-store',
        });
        const payload = (await response.json().catch(() => ({}))) as Envelope<{
          unread: NotificationUnreadCounts;
        }>;
        if (!response.ok || payload.success === false) {
          throw new Error(payload.error || 'Failed to mark notifications read');
        }
        setCounts(parseUnreadCounts(payload.unread));
        setError(null);

        const ids = markedIds === null ? null : new Set(markedIds);
        setLoaded((previous) =>
          previous
            ? {
                ...previous,
                rows: previous.rows.map((row) =>
                  row.read_at || (ids && !ids.has(row.id)) ? row : { ...row, read_at: at }
                ),
              }
            : previous
        );
      } catch (failure) {
        setError(
          failure instanceof Error ? failure.message : 'Failed to mark notifications read'
        );
      }
    },
    []
  );

  const markRead = useCallback(
    async (ids: readonly string[]) => {
      if (ids.length === 0) return;
      await postRead({ ids: [...ids] }, ids);
    },
    [postRead]
  );

  const markAllRead = useCallback(async () => {
    await postRead({ all: true }, null);
  }, [postRead]);

  // Muting is applied to the rows *after* they are read, so turning a type back on brings
  // its rows back without a request.
  const rows = useMemo(
    () => (rowsForKey ? filterMutedNotifications(rowsForKey, preferences) : []),
    [rowsForKey, preferences]
  );

  return {
    rows,
    counts,
    unreadTotal: visibleUnreadTotal(counts, preferences),
    total: loaded?.key === key ? loaded.total : 0,
    hasMore: Boolean(rowsForKey && loaded && loaded.rows.length < loaded.total),
    // Derived rather than a `useState`: a background refresh must not blank a list that
    // already has an answer (the rule `useOpenReviews` follows). A counts-only read has no
    // list to be waiting for.
    loading: enabled && !countsOnly && rowsForKey === null && error === null,
    loadingMore,
    error,
    loadMore,
    refresh,
    markRead,
    markAllRead,
  };
}

export default useNotifications;
