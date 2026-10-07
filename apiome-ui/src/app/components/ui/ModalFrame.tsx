'use client';

import * as React from 'react';
import * as DialogPrimitive from '@radix-ui/react-dialog';

/**
 * ModalFrame — focus-trapping chrome for a modal that keeps its own look (HIVE-10.2, #5338).
 *
 * `docs/mockups/DESIGN.md` §9: "all overlays trap focus and restore it". A few older surfaces
 * draw their modal by hand — a fixed backdrop `div` and a panel — so Tab walks out of the
 * dialog into the page behind it and focus is lost when it closes. `ModalFrame` puts those
 * surfaces on Radix's dialog without restyling them:
 *
 * - focus moves into the panel on open, is trapped while open, and returns to the trigger on close;
 * - Escape and a press on the backdrop call `onClose`;
 * - the panel is a labelled `role="dialog"` with `aria-modal`, named by its {@link ModalFrameTitle}.
 *
 * The backdrop *is* the overlay and the panel sits inside it (Radix's scrollable-overlay pattern),
 * so a caller's existing `fixed inset-0 flex items-center …` backdrop classes keep working as-is.
 * New screens should use `ui/Dialog` instead; this exists so a legacy modal can be made accessible
 * without a redesign.
 */
export interface ModalFrameProps {
  /** Whether the modal is shown. */
  open: boolean;
  /** Called when the reader dismisses the modal (Escape, backdrop, or a `ModalFrameClose`). */
  onClose: () => void;
  /** Classes of the backdrop, which also centres the panel. */
  overlayClassName?: string;
  /** Classes of the panel. */
  className?: string;
  /** Test hook on the panel. */
  'data-testid'?: string;
  /**
   * A fixed accessible name, for a modal whose visible title changes while it is open
   * ("Add Provider" → "Configure GitHub"). Omit it to name the panel by its `ModalFrameTitle`.
   */
  label?: string;
  /** The panel's content. Must include a {@link ModalFrameTitle}. */
  children: React.ReactNode;
}

export function ModalFrame({ open, onClose, overlayClassName, className, label, children, ...rest }: ModalFrameProps) {
  // Radix only returns focus to a `Dialog.Trigger`; these modals open from plain buttons, so the
  // element focused at open time is remembered and focused again on close.
  const returnFocusTo = React.useRef<HTMLElement | null>(null);

  return (
    <DialogPrimitive.Root
      open={open}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
    >
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className={overlayClassName}>
          <DialogPrimitive.Content
            className={className}
            // These legacy modals carry no separate description; without this Radix warns.
            aria-describedby={undefined}
            {...(label ? { 'aria-label': label, 'aria-labelledby': undefined } : {})}
            data-testid={rest['data-testid']}
            onOpenAutoFocus={() => {
              // Runs before Radix moves focus in, so this is still the element that opened it.
              const active = document.activeElement;
              returnFocusTo.current = active instanceof HTMLElement ? active : null;
            }}
            onCloseAutoFocus={(event) => {
              event.preventDefault();
              const target = returnFocusTo.current;
              returnFocusTo.current = null;
              // The trigger can be gone (the action that closed the modal re-rendered the page).
              if (target?.isConnected) target.focus();
            }}
          >
            {children}
          </DialogPrimitive.Content>
        </DialogPrimitive.Overlay>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

/** The modal's accessible name. Wrap the existing heading: `<ModalFrameTitle asChild><h3>…</h3></ModalFrameTitle>`. */
export const ModalFrameTitle = DialogPrimitive.Title;

/** A control that dismisses the modal. Wrap the existing close button with `asChild`. */
export const ModalFrameClose = DialogPrimitive.Close;
