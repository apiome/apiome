'use client';

/**
 * The repository's PR-back settings card — REPO-5.8 (#2793).
 *
 * PR-back renders a project version and opens a pull request into the repository files the
 * project was imported from. Whether a project may is the **repository's** decision, made here:
 *
 * - **Which projects** — an allow list (only the ticked projects) or a deny list (every project
 *   except the ticked ones). Until the card is saved, no project may: PR-back is opt-in.
 * - **Target branch** — where the pull requests merge; blank for the branch the files were
 *   imported from.
 * - **Commit message** — a template over `{{project}}`, `{{version}}`, `{{repository}}`,
 *   `{{branch}}` and `{{fileCount}}`; blank for the default.
 * - **Reviewers** — GitHub logins or `org/team` slugs requested on every pull request PR-back
 *   opens.
 *
 * Reads and writes go through `/api/repositories/{id}/pr-back-settings`; apiome-rest enforces
 * `imports:edit`, validates every field and audits the save. The card re-renders from what the
 * server returns, so it cannot drift from stored state.
 */

import * as React from 'react';

import { Alert } from '@/app/components/ui/Alert';
import { Badge } from '@/app/components/ui/Badge';
import { Button } from '@/app/components/ui/Button';
import { Card, CardContent } from '@/app/components/ui/Card';
import { Input } from '@/app/components/ui/Input';
import { Label } from '@/app/components/ui/Label';
import {
  PR_BACK_POLICY_COPY,
  parsePrBackSettings,
  parseReviewers,
  settingsSummary,
  type PrBackPolicy,
  type PrBackSettings,
} from '@lib/pr-back';

export interface RepositoryPrBackSettingsProps {
  /** The repository being configured. */
  repositoryId: string;
}

/** A project the card can list. */
interface ProjectOption {
  id: string;
  name: string;
}

const LOAD_ERROR = 'Could not load the PR-back settings. Reload the page to try again.';
const SAVE_ERROR = 'The settings could not be saved. Try again.';
const POLICIES: readonly PrBackPolicy[] = ['allow', 'deny'];

/** The editable form state. */
interface FormState {
  policy: PrBackPolicy;
  projectIds: string[];
  targetBranch: string;
  template: string;
  reviewers: string;
}

function formFrom(settings: PrBackSettings): FormState {
  return {
    policy: settings.projectPolicy,
    projectIds: settings.projects.map((p) => p.id),
    targetBranch: settings.targetBranch ?? '',
    template: settings.commitMessageTemplate ?? '',
    reviewers: settings.reviewers.join(', '),
  };
}

/**
 * Render the PR-back card. See {@link RepositoryPrBackSettingsProps}.
 *
 * @returns The card.
 */
