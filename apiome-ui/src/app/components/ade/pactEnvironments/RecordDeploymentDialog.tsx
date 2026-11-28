'use client';

/**
 * **Record a deployment** — PFX-8.12 (#7309), the Environments page's primary action and the
 * environment menu's **Record a deployment here**.
 *
 * Says which version of a service now runs in an environment (and, optionally, which instance of
 * it); it replaces the version deployed to that instance. Once the service, version and environment
 * are chosen the dialog asks can-i-deploy. A "yes" lets it record. A "no" — or a verdict not known
 * yet — shows the reasons, and recording is possible only after ticking **Record it anyway — this
 * already happened**: the proxy asks can-i-deploy again, refuses a "no" without the tick, and sends
 * an override to REST as `overrideCanIDeploy=true`, which the audit row keeps. **The same, from
 * anywhere** shows `apiome pact record-deployment`.
 *
 * Authority: `docs/mockups/contracts/environments.html` (`#deploy-dialog`).
 */

import * as React from 'react';
import { CircleCheck, OctagonX, Rocket } from 'lucide-react';
import {
  Button,
  Checkbox,
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
} from '@/app/components/ui';
import { pactCommandSurfaces, unsupportedLines } from '@lib/pact-commands';
import type { MatrixAnswer } from '@lib/pact-matrix';
import type { Pacticipant, PacticipantVersion } from '@lib/pact-pacticipants';
import type { Topology } from '@lib/pact-environments';
import {
  deploymentBody,
  deploymentCommandAction,
  mayRecordDeployment,
  newRecordForm,
  recordFormProblem,
  replacedVersion,
  verdictGate,
  verdictReasons,
  type RecordForm,
} from '@lib/pact-environment-writes';
import { fetchCanIDeploy } from '../pactMatrix/pactMatrixApi';
import { recordDeployment } from './environmentsApi';
import { RecordFields, usePacticipantChoices, useVersionChoices } from './RecordFields';

/** The verdict the dialog holds for the question it shows. */
type Asked = { key: string; answer: MatrixAnswer | null; error: string | null };

/** Props for {@link RecordDeploymentDialog}. */
export interface RecordDeploymentDialogProps {
  open: boolean;
  onClose: () => void;
  /** Called after a deployment is recorded, with the sentence to show. */
  onRecorded: (message: string) => void;
  topology: Topology;
  /** The environment to start in (the menu's **Record a deployment here**). */
  environment?: string;
  /** Starting values, for fixture renders. */
  initialForm?: RecordForm;
  /** Choices to offer without reading them, for fixture renders. */
  initialPacticipants?: Pacticipant[];
  initialVersions?: PacticipantVersion[];
}

/** The question a form asks, as a key: the verdict shown must be for this one. */
function questionKey(form: RecordForm): string {
  return JSON.stringify([form.pacticipant, form.version.trim(), form.environment]);
}

/**
 * The dialog.
 *
 * @param props - See {@link RecordDeploymentDialogProps}.
 * @returns The dialog.
 */
