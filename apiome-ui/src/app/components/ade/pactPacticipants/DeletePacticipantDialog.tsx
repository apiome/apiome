'use client';

/**
 * **Delete {name}?** — PFX-8.10 (#7307), the destructive pattern of `docs/mockups/DESIGN.md` §8.
 *
 * Opened from the Settings tab's **Danger zone**. Before anything can be deleted the dialog reads
 * `GET …/deletion-impact` and spells the consequence out: how many versions, pacts and verification
 * results go, which providers lose a consumer (their can-i-deploy answers change), which consumers
 * lose a provider, and how many days it can be restored. A pacticipant with a version deployed or
 * released cannot be deleted: the dialog says which versions and offers no button. Otherwise the
 * handle has to be typed to confirm, and an optional **Reason** is stored with the delete and in
 * the audit trail.
 *
 * After the delete the dialog stays open on **Deleted**, with **Restore** (undo, while the grace
 * period runs) and **All pacticipants**; the Pacticipants list's **Deleted** view restores later.
 */

import * as React from 'react';
import { RefreshCw, Trash2, Undo2 } from 'lucide-react';
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
  Input,
  LoadingState,
  Textarea,
} from '@/app/components/ui';
import { pactCommandSurfaces, unsupportedLines } from '@lib/pact-commands';
import {
  confirmMatches,
  deleteCommandAction,
  deleteSentences,
  MAX_REASON_LENGTH,
  type DeletionImpact,
} from '@lib/pact-pacticipant-settings';
import type { Pacticipant } from '@lib/pact-pacticipants';
import { deletePacticipant, fetchDeletionImpact, restorePacticipant } from './pacticipantsApi';

/** Where the dialog is. */
export type DeleteStage =
  | { kind: 'reading' }
  | { kind: 'unreadable'; error: string }
  | { kind: 'confirm'; impact: DeletionImpact }
  | { kind: 'deleted'; impact: DeletionImpact }
  | { kind: 'restored' };

/** Props for {@link DeletePacticipantDialog}. */
export interface DeletePacticipantDialogProps {
  /** The pacticipant to delete. */
  pacticipant: Pacticipant;
  /** Whether the dialog is open. */
  open: boolean;
  /** Close it; `deleted` says whether the pacticipant is gone now. */
  onClose: (deleted: boolean) => void;
  /** Go to the Pacticipants list (after a delete). */
  onLeave: () => void;
  /** A stage to start in, for fixture renders (skips the impact read). */
  initialStage?: DeleteStage;
}

/**
 * The consequence, the type-to-confirm field, the reason and the command block.
 *
 * @param props - The impact, the pacticipant's name, the two inputs and whether a delete is running.
 * @returns The body.
 */
function ConfirmBody({
  impact,
  label,
  confirmText,
  why,
  onTyped,
  onReason,
  running,
}: {
  impact: DeletionImpact;
  label: string;
  confirmText: string;
  why: string;
  onTyped: (value: string) => void;
  onReason: (value: string) => void;
  running: boolean;
}) {
  const sentences = deleteSentences(impact, label);
  const action = deleteCommandAction(impact.slug, label, why);
  return (
    <div className="ppx-delete" data-testid="ppx-delete-impact">
      <p className="ppx__statement">
        {sentences.removes}
        {sentences.affects ? ` ${sentences.affects}` : ''} {sentences.restore}
      </p>
      {sentences.blocked ? (
        <Alert variant="warn" data-testid="ppx-delete-blocked">
          <AlertTitle>This pacticipant cannot be deleted now</AlertTitle>
          <AlertDescription>{sentences.blocked}</AlertDescription>
        </Alert>
      ) : (
        <>
          <FormField label={`Type ${impact.slug} to confirm`} htmlFor="ppx-delete-typed">
            <Input
              id="ppx-delete-typed"
              value={confirmText}
              autoComplete="off"
              spellCheck={false}
              disabled={running}
              onChange={(event) => onTyped(event.target.value)}
              data-testid="ppx-delete-typed"
            />
          </FormField>
          <FormField
            label="Reason (optional)"
            helperText="Stored with the delete and in the audit trail."
            htmlFor="ppx-delete-reason"
          >
            <Textarea
              id="ppx-delete-reason"
              rows={2}
              maxLength={MAX_REASON_LENGTH}
              value={why}
              disabled={running}
              onChange={(event) => onReason(event.target.value)}
              data-testid="ppx-delete-reason"
            />
          </FormField>
          <CommandBlock
            surfaces={pactCommandSurfaces(action)}
            unsupported={unsupportedLines(action)}
            footnote="Replace {tenant} with your workspace’s handle in the REST path."
            data-testid="ppx-delete-command"
          />
        </>
      )}
    </div>
  );
}

