'use client';

/**
 * **New environment** / **Edit environment** — PFX-8.12 (#7309).
 *
 * A place services run; can-i-deploy answers for it. **Display name** (what people read; typing it
 * suggests a **Name** until the name is typed itself), **Name** (what commands use: one word),
 * **Production**, **Contracts required**, **Contact** and **Contact email**. Each field shows what
 * would be refused before anything is sent; a taken name (409) is shown under **Name**.
 *
 * Editing replaces every field (REST's `PUT`): contacts the dialog does not show — a second contact,
 * other details of the first — are kept and sent back unchanged, and the dialog says how many.
 * **The same, from anywhere** shows `apiome pact create-environment` for a new one; no command
 * changes an environment yet, so an edit shows the REST request and says so.
 *
 * Authority: `docs/mockups/contracts/environments.html` (`#env-dialog`).
 */

import * as React from 'react';
import { Plus, Save } from 'lucide-react';
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
  Input,
} from '@/app/components/ui';
import { pactCommandSurfaces, unsupportedLines } from '@lib/pact-commands';
import { plural } from '@lib/pact-pacticipant-settings';
import {
  NEW_ENVIRONMENT_FORM,
  environmentBody,
  environmentCommandAction,
  environmentProblems,
  hasNoProblems,
  suggestedName,
  type BrokerEnvironment,
  type EnvironmentForm,
} from '@lib/pact-environment-writes';
import SwitchRow from '../preferences/SwitchRow';
import { createEnvironment, updateEnvironment } from './environmentsApi';

/** Props for {@link EnvironmentDialog}. */
export interface EnvironmentDialogProps {
  open: boolean;
  onClose: () => void;
  /** Called after a save, with the sentence to show. */
  onSaved: (message: string) => void;
  /** The environment being edited, with its form; nothing for a new one. */
  editing?: { environment: BrokerEnvironment; form: EnvironmentForm } | null;
  /** Names other environments have (a new name may not be one of them). */
  takenNames: string[];
  /** Starting values, for fixture renders. */
  initialForm?: EnvironmentForm;
}

/**
 * The dialog.
 *
 * @param props - See {@link EnvironmentDialogProps}.
 * @returns The dialog.
 */
