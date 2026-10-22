'use client';

/**
 * "Where these warnings come from" (HIVE-11.10, #5606).
 *
 * Authority: `docs/mockups/proposals/catalog-quiet.html` annotation 1 and
 * `docs/mockups/PROPOSALS.md` finding 1. The sunset timeline used to stand a warning banner
 * between the header and the drawing whenever a row carried a structured `#507` warning. The
 * banner's sentence lives here now, unchanged ({@link SUNSET_WARNINGS_BANNER}), opened from the
 * {@link SUNSET_WARNINGS_LINK} ghost button in the page header's actions — which shows under
 * the same condition the banner did.
 *
 * The link is not a Radix `Dialog.Trigger`, so the element focused when the dialog opened is
 * remembered and focused again when it closes (the rule `RefResolutionDialog` and
 * `CatalogAboutDialog` follow).
 */

import * as React from 'react';
import Link from 'next/link';
import { TriangleAlert } from 'lucide-react';

import { Button } from '@/app/components/ui/Button';
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
} from '@/app/components/ui/Dialog';

import { SUNSET_WARNINGS_BANNER, SUNSET_WARNINGS_LINK, VERSIONS_HREF } from './sunsetModel';

/** Props for {@link SunsetWarningsDialog}. */
export interface SunsetWarningsDialogProps {
  /** Whether the dialog is shown. */
  open: boolean;
  /** Reports a request to open or close it (Escape, the scrim, the close button). */
  onOpenChange: (open: boolean) => void;
}

/**
 * Render the dialog.
 *
 * @param props See {@link SunsetWarningsDialogProps}.
 * @returns The dialog (nothing is in the DOM while it is closed).
 */
export function SunsetWarningsDialog({ open, onOpenChange }: SunsetWarningsDialogProps) {
  // Radix returns focus only to a `Dialog.Trigger`; this opens from a plain button.
  const returnFocusTo = React.useRef<HTMLElement | null>(null);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        data-testid="sunset-warnings-dialog"
        onOpenAutoFocus={() => {
          // Runs before Radix moves focus in, so this is still the element that opened it.
          const active = document.activeElement;
          returnFocusTo.current = active instanceof HTMLElement ? active : null;
        }}
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          const target = returnFocusTo.current;
          returnFocusTo.current = null;
          if (target?.isConnected) target.focus();
        }}
      >
        <div className="stl-warnings__head">
          <TriangleAlert aria-hidden />
          <DialogTitle>{SUNSET_WARNINGS_LINK}</DialogTitle>
        </div>
        <DialogDescription data-testid="sunset-warnings">
          {SUNSET_WARNINGS_BANNER.lead}{' '}
          <Link href={VERSIONS_HREF}>{SUNSET_WARNINGS_BANNER.linkLabel}</Link>{' '}
          {SUNSET_WARNINGS_BANNER.tail}
        </DialogDescription>
        <DialogFooter>
          <DialogClose asChild>
            <Button>Got it</Button>
          </DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default SunsetWarningsDialog;
