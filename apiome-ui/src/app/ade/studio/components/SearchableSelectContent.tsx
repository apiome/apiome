'use client';

import * as React from 'react';
import * as Select from '@radix-ui/react-select';
import { cn } from '@lib/utils';

export type SearchableSelectContentProps = {
  /** Mirrors controlled `open` on `Select.Root` so the search field can be focused when the menu opens. */
  isOpen: boolean;
  searchQuery: string;
  onSearchChange: (value: string) => void;
  searchPlaceholder?: string;
  searchAriaLabel?: string;
  inputRef?: React.RefObject<HTMLInputElement | null>;
  viewportClassName?: string;
  contentClassName?: string;
  children: React.ReactNode;
};

/** Radix Select.Content with a filter field and a scrollable viewport (studio project/version pickers). */
export function SearchableSelectContent({
  isOpen,
  searchQuery,
  onSearchChange,
  searchPlaceholder = 'Search…',
  searchAriaLabel = 'Filter list',
  inputRef,
  viewportClassName,
  contentClassName,
  children,
}: SearchableSelectContentProps) {
  React.useLayoutEffect(() => {
    if (!isOpen) return;
    const id = window.requestAnimationFrame(() => inputRef?.current?.focus());
    return () => window.cancelAnimationFrame(id);
  }, [isOpen, inputRef]);

  return (
    <Select.Content
      className={cn(
        'z-[9999] flex max-h-[min(70vh,320px)] min-w-[var(--radix-select-trigger-width)] flex-col overflow-hidden rounded-lg border border-gray-200 bg-white shadow-lg dark:border-gray-700 dark:bg-gray-800',
        contentClassName
      )}
      position="popper"
      sideOffset={5}
    >
      <div className="shrink-0 border-b border-gray-200 bg-white p-2 dark:border-gray-600 dark:bg-gray-800">
        <input
          ref={inputRef}
          type="search"
          autoComplete="off"
          value={searchQuery}
          onChange={(e) => onSearchChange(e.target.value)}
          onKeyDown={(e) => e.stopPropagation()}
          placeholder={searchPlaceholder}
          aria-label={searchAriaLabel}
          className="w-full rounded-md border border-gray-200 bg-white px-2.5 py-1.5 text-sm text-gray-900 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500/30 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100 dark:placeholder:text-gray-500"
        />
      </div>
      <Select.Viewport
        className={cn('min-h-0 flex-1 overflow-y-auto overscroll-contain p-1', viewportClassName)}
      >
        {children}
      </Select.Viewport>
    </Select.Content>
  );
}
