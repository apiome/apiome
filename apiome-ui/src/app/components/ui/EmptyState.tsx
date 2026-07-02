'use client';

import * as React from 'react';
import { cn } from '../../../../lib/utils';

type EmptyStateVariant = 'default' | 'compact';

export interface EmptyStateProps extends React.HTMLAttributes<HTMLDivElement> {
  icon?: React.ReactNode;
  title: string;
  description?: React.ReactNode;
  action?: React.ReactNode;
  variant?: EmptyStateVariant;
  showOrbs?: boolean;
  iconContainerClassName?: string;
}

export const EmptyState = React.forwardRef<HTMLDivElement, EmptyStateProps>(
  (
    {
      className,
      icon,
      title,
      description,
      action,
      variant = 'default',
      showOrbs = true,
      iconContainerClassName,
      ...props
    },
    ref
  ) => {
    const isCompact = variant === 'compact';

    return (
      <div
        ref={ref}
        className={cn(
          'relative overflow-hidden',
          // Decorative orbs use negative offsets; clip them so ancestors with overflow-y-auto
          // (e.g. dashboard main) do not show spurious scrollbars around short empty states.
          className
        )}
        {...props}
      >
        {showOrbs && !isCompact && (
          <>
            <div className="absolute -top-10 -left-10 h-40 w-40 rounded-full bg-gradient-to-br from-blue-100 to-indigo-100 opacity-60 blur-3xl dark:from-blue-900/20 dark:to-indigo-900/20" />
            <div className="absolute -bottom-10 -right-10 h-40 w-40 rounded-full bg-gradient-to-br from-indigo-100 to-purple-100 opacity-60 blur-3xl dark:from-indigo-900/20 dark:to-purple-900/20" />
          </>
        )}

        <div
          className={cn(
            'relative rounded-2xl border border-gray-200/50 bg-white/80 text-center shadow-xl backdrop-blur-sm dark:border-gray-700/50 dark:bg-gray-800/80',
            isCompact ? 'p-10' : 'p-16'
          )}
        >
          {icon ? (
            <div
              className={cn(
                'mx-auto mb-6 flex h-20 w-20 items-center justify-center rounded-2xl bg-gradient-to-br from-blue-500 to-indigo-600 text-white shadow-lg shadow-blue-500/30',
                isCompact && 'h-16 w-16',
                iconContainerClassName
              )}
            >
              {icon}
            </div>
          ) : null}

          <h3 className={cn('font-bold text-gray-900 dark:text-white', isCompact ? 'text-xl mb-2' : 'text-2xl mb-3')}>
            {title}
          </h3>

          {description ? (
            <p className={cn('mx-auto text-gray-500 dark:text-gray-400', isCompact ? 'max-w-lg text-sm' : 'max-w-md')}>
              {description}
            </p>
          ) : null}

          {action ? <div className="mt-6 flex justify-center">{action}</div> : null}
        </div>
      </div>
    );
  }
);

EmptyState.displayName = 'EmptyState';

