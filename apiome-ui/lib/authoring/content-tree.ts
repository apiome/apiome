/**
 * Content tree model and keyboard navigation (UXE-1.3).
 *
 * Scribe's content tree, Slate's structure panel and the release detail's
 * changed-page list are the same widget with different data. The WAI-ARIA tree
 * keyboard contract is subtle enough that three independent implementations
 * would be three different sets of bugs, so it is implemented once, here, as
 * pure functions over a flattened row list.
 *
 * Flattening is the key idea: a tree is rendered as a flat list of visible rows
 * with a `level`, which is both what `aria-level` needs and what makes
 * Arrow-key movement a simple index walk.
 */

import type { AuthoringTone } from './tokens';

/** One node in a content tree. */
export type AuthoringTreeNode = {
  id: string;
  label: string;
  /** Kind shown as a secondary cue, e.g. `Operation`, `Guide`, `Page`. */
  kind?: string;
  /** Status tone for the node, e.g. stale content. Always paired with `statusLabel`. */
  tone?: AuthoringTone;
  /** Text for the node's status, so status is never colour-only. */
  statusLabel?: string;
  /** Icon name resolved on the client. */
  icon?: string;
  children?: readonly AuthoringTreeNode[];
};

/** A visible row produced by flattening a tree. */
export type AuthoringTreeRow = {
  node: AuthoringTreeNode;
  /** 1-based depth, matching `aria-level`. */
  level: number;
  /** 1-based position among siblings, matching `aria-posinset`. */
  position: number;
  /** Sibling count, matching `aria-setsize`. */
  setSize: number;
  /** True when the node has children. `undefined` maps to no `aria-expanded`. */
  expandable: boolean;
  expanded: boolean;
  /** Ids of every ancestor, nearest last. Used to reveal a node on selection. */
  ancestorIds: readonly string[];
};

/**
 * Flatten a tree to the rows currently visible.
 *
 * Children of a collapsed node are omitted entirely rather than hidden with
 * CSS, so they cannot be reached by keyboard or announced by a screen reader
 * while invisible.
 *
 * @param nodes - Root nodes.
 * @param expandedIds - Ids of expanded nodes.
 * @returns Visible rows in document order.
 */
export function flattenAuthoringTree(
  nodes: readonly AuthoringTreeNode[],
  expandedIds: ReadonlySet<string>
): AuthoringTreeRow[] {
  const rows: AuthoringTreeRow[] = [];

  const walk = (siblings: readonly AuthoringTreeNode[], level: number, ancestorIds: string[]) => {
    siblings.forEach((node, index) => {
      const expandable = Boolean(node.children && node.children.length > 0);
      const expanded = expandable && expandedIds.has(node.id);

      rows.push({
        node,
        level,
        position: index + 1,
        setSize: siblings.length,
        expandable,
        expanded,
        ancestorIds: [...ancestorIds],
      });

      if (expanded) walk(node.children!, level + 1, [...ancestorIds, node.id]);
    });
  };

  walk(nodes, 1, []);
  return rows;
}

/** What a key press should do to the tree. */
export type AuthoringTreeCommand =
  | { type: 'focus'; nodeId: string }
  | { type: 'expand'; nodeId: string }
  | { type: 'collapse'; nodeId: string }
  | { type: 'activate'; nodeId: string }
  | { type: 'none' };

/**
 * Resolve a key press against the visible rows.
 *
 * Implements the WAI-ARIA tree pattern: Up/Down move by visible row, Right
 * expands then descends, Left collapses then ascends to the parent, Home/End
 * jump to the ends, and Enter or Space activates. Returning a command rather
 * than mutating keeps the whole contract unit-testable without a DOM.
 *
 * @param rows - Currently visible rows.
 * @param focusedId - Id of the row holding tabindex 0.
 * @param key - `KeyboardEvent.key`.
 * @returns The command to apply, or `none` when the key is not ours to claim.
 */
export function resolveAuthoringTreeKey(
  rows: readonly AuthoringTreeRow[],
  focusedId: string | undefined,
  key: string
): AuthoringTreeCommand {
  if (rows.length === 0) return { type: 'none' };

  const index = rows.findIndex((row) => row.node.id === focusedId);
  // An unknown or absent focus starts at the first row, so the tree is usable
  // as soon as it receives focus rather than requiring a click first.
  const current = index >= 0 ? index : 0;
  const row = rows[current];

  switch (key) {
    case 'ArrowDown':
      return current < rows.length - 1
        ? { type: 'focus', nodeId: rows[current + 1].node.id }
        : { type: 'none' };

    case 'ArrowUp':
      return current > 0 ? { type: 'focus', nodeId: rows[current - 1].node.id } : { type: 'none' };

    case 'ArrowRight':
      if (row.expandable && !row.expanded) return { type: 'expand', nodeId: row.node.id };
      if (row.expanded && current < rows.length - 1)
        return { type: 'focus', nodeId: rows[current + 1].node.id };
      return { type: 'none' };

    case 'ArrowLeft': {
      if (row.expandable && row.expanded) return { type: 'collapse', nodeId: row.node.id };
      const parentId = row.ancestorIds[row.ancestorIds.length - 1];
      return parentId ? { type: 'focus', nodeId: parentId } : { type: 'none' };
    }

    case 'Home':
      return { type: 'focus', nodeId: rows[0].node.id };

    case 'End':
      return { type: 'focus', nodeId: rows[rows.length - 1].node.id };

    case 'Enter':
    case ' ':
      return { type: 'activate', nodeId: row.node.id };

    default:
      return { type: 'none' };
  }
}

/**
 * Expand every ancestor of a node so it becomes visible.
 *
 * Used when selection arrives from elsewhere — a command palette result, a
 * canvas click — and the tree must reveal the target rather than silently not
 * showing it.
 *
 * @param nodes - Root nodes.
 * @param expandedIds - Currently expanded ids.
 * @param nodeId - Node to reveal.
 * @returns A new expanded set including every ancestor of `nodeId`.
 */
export function revealAuthoringTreeNode(
  nodes: readonly AuthoringTreeNode[],
  expandedIds: ReadonlySet<string>,
  nodeId: string
): Set<string> {
  const next = new Set(expandedIds);

  const walk = (siblings: readonly AuthoringTreeNode[], ancestors: string[]): boolean => {
    for (const node of siblings) {
      if (node.id === nodeId) {
        ancestors.forEach((id) => next.add(id));
        return true;
      }
      if (node.children && walk(node.children, [...ancestors, node.id])) return true;
    }
    return false;
  };

  walk(nodes, []);
  return next;
}
