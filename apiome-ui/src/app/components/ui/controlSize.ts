'use client';

import * as React from 'react';
import { cva } from 'class-variance-authority';

/**
 * Field sizes (SUX-1.2, apiome#6749) — one scale for `Input`, `Textarea` and the `Select`
 * trigger, matched step for step to `Button`'s `sm` / `default` / `lg`.
 *
 * Each step binds the field's height to the same density-aware metric the button uses
 * (`--control-h-sm`, `--control-h`, `--control-h-lg`) and takes the button's padding, text
 * size and radius at that step, so a button and a field placed side by side share an outer
 * height and a baseline at every size, density and font scale.
 *
 * | Size | Height            | Padding | Text        | Radius       |
 * | ---- | ----------------- | ------- | ----------- | ------------ |
 * | `sm` | `--control-h-sm`  | `px-2.5`| `text-xs`   | `rounded-sm` |
 * | `md` | `--control-h`     | `px-3`  | `text-sm`   | `rounded-md` |
 * | `lg` | `--control-h-lg`  | `px-4`  | `text-base` | `rounded-md` |
 */
export type FieldSize = 'sm' | 'md' | 'lg';

/** The size a field takes when neither it nor a surrounding `FormField` names one. */
export const DEFAULT_FIELD_SIZE: FieldSize = 'md';

/**
 * Height, padding, text and radius for a single-line field (`Input`, `SelectTrigger`).
 *
 * The `md` step adds only the height, because `CONTROL_FIELD_CLASS` already carries the
 * `md` padding, text size and radius; the other steps override those through `cn()`. The
 * heights use the arbitrary-value form (as `Button`'s sizes do) for the reason given there:
 * `tailwind-merge` can then resolve a caller's own `h-*` against it.
 */
export const fieldSizeVariants = cva('', {
  variants: {
    size: {
      sm: 'h-[var(--control-h-sm)] rounded-sm px-2.5 text-xs',
      md: 'h-[var(--control-h)]',
      lg: 'h-[var(--control-h-lg)] px-4 text-base',
    },
  },
  defaultVariants: { size: DEFAULT_FIELD_SIZE },
});

/**
 * Padding, text and radius for a `Textarea`.
 *
 * A textarea has no fixed height — it keeps its `min-h-24` and grows — so a size changes
 * its inner padding, text size and radius only, by the same steps as a single-line field.
 */
export const textareaSizeVariants = cva('', {
  variants: {
    size: {
      sm: 'rounded-sm px-2.5 py-1.5 text-xs',
      md: 'py-2.5',
      lg: 'px-4 py-3 text-base',
    },
  },
  defaultVariants: { size: DEFAULT_FIELD_SIZE },
});

/** The `FormField` label's text size at each field size: `text-xs` beside a `sm` field. */
export const FIELD_LABEL_SIZE_CLASS: Readonly<Record<FieldSize, string>> = {
  sm: 'text-xs',
  md: 'text-sm',
  lg: 'text-sm',
};

/**
 * The size a `FormField` hands down to the fields inside it.
 *
 * A context rather than a cloned prop, because a field's control is often not its direct
 * child: a `Select` root wraps its trigger, and a URL field wraps an input and a button in
 * a `div`. `undefined` means "no field above has chosen a size".
 */
export const FieldSizeContext = React.createContext<FieldSize | undefined>(undefined);

/**
 * Resolve the size a field should render at.
 *
 * @param size The size the field was given directly, if any.
 * @returns `size` when set; otherwise the surrounding `FormField`'s size; otherwise `md`.
 */
export function useFieldSize(size?: FieldSize): FieldSize {
  const inherited = React.useContext(FieldSizeContext);
  return size ?? inherited ?? DEFAULT_FIELD_SIZE;
}
