'use client';

/**
 * The publish / rollback impact sheet (UXE-1.3).
 *
 * §27.2 replaces generic "Are you sure?" dialogs with impact sheets showing
 * "checks and policy", and requires destructive actions to include scope
 * previews. This primitive is what makes that non-optional: it cannot be
 * rendered without effects and checks, and the confirm button's enabled state
 * comes from `gateAuthoringImpact` rather than from the calling screen.
 *
 * Every rejected confirmation says why, in the same place, every time. A
 * disabled Promote button that does not explain itself is the exact dead end
 * §27.2 forbids.
 */

import * as React from 'react';
import type { AuthoringCommandAction } from '@lib/authoring/actions';
import {
  describeAuthoringImpactAction,
  gateAuthoringImpact,
  summarizeAuthoringImpact,
  type AuthoringImpactSheet as AuthoringImpactSheetModel,
} from '@lib/authoring/impact';
import { cn } from '@lib/utils';
import {
  authoringFocusClass,
  authoringMonoClass,
  authoringMutedTextClass,
  authoringSectionTitleClass,
  authoringToneHookClass,
  authoringToneSurfaceClass,
  authoringToneTextClass,
} from '../../authoringClasses';
import AuthoringIcon from '../AuthoringIcon';
import AuthoringActionButton from './AuthoringActionButton';
import AuthoringCheckSummary from './AuthoringCheckSummary';
import AuthoringPeekDrawer from './AuthoringPeekDrawer';

/** Props for {@link AuthoringImpactSheet}. */
export type AuthoringImpactSheetProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  sheet: AuthoringImpactSheetModel;
  /** Invoked only when the gate allows confirmation. */
  onConfirm: () => void;
  className?: string;
};

/**
 * Render the confirmation sheet for a consequential action.
 *
 * @param props - Open state, the sheet model and the confirm handler.
 */
export default function AuthoringImpactSheet({
  open,
  onOpenChange,
  sheet,
  onConfirm,
  className,
}: AuthoringImpactSheetProps) {
  const [acknowledged, setAcknowledged] = React.useState(false);
  const [typedPhrase, setTypedPhrase] = React.useState('');
  const phraseId = React.useId();
  const acknowledgeId = React.useId();

  // Reopening the sheet must start from an unconfirmed state; carrying the
  // previous acknowledgement over would let a second, different action inherit
  // consent given for the first.
  React.useEffect(() => {
    if (!open) {
      setAcknowledged(false);
      setTypedPhrase('');
    }
  }, [open]);

  const { title, confirm } = describeAuthoringImpactAction(sheet.action);
  const gate = gateAuthoringImpact(sheet, { acknowledged, typedPhrase });
  const expectedPhrase = sheet.confirmationPhrase ?? sheet.target;

  const confirmAction: AuthoringCommandAction = {
    id: 'confirm',
    label: confirm,
    variant: 'primary',
    tone: sheet.severity === 'irreversible' ? 'danger' : undefined,
    disabledReason: gate.canConfirm ? undefined : gate.block?.message,
  };

  return (
    <AuthoringPeekDrawer
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      description={summarizeAuthoringImpact(sheet)}
      className={className}
      footer={
        <>
          <AuthoringActionButton action={confirmAction} onAction={onConfirm} />
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            className={cn(
              'min-h-9 rounded-lg border border-gray-300 px-3 text-sm font-medium dark:border-gray-600',
              authoringFocusClass
            )}
          >
            Cancel
          </button>
        </>
      }
    >
      <div className="flex flex-col gap-4" data-impact-severity={sheet.severity}>
        {sheet.policy ? (
          <p
            className={cn(
              'flex items-start gap-2 rounded-lg border p-2 text-sm',
              authoringToneSurfaceClass.info,
              authoringToneHookClass.info,
              authoringToneTextClass.info
            )}
          >
            <AuthoringIcon name="Lock" className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{sheet.policy}</span>
          </p>
        ) : null}

        {/* The scope preview §27.2 demands: what changes, and how much of it. */}
        <section aria-labelledby="authoring-impact-effects">
          <h3 id="authoring-impact-effects" className={authoringSectionTitleClass}>
            What changes
          </h3>
          <ul className="mt-2 flex flex-col gap-2">
            {sheet.effects.map((effect) => (
              <li
                key={effect.id}
                data-effect-id={effect.id}
                className={cn(
                  'flex flex-col gap-0.5 rounded-lg border p-2',
                  authoringToneSurfaceClass[effect.tone],
                  authoringToneHookClass[effect.tone]
                )}
              >
                <span className="text-sm font-medium text-gray-900 dark:text-white">
                  {effect.label}
                </span>
                <span className={authoringMutedTextClass}>{effect.detail}</span>
                {effect.scope ? <span className={authoringMonoClass}>{effect.scope}</span> : null}
              </li>
            ))}
          </ul>
        </section>

        <AuthoringCheckSummary checks={sheet.checks} />

        {sheet.severity === 'notable' ? (
          <label
            htmlFor={acknowledgeId}
            className="flex items-start gap-2 text-sm text-gray-900 dark:text-gray-100"
          >
            <input
              id={acknowledgeId}
              type="checkbox"
              checked={acknowledged}
              onChange={(event) => setAcknowledged(event.target.checked)}
              className={cn('mt-0.5 h-4 w-4', authoringFocusClass)}
            />
            I have reviewed what changes above.
          </label>
        ) : null}

        {sheet.severity === 'irreversible' ? (
          <div className="flex flex-col gap-1">
            <label htmlFor={phraseId} className="text-sm text-gray-900 dark:text-gray-100">
              Type <span className={authoringMonoClass}>{expectedPhrase}</span> to confirm. This
              cannot be undone.
            </label>
            <input
              id={phraseId}
              type="text"
              value={typedPhrase}
              onChange={(event) => setTypedPhrase(event.target.value)}
              autoComplete="off"
              className={cn(
                'min-h-9 w-full rounded-lg border border-gray-300 px-3 text-sm dark:border-gray-600 dark:bg-gray-700/50 dark:text-white',
                authoringFocusClass
              )}
            />
          </div>
        ) : null}

        {/*
         * The blocking reason is announced, not just rendered: an operator who
         * tabs straight to the confirm button must hear why it will not fire.
         */}
        {gate.block ? (
          <p
            role="status"
            aria-live="polite"
            className={cn('text-sm', authoringToneTextClass[gate.tone])}
            data-block-reason={gate.block.reason}
          >
            {gate.block.message}
          </p>
        ) : null}
      </div>
    </AuthoringPeekDrawer>
  );
}