export function EnvironmentDialog({ open, onClose, onSaved, editing = null, takenNames, initialForm }: EnvironmentDialogProps) {
  const start = editing?.form ?? initialForm ?? NEW_ENVIRONMENT_FORM;
  const [form, setForm] = React.useState<EnvironmentForm>(start);
  const [nameTyped, setNameTyped] = React.useState(Boolean(editing) || Boolean(initialForm?.name));
  const [sent, setSent] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [problem, setProblem] = React.useState<string | null>(null);
  const [nameTaken, setNameTaken] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!open) return;
    setForm(editing?.form ?? initialForm ?? NEW_ENVIRONMENT_FORM);
    setNameTyped(Boolean(editing) || Boolean(initialForm?.name));
    setSent(false);
    setProblem(null);
    setNameTaken(null);
  }, [editing, initialForm, open]);

  const others = takenNames.filter((name) => name !== editing?.environment.name);
  const problems = environmentProblems(form, others);
  const shown = { ...(sent ? problems : {}), ...(nameTaken ? { name: nameTaken } : {}) };
  const keptContacts = form.otherContacts.length + (Object.keys(form.contactDetails).length ? 1 : 0);

  const edit = (patch: Partial<EnvironmentForm>) => {
    setForm((previous) => {
      const next = { ...previous, ...patch };
      if ('displayName' in patch && !nameTyped) next.name = suggestedName(patch.displayName ?? '');
      return next;
    });
    if ('name' in patch) {
      setNameTyped(true);
      setNameTaken(null);
    }
    setProblem(null);
  };

  const save = async () => {
    setSent(true);
    if (!hasNoProblems(problems)) return;
    setBusy(true);
    setProblem(null);
    const body = environmentBody(form);
    const answer = editing ? await updateEnvironment(editing.environment.name, body) : await createEnvironment(body);
    setBusy(false);
    if ('error' in answer) {
      if (answer.status === 409) setNameTaken(answer.error);
      else setProblem(answer.error);
      return;
    }
    onSaved(editing ? `${body.displayName} is saved.` : `${body.displayName} is created. Record a deployment to it from your pipeline or here.`);
  };

  const action = environmentCommandAction(form, { tenant: '', uuid: editing?.environment.uuid ?? null });

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent data-testid="penv-env-dialog">
        <DialogHeader>
          <DialogTitle>{editing ? `Edit ${editing.environment.displayName}` : 'New environment'}</DialogTitle>
          <DialogDescription>A place services run. can-i-deploy answers for it.</DialogDescription>
        </DialogHeader>
        <DialogBody>
          <form
            className="penv-dialog__form"
            onSubmit={(event) => {
              event.preventDefault();
              void save();
            }}
            noValidate
          >
            <div className="ppx-settings__grid">
              <FormField label="Display name" htmlFor="penv-env-display" error={shown.displayName} helperText="What people read.">
                <Input
                  id="penv-env-display"
                  value={form.displayName}
                  placeholder="Production EU"
                  disabled={busy}
                  onChange={(event) => edit({ displayName: event.target.value })}
                  data-testid="penv-env-display"
                />
              </FormField>
              <FormField
                label="Name"
                htmlFor="penv-env-name"
                error={shown.name}
                helperText={
                  editing
                    ? 'Used in commands. Renaming keeps every deployment: they refer to the environment, not its name.'
                    : 'Used in commands. One word, no spaces.'
                }
              >
                <Input
                  id="penv-env-name"
                  className="ppx__mono"
                  value={form.name}
                  placeholder="production-eu"
                  disabled={busy}
                  onChange={(event) => edit({ name: event.target.value })}
                  data-testid="penv-env-name"
                />
              </FormField>
            </div>
            <div className="penv-dialog__switches">
              <SwitchRow
                title="Production"
                description="Marked red everywhere. Verification never sends requests that change data here."
                checked={form.production}
                name="penv-env-production"
                onCheckedChange={(production) => edit({ production })}
              />
              <SwitchRow
                title="Contracts required"
                description="A version with no verified contract gets a “no” from can-i-deploy."
                checked={form.contractRequired}
                name="penv-env-contract-required"
                onCheckedChange={(contractRequired) => edit({ contractRequired })}
              />
            </div>
            <div className="ppx-settings__grid">
              <FormField label="Contact" htmlFor="penv-env-contact" error={shown.contactName}>
                <Input
                  id="penv-env-contact"
                  value={form.contactName}
                  placeholder="Platform team"
                  disabled={busy}
                  onChange={(event) => edit({ contactName: event.target.value })}
                  data-testid="penv-env-contact"
                />
              </FormField>
              <FormField label="Contact email" htmlFor="penv-env-email" error={shown.contactEmail}>
                <Input
                  id="penv-env-email"
                  type="email"
                  value={form.contactEmail}
                  placeholder="platform@acme.dev"
                  disabled={busy}
                  onChange={(event) => edit({ contactEmail: event.target.value })}
                  data-testid="penv-env-email"
                />
              </FormField>
            </div>
            {keptContacts ? (
              <p className="ppx__muted" data-testid="penv-env-kept">
                {form.otherContacts.length
                  ? `${plural(form.otherContacts.length, 'other contact')} ${form.otherContacts.length === 1 ? 'is' : 'are'} kept as ${form.otherContacts.length === 1 ? 'it is' : 'they are'}.`
                  : 'The contact’s other details are kept as they are.'}{' '}
                Change them through REST.
              </p>
            ) : null}
            {problem ? (
              <p className="ppx__error" role="alert" data-testid="penv-env-problem">
                {problem}
              </p>
            ) : null}
            <CommandBlock
              surfaces={pactCommandSurfaces(action)}
              unsupported={unsupportedLines(action)}
              footnote="Replace {tenant} with your workspace’s handle in the REST path."
              data-testid="penv-env-command"
            />
          </form>
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => void save()} disabled={busy} data-testid="penv-env-save">
            {editing ? <Save aria-hidden /> : <Plus aria-hidden />}
            {busy ? 'Saving…' : editing ? 'Save environment' : 'Create environment'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
