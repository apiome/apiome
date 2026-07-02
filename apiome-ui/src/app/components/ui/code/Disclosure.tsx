'use client';

import * as React from 'react';
import { Braces, ChevronRight } from 'lucide-react';
import { cn } from '../../../../../lib/utils';

export interface DisclosureProps {
  /** Header label (e.g. "Input schema" / "View diff"). */
  label: string;
  /** Optional right-aligned meta text (e.g. "12 lines"). */
  meta?: string;
  /** Optional icon next to the label; defaults to a JSON braces glyph. */
  icon?: React.ReactNode;
  defaultOpen?: boolean;
  children: React.ReactNode;
  className?: string;
}

/**
 * `<Disclosure>` — a collapsible section for heavyweight content (monaco viewers/diffs). Its children
 * mount only after the first expand (and stay mounted afterwards, hidden while closed) so a list of
 * many sections doesn't pay the editors' cost up front.
 *
 * Promoted from `ui/mcp/McpDisclosure` to `ui/code` in MFI-28.7 (#4123); `ui/mcp` keeps a back-compat
 * re-export.
 */
export function Disclosure({
  label,
  meta,
  icon,
  defaultOpen = false,
  children,
  className,
}: DisclosureProps) {
  const [open, setOpen] = React.useState(defaultOpen);
  const [everOpened, setEverOpened] = React.useState(defaultOpen);

  return (
    <div
      className={cn(
        'overflow-hidden rounded-lg border border-gray-200 dark:border-gray-700',
        className,
      )}
    >
      <button
        type="button"
        onClick={() => {
          setOpen((prev) => !prev);
          setEverOpened(true);
        }}
        aria-expanded={open}
        className="flex w-full items-center gap-2 bg-gray-50 px-3 py-2 text-left text-xs font-medium text-gray-700 transition-colors hover:bg-gray-100 dark:bg-gray-900/40 dark:text-gray-300 dark:hover:bg-gray-900/70"
      >
        <ChevronRight
          className={cn(
            'h-3.5 w-3.5 shrink-0 text-gray-400 transition-transform',
            open && 'rotate-90',
          )}
          aria-hidden
        />
        {icon ?? <Braces className="h-3.5 w-3.5 shrink-0 text-indigo-500" aria-hidden />}
        {label}
        {meta ? (
          <span className="ml-auto font-normal tabular-nums text-gray-400 dark:text-gray-500">
            {meta}
          </span>
        ) : null}
      </button>
      {everOpened ? (
        <div className={open ? 'border-t border-gray-200 dark:border-gray-700' : 'hidden'}>
          {children}
        </div>
      ) : null}
    </div>
  );
}
