/**
 * Canvas group collapse (#154): compact group frames and hide member class nodes.
 */

export const COLLAPSED_GROUP_FRAME_WIDTH = 240;
export const COLLAPSED_GROUP_FRAME_HEIGHT = 56;

export function collapsePrefsStorageKey(userId: string, versionId: string): string {
  return `ade.canvasGroupCollapsed:v1:${userId}:${versionId}`;
}

/** Class node IDs that belong to a collapsed group or a descendant group under a collapsed ancestor (#155). */
export function getClassIdsInCollapsedGroups(
  groups: { id: string; nodeIds: string[]; parentId?: string | null }[],
  collapsedGroupIds: Set<string>
): Set<string> {
  const byId = new Map(groups.map((g) => [g.id, g]));
  const hasCollapsedAncestor = (groupId: string): boolean => {
    let cur = byId.get(groupId);
    while (cur) {
      if (collapsedGroupIds.has(cur.id)) return true;
      if (!cur.parentId) break;
      cur = byId.get(cur.parentId);
    }
    return false;
  };
  const ids = new Set<string>();
  for (const g of groups) {
    if (!hasCollapsedAncestor(g.id)) continue;
    for (const id of g.nodeIds) {
      ids.add(id);
    }
  }
  return ids;
}
