'use client';

import * as React from 'react';
import { CircleAlert } from 'lucide-react';
import { cn } from '../../../../lib/utils';
import { Button } from './Button';
import { Spinner } from './Spinner';

/**
 * FormFrame and FormSection — the page-level form container and its spacing rule (SUX-2.4,
 * apiome#6752).
 *
 * Before this, every form chose its own label gap (`mb-1`, `mb-2`, `mb-0.5` …), its own
 * section gap (`space-y-4`, `space-y-5`) and its own place for the buttons. The frame fixes
 * all three, so sibling forms line up and do not jump in width:
 *
 * - **Header** (`header`) — the title, or a `DialogHeader` inside a dialog.
 * - **Body** (`children`) — one or more {@link FormSection}s, 24 px apart. It is the part that
 *   scrolls: inside a `DialogContent` the dialog becomes a column and the body scrolls between
 *   header and footer; on a page the page scrolls and the footer sticks to the bottom of the
 *   window (or of whatever scroll container holds the frame).
 * - **Footer** — sticky. Left: the unsaved-changes marker (`dirty`) and the form-level error
 *   (`error`). Right: `secondaryActions`, then the primary submit button (`submitLabel`).
 *
 * Inside a section, {@link FormField} is the label + control pairing (6 px label gap) and the
 * section's grid puts 16 px between fields. The numbers live in `globals.css` under
 * "FORM FRAME (SUX-2.4)", as `.hive-form-frame*` and `.hive-form-section*` rules.
 *
 * **Keyboard.** The frame is a real `<form>` and the primary action is its submit button, so
 * Enter in a single-line field submits (a text area keeps Enter for new lines), and ⌘S /
 * Ctrl+S anywhere inside the frame submits too instead of opening the browser's Save dialog.
 * Neither submits while the primary action is disabled or `submitting`.
 *
 * **Secondary buttons never submit.** A `<button>` with no `type` inside a form is a submit
 * button, and the *first* one is what Enter presses — so a Cancel placed before the primary
 * action would be pressed by Enter. Every button in `secondaryActions` that does not name its
 * own `type` is therefore made `type="button"`.
 */

/** The three frame widths: 560, 720 and 960 px at the default font size. */
export type FormFrameWidth = 'narrow' | 'default' | 'wide';

export interface FormFrameProps
  extends Omit<React.FormHTMLAttributes<HTMLFormElement>, 'onSubmit' | 'title'> {
  /**
   * The frame's maximum width (`narrow` 560 px, `default` 720 px, `wide` 960 px). Forms of the
   * same kind should share one, so moving between them does not change the width.
   */
  width?: FormFrameWidth;
  /** The header slot: a heading and a sentence, or a `DialogHeader` inside a dialog. */
  header?: React.ReactNode;
  /** The body slot: the form's {@link FormSection}s. */
  children: React.ReactNode;
  /** The primary action's label ("Save", "Create project"). It is the form's submit button. */
  submitLabel: string;
  /**
   * Called when the form is submitted — by the primary button, Enter in a single-line field,
   * or ⌘S / Ctrl+S. The browser's own navigation is already prevented.
   */
  onSubmit: (event: React.FormEvent<HTMLFormElement>) => void;
  /** Disable the primary action (and with it Enter and ⌘S / Ctrl+S). */
  submitDisabled?: boolean;
  /**
   * Why the primary action is disabled, shown as its tooltip — a disabled button always says
   * why (HIVE-13.2). Default "Fill in the required fields to save."
   */
  submitDisabledReason?: string;
  /** A save is in flight: the primary action shows a spinner and cannot be pressed again. */
  submitting?: boolean;
  /** Buttons to the left of the primary action, e.g. Cancel. Rendered in the order given. */
  secondaryActions?: React.ReactNode;
  /** Show the unsaved-changes marker at the footer's left. */
  dirty?: boolean;
  /** What the unsaved-changes marker says. Default "Unsaved changes". */
  dirtyLabel?: string;
  /** A form-level error ("Couldn't save. Try again."), shown at the footer's left as an alert. */
  error?: string;
}

/**
 * Whether a key press is ⌘S (macOS) or Ctrl+S (elsewhere), with no other modifier.
 *
 * @param event The key press.
 * @returns `true` for the save chord.
 */
export function isSaveChord(event: Pick<KeyboardEvent, 'key' | 'metaKey' | 'ctrlKey' | 'altKey' | 'shiftKey'>): boolean {
  return (
    (event.metaKey || event.ctrlKey) && !event.altKey && !event.shiftKey && event.key.toLowerCase() === 's'
  );
}

/**
 * The form container: header, scrolling body, sticky footer.
 *
 * @param props See {@link FormFrameProps}; any other `<form>` attribute is passed through.
 * @returns The `<form>`.
 */
