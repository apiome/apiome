'use client';

/**
 * **End support** — PFX-8.13 (#7310), from a release on the board's **Released to users** column.
 *
 * Says a released version is no longer supported (`apiome pact record-support-ended`): can-i-deploy
 * stops requiring its counterparts to stay compatible with it. The release stays in the history.
 * **The same, from anywhere** shows the command and the REST `PATCH`.
 *
 * Authority: `docs/mockups/contracts/environments.html` (`#release-dialog`, “untick to end its support”).
 */

import * as React from 'react';
import { CircleMinus } from 'lucide-react';
import {
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
import type { NamedPacticipant } from '@lib/pact-environments';
import { supportEndedCommandAction } from '@lib/pact-environment-endings';
import { endSupport } from './environmentsApi';

/** Props for {@link EndSupportDialog}. */
export interface EndSupportDialogProps {
  open: boolean;
  onClose: () => void;
  /** Called after support ends, with the sentence to show. */
  onEnded: (message: string) => void;
  pacticipant: NamedPacticipant;
  version: string;
  /** The environment's name. */
  environment: string;
}

/**
 * The dialog.
 *
 * @param props - See {@link EndSupportDialogProps}.
 * @returns The dialog.
 */
export function EndSupportDialog({ open, onClose, onEnded, pacticipant, version, environment }: EndSupportDialogProps) {
  const [busy, setBusy] = React.useState(false);
  const [problem, setProblem] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (open) setProblem(null);
  }, [open]);

  const confirm = async () => {
    setBusy(true);
    setProblem(null);
    const answer = await endSupport(environment, { pacticipant: pacticipant.slug, version });
    setBusy(false);
    if ('error' in answer) setProblem(answer.error);
    else onEnded(`Support for ${pacticipant.name} ${version} in ${environment} has ended. Its pacts no longer hold its counterparts back.`);
  };

  const action = supportEndedCommandAction({ pacticipant: pacticipant.slug, version, environment });

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent data-testid="penv-end-dialog">
        <DialogHeader>
          <DialogTitle>
            End support for {pacticipant.name} {version}?
          </DialogTitle>
          <DialogDescription>
            can-i-deploy will no longer require other services to stay compatible with it in {environment}. The release stays in the history.
          </DialogDescription>
        </DialogHeader>
        <DialogBody>
          <div className="penv-dialog__form">
            {problem ? (
              <p className="ppx__error" role="alert" data-testid="penv-end-problem">
                {problem}
              </p>
            ) : null}
            <CommandBlock surfaces={pactCommandSurfaces(action)} data-testid="penv-end-command" />
          </div>
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button variant="danger" onClick={() => void confirm()} disabled={busy} data-testid="penv-end-confirm">
            <CircleMinus aria-hidden />
            {busy ? 'Ending…' : 'End support'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
