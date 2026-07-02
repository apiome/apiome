'use client';

import * as React from 'react';
import { cn } from '../../../../lib/utils';

export interface FormFieldProps {
  label?: string;
  helperText?: string;
  error?: string;
  required?: boolean;
  className?: string;
  children: React.ReactNode;
}

export const FormField = React.forwardRef<HTMLDivElement, FormFieldProps>(
  ({ label, helperText, error, required, className, children }, ref) => {
    return (
      <div ref={ref} className={cn('space-y-2', className)}>
        {label && (
          <label className="text-sm font-medium tracking-[0.01em] text-slate-700 dark:text-slate-300">
            {label}
            {required && <span className="ml-1 text-red-600 dark:text-red-400">*</span>}
          </label>
        )}
        {children}
        {(helperText || error) && (
          <p
            className={cn(
              'text-xs leading-5',
              error ? 'text-red-600 dark:text-red-400' : 'text-slate-500 dark:text-slate-400'
            )}
          >
            {error || helperText}
          </p>
        )}
      </div>
    );
  }
);
FormField.displayName = 'FormField';

