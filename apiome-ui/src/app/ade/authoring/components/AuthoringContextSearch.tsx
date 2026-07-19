'use client';

/**
 * Contextual search field for an Authoring surface (UXE-1.2).
 *
 * Where the command palette searches the whole shell, this searches whatever
 * the current surface is showing. Pressing `/` anywhere outside a text field
 * moves focus here.
 *
 * The shell finds this field by the {@link AUTHORING_SEARCH_TARGET_ATTRIBUTE}
 * attribute rather than through a ref, so a surface can render its search box
 * wherever its layout needs it — including inside a portal or a lazily mounted
 * panel — without wiring anything back up to the layout.
 */

import * as React from 'react';
import { Search } from 'lucide-react';
import { cn } from '@lib/utils';
import { authoringSearchInputClass } from '../authoringClasses';

/** Attribute marking the field that `/` focuses. */
export const AUTHORING_SEARCH_TARGET_ATTRIBUTE = 'data-authoring-search';

/** Props for {@link AuthoringContextSearch}. */
export type AuthoringContextSearchProps = {
  value: string;
  onValueChange: (value: string) => void;
  /** Accessible name, e.g. `Search content`. */
  label: string;
  placeholder?: string;
  className?: string;
};

/**
 * Render the surface-scoped search field.
 *
 * @param props - Controlled value, accessible name and placeholder.
 */
export default function AuthoringContextSearch({
  value,
  onValueChange,
  label,
  placeholder = 'Search this surface…',
  className,
}: AuthoringContextSearchProps) {
  return (
    <div className={cn('relative', className)}>
      <Search
        className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400"
        aria-hidden="true"
      />
      <input
        type="search"
        value={value}
        onChange={(event) => onValueChange(event.target.value)}
        aria-label={label}
        aria-keyshortcuts="/"
        placeholder={placeholder}
        className={authoringSearchInputClass}
        {...{ [AUTHORING_SEARCH_TARGET_ATTRIBUTE]: 'true' }}
      />
    </div>
  );
}

/**
 * Move focus to the surface's search field, if it has one.
 *
 * @returns True when a field was found and focused.
 */
export function focusAuthoringContextSearch(): boolean {
  if (typeof document === 'undefined') return false;
  const field = document.querySelector<HTMLInputElement>(`[${AUTHORING_SEARCH_TARGET_ATTRIBUTE}]`);
  if (!field) return false;
  // Focus only — selecting the existing text would destroy a query the viewer
  // had already typed if the shortcut fires unintentionally.
  field.focus();
  return true;
}
