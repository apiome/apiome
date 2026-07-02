'use client';

import * as React from 'react';
import { cn } from '../../../../lib/utils';
import { Spinner, type SpinnerProps } from './Spinner';

export interface LoadingStateProps extends React.HTMLAttributes<HTMLDivElement> {
  message?: string;
  minHeightClassName?: string;
  spinnerSize?: SpinnerProps['size'];
}

export const LoadingState = React.forwardRef<HTMLDivElement, LoadingStateProps>(
  (
    {
      className,
      message = 'Loading...',
      minHeightClassName = 'min-h-[280px]',
      spinnerSize = 'lg',
      ...props
    },
    ref
  ) => {
    return (
      <div
        ref={ref}
        className={cn('flex items-center justify-center', minHeightClassName, className)}
        {...props}
      >
        <div className="flex flex-col items-center gap-3 text-center">
          <Spinner size={spinnerSize} label={message} />
          <p className="text-sm text-gray-500 dark:text-gray-400">{message}</p>
        </div>
      </div>
    );
  }
);
LoadingState.displayName = 'LoadingState';