/**
 * The dialog.
 *
 * @param props - See {@link DeletePacticipantDialogProps}.
 * @returns The dialog.
 */
export function DeletePacticipantDialog({
  pacticipant,
  open,
  onClose,
  onLeave,
  initialStage,
}: DeletePacticipantDialogProps) {
  const [stage, setStage] = React.useState<DeleteStage>(initialStage ?? { kind: 'reading' });
  const [typed, setTyped] = React.useState('');
  const [reason, setReason] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const [problem, setProblem] = React.useState<string | null>(null);

  const read = React.useCallback(async () => {
    setStage({ kind: 'reading' });
    const answer = await fetchDeletionImpact(pacticipant.slug);
    setStage(
      'error' in answer
        ? { kind: 'unreadable', error: answer.error }
        : { kind: 'confirm', impact: answer },
    );
  }, [pacticipant.slug]);

  React.useEffect(() => {
    if (!open || initialStage) return;
    setTyped('');
    setReason('');
    setProblem(null);
    void read();
  }, [initialStage, open, read]);

  const confirm = async (impact: DeletionImpact) => {
    setBusy(true);
    setProblem(null);
    const answer = await deletePacticipant(pacticipant.slug, reason);
    setBusy(false);
    if ('error' in answer) {
      setProblem(answer.error);
      // A version may have been deployed since the impact was read: read it again.
      if (answer.status === 409) void read();
      return;
    }
    setStage({ kind: 'deleted', impact });
  };

  const restore = async () => {
    setBusy(true);
    setProblem(null);
    const answer = await restorePacticipant(pacticipant.slug);
    setBusy(false);
    if ('error' in answer) setProblem(answer.error);
    else setStage({ kind: 'restored' });
  };

  const gone = stage.kind === 'deleted';
  const name = pacticipant.name;

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose(gone)}>
      <DialogContent data-testid="ppx-delete-dialog">
        <DialogHeader>
          <DialogTitle>
            {stage.kind === 'deleted'
              ? `${name} is deleted`
              : stage.kind === 'restored'
                ? `${name} is back`
                : `Delete ${name}?`}
          </DialogTitle>
          <DialogDescription>
            {stage.kind === 'deleted'
              ? `It is hidden everywhere now and purged after ${stage.impact.grace_days} days unless you restore it.`
              : stage.kind === 'restored'
                ? 'It and the versions deleted with it are back, exactly as they were.'
                : 'A pacticipant is deleted with its whole history.'}
          </DialogDescription>
        </DialogHeader>
        <DialogBody>
          {stage.kind === 'reading' ? (
            <LoadingState
              message="Reading what the delete removes…"
              minHeightClassName="min-h-[4rem]"
            />
          ) : stage.kind === 'unreadable' ? (
            <Alert variant="danger">
              <AlertTitle>What the delete removes could not be read</AlertTitle>
              <AlertDescription>{stage.error}</AlertDescription>
            </Alert>
          ) : stage.kind === 'confirm' ? (
            <ConfirmBody
              impact={stage.impact}
              label={name}
              confirmText={typed}
              why={reason}
              onTyped={setTyped}
              onReason={setReason}
              running={busy}
            />
          ) : null}
          {problem ? (
            <p className="ppx__error" role="alert" data-testid="ppx-delete-problem">
              {problem}
            </p>
          ) : null}
        </DialogBody>
        <DialogFooter>
          {stage.kind === 'deleted' ? (
            <>
              <Button
                variant="outline"
                onClick={() => void restore()}
                disabled={busy}
                data-testid="ppx-delete-restore"
              >
                <Undo2 aria-hidden />
                Restore {name}
              </Button>
              <Button onClick={onLeave} data-testid="ppx-delete-leave">
                All pacticipants
              </Button>
            </>
          ) : stage.kind === 'restored' ? (
            <Button onClick={() => onClose(false)}>Close</Button>
          ) : (
            <>
              <Button variant="outline" onClick={() => onClose(false)} disabled={busy}>
                Cancel
              </Button>
              {stage.kind === 'unreadable' ? (
                <Button variant="soft" onClick={() => void read()}>
                  <RefreshCw aria-hidden />
                  Try again
                </Button>
              ) : stage.kind === 'confirm' && !stage.impact.blocked ? (
                <Button
                  variant="danger"
                  onClick={() => void confirm(stage.impact)}
                  disabled={busy || !confirmMatches(typed, pacticipant.slug)}
                  data-testid="ppx-delete-confirm"
                >
                  <Trash2 aria-hidden />
                  {busy ? 'Deleting…' : `Delete ${name}`}
                </Button>
              ) : null}
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
