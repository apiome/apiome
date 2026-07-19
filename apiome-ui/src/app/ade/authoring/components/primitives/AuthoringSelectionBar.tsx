'use client';

/**
 * The shared multiselect bar (UXE-1.3).
 *
 * §27.2 requires tree, table and canvas selection to share "multiselect, bulk
 * actions and a visible selection bar". Visible is the operative word: the bar
 * is rendered in flow rather than floating over content, so it cannot obscure
 * the rows it acts on or trap focus behind a sticky header (§27.4).
 */

import * as React from 'react';
import {
  gateAuthoringBulkActions,
  summarizeAuthoringSelection,
  type AuthoringCommandAction,
} from '@lib/authoring/actions';
import { cn } from '@lib/utils';
import { authoringFocusClass, authoringSurfaceClass } from '../../authoringClasses';
import AuthoringActionButton from './AuthoringActionButton';

/** Props for {@link AuthoringSelectionBar}. */
export type AuthoringSelectionBarProps = {
  selectedCount: number;
  totalCount: number;
  /** Singular noun for the items, e.g. `page`. Used in every announcement. */
  noun: string;
  /** Bulk actions. Disabled with a shared reason when nothing is selected. */
  actions: readonly AuthoringCommandAction[];
  onAction: (actionId: string) => void;
  /** Clears the selection. Omit when the surface has no clear affordance. */
  onClear?: () => void;
  className?: string;
};

/**
 * Render the selection summary and its bulk actions.
 *
 * @param props - Selection counts, the noun, and the actions offered.
 */
export default function AuthoringSelectionBar({
  selectedCount,
  totalCount,
  noun,
  actions,
  onAction,
  onClear,
  className,
}: AuthoringSelectionBarProps) {
  const summary = summarizeAuthoringSelection(selectedCount, totalCount, noun);
  const gated = gateAuthoringBulkActions(actions, selectedCount, noun);

  return (
    <div
      className={cn(
        authoringSurfaceClass,
        'flex flex-wrap items-center gap-3 px-3 py-2',
        className
      )}
      data-selected-count={selectedCount}
    >
      {/*
       * The count is announced politely on change. Assertive would interrupt
       * the user mid-selection, which is precisely when they are least helped
       * by being interrupted.
       */}
      <span role="status" aria-live="polite" className="text-sm font-medium text-gray-900 dark:text-white">
        {summary.label}
        <span className="sr-only"> — {summary.announcement}</span>
      </span>

      <div className="flex flex-wrap items-start gap-2">
        {gated.map((action) => (
          <AuthoringActionButton key={action.id} action={action} onAction={onAction} />
        ))}
      </div>

      {onClear ? (
        <button
          type="button"
          onClick={onClear}
          className={cn(
            'ml-auto min-h-9 rounded-lg px-3 text-sm text-gray-600 hover:text-gray-900 dark:text-gray-300 dark:hover:text-white',
            authoringFocusClass
          )}
        >
          Clear selection
        </button>
      ) : null}
    </div>
  );
}
