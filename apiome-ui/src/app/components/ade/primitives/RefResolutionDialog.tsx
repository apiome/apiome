'use client';

/**
 * "How resolution works" (HIVE-11.8, #5604).
 *
 * Authority: `docs/mockups/proposals/catalog-quiet.html` annotation 1 (the explainer moves off
 * the page into a dialog behind a ghost link) and `docs/mockups/PROPOSALS.md` finding 1. The
 * registry rail used to open with a standing *Relative `$ref` resolution* card above Recent
 * activity; its copy lives here now, unchanged — the sentence, the worked example
 * ({@link REF_RESOLUTION_EXAMPLE}) and the **Open reference resolver** link — opened from the
 * **How resolution works** ghost link in the page description.
 *
 * The link is not a Radix `Dialog.Trigger`, so the element focused when the dialog opened is
 * remembered and focused again when it closes (the rule `ui/ModalFrame` and
 * `CatalogAboutDialog` follow).
 */

import * as React from 'react';
import { GitFork, Waypoints } from 'lucide-react';

import { Button } from '@/app/components/ui/Button';
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
} from '@/app/components/ui/Dialog';

import { REF_RESOLUTION_EXAMPLE } from './primitivesModel';

/** Props for {@link RefResolutionDialog}. */
export interface RefResolutionDialogProps {
  /** Whether the dialog is shown. */
  open: boolean;
  /** Reports a request to open or close it (Escape, the scrim, the close buttons). */
  onOpenChange: (open: boolean) => void;
  /** Switch the screen to the Resolver tab; the dialog closes first. */
  onOpenResolver: () => void;
}

/**
 * Render the dialog.
 *
 * @param props See {@link RefResolutionDialogProps}.
 * @returns The dialog (nothing is in the DOM while it is closed).
 */
export function RefResolutionDialog({
  open,
  onOpenChange,
  onOpenResolver,
}: RefResolutionDialogProps) {
  // Radix returns focus only to a `Dialog.Trigger`; this opens from a plain button.
  const returnFocusTo = React.useRef<HTMLElement | null>(null);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        data-testid="primitives-resolution-dialog"
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
        <div className="prm-resolution__head">
          <Waypoints aria-hidden />
          <DialogTitle>How resolution works</DialogTitle>
        </div>
        <DialogDescription>
          Relative <span className="mono">$ref</span> resolution: references resolve against the
          type’s import-source base URL in the API server.
        </DialogDescription>

        <pre className="prm-code" data-testid="primitives-ref-example">
          {REF_RESOLUTION_EXAMPLE.map((line) => (
            <span
              key={line.text}
              className={line.comment ? 'prm-code__comment' : undefined}
              data-comment={line.comment ? 'true' : undefined}
            >
              {line.text}
            </span>
          ))}
        </pre>

        <DialogFooter>
          <Button
            variant="ghost"
            onClick={() => {
              onOpenChange(false);
              onOpenResolver();
            }}
            data-testid="primitives-resolution-open-resolver"
          >
            <GitFork aria-hidden />
            Open reference resolver
          </Button>
          <DialogClose asChild>
            <Button>Got it</Button>
          </DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default RefResolutionDialog;
