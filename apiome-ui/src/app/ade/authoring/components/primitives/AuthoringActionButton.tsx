'use client';

/**
 * A command action rendered as a button (UXE-1.3).
 *
 * The reason this is a primitive rather than a plain `<button>` is the disabled
 * case. §27.2 forbids dead ends, so an unavailable action must say why. The
 * `AuthoringCommandAction` type makes `disabledReason` the only way to disable
 * an action, and this component renders that reason where both sighted and
 * screen-reader users can reach it — a `title` alone would be neither
 * keyboard-reachable nor reliably announced.
 */

import * as React from 'react';
import { isAuthoringActionDisabled, type AuthoringCommandAction } from '@lib/authoring/actions';
import { cn } from '@lib/utils';
import {
  authoringActionBaseClass,
  authoringActionClass,
  authoringFocusClass,
  authoringKbdClass,
  authoringMotionClass,
} from '../../authoringClasses';
import AuthoringIcon from '../AuthoringIcon';

/** Props for {@link AuthoringActionButton}. */
export type AuthoringActionButtonProps = {
  action: AuthoringCommandAction;
  /** Invoked when the action is taken. Not called while disabled. */
  onAction: (actionId: string) => void;
  className?: string;
};

/**
 * Render one action button.
 *
 * @param props - The action descriptor and its handler.
 */
export default function AuthoringActionButton({
  action,
  onAction,
  className,
}: AuthoringActionButtonProps) {
  const disabled = isAuthoringActionDisabled(action);
  const reasonId = React.useId();

  return (
    <span className="inline-flex flex-col items-start gap-0.5">
      <button
        type="button"
        disabled={disabled}
        onClick={() => onAction(action.id)}
        data-action-id={action.id}
        // Announced with the label, so the reason is heard on focus rather
        // than only found by sighted users reading the hint below.
        aria-describedby={disabled ? reasonId : undefined}
        className={cn(
          authoringActionBaseClass,
          authoringActionClass[action.variant],
          authoringFocusClass,
          authoringMotionClass.quick,
          className
        )}
      >
        {action.icon ? <AuthoringIcon name={action.icon} className="h-4 w-4 shrink-0" /> : null}
        {action.label}
        {action.shortcut ? (
          <kbd className={cn(authoringKbdClass, 'ml-1')} aria-hidden="true">
            {action.shortcut}
          </kbd>
        ) : null}
      </button>

      {disabled ? (
        <span id={reasonId} className="text-xs text-gray-500 dark:text-gray-400">
          {action.disabledReason}
        </span>
      ) : null}
    </span>
  );
}
