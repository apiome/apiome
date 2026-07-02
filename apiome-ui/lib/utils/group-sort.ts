/**
 * Shared topological sorter for canvas group hierarchies.
 * Used by both the server-side DB sync (lib/db/helper.ts) and the
 * client-side canvas utility (src/app/utils/canvas-nested-groups.ts).
 * No React or browser dependencies — safe to import from either context.
 */

/** Minimal interface required for topological group sorting. */
export interface GroupSortItem {
  id: string;
  parentId?: string | null;
}

/**
 * Topologically sort groups so every parent appears before its children (for DB sync inserts).
 * Safe against cycles: a group involved in a cycle is treated as depth 0 to prevent infinite recursion.
 */
export function sortGroupsParentsBeforeChildren<T extends GroupSortItem>(groups: T[]): T[] {
  const byId = new Map(groups.map((g) => [g.id, g]));
  const memo = new Map<string, number>();
  const visiting = new Set<string>();

  function depthKey(gid: string): number {
    if (memo.has(gid)) return memo.get(gid)!;
    if (visiting.has(gid)) {
      // Cycle detected — treat as depth 0 to stop recursion
      return 0;
    }
    const g = byId.get(gid);
    if (!g || !g.parentId || !byId.has(g.parentId)) {
      memo.set(gid, 0);
      return 0;
    }
    visiting.add(gid);
    const d = 1 + depthKey(g.parentId);
    visiting.delete(gid);
    memo.set(gid, d);
    return d;
  }

  return [...groups].sort((a, b) => depthKey(a.id) - depthKey(b.id));
}
