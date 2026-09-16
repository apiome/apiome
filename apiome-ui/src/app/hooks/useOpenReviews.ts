'use client';

/**
 * Open reviews for the status pills — COL-2.4 (#4520).
 *
 * One hook behind `GET /api/reviews/status`, shared by the Versions screen (one project) and the
 * Projects screen (the whole tenant). It hands back both shapes of the same rows — indexed by
 * revision for a version row or the publish dialog, summarised per project for a card — so no
 * screen re-derives them.
 *
 * ### Why it refetches
 *
 * The ticket's third acceptance criterion is that the states update after decisions **without
 * stale caches**, and a decision is recorded on a different page — `/ade/reviews/{id}`, usually in
 * another tab. Three things therefore reload the rows:
 *
 * 1. the inputs changing (a different project, a tenant switch);
 * 2. the tab becoming visible again, which is what a reader coming back from the review page
 *    does;
 * 3. a screen calling {@link UseOpenReviewsResult.refresh}, which is how it folds its own write —
 *    the Versions screen does after a publish.
 *
 * The request itself is `cache: 'no-store'`, so neither the browser nor Next's fetch cache can
 * answer it with a state a reviewer has already moved past.
 *
 * ### Why a failure is silent
 *
 * A pill is an aid, not the page. If the read fails the surfaces draw no pill and keep working —
 * the same rule the mock-usage sparklines follow — rather than putting an error banner on a
 * screen whose actual job succeeded.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';

import {
  indexReviewsByVersion,
  parseReviewStatusPayload,
  summarizeProjectReviews,
  type ProjectReviewSummary,
  type ReviewStatusRow,
} from '@lib/review-status';

export interface UseOpenReviewsOptions {
  /** Skip the read entirely — no tenant yet, or a screen that has nothing to draw pills on. */
  enabled: boolean;
  /** Narrow to one project. Omit (or pass null) to read the whole tenant. */
  projectId?: string | null;
}

export interface UseOpenReviewsResult {
  /** Every open review in scope; empty while loading, disabled, or after a failed read. */
  reviews: readonly ReviewStatusRow[];
  /** Those rows keyed by revision id — `null` until the first read resolves. */
  byVersionId: ReadonlyMap<string, ReviewStatusRow> | null;
  /** One summary per project that has an open review — `null` until the first read resolves. */
  byProjectId: ReadonlyMap<string, ProjectReviewSummary> | null;
  /**
   * True until the first read for the current inputs has resolved.
   *
   * A *background* refresh does not set it: the rows it will replace are still the best answer
   * there is, and a panel that blanked itself every time the tab regained focus would flicker.
   */
  loading: boolean;
  /** Read again now — for a screen folding its own write back in. */
  refresh: () => void;
}

/** What a resolved read belongs to, so a reply for the previous inputs is never served. */
interface LoadedReviews {
  key: string;
  rows: ReviewStatusRow[];
}

/**
 * Read the open reviews the calling screen needs.
 *
 * @param options - See {@link UseOpenReviewsOptions}.
 * @returns See {@link UseOpenReviewsResult}.
 */
export function useOpenReviews(options: UseOpenReviewsOptions): UseOpenReviewsResult {
  const { enabled, projectId = null } = options;
  const [loaded, setLoaded] = useState<LoadedReviews | null>(null);
  const [nonce, setNonce] = useState(0);

  // Identifies the inputs a loaded set belongs to. While this and `loaded.key` disagree the hook
  // reports `null`, so a project switch cannot flash the previous project's pills.
  const scopeKey = enabled ? `${projectId ?? ''}` : null;

  const refresh = useCallback(() => setNonce((value) => value + 1), []);

  useEffect(() => {
    if (scopeKey === null) return;
    let cancelled = false;

    const load = async () => {
      let rows: ReviewStatusRow[] = [];
      try {
        const query = projectId ? `?projectId=${encodeURIComponent(projectId)}` : '';
        const response = await fetch(`/api/reviews/status${query}`, { cache: 'no-store' });
        const payload = await response.json().catch(() => null);
        if (response.ok && payload?.success) rows = parseReviewStatusPayload(payload);
      } catch {
        // Silent: see the module note. `rows` stays empty and the surfaces draw no pill.
      }
      if (cancelled) return;
      setLoaded({ key: scopeKey, rows });
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [projectId, scopeKey, nonce]);

  // A reviewer decides on `/ade/reviews/{id}` and comes back to this tab; without this the pill
  // would still read "In review" until the next navigation.
  useEffect(() => {
    if (scopeKey === null || typeof document === 'undefined') return;
    const onVisible = () => {
      if (document.visibilityState === 'visible') refresh();
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => document.removeEventListener('visibilitychange', onVisible);
  }, [refresh, scopeKey]);

  const rows = loaded && loaded.key === scopeKey ? loaded.rows : null;

  const byVersionId = useMemo(() => (rows ? indexReviewsByVersion(rows) : null), [rows]);
  const byProjectId = useMemo(() => (rows ? summarizeProjectReviews(rows) : null), [rows]);

  return {
    reviews: rows ?? [],
    byVersionId,
    byProjectId,
    loading: scopeKey !== null && rows === null,
    refresh,
  };
}

export default useOpenReviews;
