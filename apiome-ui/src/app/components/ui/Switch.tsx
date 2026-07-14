'use client';

import * as React from 'react';
import { cn } from '../../../../lib/utils';

export interface SwitchProps extends Omit<
  React.InputHTMLAttributes<HTMLInputElement>,
  'onChange' | 'type'
> {
  checked?: boolean;
  /** Tri-state mixed (partial group). Surfaces as `aria-checked="mixed"`. */
  indeterminate?: boolean;
  onCheckedChange?: (checked: boolean) => void;
}

const Switch = React.forwardRef<HTMLInputElement, SwitchProps>(
  ({ className, checked, indeterminate = false, onCheckedChange, disabled, ...props }, ref) => {
    const inputRef = React.useRef<HTMLInputElement | null>(null);

    React.useImperativeHandle(ref, () => inputRef.current as HTMLInputElement);

    React.useEffect(() => {
      if (inputRef.current) {
        inputRef.current.indeterminate = indeterminate;
      }
    }, [indeterminate]);

    const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
      onCheckedChange?.(e.target.checked);
    };

    return (
      <label
        className={cn(
          'relative inline-flex items-center cursor-pointer',
          disabled && 'cursor-not-allowed opacity-50'
        )}
      >
        <input
          type="checkbox"
          role="switch"
          ref={inputRef}
          checked={checked}
          onChange={handleChange}
          disabled={disabled}
          aria-checked={indeterminate ? 'mixed' : Boolean(checked)}
          className="sr-only peer"
          {...props}
        />
        <div
          className={cn(
            'w-11 h-6 rounded-full transition-colors duration-200',
            'bg-gray-200 dark:bg-gray-700',
            'peer-checked:bg-emerald-500',
            indeterminate && 'bg-emerald-400 dark:bg-emerald-600',
            'peer-focus:ring-2 peer-focus:ring-offset-2 peer-focus:ring-emerald-500 peer-focus:ring-offset-white dark:peer-focus:ring-offset-gray-900',
            className
          )}
        >
          <div
            className={cn(
              'absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white shadow-sm transition-transform duration-200',
              (checked || indeterminate) && 'translate-x-5'
            )}
          />
        </div>
      </label>
    );
  }
);
Switch.displayName = 'Switch';

export { Switch };

