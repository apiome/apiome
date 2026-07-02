/**
 * Pick the revision id with the latest `created_at` among the given rows.
 * Used for "compare to current (head)" in the versions timeline (#2580).
 */
export function projectHeadRevisionId<T extends { id: string; created_at: string }>(
  versions: T[]
): string | null {
  if (versions.length === 0) return null;
  let best = versions[0];
  let bestT = new Date(best.created_at).getTime();
  for (let i = 1; i < versions.length; i++) {
    const v = versions[i];
    const t = new Date(v.created_at).getTime();
    if (t > bestT) {
      best = v;
      bestT = t;
    }
  }
  return best.id;
}