export function RepositoryPrBackSettings({ repositoryId }: RepositoryPrBackSettingsProps): React.JSX.Element {
  const [settings, setSettings] = React.useState<PrBackSettings | null>(null);
  const [form, setForm] = React.useState<FormState | null>(null);
  const [projects, setProjects] = React.useState<ProjectOption[]>([]);
  const [error, setError] = React.useState<string | null>(null);
  const [saving, setSaving] = React.useState(false);
  const [saved, setSaved] = React.useState(false);

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [settingsResponse, projectsResponse] = await Promise.all([
          fetch(`/api/repositories/${encodeURIComponent(repositoryId)}/pr-back-settings`),
          fetch('/api/projects'),
        ]);
        const payload = await settingsResponse.json().catch(() => null);
        const parsed = settingsResponse.ok ? parsePrBackSettings(payload) : null;
        const projectPayload = (await projectsResponse.json().catch(() => null)) as {
          projects?: Array<{ id?: unknown; name?: unknown }>;
        } | null;
        if (cancelled) return;
        if (!parsed) {
          setError((payload as { error?: string } | null)?.error || LOAD_ERROR);
          return;
        }
        setSettings(parsed);
        setForm(formFrom(parsed));
        setProjects(
          (projectPayload?.projects ?? []).flatMap((p) =>
            typeof p.id === 'string' ? [{ id: p.id, name: typeof p.name === 'string' ? p.name : p.id }] : [],
          ),
        );
      } catch {
        if (!cancelled) setError(LOAD_ERROR);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [repositoryId]);

  const update = (patch: Partial<FormState>) => {
    setSaved(false);
    setForm((current) => (current ? { ...current, ...patch } : current));
  };

  const toggleProject = (id: string, checked: boolean) => {
    if (!form) return;
    update({
      projectIds: checked ? [...form.projectIds, id] : form.projectIds.filter((projectId) => projectId !== id),
    });
  };

  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!form) return;
    setSaving(true);
    setError(null);
    try {
      const response = await fetch(`/api/repositories/${encodeURIComponent(repositoryId)}/pr-back-settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          projectPolicy: form.policy,
          projectIds: form.projectIds,
          targetBranch: form.targetBranch,
          commitMessageTemplate: form.template,
          reviewers: parseReviewers(form.reviewers),
        }),
      });
      const payload = await response.json().catch(() => null);
      const parsed = response.ok ? parsePrBackSettings(payload) : null;
      if (!parsed) {
        setError((payload as { error?: string } | null)?.error || SAVE_ERROR);
      } else {
        setSettings(parsed);
        setForm(formFrom(parsed));
        setSaved(true);
      }
    } catch {
      setError(SAVE_ERROR);
    } finally {
      setSaving(false);
    }
  };

  // Listed projects that the picker does not show (deleted, or catalog items) stay visible.
  const extra = (settings?.projects ?? []).filter((p) => !projects.some((option) => option.id === p.id));

  return (
    <Card data-testid="repository-settings-pr-back">
      <CardContent className="prb-card">
        <div className="prb-card__head">
          <h3 className="repo-det-card__title">Pull requests back to this repository</h3>
          {settings ? (
            <Badge variant={settings.configured ? 'ok' : 'outline'} data-testid="pr-back-configured">
              {settings.configured ? 'On' : 'Off'}
            </Badge>
          ) : null}
        </div>
        <p className="repo-det-note">
          Apiome can render a project version and open a pull request into the files it was imported from. Choose
          which projects may, where the pull requests go and who reviews them.
        </p>

        {error ? (
          <Alert variant="error" data-testid="pr-back-settings-error">
            {error}
          </Alert>
        ) : null}

        {settings && form ? (
          <form className="prb-form" onSubmit={(event) => void save(event)} data-testid="pr-back-settings-form">
            <p className="prb-summary" data-testid="pr-back-settings-summary">
              {settingsSummary(settings)}
            </p>

            <fieldset className="prb-fieldset">
              <legend className="prb-legend">Projects that may open pull requests</legend>
              {POLICIES.map((policy) => (
                <label key={policy} className="prb-choice">
                  <input
                    type="radio"
                    name={`pr-back-policy-${repositoryId}`}
                    value={policy}
                    checked={form.policy === policy}
                    onChange={() => update({ policy })}
                    data-testid={`pr-back-policy-${policy}`}
                  />
                  <span className="prb-choice__text">
                    <span className="prb-choice__label">{PR_BACK_POLICY_COPY[policy].label}</span>
                    <span className="prb-note">{PR_BACK_POLICY_COPY[policy].description}</span>
                  </span>
                </label>
              ))}
              {projects.length + extra.length === 0 ? (
                <p className="prb-note">This workspace has no projects yet.</p>
              ) : (
                <ul className="prb-projects" aria-label="Projects">
                  {[...projects, ...extra.map((p) => ({ id: p.id, name: p.name ?? `Deleted project ${p.id}` }))].map(
                    (project) => (
                      <li key={project.id}>
                        <label className="prb-check">
                          <input
                            type="checkbox"
                            checked={form.projectIds.includes(project.id)}
                            onChange={(event) => toggleProject(project.id, event.target.checked)}
                            data-testid="pr-back-project"
                          />
                          {project.name}
                        </label>
                      </li>
                    ),
                  )}
                </ul>
              )}
            </fieldset>

            <div className="prb-grid">
              <div className="prb-field">
                <Label htmlFor={`pr-back-branch-${repositoryId}`}>Target branch</Label>
                <Input
                  id={`pr-back-branch-${repositoryId}`}
                  className="mono"
                  value={form.targetBranch}
                  placeholder="Branch the files came from"
                  onChange={(event) => update({ targetBranch: event.target.value })}
                  data-testid="pr-back-target-branch"
                />
              </div>
              <div className="prb-field">
                <Label htmlFor={`pr-back-reviewers-${repositoryId}`}>Reviewers</Label>
                <Input
                  id={`pr-back-reviewers-${repositoryId}`}
                  className="mono"
                  value={form.reviewers}
                  placeholder="octocat, acme/api-reviewers"
                  onChange={(event) => update({ reviewers: event.target.value })}
                  data-testid="pr-back-reviewers"
                />
              </div>
              <div className="prb-field prb-field--wide">
                <Label htmlFor={`pr-back-template-${repositoryId}`}>Commit message</Label>
                <Input
                  id={`pr-back-template-${repositoryId}`}
                  className="mono"
                  value={form.template}
                  placeholder={settings.defaultCommitMessageTemplate}
                  onChange={(event) => update({ template: event.target.value })}
                  data-testid="pr-back-template"
                />
                <p className="prb-note">
                  Use <span className="mono">{'{{project}}'}</span>, <span className="mono">{'{{version}}'}</span>,{' '}
                  <span className="mono">{'{{repository}}'}</span>, <span className="mono">{'{{branch}}'}</span> and{' '}
                  <span className="mono">{'{{fileCount}}'}</span>. Leave blank for the default.
                </p>
              </div>
            </div>

            <div className="prb-form__actions">
              <Button type="submit" variant="primary" size="sm" disabled={saving} data-testid="pr-back-save">
                {saving ? 'Saving…' : 'Save PR-back settings'}
              </Button>
              <span aria-live="polite" className="prb-note">
                {saved ? 'Saved.' : ''}
              </span>
            </div>
          </form>
        ) : null}
      </CardContent>
    </Card>
  );
}

export default RepositoryPrBackSettings;
