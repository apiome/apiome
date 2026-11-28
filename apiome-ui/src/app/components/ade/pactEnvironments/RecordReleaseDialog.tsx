'use client';

/**
 * **Record a release** — PFX-8.12 (#7309), a secondary action of the Environments page.
 *
 * For apps people install: old versions stay in use, so several are supported at once. The dialog
 * records one version as released to an environment and lists the service's other releases there
 * that stay supported — a release never replaces another. **The same, from anywhere** shows
 * `apiome pact record-release`.
 *
 * Authority: `docs/mockups/contracts/environments.html` (`#release-dialog`).
 */

import * as React from 'react';
import { Tag } from 'lucide-react';
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
import { pactCommandSurfaces, unsupportedLines } from '@lib/pact-commands';
import { formatWhen, type Pacticipant, type PacticipantVersion } from '@lib/pact-pacticipants';
import type { Topology } from '@lib/pact-environments';
import { newRecordForm, recordFormProblem, releaseCommandAction, stillSupported, type RecordForm } from '@lib/pact-environment-writes';
import { recordRelease } from './environmentsApi';
import { RecordFields, usePacticipantChoices, useVersionChoices } from './RecordFields';

/** Props for {@link RecordReleaseDialog}. */
export interface RecordReleaseDialogProps {
  open: boolean;
  onClose: () => void;
  /** Called after the release is recorded, with the sentence to show. */
  onRecorded: (message: string) => void;
  topology: Topology;
  /** Starting values, for fixture renders. */
  initialForm?: RecordForm;
  initialPacticipants?: Pacticipant[];
  initialVersions?: PacticipantVersion[];
}

/**
 * The dialog.
 *
 * @param props - See {@link RecordReleaseDialogProps}.
 * @returns The dialog.
 */
export function RecordReleaseDialog({
  open,
  onClose,
  onRecorded,
  topology,
  initialForm,
  initialPacticipants,
  initialVersions,
}: RecordReleaseDialogProps) {
  const [form, setForm] = React.useState<RecordForm>(initialForm ?? newRecordForm());
  const [sent, setSent] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [problem, setProblem] = React.useState<string | null>(null);
  const pacticipants = usePacticipantChoices(open, initialPacticipants);
  const versions = useVersionChoices(form.pacticipant, initialVersions);

  // Each opening starts afresh.
  React.useEffect(() => {
    if (!open) return;
    setForm(initialForm ?? newRecordForm());
    setSent(false);
    setProblem(null);
  }, [initialForm, open]);

  const formProblem = recordFormProblem(form);
  const supported = stillSupported(topology, form.environment, form.pacticipant, form.version);
  const target = topology.environments.find((entry) => entry.name === form.environment) ?? null;

  const edit = (patch: Partial<RecordForm>) => {
    setForm((previous) => ({ ...previous, ...patch }));
    setProblem(null);
  };

  const record = async () => {
    setSent(true);
    if (formProblem) return;
    setBusy(true);
    setProblem(null);
    const answer = await recordRelease(form.environment, { pacticipant: form.pacticipant, version: form.version.trim() });
    setBusy(false);
    if ('error' in answer) {
      setProblem(answer.error);
      return;
    }
    const where = target?.displayName ?? form.environment;
    const kept = supported.length ? ` ${supported.map((release) => release.version).join(', ')} stay supported.` : '';
    onRecorded(`${form.version.trim()} is recorded as released to ${where}.${kept}`);
  };

  const action = releaseCommandAction(form, { tenant: '', uuid: target?.uuid ?? null });

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent data-testid="penv-release-dialog">
        <DialogHeader>
          <DialogTitle>Record a release</DialogTitle>
          <DialogDescription>
            For apps people install: old versions stay in use, so several are supported at once.
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
            <div className="ppx-settings__grid">
              <RecordFields
                form={form}
                onChange={edit}
                pacticipants={pacticipants}
                versions={versions}
                environments={topology.environments}
                idPrefix="penv-release"
                disabled={busy}
              />
            </div>
            {form.pacticipant && form.environment ? (
              <section className="penv-supported" aria-labelledby="penv-release-supported" data-testid="penv-release-supported">
                <h3 id="penv-release-supported" className="penv-supported__title">
                  Still supported
                </h3>
                {supported.length ? (
                  <ul className="penv-supported__list">
                    {supported.map((release) => (
                      <li key={release.version}>
                        <span className="ppx__mono">{release.version}</span>
                        <span className="ppx__muted"> — released {formatWhen(release.releasedAt)}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="ppx__muted">No other release of this service is supported there.</p>
                )}
                <p className="ppx__muted">A release does not replace another: these stay supported until their support is ended.</p>
              </section>
            ) : null}
            {sent && formProblem ? (
              <p className="ppx__error" role="alert" data-testid="penv-release-form-problem">
                {formProblem}
              </p>
            ) : null}
            {problem ? (
              <p className="ppx__error" role="alert" data-testid="penv-release-problem">
                {problem}
              </p>
            ) : null}
            <CommandBlock
              surfaces={pactCommandSurfaces(action)}
              unsupported={unsupportedLines(action)}
              footnote="Replace {tenant} with your workspace’s handle in the REST path."
              data-testid="penv-release-command"
            />
          </form>
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => void record()} disabled={busy} data-testid="penv-release-record">
            <Tag aria-hidden />
            {busy ? 'Recording…' : 'Record release'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
