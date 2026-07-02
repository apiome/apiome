'use client';

import * as React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '../../../../../lib/utils';
import type { McpBadgeTone } from '../../ade/dashboard/mcp/mcpUiPrimitives';

/**
 * The seven-tone MCP badge — a soft tinted fill + matching text + hairline border, mirroring the
 * mockup's `.badge.*` palette. Used for transport, visibility, auth scheme, and capability
 * annotation chips. The {@link McpBadgeTone} keeps tones in lockstep with the resolver helpers in
 * `mcpUiPrimitives` (e.g. {@link mcpTransportBadge}), so a screen passes a domain value through a
 * resolver and renders the result here without choosing colors itself.
 */
const mcpBadgeVariants = cva(
  'inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-semibold whitespace-nowrap',
  {
    variants: {
      tone: {
        indigo:
          'bg-indigo-50 text-indigo-700 border-indigo-100 dark:bg-indigo-900/30 dark:text-indigo-300 dark:border-indigo-800',
        green:
          'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-900/30 dark:text-emerald-300 dark:border-emerald-800',
        amber:
          'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-900/30 dark:text-amber-300 dark:border-amber-800',
        red:
          'bg-red-50 text-red-700 border-red-200 dark:bg-red-900/30 dark:text-red-300 dark:border-red-800',
        blue:
          'bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-900/30 dark:text-blue-300 dark:border-blue-800',
        slate:
          'bg-slate-50 text-slate-600 border-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-700',
        violet:
          'bg-violet-50 text-violet-700 border-violet-200 dark:bg-violet-900/30 dark:text-violet-300 dark:border-violet-800',
      },
    },
    defaultVariants: {
      tone: 'slate',
    },
  },
);

export interface McpBadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof mcpBadgeVariants> {
  /** Semantic tone (kept null-safe: an absent tone falls back to the neutral slate default). */
  tone?: McpBadgeTone;
  /** Optional leading glyph (e.g. a small lucide icon or a status dot). */
  icon?: React.ReactNode;
}

export const McpBadge = React.forwardRef<HTMLSpanElement, McpBadgeProps>(
  ({ className, tone, icon, children, ...props }, ref) => {
    return (
      <span ref={ref} className={cn(mcpBadgeVariants({ tone }), className)} {...props}>
        {icon ? (
          <span className="inline-flex shrink-0 items-center" aria-hidden>
            {icon}
          </span>
        ) : null}
        {children}
      </span>
    );
  },
);
McpBadge.displayName = 'McpBadge';

export { mcpBadgeVariants };
