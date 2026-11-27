'use client';

/**
 * Standing sources on **Publish a provider contract** — PFX-8.7 (#7304), built to
 * `docs/mockups/contracts/provider-contract.html`:
 *
 * - {@link FollowProjectToggle} — **Do this on every publish** on the *A project version* tab: each
 *   published version of the project becomes the provider's contract (drafts never do).
 * - {@link RepositoryFields} — the *Repository* tab: a registered repository, the file's path and the
 *   branch whose pushes publish it, the pushed commit being the provider version.
 * - {@link StandingSourcesNote} — under the provider: where its contract already comes from, any
 *   warning REST gives (no project bound, no push webhook, repository deleted), and a way to stop
 *   each source. Stopping a source stops new publishes only.
 */

import * as React from 'react';
import { Badge, Button, Checkbox, Input, Label } from '@/app/components/ui';
import {
  PUSH_EVIDENCE_NOTE,
  STOPS_NEW_ONLY,
  sourcesLines,
  type ContractSources,
  type RepositoryChoice,
} from '@lib/pact-contract-sources';
import type { ProviderContractForm } from '@lib/pact-provider-contract';

/**
 * **Do this on every publish**.
 *
 * @param props - Whether it is on, the project and provider it names, and the change handler.
 * @returns The option card.
 */
export function FollowProjectToggle({
  checked,
  projectName,
  providerName,
  onChange,
}: {
  checked: boolean;
  projectName: string | null;
  providerName: string;
  onChange: (checked: boolean) => void;
}) {
  const project = projectName ?? 'the project';
  const provider = providerName.trim() || 'the provider';
  return (
    <div className={checked ? 'ppc-follow is-active' : 'ppc-follow'} data-testid="ppc-follow">
      <Checkbox
        id="ppc-follow"
        checked={checked}
        onCheckedChange={(value) => onChange(value === true)}
        aria-describedby="ppc-follow-desc"
        className="ppc-follow__box"
      />
      <div className="ppc-follow__body">
        <div className="ppc-option__head">
          <Label htmlFor="ppc-follow" className="ppc-option__title">
            Do this on every publish
          </Label>
          <Badge variant="accent">Recommended</Badge>
        </div>
        <p className="ppc-option__desc" id="ppc-follow-desc">
          Each time a version of {project} is published, it becomes {provider}’s provider contract — drafts never do. You never come back to
          this page. Saved when you publish.
        </p>
      </div>
    </div>
  );
}

/**
 * The *Repository* tab's fields.
 *
 * @param props - The form, its editor, the repositories (or why they could not be read) and the hint renderer.
 * @returns The fields.
 */
export function RepositoryFields({
  form,
  edit,
  repositories,
  hint,
}: {
  form: ProviderContractForm;
  edit: (patch: Partial<ProviderContractForm>) => void;
  repositories: RepositoryChoice[] | null | { error: string };
  hint: (field: keyof ProviderContractForm) => React.ReactNode;
}) {
  const list = Array.isArray(repositories) ? repositories : [];
  return (
    <>
      {repositories && 'error' in repositories ? <p className="ppub-hint ppub-hint--danger">{repositories.error}</p> : null}
      <div className="ppub-grid">
        <div className="ppub-field">
          <Label htmlFor="ppc-repository">Repository</Label>
          <select
            id="ppc-repository"
            className="ppub-select"
            value={form.repositoryId}
            onChange={(event) => {
              const chosen = list.find((repo) => repo.id === event.target.value);
              edit({ repositoryId: event.target.value, repositoryBranch: form.repositoryBranch || chosen?.defaultBranch || '' });
            }}
          >
            <option value="">{repositories === null ? 'Loading repositories…' : list.length ? 'Choose a repository' : 'No repository is registered'}</option>
            {list.map((repo) => (
              <option key={repo.id} value={repo.id} disabled={!repo.readable}>
                {repo.fullName}
                {repo.readable ? '' : ` — ${repo.provider}: only GitHub files can be read on a push`}
              </option>
            ))}
          </select>
          {hint('repositoryId')}
        </div>
        <div className="ppub-field">
          <Label htmlFor="ppc-repository-path">Path</Label>
          <Input
            id="ppc-repository-path"
            className="ppx__mono"
            value={form.repositoryPath}
            maxLength={1024}
            placeholder="openapi/billing.yaml"
            onChange={(event) => edit({ repositoryPath: event.target.value })}
          />
          {hint('repositoryPath')}
        </div>
        <div className="ppub-field">
          <Label htmlFor="ppc-repository-branch">Branch</Label>
          <Input
            id="ppc-repository-branch"
            value={form.repositoryBranch}
            maxLength={255}
            placeholder="main"
            onChange={(event) => edit({ repositoryBranch: event.target.value })}
          />
          {hint('repositoryBranch')}
        </div>
      </div>
      <p className="ppub-hint">
        Published on every push to {form.repositoryBranch.trim() || 'the branch'}, with the commit as the provider version. The repository needs
        a push webhook; register one on its page. Nothing is published until the next push.
      </p>
      <p className="ppc-callout" data-testid="ppc-push-evidence">
        {PUSH_EVIDENCE_NOTE}
      </p>
    </>
  );
}

/**
 * Where a provider's contract already comes from, with a way to stop each source.
 *
 * @param props - The sources (`null` while none is known), whether a change is being saved, and the stop handlers.
 * @returns The note, or nothing when no source is on and REST has no warning.
 */
export function StandingSourcesNote({
  sources,
  busy,
  onStopProject,
  onStopRepository,
}: {
  sources: ContractSources | null;
  busy: boolean;
  onStopProject: () => void;
  onStopRepository: () => void;
}) {
  if (!sources) return null;
  const lines = sourcesLines(sources);
  if (!lines.length && !sources.warnings.length) return null;
  return (
    <div className="ppc-standing" role="status" data-testid="ppc-standing">
      <p className="ppub-caps">Published automatically</p>
      <ul className="ppc-standing__list">
        {lines.map((line) => (
          <li key={line} className="ppc-standing__line">
            {line}
          </li>
        ))}
        {sources.warnings.map((warning) => (
          <li key={warning} className="ppc-standing__line ppc-standing__line--warn">
            {warning}
          </li>
        ))}
      </ul>
      <div className="ppub-row-actions">
        {sources.onProjectPublish ? (
          <Button type="button" variant="outline" size="sm" disabled={busy} onClick={onStopProject} data-testid="ppc-stop-project">
            Stop publishing each version
          </Button>
        ) : null}
        {sources.repository ? (
          <Button type="button" variant="outline" size="sm" disabled={busy} onClick={onStopRepository} data-testid="ppc-stop-repository">
            Stop following {sources.repository.path}
          </Button>
        ) : null}
      </div>
      <p className="ppub-hint">{STOPS_NEW_ONLY}</p>
    </div>
  );
}
