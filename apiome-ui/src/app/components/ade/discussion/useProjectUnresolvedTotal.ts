'use client';

/**
 * The project's unresolved comment-thread total, for the Versions dashboard's Discussion tab count
 * — COL-1.3 (#4515).
 *
 * The tab is drawn before its panel is opened, so the count has its own read: one `limit=1` page
 * of the project's open threads, whose `total` is apiome-rest's count of `status=open` — the same
 * rule the Studio badges and the panel's summary use. The panel pushes a fresher number through the
 * returned setter whenever its summary reloads.
 */

import { useCallback, useEffect, useState } from 'react';
import { DEFAULT_DISCUSSION_FILTERS, discussionListParams } from '@lib/comment-discussion';

/**
 * Read a project's unresolved thread total.
 *
 * @param projectId - The selected project, or empty/null for none.
 * @returns The total for that project (null until read, or when the read failed) and a setter the
 *   panel calls with a newer total.
 */
export function useProjectUnresolvedTotal(
  projectId: string | null | undefined
): [number | null, (total: number) => void] {
  const [state, setState] = useState<{ projectId: string; total: number } | null>(null);

  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    (async () => {
      try {
        const query = discussionListParams(DEFAULT_DISCUSSION_FILTERS, { limit: 1, offset: 0 });
        const res = await fetch(`/api/projects/${encodeURIComponent(projectId)}/comment-threads${query}`);
        const json = (await res.json()) as { success?: boolean; total?: unknown };
        if (cancelled || !json?.success || typeof json.total !== 'number') return;
        setState({ projectId, total: json.total });
      } catch {
        // The count is a nicety: without it the tab still opens and the panel reads its own.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const setTotal = useCallback(
    (total: number) => {
      if (projectId) setState({ projectId, total });
    },
    [projectId]
  );

  return [state && state.projectId === projectId ? state.total : null, setTotal];
}
