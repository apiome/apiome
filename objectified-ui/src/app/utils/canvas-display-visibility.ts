/**
 * Canvas display visibility (#483): which class nodes remain visible after hide criteria.
 */

import type { CanvasGroupForVisibility } from '@/app/utils/canvas-node-visibility';

export interface CanvasClassNodeShape {
  id: string;
  type?: string;
  data?: {
    properties?: unknown[] | null;
    schema?: { deprecated?: boolean } | null;
  };
}

export interface CanvasHideCriteriaInput {
  hideEmptyClasses: boolean;
  /** When true, hide class nodes that have no incident edges (same as "Connected" view filter). */
  hideUnconnectedClasses: boolean;
  hideDeprecatedClasses: boolean;
  /** Group IDs whose member class nodes should be hidden. */
  hiddenGroupIds: Set<string>;
}

/** Class node IDs that should still appear on the canvas (before per-node manual hide). */
export function computeClassIdsPassingHideCriteria(
  classNodes: CanvasClassNodeShape[],
  groups: CanvasGroupForVisibility[],
  connectedNodeIds: Set<string>,
  criteria: CanvasHideCriteriaInput
): Set<string> {
  const byId = new Map(groups.map((g) => [g.id, g]));
  const inHiddenGroups = new Set<string>();
  const underHiddenBranch = (groupId: string): boolean => {
    let cur = byId.get(groupId);
    while (cur) {
      if (criteria.hiddenGroupIds.has(cur.id)) return true;
      if (!cur.parentId) break;
      cur = byId.get(cur.parentId);
    }
    return false;
  };
  for (const g of groups) {
    if (underHiddenBranch(g.id)) {
      for (const id of g.nodeIds) {
        inHiddenGroups.add(id);
      }
    }
  }

  const visible = new Set<string>();
  for (const node of classNodes) {
    if (node.type === 'groupNode') continue;
    const props = node.data?.properties;
    const propCount = Array.isArray(props) ? props.length : 0;
    if (criteria.hideEmptyClasses && propCount === 0) continue;
    if (criteria.hideUnconnectedClasses && !connectedNodeIds.has(node.id)) continue;
    if (criteria.hideDeprecatedClasses && node.data?.schema?.deprecated === true) continue;
    if (inHiddenGroups.has(node.id)) continue;
    visible.add(node.id);
  }
  return visible;
}

/** Group frame is visible if any member class passes criteria or a visible nested child group does (#155). Safe against cycles via a visited set. */
export function groupNodeIdIsVisible(
  group: CanvasGroupForVisibility,
  visibleClassIds: Set<string>,
  allGroups?: CanvasGroupForVisibility[],
  _visited: Set<string> = new Set()
): boolean {
  if (_visited.has(group.id)) return false; // cycle guard
  _visited.add(group.id);

  if (group.nodeIds.some((id) => visibleClassIds.has(id))) return true;
  if (allGroups) {
    for (const cg of allGroups) {
      if (cg.parentId === group.id && groupNodeIdIsVisible(cg, visibleClassIds, allGroups, _visited)) {
        return true;
      }
    }
  }
  return false;
}

/**
 * True when any canvas visibility control is active (#485).
 * Used to enable “show all nodes” / highlight View Mode when something is restricting visibility.
 */
export function hasActiveCanvasVisibilityRestrictions(params: {
  manualHiddenNodeCount: number;
  hideEmptyClasses: boolean;
  hideUnconnectedClasses: boolean;
  hideDeprecatedClasses: boolean;
  hiddenGroupIdsCount: number;
  nodeGhostsModeEnabled: boolean;
  isolateSelectionEnabled: boolean;
  focusModeEnabled: boolean;
}): boolean {
  return (
    params.manualHiddenNodeCount > 0 ||
    params.hideEmptyClasses ||
    params.hideUnconnectedClasses ||
    params.hideDeprecatedClasses ||
    params.hiddenGroupIdsCount > 0 ||
    params.nodeGhostsModeEnabled ||
    params.isolateSelectionEnabled ||
    params.focusModeEnabled
  );
}
