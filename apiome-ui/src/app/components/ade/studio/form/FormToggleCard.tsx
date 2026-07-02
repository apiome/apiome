'use client';

import * as React from 'react';
import { Checkbox } from '../../../ui/Checkbox';
import { cn } from '../../../../../../lib/utils';

/**
 * Unified checkbox-card used for property flags (Required, Nullable, Read Only,
 * Write Only, Deprecated, etc). Replaces ~8 hand-rolled copies across the
 * three dialogs.
 *
 * Unchecked state is a neutral outlined card; when checked the card fills
 * with a soft accent tint so the active flags stand out at a glance.
 */
export type ToggleAccent = 'indigo' | 'emerald' | 'amber' | 'blue' | 'purple' | 'rose' | 'slate';

const ACTIVE_CARD: Record<ToggleAccent, string> = {
  indigo:
    'bg-indigo-50 dark:bg-indigo-900/20 border-indigo-300 dark:border-indigo-700',
  emerald:
    'bg-emerald-50 dark:bg-emerald-900/20 border-emerald-300 dark:border-emerald-700',
  amber:
    'bg-amber-50 dark:bg-amber-900/20 border-amber-300 dark:border-amber-700',
  blue:
    'bg-blue-50 dark:bg-blue-900/20 border-blue-300 dark:border-blue-700',
  purple:
    'bg-purple-50 dark:bg-purple-900/20 border-purple-300 dark:border-purple-700',
  rose:
    'bg-rose-50 dark:bg-rose-900/20 border-rose-300 dark:border-rose-700',
  slate:
    'bg-slate-100 dark:bg-slate-800/70 border-slate-300 dark:border-slate-600',
};

const ACTIVE_ICON: Record<ToggleAccent, string> = {
  indigo: 'text-indigo-500 dark:text-indigo-400',
  emerald: 'text-emerald-500 dark:text-emerald-400',
  amber: 'text-amber-500 dark:text-amber-400',
  blue: 'text-blue-500 dark:text-blue-400',
  purple: 'text-purple-500 dark:text-purple-400',
  rose: 'text-rose-500 dark:text-rose-400',
  slate: 'text-slate-500 dark:text-slate-400',
};

export interface FormToggleCardProps {
  id: string;
  label: React.ReactNode;
  /** Short helper shown under the label. */
  description?: React.ReactNode;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  disabled?: boolean;
  /** Leading icon (16px) shown next to the label. */
  icon?: React.ReactNode;
  /** Accent when checked. Defaults to indigo. */
  accent?: ToggleAccent;
  /** Optional trailing node (e.g. inline message input for Deprecated). */
  trailing?: React.ReactNode;
  /** Force the card to stack label + trailing vertically. */
  stack?: boolean;
  className?: string;
}

export const FormToggleCard = React.forwardRef<HTMLDivElement, FormToggleCardProps>(
  (
    {
      id,
      label,
      description,
      checked,
      onCheckedChange,
      disabled,
      icon,
      accent = 'indigo',
      trailing,
      stack,
      className,
    },
    ref,
  ) => {
    const base =
      'relative rounded-lg border px-3 py-2.5 transition-colors duration-150 focus-within:ring-2 focus-within:ring-indigo-500/60';
    const inactive =
      'bg-white dark:bg-slate-900/40 border-slate-200 dark:border-slate-800';
    return (
      <div
        ref={ref}
        className={cn(
          base,
          checked ? ACTIVE_CARD[accent] : inactive,
          disabled && 'opacity-60',
          className,
        )}
      >
        <div
          className={cn(
            stack ? 'flex flex-col gap-2.5' : 'flex items-start gap-3',
          )}
        >
          <div className="flex min-w-0 flex-1 items-start gap-2.5">
            <Checkbox
              id={id}
              checked={checked}
              onCheckedChange={(v) => onCheckedChange(!!v)}
              disabled={disabled}
              className="mt-0.5"
            />
            <label
              htmlFor={id}
              className={cn(
                'flex min-w-0 flex-1 cursor-pointer flex-col leading-tight',
                disabled && 'cursor-not-allowed',
              )}
            >
              <span className="flex items-center gap-1.5 text-sm font-medium text-slate-800 dark:text-slate-200">
                {icon && (
                  <span className={cn('inline-flex h-3.5 w-3.5 shrink-0', checked ? ACTIVE_ICON[accent] : 'text-slate-400 dark:text-slate-500')}>
                    {icon}
                  </span>
                )}
                {label}
              </span>
              {description && (
                <span className="mt-0.5 text-xs leading-4 text-slate-500 dark:text-slate-400">
                  {description}
                </span>
              )}
            </label>
          </div>
          {trailing && (
            <div className={cn(stack ? 'pl-7' : 'shrink-0')}>{trailing}</div>
          )}
        </div>
      </div>
    );
  },
);
FormToggleCard.displayName = 'FormToggleCard';
