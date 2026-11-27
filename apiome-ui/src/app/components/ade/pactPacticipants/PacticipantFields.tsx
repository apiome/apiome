'use client';

/**
 * The fields of a pacticipant — PFX-8.10 (#7307), shared by the **Settings** tab and the **New
 * pacticipant** dialog: **Name**, **Display name**, **Main branch**, **Repository**, **Linked
 * project** and **Labels**. Each field shows the problem REST would refuse it for
 * (`settingsProblems`) before anything is sent. A read-only role gets {@link PacticipantValues}
 * instead: the same values, without inputs.
 *
 * Authority: `docs/mockups/contracts/pacticipant.html` (Settings → General).
 */

import * as React from 'react';
import { X } from 'lucide-react';
import { Button, FormField, Input } from '@/app/components/ui';
import type { ProjectChoice } from '../pactPublish/publishApi';
import {
  labelProblem,
  type SettingsField,
  type SettingsForm,
  type SettingsProblems,
} from '@lib/pact-pacticipant-settings';

/** Props for {@link PacticipantFields}. */
export interface PacticipantFieldsProps {
  /** The form. */
  form: SettingsForm;
  /** Change some fields. */
  onChange: (patch: Partial<SettingsForm>) => void;
  /** The problems to show, by field (only the touched ones, or all after a send). */
  problems: SettingsProblems;
  /** The workspace's projects for **Linked project**; `null` while loading; an error hides the list. */
  projects: ProjectChoice[] | { error: string } | null;
  /** Show **Labels** (the New dialog leaves them for Settings). */
  withLabels?: boolean;
  /** Show **Display name** (the New dialog keeps to the mockup's four fields). */
  withDisplayName?: boolean;
  /** Prefix of the input ids, unique on the page. */
  idPrefix: string;
  /** Under **Name**: what renaming does (Settings) or what the handle will be (New). */
  nameHint: string;
  /** Disable every input while a save runs. */
  disabled?: boolean;
}

/**
 * The project select's options: none, then the projects by name. A linked project that is not in
 * the list (another page of projects, or no permission to list them) is kept as its id.
 *
 * @param projects - The loaded projects.
 * @param current - The linked project's id.
 * @returns The options.
 */
function projectOptions(
  projects: PacticipantFieldsProps['projects'],
  current: string,
): ProjectChoice[] {
  const list = Array.isArray(projects) ? projects : [];
  if (current && !list.some((project) => project.id === current)) {
    return [{ id: current, name: `Project ${current.slice(0, 8)}…`, slug: current }, ...list];
  }
  return list;
}

/**
 * The label chips with their remove buttons, and **Add a label** (Enter or **Add**).
 *
 * @param props - The labels, the change callback, the input id and whether it is disabled.
 * @returns The editor.
 */
function LabelsEditor({
  labels,
  onChange,
  id,
  disabled,
}: {
  labels: string[];
  onChange: (labels: string[]) => void;
  id: string;
  disabled?: boolean;
}) {
  const [draft, setDraft] = React.useState('');
  const [problem, setProblem] = React.useState<string | null>(null);

  const add = () => {
    const label = draft.trim();
    const why = labelProblem(label, 'label');
    if (why) {
      setProblem(why);
      return;
    }
    if (!labels.includes(label)) onChange([...labels, label]);
    setDraft('');
    setProblem(null);
  };

  return (
    <div className="ppx-settings__labels" data-testid="ppx-settings-labels">
      {labels.length ? (
        <ul className="ppx__chips" aria-label="Labels">
          {labels.map((label) => (
            <li key={label} className="ppx-settings__chip">
              <span>{label}</span>
              <button
                type="button"
                className="ppx-settings__chip-remove"
                aria-label={`Remove the label ${label}`}
                onClick={() => onChange(labels.filter((item) => item !== label))}
                disabled={disabled}
              >
                <X aria-hidden />
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="ppx__meta">No labels.</p>
      )}
      <div className="ppx-settings__label-add">
        <Input
          id={id}
          value={draft}
          placeholder="Add a label"
          aria-label="Add a label"
          disabled={disabled}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.preventDefault();
              add();
            }
          }}
          data-testid="ppx-settings-label-input"
        />
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={add}
          disabled={disabled || !draft.trim()}
        >
          Add
        </Button>
      </div>
      {problem ? (
        <p className="ppx__error" role="alert">
          {problem}
        </p>
      ) : null}
    </div>
  );
}

