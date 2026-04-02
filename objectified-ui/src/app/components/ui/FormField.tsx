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
          <label className="text-sm font-medium text-slate-700 dark:text-slate-300 tracking-[0.01em]">
            {label}
            {required && <span className="text-red-500 ml-1">*</span>}
          </label>
        )}
        {children}
        {(helperText || error) && (
          <p className={cn(
            'text-xs',
            error ? 'text-red-500' : 'text-slate-500 dark:text-slate-400'
          )}>
            {error || helperText}
          </p>
        )}
      </div>
    );
  }
);
FormField.displayName = 'FormField';

