'use client';

import * as React from 'react';
import { cn } from '../../../../lib/utils';
import { fieldSizeVariants, useFieldSize, type FieldSize } from './controlSize';

/** Geometry and colour shared by `Input`, `Textarea` and the `Select` trigger. */
export const CONTROL_FIELD_CLASS = [
  // `hive-control` carries the inset hairline and its hover/focus/invalid states. It has to
  // be CSS rather than a utility because the app-wide `*:focus-visible` ring is unlayered
  // and would otherwise win — see the "HIVE CONTROL CHROME" block in globals.css.
  'hive-control',
  'flex w-full min-w-0 rounded-md bg-surface px-3 text-sm text-fg',
  'placeholder:text-fg-faint',
  'transition-[box-shadow,background-color] duration-[var(--dur-fast)]',
  'focus-visible:outline-none',
  'disabled:cursor-not-allowed disabled:bg-subtle disabled:text-fg-subtle',
].join(' ');

/**
 * Props of {@link Input}.
 *
 * The native `size` attribute (a width in characters) is replaced by the field size: width
 * is the layout's job (`w-*`, `max-w-*`), and `size` across the form primitives means height.
 */
export interface InputProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'size'> {
  /**
   * Height step, matching `Button`'s `sm` / `default` / `lg` (SUX-1.2). Defaults to the
   * surrounding `FormField`'s size, else `md` — the 36 px control every existing field uses.
   */
  size?: FieldSize;
}

/**
 * Input — the Hive text field (HIVE-2.1, #5280).
 *
 * Authority: `docs/mockups/assets/hive.css` §9 (`.input`), `docs/mockups/DESIGN.md` §7.
 *
 * A `--control-h` box on the surface colour with a hairline drawn *inside* it, so the field
 * keeps its full height and follows the density preference. Invalidity is read from
 * `aria-invalid`, which is also what assistive technology reads — the red hairline and the
 * announcement can therefore never disagree.
 *
 * `size` (`sm` | `md` | `lg`) binds the height to `--control-h-sm` / `--control-h` /
 * `--control-h-lg` with the button's padding, text and radius at that step (SUX-1.2).
 */
const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, type, size, ...props }, ref) => {
    const resolvedSize = useFieldSize(size);
    return (
      <input
        type={type}
        className={cn(CONTROL_FIELD_CLASS, fieldSizeVariants({ size: resolvedSize }), className)}
        ref={ref}
        {...props}
      />
    );
  }
);
Input.displayName = 'Input';

export { Input };
