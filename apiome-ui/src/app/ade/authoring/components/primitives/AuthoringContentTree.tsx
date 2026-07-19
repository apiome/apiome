'use client';

/**
 * The shared content tree (UXE-1.3).
 *
 * Scribe's content tree, Slate's structure panel and a release's changed-page
 * list are one widget. The WAI-ARIA tree pattern it implements — roving
 * tabindex, Arrow navigation, Home/End, Enter to activate — lives in
 * `@lib/authoring/content-tree` as pure functions, so the contract is tested
 * without a DOM and this component stays a thin renderer over it.
 *
 * Roving tabindex, not `tabindex="0"` per row: a 400-node tree must cost one
 * Tab stop, not four hundred (§27.4, keyboard-complete flows).
 */

import * as React from 'react';
import {
  flattenAuthoringTree,
  resolveAuthoringTreeKey,
  type AuthoringTreeNode,
} from '@lib/authoring/content-tree';
import { cn } from '@lib/utils';
import {
  authoringFocusClass,
  authoringMotionClass,
  authoringToneTextClass,
  authoringTreeRowClass,
  authoringTreeRowSelectedClass,
} from '../../authoringClasses';
import AuthoringIcon from '../AuthoringIcon';

/** Props for {@link AuthoringContentTree}. */
export type AuthoringContentTreeProps = {
  nodes: readonly AuthoringTreeNode[];
  /** Accessible name for the tree, e.g. `Scribe content`. */
  label: string;
  /** Id of the selected node, if any. */
  selectedId?: string;
  /** Ids of expanded nodes. Controlled by the owning surface. */
  expandedIds: ReadonlySet<string>;
  onExpandedChange: (expandedIds: Set<string>) => void;
  onSelect: (nodeId: string) => void;
  className?: string;
};

/**
 * Render a keyboard-complete content tree.
 *
 * @param props - Nodes, selection, expansion and their handlers.
 */
export default function AuthoringContentTree({
  nodes,
  label,
  selectedId,
  expandedIds,
  onExpandedChange,
  onSelect,
  className,
}: AuthoringContentTreeProps) {
  const rows = React.useMemo(
    () => flattenAuthoringTree(nodes, expandedIds),
    [nodes, expandedIds]
  );

  // Focus is tracked separately from selection: arrowing through a tree moves
  // focus without committing to a selection, which is what lets a keyboard
  // user survey it without loading every node they pass over.
  const [focusedId, setFocusedId] = React.useState<string | undefined>(
    selectedId ?? rows[0]?.node.id
  );
  const rowRefs = React.useRef(new Map<string, HTMLDivElement>());

  // If the focused row disappears — collapsed, filtered, deleted — focus must
  // land somewhere real rather than leaving the tree with no tab stop at all.
  React.useEffect(() => {
    if (rows.length === 0) return;
    if (!rows.some((row) => row.node.id === focusedId)) setFocusedId(rows[0].node.id);
  }, [rows, focusedId]);

  const toggle = React.useCallback(
    (nodeId: string, expanded: boolean) => {
      const next = new Set(expandedIds);
      if (expanded) next.add(nodeId);
      else next.delete(nodeId);
      onExpandedChange(next);
    },
    [expandedIds, onExpandedChange]
  );

  const moveFocus = React.useCallback((nodeId: string) => {
    setFocusedId(nodeId);
    rowRefs.current.get(nodeId)?.focus();
  }, []);

  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    const command = resolveAuthoringTreeKey(rows, focusedId, event.key);
    if (command.type === 'none') return;

    event.preventDefault();
    switch (command.type) {
      case 'focus':
        moveFocus(command.nodeId);
        break;
      case 'expand':
        toggle(command.nodeId, true);
        break;
      case 'collapse':
        toggle(command.nodeId, false);
        break;
      case 'activate':
        onSelect(command.nodeId);
        break;
    }
  };

  if (rows.length === 0) {
    return (
      <p className={cn('px-2 py-4 text-sm text-gray-600 dark:text-gray-300', className)}>
        Nothing to show yet. Import a version or add a guide to populate this tree.
      </p>
    );
  }

  return (
    // The tree owns keyboard handling for all of its rows; each row carries
    // role="treeitem" and a roving tabindex, per the WAI-ARIA tree pattern.
    <div
      role="tree"
      aria-label={label}
      className={cn('flex flex-col gap-0.5', className)}
      onKeyDown={onKeyDown}
    >
      {rows.map((row) => {
        const selected = row.node.id === selectedId;
        const focused = row.node.id === focusedId;

        return (
          <div
            key={row.node.id}
            ref={(element) => {
              if (element) rowRefs.current.set(row.node.id, element);
              else rowRefs.current.delete(row.node.id);
            }}
            role="treeitem"
            aria-level={row.level}
            aria-posinset={row.position}
            aria-setsize={row.setSize}
            aria-selected={selected}
            aria-expanded={row.expandable ? row.expanded : undefined}
            tabIndex={focused ? 0 : -1}
            data-node-id={row.node.id}
            onFocus={() => setFocusedId(row.node.id)}
            onClick={() => onSelect(row.node.id)}
            className={cn(
              authoringTreeRowClass,
              authoringFocusClass,
              authoringMotionClass.quick,
              selected && authoringTreeRowSelectedClass
            )}
            // Indentation is inline because the depth is data, not a fixed set
            // of classes; a tree can nest arbitrarily deep.
            style={{ paddingInlineStart: `${row.level * 0.75}rem` }}
          >
            {row.expandable ? (
              <AuthoringIcon
                name={row.expanded ? 'ChevronDown' : 'ChevronRight'}
                className="h-4 w-4 shrink-0 text-gray-400 dark:text-gray-500"
              />
            ) : (
              <span className="w-4 shrink-0" aria-hidden="true" />
            )}

            {row.node.icon ? (
              <AuthoringIcon name={row.node.icon} className="h-4 w-4 shrink-0" />
            ) : null}

            <span className="min-w-0 flex-1 truncate">{row.node.label}</span>

            {row.node.kind ? (
              <span className="shrink-0 text-xs text-gray-500 dark:text-gray-400">
                {row.node.kind}
              </span>
            ) : null}

            {/* Status is a word first; the tone only tints that word. */}
            {row.node.statusLabel ? (
              <span
                className={cn(
                  'shrink-0 text-xs font-medium',
                  authoringToneTextClass[row.node.tone ?? 'neutral']
                )}
              >
                {row.node.statusLabel}
              </span>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