/**
 * The editable fields.
 *
 * @param props - See {@link PacticipantFieldsProps}.
 * @returns The fields in a two-column grid, then the labels.
 */
export function PacticipantFields({
  form,
  onChange,
  problems,
  projects,
  withLabels = true,
  withDisplayName = true,
  idPrefix,
  nameHint,
  disabled,
}: PacticipantFieldsProps) {
  const id = (field: SettingsField | 'project') => `${idPrefix}-${field}`;
  return (
    <div className="ppx-settings__fields">
      <div className="ppx-settings__grid">
        <FormField
          label="Name"
          required
          helperText={nameHint}
          error={problems.name}
          htmlFor={id('name')}
        >
          <Input
            id={id('name')}
            value={form.name}
            disabled={disabled}
            placeholder="Billing Service"
            onChange={(event) => onChange({ name: event.target.value })}
            data-testid={`${idPrefix}-name`}
          />
        </FormField>
        {withDisplayName ? (
          <FormField
            label="Display name"
            helperText="What people read, when it differs from the name. Pacts never use it."
            error={problems.displayName}
            htmlFor={id('displayName')}
          >
            <Input
              id={id('displayName')}
              value={form.displayName}
              disabled={disabled}
              onChange={(event) => onChange({ displayName: event.target.value })}
              data-testid={`${idPrefix}-display-name`}
            />
          </FormField>
        ) : null}
        <FormField
          label="Main branch"
          helperText="“Latest on main” selectors read this."
          error={problems.mainBranch}
          htmlFor={id('mainBranch')}
        >
          <Input
            id={id('mainBranch')}
            value={form.mainBranch}
            disabled={disabled}
            placeholder="main"
            onChange={(event) => onChange({ mainBranch: event.target.value })}
            data-testid={`${idPrefix}-main-branch`}
          />
        </FormField>
        <FormField label="Repository" error={problems.repositoryUrl} htmlFor={id('repositoryUrl')}>
          <Input
            id={id('repositoryUrl')}
            value={form.repositoryUrl}
            disabled={disabled}
            placeholder="https://github.com/acme/billing"
            onChange={(event) => onChange({ repositoryUrl: event.target.value })}
            data-testid={`${idPrefix}-repository`}
          />
        </FormField>
        <FormField
          label="Linked project"
          helperText={
            projects && !Array.isArray(projects)
              ? `The projects could not be listed: ${projects.error}`
              : 'A linked project’s published versions can become provider contracts.'
          }
          htmlFor={id('project')}
        >
          <select
            id={id('project')}
            className="ppx__select"
            value={form.projectId}
            disabled={disabled || projects === null}
            onChange={(event) => onChange({ projectId: event.target.value })}
            data-testid={`${idPrefix}-project`}
          >
            <option value="">None — not described by a project</option>
            {projectOptions(projects, form.projectId).map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </select>
        </FormField>
      </div>
      {withLabels ? (
        <FormField label="Labels" error={problems.labels} htmlFor={id('labels')}>
          <LabelsEditor
            id={id('labels')}
            labels={form.labels}
            onChange={(labels) => onChange({ labels })}
            disabled={disabled}
          />
        </FormField>
      ) : null}
    </div>
  );
}

/**
 * The same values for a role that cannot edit them: text, no inputs.
 *
 * @param props - The form and the name of the linked project, when it is known.
 * @returns A description list.
 */
export function PacticipantValues({
  form,
  projectName,
}: {
  form: SettingsForm;
  projectName: string | null;
}) {
  const rows: Array<[string, React.ReactNode]> = [
    ['Name', form.name],
    ['Display name', form.displayName || '—'],
    ['Main branch', form.mainBranch || '—'],
    ['Repository', form.repositoryUrl || '—'],
    ['Linked project', form.projectId ? (projectName ?? form.projectId) : 'None'],
    ['Labels', form.labels.length ? form.labels.join(', ') : 'None'],
  ];
  return (
    <dl className="ppx__facts" data-testid="ppx-settings-values">
      {rows.map(([term, value]) => (
        <div key={term} className="ppx__fact">
          <dt>{term}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}
