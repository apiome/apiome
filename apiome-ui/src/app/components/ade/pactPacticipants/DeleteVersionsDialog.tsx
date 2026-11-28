'use client';

/**
 * **Delete versions?** — PFX-8.11 (#7308), the destructive pattern of `docs/mockups/DESIGN.md` §8.
 *
 * Opened from a row's **Delete version** or the bulk bar's **Delete**. It spells out what goes —
 * each version's pacts, the verification results it published, its branch membership and tags —
 * and that it can be restored from **Deleted** until it is purged. A version that runs in an
 * environment cannot be deleted: the dialog names it with "Record its undeployment first" and
 * leaves it out; with nothing left to delete there is no delete button. An optional **Reason** is
 * stored with the delete and in the audit trail. The tab never sends `force`.
 */

import * as React from 'react';
import { Trash2 } from 'lucide-react';
import {
  Alert,
  AlertDescription,
  AlertTitle,
  Button,
  CommandBlock,
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  FormField,
  Textarea,
} from '@/app/components/ui';
import { pactCommandSurfaces, unsupportedLines } from '@lib/pact-commands';
import {
  MAX_VERSION_REASON_LENGTH,
  deleteBlock,
  versionCommandAction,
  type RunningIn,
} from '@lib/pact-pacticipant-versions';

/** Props for {@link DeleteVersionsDialog}. */
export interface DeleteVersionsDialogProps {
  /** The pacticipant's handle and name. */
  pacticipant: { slug: string; name: string };
  /** The versions asked for; empty closes the dialog. */
  numbers: string[];
  /** Where each version runs now; `null` when the environments could not be read. */
  runningIn: Map<string, RunningIn[]> | null;
  /** Whether a delete is running. */
  deleting: boolean;
  /** Delete these versions with this reason. */
  onConfirm: (numbers: string[], reason: string) => void;
  /** Close without deleting. */
  onCancel: () => void;
}

/**
 * The dialog.
 *
 * @param props - See {@link DeleteVersionsDialogProps}.
 * @returns The dialog.
 */
export function DeleteVersionsDialog({
  pacticipant,
  numbers,
  runningIn,
  deleting,
  onConfirm,
  onCancel,
}: DeleteVersionsDialogProps) {
  const [reason, setReason] = React.useState('');
  const open = numbers.length > 0;
  React.useEffect(() => {
    if (open) setReason('');
  }, [open]);

  const blocked = numbers
    .map((number) => ({ number, why: deleteBlock(number, runningIn?.get(number)) }))
    .filter((entry): entry is { number: string; why: string } => entry.why !== null);
  const deletable = numbers.filter((number) => !blocked.some((entry) => entry.number === number));
  const one = numbers.length === 1;
  const title = one ? `Delete ${numbers[0]}?` : `Delete ${numbers.length} versions?`;
  const tooLong = reason.trim().length > MAX_VERSION_REASON_LENGTH;
  const action = deletable.length ? versionCommandAction('delete', pacticipant, deletable[0], reason) : null;

  return (
    <Dialog open={open} onOpenChange={(next) => (!next && !deleting ? onCancel() : undefined)}>
      <DialogContent role="alertdialog" data-testid="ppx-delete-versions-dialog">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            {one ? 'Its' : 'Their'} pacts and the verification results {one ? 'it' : 'they'} published go
            with {one ? 'it' : 'them'}, with branch membership and tags; can-i-deploy answers that relied on{' '}
            {one ? 'it' : 'them'} change. You can restore {one ? 'it' : 'them'} from Deleted until{' '}
            {one ? 'it is' : 'they are'} purged.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="ppx-versions__dialog-body">
          {runningIn === null ? (
            <Alert variant="warn" data-testid="ppx-delete-versions-unknown">
              <AlertTitle>Where these versions run could not be read</AlertTitle>
              <AlertDescription>
                Apiome still refuses to delete a version that is deployed or released, and says which.
              </AlertDescription>
            </Alert>
          ) : null}
          {blocked.length ? (
            <Alert variant="danger" data-testid="ppx-delete-versions-blocked">
              <AlertTitle>{blocked.length === 1 ? 'This version cannot be deleted' : 'These versions cannot be deleted'}</AlertTitle>
              <AlertDescription>
                <ul className="ppx-versions__blocked">
                  {blocked.map((entry) => (
                    <li key={entry.number}>{entry.why}</li>
                  ))}
                </ul>
              </AlertDescription>
            </Alert>
          ) : null}
          {deletable.length ? (
            <>
              {!one ? (
                <p className="ppx__statement" data-testid="ppx-delete-versions-list">
                  Deletes <span className="ppx__mono">{deletable.join(', ')}</span>.
                </p>
              ) : null}
              <FormField
                label="Reason (optional)"
                htmlFor="ppx-delete-versions-reason"
                helperText="Stored with the delete and in the audit trail."
                error={tooLong ? `A reason is at most ${MAX_VERSION_REASON_LENGTH} characters.` : undefined}
              >
                <Textarea
                  id="ppx-delete-versions-reason"
                  value={reason}
                  rows={2}
                  onChange={(event) => setReason(event.target.value)}
                  data-testid="ppx-delete-versions-reason"
                />
              </FormField>
              {action ? (
                <CommandBlock
                  surfaces={pactCommandSurfaces(action)}
                  unsupported={unsupportedLines(action)}
                  footnote={
                    deletable.length > 1
                      ? 'One command per version; replace {tenant} with your workspace’s handle in the REST path.'
                      : 'Replace {tenant} with your workspace’s handle in the REST path.'
                  }
                  data-testid="ppx-delete-versions-command"
                />
              ) : null}
            </>
          ) : null}
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onCancel} disabled={deleting}>
            {deletable.length ? 'Cancel' : 'Close'}
          </Button>
          {deletable.length ? (
            <Button
              variant="danger"
              disabled={deleting || tooLong}
              onClick={() => onConfirm(deletable, reason.trim())}
              data-testid="ppx-delete-versions-confirm"
            >
              <Trash2 aria-hidden />
              {deleting
                ? 'Deleting…'
                : deletable.length === 1
                  ? `Delete ${deletable[0]}`
                  : `Delete ${deletable.length} versions`}
            </Button>
          ) : null}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