export function RecordDeploymentDialog({
  open,
  onClose,
  onRecorded,
  topology,
  environment = '',
  initialForm,
  initialPacticipants,
  initialVersions,
}: RecordDeploymentDialogProps) {
  const [form, setForm] = React.useState<RecordForm>(initialForm ?? newRecordForm(environment));
  const [recordAnyway, setRecordAnyway] = React.useState(false);
  const [asked, setAsked] = React.useState<Asked | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [problem, setProblem] = React.useState<string | null>(null);
  const pacticipants = usePacticipantChoices(open, initialPacticipants);
  const versions = useVersionChoices(form.pacticipant, initialVersions);

  // Each opening starts afresh (in the environment the menu named, if any).
  React.useEffect(() => {
    if (!open) return;
    setForm(initialForm ?? newRecordForm(environment));
    setRecordAnyway(false);
    setAsked(null);
    setProblem(null);
  }, [environment, initialForm, open]);

  const formProblem = recordFormProblem(form);
  const key = questionKey(form);

  // Ask can-i-deploy for each complete question (after a short pause while the version is typed).
  React.useEffect(() => {
    if (!open || formProblem) return;
    let live = true;
    const timer = setTimeout(() => {
      fetchCanIDeploy({ pacticipant: form.pacticipant, version: form.version, kind: 'environment', destination: form.environment, ignore: [] })
        .then((answer) => live && setAsked({ key, answer, error: null }))
        .catch((caught: unknown) =>
          live && setAsked({ key, answer: null, error: caught instanceof Error ? caught.message : 'Could not ask can-i-deploy' }),
        );
    }, 300);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [form.environment, form.pacticipant, form.version, formProblem, key, open]);

  const current = asked && asked.key === key && !formProblem ? asked : null;
  const gate = verdictGate(current?.answer ?? null);
  const sendable = !formProblem && mayRecordDeployment(gate, recordAnyway);
  const override = gate === 'no' && recordAnyway;
  const target = topology.environments.find((entry) => entry.name === form.environment) ?? null;
  const replaces = formProblem ? null : replacedVersion(topology, form);

  const edit = (patch: Partial<RecordForm>) => {
    setForm((previous) => ({ ...previous, ...patch }));
    setRecordAnyway(false);
    setProblem(null);
  };

  const record = async () => {
    if (!sendable) return;
    setBusy(true);
    setProblem(null);
    const answer = await recordDeployment(form.environment, deploymentBody(form, override));
    setBusy(false);
    if ('error' in answer) {
      setProblem(answer.reasons?.length ? `${answer.error} ${answer.reasons.join(' ')}` : answer.error);
      return;
    }
    const where = target?.displayName ?? form.environment;
    const name = pacticipants.state === 'ready' ? (pacticipants.items.find((p) => p.slug === form.pacticipant)?.name ?? form.pacticipant) : form.pacticipant;
    onRecorded(
      answer.verdict === 'no'
        ? `${name} ${form.version.trim()} is recorded as deployed to ${where}, over a “no” from can-i-deploy. The override is in the audit trail.`
        : `${name} ${form.version.trim()} is recorded as deployed to ${where}.`,
    );
  };

  const action = deploymentCommandAction(form, { tenant: '', uuid: target?.uuid ?? null, recordAnyway: override });

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent data-testid="penv-deploy-dialog">
        <DialogHeader>
          <DialogTitle>Record a deployment</DialogTitle>
          <DialogDescription>Say which version is now running. It replaces the one in that instance.</DialogDescription>
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
                idPrefix="penv-deploy"
                disabled={busy}
              />
              <FormField
                label="Instance (optional)"
                htmlFor="penv-deploy-instance"
                helperText="For the same service running in several places."
              >
                <Input
                  id="penv-deploy-instance"
                  value={form.applicationInstance}
                  placeholder="eu-west"
                  disabled={busy}
                  onChange={(event) => edit({ applicationInstance: event.target.value })}
                  data-testid="penv-deploy-instance"
                />
              </FormField>
            </div>
            {formProblem ? (
              <p className="ppx__muted" data-testid="penv-deploy-waiting">
                {formProblem} can-i-deploy is asked once the service, version and environment are chosen.
              </p>
            ) : (
              <section className="penv-verdict" aria-live="polite" data-testid="penv-deploy-verdict">
                {current === null ? (
                  <LoadingState message="Asking can-i-deploy…" minHeightClassName="min-h-[3rem]" />
                ) : current.error ? (
                  <p className="ppx__error" role="alert">
                    {current.error}
                  </p>
                ) : gate === 'yes' ? (
                  <p className="penv-verdict__head penv-verdict__head--ok">
                    <CircleCheck aria-hidden />
                    can-i-deploy says yes
                  </p>
                ) : (
                  <>
                    <p className="penv-verdict__head penv-verdict__head--no">
                      <OctagonX aria-hidden />
                      {current.answer?.summary.deployable === null ? 'can-i-deploy does not know yet' : 'can-i-deploy says no'}
                    </p>
                    <ul className="penv-verdict__reasons" data-testid="penv-deploy-reasons">
                      {verdictReasons(current.answer!).map((line) => (
                        <li key={line}>{line}</li>
                      ))}
                    </ul>
                    <label className="penv-verdict__tick" htmlFor="penv-deploy-anyway">
                      <Checkbox
                        id="penv-deploy-anyway"
                        checked={recordAnyway}
                        disabled={busy}
                        onCheckedChange={(next) => setRecordAnyway(next === true)}
                        data-testid="penv-deploy-anyway"
                      />
                      Record it anyway — this already happened
                    </label>
                  </>
                )}
                {replaces ? (
                  <p className="ppx__muted" data-testid="penv-deploy-replaces">
                    Replaces {replaces}
                    {form.applicationInstance ? ` on ${form.applicationInstance}` : ''}.
                  </p>
                ) : null}
              </section>
            )}
            {problem ? (
              <p className="ppx__error" role="alert" data-testid="penv-deploy-problem">
                {problem}
              </p>
            ) : null}
            <CommandBlock
              surfaces={pactCommandSurfaces(action)}
              unsupported={unsupportedLines(action)}
              footnote="Replace {tenant} with your workspace’s handle in the REST path."
              data-testid="penv-deploy-command"
            />
          </form>
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => void record()} disabled={busy || !sendable} data-testid="penv-deploy-record">
            <Rocket aria-hidden />
            {busy ? 'Recording…' : 'Record deployment'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
