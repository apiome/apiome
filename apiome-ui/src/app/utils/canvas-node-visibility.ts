/**
 * Helpers for ADE studio canvas node/edge visibility (#482 isolate selection, etc.).
 */

export interface CanvasGroupForVisibility {
  id: string;
  nodeIds: string[];
  parentId?: string | null;
}

/** Group nodes that contain at least one of the selected class IDs (includes ancestor frames for nesting #155). */
export function getVisibleGroupIdsForSelectedClasses(
  groups: CanvasGroupForVisibility[],
  selectedClassIds: Set<string>
): Set<string> {
  const byId = new Map(groups.map((g) => [g.id, g]));
  const out = new Set<string>();
  for (const g of groups) {
    if (!g.nodeIds.some((id) => selectedClassIds.has(id))) continue;
    let cur: CanvasGroupForVisibility | undefined = g;
    while (cur) {
      out.add(cur.id);
      if (!cur.parentId) break;
      cur = byId.get(cur.parentId);
    }
  }
  return out;
}

/** Build the set of canvas node IDs visible when isolating to the given class selection. */
export function getVisibleNodeIdsForIsolateSelection(
  groups: CanvasGroupForVisibility[],
  selectedClassIds: Set<string>
): Set<string> {
  const visibleGroupIds = getVisibleGroupIdsForSelectedClasses(groups, selectedClassIds);
  return new Set<string>([...selectedClassIds, ...visibleGroupIds]);
}
