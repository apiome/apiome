'use client';

import * as React from 'react';
import { cn } from '../../../../lib/utils';

/**
 * Form — the vertical rhythm every form shares.
 *
 * `FormField` fixes the distance from a label to its control; this fixes the rest: fields are
 * `--space-form` apart, sections `--space-section` apart, and the actions sit in one row at the
 * foot. The three are tokens (globals.css, beside the spacing grid), so a form keeps the same
 * rhythm on every screen and tightens with the Compact density preference — which a form that
 * spells its own `space-y-3` or `gap-4` does not.
 *
 *     <Form onSubmit={…}>
 *       <FormSection title="Connection" description="Where Apiome reaches the server.">
 *         <FormRow>
 *           <FormField label="Endpoint URL" htmlFor="url"><Input id="url" /></FormField>
 *           <FormField label="Display name" htmlFor="name"><Input id="name" /></FormField>
 *         </FormRow>
 *       </FormSection>
 *       <FormActions>
 *         <Button variant="outline">Cancel</Button>
 *         <Button type="submit">Save</Button>
 *       </FormActions>
 *     </Form>
 */

export interface FormProps extends React.FormHTMLAttributes<HTMLFormElement> {
  /**
   * How wide the form may grow. `narrow` caps it at the 560 px of an ordinary dialog, which is
   * the measure a single column of fields reads best at; `full` (the default) leaves the width
   * to the container — a dialog, a drawer or a card already has one.
   */
  width?: 'full' | 'narrow';
}

export const Form = React.forwardRef<HTMLFormElement, FormProps>(
  ({ className, width = 'full', ...props }, ref) => (
    <form
      ref={ref}
      className={cn(
        'flex min-w-0 flex-col gap-[var(--space-form)]',
        width === 'narrow' && 'max-w-[35rem]',
        className,
      )}
      {...props}
    />
  ),
);
Form.displayName = 'Form';

export interface FormSectionProps extends Omit<React.HTMLAttributes<HTMLElement>, 'title'> {
  /** The section's heading. */
  title?: React.ReactNode;
  /** A sentence under the heading saying what the fields below are for. */
  description?: React.ReactNode;
}

/**
 * A titled group of fields. Two sections in a row are `--space-section` apart rather than the
 * `--space-form` that separates fields, so the grouping reads without a rule between them.
 */
export const FormSection = React.forwardRef<HTMLElement, FormSectionProps>(
  ({ className, title, description, children, ...props }, ref) => (
    <section
      ref={ref}
      className={cn(
        'flex min-w-0 flex-col gap-[var(--space-form)]',
        // The parent's own gap already supplies `--space-form`; this adds the difference.
        '[&+&]:mt-[calc(var(--space-section)-var(--space-form))]',
        className,
      )}
      {...props}
    >
      {(title || description) && (
        <div className="flex flex-col gap-1">
          {title && <h3 className="text-base font-semibold tracking-[0.01em] text-fg">{title}</h3>}
          {description && <p className="text-sm text-fg-muted">{description}</p>}
        </div>
      )}
      {children}
    </section>
  ),
);
FormSection.displayName = 'FormSection';

export interface FormRowProps extends React.HTMLAttributes<HTMLDivElement> {
  /** How many fields share the row once there is room for them (default 2). */
  columns?: 2 | 3;
}

/** Fields side by side, stacking to one column on a narrow container. */
export const FormRow = React.forwardRef<HTMLDivElement, FormRowProps>(
  ({ className, columns = 2, ...props }, ref) => (
    <div
      ref={ref}
      className={cn(
        'grid min-w-0 items-start gap-[var(--space-form)]',
        columns === 3 ? 'sm:grid-cols-3' : 'sm:grid-cols-2',
        className,
      )}
      {...props}
    />
  ),
);
FormRow.displayName = 'FormRow';

export interface FormActionsProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Where the buttons sit. `between` puts the first child at the leading edge (a Back button). */
  align?: 'end' | 'start' | 'between';
}

const ACTIONS_ALIGN: Readonly<Record<NonNullable<FormActionsProps['align']>, string>> = {
  end: 'justify-end',
  start: 'justify-start',
  between: 'justify-between',
};

/**
 * The form's buttons, in one row at its foot. Inside a dialog use `DialogFooter` instead — it
 * carries the dialog's tinted band; this is for a form on a page, in a card or in a drawer.
 */
export const FormActions = React.forwardRef<HTMLDivElement, FormActionsProps>(
  ({ className, align = 'end', ...props }, ref) => (
    <div
      ref={ref}
      className={cn('flex flex-wrap items-center gap-2 pt-2', ACTIONS_ALIGN[align], className)}
      {...props}
    />
  ),
);
FormActions.displayName = 'FormActions';
