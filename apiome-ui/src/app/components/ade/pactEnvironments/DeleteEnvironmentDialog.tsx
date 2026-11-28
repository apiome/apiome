'use client';

/**
 * **Delete environment** — PFX-8.12 (#7309), from an environment's menu.
 *
 * Deleting an environment removes its whole deployment and release history, and can-i-deploy can
 * no longer be asked about it. While any version is deployed or released there the delete is
 * blocked — “Production still has 9 versions running.” — and the dialog offers no delete button;
 * the proxy checks the same with REST before deleting. **The same, from anywhere** shows the REST
 * request (no `apiome pact` command deletes an environment yet).
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
} from '@/app/components/ui';
import { pactCommandSurfaces } from '@lib/pact-commands';
import type { TopologyEnvironment } from '@lib/pact-environments';
import { deleteBlockSentence, deleteEnvironmentAction, runningCount } from '@lib/pact-environment-writes';
import { deleteEnvironment } from './environmentsApi';

/** Props for {@link DeleteEnvironmentDialog}. */
export interface DeleteEnvironmentDialogProps {
  open: boolean;
  onClose: () => void;
  /** Called after the delete, with the sentence to show. */
  onDeleted: (message: string) => void;
  environment: TopologyEnvironment;
}

/**
 * The dialog.
 *
 * @param props - See {@link DeleteEnvironmentDialogProps}.
 * @returns The dialog.
 */
export function DeleteEnvironmentDialog({ open, onClose, onDeleted, environment }: DeleteEnvironmentDialogProps) {
  const [busy, setBusy] = React.useState(false);
  const [problem, setProblem] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!open) setProblem(null);
  }, [open]);

  const blocked = deleteBlockSentence(environment.displayName, runningCount(environment));

  const confirm = async () => {
    setBusy(true);
    setProblem(null);
    const answer = await deleteEnvironment(environment.name);
    setBusy(false);
    if ('error' in answer) setProblem(answer.error);
    else onDeleted(`${environment.displayName} is deleted.`);
  };

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent data-testid="penv-delete-dialog">
        <DialogHeader>
          <DialogTitle>Delete {environment.displayName}?</DialogTitle>
          <DialogDescription>
            Its deployment and release history goes with it, and can-i-deploy can no longer be asked about it.
          </DialogDescription>
        </DialogHeader>
        <DialogBody>
          <div className="penv-dialog__form">
            {blocked ? (
              <Alert variant="warn" data-testid="penv-delete-blocked">
                <AlertTitle>{blocked}</AlertTitle>
                <AlertDescription>
                  Record their undeployment or end their support first; an environment is deleted only when nothing runs there.
                </AlertDescription>
              </Alert>
            ) : null}
            {problem ? (
              <p className="ppx__error" role="alert" data-testid="penv-delete-problem">
                {problem}
              </p>
            ) : null}
            <CommandBlock surfaces={pactCommandSurfaces(deleteEnvironmentAction(environment.uuid))} data-testid="penv-delete-command" />
          </div>
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy} data-testid="penv-delete-cancel">
            {blocked ? 'Close' : 'Cancel'}
          </Button>
          {blocked ? null : (
            <Button variant="danger" onClick={() => void confirm()} disabled={busy} data-testid="penv-delete-confirm">
              <Trash2 aria-hidden />
              {busy ? 'Deleting…' : `Delete ${environment.displayName}`}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
