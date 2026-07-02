'use client';

import * as React from 'react';
import { cn } from '../../../../../../lib/utils';

/**
 * Form design-system primitives used across the Class and Property dialogs.
 *
 * Visual contract:
 * - Sections use an uppercase tracked eyebrow + an h3 title. One indigo accent
 *   by default; other accents ("amber", "orange", "purple") are reserved for
 *   semantic callouts (e.g. XML, oneOf) and must be used sparingly.
 * - Subsections are cards inside a section. They inherit the same rhythm but
 *   use a smaller icon/title and a subtle border.
 * - FieldGroup is the standard label + input + helper/error wrapper. It
 *   replaces the ad-hoc `<div className="space-y-2"><Label/>...</div>`
 *   pattern.
 */

const ACCENT_ICON: Record<AccentColor, string> = {
  indigo: 'text-indigo-500 dark:text-indigo-400',
  amber: 'text-amber-500 dark:text-amber-400',
  orange: 'text-orange-500 dark:text-orange-400',
  purple: 'text-purple-500 dark:text-purple-400',
  emerald: 'text-emerald-500 dark:text-emerald-400',
  slate: 'text-slate-500 dark:text-slate-400',
};

const ACCENT_EYEBROW: Record<AccentColor, string> = {
  indigo: 'text-indigo-600 dark:text-indigo-400',
  amber: 'text-amber-600 dark:text-amber-400',
  orange: 'text-orange-600 dark:text-orange-400',
  purple: 'text-purple-600 dark:text-purple-400',
  emerald: 'text-emerald-600 dark:text-emerald-400',
  slate: 'text-slate-500 dark:text-slate-400',
};

export type AccentColor = 'indigo' | 'amber' | 'orange' | 'purple' | 'emerald' | 'slate';

export interface FormSectionProps {
  /** Stable id used by the sidebar nav and scroll-spy. */
  id?: string;
  /** Lucide icon node (14-16px) rendered before the title. */
  icon?: React.ReactNode;
  /** Uppercase tracked eyebrow label (e.g. "Step 1", "Essentials"). */
  eyebrow?: string;
  /** Section title (h3). */
  title: string;
  /** Optional one-line description shown under the title. */
  description?: React.ReactNode;
  /** Small pill rendered to the right of the title (e.g. "Optional", "OpenAPI 3.1"). */
  badge?: React.ReactNode;
  /** Right-aligned header slot, typically an "Add" button. */
  action?: React.ReactNode;
  /** Subtle amber ring and dot signalling this section contains non-default values. */
  changed?: boolean;
  /** Color accent applied to icon and eyebrow. Defaults to indigo. */
  accent?: AccentColor;
  /** Tightens vertical padding. Use inside already-padded containers. */
  dense?: boolean;
  className?: string;
  headerClassName?: string;
  bodyClassName?: string;
  children: React.ReactNode;
}

export const FormSection = React.forwardRef<HTMLElement, FormSectionProps>(
  (
    {
      id,
      icon,
      eyebrow,
      title,
      description,
      badge,
      action,
      changed,
      accent = 'indigo',
      dense,
      className,
      headerClassName,
      bodyClassName,
      children,
    },
    ref,
  ) => {
    return (
      <section
        ref={ref}
        id={id}
        data-section-id={id}
        className={cn(
          'relative scroll-mt-24 border-b border-slate-200 dark:border-slate-800 last:border-b-0',
          dense ? 'px-6 py-5' : 'px-8 py-7',
          changed &&
            'before:absolute before:inset-y-3 before:left-0 before:w-[3px] before:rounded-r-full before:bg-amber-400/80',
          className,
        )}
      >
        <header
          className={cn(
            'mb-5 flex flex-wrap items-start justify-between gap-x-6 gap-y-2',
            headerClassName,
          )}
        >
          <div className="flex min-w-0 flex-1 flex-col gap-1">
            {eyebrow && (
              <span
                className={cn(
                  'text-[11px] font-semibold uppercase tracking-[0.1em]',
                  ACCENT_EYEBROW[accent],
                )}
              >
                {eyebrow}
              </span>
            )}
            <div className="flex flex-wrap items-center gap-2">
              {icon && (
                <span className={cn('flex h-5 w-5 shrink-0 items-center justify-center', ACCENT_ICON[accent])}>
                  {icon}
                </span>
              )}
              <h3 className="text-base font-semibold leading-6 tracking-[-0.01em] text-slate-900 dark:text-slate-100">
                {title}
              </h3>
              {changed && (
                <span
                  className="inline-flex h-1.5 w-1.5 rounded-full bg-amber-400"
                  aria-label="Contains non-default values"
                  title="Contains non-default values"
                />
              )}
              {badge && <span className="ml-1 flex items-center">{badge}</span>}
            </div>
            {description && (
              <p className="mt-1 max-w-3xl text-sm leading-5 text-slate-500 dark:text-slate-400">
                {description}
              </p>
            )}
          </div>
          {action && <div className="flex shrink-0 items-center gap-2">{action}</div>}
        </header>
        <div className={cn('space-y-5', bodyClassName)}>{children}</div>
      </section>
    );
  },
);
FormSection.displayName = 'FormSection';

export interface FormSubsectionProps {
  icon?: React.ReactNode;
  title: string;
  description?: React.ReactNode;
  badge?: React.ReactNode;
  action?: React.ReactNode;
  changed?: boolean;
  accent?: AccentColor;
  /** Slightly stronger background for chromeless fields; defaults to 'card'. */
  tone?: 'card' | 'subtle' | 'flat';
  className?: string;
  bodyClassName?: string;
  children: React.ReactNode;
}

