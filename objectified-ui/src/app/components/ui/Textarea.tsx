'use client';

import * as React from 'react';
import { cn } from '../../../../lib/utils';

export interface TextareaProps
  extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {}

const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, ...props }, ref) => {
    return (
      <textarea
        className={cn(
          'flex min-h-[88px] w-full rounded-lg border border-slate-300/90 dark:border-slate-600',
          'bg-white/95 dark:bg-slate-800 px-3 py-2 text-sm',
          'text-slate-900 dark:text-slate-100 placeholder:text-slate-400 dark:placeholder:text-slate-500',
          'ring-offset-white dark:ring-offset-gray-900',
          'focus:outline-none focus:ring-2 focus:ring-indigo-500/80 focus:ring-offset-2',
          'disabled:cursor-not-allowed disabled:opacity-50',
          'resize-none shadow-[0_1px_2px_rgba(2,6,23,0.04)] transition-all duration-200',
          className
        )}
        ref={ref}
        {...props}
      />
    );
  }
);
Textarea.displayName = 'Textarea';

export { Textarea };

