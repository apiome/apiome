'use client';

/**
 * How many Arazzo workflows a revision holds (COA-1.3, #7039).
 *
 * The project Versions page shows its **Workflows** tab only for a project that has workflows,
 * and a project row carries no format to tell it; so this reads the revision's workflows once
 * per revision and reports the count. Any failure counts as "none" — a project whose workflows
 * cannot be read simply shows no tab, rather than a tab that opens on an error.
 */

import { useEffect, useState } from 'react';
import { parseArazzoWorkflows } from './arazzoWorkflowModel';

/**
 * Count a revision's workflows.
 *
 * @param versionId The revision (`versions.id`) to read, or `null` while there is none.
 * @returns The workflow count once read; `0` while loading, on failure, or with no revision.
 */
export function useArazzoWorkflowCount(versionId: string | null): number {
  const [count, setCount] = useState<{ versionId: string | null; value: number }>({ versionId: null, value: 0 });

  useEffect(() => {
    if (!versionId) return;
    let cancelled = false;
    fetch(`/api/workflows/versions/${encodeURIComponent(versionId)}`)
      .then(async (response) => {
        const body = response.ok ? await response.json().catch(() => ({})) : {};
        const value = body?.success === false ? 0 : parseArazzoWorkflows(body?.workflows).workflows.length;
        if (!cancelled) setCount({ versionId, value });
      })
      .catch(() => {
        if (!cancelled) setCount({ versionId, value: 0 });
      });
    return () => {
      cancelled = true;
    };
  }, [versionId]);

  // A count read for an earlier revision never leaks onto the current one.
  return versionId && count.versionId === versionId ? count.value : 0;
}