export const FormFrame = React.forwardRef<HTMLFormElement, FormFrameProps>(
  (
    {
      width = 'default',
      header,
      children,
      submitLabel,
      onSubmit,
      submitDisabled = false,
      submitDisabledReason = 'Fill in the required fields to save.',
      submitting = false,
      secondaryActions,
      dirty = false,
      dirtyLabel = 'Unsaved changes',
      error,
      className,
      onKeyDown,
      ...props
    },
    ref,
  ) => {
    const secondaryRef = React.useRef<HTMLDivElement>(null);
    const blocked = submitDisabled || submitting;

    // Make untyped secondary buttons plain buttons, so Enter and a click on Cancel never submit.
    // Runs after every render because the slot's buttons can change with any render.
    React.useLayoutEffect(() => {
      secondaryRef.current?.querySelectorAll('button:not([type])').forEach((button) => {
        button.setAttribute('type', 'button');
      });
    });

    return (
      <form
        ref={ref}
        noValidate
        data-width={width}
        className={cn('hive-form-frame', className)}
        {...props}
        onSubmit={(event) => {
          event.preventDefault();
          if (blocked) return;
          onSubmit(event);
        }}
        onKeyDown={(event) => {
          onKeyDown?.(event);
          if (event.defaultPrevented || !isSaveChord(event)) return;
          // Always swallow the chord inside the frame: the browser's Save page dialog is never
          // what someone pressing ⌘S in a form wants, even when the form can't be saved yet.
          event.preventDefault();
          if (!blocked) event.currentTarget.requestSubmit();
        }}
      >
        {header && <div className="hive-form-frame__header">{header}</div>}
        <div className="hive-form-frame__body">{children}</div>
        <div className="hive-form-frame__footer">
          <div className="hive-form-frame__status">
            {dirty && (
              <span role="status" className="hive-form-frame__dirty">
                <span className="hive-form-frame__dirty-dot" aria-hidden="true" />
                {dirtyLabel}
              </span>
            )}
            {error && (
              <p role="alert" className="hive-form-frame__error">
                <CircleAlert className="size-3.5 shrink-0" aria-hidden="true" />
                {error}
              </p>
            )}
          </div>
          <div className="hive-form-frame__actions">
            {secondaryActions && (
              <div ref={secondaryRef} className="hive-form-frame__secondary">
                {secondaryActions}
              </div>
            )}
            <Button
              type="submit"
              disabled={blocked}
              title={submitting ? 'Saving…' : submitDisabled ? submitDisabledReason : undefined}
              aria-busy={submitting || undefined}
            >
              {submitting && <Spinner size="xs" label="Saving" />}
              {submitLabel}
            </Button>
          </div>
        </div>
      </form>
    );
  },
);
FormFrame.displayName = 'FormFrame';

/** The heading levels a section title can take. */
export type FormSectionHeading = 'h2' | 'h3' | 'h4';

export interface FormSectionProps extends Omit<React.HTMLAttributes<HTMLDivElement>, 'title'> {
  /** The section's title ("Basics", "Access"). Also names the group for assistive technology. */
  title: string;
  /** One sentence under the title on what the section holds. */
  description?: string;
  /**
   * The title's heading level. Default `h3`, which is right under a page's `h2` or a dialog's
   * title (an `h2`); use `h2` directly under a page's `h1`.
   */
  headingLevel?: FormSectionHeading;
  /** The section's {@link FormField}s, 16 px apart. */
  children: React.ReactNode;
}

/**
 * One titled group of fields in a {@link FormFrame} body.
 *
 * Rendered as a labelled `role="group"` rather than a `<fieldset>`, whose legend does not take
 * part in grid layout; screen readers announce both the same way.
 *
 * @param props See {@link FormSectionProps}.
 * @returns The section.
 */
export const FormSection = React.forwardRef<HTMLDivElement, FormSectionProps>(
  ({ title, description, headingLevel = 'h3', className, children, ...props }, ref) => {
    const id = React.useId();
    const titleId = `${id}-title`;
    const descriptionId = description ? `${id}-description` : undefined;
    const Heading = headingLevel;
    return (
      <div
        ref={ref}
        role="group"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        className={cn('hive-form-section', className)}
        {...props}
      >
        <div className="hive-form-section__head">
          <Heading id={titleId} className="hive-form-section__title">
            {title}
          </Heading>
          {description && (
            <p id={descriptionId} className="hive-form-section__description">
              {description}
            </p>
          )}
        </div>
        <div className="hive-form-section__fields">{children}</div>
      </div>
    );
  },
);
FormSection.displayName = 'FormSection';
