'use client';

/**
 * The peek drawer (UXE-1.3).
 *
 * §27.2: "Peek drawers inspect targets, releases and metrics without losing
 * list scroll/filter state." Preserving that state is the entire point, so the
 * drawer is an overlay over the live list rather than a route change — the list
 * behind it is never unmounted, and closing returns to exactly the scroll
 * position and filters the operator left.
 *
 * Radix Dialog supplies the parts that are easy to get wrong: focus trapping,
 * focus restoration to the trigger on close, Escape handling and inert
 * background content.
 */

import * as React from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { cn } from '@lib/utils';
import {
  authoringDrawerClass,
  authoringDrawerOverlayClass,
  authoringFocusClass,
  authoringMotionClass,
  authoringMutedTextClass,
  authoringPaneBodyClass,
  authoringPaneHeaderClass,
  authoringSectionTitleClass,
} from '../../authoringClasses';
import AuthoringIcon from '../AuthoringIcon';

/** Props for {@link AuthoringPeekDrawer}. */
export type AuthoringPeekDrawerProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Drawer heading, and its accessible name. */
  title: string;
  /** One line of context under the heading. */
  description?: string;
  /** Actions pinned to the drawer footer, e.g. Promote or Roll back. */
  footer?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
};

/**
 * Render a docked inspection drawer.
 *
 * @param props - Open state, heading, content and optional footer.
 */
export default function AuthoringPeekDrawer({
  open,
  onOpenChange,
  title,
  description,
  footer,
  children,
  className,
}: AuthoringPeekDrawerProps) {
  const descriptionId = React.useId();

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className={authoringDrawerOverlayClass} />
        <Dialog.Content
          className={cn(authoringDrawerClass, authoringMotionClass.standard, className)}
          aria-describedby={description ? descriptionId : undefined}
          data-testid="authoring-peek-drawer"
        >
          <header className={authoringPaneHeaderClass}>
            <div className="flex min-w-0 flex-col">
              <Dialog.Title className={authoringSectionTitleClass}>{title}</Dialog.Title>
              {description ? (
                <Dialog.Description id={descriptionId} className={authoringMutedTextClass}>
                  {description}
                </Dialog.Description>
              ) : null}
            </div>

            <Dialog.Close
              className={cn(
                'inline-flex h-9 w-9 items-center justify-center rounded-lg text-gray-500 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-700',
                authoringFocusClass
              )}
            >
              {/* The icon is decorative; this is the accessible name. */}
              <span className="sr-only">Close {title}</span>
              <AuthoringIcon name="X" className="h-4 w-4" />
            </Dialog.Close>
          </header>

          <div className={authoringPaneBodyClass}>{children}</div>

          {footer ? (
            <footer className="flex flex-wrap items-start gap-2 border-t border-gray-200 p-3 dark:border-gray-700">
              {footer}
            </footer>
          ) : null}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