const TONE_CLASSES: Record<NonNullable<FormSubsectionProps['tone']>, string> = {
  card: 'bg-white dark:bg-slate-900/60 border border-slate-200 dark:border-slate-800 shadow-sm',
  subtle: 'bg-slate-50 dark:bg-slate-900/40 border border-slate-200/70 dark:border-slate-800/70',
  flat: 'bg-transparent border border-dashed border-slate-300 dark:border-slate-700',
};

export const FormSubsection = React.forwardRef<HTMLDivElement, FormSubsectionProps>(
  (
    {
      icon,
      title,
      description,
      badge,
      action,
      changed,
      accent = 'indigo',
      tone = 'card',
      className,
      bodyClassName,
      children,
    },
    ref,
  ) => {
    return (
      <div
        ref={ref}
        className={cn(
          'rounded-xl p-5 transition-colors',
          TONE_CLASSES[tone],
          changed && 'ring-1 ring-amber-400/70 dark:ring-amber-400/60',
          className,
        )}
      >
        <div className="mb-4 flex flex-wrap items-start justify-between gap-x-4 gap-y-1.5">
          <div className="flex min-w-0 flex-1 flex-col gap-0.5">
            <div className="flex flex-wrap items-center gap-2">
              {icon && (
                <span className={cn('flex h-4 w-4 shrink-0 items-center justify-center', ACCENT_ICON[accent])}>
                  {icon}
                </span>
              )}
              <h4 className="text-sm font-semibold leading-5 text-slate-900 dark:text-slate-100">
                {title}
              </h4>
              {changed && (
                <span
                  className="inline-flex h-1.5 w-1.5 rounded-full bg-amber-400"
                  aria-label="Contains non-default values"
                />
              )}
              {badge && <span className="ml-1 flex items-center">{badge}</span>}
            </div>
            {description && (
              <p className="text-xs leading-5 text-slate-500 dark:text-slate-400">{description}</p>
            )}
          </div>
          {action && <div className="flex shrink-0 items-center gap-2">{action}</div>}
        </div>
        <div className={cn('space-y-4', bodyClassName)}>{children}</div>
      </div>
    );
  },
);
FormSubsection.displayName = 'FormSubsection';

export interface FormFieldGroupProps {
  label?: React.ReactNode;
  htmlFor?: string;
  helper?: React.ReactNode;
  error?: React.ReactNode;
  required?: boolean;
  /** Render label and field on a single row when true. */
  inline?: boolean;
  className?: string;
  children: React.ReactNode;
}

export const FormFieldGroup = React.forwardRef<HTMLDivElement, FormFieldGroupProps>(
  ({ label, htmlFor, helper, error, required, inline, className, children }, ref) => {
    return (
      <div
        ref={ref}
        className={cn(
          inline ? 'flex flex-wrap items-center gap-3' : 'flex flex-col gap-1.5',
          className,
        )}
      >
        {label && (
          <label
            htmlFor={htmlFor}
            className="text-sm font-medium leading-none tracking-[0.01em] text-slate-700 dark:text-slate-300"
          >
            {label}
            {required && <span className="ml-1 text-red-600 dark:text-red-400">*</span>}
          </label>
        )}
        <div className={cn(inline ? 'flex-1' : 'w-full')}>{children}</div>
        {(helper || error) && (
          <p
            className={cn(
              'text-xs leading-5',
              error ? 'text-red-600 dark:text-red-400' : 'text-slate-500 dark:text-slate-400',
              inline && 'basis-full',
            )}
          >
            {error || helper}
          </p>
        )}
      </div>
    );
  },
);
FormFieldGroup.displayName = 'FormFieldGroup';

export interface FormGridProps {
  /** Column count on md+ screens. Caller controls mobile layout via className. */
  cols?: 1 | 2 | 3 | 4;
  gap?: 'sm' | 'md' | 'lg';
  className?: string;
  children: React.ReactNode;
}

const COL_CLASS: Record<NonNullable<FormGridProps['cols']>, string> = {
  1: 'md:grid-cols-1',
  2: 'md:grid-cols-2',
  3: 'md:grid-cols-3',
  4: 'md:grid-cols-4',
};
const GAP_CLASS: Record<NonNullable<FormGridProps['gap']>, string> = {
  sm: 'gap-3',
  md: 'gap-4',
  lg: 'gap-5',
};

/** Simple grid wrapper that keeps the dialog forms on the same rhythm. */
export const FormGrid: React.FC<FormGridProps> = ({ cols = 2, gap = 'md', className, children }) => (
  <div className={cn('grid grid-cols-1', COL_CLASS[cols], GAP_CLASS[gap], className)}>{children}</div>
);

export interface FormEmptyStateProps {
  title?: string;
  description?: React.ReactNode;
  icon?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}

export const FormEmptyState: React.FC<FormEmptyStateProps> = ({
  title = 'Nothing here yet',
  description,
  icon,
  action,
  className,
}) => (
  <div
    className={cn(
      'flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-slate-300 dark:border-slate-700 bg-slate-50/60 dark:bg-slate-900/40 px-6 py-8 text-center',
      className,
    )}
  >
    {icon && <div className="text-slate-400 dark:text-slate-500">{icon}</div>}
    <p className="text-sm font-medium text-slate-700 dark:text-slate-300">{title}</p>
    {description && (
      <p className="max-w-md text-xs leading-5 text-slate-500 dark:text-slate-400">{description}</p>
    )}
    {action && <div className="pt-1">{action}</div>}
  </div>
);
