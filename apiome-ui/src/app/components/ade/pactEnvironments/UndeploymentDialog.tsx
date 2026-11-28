'use client';

/**
 * **Record an undeployment** — PFX-8.13 (#7310), from an environment's column menu on the board.
 *
 * Says a service no longer runs in the environment (`apiome pact record-undeployment`): pick the
 * service and, when it runs in several instances, the instance. The deployment stays in the history,
 * and can-i-deploy stops counting it. The proxy chooses the deployment exactly as `pact-broker` does
 * and refuses with what *is* deployed when nothing matches. **The same, from anywhere** shows the
 * command and the REST `PATCH` it ends with.
 *
 * Authority: `docs/mockups/contracts/environments.html` (`#env-menu`).
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
  FormField,
} from '@/app/components/ui';
import { pactCommandSurfaces, unsupportedLines } from '@lib/pact-commands';
import type { EnvironmentFacts } from '@lib/pact-environments';
import { deployedIn, type Board } from '@lib/pact-environment-board';
import { undeploymentCommandAction, type UndeploymentForm } from '@lib/pact-environment-endings';
import { recordUndeployment } from './environmentsApi';

/** The value the instance select uses for the unnamed instance. */
const UNNAMED = '';

/** Props for {@link UndeploymentDialog}. */
export interface UndeploymentDialogProps {
  open: boolean;
  onClose: () => void;
  /** Called after the undeployment, with the sentence to show. */
  onRecorded: (message: string) => void;
  board: Board;
  environment: EnvironmentFacts;
  /** Starting values, for fixture renders. */
  initialForm?: UndeploymentForm;
}

/**
 * The dialog.
 *
 * @param props - See {@link UndeploymentDialogProps}.
 * @returns The dialog.
 */
export function UndeploymentDialog({ open, onClose, onRecorded, board, environment, initialForm }: UndeploymentDialogProps) {
  const services = deployedIn(board, environment.uuid);
  const first = (): UndeploymentForm => {
    const service = services[0];
    return {
      pacticipant: service?.pacticipant.slug ?? '',
      environment: environment.name,
      applicationInstance: service?.versions[0]?.instance ?? UNNAMED,
    };
  };
  const [form, setForm] = React.useState<UndeploymentForm>(initialForm ?? first());
  const [busy, setBusy] = React.useState(false);
  const [problem, setProblem] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!open) return;
    setForm(initialForm ?? first());
    setProblem(null);
    // `first` reads the board and environment named below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, initialForm, environment.uuid, board]);

  const service = services.find((entry) => entry.pacticipant.slug === form.pacticipant) ?? null;
  const running = service?.versions.filter((entry) => (entry.instance ?? UNNAMED) === form.applicationInstance) ?? [];

  const record = async () => {
    if (!service) return;
    setBusy(true);
    setProblem(null);
    const answer = await recordUndeployment(environment.name, {
      pacticipant: form.pacticipant,
      ...(form.applicationInstance ? { applicationInstance: form.applicationInstance } : {}),
    });
    setBusy(false);
    if ('error' in answer) {
      setProblem(answer.error);
      return;
    }
    const versions = answer.undeployed.map((entry) => entry.version).join(', ');
    const instance = form.applicationInstance ? ` (${form.applicationInstance})` : '';
    onRecorded(`${service.pacticipant.name} ${versions} is recorded as no longer deployed to ${environment.displayName}${instance}.`);
  };

  const action = undeploymentCommandAction(form);

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent data-testid="penv-undeploy-dialog">
        <DialogHeader>
          <DialogTitle>Record an undeployment</DialogTitle>
          <DialogDescription>
            Say a service no longer runs in {environment.displayName}. It stays in the history; can-i-deploy stops counting it.
          </DialogDescription>
        </DialogHeader>
        <DialogBody>
          <form
            className="penv-dialog__form"
            onSubmit={(event) => {
              event.preventDefault();
              void record();
            }}
            noValidate
          >
            {services.length ? (
              <div className="ppx-settings__grid">
                <FormField label="Service" htmlFor="penv-undeploy-service">
                  <select
                    id="penv-undeploy-service"
                    className="ppx__select"
                    value={form.pacticipant}
                    disabled={busy}
                    onChange={(event) => {
                      const next = services.find((entry) => entry.pacticipant.slug === event.target.value);
                      setForm({ ...form, pacticipant: event.target.value, applicationInstance: next?.versions[0]?.instance ?? UNNAMED });
                      setProblem(null);
                    }}
                    data-testid="penv-undeploy-service"
                  >
                    {services.map((entry) => (
                      <option key={entry.pacticipant.slug} value={entry.pacticipant.slug}>
                        {entry.pacticipant.name}
                      </option>
                    ))}
                  </select>
                </FormField>
                <FormField
                  label="Instance"
                  htmlFor="penv-undeploy-instance"
                  helperText={running.length ? `Running ${running.map((entry) => entry.version).join(', ')} there.` : undefined}
                >
                  <select
                    id="penv-undeploy-instance"
                    className="ppx__select"
                    value={form.applicationInstance}
                    disabled={busy || !service}
                    onChange={(event) => {
                      setForm({ ...form, applicationInstance: event.target.value });
                      setProblem(null);
                    }}
                    data-testid="penv-undeploy-instance"
                  >
                    {(service?.versions ?? []).map((entry) => (
                      <option key={entry.instance ?? UNNAMED} value={entry.instance ?? UNNAMED}>
                        {entry.instance ?? 'The only instance'}
                      </option>
                    ))}
                  </select>
                </FormField>
              </div>
            ) : (
              <p className="ppx__muted" data-testid="penv-undeploy-nothing">
                Nothing is deployed to {environment.displayName}.
              </p>
            )}
            {problem ? (
              <p className="ppx__error" role="alert" data-testid="penv-undeploy-problem">
                {problem}
              </p>
            ) : null}
            <CommandBlock
              surfaces={pactCommandSurfaces(action)}
              unsupported={unsupportedLines(action)}
              footnote="The command finds the deployment itself; REST names it by its uuid, from …/deployed-versions/currently-deployed."
              data-testid="penv-undeploy-command"
            />
          </form>
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button variant="danger" onClick={() => void record()} disabled={busy || !service} data-testid="penv-undeploy-record">
            <CircleMinus aria-hidden />
            {busy ? 'Recording…' : 'Record undeployment'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
