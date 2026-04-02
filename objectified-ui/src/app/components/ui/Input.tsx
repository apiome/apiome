'use client';

import * as React from 'react';
import { cn } from '../../../../lib/utils';

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {}

const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, type, ...props }, ref) => {
    return (
      <input
        type={type}
        className={cn(
          'flex h-10 w-full rounded-lg border border-slate-300/90 dark:border-slate-600',
          'bg-white/95 dark:bg-slate-800 px-3 py-2 text-sm',
          'text-slate-900 dark:text-slate-100 placeholder:text-slate-400 dark:placeholder:text-slate-500',
          'ring-offset-white dark:ring-offset-gray-900',
          'focus:outline-none focus:ring-2 focus:ring-indigo-500/80 focus:ring-offset-2',
          'disabled:cursor-not-allowed disabled:opacity-50',
          'shadow-[0_1px_2px_rgba(2,6,23,0.04)] transition-all duration-200',
          className
        )}
        ref={ref}
        {...props}
      />
    );
  }
);
Input.displayName = 'Input';

export { Input };

