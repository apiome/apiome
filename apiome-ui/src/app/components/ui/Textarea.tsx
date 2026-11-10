'use client';

import * as React from 'react';
import { cn } from '../../../../lib/utils';
import { CONTROL_FIELD_CLASS } from './Input';
import { textareaSizeVariants, useFieldSize, type FieldSize } from './controlSize';

/** Props of {@link Textarea}. */
export interface TextareaProps
  extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  /**
   * Padding, text and radius step, matching `Input`'s (SUX-1.2). Defaults to the surrounding
   * `FormField`'s size, else `md`. The height stays a growing `min-h-24` at every size.
   */
  size?: FieldSize;
}

/**
 * Textarea — the Hive multi-line field (HIVE-2.1, #5280).
 *
 * The same chrome as {@link Input} (hive.css §9 `.textarea`), with its own vertical padding
 * and a `min-height` of six `--space-4` units rather than a fixed control height, so it
 * still grows with the font-size preference.
 */
const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, size, ...props }, ref) => {
    const resolvedSize = useFieldSize(size);
    return (
      <textarea
        className={cn(
          CONTROL_FIELD_CLASS,
          'min-h-24 resize-y leading-normal',
          textareaSizeVariants({ size: resolvedSize }),
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
