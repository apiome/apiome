'use client';

/**
 * **New pacticipant** — PFX-8.10 (#7307), opened from the Pacticipants list's header.
 *
 * Publishing a pact registers its consumer and provider; this dialog is for setting one up first:
 * **Name**, **Main branch**, **Owner**, **Repository** and **Start from a project**. Choosing a
 * project links it (its published versions can become provider contracts) and fills in an empty
 * name with the project's. Each field shows what REST would refuse before anything is sent; a taken
 * name (409) is shown under **Name**. The owner is assigned after the pacticipant is created; if
 * that fails the pacticipant still exists and the dialog says so, with the reason — nothing is
 * dropped silently. **The same, from anywhere** shows the form as
 * `apiome pact create-or-update-pacticipant`.
 *
 * Authority: `docs/mockups/contracts/pacticipant.html` (`#new-dialog`).
 */

import * as React from 'react';
import { Plus } from 'lucide-react';
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
import {
  createBody,
  handleOf,
  isSendable,
  pacticipantCommandAction,
  settingsProblems,
  type SettingsForm,
} from '@lib/pact-pacticipant-settings';
import type { Pacticipant } from '@lib/pact-pacticipants';
import type { Team } from '@lib/owners';
import { fetchProjects, type ProjectChoice } from '../pactPublish/publishApi';
import { assignOwner } from '../owners/ownersApi';
import { useTeams } from '../owners/useTeams';
import { PacticipantFields } from './PacticipantFields';
import { createPacticipant } from './pacticipantsApi';

/** The dialog's empty form: `main` is the usual main branch. */
export const NEW_FORM: SettingsForm = {
  name: '',
  displayName: '',
  mainBranch: 'main',
  repositoryUrl: '',
  projectId: '',
  labels: [],
};

/** Why the owner is not in the command block. */
export const OWNER_NOT_IN_CLI =
  'The owner is not carried by the command: run apiome teams assign pacticipant <id> --team <team> after it is created.';

/** Props for {@link NewPacticipantDialog}. */
export interface NewPacticipantDialogProps {
  open: boolean;
  onClose: () => void;
  /** Called with the new pacticipant (and a note when the owner could not be set). */
  onCreated: (pacticipant: Pacticipant, ownerProblem: string | null) => void;
  /** Starting values, for fixture renders. */
  initialForm?: SettingsForm;
  /** Projects to offer without reading them, for fixture renders. */
  initialProjects?: ProjectChoice[];
  /** Teams to offer without reading them, for fixture renders. */
  initialTeams?: Team[];
}

/**
 * The dialog.
 *
 * @param props - See {@link NewPacticipantDialogProps}.
 * @returns The dialog.
 */
export function NewPacticipantDialog({
  open,
  onClose,
  onCreated,
  initialForm,
  initialProjects,
  initialTeams,
}: NewPacticipantDialogProps) {
  const [form, setForm] = React.useState<SettingsForm>(initialForm ?? NEW_FORM);
  const [team, setTeam] = React.useState('');
  const [projects, setProjects] = React.useState<ProjectChoice[] | { error: string } | null>(
    initialProjects ?? null,
  );
  const [sent, setSent] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [problem, setProblem] = React.useState<string | null>(null);
  const [nameTaken, setNameTaken] = React.useState<string | null>(null);
  const loadedTeams = useTeams();
  const teams = initialTeams ?? loadedTeams.teams;

  React.useEffect(() => {
    if (!open || projects !== null) return;
    let live = true;
    void fetchProjects().then((answer) => {
      if (live) setProjects('error' in answer ? { error: answer.error } : answer);
    });
    return () => {
      live = false;
    };
  }, [open, projects]);

  React.useEffect(() => {
    if (open) return;
    setForm(initialForm ?? NEW_FORM);
    setTeam('');
    setSent(false);
    setProblem(null);
    setNameTaken(null);
  }, [initialForm, open]);

  const edit = (patch: Partial<SettingsForm>) => {
    setForm((current) => {
      const next = { ...current, ...patch };
      // Starting from a project names the pacticipant after it, unless a name is typed already.
      if (patch.projectId && !current.name.trim() && Array.isArray(projects)) {
        const project = projects.find((choice) => choice.id === patch.projectId);
        if (project) next.name = project.name;
      }
      return next;
    });
    if ('name' in patch) setNameTaken(null);
    setProblem(null);
  };

  const problems = settingsProblems(form);
  const shown = sent
    ? { ...problems, ...(nameTaken ? { name: nameTaken } : {}) }
    : nameTaken
      ? { name: nameTaken }
      : {};
  const handle = handleOf(form.name);

  const create = async () => {
    setSent(true);
    if (!isSendable(problems)) return;
    setBusy(true);
    setProblem(null);
    const answer = await createPacticipant(createBody(form));
    if ('error' in answer) {
      setBusy(false);
      if (answer.status === 409) setNameTaken(answer.error);
      else setProblem(answer.error);
      return;
    }
    let ownerProblem: string | null = null;
    if (team) {
      try {
        await assignOwner(team, [{ kind: 'pacticipant', id: answer.id }]);
      } catch (caught) {
        ownerProblem = `${answer.name} was created, but its owner could not be set: ${
          caught instanceof Error ? caught.message : 'the owners API did not answer'
        }. Set it on the Settings tab.`;
      }
    }
    setBusy(false);
    onCreated(answer, ownerProblem);
  };

  const action = pacticipantCommandAction(form, { tenant: '' });

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent data-testid="ppx-new-dialog">
        <DialogHeader>
          <DialogTitle>New pacticipant</DialogTitle>
          <DialogDescription>
            A service that provides or consumes an API. Publishing a pact creates one for you; this
            is for setting one up first.
          </DialogDescription>
        </DialogHeader>
        <DialogBody>
          <form
            className="ppx-settings__form"
            onSubmit={(event) => {
              event.preventDefault();
              void create();
            }}
            noValidate
          >
            <PacticipantFields
              form={form}
              onChange={edit}
              problems={shown}
              projects={projects}
              withLabels={false}
              withDisplayName={false}
              idPrefix="ppx-new"
              nameHint={
                handle
                  ? `Its handle will be ${handle}; URLs and CI name it by that.`
                  : 'The name pacts use.'
              }
              disabled={busy}
            />
            {teams.length ? (
              <FormField
                label="Owner"
                helperText="Gets failures, stale requests and re-publish asks."
                htmlFor="ppx-new-owner"
              >
                <select
                  id="ppx-new-owner"
                  className="ppx__select"
                  value={team}
                  disabled={busy}
                  onChange={(event) => setTeam(event.target.value)}
                  data-testid="ppx-new-owner"
                >
                  <option value="">No owner</option>
                  {teams.map((entry) => (
                    <option key={entry.slug} value={entry.slug}>
                      {entry.name}
                    </option>
                  ))}
                </select>
              </FormField>
            ) : null}
            {problem ? (
              <p className="ppx__error" role="alert" data-testid="ppx-new-problem">
                {problem}
              </p>
            ) : null}
            <CommandBlock
              surfaces={pactCommandSurfaces(action)}
              unsupported={[...unsupportedLines(action), ...(team ? [OWNER_NOT_IN_CLI] : [])]}
              footnote="Replace {tenant} with your workspace’s handle in the REST path."
              data-testid="ppx-new-command"
            />
          </form>
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => void create()} disabled={busy} data-testid="ppx-new-create">
            <Plus aria-hidden />
            {busy ? 'Creating…' : 'Create pacticipant'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
