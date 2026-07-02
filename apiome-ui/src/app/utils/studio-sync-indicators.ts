/**
 * Git-like sync helpers for Studio header chips (#2569).
 * Versions are expected newest-first (REST `ORDER BY created_at DESC`).
 */

export type StudioSyncVersionRow = {
  id: string;
  parent_version_id?: string | null;
  creator_id?: string | null;
};

/** Walk parent_version_id from the project head toward ancestors; count revisions authored by the user on the path down to `localVersionId`. */
export function countAuthoredRevisionsTowardHead(
  versionsNewestFirst: StudioSyncVersionRow[],
  localVersionId: string | null,
  currentUserId: string | undefined
): number {
  if (!versionsNewestFirst.length || !localVersionId || !currentUserId) return 0;
  const byId = new Map(versionsNewestFirst.map((v) => [v.id, v]));
  const head = versionsNewestFirst[0];
  if (!head || head.id === localVersionId) return 0;

  let current: StudioSyncVersionRow | undefined = head;
  let count = 0;
  const seen = new Set<string>();
  const maxSteps = versionsNewestFirst.length + 2;

  for (let step = 0; step < maxSteps && current; step++) {
    if (seen.has(current.id)) return 0;
    seen.add(current.id);
    if (current.id === localVersionId) break;
    if (current.creator_id === currentUserId) count++;
    const pid = current.parent_version_id;
    if (!pid) return 0;
    current = byId.get(pid);
    if (!current) return 0;
  }

  return current?.id === localVersionId ? count : 0;
}

/** True when the latest project revision differs from the selected revision (server has newer work). */
export function isRemoteHeadAheadOfSelection(
  versionsNewestFirst: StudioSyncVersionRow[],
  localVersionId: string | null
): boolean {
  const head = versionsNewestFirst[0];
  if (!head?.id || !localVersionId) return false;
  return head.id !== localVersionId;
}
