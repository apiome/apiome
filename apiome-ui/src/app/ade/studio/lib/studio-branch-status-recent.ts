/**
 * Last N revisions on the main parent chain from a tip revision (#2726 GLI-07).
 * Uses `parent_version_id` only (merge parents ignored for this summary list).
 */

export type VersionLineageRow = {
  id: string;
  parent_version_id?: string | null;
  shortMessage?: string | null;
  description?: string | null;
  created_at?: string;
  creator_id?: string | null;
};

export function collectRecentRevisionsOnLineage(
  versions: VersionLineageRow[],
  tipId: string,
  limit: number
): VersionLineageRow[] {
  if (!tipId.trim() || limit <= 0) return [];
  const byId = new Map(versions.map((v) => [v.id, v]));
  const out: VersionLineageRow[] = [];
  let cur: VersionLineageRow | undefined = byId.get(tipId);
  for (let i = 0; i < limit && cur; i++) {
    out.push(cur);
    const pid = cur.parent_version_id?.trim();
    cur = pid ? byId.get(pid) : undefined;
  }
  return out;
}
