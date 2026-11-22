'use client';

/**
 * Whether a revision has nothing in it — no operations and no schemas (COA-4.3a, #7126).
 *
 * Reads the revision's rendered OpenAPI document (`GET /api/versions/{id}/document`) and asks
 * {@link isEmptyOpenApiDocument}. The Publish dialog warns on it and the lint report says
 * "nothing to score" instead of showing an empty document as A · 100.
 */

import { useEffect, useState } from 'react';

import { isEmptyOpenApiDocument } from './versionsModel';

/** `true`/`false` once known; `null` while loading, disabled, or when the read failed. */
export type VersionEmptiness = boolean | null;

/**
 * Read the revision's document and report whether it is empty.
 *
 * A failed read answers `null` (unknown), never `true`: a warning that cries "empty" on a
 * network blip would be worse than none.
 *
 * @param projectId The owning project's id.
 * @param versionId The revision's record id.
 * @param enabled Only fetch while true (a dialog being open).
 * @returns Whether the revision is empty, or `null` when unknown.
 */
export function useVersionIsEmpty(
  projectId: string | undefined,
  versionId: string | undefined,
  enabled: boolean,
): VersionEmptiness {
  const [state, setState] = useState<{ key: string; empty: boolean } | null>(null);
  const key = projectId && versionId ? `${projectId}:${versionId}` : '';

  useEffect(() => {
    if (!enabled || !key || !projectId || !versionId) return;
    const controller = new AbortController();
    fetch(
      `/api/versions/${encodeURIComponent(versionId)}/document?projectId=${encodeURIComponent(projectId)}`,
      { signal: controller.signal },
    )
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(String(res.status)))))
      .then((doc: unknown) => {
        if (!controller.signal.aborted) setState({ key, empty: isEmptyOpenApiDocument(doc) });
      })
      .catch(() => {
        if (!controller.signal.aborted) setState(null);
      });
    return () => controller.abort();
  }, [enabled, key, projectId, versionId]);

  return enabled && state && state.key === key ? state.empty : null;
}
