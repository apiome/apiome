'use client';

import * as React from 'react';

import { Alert } from '@/app/components/ui/Alert';
import { Button } from '@/app/components/ui/Button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/app/components/ui/Dialog';
import { Spinner } from '@/app/components/ui/Spinner';

/**
 * One confirmation dialog for every Agent access decision — AGX-3.4 (#4540).
 *
 * Three decisions on the screen need one: exposing a **write operation** to agents (AGX-1.2's
 * explicit confirmation), **deleting a toolset** (which deletes its keys and credentials) and
 * **revoking a key**. They differ only in their words and their tone, so they share this.
 *
 * The confirm runs the write itself and keeps the dialog open on failure, with the message beside
 * the button that caused it; only a write that worked closes it.
 */

/** Props for {@link AgentConfirmDialog}. */
export interface AgentConfirmDialogProps {
  /** Whether the dialog is open. */
  open: boolean;
  /** Close it. Ignored while the write runs. */
  onOpenChange: (open: boolean) => void;
  /** The tinted tile's tone, from the shared status vocabulary. */
  tone: 'warn' | 'danger';
  /** The icon in the tile. */
  icon: React.ReactNode;
  /** The question. */
  title: string;
  /** One sentence under the title. */
  description: React.ReactNode;
  /** What happens, stated as consequences. */
  children?: React.ReactNode;
  /** The confirm button's words. */
  confirmLabel: string;
  /** The confirm button's words while the write runs. */
  busyLabel: string;
  /**
   * Run the write.
   *
   * @returns `null` on success (the dialog closes), or the message to show.
   */
  onConfirm: () => Promise<string | null>;
  /** Test id for the dialog. */
  testId: string;
}

/**
 * The confirmation dialog.
 *
 * @param props See {@link AgentConfirmDialogProps}.
 * @returns The dialog.
 */
export default function AgentConfirmDialog({
  open,
  onOpenChange,
  tone,
  icon,
  title,
  description,
  children,
  confirmLabel,
  busyLabel,
  onConfirm,
  testId,
}: AgentConfirmDialogProps) {
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState('');

  React.useEffect(() => {
    if (!open) return;
    setBusy(false);
    setError('');
  }, [open]);

  const runConfirm = React.useCallback(async () => {
    setBusy(true);
    setError('');
    const failure = await onConfirm();
    setBusy(false);
    if (failure) {
      setError(failure);
      return;
    }
    onOpenChange(false);
  }, [onConfirm, onOpenChange]);

  return (
    <Dialog open={open} onOpenChange={(next) => !busy && onOpenChange(next)}>
      <DialogContent data-testid={testId}>
        <DialogHeader>
          <DialogTitle className="agx-dialog-title">
            <span className="tnt-icon-tile" data-tone={tone}>
              {icon}
            </span>
            {title}
          </DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>

        <div className="agx-dialog-body">
          {children}
          {error && (
            <Alert variant="error" data-testid={`${testId}-error`}>
              {error}
            </Alert>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" disabled={busy} onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            variant={tone === 'danger' ? 'danger' : 'primary'}
            disabled={busy}
            data-testid={`${testId}-confirm`}
            onClick={() => void runConfirm()}
          >
            {busy && <Spinner size="sm" aria-hidden />}
            {busy ? busyLabel : confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
