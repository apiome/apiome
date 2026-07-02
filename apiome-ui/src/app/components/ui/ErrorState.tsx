'use client';

import * as React from 'react';
import { AlertTriangle } from 'lucide-react';
import { cn } from '../../../../lib/utils';
import { Button } from './Button';

type ErrorStateVariant = 'default' | 'compact';

export interface ErrorStateProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Headline (default `Something went wrong`). */
  title?: string;
  /** Detail message — typically the caught error's message. */
  description?: React.ReactNode;
  /** Replace the default warning icon. */
  icon?: React.ReactNode;
  /** When given, renders a "Try again" button wired to this handler. */
  onRetry?: () => void;
  /** Label for the retry button (default `Try again`). */
  retryLabel?: string;
  /** Extra action rendered next to (or instead of) the retry button. */
  action?: React.ReactNode;
  variant?: ErrorStateVariant;
}

/**
 * `<ErrorState>` — the shared error placeholder that completes the empty / loading / error trio
 * alongside {@link EmptyState} and {@link LoadingState}. A red-tinted icon, a title + description,
 * and an optional retry affordance. Used wherever an MCP panel fails to load (endpoint, lint
 * report, versions). Token-driven: colors come from the shared red scale, no literals in consumers.
 */
export const ErrorState = React.forwardRef<HTMLDivElement, ErrorStateProps>(
  (
    {
      className,
      title = 'Something went wrong',
      description,
      icon,
      onRetry,
      retryLabel = 'Try again',
      action,
      variant = 'default',
      ...props
    },
    ref,
  ) => {
    const isCompact = variant === 'compact';
    return (
      <div
        ref={ref}
        role="alert"
        className={cn(
          'rounded-2xl border border-red-200 bg-red-50/60 text-center dark:border-red-900/50 dark:bg-red-900/10',
          isCompact ? 'p-8' : 'p-12',
          className,
        )}
        {...props}
      >
        <div
          className={cn(
            'mx-auto mb-4 flex items-center justify-center rounded-2xl bg-red-100 text-red-600 dark:bg-red-900/40 dark:text-red-300',
            isCompact ? 'h-12 w-12' : 'h-16 w-16',
          )}
        >
          {icon ?? <AlertTriangle className={isCompact ? 'h-6 w-6' : 'h-8 w-8'} aria-hidden />}
        </div>
        <h3
          className={cn(
            'font-bold text-gray-900 dark:text-white',
            isCompact ? 'mb-1 text-lg' : 'mb-2 text-xl',
          )}
        >
          {title}
        </h3>
        {description ? (
          <p className="mx-auto max-w-md text-sm text-gray-600 dark:text-gray-300">{description}</p>
        ) : null}
        {onRetry || action ? (
          <div className="mt-5 flex flex-wrap items-center justify-center gap-2">
            {onRetry ? (
              <Button type="button" variant="outline" size="sm" onClick={onRetry}>
                {retryLabel}
              </Button>
            ) : null}
            {action}
          </div>
        ) : null}
      </div>
    );
  },
);
ErrorState.displayName = 'ErrorState';
