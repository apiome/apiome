'use client';

import * as React from 'react';
import { Check } from 'lucide-react';

import { cn } from '../../../../lib/utils';

/**
 * Stepper — the numbered progress row of a multi-step flow (HIVE-4.4, #5298).
 *
 * Authority: `docs/mockups/assets/hive.css` §16 (`.stepper`, `.step`, `.step__num`,
 * `.step__line`, `.stepper--fill`), drawn by ten of the mockups — the onboarding
 * wizard, the import wizard, the migration tool, the new-repository flow and the
 * design-system gallery among them. It is built here because the wizard is the first
 * surface to need it in production; it is in `components/ui` rather than beside that
 * wizard because the other nine are the reason it has no `auth-` prefix.
 *
 * ```tsx
 * <Stepper
 *   aria-label="Setup progress"
 *   steps={[{ id: 'welcome', label: 'Welcome' }, { id: 'org', label: 'Organization' }]}
 *   current="org"
 *   fill
 * />
 * ```
 *
 * ### What it says out loud
 *
 * The badge is a numeral or a tick, and both are decoration: they repeat in shape what
 * the list already says in structure. So the badge is `aria-hidden` and every step
 * carries a visually-hidden note instead — `Completed`, `Step 2 of 3`, `Not started` —
 * beside the `aria-current="step"` that marks the one the reader is on. A screen reader
 * therefore hears where the reader is *and* how far along that is, which the numeral
 * alone never conveyed.
 *
 * `role="list"` is stated explicitly: Safari drops list semantics from an `<ol>` whose
 * marker is removed, and the marker is removed here by the app's own reset.
 *
 * ### Clickable steps (SUX-2.5, apiome#6766)
 *
 * Pass `onStepSelect` and each step's badge, label and note sit in a
 * `<button type="button" class="step__button">`, so the reader can jump straight to a step
 * (Studio's Guided editors do). The button's name is the label plus its state note, and
 * `aria-current` stays on the list item. Without it the row is display-only, as before.
 *
 * ### Sizing and colour
 *
 * Everything visual is in the `STEPPER` section of `globals.css` and every value there
 * is a token, so the row follows the reader's theme, density and font scale. The one
 * deliberate deviation from the mockup is the ink of an upcoming step: `hive.css` sets
 * it in `--fg-subtle`, which measures under WCAG AA at this size — the same call, for
 * the same reason, as HIVE-3.5's breadcrumbs and HIVE-4.1's terms line. The three
 * states stay distinguishable by their badge, which is what carries the meaning.
 */

/** One step of a {@link Stepper}. */
export interface StepperStep {
  /** Stable identifier — the caller's own name for the step, matched against `current`. */
  id: string;
  /** The step's visible name. */
  label: string;
}

/** Where a step sits relative to the one the reader is on. */
export type StepperStatus = 'done' | 'current' | 'upcoming';

/**
 * The visually-hidden note each state adds after its label.
 *
 * `current` states the position rather than repeating "current step", which
 * `aria-current` already announces.
 */
const STATUS_NOTE: Readonly<Record<StepperStatus, (position: number, total: number) => string>> = {
  done: () => 'Completed',
  current: (position, total) => `Step ${position} of ${total}`,
  upcoming: () => 'Not started',
};

/** The modifier class each state adds to `.step`. `upcoming` is the class's own default. */
const STATUS_CLASS: Readonly<Record<StepperStatus, string>> = {
  done: 'is-done',
  current: 'is-active',
  upcoming: '',
};

/**
 * Where one step sits relative to the reader's position.
 *
 * Exported because the wizard's own step model is tested against it: the terminal step
 * of a flow is past the last *shown* step, which is what `complete` expresses.
 *
 * @param index Zero-based position of the step being drawn.
 * @param currentIndex Zero-based position of the current step; negative when the current
 *   id is not in the list, which is how a terminal step reads.
 * @param complete Draw every step as done — the flow is finished.
 * @returns The step's state.
 */
export function stepperStatus(
  index: number,
  currentIndex: number,
  complete = false
): StepperStatus {
  if (complete) return 'done';
  if (currentIndex < 0) return 'upcoming';
  if (index < currentIndex) return 'done';
  return index === currentIndex ? 'current' : 'upcoming';
}

/** Inputs of {@link Stepper}. */
export interface StepperProps extends Omit<React.OlHTMLAttributes<HTMLOListElement>, 'children'> {
  /** The steps, in visit order. */
  steps: readonly StepperStep[];
  /** The `id` of the step the reader is on. An id not in `steps` marks none of them current. */
  current?: string;
  /** Draw every step as done — for the terminal state of a flow, past its last shown step. */
  complete?: boolean;
  /** Stretch the connectors so the row fills its container (`hive.css` `.stepper--fill`). */
  fill?: boolean;
  /**
   * Make every step a button that jumps to it. Called with the step's `id` and zero-based
   * index. Omit it for a display-only row (the default).
   */
  onStepSelect?: (id: string, index: number) => void;
}

/**
 * One step's badge, label and visually-hidden state note.
 *
 * @param props.step The step being drawn.
 * @param props.status Where it sits relative to the reader.
 * @param props.index Its zero-based position.
 * @param props.total How many steps the row has.
 * @returns The step's contents, without the list item around them.
 */
function StepContent({
  step,
  status,
  index,
  total,
}: {
  step: StepperStep;
  status: StepperStatus;
  index: number;
  total: number;
}) {
  return (
    <>
      <span aria-hidden="true" className="step__num">
        {status === 'done' ? <Check /> : index + 1}
      </span>
      {step.label}
      <span className="sr-only">{STATUS_NOTE[status](index + 1, total)}</span>
    </>
  );
}

/**
 * The numbered progress row.
 *
 * @param props The steps, the current one, the two layout flags and the optional
 *   `onStepSelect` — see
 *   {@link StepperProps}. Pass `aria-label` to name the list; every other `<ol>`
 *   attribute is forwarded.
 * @returns An ordered list of steps with a connector between each pair.
 */
export function Stepper({
  steps,
  current,
  complete = false,
  fill = false,
  onStepSelect,
  className,
  ...props
}: StepperProps) {
  const currentIndex = current ? steps.findIndex((step) => step.id === current) : -1;

  return (
    <ol role="list" className={cn('stepper', fill && 'stepper--fill', className)} {...props}>
      {steps.map((step, index) => {
        const status = stepperStatus(index, currentIndex, complete);
        return (
          <React.Fragment key={step.id}>
            {/* The connector before this step is "done" when the step *behind* it is —
                which is what makes the filled run stop at the reader's position. */}
            {index > 0 && (
              <li
                aria-hidden="true"
                className={cn(
                  'step__line',
                  stepperStatus(index - 1, currentIndex, complete) === 'done' && 'is-done'
                )}
              />
            )}
            <li
              aria-current={status === 'current' ? 'step' : undefined}
              data-status={status}
              className={cn('step', STATUS_CLASS[status])}
            >
              {onStepSelect ? (
                <button
                  type="button"
                  className="step__button hit-target"
                  onClick={() => onStepSelect(step.id, index)}
                >
                  <StepContent step={step} status={status} index={index} total={steps.length} />
                </button>
              ) : (
                <StepContent step={step} status={status} index={index} total={steps.length} />
              )}
            </li>
          </React.Fragment>
        );
      })}
    </ol>
  );
}

export default Stepper;
