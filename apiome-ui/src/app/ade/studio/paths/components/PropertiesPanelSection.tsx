'use client';

import * as React from 'react';
import { ChevronDown } from 'lucide-react';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '../../../../components/ui/Collapsible';
import { pathsTheme } from './paths-theme';

interface PropertiesPanelSectionProps {
  /** Section title (shown in the uppercase muted style). */
  title: React.ReactNode;
  /** Optional count pill next to the title (e.g. number of parameters). */
  count?: number;
  /** Optional inline icon rendered before the title. */
  icon?: React.ReactNode;
  /** Right-aligned actions rendered in the section header (e.g. + Add). */
  actions?: React.ReactNode;
  /** Extra descriptive text below the title (helper copy). */
  description?: React.ReactNode;
  /** Whether the section starts expanded. Defaults to true. */
  defaultOpen?: boolean;
  /** Controlled open state. */
  open?: boolean;
  /** Controlled-open change handler. */
  onOpenChange?: (open: boolean) => void;
  /** Section content. */
  children: React.ReactNode;
  /** Optional extra className applied to the outer wrapper. */
  className?: string;
}

/**
 * Collapsible section used inside a PropertiesPanelShell. Provides the
 * canonical `{title}{count}{actions}` row + chevron used across the
 * Paths panels for progressive disclosure of nested concerns
 * (parameters, responses, security, etc.).
 */
export default function PropertiesPanelSection({
  title,
  count,
  icon,
  actions,
  description,
  defaultOpen = true,
  open,
  onOpenChange,
  children,
  className,
}: PropertiesPanelSectionProps) {
  return (
    <Collapsible
      defaultOpen={defaultOpen}
      open={open}
      onOpenChange={onOpenChange}
      className={[
        'border rounded-md',
        pathsTheme.borderSoft,
        pathsTheme.surface,
        className ?? '',
      ].join(' ')}
    >
      <div className="flex items-center gap-2 pl-2 pr-2 py-1.5">
        <CollapsibleTrigger
          className={[
            'group/section-trigger flex min-w-0 flex-1 items-center gap-2 rounded-sm py-1 pl-1 pr-2 text-left transition-colors',
            pathsTheme.hover,
          ].join(' ')}
        >
          <ChevronDown
            className={[
              'h-3.5 w-3.5 shrink-0 transition-transform',
              'group-data-[state=closed]/section-trigger:-rotate-90',
              pathsTheme.textTertiary,
            ].join(' ')}
            strokeWidth={2.25}
          />
          {icon != null && (
            <span className={['shrink-0 [&>svg]:w-3.5 [&>svg]:h-3.5', pathsTheme.textSecondary].join(' ')}>
              {icon}
            </span>
          )}
          <span
            className={[
              'truncate',
              pathsTheme.sectionLabel,
              'text-slate-600 dark:text-slate-300',
            ].join(' ')}
          >
            {title}
          </span>
          {typeof count === 'number' && (
            <span
              className={[
                'shrink-0 rounded-full px-1.5 py-[1px] text-[10px] font-semibold tabular-nums',
                count > 0
                  ? 'bg-indigo-50 text-indigo-700 dark:bg-indigo-950/50 dark:text-indigo-300'
                  : 'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400',
              ].join(' ')}
            >
              {count}
            </span>
          )}
        </CollapsibleTrigger>
        {actions != null && (
          <div className="shrink-0 flex items-center gap-1">{actions}</div>
        )}
      </div>
      <CollapsibleContent className="overflow-hidden">
        <div className={['border-t', pathsTheme.borderSoft].join(' ')}>
          {description != null && (
            <div className={['px-3 pt-2.5 text-[11.5px]', pathsTheme.textSecondary].join(' ')}>{description}</div>
          )}
          <div className="px-3 py-3">{children}</div>
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}
